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


def test_peer_config_tela_boost(env):
    """0.32.440: Copiar tela BOOST — o servidor escolhe as opções do BOOST; fica fora a REAL e o que vale para o servidor todo."""
    c = env["c"]
    A, B = tok(UA), tok(UB, "b@x.com")
    c.get("/api/pump", headers=A)
    c.post("/api/pump/settings", json={"pump_bm_stop_pct": 41, "pump_bmr_stop_pct": 22}, headers=B)
    r = c.post("/api/pump/config/peer", json={"user": UB, "tela": "boost", "keys": ["pump_stop_pct"]}, headers=A).json()
    v = r["valores"]
    assert v["pump_bm_stop_pct"] == 41 and v["pump_bmr_stop_pct"] == 22
    assert "pump_stop_pct" not in v                                   # só opções do BOOST
    assert all(k.startswith(("pump_bm_", "pump_bmr_")) for k in v)
    assert "pump_bm_real" not in v and "pump_bm_real_follow" not in v # ligar a REAL é de cada um
    assert "pump_bm_hist_min" not in v and "pump_bm_sybil_on" not in v  # valem para o servidor todo


def test_peer_config_shows_real_switches_read_only(env):
    """0.32.455: a comparação mostra as chaves REAL da outra conta só como ligada/desligada; valores da REAL continuam fora."""
    c, hub = env["c"], env["hub"]
    A, B = tok(UA), tok(UB, "b@x.com")
    c.get("/api/pump", headers=A)
    c.post("/api/pump/settings", json={"pump_real_mirror": False, "pump_real_max_sol": 0.7}, headers=B)
    r = c.post("/api/pump/config/peer", json={"user": UB, "keys": ["pump_copy_enabled", "pump_real_mirror"], "reais": 1}, headers=A).json()
    assert "pump_real_mirror" not in r["valores"] and r["reais"]["pump_real_mirror"] is False
    assert set(r["reais"]) == set(hub.REAL_VIEW) and all(isinstance(v, bool) for v in r["reais"].values())
    assert "pump_real_max_sol" not in r["reais"]
    assert "reais" not in c.post("/api/pump/config/peer", json={"user": UB, "keys": ["pump_copy_enabled"]}, headers=A).json()
