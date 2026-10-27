"""Comparar configuração copiada: usuário X (origem) × usuário Y (copiou) depois da cópia (0.31.34)."""
import time
from datetime import datetime, timezone

from tests.test_api import UA, UB, env, tok  # noqa: F401  (fixture env)


def _t(pf, sym, mint, pnl, why="alvo"):
    pf._save_trade({"wallet": "W", "symbol": sym, "mint": mint, "sol_in": 0.1, "pnl_sol": pnl, "pnl_pct": pnl * 1000,
                    "reason": why, "real": False, "opened_at": _iso(time.time() - 60), "closed_at": _iso(time.time() + 5)})


def _iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


def test_compare_after_copy_and_save_for_ai(env):
    c, hub, db = env["c"], env["hub"], env["db"]
    A, B = tok(UA), tok(UB, "b@x.com")
    c.get("/api/pump", headers=B)
    assert c.post(f"/api/admin/users/{UB}/copy-config", json={}, headers=A).json()["ok"]   # A copiou a config de B
    x, y = hub.engines[UB], hub.engines[UA]
    _t(x, "AAA", "A" * 40, 0.05)
    _t(x, "BBB", "B" * 40, 0.02)
    _t(y, "AAA", "A" * 40, -0.01, "stop de perda")
    _t(y, "CCC", "C" * 40, -0.03, "stop de perda")
    lst = c.get("/api/pump/compare", headers=A).json()
    assert lst["copias"] and lst["copias"][0]["eu_sou"] == "copiou"
    oid = lst["copias"][0]["id"]
    r = c.get(f"/api/pump/compare/{oid}", headers=A).json()
    assert r["x"]["trades"] == 2 and r["y"]["trades"] == 2 and r["x"]["pnl_sol"] == 0.07
    assert [g["token"] for g in r["comum"]] == ["AAA"] and r["so_x"][0]["token"] == "BBB" and r["so_y"][0]["token"] == "CCC"
    assert any("tokens que você não pegou" in s for s in r["conclusoes"])
    assert "PERGUNTA PARA A IA" in c.get(f"/api/pump/compare/{oid}/ai", headers=A).json()["texto"]
    assert c.post(f"/api/pump/compare/{oid}/save", json={}, headers=A).json()["ok"]
    assert c.get("/api/pump/compare", headers=A).json()["salvas"][0]["x"]["trades"] == 2
    assert c.get(f"/api/pump/compare/{oid}", headers=B).status_code == 403                 # só admin


def test_compare_hides_other_accounts_copies(env):
    c, db = env["c"], env["db"]
    A = tok(UA)
    db.tables["config_offers"].append({"id": 999, "de_user": UB, "para_user": UB, "status": "aceita", "valores": {},
                                       "respondido_em": "2026-10-27T10:00:00+00:00"})
    assert c.get("/api/pump/compare/999", headers=A).json()["error"]


def test_origin_change_creates_update_offer_with_effect(env):
    c, hub, db = env["c"], env["hub"], env["db"]
    import asyncio
    A, B = tok(UA), tok(UB, "b@x.com")
    c.get("/api/pump", headers=B)
    assert c.post(f"/api/admin/users/{UB}/copy-config", json={}, headers=A).json()["ok"]   # A usa a config idêntica à de B
    assert asyncio.run(hub.config_watch()) == 0                                            # nada mudou ainda
    c.post("/api/pump/settings", json={"pump_stop_pct": 33}, headers=B)                      # B altera
    assert asyncio.run(hub.config_watch()) == 1
    assert asyncio.run(hub.config_watch()) == 0                                            # não repete a mesma alteração
    of = c.get("/api/pump/config/offers", headers=A).json()["offers"]
    up = [o for o in of if o["tipo"] == "atualizacao"][0]
    assert up["mudou"][0]["k"] == "pump_stop_pct" and up["mudou"][0]["agora"] == 33 and "efeito" in up
    assert any("alterou a configuração" in e["msg"] for e in hub.engines[UA].events)
    c.post(f"/api/pump/config/offers/{up['id']}", json={"accept": False}, headers=A)        # não aplica
    assert hub.engines[UA].cfg.pump_stop_pct != 33 and asyncio.run(hub.config_watch()) == 0
    c.post("/api/pump/settings", json={"pump_stop_pct": 35}, headers=B)                      # mudou de novo: avisa outra vez
    assert asyncio.run(hub.config_watch()) == 1
    up = [o for o in c.get("/api/pump/config/offers", headers=A).json()["offers"] if o["tipo"] == "atualizacao"][0]
    c.post(f"/api/pump/config/offers/{up['id']}", json={"accept": True}, headers=A)         # aplica
    assert hub.engines[UA].cfg.pump_stop_pct == 35 and asyncio.run(hub.config_watch()) == 0


def test_no_update_when_receiver_changed_own_config(env):
    c, hub = env["c"], env["hub"]
    import asyncio
    A, B = tok(UA), tok(UB, "b@x.com")
    c.get("/api/pump", headers=B)
    c.post(f"/api/admin/users/{UB}/copy-config", json={}, headers=A)
    c.post("/api/pump/settings", json={"pump_copy_sol": 0.77}, headers=A)                    # A se afastou por conta própria
    c.post("/api/pump/settings", json={"pump_stop_pct": 33}, headers=B)
    assert asyncio.run(hub.config_watch()) == 0


