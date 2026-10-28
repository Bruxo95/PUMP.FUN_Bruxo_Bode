"""Administração: gestão de usuários (categoria, bloqueio, desligar real), registro de todos e logs do servidor."""
import asyncio
import json
import logging

from tests.test_api import NOFILTER, UA, UB, W, env, tok  # noqa: F401  (fixture env)

UC = "33333333-3333-3333-3333-333333333333"


def test_only_admin_reaches_admin_routes(env):
    c = env["c"]
    B = tok(UB, "b@x.com")
    for path in ("/api/admin/users", "/api/admin/audit", "/api/admin/logs"):
        assert c.get(path, headers=B).status_code == 403
        assert c.get(path).status_code == 401
    assert c.post(f"/api/admin/users/{UA}", json={"role": "user"}, headers=B).status_code == 403


def test_usar_ou_descartar_routes_are_admin_only(env):
    """0.17.4: Carteiras em estudo, Radar, Relatórios e Aprendizado só para admin também no servidor."""
    c = env["c"]
    A, B = tok(UA), tok(UB, "b@x.com")
    for path in ("/api/pump/study", "/api/pump/study/share-targets", f"/api/pump/study/{W}", "/api/pump/radar",
                 "/api/pump/reports", "/api/pump/aprendizado"):
        assert c.get(path, headers=B).status_code == 403
        assert c.get(path).status_code == 401
        assert c.get(path, headers=A).status_code == 200
    assert c.post("/api/pump/study", json={"wallet": W, "action": "add"}, headers=B).status_code == 403
    assert c.post("/api/pump/study/share", json={"wallet": W, "to": UA}, headers=B).status_code == 403
    assert c.get("/api/pump", headers=B).status_code == 200                          # o resto do painel segue aberto


def test_users_list_has_usage_but_never_keys(env):
    c = env["c"]
    c.post("/api/secrets", json={"name": "solanatracker_api_key", "value": "st-segredo-" + "w" * 30}, headers=tok(UB, "b@x.com"))
    c.post("/api/pump/wallets", json={"wallet": W, "action": "add"}, headers=tok(UB, "b@x.com"))
    r = c.get("/api/admin/users", headers=tok(UA))
    assert r.status_code == 200 and "st-segredo" not in r.text
    users = {u["email"]: u for u in r.json()["users"]}
    assert users["a@x.com"]["role"] == "admin" and users["b@x.com"]["role"] == "user"
    sb = users["b@x.com"]["stats"]
    assert sb["keys"]["solanatracker_api_key"] is True and sb["keys"]["wallet_private_key"] is False
    assert sb["followed"] >= 1 and sb["real_enabled"] is False and users["b@x.com"]["ultimo_acesso"]


def test_change_category_and_keep_at_least_one_admin(env):
    c, db = env["c"], env["db"]
    A = tok(UA)
    r = c.post(f"/api/admin/users/{UA}", json={"role": "user"}, headers=A).json()
    assert "pelo menos um admin" in r["error"]
    r = c.post(f"/api/admin/users/{UB}", json={"role": "admin"}, headers=A).json()
    assert r["ok"] and c.get("/api/me", headers=tok(UB, "b@x.com")).json()["role"] == "admin"
    assert c.get("/api/admin/users", headers=tok(UB, "b@x.com")).status_code == 200      # B virou admin
    r = c.post(f"/api/admin/users/{UB}", json={"role": "user"}, headers=A).json()
    assert r["ok"] and c.get("/api/admin/users", headers=tok(UB, "b@x.com")).status_code == 403
    assert c.post(f"/api/admin/users/{UB}", json={"role": "dono"}, headers=A).json()["error"] == "categoria inválida"
    acoes = [(a["user_id"], a["acao"]) for a in db.tables["audit_log"]]
    assert (UA, "admin: alterou usuário") in acoes and (UB, "alterado pelo administrador") in acoes


