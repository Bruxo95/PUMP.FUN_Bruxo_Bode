"""Carteiras em estudo (0.14.0): perfil (ganho por minuto/hora/dia), gravação das operações e rotas por usuário."""
import asyncio
import time
from datetime import datetime, timezone

from tests.test_api import UA, UB, W, env, tok  # noqa: F401  (fixture env)


def test_profile_from_positions_and_from_live_trades():
    from app.study import compact_position, from_positions, from_trades, profile
    now = time.time()
    raw = [{"token": f"T{i}", "meta": {"symbol": f"S{i}", "primaryMarket": "pumpfun"}, "invested": 100.0,
            "pnl": {"realized": 48.0 if i < 3 else -24.0}, "roi": 48.0, "counts": {"buys": 1, "sells": 1},
            "timing": {"firstBuy": (now - 1800) * 1000, "lastSell": (now - 600) * 1000, "holdTimeSecs": 90}}
           for i in range(4)]
    rows = [compact_position(p) for p in raw] + [compact_position({"nada": 1})]
    m = from_positions(rows, now)
    assert m["closed"] == 4 and m["pnl_24h"] == 120.0 and m["pnl_1h"] == 120.0
    assert m["per_hour"] == 5.0 and abs(m["per_min"] - 120 / 1440) < 1e-3 and m["win_rate"] == 0.75
    assert m["hold_med_s"] == 90 and m["best"][0]["realized"] == 48.0
    trades = [{"mint": "A", "side": "buy", "sol": 1.0, "tokens": 100, "at": datetime.fromtimestamp(now - 300, timezone.utc).isoformat()},
              {"mint": "A", "side": "sell", "sol": 1.5, "tokens": 100, "at": datetime.fromtimestamp(now - 60, timezone.utc).isoformat()}]
    lv = from_trades(trades, now)
    assert lv["closed"] == 1 and abs(lv["pnl_24h"] - 0.5) < 1e-9 and lv["win_rate"] == 1.0
    p = profile("W", [{"data": r} for r in rows if r], trades, now)
    assert p["main"]["closed"] == 4 and p["live"]["closed"] == 1 and p["trades_seen"] == 2


def test_study_routes_are_per_user_and_record_trades(env):
    c, hub, db = env["c"], env["hub"], env["db"]
    A, B = tok(UA), tok(UB, "b@x.com")
    assert c.post("/api/pump/study", json={"wallet": "x;drop", "action": "add"}, headers=A).json()["error"]
    r = c.post("/api/pump/study", json={"wallet": W, "action": "add", "apelido": "baleia"}, headers=A).json()
    assert r["ok"]
    lst = c.get("/api/pump/study", headers=A).json()
    assert [x["wallet"] for x in lst["wallets"]] == [W] and lst["wallets"][0]["apelido"] == "baleia"
    assert c.get("/api/pump/study", headers=B).json()["wallets"] == []                   # B não vê a lista de A
    assert c.get(f"/api/pump/study/{W}", headers=B).json()["error"]                       # nem o perfil
    hub.record_trade(W, {"signature": "SIG1", "txType": "buy", "mint": "M1", "solAmount": 1.0, "tokenAmount": 10,
                         "marketCapSol": 50.0, "blockTime": int(time.time())})
    hub.record_trade(W, {"signature": "SIG1", "txType": "buy", "mint": "M1", "solAmount": 1.0, "tokenAmount": 10})
    asyncio.run(hub.flush_trades())
    assert len(db.tables["wallet_trades"]) == 1                                            # mesma assinatura: 1 linha
    prof = c.get(f"/api/pump/study/{W}", headers=A).json()
    assert prof["trades_seen"] == 1 and prof["recent"][0]["mint"] == "M1"
    assert c.post("/api/pump/study", json={"wallet": W, "action": "remove"}, headers=A).json()["ok"]
    assert c.get("/api/pump/study", headers=A).json()["wallets"] == []
    assert c.get("/api/pump/study").status_code == 401


def test_study_without_tables_does_not_break(env):
    c, db = env["c"], env["db"]
    for t in ("study_wallets", "wallet_trades", "study_positions"):
        del db.tables[t]
    r = c.get("/api/pump/study", headers=tok(UA))
    assert r.status_code == 200 and "não criadas" in r.json()["error"]
