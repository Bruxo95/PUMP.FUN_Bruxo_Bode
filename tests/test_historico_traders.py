"""0.32.163 (pedido do dono): histórico de cada trader copiado — resumo, detalhe e o que fica guardado. Sem internet."""
import asyncio
import inspect
from datetime import datetime, timezone

from app import traderhist as th
from tests.test_api import UA, env, tok  # noqa: F401  (fixture env)

W1, W2 = "A" * 44, "B" * 44
ab = lambda x: x.get("_a", "Top traders")


def t(w, pnl, closed, real=False, **kw):
    return {"wallet": w, "symbol": f"S{pnl}", "mint": "M" * 40, "sol_in": 0.1, "pnl_sol": pnl / 1000, "pnl_pct": pnl,
            "opened_at": closed, "closed_at": closed, "real": real, "reason": "alvo", **kw}


def test_summary_per_trader_skips_manual_and_false_gains():
    T = [t(W1, 30, "2026-11-01T10:00:00+00:00"), t(W1, -10, "2026-11-02T10:00:00+00:00"), t(W1, 5000, "2026-11-02T11:00:00+00:00"),
         t(W2, -20, "2026-11-02T09:00:00+00:00"), t("manual", 50, "2026-11-02T09:00:00+00:00")]
    R = th.resumo(T, ab, {W1: "trader um"}, {W2: {"rank": 3, "winrate": 61.0}})
    assert [r["wallet"] for r in R] == [W1, W2]                        # do maior resultado para o menor; "manual" fora
    a = R[0]
    assert a["nome"] == "trader um" and a["trades"] == 2 and a["falsos"] == 1 and a["acerto"] == 50 and a["dias"] == 2
    assert abs(a["saldo_sol"] - 0.02) < 1e-9 and a["melhor"]["symbol"] == "S30" and a["pior"]["symbol"] == "S-10"
    assert R[1]["ranking"]["rank"] == 3


def test_detail_has_both_wallets_each_trade_and_open_positions():
    T = [t(W1, 30, "2026-11-01T10:00:00+00:00"), t(W1, -10, "2026-11-02T10:00:00+00:00", real=True), t(W2, 5, "2026-11-02T10:00:00+00:00")]
    P = [{"id": 9, "wallet": W1, "real": False, "symbol": "OPEN", "sol_in": 0.1, "chg_pct": 12.0}]
    d = th.detalhe(T, W1, ab, positions=P)
    assert d["ficticia"]["trades"] == 1 and d["real"]["trades"] == 1
    assert d["ficticia"]["trades_lista"][0]["symbol"] == "S30" and d["ficticia"]["abertas"][0]["symbol"] == "OPEN"
    assert d["real"]["por_dia"][0]["dia"] == "2026-11-02" and not d["real"]["abertas"]


def test_saved_row_keeps_the_ranking_per_day():
    antes = {"ranking": {"rank": 5}, "ranking_dias": {"2026-11-01": {"rank": 5}}, "nome": "velho"}
    g = th.guardar({"wallet": W1, "ranking": {"rank": 2, "winrate": 70.0}, "nome": None}, antes, "2026-11-02")
    assert g["ranking"]["rank"] == 2 and set(g["ranking_dias"]) == {"2026-11-01", "2026-11-02"} and g["nome"] == "velho"
    g2 = th.guardar({"wallet": W1, "ranking": None}, g, "2026-11-03")
    assert g2["ranking"]["rank"] == 2                                   # saiu do ranking: fica o último que se viu


def test_module_decides_nothing():
    src = inspect.getsource(th)
    assert "manual_buy" not in src and "_sell(" not in src and "save_settings" not in src


def test_routes_and_history_saved_once(env):
    c, hub = env["c"], env["hub"]
    A = tok(UA)
    c.get("/api/pump", headers=A)
    pf = hub.engines[UA]
    pf._save_trade({"wallet": W1, "symbol": "X", "mint": "M" * 40, "sol_in": 0.1, "pnl_sol": 0.01, "pnl_pct": 10, "reason": "alvo",
                    "hold_s": 60, "opened_at": "2026-11-02T10:00:00+00:00", "closed_at": datetime.now(timezone.utc).isoformat(), "real": False})
    r = c.get("/api/pump/trader-hist", headers=A).json()
    assert r["traders"][0]["wallet"] == W1 and r["traders"][0]["trades"] == 1
    d = c.get(f"/api/pump/trader-hist/w/{W1}", headers=A).json()
    assert d["ficticia"]["trades_lista"][0]["symbol"] == "X"
    assert c.get("/api/pump/trader-hist/w/nao-e-carteira", headers=A).status_code == 400
    assert asyncio.run(hub.th_save(pf)) == 1 and asyncio.run(hub.th_save(pf)) == 0   # guarda e não repete sem mudança
