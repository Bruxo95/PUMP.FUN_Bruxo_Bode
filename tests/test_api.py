"""Etapa 5: login (JWT do Supabase), API por usuário, chaves nunca devolvidas, execução real protegida.
Inclui os 2 testes da API do projeto original (test_pump_real_disabled_by_default_and_api e
test_pump_wallet_endpoint_without_wallet), adaptados para o modo multiusuário. Nada usa internet."""
import asyncio
import base64
import json
import logging
import os
import time

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient

from tests.fakes import FakeREST

SB = "https://projetoteste.supabase.co"
SECRET = "segredo-jwt-de-teste-" + "x" * 20
UA = "11111111-1111-1111-1111-111111111111"
UB = "22222222-2222-2222-2222-222222222222"
W = "TraderGood1111111111111111111111111111111"
W2 = "TraderBeta1111111111111111111111111111111"


def tok(uid, email="a@x.com", exp=3600, **kw):
    c = {"sub": uid, "email": email, "aud": "authenticated", "role": "authenticated", "iss": SB + "/auth/v1",
         "exp": int(time.time()) + exp, "user_metadata": {"full_name": email.split("@")[0]}, **kw}
    return {"Authorization": "Bearer " + jwt.encode(c, SECRET, algorithm="HS256")}


NOFILTER = {"pump_min_vol_h1_usd": 0, "pump_min_txns_h1": 0, "pump_max_top10_pct": 0, "pump_min_mcap_usd": 0,
            "pump_min_wallet_usd": 0}


def _flush(hub):
    async def go():
        for e in hub.engines.values():
            await e.store.flush()
    asyncio.run(go())


def net_handler(req: httpx.Request):
    if "solanatracker" in req.url.host:
        tr = [{"wallet": f"Top{i}".ljust(44, "1"), "period": {"realized": 9000 - i}, "winRate": 0.7,
               "counts": {"trades": 2000}} for i in range(3)]
        return httpx.Response(200, json={"traders": tr})
    return httpx.Response(404)


@pytest.fixture
def env(monkeypatch):
    from app.api import create_app
    from app.auth import Auth
    from app.crypto import SecretBox
    from app.hub import PumpHub
    from app.settings import ServerConfig
    monkeypatch.setenv("SUPABASE_URL", SB)
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-publica")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role-SECRETA-123456")
    monkeypatch.setenv("APP_ENCRYPTION_KEY", base64.b64encode(os.urandom(32)).decode())
    monkeypatch.delenv("PUMP_REAL_ALLOWED", raising=False)
    cfg = ServerConfig()
    db = FakeREST()
    db.add_user(UA, "a@x.com")
    db.add_user(UB, "b@x.com")
    http = httpx.AsyncClient(transport=httpx.MockTransport(net_handler))
    hub = PumpHub(cfg, http, db, SecretBox(cfg.encryption_key))
    auth = Auth(SB, cfg.supabase_anon_key, http, SECRET)
    app = create_app(hub, auth, cfg)
    return {"c": TestClient(app), "hub": hub, "db": db, "cfg": cfg, "app": app}


# ---------------------------------------------------------------- do projeto original (adaptados)
def test_pump_real_disabled_by_default_and_api(env):
    c, hub = env["c"], env["hub"]
    d = c.get("/api/pump", headers=tok(UA)).json()
    assert d["real"]["enabled"] is False and d["wallet"]["start_sol"] == 5.0
    r = c.post("/api/pump/wallets", json={"wallet": W, "action": "add"}, headers=tok(UA)).json()
    assert r.get("ok") and W in c.get("/api/pump", headers=tok(UA)).json()["manual"]
    assert c.post("/api/pump/wallets", json={"wallet": "x", "action": "add"}, headers=tok(UA)).json().get("error")
    r = c.post("/api/secrets", json={"name": "pumpportal_api_key", "value": "k" * 40}, headers=tok(UA)).json()
    assert r.get("ok") and "k" * 40 not in c.get("/api/pump", headers=tok(UA)).text
    assert "k" * 40 not in c.get("/api/secrets", headers=tok(UA)).text
    assert c.get("/api/pump", headers=tok(UA)).json()["real"]["api_key_set"] is True
    rl = asyncio.run(hub.engine(UA)).real
    assert asyncio.run(rl.buy("MintX".ljust(40, "1"), {}))["reason"] == "execução real desligada"


