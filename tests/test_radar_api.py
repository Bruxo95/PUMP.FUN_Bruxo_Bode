"""Radar: autorização, configurações e alertas ao vivo sem cópia ou rede real."""
import asyncio
import time
from datetime import datetime

import pytest

from tests.test_api import UA, UB, W, W2, env, tok  # noqa: F401 (fixture env)


MINT = "Radar".ljust(40, "1") + "pump"


def add_study(c, headers, wallet):
    result = c.post("/api/pump/study", json={"wallet": wallet, "action": "add"}, headers=headers)
    assert result.status_code == 200 and result.json()["ok"]


def radar(c, headers):
    result = c.get("/api/pump/radar", headers=headers)
    assert result.status_code == 200
    return result.json()


def record(hub, wallet, signature, side="buy", sol=1.0):
    hub.record_trade(wallet, {"signature": signature, "txType": side, "mint": MINT,
                              "solAmount": sol, "tokenAmount": 1000.0, "blockTime": time.time()})


def radar_events(pf):
    return [e for e in pf.events if "radar" in e["msg"].lower()]


def test_radar_requires_login_and_settings_are_private_and_persistent(env):
    c, hub, db = env["c"], env["hub"], env["db"]
    a, b = tok(UA), tok(UB, "b@x.com")
    assert c.get("/api/pump/radar").status_code == 401
    initial = radar(c, a)
    assert initial["enabled"] is False and initial["min_wallets"] == 2 and initial["window_min"] == 5
    assert initial["waves"] == [] and initial["wallet_count"] == 0
    settings = {"pump_radar_enabled": True, "pump_radar_min_wallets": 3, "pump_radar_window_min": 10}
    result = c.post("/api/pump/settings", json=settings, headers=a).json()
    assert result["applied"] == settings and result["errors"] == {}
    saved = next(row["settings"] for row in db.tables["user_settings"] if row["user_id"] == UA)
    assert all(saved[key] == value for key, value in settings.items())
    assert radar(c, b)["enabled"] is False
    hub.engines.pop(UA)  # motor recarrega a configuração já persistida
    reloaded = radar(c, a)
    assert reloaded["enabled"] is True and reloaded["min_wallets"] == 3 and reloaded["window_min"] == 10


@pytest.mark.parametrize("key,value", [
    ("pump_radar_min_wallets", 1), ("pump_radar_min_wallets", 31),
    ("pump_radar_min_wallets", 2.5), ("pump_radar_min_wallets", True),
    ("pump_radar_window_min", 0), ("pump_radar_window_min", 31),
    ("pump_radar_window_min", 1.5), ("pump_radar_window_min", "1e1000"),
    ("pump_radar_enabled", "qualquer coisa"),
])
def test_radar_rejects_invalid_options_without_changing_them(env, key, value):
    c, headers = env["c"], tok(UA)
    before = radar(c, headers)
    result = c.post("/api/pump/settings", json={key: value}, headers=headers).json()
    assert key in result["errors"] and key not in result["applied"]
    after = radar(c, headers)
    assert (after["enabled"], after["min_wallets"], after["window_min"]) == (
        before["enabled"], before["min_wallets"], before["window_min"])


def test_radar_counts_only_the_authenticated_users_study_wallets(env):
    c, hub = env["c"], env["hub"]
    a, b = tok(UA), tok(UB, "b@x.com")
    for wallet in (W, W2):
        add_study(c, a, wallet)
    add_study(c, b, W)
    for headers in (a, b):
        assert c.post("/api/pump/settings", json={"pump_radar_enabled": True}, headers=headers).json()["applied"]
    record(hub, W, "r-a")
    record(hub, W2, "r-b")
    visible = radar(c, a)
    assert visible["wallet_count"] == 2 and len(visible["waves"]) == 1
    wave = visible["waves"][0]
    assert wave["mint"] == MINT and wave["wallet_count"] == 2 and wave["buy_count"] == 2
    assert {w["wallet"] for w in wave["wallets"]} == {W, W2}
    assert wave["status"] == "accumulating" and wave["seller_count"] == 0
    private = c.get("/api/pump/radar?user_id=" + UA, headers=b).json()
    assert private["wallet_count"] == 1 and private["waves"] == []
    pa, pb = hub.engines[UA], hub.engines[UB]
    assert len(radar_events(pa)) == 1 and radar_events(pb) == []
    assert pa.positions() == pb.positions() == [] and pa.trades() == pb.trades() == []
    assert not pa.cfg.pump_real_enabled and not pb.cfg.pump_real_enabled
    assert (pa._rq is None or pa._rq.empty()) and (pb._rq is None or pb._rq.empty())


