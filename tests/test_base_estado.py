"""Base da pump.fun não some quando o servidor reinicia e mostra as suas compras da tela (0.24.0)."""
import asyncio
import time
from datetime import datetime, timezone

from tests.test_api import UA, env, tok  # noqa: F401  (fixture env)

M1 = "Vivo".ljust(40, "1") + "pump"
M2 = "Compra".ljust(40, "1") + "pump"


def test_live_tokens_and_recent_list_survive_a_restart(env):
    c, hub, db = env["c"], env["hub"], env["db"]
    t0 = time.time() - 600
    hub.lab.on_create({"mint": M1, "marketCapSol": 30.0, "symbol": "VIVO"}, t0)
    hub.lab.live[M1]["snaps"] = {"1": 50.0, "5": 70.0}
    old = hub.lab.live.pop(M2, None)
    assert old is None
    hub.lab.on_create({"mint": M2, "marketCapSol": 30.0, "symbol": "GRAD"}, t0)
    hub.lab.finalize(hub.lab.live[M2], True, time.time())
    asyncio.run(hub.save_lab())
    assert db.tables["lab_state"][0]["data"]["live"][0]["mint"] == M1
    from app.tokenlab import TokenLab
    hub.lab = TokenLab(hub.market)                                         # "reinício": memória vazia
    asyncio.run(hub.load_lab())
    assert hub.lab.live[M1]["snaps"] == {"1": 50.0, "5": 70.0}
    assert [r["mint"] for r in hub.lab.done] == [M2] and hub.lab.done[0]["label"] == "graduou"
    r = c.get("/api/pump/base", headers=tok(UA)).json()
    assert r["rising"][0]["mint"] == M1 and r["recent_up"][0]["mint"] == M2


def test_restore_ignores_old_live_tokens():
    from app.pumpfun import PumpMarket
    from app.tokenlab import TokenLab
    lab = TokenLab(PumpMarket())
    now = time.time()
    lab.restore({"live": [{"mint": M1, "t0": now - 7200, "snaps": {}}]},
                [{"mint": M2, "label": "2x", "data": {"created_at": datetime.fromtimestamp(now - 15 * 86400, timezone.utc).isoformat()}}], now)
    assert not lab.live and not lab.done


def test_screen_lists_your_manual_buys_even_after_they_close(env):
    c, hub = env["c"], env["hub"]
    hub.market.tokens[M2] = {"price": 1e-6, "symbol": "CMP", "mcap_sol": 30.0}
    assert c.post("/api/pump/manual-buy", json={"mint": M2}, headers=tok(UA)).json()["ok"]
    mine = c.get("/api/pump/base", headers=tok(UA)).json()["mine"]
    assert len(mine) == 1 and mine[0]["open"] and mine[0]["mint"] == M2
    pf = hub.engines[UA]
    hub.market.tokens[M2]["price"] = 0.3e-6
    pf._check_stops(M2, time.time())
    mine = c.get("/api/pump/base", headers=tok(UA)).json()["mine"]
    assert len(mine) == 1 and not mine[0]["open"] and mine[0]["pnl_sol"] < 0 and pf.trades()[0]["manual"]


def test_lessons_find_the_signals_that_led_to_rising():
    from app.pumpfun import PumpMarket
    from app.tokenlab import TokenLab
    lab = TokenLab(PumpMarket())
    now = time.time()
    when = datetime.fromtimestamp(now - 3600, timezone.utc).isoformat(timespec="seconds")
    for i in range(40):                                                    # subiram forte no 1º minuto: 30 de 40 sobem
        lab.done.append({"mint": f"A{i}", "label": "2x" if i < 30 else "morreu", "mcap0": 30.0,
                         "snaps": {"1": 50.0}, "dev_buy": 2.0, "created_at": when, "boost": i < 10})
    for i in range(60):                                                    # parados no 1º minuto: 3 de 60 sobem
        lab.done.append({"mint": f"B{i}", "label": "2x" if i < 3 else ("despencou" if i < 20 else "morreu"),
                         "mcap0": 30.0, "snaps": {"1": 31.0}, "dev_buy": 0.0, "created_at": when})
    ls = lab.lessons(now)
    assert ls["tokens"] == 100 and ls["base_up_pct"] == 33.0
    g1 = {x["faixa"]: x for x in ls["tables"][0]["linhas"]}
    assert g1["30 a 100%"]["up_pct"] == 75.0 and g1["0 a 30%"]["up_pct"] == 5.0 and g1["0 a 30%"]["rug_pct"] == 28.3
    assert ls["best"][0]["sinal"].startswith("Ganho na foto de 1 min: 30 a 100%") or ls["best"][0]["up_pct"] == 75.0


def test_old_graduated_labels_are_redone_on_restore():
    from app.pumpfun import PumpMarket
    from app.tokenlab import TokenLab
    lab = TokenLab(PumpMarket())
    now = time.time()
    when = datetime.fromtimestamp(now - 3600, timezone.utc).isoformat(timespec="seconds")
    lab.restore(None, [{"mint": "G1", "label": "graduou", "data": {"created_at": when, "mcap0": 411.0, "snaps": {"1": 411.0}}},
                       {"mint": "G2", "label": "graduou", "data": {"created_at": when, "mcap0": 33.0, "snaps": {"1": 33.0}}}], now)
    assert [r["label"] for r in lab.done] == ["nasceu graduado", "graduou"]