def test_pump_wallet_endpoint_without_wallet(env):
    w = env["c"].get("/api/pump/wallet", headers=tok(UA)).json()
    assert w["configured"] is False and "usdc_in_sol" in w


# ---------------------------------------------------------------- login
def test_requires_valid_supabase_login(env):
    c = env["c"]
    h = c.get("/health").json()
    assert h["ok"] is True and h["version"] == __import__("app.version").version.VERSION and h["no_ar_desde"]
    pub = c.get("/api/public-config").json()
    assert pub["supabase_url"] == SB and pub["supabase_anon_key"] == "anon-publica" and "SECRETA" not in json.dumps(pub)
    for path in ("/api/pump", "/api/me", "/api/secrets", "/api/pump/wallet", "/api/audit"):
        assert c.get(path).status_code == 401
    assert c.get("/api/pump", headers={"Authorization": "Bearer lixo"}).status_code == 401
    assert c.get("/api/pump", headers=tok(UA, exp=-120)).status_code == 401                 # expirado
    bad = jwt.encode({"sub": UA, "aud": "authenticated", "exp": int(time.time()) + 60, "iss": SB + "/auth/v1"},
                     "outro-segredo-" + "y" * 30, algorithm="HS256")
    assert c.get("/api/pump", headers={"Authorization": "Bearer " + bad}).status_code == 401  # assinatura falsa
    other_iss = tok(UA, iss="https://outro.supabase.co/auth/v1")
    assert c.get("/api/pump", headers=other_iss).status_code == 401                          # outro projeto
    me = c.get("/api/me", headers=tok(UA)).json()
    assert me["id"] == UA and me["role"] == "admin"
    assert c.get("/api/me", headers=tok(UB, "b@x.com")).json()["role"] == "user"


def test_jwks_es256_tokens_are_verified():
    from cryptography.hazmat.primitives.asymmetric import ec
    from app.auth import Auth, AuthError
    key = ec.generate_private_key(ec.SECP256R1())
    jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key.public_key()))
    jwk.update(kid="k1", alg="ES256", use="sig")
    calls = []

    def h(req):
        calls.append(req.url.path)
        return httpx.Response(200, json={"keys": [jwk]})
    a = Auth(SB, "anon", httpx.AsyncClient(transport=httpx.MockTransport(h)))
    good = jwt.encode({"sub": UA, "aud": "authenticated", "role": "authenticated", "iss": SB + "/auth/v1",
                       "exp": int(time.time()) + 60}, key, algorithm="ES256", headers={"kid": "k1"})
    assert asyncio.run(a.verify(good))["sub"] == UA and calls == ["/auth/v1/.well-known/jwks.json"]
    other = ec.generate_private_key(ec.SECP256R1())
    forged = jwt.encode({"sub": UB, "aud": "authenticated", "iss": SB + "/auth/v1", "exp": int(time.time()) + 60},
                        other, algorithm="ES256", headers={"kid": "k1"})
    with pytest.raises(AuthError):
        asyncio.run(a.verify(forged))


# ---------------------------------------------------------------- isolamento pela API
def test_two_users_only_see_their_own_data(env):
    c, db = env["c"], env["db"]
    A, B = tok(UA), tok(UB, "b@x.com")
    c.post("/api/pump/wallets", json={"wallet": W, "action": "add"}, headers=A)
    c.post("/api/pump/wallets", json={"wallet": W2, "action": "add"}, headers=B)
    c.post("/api/pump/settings", json={"pump_copy_sol": 0.33, **NOFILTER}, headers=A)
    ea = asyncio.run(env["hub"].engine(UA))
    m = "Iso".ljust(40, "1") + "pump"
    ea.on_message({"txType": "buy", "traderPublicKey": W, "mint": m, "solAmount": 1.0, "tokenAmount": 1e6,
                   "vSolInBondingCurve": 30, "vTokensInBondingCurve": 3e7, "marketCapSol": 900})
    da, dbb = c.get("/api/pump", headers=A).json(), c.get("/api/pump", headers=B).json()
    assert da["manual"] == [W] and dbb["manual"] == [W2]
    assert len(da["positions"]) == 1 and dbb["positions"] == [] and dbb["feed"] == []
    assert da["cfg"]["pump_copy_sol"] == 0.33 and dbb["cfg"]["pump_copy_sol"] == 0.1
    pid = da["positions"][0]["id"]
    assert c.post("/api/pump/close", json={"id": pid}, headers=B).json()["error"] == "posição não encontrada"
    assert len(c.get("/api/pump", headers=A).json()["positions"]) == 1
    c.post("/api/secrets", json={"name": "rpc_url", "value": "https://meu-rpc.exemplo.com/?api-key=" + "z" * 30}, headers=A)
    assert c.get("/api/secrets", headers=A).json()["keys"]["rpc_url"]["configured"] is True
    assert c.get("/api/secrets", headers=B).json()["keys"]["rpc_url"]["configured"] is False
    assert [a["acao"] for a in c.get("/api/audit", headers=B).json()] == []
    assert [a["acao"] for a in c.get("/api/audit", headers=A).json()] == ["salvar chave"]
    _flush(env["hub"])
    owners = {r["user_id"] for r in db.tables["pump_positions"]}
    assert owners == {UA}


