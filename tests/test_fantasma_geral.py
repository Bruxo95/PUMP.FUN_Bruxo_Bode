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
