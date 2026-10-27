"""Entradas sombra e sem contar duas vezes (0.31.72)."""
import asyncio
import time

from tests.test_api import UA, UB, env, tok  # noqa: F401  (fixture env)


def test_shadow_measured_and_learned(env):
    c, hub = env["c"], env["hub"]
    c.get("/api/pump", headers=tok(UA))
    pf = hub.engines[UA]
    mint = "Shad".ljust(40, "1") + "pump"
    hub.market.tokens[mint] = {"price": 1e-6}
    row = {"mint": mint, "symbol": "SHD", "pred": {"verdict": "chance alta"}, "pressure": 65, "holders": 150, "curve_pct": 85,
           "risk": 5, "chg_5m": 10, "boost": None}
    pf._funnel_note(row, "aprendi com os erros: Risco 4 a 6", time.time() - 1000)
    assert mint in hub.shadows and hub.shadows[mint]["px0"] == 1e-6
    hub.market.tokens[mint]["price"] = 0.5e-6                       # caiu 50% em 15 min
    hub.monitor = None
    assert asyncio.run(hub.shadow_tick()) == 1
    st = [t for t in pf.learn_trades() if t.get("sombra")]
    assert st and abs(st[0]["pnl_pct"] - (-54.0)) < 0.01
    assert env["db"].tables["base_shadows"]
    fx = [x for x in pf.learned("explorar", time.time() + 120)["faixas"] if x["feature"] == "risk"]
    assert fx and fx[0]["n_sombra"] == 1


def test_same_token_two_accounts_counts_once(env):
    c, hub = env["c"], env["hub"]
    c.get("/api/pump", headers=tok(UA))
    c.get("/api/pump", headers=tok(UB, "b@x.com"))
    a, b = hub.engines[UA], hub.engines[UB]
    t = {"id": "x1", "mint": "Same".ljust(44, "1"), "origem": "explorar", "auto": True, "pnl_pct": -20.0, "pnl_sol": -0.01,
         "auto_info": {"risk": 5}, "opened_at": "2026-10-27T10:00:00+00:00", "closed_at": "2026-10-27T10:10:00+00:00"}
    a._save_trade(dict(t))
    b._save_trade(dict(t, id="x2", opened_at="2026-10-27T10:03:00+00:00"))
    lt = [x for x in a.learn_trades() if x["mint"] == t["mint"]]
    assert len(lt) == 1 and lt[0]["_mine"] is True