def test_admin_status_only_for_admin_and_never_keys(env):
    c = env["c"]
    c.post("/api/secrets", json={"name": "solanatracker_api_key", "value": "st-" + "q" * 30}, headers=tok(UA))
    assert c.get("/api/admin/status", headers=tok(UB, "b@x.com")).status_code == 403
    r = c.get("/api/admin/status", headers=tok(UA))
    assert r.status_code == 200 and r.json()["users_total"] == 2 and "q" * 30 not in r.text


def test_system_keys_let_everyone_view_and_personal_key_wins(env):
    c, db, hub = env["c"], env["db"], env["hub"]
    A, B = tok(UA), tok(UB, "b@x.com")
    SYS = "st-SISTEMA-" + "s" * 30
    # só admin mexe nas chaves do sistema
    assert c.get("/api/admin/keys", headers=B).status_code == 403
    assert c.post("/api/admin/keys", json={"name": "solanatracker_api_key", "value": SYS}, headers=B).status_code == 403
    assert c.post("/api/admin/keys", json={"name": "wallet_private_key", "value": "x" * 40}, headers=A).json()["error"]
    assert c.post("/api/admin/keys", json={"name": "solanatracker_api_key", "value": SYS}, headers=A).json()["ok"]
    for name in ("pumpportal_api_key", "jupiter_api_key"):
        assert c.post("/api/admin/keys", json={"name": name, "value": "k-" + name + "-" + "z" * 20}, headers=A).json()["ok"]
    assert c.post("/api/admin/keys", json={"name": "rpc_url", "value": "https://helius.com/?api-key=" + "z" * 20}, headers=A).json()["ok"]
    view = c.get("/api/admin/keys", headers=A)
    assert all(v["configured"] for v in view.json()["keys"].values()) and SYS not in view.text
    assert SYS not in json.dumps(db.tables["app_secrets"])                       # no banco só a cifra
    # B não tem chave nenhuma: vê o ranking pela chave do sistema, sem nunca ver a chave
    d = c.post("/api/pump/leaderboard", json={"days": 7}, headers=B).json()
    assert d["count"] == 3 and SYS not in json.dumps(d)
    snap = c.get("/api/pump", headers=B)
    assert snap.json()["lb_status"]["own_key"] is False and SYS not in snap.text
    sec = c.get("/api/secrets", headers=B).json()["keys"]
    st = sec["solanatracker_api_key"]
    assert st["configured"] is False and st["system"] is True and st["link"].startswith("https://www.solanatracker.io")
    assert sec["wallet_private_key"]["system"] is False                          # carteira nunca é do sistema
    # chave do sistema não vira chave do usuário: execução e trocas continuam só com o que é dele
    eb = asyncio.run(hub.engine(UB))
    assert eb.real.api_key() == "" and eb.keys.get("jupiter_api_key") == ""
    assert eb.jw.dex is hub.public_quoter and hub.market.jup is not hub.public_quoter
    # B põe a própria chave: passa a usar a dele
    c.post("/api/secrets", json={"name": "solanatracker_api_key", "value": "st-da-B-" + "b" * 30}, headers=B)
    assert c.get("/api/pump", headers=B).json()["lb_status"]["own_key"] is True
    assert c.get("/api/secrets", headers=B).json()["keys"]["solanatracker_api_key"]["configured"] is True
    # remover a do sistema: quem não tem a própria deixa de ver; B (com a dele) continua
    c.post("/api/admin/keys/remove", json={"name": "solanatracker_api_key"}, headers=A)
    assert c.get("/api/secrets", headers=A).json()["keys"]["solanatracker_api_key"]["system"] is False
    assert c.get("/api/pump", headers=B).json()["lb_status"]["key_set"] is True
    acoes = [a["acao"] for a in db.tables["audit_log"] if a["user_id"] == UA]
    assert acoes.count("admin: salvar chave do sistema") == 4 and "admin: remover chave do sistema" in acoes


