"""Melhorias do Explorar (0.31.21): fantasmas das automáticas, ajuste automático delas, aprender com 6 operações e
ganhou × perdeu pelos números da entrada."""
import time

from tests.test_auto_explorar import _pf

M = "Gh0st".ljust(44, "1").replace("0", "o")


def test_auto_ghosts_open_and_exit_by_their_own_rules():
    from app.ghosts import AUTO_VARIANTS
    pf = _pf()
    pf.tokens[M] = {"price": 1e-6, "symbol": "GH", "mcap_sol": 60.0}
    t = time.time()
    pf.ghosts_auto.on_open({"mint": M, "wallet": "manual", "symbol": "GH", "sol_in": 0.05, "tokens": 50000.0, "opened_at": None}, t)
    assert len(pf.ghosts_auto.open) == len(AUTO_VARIANTS) and not pf.ghosts.open        # não mistura com as cópias
    pf.tokens[M]["price"] = 0.82e-6                                                        # cerca de −23% já com taxas
    pf._check_stops(M, t + 5)
    st = pf.ghosts_auto.stats
    assert st["a_stop15"]["trades"] == 1 and "a_base" not in st and "a_stop40" not in st
    pf.tokens[M]["price"] = 0.7e-6
    pf._check_stops(M, t + 10)
    assert pf.ghosts_auto.stats["a_base"]["trades"] == 1                                  # stop 25% das proteções sugeridas
    snap = pf.ghosts_auto.snapshot(pf.trades(100))
    assert snap["variants"][0]["id"] == "a_base" and snap["yours"]["nome"]


def test_auto_variant_settings_map_to_auto_options():
    from app.autotune import auto_variant_settings
    s = auto_variant_settings("a_press3")
    assert s["pump_ar_press_min"] == 3.0 and s["pump_ar_stop_pct"] == 25 and s["pump_ar_exit_grad"] is True
    assert auto_variant_settings("a_sem_press")["pump_ar_press_min"] == 0.0
    assert auto_variant_settings("a_segura_grad")["pump_ar_exit_grad"] is False
    assert auto_variant_settings("a_alvo60")["pump_ar_tp1_pct"] == 0.0
    assert auto_variant_settings("stop20") is None                                         # fantasma das cópias não vale aqui


def test_pressure_exit_waits_the_configured_minutes():
    pf = _pf()
    pf.pressure = lambda mint: (20.0, "teste")
    p = {"mint": M, "open_t": 1000.0, "grad_in": False, "press_min": 3.0}
    assert pf.smart_exit(p, 1000.0 + 90, force=True) is None                              # 1,5 min < 3 min
    assert pf.smart_exit(p, 1000.0 + 200, force=True).startswith("pressão de compra virou")
    p["press_min"] = 0.0
    assert pf.smart_exit(p, 1000.0 + 999, force=True) is None                             # 0 = não usa


def test_learns_with_six_and_compares_winners_and_losers():
    from app.autolearn import MIN_N, compare
    assert MIN_N == 6
    pf = _pf()
    for i in range(4):
        pf._save_trade({"wallet": "manual", "origem": "explorar", "auto": True, "mint": f"W{i}", "symbol": f"W{i}", "real": False,
                        "pnl_sol": 0.02, "pnl_pct": 40.0, "best_pct": 45.0, "hold_s": 600, "reason": "token graduou (PumpSwap)",
                        "auto_info": {"pressure": 85, "holders": 300, "curve_pct": 92, "chg_5m": 20, "risk": 2, "score": 70}})
    for i in range(6):
        pf._save_trade({"wallet": "manual", "origem": "explorar", "auto": True, "mint": f"L{i}", "symbol": f"L{i}", "real": False,
                        "pnl_sol": -0.03, "pnl_pct": -60.0, "best_pct": 0.5, "hold_s": 120, "reason": "stop de perda (−40%)",
                        "auto_info": {"pressure": 62, "holders": 120, "curve_pct": 70, "chg_5m": 90, "risk": 5, "score": 40}})
    c = compare(pf.trades(100), "explorar")
    assert c["ganhou"] == 4 and c["perdeu"] == 6 and c["entrou_no_topo"] == 6
    n = {x["feature"]: x for x in c["numeros"]}
    assert n["pressure"]["ganhou"] == 85 and n["pressure"]["perdeu"] == 62 and n["curve_pct"]["perdeu"] == 70
    assert c["stops"][0]["stop"] == 40 and c["stops"][0]["escorregou"] == 20.0 and c["stop_medio_escorregou"] == 20.0
    assert c["saidas_perdas"][0] == ["stop de perda", 6]
