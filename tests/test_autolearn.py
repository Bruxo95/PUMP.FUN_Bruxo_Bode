"""Aprender com os erros sozinho (0.31.12): faixa das compras automáticas que perde é bloqueada; só aperta."""
import time

from tests.test_api import UA, env, tok  # noqa: F401  (fixture env)
from tests.test_auto_explorar import _pf, _row


def _closed(pf, n, pressure, pnl, hold=4):
    for i in range(n):
        pf._save_trade({"wallet": "manual", "origem": "explorar", "auto": True, "mint": f"P{pressure}-{i}", "sol_in": 0.0505,
                        "pnl_sol": pnl, "pnl_pct": pnl / 0.0505 * 100, "hold_s": hold, "real": False,
                        "auto_info": {"pressure": pressure, "holders": 150, "curve_pct": 85, "chg_5m": 20, "risk": 3, "boost": {"active": False}}})


def test_losing_band_is_blocked_and_good_band_is_not():
    from app.autolearn import study
    pf = _pf(pump_ex_auto_on=True, pump_ar_learn=True)
    _closed(pf, 10, 65, -0.02)                                            # pressão 60–70%: 10 perdas
    _closed(pf, 10, 85, 0.01)                                             # pressão 80%+: 10 ganhos
    st = study(pf.trades(1000), "explorar")
    blocked = {(x["feature"], x["faixa"]) for x in st["bloqueios"]}
    assert ("pressure", "60 a 70%") in blocked and ("pressure", "80% ou mais") not in blocked
    assert st["morte_rapida"] == 10 and st["fechadas"] == 20
    old = (time.time() - 3600) * 1000
    assert pf.explore_entry_reason(_row(pressure=65.0, created=old)).startswith("aprendi com os erros: Pressão de compra 60 a 70%")
    assert pf.explore_entry_reason(_row(pressure=85.0, created=old)) is None
    pf.cfg.pump_ar_learn = False
    assert pf.explore_entry_reason(_row(pressure=65.0, created=old)) is None            # desligado: não bloqueia


def test_needs_minimum_base_and_warns_when_it_learns():
    pf = _pf(pump_ex_auto_on=True, pump_ar_learn=True)
    _closed(pf, 9, 65, -0.02)
    assert pf.learned("explorar", time.time())["bloqueios"] == []                       # 9 < 10: ainda aprendendo
    _closed(pf, 1, 65, -0.02)
    st = pf.learned("explorar", time.time() + 61)
    assert st["bloqueios"] and any("Aprendi com os erros" in e["msg"] for e in pf.events)


def test_explore_screen_shows_what_was_learned(env):
    c, hub = env["c"], env["hub"]
    c.get("/api/pump", headers=tok(UA))
    _closed(hub.engines[UA], 10, 65, -0.02)
    r = c.get("/api/pump/explore", headers=tok(UA)).json()
    assert r["learn_on"] is True and any(x["faixa"] == "60 a 70%" for x in r["learned_auto"]["bloqueios"])
