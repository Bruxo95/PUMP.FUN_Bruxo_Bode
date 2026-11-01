"""0.32.140: traders de uma aba em todo o tempo e 24 h, e relatório para a Base geral. Só mede. Sem internet."""
import inspect
from datetime import datetime, timezone

from app import traderreport as tr
from tests.test_api import UA, env, tok  # noqa: F401  (fixture env)

NOW = 1_800_000_000.0


def t(h, w, pnl, aba="Top traders", **kw):
    return {"closed_at": datetime.fromtimestamp(NOW - h * 3600, timezone.utc).isoformat(), "wallet": w, "pnl_pct": pnl, "pnl_sol": pnl / 1000, "sol_in": 0.1, "symbol": f"S{h}", "_a": aba, **kw}


ab = lambda x: x["_a"]


def test_all_time_and_24h_are_separate_and_only_of_the_chosen_tab():
    T = [t(1, "A", 10), t(2, "A", -5), t(50, "A", 20), t(3, "B", 5), t(1, "C", 9, aba="Explorar"), t(1, "manual", 9), t(1, "R", 9, real=True), t(1, "F", 5000)]
    r = tr.tabela(T, "Top traders", ab, False, {"A": "Fulano"}, NOW)
    assert {x["wallet"]: x["trades"] for x in r["todo"]} == {"A": 3, "B": 1}
    assert {x["wallet"]: x["trades"] for x in r["h24"]} == {"A": 2, "B": 1}
    a = r["todo"][0]
    assert a["nome"] == "Fulano" and a["saldo_sol"] == 0.025 and a["acerto"] == 67 and a["melhor"]["sol"] == 0.02


def test_lessons_warn_about_concentration_and_a_bad_day():
    T = [t(100 + i, "A", 50) for i in range(4)] + [t(1, "A", -5), t(2, "A", -5), t(3, "A", -5)] + [t(100, "B", 1)]
    L = tr.build(T, "Top traders", ab, False, {}, NOW)["licoes"]
    assert any("responde por" in x for x in L) and any("perdeu nas últimas 24 h" in x for x in L) and any("use como pista" in x for x in L)


def test_learn_uses_the_newest_report_of_each_account():
    novo = {"user_id": "u", "data": {"aba": "Top traders", "todo": [{"wallet": "A", "nome": "N", "trades": 4, "ganhos": 3, "saldo_sol": 0.4, "veredito": "promissor"}]}}
    velho = {"user_id": "u", "data": {"aba": "Top traders", "todo": [{"wallet": "A", "trades": 1, "ganhos": 0, "saldo_sol": -1, "veredito": "ruim"}]}}
    outra = {"user_id": "v", "data": {"aba": "Top traders", "todo": [{"wallet": "A", "trades": 2, "ganhos": 1, "saldo_sol": 0.1, "veredito": "ruim"}]}}
    x = tr.learn([novo, velho, outra])[0]
    assert x["contas"] == 2 and x["trades"] == 6 and x["acerto"] == 67 and x["saldo_sol"] == 0.5 and x["vereditos"] == {"promissor": 1, "ruim": 1}


def test_module_decides_nothing():
    src = inspect.getsource(tr)
    for proibido in ("manual_buy", "save_settings", ".pause(", "_sell("):
        assert proibido not in src


def test_routes_save_and_list_the_report(env):
    c, hub = env["c"], env["hub"]
    A = tok(UA)
    c.get("/api/pump", headers=A)
    pf = hub.engines[UA]
    pf._save_trade({"wallet": "W" * 32, "symbol": "X", "mint": "M" * 40, "sol_in": 0.1, "pnl_sol": 0.01, "pnl_pct": 10, "reason": "alvo", "hold_s": 60, "closed_at": datetime.now(timezone.utc).isoformat(), "real": False})
    r = c.get("/api/pump/traders-aba?aba=Top traders", headers=A).json()
    assert r["todo"][0]["trades"] == 1 and r["h24"][0]["trades"] == 1
    assert c.post("/api/pump/trader-report", json={"aba": "Top traders"}, headers=A).json()["total"]["trades"] == 1
    b = c.get("/api/pump/trader-report/base", headers=A).json()
    assert len(b["relatorios"]) == 1 and b["traders"][0]["trades"] == 1
    assert c.get("/api/pump/trader-report/item?id=" + b["relatorios"][0]["id"], headers=A).json()["aba"] == "Top traders"
    assert c.post("/api/pump/trader-report", json={"aba": "inventada"}, headers=A).status_code == 400
