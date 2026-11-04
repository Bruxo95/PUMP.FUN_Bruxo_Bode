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