def test_system_keys_survive_restart(env):
    from app.crypto import SecretBox
    from app.hub import PumpHub
    c, db, cfg = env["c"], env["db"], env["cfg"]
    c.post("/api/admin/keys", json={"name": "solanatracker_api_key", "value": "st-SISTEMA-" + "r" * 30}, headers=tok(UA))
    hub2 = PumpHub(cfg, httpx.AsyncClient(transport=httpx.MockTransport(net_handler)), db, SecretBox(cfg.encryption_key))

    async def go():
        await hub2.refresh_shared_key()
        return hub2.shared_st_key
    assert asyncio.run(go()) == "st-SISTEMA-" + "r" * 30


# ---------------------------------------------------------------- execução real e chaves
def test_real_needs_server_lock_wallet_and_confirmation_and_is_audited(env, caplog):
    from solders.keypair import Keypair
    c, hub, db = env["c"], env["hub"], env["db"]
    A = tok(UA)
    caplog.set_level(logging.DEBUG)
    r = c.post("/api/pump/real", json={"enabled": True, "confirm": "LIGAR"}, headers=A).json()
    assert "travada" in r["error"]                                    # PUMP_REAL_ALLOWED=false (padrão)
    hub.real_allowed = True
    assert "carteira" in c.post("/api/pump/real", json={"enabled": True, "confirm": "LIGAR"}, headers=A).json()["error"]
    kp = Keypair()
    priv = str(kp)
    r = c.post("/api/secrets", json={"name": "wallet_private_key", "value": "não é chave"}, headers=A).json()
    assert "inválida" in r["error"]
    r = c.post("/api/secrets", json={"name": "wallet_private_key", "value": priv}, headers=A)
    assert r.json()["address"] == str(kp.pubkey()) and priv not in r.text
    assert "confirmação" in c.post("/api/pump/real", json={"enabled": True}, headers=A).json()["error"]
    assert c.post("/api/pump/settings", json={"pump_real_enabled": True}, headers=A).json()["errors"]
    assert c.post("/api/pump/real", json={"enabled": True, "confirm": "LIGAR"}, headers=A).json()["enabled"] is True
    assert c.get("/api/pump", headers=A).json()["real"]["enabled"] is True
    assert c.get("/api/pump", headers=tok(UB, "b@x.com")).json()["real"]["enabled"] is False
    c.post("/api/pump/real", json={"enabled": False}, headers=A)
    acoes = [a["acao"] for a in db.tables["audit_log"] if a["user_id"] == UA]
    assert acoes == ["salvar chave", "ligar execução real", "desligar execução real"]
    # a chave privada nunca aparece: nem nas respostas, nem no banco aberto, nem no log
    everything = json.dumps(db.tables) + caplog.text + c.get("/api/secrets", headers=A).text + c.get("/api/pump", headers=A).text
    assert priv not in everything
    # remover a carteira desliga o real
    c.post("/api/pump/real", json={"enabled": True, "confirm": "LIGAR"}, headers=A)
    c.post("/api/secrets/remove", json={"name": "wallet_private_key"}, headers=A)
    assert c.get("/api/pump", headers=A).json()["real"]["enabled"] is False
    assert db.tables["audit_log"][-1]["acao"] == "remover chave"


