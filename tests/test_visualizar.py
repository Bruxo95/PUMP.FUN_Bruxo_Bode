"""Admin vê a tela de um usuário, só leitura e sem registrar (0.31.36)."""
from tests.test_api import UA, UB, env, tok  # noqa: F401  (fixture env)


def test_admin_views_user_screen_read_only(env):
    c, hub, db = env["c"], env["hub"], env["db"]
    A, B = tok(UA), tok(UB, "b@x.com")
    c.post("/api/pump/settings", json={"pump_copy_sol": 0.3}, headers=B)
    n_audit = len(db.tables["audit_log"])
    V = {**A, "X-View-As": UB}
    me = c.get("/api/me", headers=V).json()
    assert me["id"] == UB and me["view_by"] == UA
    assert c.get("/api/pump", headers=V).json()["cfg"]["pump_copy_sol"] == 0.3         # vê o que o usuário vê
    assert c.post("/api/pump/settings", json={"pump_copy_sol": 0.9}, headers=V).status_code == 403
    assert hub.engines[UB].cfg.pump_copy_sol == 0.3                                        # nada mudou
    assert c.get("/api/secrets", headers=V).status_code == 403                             # chaves não abrem
    assert c.get("/api/audit", headers=V).status_code == 403
    assert c.get("/api/admin/users", headers=V).status_code == 403
    assert len(db.tables["audit_log"]) == n_audit                                          # não registra
    assert c.get("/api/me", headers={**B, "X-View-As": UA}).status_code == 403             # usuário comum não pode
