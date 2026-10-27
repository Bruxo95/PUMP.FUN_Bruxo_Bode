"""Aprendizado geral (0.31.63): cada conta aprende com as compras automáticas de todas, marcando CONHECIMENTO; sem a cópia
de trades de outra conta e sem ganhos de preço lido errado."""
from tests.test_api import UA, UB, env, tok  # noqa: F401  (fixture env)


def _t(mint, pnl_pct, **kw):
    return dict({"id": "t" + mint[:6], "mint": mint, "symbol": "X", "origem": "explorar", "auto": True, "pnl_pct": pnl_pct, "pnl_sol": pnl_pct / 1000,
                 "auto_info": {"curve_pct": 85}, "closed_at": "2026-10-27T10:00:00+00:00"}, **kw)


def test_learning_is_shared_between_accounts(env):
    c, hub = env["c"], env["hub"]
    c.get("/api/pump", headers=tok(UA))
    c.get("/api/pump", headers=tok(UB, "b@x.com"))
    a, b = hub.engines[UA], hub.engines[UB]
    for i in range(6):
        a._save_trade(_t(f"A{i}".ljust(44, "1"), -30.0))
    a._save_trade(_t("Fake".ljust(44, "1"), 182916.0))                 # preço lido errado: fora
    b._save_trade(_t("Copy".ljust(44, "1"), -30.0, follow_of={"user": UA, "pos": 1}))   # cópia: fora
    tb = b.learn_trades()
    assert len(tb) == 6 and all(not t["_mine"] for t in tb)
    st = b.learned("explorar")
    fx = [x for x in st["faixas"] if x["n"] == 6]
    assert fx and fx[0]["n_conhecimento"] == 6 and fx[0]["n_sua"] == 0
    assert st["bloqueios"]                                            # B já sabe o que A aprendeu
