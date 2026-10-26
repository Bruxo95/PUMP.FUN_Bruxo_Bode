"""Ajuste automático (0.31.14): aplica a regra de saída que os fantasmas mostram render mais, desfaz se piorar e pausa
trader que só dá prejuízo. Só com a execução real desligada."""
import time

from tests.test_api import UA, UB, env, tok  # noqa: F401  (fixture env)
from tests.test_daily import _iso

HOLDER = "dmuX".ljust(44, "1")


def _trades(pf, n, pnl, at, wallet=HOLDER):
    for i in range(n):
        pf._save_trade({"wallet": wallet, "symbol": f"T{i}", "mint": "M" * 40, "sol_in": 0.1, "pnl_sol": pnl,
                        "pnl_pct": pnl * 1000, "reason": "stop de perda", "hold_s": 60, "closed_at": _iso(at), "real": False})


def test_variant_settings_and_pick():
    from app.autotune import pick_exit, variant_settings
    s = variant_settings("alvo50")
    assert s["pump_tp_pct"] == 50 and s["pump_trail_enabled"] is False and s["pump_stop_pct"] == 40
    assert variant_settings("trail_justo")["pump_trail_start_pct"] == 10.0
    assert variant_settings("sem_trader") is None                    # não existe nas opções
    snap = {"yours": {"trades": 40, "pnl_sol": -0.4}, "variants": [
        {"id": "alvo50", "nome": "Alvo", "trades": 40, "pnl_sol": 0.8}, {"id": "stop20", "nome": "S", "trades": 10, "pnl_sol": 5.0},
        {"id": "sem_trader", "nome": "X", "trades": 40, "pnl_sol": 9.0}]}
    assert pick_exit(snap, 3, set())["id"] == "alvo50"              # stop20 sem base; sem_trader não dá para aplicar
    assert pick_exit(snap, 1, set()) is None                         # fantasmas com menos de 2 dias
    assert pick_exit(snap, 3, {"alvo50"}) is None                    # rejeitada recentemente


def test_tune_applies_tests_and_reverts(env):
    c, hub, db = env["c"], env["hub"], env["db"]
    A = tok(UA)
    c.get("/api/pump", headers=A)
    pf = hub.engines[UA]
    now = time.time()
    pf.ghosts.since = _iso(now - 72 * 3600)
    pf.ghosts.stats = {"alvo50": {"trades": 40, "wins": 30, "pnl_sol": 0.8, "invested_sol": 4.0, "best_sum": 0}}
    _trades(pf, 30, -0.01, now - 50 * 3600)
    r = c.post("/api/pump/tune/run", json={}, headers=A).json()
    assert r["ok"] and "aplicou" in r["acoes"] and "pausou" in r["acoes"]
    assert pf.cfg.pump_tp_pct == 50 and pf.cfg.pump_trail_enabled is False and HOLDER in pf.paused()
    r = c.post("/api/pump/tune/run", json={}, headers=A).json()
    assert r["testando"] and r["acoes"] == []                        # em teste: não muda de novo nem pausa de novo
    info = c.get("/api/pump/tune", headers=A).json()
    assert info["testing"]["nome"] and info["log"][0]["acao"] in ("aplicou", "pausou")
    for row in db.tables["auto_tune_log"]:                           # finge que a regra entrou 55 h atrás
        row["em"] = _iso(now - 55 * 3600)
    _trades(pf, 20, 0.005, now - 80 * 3600, "Bom".ljust(44, "1"))    # antes da regra: estava melhor
    r = c.post("/api/pump/tune/run", json={}, headers=A).json()
    assert "desfez" in r["acoes"] and "aplicou" not in r["acoes"]
    assert pf.cfg.pump_tp_pct == 0 and pf.cfg.pump_trail_enabled is True
    assert any("Ajuste automático: desfez" in e["msg"] for e in pf.events)


def test_tune_stops_with_real_on_and_is_admin_only(env):
    c, hub = env["c"], env["hub"]
    A = tok(UA)
    c.get("/api/pump", headers=A)
    hub.engines[UA].cfg.pump_real_enabled = True
    r = c.post("/api/pump/tune/run", json={}, headers=A).json()
    assert r["ok"] is False and "real" in r["motivo"]
    assert c.post("/api/pump/tune/run", json={}, headers=tok(UB, "b@x.com")).status_code == 403
