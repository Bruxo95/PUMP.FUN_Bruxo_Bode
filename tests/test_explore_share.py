"""Compartilhar a configuração do Explorar com outro admin (0.31.16): filtros, proteções ou tudo."""
from tests.test_api import UA, UB, env, tok  # noqa: F401  (fixture env)


def test_share_explore_config_by_part(env):
    c, hub, db = env["c"], env["hub"], env["db"]
    A, B = tok(UA), tok(UB, "b@x.com")
    c.post("/api/pump/settings", json={"pump_ex_auto_min_pressure": 75, "pump_ar_stop_pct": 40, "pump_copy_sol": 0.3}, headers=A)
    r = c.post("/api/pump/explore/share", json={"to": UB, "part": "filtros"}, headers=A).json()
    assert r["error"] == "usuário não encontrado"                    # só para admin
    db.set_role(UB, "admin")
    c.get("/api/pump", headers=B)
    r = c.post("/api/pump/explore/share", json={"to": UB, "part": "filtros"}, headers=A).json()
    other = hub.engines[UB]
    assert r["ok"] and other.cfg.pump_ex_auto_min_pressure == 75 and other.cfg.pump_ar_stop_pct == 25
    r = c.post("/api/pump/explore/share", json={"to": UB, "part": "protecoes"}, headers=A).json()
    assert r["ok"] and other.cfg.pump_ar_stop_pct == 40
    assert other.cfg.pump_copy_sol != 0.3                            # fora do Explorar não vai junto
    assert any("recebeu" in e["msg"] for e in other.events)
    assert c.post("/api/pump/explore/share", json={"to": UB, "part": "chaves"}, headers=A).json()["error"]
    assert c.post("/api/pump/explore/share", json={"to": UA, "part": "tudo"}, headers=A).json()["error"]


def test_share_explore_is_admin_only(env):
    c = env["c"]
    assert c.post("/api/pump/explore/share", json={"to": UA, "part": "tudo"}, headers=tok(UB, "b@x.com")).status_code == 403