def test_real_is_off_after_server_restart(env):
    from app.api import create_app
    from app.auth import Auth
    from app.crypto import SecretBox
    from app.hub import PumpHub
    from solders.keypair import Keypair
    c, hub, db, cfg = env["c"], env["hub"], env["db"], env["cfg"]
    hub.real_allowed = True
    c.post("/api/secrets", json={"name": "wallet_private_key", "value": str(Keypair())}, headers=tok(UA))
    c.post("/api/pump/real", json={"enabled": True, "confirm": "LIGAR"}, headers=tok(UA))
    _flush(hub)
    http = httpx.AsyncClient(transport=httpx.MockTransport(net_handler))
    hub2 = PumpHub(cfg, http, db, SecretBox(cfg.encryption_key))                  # "reiniciou"
    hub2.real_allowed = True
    c2 = TestClient(create_app(hub2, Auth(SB, "anon", http, SECRET), cfg))
    d = c2.get("/api/pump", headers=tok(UA)).json()
    assert d["real"]["enabled"] is False and d["real"]["wallet_configured"] is True


def test_swap_and_manual_sell_are_audited(env):
    c, db = env["c"], env["db"]
    A = tok(UA)
    assert c.post("/api/pump/swap", json={"usdc": 5}, headers=A).json()["error"] == "confirmação obrigatória"
    r = c.post("/api/pump/swap", json={"usdc": 5, "confirm": True}, headers=A).json()
    assert "carteira" in r["error"]                                               # sem carteira: nada é enviado
    c.post("/api/pump/wallets", json={"wallet": W, "action": "add"}, headers=A)
    c.post("/api/pump/settings", json=NOFILTER, headers=A)
    e = asyncio.run(env["hub"].engine(UA))
    m = "Sell".ljust(40, "1") + "pump"
    e.on_message({"txType": "buy", "traderPublicKey": W, "mint": m, "solAmount": 1.0, "tokenAmount": 1e6,
                  "vSolInBondingCurve": 30, "vTokensInBondingCurve": 3e7, "marketCapSol": 900})
    pid = c.get("/api/pump", headers=A).json()["positions"][0]["id"]
    assert c.post("/api/pump/close", json={"id": pid}, headers=A).json()["ok"]
    acoes = [a["acao"] for a in db.tables["audit_log"]]
    assert acoes == ["trocar USDC→SOL", "vender manual"]


def test_settings_validated_and_saved(env):
    c, db = env["c"], env["db"]
    r = c.post("/api/pump/settings", json={"pump_stop_pct": 25, "pump_max_open": 999, "pump_rpc_http": "https://x"},
               headers=tok(UA)).json()
    assert r["applied"] == {"pump_stop_pct": 25.0} and set(r["errors"]) == {"pump_max_open", "pump_rpc_http"}
    saved = [x for x in db.tables["user_settings"] if x["user_id"] == UA][0]["settings"]
    assert saved["pump_stop_pct"] == 25.0 and "pump_real_enabled" not in saved
    assert [x for x in db.tables["user_settings"] if x["user_id"] == UB][0]["settings"] == {}


def test_pages_and_security_headers(env):
    c = env["c"]
    r = c.get("/")
    assert r.status_code == 200 and "Entrar com Google" in r.text and "Content-Security-Policy" in r.headers
    assert c.get("/app").status_code == 200 and c.get("/static/app.js").status_code == 200
    for pose in ("rindo", "acenando", "ideia", "triste", "chorando", "bravo", "timido"):     # mascote da Visão geral
        assert c.get(f"/static/mascote/{pose}.webp").status_code == 200
    assert r.headers["X-Frame-Options"] == "DENY"
    a = c.get("/app")
    assert "__V__" not in a.text and "/static/app.js?v=" in a.text and a.headers["Cache-Control"] == "no-cache"
    assert 'id="navAdmin"' in a.text
    # pré-visualização de link (WhatsApp, Telegram…): nome novo, imagem com endereço completo
    assert 'og:title" content="PUMP FUN COPY' in r.text and "Bruxo Bode" not in r.text and "__BASE__" not in r.text
    assert 'og:image" content="http' in r.text and c.get("/static/og.png").status_code == 200


def test_token_card_route_validates_address(env):
    c = env["c"]
    assert c.get("/api/pump/token/x;drop", headers=tok(UA)).json()["error"] == "endereço de token inválido"
    r = c.get("/api/pump/token/" + "Tok".ljust(40, "1") + "pump", headers=tok(UA)).json()
    assert r["seen"] is False
    assert c.get("/api/pump/token/" + "Tok".ljust(40, "1") + "pump").status_code == 401