def test_radar_alerts_once_per_wave_and_first_sale_then_honors_off_and_removal(env):
    c, hub = env["c"], env["hub"]
    headers = tok(UA)
    for wallet in (W, W2):
        add_study(c, headers, wallet)
    c.post("/api/pump/settings", json={"pump_radar_enabled": True}, headers=headers)
    pf = hub.engines[UA]
    record(hub, W, "wave-1")
    record(hub, W, "wave-1")  # reconexão não conta a operação duas vezes
    assert radar(c, headers)["waves"] == [] and radar_events(pf) == []
    record(hub, W2, "wave-2")
    assert radar(c, headers)["waves"][0]["buy_count"] == 2 and len(radar_events(pf)) == 1
    record(hub, W, "wave-3")
    radar(c, headers)
    radar(c, headers)
    assert len(radar_events(pf)) == 1  # polling e compra extra não repetem o aviso
    record(hub, W, "wave-sale-1", "sell", 0.4)
    wave = radar(c, headers)["waves"][0]
    assert wave["status"] == "selling" and wave["seller_count"] == 1 and wave["sell_count"] == 1
    assert wave["sell_sol"] == 0.4 and 0 < wave["buy_pressure"] < 100
    assert len(radar_events(pf)) == 2
    record(hub, W2, "wave-sale-2", "sell", 0.2)
    assert len(radar_events(pf)) == 2
    c.post("/api/pump/settings", json={"pump_radar_enabled": False}, headers=headers)
    before = len(radar_events(pf))
    record(hub, W2, "off-buy")
    assert radar(c, headers)["waves"] == [] and len(radar_events(pf)) == before
    c.post("/api/pump/settings", json={"pump_radar_enabled": True}, headers=headers)
    result = c.post("/api/pump/study", json={"wallet": W2, "action": "remove"}, headers=headers).json()
    assert result["ok"]
    before = len(radar_events(pf))
    record(hub, W2, "removed-buy")
    assert radar(c, headers)["wallet_count"] == 1 and radar(c, headers)["waves"] == []
    assert len(radar_events(pf)) == before


def test_radar_poll_does_not_query_history_providers(env):
    c, db = env["c"], env["db"]
    headers = tok(UA)
    radar(c, headers)  # carrega o motor antes da medição
    db.calls.clear()
    for _ in range(3):
        radar(c, headers)
    assert not any(call[1] in {"wallet_trades", "study_positions"} for call in db.calls)


def test_old_study_trades_are_saved_even_when_outside_radar_retention(env):
    c, hub, db = env["c"], env["hub"], env["db"]
    headers = tok(UA)
    for wallet in (W, W2):
        add_study(c, headers, wallet)
    c.post("/api/pump/settings", json={"pump_radar_enabled": True}, headers=headers)
    old_at = time.time() - 3600
    for wallet, signature in ((W, "old-study-a"), (W2, "old-study-b")):
        hub.record_trade(wallet, {"signature": signature, "txType": "buy", "mint": MINT,
                                  "solAmount": 1.0, "tokenAmount": 1000.0, "blockTime": old_at})
    observed = radar(c, headers)
    assert observed["waves"] == [] and observed["event_count"] == 0
    assert radar_events(hub.engines[UA]) == []
    asyncio.run(hub.flush_trades())
    assert {row["signature"] for row in db.tables["wallet_trades"]} == {"old-study-a", "old-study-b"}
    assert all(datetime.fromisoformat(row["at"]).timestamp() == pytest.approx(old_at)
               for row in db.tables["wallet_trades"])


def test_shared_signature_does_not_poison_study_upsert_or_erase_radar_participants(env):
    c, hub, db = env["c"], env["hub"], env["db"]
    headers = tok(UA)
    for wallet in (W, W2):
        add_study(c, headers, wallet)
    c.post("/api/pump/settings", json={"pump_radar_enabled": True}, headers=headers)
    record(hub, W, "shared-signature")
    record(hub, W2, "shared-signature")
    assert radar(c, headers)["waves"][0]["wallet_count"] == 2
    insert = db.insert
    checked_batches = []

    async def insert_rejecting_duplicate_signatures(table, rows, **kwargs):
        if table == "wallet_trades":
            batch = rows if isinstance(rows, list) else [rows]
            signatures = [row["signature"] for row in batch]
            checked_batches.append(signatures)
            # PostgreSQL não aceita atingir a mesma PK duas vezes em um upsert de lote.
            assert len(signatures) == len(set(signatures))
        return await insert(table, rows, **kwargs)

    db.insert = insert_rejecting_duplicate_signatures
    asyncio.run(hub.flush_trades())
    assert checked_batches == [["shared-signature"]] and hub._trade_q == []
    stored = db.tables["wallet_trades"]
    assert len(stored) == 1 and stored[0]["wallet"] == W2  # limite do histórico existente: PK(signature)
    wave = radar(c, headers)["waves"][0]
    assert wave["wallet_count"] == 2 and {row["wallet"] for row in wave["wallets"]} == {W, W2}
