"""0.32.151: Ajustes de Abas de trades compara com outro usuário (só leitura, só admin, sem opções da real)."""
from tests.test_api import UA, UB, env, tok  # noqa: F401  (fixture env)


def test_peer_config_read_only_without_real(env):
    c, hub = env["c"], env["hub"]
    A, B = tok(UA), tok(UB, "b@x.com")
    c.get("/api/pump", headers=A)
    c.post("/api/pump/settings", json={"pump_stop_pct": 33, "pump_real_max_sol": 0.7}, headers=B)
    r = c.post("/api/pump/config/peer", json={"user": UB, "keys": ["pump_stop_pct", "pump_real_max_sol", "nao_existe"]}, headers=A).json()
    assert r["valores"] == {"pump_stop_pct": 33}                      # a real e o que não existe ficam fora
    assert hub.engines[UA].cfg.pump_stop_pct != 33                    # só leitura
    assert c.post("/api/pump/config/peer", json={"user": UA, "keys": ["pump_stop_pct"]}, headers=A).json()["error"]
    assert c.post("/api/pump/config/peer", json={"user": UA, "keys": ["pump_stop_pct"]}, headers=B).status_code == 403
