"""0.32.199 (pedido do dono): histórico da configuração e Voltar para uma versão. Sem internet."""
from app import cfghist
from tests.test_api import UA, env, tok  # noqa: F401  (fixture env)


def test_diff_and_snapshot_never_keep_the_real_switch():
    assert "pump_real_enabled" not in cfghist.snap({"pump_real_enabled": True, "pump_stop_pct": 30})
    assert cfghist.diff({"a": 1, "b": 2}, {"a": 1, "b": 3}) == [{"k": "b", "de": 2, "para": 3}]


def test_changes_become_versions_and_can_go_back(env):
    c, hub, db = env["c"], env["hub"], env["db"]
    A = tok(UA)
    c.get("/api/me", headers=A)
    c.post("/api/pump/settings", json={"pump_stop_pct": 30, "pump_real_max_sol": 0.05}, headers=A)
    pf = hub.engines[UA]
    v1 = c.get("/api/pump/config/historico", headers=A).json()
    n1 = v1["atual"]
    pf._cfg_row["t"] = 0                                     # passou o tempo de juntar
    c.post("/api/pump/settings", json={"pump_stop_pct": 45, "pump_real_max_sol": 0.2}, headers=A)
    pf._cfg_row["t"] = 0
    v2 = c.get("/api/pump/config/historico", headers=A).json()
    assert v2["atual"] == n1 + 1 and v2["versoes"][0]["n"] == n1 + 1 and {"k": "pump_stop_pct", "de": 30, "para": 45} in [
        {k: x[k] for k in ("k", "de", "para")} for x in v2["versoes"][0]["mudou"]]
    d = c.get(f"/api/pump/config/historico/diff?n={n1}", headers=A).json()
    assert [x["k"] for x in d["mudaria"]] == ["pump_stop_pct"] and [x["k"] for x in d["fora"]] == ["pump_real_max_sol"]
    r = c.post("/api/pump/config/historico/voltar", json={"n": n1}, headers=A).json()
    assert r["ok"] and r["mudou"] == 1 and pf.cfg.pump_stop_pct == 30 and pf.cfg.pump_real_max_sol == 0.2     # a REAL não volta
    v3 = c.get("/api/pump/config/historico", headers=A).json()
    assert v3["versoes"][0]["origem"].startswith("você voltou para") and any(a["acao"] == "configuração: voltou para outra versão" for a in db.tables["audit_log"])
    assert c.post("/api/pump/config/historico/voltar", json={"n": 9999}, headers=A).json()["error"]
    assert c.post("/api/pump/config/historico/voltar", json={}, headers=A).json()["error"]


def test_screen_edits_in_a_row_become_one_version(env):
    c, hub = env["c"], env["hub"]
    A = tok(UA)
    c.post("/api/pump/settings", json={"pump_stop_pct": 31}, headers=A)
    n = c.get("/api/pump/config/historico", headers=A).json()["atual"]
    c.post("/api/pump/settings", json={"pump_stop_pct": 32}, headers=A)
    assert c.get("/api/pump/config/historico", headers=A).json()["atual"] == n


def test_go_back_only_the_chosen_tabs(env):
    """0.32.200 (pedido do dono): voltar só as abas marcadas; as outras opções ficam como estão."""
    c, hub = env["c"], env["hub"]
    A = tok(UA)
    c.post("/api/pump/settings", json={"pump_stop_pct": 30, "pump_tp_pct": 100}, headers=A)
    pf = hub.engines[UA]
    n1 = c.get("/api/pump/config/historico", headers=A).json()["atual"]
    pf._cfg_row["t"] = 0
    c.post("/api/pump/settings", json={"pump_stop_pct": 45, "pump_tp_pct": 0}, headers=A)
    r = c.post("/api/pump/config/historico/voltar", json={"n": n1, "keys": ["pump_stop_pct"]}, headers=A).json()
    assert r["ok"] and r["mudou"] == 1 and pf.cfg.pump_stop_pct == 30 and pf.cfg.pump_tp_pct == 0
    v = c.get("/api/pump/config/historico", headers=A).json()["versoes"][0]
    assert v["origem"].endswith("só as abas escolhidas") and [x["k"] for x in v["mudou"]] == ["pump_stop_pct"] and v["mudou"][0]["volta"] is True
    assert c.post("/api/pump/config/historico/voltar", json={"n": n1, "keys": ["pump_real_max_sol"]}, headers=A).json()["mudou"] == 0    # a REAL nunca volta
    assert c.post("/api/pump/config/historico/voltar", json={"n": n1, "keys": "pump_stop_pct"}, headers=A).json()["error"]
    assert c.post("/api/pump/config/historico/voltar", json={"n": n1}, headers=A).json()["mudou"] == 1 and pf.cfg.pump_tp_pct == 100     # sem keys volta tudo


