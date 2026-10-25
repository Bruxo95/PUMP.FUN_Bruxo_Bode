"""Aba Relatórios (0.9.8): números vêm só dos dados do próprio usuário e batem com os trades."""
from app.reports import build
from tests.test_api import env  # noqa: F401  (fixture env)


def _t(wallet, pnl, reason, real=False, day="2026-10-25T10:00:00+00:00", fees=0.01):
    return {"wallet": wallet, "pnl_sol": pnl, "reason": reason, "real": real, "closed_at": day, "fees_sol": fees,
            "sol_in": 0.1, "hold_s": 60, "fee_parts": {"platform": fees / 2, "portal": fees / 2}}


def test_reports_group_by_trader_exit_and_skip_reason():
    trades = [_t("A", 0.05, "trader vendeu 100%"), _t("A", -0.04, "stop de perda (−40%)"),
              _t("B", -0.03, "stop móvel (pico +25.0% → saiu em +12.0% líquido)"), _t("B", 0.2, "alvo (+100%)", real=True)]
    feed = [{"action": "não copiou", "reason": "risco 9/10 acima do máximo 7", "at": "2026-10-25T10:00:00+00:00"},
            {"action": "não copiou", "reason": "10 maiores carteiras têm 60% (máx. 35%) — risco de insiders/dev"},
            {"action": "não copiou", "reason": "preço já subiu 50% desde a compra do trader (máx. 30%)"},
            {"action": "REAL não copiou", "reason": "perda do dia chegou a 0.5 SOL"},
            {"action": "copiou compra", "reason": "comprou"}]
    r = build(trades, feed, None, False, followed=["A"], paused=["B"])
    assert r["total"]["trades"] == 3 and abs(r["total"]["pnl_sol"] - (-0.02)) < 1e-9          # o real fica de fora
    assert [x["wallet"] for x in r["traders"]] == ["B", "A"] and r["traders"][0]["status"] == "pausado"
    assert {x["reason"] for x in r["exits"]} == {"Trader vendeu", "Stop de perda", "Stop móvel"}
    sk = {x["reason"]: x["count"] for x in r["skips"]}
    assert sk == {"Risco do token": 1, "Concentração nas 10 maiores": 1, "Preço já subiu desde o trader": 1}
    real = build(trades, feed, None, True)
    assert real["total"]["trades"] == 1 and real["skips"] == [{"reason": "Perda máxima do dia (real)", "count": 1}]
    old = build([_t("A", 1.0, "alvo", day="2020-01-01T00:00:00+00:00")], [], 7, False)
    assert old["total"]["trades"] == 0                                                          # fora do período


def test_reports_route_is_per_user(env):
    from tests.test_api import UA, UB, tok
    c, hub = env["c"], env["hub"]
    import asyncio
    pa = asyncio.run(hub.engine(UA))
    env["db"].set_role(UB, "admin")  # telas do menu Usar ou descartar: só admin (0.17.4)
    pa._save_trade(_t("W", 0.5, "alvo (+50%)"))
    ra = c.get("/api/pump/reports?days=0", headers=tok(UA)).json()
    rb = c.get("/api/pump/reports?days=0", headers=tok(UB, "b@x.com")).json()
    assert ra["total"]["trades"] == 1 and rb["total"]["trades"] == 0                            # B não vê os de A
    assert c.get("/api/pump/reports").status_code == 401
