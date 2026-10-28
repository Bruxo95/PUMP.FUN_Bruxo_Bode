"""Evoluções do cérebro (0.31.85): registro, relatório, comparação e voltar/automático."""
import asyncio

from app.evolucoes import comparar, relatorio, reverter_ajustes
from tests.test_api import UA, env, tok  # noqa: F401  (fixture env)


def _t(day, pnl, sombra=False, reason="stop de perda (-25%)"):
    return {"origem": "explorar", "pnl_sol": pnl, "pnl_pct": pnl * 2000, "sombra": sombra, "symbol": "T" + str(day),
            "reason": reason, "closed_at": f"2026-10-{day:02d}T12:00:00+00:00"}


def test_report_and_compare_by_period():
    from app.auto_trades import ts
    trades = [_t(20, 0.01), _t(20, -0.02), _t(22, 0.03), _t(22, 0.01, sombra=True)]
    e1 = relatorio(trades, ts("2026-10-19T00:00:00+00:00"), ts("2026-10-21T00:00:00+00:00"))
    e2 = relatorio(trades, ts("2026-10-21T00:00:00+00:00"), None)
    assert e1["operacoes"] == 2 and e1["acerto"] == 0.5 and e1["piores"][0]["symbol"] == "T20"
    assert e2["operacoes"] == 1 and e2["sombras"] == 1 and e2["lucro_sol"] == 0.03
    linha = next(x for x in comparar(e1, e2) if x["chave"] == "lucro_sol")
    assert linha["diferenca"] == round(0.03 - (-0.01), 6)


def test_revert_takes_settings_before_first_change():
    from app.auto_trades import ts
    log = [{"tipo": "saida_auto", "acao": "aplicou", "em": "2026-10-22T00:00:00+00:00", "detalhe": {"antes": {"pump_ar_stop_pct": 25}}},
           {"tipo": "saida_auto", "acao": "aplicou", "em": "2026-10-23T00:00:00+00:00", "detalhe": {"antes": {"pump_ar_stop_pct": 15}}},
           {"tipo": "saida_auto", "acao": "aplicou", "em": "2026-10-19T00:00:00+00:00", "detalhe": {"antes": {"pump_ar_stop_pct": 40}}}]
    assert reverter_ajustes(log, ts("2026-10-21T00:00:00+00:00")) == {"pump_ar_stop_pct": 25}


def test_rollback_freezes_entry_and_back_to_auto(env):
    c, hub = env["c"], env["hub"]
    env["db"].set_role(UA, "admin")
    c.get("/api/pump", headers=tok(UA))
    asyncio.run(hub.base_tick())
    L = c.get("/api/pump/base/evolucoes", headers=tok(UA)).json()
    assert L["evolucoes"] and L["evolucoes"][0]["numero"] == 1 and L["congelado"] is None
    env["db"].tables["base_evolutions"][0]["estado"]["bloqueios"] = [
        {"feature": "pressure", "faixa": "abaixo de 60%", "nome": "Pressão de compra", "n": 9, "acerto": 0.1, "media_pct": -30}]
    r = c.post("/api/pump/base/evolucoes/1/voltar", headers=tok(UA), json={}).json()
    assert r["ok"]
    pf = asyncio.run(hub.engine(UA))
    assert pf.learned_for_entry("explorar")["bloqueios"][0]["faixa"] == "abaixo de 60%"
    assert asyncio.run(hub.auto_tune(pf))["ok"] is False
    rep = c.get("/api/pump/base/evolucoes/1", headers=tok(UA)).json()
    assert rep["numero"] == 1 and "piores" in rep
    assert c.post("/api/pump/base/automatico", headers=tok(UA), json={}).json()["ok"]
    assert pf.brain_freeze is None


def test_compare_says_if_improved_with_enough_base():
    """0.32.24 (pedido do dono): o comparar diz se melhorou, com %, e só com base suficiente."""
    from app.evolucoes import comparar, veredito
    a = {"operacoes": 6, "por_trade": 0.002, "sombras": 0, "estado": {"bloqueios": [1]}}
    b = {"operacoes": 8, "por_trade": 0.003, "sombras": 0, "estado": {"bloqueios": [1, 2]}}
    v = veredito(a, b)
    assert v["resultado"] == "melhorou" and v["pct"] == 50.0
    linhas = {x["chave"]: x for x in comparar(a, b)}
    assert linhas["por_trade"]["melhor"] == "melhorou" and linhas["bloqueios"]["b"] == 2 and linhas["por_trade"]["explica"]
    assert veredito({"operacoes": 0, "sombras": 4}, {"operacoes": 0, "sombras": 2})["resultado"] == "poucos dados"
