"""0.32.118: com a real ligada o ajuste só sugere e aplica no clique; evolução por aba e limite por hora só medem. Sem internet."""
import time

from app import brainshadow as bs
from tests.test_api import UA, env, tok  # noqa: F401  (fixture env)
from tests.test_autotune import HOLDER, _trades
from tests.test_daily import _iso


def _base(env):
    c, hub = env["c"], env["hub"]
    A = tok(UA)
    c.get("/api/pump", headers=A)
    pf = hub.engines[UA]
    now = time.time()
    pf.ghosts.since = _iso(now - 72 * 3600)
    pf.ghosts.stats = {"alvo50": {"trades": 40, "wins": 30, "pnl_sol": 0.8, "invested_sol": 4.0, "best_sum": 0}}
    _trades(pf, 30, -0.01, now - 50 * 3600)
    return c, hub, A, pf


def test_real_on_changes_nothing_alone_and_click_applies(env):
    c, hub, A, pf = _base(env)
    pf.cfg.pump_real_enabled = True
    antes, trail = pf.cfg.pump_tp_pct, pf.cfg.pump_trail_enabled
    assert c.post("/api/pump/tune/run", json={}, headers=A).json()["ok"] is False
    assert pf.cfg.pump_tp_pct == antes and pf.cfg.pump_trail_enabled == trail and HOLDER not in pf.paused()
    L = c.get("/api/pump/tune", headers=A).json()["sugestoes"]
    ids = [x["id"] for x in L]
    assert "saida:alvo50" in ids and "trader:" + HOLDER in ids
    assert c.post("/api/pump/tune/apply", json={"id": "saida:alvo50"}, headers=A).json()["ok"]
    assert pf.cfg.pump_tp_pct == 50 and pf.cfg.pump_real_enabled is True          # a real continua como estava
    assert "saida:alvo50" not in [x["id"] for x in c.get("/api/pump/tune", headers=A).json()["sugestoes"]]   # em teste
    assert c.post("/api/pump/tune/apply", json={"id": "trader:" + HOLDER}, headers=A).json()["ok"]
    assert HOLDER in pf.paused()


def test_browser_cannot_invent_a_suggestion(env):
    c, hub, A, pf = _base(env)
    pf.cfg.pump_real_enabled = True
    stop = pf.cfg.pump_stop_pct
    r = c.post("/api/pump/tune/apply", json={"id": "saida:nao_existe", "mudancas": [{"opcao": "pump_stop_pct", "depois": 1}]}, headers=A).json()
    assert r.get("error") and pf.cfg.pump_stop_pct == stop


def test_no_suggestions_with_real_off(env):
    c, hub, A, pf = _base(env)
    assert c.get("/api/pump/tune", headers=A).json()["sugestoes"] == []


def tr(t, pnl, mint="m"):
    return {"opened_at": _iso(t), "closed_at": _iso(t + 600), "mint": f"{mint}{t}", "pnl_pct": pnl, "pnl_sol": pnl / 1000, "mcap_in": 20}


def test_evolution_only_speaks_with_separated_ranges():
    now = time.time()
    dia = 86400
    L = [(f"{i}a", "Aba", tr(now - i * dia - 3600, 30.0 + i)) for i in range(0, 7)] + [(f"{i}b", "Aba", tr(now - i * dia - 3600, -30.0 - i)) for i in range(8, 14)]
    x = bs.run(L, now)["evolucao"][0]
    assert x["veredito"] == "melhorou" and x["recente"]["n"] == 7
    assert bs.run(L[:3] + L[7:9], now)["evolucao"][0]["veredito"] == "poucos dados"


def test_hour_limit_counts_each_account_apart():
    t0 = 1_800_000_000
    L = [("a", "Aba", tr(t0 + i * 60, -10.0)) for i in range(5)] + [("b", "Aba", tr(t0 + i * 60, 10.0)) for i in range(3)]
    r = {x["limite"]: x for x in bs.run(L, t0 + 7200)["limites"]}
    assert r[2]["n"] == 4 and r[2]["pico_hora"] == 5            # 3 da conta a e 1 da conta b
    assert r[4]["n"] == 1 and 6 not in r and 10 not in r
    assert r[4]["efeito_sol"] == 0.01


def test_hour_limit_frees_again_after_one_hour():
    t0 = 1_800_000_000
    L = [("a", "Aba", tr(t0, -10.0)), ("a", "Aba", tr(t0 + 60, -10.0)), ("a", "Aba", tr(t0 + 3700, -10.0))]
    assert bs.run(L, t0 + 7200)["limites"] == []
