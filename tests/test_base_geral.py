"""Base geral (0.31.71): maturidade, o que está por vir e o log do que mudou."""
from app.basegeral import diff, maturity, state_summary, upcoming


def test_maturity_and_log():
    L = {"fechadas": 54, "min_n": 6, "faixas": [
        {"feature": "risk", "nome": "Risco", "faixa": "4 a 6", "n": 52, "acerto": 0.34, "media_pct": -12.3, "bloqueada": True},
        {"feature": "pressure", "nome": "Pressão de compra", "faixa": "70 a 80%", "n": 4, "acerto": 0.25, "media_pct": -16.7, "bloqueada": False}]}
    G = {"best": "grad", "variants": [{"id": "grad", "nome": "Não sai quando gradua", "trades": 16, "avg_sol": 0.0037},
                                      {"id": "s15", "nome": "Stop 15%", "trades": 18, "avg_sol": -0.0128}]}
    m = maturity(L, G, 2, 0.9)
    assert 0 < m["total"] < 100 and len(m["partes"]) == 3
    nxt = upcoming(L, G, 0.9, 6, 0.35, -5.0)
    assert any("70 a 80%" in x and "2 operação" in x for x in nxt) and any("Ajuste automático" in x for x in nxt)
    cur = state_summary(L, G)
    assert cur["bloqueadas"] == ["Risco 4 a 6"] and cur["melhor_regra"] == "Não sai quando gradua"
    assert diff(None, cur)[0][0] == "inicio"
    nxt_state = dict(cur, bloqueadas=["Pressão de compra 70 a 80%", "Risco 4 a 6"])
    assert diff(cur, nxt_state) == [("bloqueou", "Faixa bloqueada: Pressão de compra 70 a 80% (o robô para de comprar aí)")]


def test_base_geral_route(env):
    from tests.test_api import UA, tok
    c = env["c"]
    env["db"].set_role(UA, "admin")
    c.get("/api/pump", headers=tok(UA))
    r = c.get("/api/pump/base-geral", headers=tok(UA)).json()
    assert "maturidade" in r and "log" in r and "por_vir" in r
    import asyncio
    asyncio.run(env["hub"].base_tick())
    asyncio.run(env["hub"].base_tick())
    assert len(env["db"].tables["base_snapshots"]) == 2 and env["db"].tables["base_log"][0]["tipo"] == "inicio"


from tests.test_api import env  # noqa: E402,F401  (fixture env)
