"""Estratégias fantasma e pós-trade (0.18.0): mesmas entradas da cópia fictícia, saídas diferentes, lado a lado;
melhor e pior momento de cada posição gravados no trade fechado."""
import asyncio
import time

from tests.test_api import UA, UB, env, tok  # noqa: F401  (fixture env)
from tests.test_pump import _W, _ev, _pump


def _price(pf, m, px):
    pf.tokens[m]["price"] = px
    pf._check_stops(m, time.time())


def test_ghost_variants_share_entry_and_exit_differently(tmp_path):
    pf = _pump(tmp_path, paid=False, pump_extra_slip_pct=0.0)
    pf.add_manual(_W)
    m = "Ghost".ljust(40, "1") + "pump"
    pf.on_message(_ev("buy", _W, m, 1.0, 1e6, 30, 3e7))                     # entra a 1e-6
    assert len(pf.positions()) == 1 and len(pf.ghosts.open) == 10
    _price(pf, m, 0.75e-6)                                                   # −28% líquido
    st = pf.ghosts.stats
    assert st["stop20"]["trades"] == 1 and st["stop20"]["pnl_sol"] < 0 and "base" not in st
    _price(pf, m, 1.6e-6)                                                    # +53% líquido
    assert st["alvo50"]["trades"] == 1 and st["alvo50"]["pnl_sol"] > 0
    part = next(g for g in pf.ghosts.open if g["v"] == "partes")
    assert abs(part["left"] / part["tokens"] - 0.5) < 1e-9
    _price(pf, m, 1.45e-6)                                                   # +39%: caiu 14 pontos do pico
    assert st["trail_justo"]["trades"] == 1
    assert any(g["v"] == "trail_largo" for g in pf.ghosts.open)
    pf.on_message(_ev("sell", _W, m, 1.0, 1e6, 30, 30 / 1.45e-6, newTokenBalance=0))
    assert not pf.ghosts.open and st["base"]["pnl_sol"] > 0
    t = pf.trades()[0]
    assert t["best_pct"] > 50 and t["worst_pct"] < -25                       # pós-trade da cópia fictícia
    snap = pf.ghosts.snapshot(pf.trades())
    assert snap["yours"]["trades"] == 1 and snap["best"] == "alvo50" and len(snap["variants"]) == 10
    copy = type(pf.ghosts)(pf)
    copy.load(pf.ghosts.dump())
    assert copy.stats == pf.ghosts.stats and copy.since == pf.ghosts.since
    pf.reset_sim()
    assert pf.ghosts.stats == {} and pf.ghosts.dirty


def test_ghosts_route_reports_mesa_and_persistence(env):
    c, hub, db = env["c"], env["hub"], env["db"]
    r = c.get("/api/pump/ghosts", headers=tok(UA)).json()
    assert r["yours"]["trades"] == 0 and len(r["variants"]) == 10 and r["best"] is None
    assert c.get("/api/pump/ghosts", headers=tok(UB, "b@x.com")).status_code == 403
    assert c.get("/api/pump/ghosts").status_code == 401
    rep = c.get("/api/pump/reports?days=0", headers=tok(UA)).json()
    assert rep["mesa"] == {"trades": 0}
    pf = hub.engines[UA]
    pf.ghosts.stats = {"base": {"trades": 2, "wins": 1, "pnl_sol": 0.01, "invested_sol": 0.2, "best_sum": 40.0, "recent": []}}
    pf.ghosts.since, pf.ghosts.dirty = "2026-10-26T00:00:00+00:00", True
    assert asyncio.run(hub.save_ghosts()) == 1 and not pf.ghosts.dirty
    assert db.tables["ghost_stats"][0]["data"]["stats"]["base"]["trades"] == 2
    hub.engines.pop(UA)
    again = c.get("/api/pump/ghosts", headers=tok(UA)).json()
    base = next(v for v in again["variants"] if v["id"] == "base")
    assert base["trades"] == 2 and base["roi_pct"] == 5.0 and again["best"] == "base"


def test_reports_mesa_counts_profit_given_back():
    from app.reports import mesa
    T = [{"best_pct": 45.0, "worst_pct": -5.0, "pnl_pct": -3.0, "reason": "trader vendeu 100%"},
         {"best_pct": 12.0, "worst_pct": -41.0, "pnl_pct": -40.0, "reason": "stop de perda (−40%)"},
         {"best_pct": 60.0, "worst_pct": 0.0, "pnl_pct": 50.0, "reason": "alvo (+50%)"},
         {"pnl_pct": 10.0, "reason": "antigo, sem o dado"}]
    m = mesa(T)
    assert m["trades"] == 3 and m["gave_back"] == 1 and m["stops"] == 1 and m["stops_were_up"] == 1
    assert m["avg_best_pct"] == 39.0 and m["avg_left_pct"] == round((48 + 52 + 10) / 3, 1)