def test_sync_makes_config_identical_to_origin_now(env):
    c, hub = env["c"], env["hub"]
    A, B = tok(UA), tok(UB, "b@x.com")
    c.get("/api/pump", headers=B)
    c.post(f"/api/admin/users/{UB}/copy-config", json={}, headers=A)
    c.post("/api/pump/settings", json={"pump_stop_pct": 44}, headers=A)                      # A ficou diferente
    c.post("/api/pump/settings", json={"pump_copy_sol": 0.5}, headers=B)                     # e B também mudou
    oid = c.get("/api/pump/config/applied", headers=A).json()["applied"][0]["id"]
    r = c.post(f"/api/pump/config/applied/{oid}/sync", json={}, headers=A).json()
    assert r["ok"] and hub.engines[UA].cfg.pump_stop_pct == hub.engines[UB].cfg.pump_stop_pct
    assert hub.engines[UA].cfg.pump_copy_sol == 0.5
    ap = c.get("/api/pump/config/applied", headers=A).json()["applied"]
    assert "idêntica" in ap[0]["parte"] and ap[0]["antes"]["pump_stop_pct"] == 44
    assert c.post(f"/api/pump/config/applied/{oid}/sync", json={}, headers=B).json()["error"]   # só quem recebeu


def test_config_users_lists_who_uses_my_config(env):
    c = env["c"]
    A, B = tok(UA), tok(UB, "b@x.com")
    c.get("/api/pump", headers=B)
    c.post(f"/api/admin/users/{UB}/copy-config", json={}, headers=A)                   # A usa a config de B
    us = c.get("/api/pump/config/users", headers=B).json()["users"]
    assert len(us) == 1 and us[0]["identica"] is True
    c.post("/api/pump/settings", json={"pump_stop_pct": 44}, headers=A)
    us = c.get("/api/pump/config/users", headers=B).json()["users"]
    assert us[0]["identica"] is False and us[0]["mudou"] == 1
    assert c.get("/api/pump/config/users", headers=A).json()["users"] == []


def test_compare_explorar_only_with_times_and_chance(env):
    c, hub = env["c"], env["hub"]
    A, B = tok(UA), tok(UB, "b@x.com")
    c.get("/api/pump", headers=B)
    c.post(f"/api/admin/users/{UB}/copy-config", json={}, headers=A)
    x, y = hub.engines[UB], hub.engines[UA]
    for pf, sym, m, pnl in ((x, "AAA", "A" * 40, 0.05), (x, "BBB", "B" * 40, 0.02), (y, "AAA", "A" * 40, 0.04)):
        pf._save_trade({"wallet": "manual", "symbol": sym, "mint": m, "sol_in": 0.05, "pnl_sol": pnl, "pnl_pct": pnl * 2000,
                        "reason": "alvo", "real": False, "origem": "explorar",
                        "opened_at": _iso(time.time() - (60 if pf is x else 45)), "closed_at": _iso(time.time() + 5)})
    _t(x, "CPY", "C" * 40, 0.09)                                            # cópia de trader: fora da conta do Explorar
    oid = c.get("/api/pump/compare", headers=A).json()["copias"][0]["id"]
    r = c.get(f"/api/pump/compare/{oid}?origem=explorar", headers=A).json()
    assert r["chance"]["de_x_que_y_fez"] == 50.0 and r["chance"]["de_y_que_x_fez"] == 100.0
    m = r["comum"][0]
    assert m["token"] == "AAA" and m["atraso_s"] == 15 and m["abriu_x"] and m["abriu_y"] and m["fechou_y"]


def test_compare_tells_why_the_copy_did_not_enter(env):
    c, hub = env["c"], env["hub"]
    A, B = tok(UA), tok(UB, "b@x.com")
    c.get("/api/pump", headers=B)
    c.post(f"/api/admin/users/{UB}/copy-config", json={}, headers=A)
    x, y = hub.engines[UB], hub.engines[UA]
    _t(x, "R1R", "R" * 40, 0.9)
    y._funnel_note({"mint": "R" * 40, "symbol": "R1R", "pred": {"verdict": "chance alta"}}, "aprendi com os erros: faixa bloqueada", time.time())
    oid = c.get("/api/pump/compare", headers=A).json()["copias"][0]["id"]
    r = c.get(f"/api/pump/compare/{oid}", headers=A).json()
    assert r["so_x"][0]["por_que_nao"].startswith("aprendi com os erros")
    assert y.funnel_dump()["R" * 40]["why"].startswith("aprendi")



def test_compare_real_mode_uses_only_real_trades():
    """0.31.50: no modo Real a comparação usa só os trades da carteira real das duas contas."""
    from app.compare import compare
    em = "2026-10-27T10:00:00+00:00"
    sim = {"mint": "M" * 40, "symbol": "SIM", "pnl_sol": 1.0, "closed_at": "2026-10-27T11:00:00+00:00", "opened_at": em}
    real = dict(sim, mint="R" * 40, symbol="REAL", pnl_sol=0.02, real=True)
    r = compare({"em": em, "valores": {}}, [sim, real], [], {}, {}, "X", "Y", real=True)
    assert r["real"] is True and r["x"]["trades"] == 1 and r["x"]["pnl_sol"] == 0.02
    assert compare({"em": em, "valores": {}}, [sim, real], [], {}, {}, "X", "Y")["x"]["pnl_sol"] == 1.0