def test_list_says_which_changes_can_go_back(env):
    c, hub = env["c"], env["hub"]
    A = tok(UA)
    c.post("/api/pump/settings", json={"pump_real_max_sol": 0.05}, headers=A)
    hub.engines[UA]._cfg_row["t"] = 0
    c.post("/api/pump/settings", json={"pump_real_max_sol": 0.2}, headers=A)
    m = c.get("/api/pump/config/historico", headers=A).json()["versoes"][0]["mudou"]
    assert m[0]["k"] == "pump_real_max_sol" and m[0]["volta"] is False


def test_real_takes_the_sim_values_as_a_version_and_can_undo(env):
    """0.32.206 (pedido do dono): aplicar a configuração da FICTÍCIA na REAL vira versão; Desfazer devolve só esses valores."""
    c, hub, db = env["c"], env["hub"], env["db"]
    A = tok(UA)
    c.post("/api/pump/settings", json={"pump_copy_sol": 0.1, "pump_max_open": 20, "pump_copy_other": True,
                                        "pump_real_max_sol": 0.05, "pump_real_max_open": 5, "pump_copy_other_real": False}, headers=A)
    pf = hub.engines[UA]
    pf._cfg_row["t"] = 0
    r = c.post("/api/pump/config/real-da-ficticia", json={}, headers=A).json()
    assert r["ok"] and r["mudou"] == 3 and r["versao"]
    assert pf.cfg.pump_real_max_sol == 0.1 and pf.cfg.pump_real_max_open == 20 and pf.cfg.pump_copy_other_real is True
    assert not pf.cfg.pump_real_enabled                                           # nunca liga a REAL
    v = c.get("/api/pump/config/historico", headers=A).json()["versoes"][0]
    assert v["n"] == r["versao"] and v["origem"] == cfghist.REAL_DA_FICTICIA
    assert c.post("/api/pump/config/real-da-ficticia", json={}, headers=A).json()["mudou"] == 0     # já igual
    u = c.post("/api/pump/config/real-da-ficticia/desfazer", json={"n": r["versao"]}, headers=A).json()
    assert u["ok"] and u["mudou"] == 3 and pf.cfg.pump_real_max_sol == 0.05 and pf.cfg.pump_real_max_open == 5 and pf.cfg.pump_copy_other_real is False
    assert pf.cfg.pump_copy_sol == 0.1                                            # a FICTÍCIA fica como está
    assert any(a["acao"] == "configuração: desfez REAL igual à FICTÍCIA" for a in db.tables["audit_log"])
    assert c.post("/api/pump/config/real-da-ficticia/desfazer", json={"n": 1}, headers=A).json().get("error")   # versão de outra origem
    assert c.post("/api/pump/config/real-da-ficticia/desfazer", json={"n": "x"}, headers=A).json()["error"]


def test_compare_apply_is_its_own_version_and_can_go_back(env):
    """0.32.221 (pedido do dono): "deixar igual" do Comparar vira uma versão própria (com o nome de quem) e volta pelo histórico."""
    c = env["c"]
    A = tok(UA)
    c.post("/api/pump/settings", json={"pump_stop_pct": 31}, headers=A)
    n0 = c.get("/api/pump/config/historico", headers=A).json()["atual"]
    r = c.post("/api/pump/settings", json={"pump_stop_pct": 25, "_why": "deixou igual à de Bruxo (Comparar)"}, headers=A).json()
    assert not r.get("errors")
    h = c.get("/api/pump/config/historico", headers=A).json()
    assert h["atual"] == n0 + 1 and h["versoes"][0]["origem"] == "você deixou igual à de Bruxo (Comparar)"
    c.post("/api/pump/config/historico/voltar", json={"n": n0, "keys": ["pump_stop_pct"]}, headers=A)
    assert env["hub"].engines[UA].cfg.pump_stop_pct == 31


def test_adding_by_hand_takes_the_wallet_from_the_ia(env):
    """0.32.224 (dono, dmuX 05/11): adicionar à mão uma carteira que a IA do estudo tinha posto deixa de ser "da IA"."""
    from tests.test_api import W
    c, hub = env["c"], env["hub"]
    c.get("/api/pump", headers=tok(UA))
    pf = hub.engines[UA]
    pf.ia_added = [W]
    r = c.post("/api/pump/wallets", json={"wallet": W, "action": "add"}, headers=tok(UA)).json()
    assert r.get("ok") and W in pf.manual and W not in pf.ia_added
