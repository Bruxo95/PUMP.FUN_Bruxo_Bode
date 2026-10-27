"""Compartilhar configuração (0.31.16 Explorar, 0.31.17 Configurações): vira um convite que a pessoa aceita ou recusa."""
from tests.test_api import UA, UB, env, tok  # noqa: F401  (fixture env)


def test_share_explore_config_by_part_needs_accept(env):
    c, hub, db = env["c"], env["hub"], env["db"]
    A, B = tok(UA), tok(UB, "b@x.com")
    c.post("/api/pump/settings", json={"pump_ex_auto_min_pressure": 75, "pump_ar_stop_pct": 40, "pump_copy_sol": 0.3}, headers=A)
    db.set_role(UB, "admin")
    c.get("/api/pump", headers=B)
    other = hub.engines[UB]
    r = c.post("/api/pump/explore/share", json={"to": UB, "part": "filtros"}, headers=A).json()
    assert r["ok"] and other.cfg.pump_ex_auto_min_pressure == 60       # nada muda antes de aceitar
    of = c.get("/api/pump/config/offers", headers=B).json()["offers"]
    assert len(of) == 1 and "filtros" in of[0]["parte"] and "pump_ex_auto_min_pressure" in of[0]["nomes"]
    assert of[0]["valores"]["pump_ex_auto_min_pressure"] == 75                        # a tela mostra seu valor → enviado
    assert c.get("/api/pump/config/offers", headers=A).json()["offers"] == []          # só quem recebe vê
    assert c.post(f"/api/pump/config/offers/{of[0]['id']}", json={"accept": True}, headers=A).json()["error"]
    r = c.post(f"/api/pump/config/offers/{of[0]['id']}", json={"accept": True}, headers=B).json()
    assert r["ok"] and other.cfg.pump_ex_auto_min_pressure == 75 and other.cfg.pump_ar_stop_pct == 25
    ap = c.get("/api/pump/config/applied", headers=B).json()["applied"]                 # 0.31.31: antes × enviado
    assert ap[0]["valores"]["pump_ex_auto_min_pressure"] == 75 and ap[0]["antes"]["pump_ex_auto_min_pressure"] == 60
    assert c.get("/api/pump/config/applied", headers=A).json()["applied"] == []
    assert not any(UB in (a["detalhe"] or "") for a in c.get("/api/audit", headers=A).json())   # nome, não o código
    assert c.get("/api/pump/config/offers", headers=B).json()["offers"] == []
    c.post("/api/pump/explore/share", json={"to": UB, "part": "protecoes"}, headers=A)
    of = c.get("/api/pump/config/offers", headers=B).json()["offers"]
    c.post(f"/api/pump/config/offers/{of[0]['id']}", json={"accept": False}, headers=B)
    assert other.cfg.pump_ar_stop_pct == 25 and other.cfg.pump_copy_sol != 0.3        # recusou: nada muda
    assert c.post("/api/pump/explore/share", json={"to": UB, "part": "chaves"}, headers=A).json()["error"]
    assert c.post("/api/pump/explore/share", json={"to": UA, "part": "tudo"}, headers=A).json()["error"]


def test_share_config_section_and_all_without_real_or_telegram(env):
    c, hub = env["c"], env["hub"]
    A, B = tok(UA), tok(UB, "b@x.com")
    c.post("/api/pump/settings", json={"pump_copy_sol": 0.3, "pump_stop_pct": 25, "pump_real_max_sol": 0.9, "pump_tg_on": True}, headers=A)
    c.get("/api/pump", headers=B)
    other = hub.engines[UB]
    assert any(u["user_id"] == UB for u in c.get("/api/pump/config/share-targets", headers=A).json()["users"])
    r = c.post("/api/pump/config/share", json={"to": UB, "parte": "Configurações · Cópia", "keys": ["pump_copy_sol", "pump_real_max_sol"]}, headers=A).json()
    assert r["ok"] and r["opcoes"] == 1                                   # nada da carteira real
    r = c.post("/api/pump/config/share", json={"to": UB, "all": True}, headers=A).json()
    of = c.get("/api/pump/config/offers", headers=B).json()["offers"]
    tudo = next(o for o in of if o["parte"] == "toda a configuração")
    assert not any("real" in k or k.startswith(("pump_tg_", "pump_ex_auto_", "pump_ar_")) for k in tudo["nomes"])  # B não é admin
    c.post(f"/api/pump/config/offers/{tudo['id']}", json={"accept": True}, headers=B)
    assert other.cfg.pump_copy_sol == 0.3 and other.cfg.pump_stop_pct == 25 and other.cfg.pump_real_max_sol != 0.9
    assert not other.cfg.pump_tg_on
    assert any("quer compartilhar" in e["msg"] for e in other.events)
    me = hub.engines[UA]                                                   # quem enviou é avisado e fica no registro
    assert any("aceitou e aplicou seu convite" in e["msg"] for e in me.events)
    assert any(a["user_id"] == UA and a["acao"] == "convite de configuração aceito" for a in env["db"].tables["audit_log"])


def test_admin_copies_user_config_and_sees_trades(env):
    c, hub, db = env["c"], env["hub"], env["db"]
    A, B = tok(UA), tok(UB, "b@x.com")
    c.post("/api/pump/settings", json={"pump_copy_sol": 0.3, "pump_stop_pct": 22}, headers=B)
    c.get("/api/pump", headers=A)
    r = c.post(f"/api/admin/users/{UB}/copy-config", json={}, headers=A).json()
    assert r["ok"] and hub.engines[UA].cfg.pump_copy_sol == 0.3 and hub.engines[UA].cfg.pump_stop_pct == 22
    ap = c.get("/api/pump/config/applied", headers=A).json()["applied"]
    assert ap and ap[0]["antes"]["pump_copy_sol"] != 0.3                                  # "ver o que mudou" funciona
    assert not any("aceitou" in e["msg"] for e in hub.engines[UB].events)                  # B não enviou convite
    assert c.post(f"/api/admin/users/{UA}/copy-config", json={}, headers=A).json()["error"]
    assert c.post(f"/api/admin/users/{UB}/copy-config", json={}, headers=B).status_code == 403
    hub.engines[UB]._save_trade({"wallet": "W", "symbol": "WIN", "mint": "M" * 40, "sol_in": 0.1, "pnl_sol": 0.05, "pnl_pct": 50.0,
                                 "reason": "alvo", "real": False})
    t = c.get(f"/api/admin/users/{UB}/trades", headers=A).json()["trades"]
    assert t[0]["token"] == "WIN" and t[0]["pnl_sol"] == 0.05
    assert c.get(f"/api/admin/users/{UA}/trades", headers=B).status_code == 403


def test_share_is_admin_only(env):
    c = env["c"]
    B = tok(UB, "b@x.com")
    assert c.post("/api/pump/explore/share", json={"to": UA, "part": "tudo"}, headers=B).status_code == 403
    assert c.post("/api/pump/config/share", json={"to": UA, "all": True}, headers=B).status_code == 403
