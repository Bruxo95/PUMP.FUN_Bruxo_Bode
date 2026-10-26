"""Por que está no vermelho (0.31.11): causa de cada perda, por trader, e guardado no relatório do dia."""
import time

from tests.test_api import UA, env, tok  # noqa: F401  (fixture env)
from tests.test_daily import _iso

HOLDER = "dmuX".ljust(44, "1")


def test_causes_and_trader_recommendation():
    from app.reports import autopsy, loss_cause
    assert loss_cause({"pnl_sol": -1, "reason": "dev vendeu (-3%)"}) == "rug"
    assert loss_cause({"pnl_sol": -1, "reason": "tempo máximo (6 h)"}) == "parado"
    assert loss_cause({"pnl_sol": -1, "reason": "stop de perda", "best_pct": 25}) == "devolveu"
    assert loss_cause({"pnl_sol": -0.001, "gross_sol": 0.001, "reason": "trader vendeu 100%"}) == "taxas"
    assert loss_cause({"pnl_sol": -1, "reason": "stop de perda", "trader_px": 1.0, "price_in": 1.2}) == "entrada_cara"
    assert loss_cause({"pnl_sol": -1, "reason": "trader vendeu 100%"}) == "trader_perdeu"
    assert loss_cause({"pnl_sol": -1, "reason": "stop de perda (−40%)"}) == "so_caiu"
    T = [{"wallet": HOLDER, "pnl_sol": -0.022, "reason": "tempo máximo (6 h)", "hold_s": 21500} for _ in range(8)]
    T.append({"wallet": "Bom".ljust(44, "1"), "pnl_sol": 0.02, "reason": "stop móvel"})
    a = autopsy(T)
    assert a["losses"] == 8 and a["causes"][0]["causa"] == "parado" and a["causes"][0]["trades"] == 8
    tr = a["traders"][0]
    assert tr["wallet"] == HOLDER and tr["causa"] == "parado" and "holder longo" in tr["recomendacao"] and "pause ou bana" in tr["recomendacao"]
    assert len(a["traders"]) == 1                                         # quem está no lucro não entra


def test_reports_route_and_daily_report_keep_the_causes(env):
    c, hub = env["c"], env["hub"]
    c.get("/api/pump", headers=tok(UA))
    pf = hub.engines[UA]
    now = time.time()
    for i in range(4):
        pf._save_trade({"wallet": HOLDER, "symbol": f"T{i}", "mint": "M" * 40, "sol_in": 0.1005, "pnl_sol": -0.02, "pnl_pct": -20.0,
                        "reason": "tempo máximo (6 h)", "hold_s": 21600, "closed_at": _iso(now - 60), "real": False})
    r = c.get("/api/pump/reports?days=0", headers=tok(UA)).json()
    assert r["autopsy"]["causes"][0]["causa"] == "parado" and r["autopsy"]["traders"][0]["wallet"] == HOLDER
    d = c.get("/api/pump/daily", headers=tok(UA)).json()["report"]
    assert d["loss_causes"][0]["causa"] == "parado" and any(s["tipo"] == "causa_parado" for s in d["suggestions"])
    assert "Por que ficou no vermelho" in c.get("/api/pump/daily/ai", headers=tok(UA)).text