def test_block_stops_copying_and_access_unblock_restores(env):
    c, hub = env["c"], env["hub"]
    A, B = tok(UA), tok(UB, "b@x.com")
    c.post("/api/pump/wallets", json={"wallet": W, "action": "add"}, headers=B)
    assert UB in hub.engines
    r = c.post(f"/api/admin/users/{UB}", json={"bloqueado": True}, headers=A).json()
    assert r["ok"] and UB not in hub.engines                            # parou de copiar
    assert c.get("/api/pump", headers=B).status_code == 403
    assert "bloqueada" in c.get("/api/me", headers=B).json()["error"]
    assert c.post(f"/api/admin/users/{UA}", json={"bloqueado": True}, headers=A).json()["error"].startswith("você não pode")
    r = c.post(f"/api/admin/users/{UB}", json={"bloqueado": False}, headers=A).json()
    assert r["ok"] and UB in hub.engines
    d = c.get("/api/pump", headers=B).json()
    assert d["manual"] == [W]                                           # dados dele continuam lá


def test_admin_turns_off_someones_real(env):
    from solders.keypair import Keypair
    c, hub = env["c"], env["hub"]
    hub.real_allowed = True
    B = tok(UB, "b@x.com")
    c.post("/api/secrets", json={"name": "wallet_private_key", "value": str(Keypair())}, headers=B)
    c.post("/api/pump/real", json={"enabled": True, "confirm": "LIGAR"}, headers=B)
    assert c.get("/api/pump", headers=B).json()["real"]["enabled"] is True
    r = c.post(f"/api/admin/users/{UB}", json={"real_off": True}, headers=tok(UA)).json()
    assert r["ok"] and c.get("/api/pump", headers=B).json()["real"]["enabled"] is False
    assert any("DESLIGADA pelo administrador" in e["msg"] for e in c.get("/api/pump", headers=B).json()["events"])


def test_admin_sees_everyones_audit_and_server_logs_masked(env):
    from app.logsafe import add_secret, ring
    c = env["c"]
    h = ring()
    c.post("/api/secrets", json={"name": "rpc_url", "value": "https://rpc.exemplo.com/" + "s" * 32}, headers=tok(UB, "b@x.com"))
    aud = c.get("/api/admin/audit", headers=tok(UA)).json()
    assert [(a["email"], a["acao"]) for a in aud] == [("b@x.com", "salvar chave")]
    assert c.get(f"/api/admin/audit?user_id={UA}", headers=tok(UA)).json() == []
    add_secret("segredo-que-nao-pode-aparecer-123")
    logging.getLogger("teste").warning("tentou logar segredo-que-nao-pode-aparecer-123 e api_key=abcdef123456")
    r = c.get("/api/admin/logs?level=WARNING&q=tentou", headers=tok(UA)).json()
    assert r["logs"] and "segredo-que-nao" not in json.dumps(r) and "abcdef123456" not in json.dumps(r)
    last = r["logs"][-1]["id"]
    novos = c.get(f"/api/admin/logs?after={last}&q=tentou", headers=tok(UA)).json()["logs"]
    assert not [x for x in novos if "tentou logar" in x["msg"]]               # só vem o que é novo
    assert h.counts()["warnings"] >= 1


def test_blocked_users_are_not_loaded_at_start(env):
    hub, db = env["hub"], env["db"]
    db.add_user(UC, "c@x.com")
    db.tables["profiles"][-1]["bloqueado"] = True

    async def go():
        await hub.start()
        loaded = set(hub.engines)
        await hub.stop()
        return loaded
    loaded = asyncio.run(go())
    assert UC not in loaded and {UA, UB} <= loaded


def test_false_gains_review_is_admin_only_and_read_only(env):
    """0.32.1: revisão dos ganhos de +1.900% — só admin, sem rede com check=0, e não muda nenhum trade."""
    c = env["c"]
    A, B = tok(UA), tok(UB, "b@x.com")
    assert c.get("/api/pump/false-gains?check=0", headers=B).status_code == 403
    r = c.get("/api/pump/false-gains?check=0", headers=A)
    assert r.status_code == 200 and r.json()["limite_pct"] == 1900.0 and "items" in r.json()
    assert c.get("/api/pump/false-gains/ai", headers=A).status_code == 200
