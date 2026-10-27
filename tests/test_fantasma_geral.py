"""Estratégias fantasma com base geral (0.31.64): as regras de saída somam os resultados de todas as contas."""
from tests.test_api import UA, UB, env, tok  # noqa: F401  (fixture env)


def test_ghost_variants_sum_all_accounts(env):
    c, hub = env["c"], env["hub"]
    env["db"].set_role(UA, "admin")
    c.get("/api/pump", headers=tok(UA))
    c.get("/api/pump", headers=tok(UB, "b@x.com"))
    a, b = hub.engines[UA], hub.engines[UB]
    vid = a.ghosts.variants[0][0]
    a.ghosts.stats[vid] = {"trades": 2, "wins": 1, "pnl_sol": 0.01, "invested_sol": 0.2, "best_sum": 40.0, "recent": []}
    b.ghosts.stats[vid] = {"trades": 3, "wins": 3, "pnl_sol": 0.06, "invested_sol": 0.3, "best_sum": 90.0, "recent": []}
    r = c.get("/api/pump/ghosts", headers=tok(UA)).json()
    v = [x for x in r["variants"] if x["id"] == vid][0]
    assert v["trades"] == 5 and v["n_sua"] == 2 and v["n_conhecimento"] == 3 and abs(v["pnl_sol"] - 0.07) < 1e-9
    assert r["geral"] is True and r["best"] == vid



def test_ghosts_drop_fake_price_gains_on_load():
    """0.31.65: +182.916% (R1R2L1R2) sai das somas guardadas dos fantasmas."""
    from app.ghosts import Ghosts

    class P:
        pass
    g = Ghosts.__new__(Ghosts)
    g.names = {"v1"}
    g.load({"since": "2026-10-27T00:23:03+00:00", "stats": {"v1": {"trades": 3, "wins": 2, "pnl_sol": 183.9, "invested_sol": 0.3,
            "best_sum": 183000.0, "recent": [{"pnl_sol": 183.83, "pnl_pct": 182916.0, "best": 182916.0},
                                             {"pnl_sol": 0.1, "pnl_pct": 100.0, "best": 120.0},
                                             {"pnl_sol": -0.03, "pnl_pct": -30.0, "best": 5.0}]}}})
    s = g.stats["v1"]
    assert s["trades"] == 2 and s["wins"] == 1 and abs(s["pnl_sol"] - 0.07) < 1e-6 and len(s["recent"]) == 2
