"""Simulador "e se" e onde o dinheiro vai (0.22.0)."""
import time

from tests.test_pump import _W, _ev, _pump


def test_whatif_uses_best_and_worst_moment_and_counts_stop_first():
    from app.reports import whatif
    T = [{"best_pct": 45.0, "worst_pct": -5.0, "pnl_pct": -3.0, "pnl_sol": -0.003, "sol_in": 0.1},
         {"best_pct": 12.0, "worst_pct": -41.0, "pnl_pct": -40.0, "pnl_sol": -0.04, "sol_in": 0.1},
         {"best_pct": 60.0, "worst_pct": 0.0, "pnl_pct": 50.0, "pnl_sol": 0.05, "sol_in": 0.1},
         {"pnl_pct": 10.0, "pnl_sol": 0.01, "sol_in": 0.1}]                                    # antigo: fica de fora
    w = whatif(T)
    rows = {r["regra"]: r for r in w["rows"]}
    assert w["trades"] == 3 and w["real_sol"] == 0.007
    assert rows["Alvo fixo +30%"]["pnl_sol"] == 0.02 and rows["Alvo fixo +30%"]["diff_sol"] == 0.013
    assert rows["Stop de perda 25%"]["pnl_sol"] == 0.022
    assert rows["Stop 20% + alvo +30%"]["pnl_sol"] == 0.04
    assert w["rows"][0]["pnl_sol"] == max(r["pnl_sol"] for r in w["rows"])


def test_cost_shows_entry_worse_than_trader_and_fees(tmp_path):
    from app.reports import build
    pf = _pump(tmp_path, paid=False, pump_extra_slip_pct=3.0, pump_trail_enabled=False)
    pf.add_manual(_W)
    m = "Cost".ljust(40, "1") + "pump"
    pf.on_message(_ev("buy", _W, m, 1.0, 1e6, 30, 3e7), time.time())
    pf.on_message(_ev("sell", _W, m, 1.0, 1e6, 30, 3e7 / 1.5, newTokenBalance=0), time.time())
    t = pf.trades()[0]
    assert abs(t["trader_px"] - 1e-6) < 1e-15
    cu = build(pf.trades(), [], None, False)["custo"]
    assert cu["with_px"] == 1 and abs(cu["entry_worse_pct"] - 3.0) < 0.01
    assert cu["fees_pct"] > 0 and cu["gross_sol"] > cu["net_sol"]
