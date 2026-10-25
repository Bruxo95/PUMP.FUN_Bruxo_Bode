"""Reproduz achados da auditoria com rede e banco inteiramente simulados.

Executar da raiz: .venv/Scripts/python.exe docs/auditoria/2026-10-25/reproduzir-auth-db.py
Exit 0 significa que os comportamentos vulneráveis do baseline foram reproduzidos,
não que a aplicação passou em uma verificação de segurança.
Não carrega .env, não chama serviços externos e não cria nem usa carteira real.
"""
import asyncio
import base64
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import httpx
import jwt

from app.api import create_app
from app.auth import Auth, AuthError
from app.crypto import SecretBox
from app.hub import PumpHub
from app.settings import ServerConfig
from tests.fakes import FakeREST

SB = "https://audit.invalid"
SECRET = "somente-teste-offline-" + "x" * 40
UA = "11111111-1111-1111-1111-111111111111"
UB = "22222222-2222-2222-2222-222222222222"
WALLET = "TraderGood1111111111111111111111111111111"


def token(uid):
    claims = {"sub": uid, "exp": int(time.time()) + 120, "aud": "authenticated",
              "iss": SB + "/auth/v1", "role": "authenticated"}
    return {"Authorization": "Bearer " + jwt.encode(claims, SECRET, algorithm="HS256")}


def build(db=None):
    # Valores sintéticos exclusivos deste processo; não lê configuração de produção.
    for key, value in {
        "SUPABASE_URL": SB,
        "SUPABASE_ANON_KEY": "offline-anon",
        "SUPABASE_SERVICE_ROLE_KEY": "offline-service",
        "APP_ENCRYPTION_KEY": base64.b64encode(b"x" * 32).decode(),
        "PUMP_REAL_ALLOWED": "false",
    }.items():
        os.environ[key] = value
    calls = []

    def mock(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={"traders": []})

    http = httpx.AsyncClient(transport=httpx.MockTransport(mock))
    cfg = ServerConfig()
    db = db or FakeREST()
    db.add_user(UA, "admin@audit.invalid")
    db.add_user(UB, "user@audit.invalid")
    hub = PumpHub(cfg, http, db, SecretBox(cfg.encryption_key))
    auth = Auth(SB, cfg.supabase_anon_key, http, SECRET)
    return create_app(hub, auth, cfg), hub, calls, http


async def unknown_kid():
    calls = []

    def mock(request):
        calls.append(request.url.path)
        if "jwks" in request.url.path:
            return httpx.Response(200, json={"keys": []})
        return httpx.Response(401, json={"error": "invalid"})

    def b64(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")

    forged = (b64({"alg": "RS256", "kid": "unknown"}) + "." +
              b64({"sub": UB, "exp": int(time.time()) + 120}) + ".eA")
    rejected = 0
    async with httpx.AsyncClient(transport=httpx.MockTransport(mock)) as http:
        auth = Auth(SB, "offline-anon", http)
        for _ in range(2):
            try:
                await auth.verify(forged)
            except AuthError:
                rejected += 1
    assert rejected == 2 and len(calls) == 6
    print(json.dumps({"case": "unknown_kid_amplification", "tokens_rejected": rejected,
                      "mock_requests": calls}))


async def quota_and_validation():
    app, hub, calls, http = build()
    hub.shared_st_key = "offline-shared-key-not-a-real-api-key"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                 base_url="http://local.invalid") as client:
        statuses = []
        for _ in range(3):
            r = await client.post("/api/pump/leaderboard", headers=token(UB), json={"days": 7})
            statuses.append(r.status_code)
        assert statuses == [200] * 3 and len(calls) == 3
        print(json.dumps({"case": "force_shared_leaderboard", "http_statuses": statuses,
                          "mock_upstream_calls": len(calls)}))
        r = await client.post("/api/pump/settings", headers=token(UB),
                              json={"pump_max_open": "1e1000"})
        assert r.status_code == 500
        print(json.dumps({"case": "integer_overflow_validation", "http_status": r.status_code,
                          "body": r.text}))
    await http.aclose()


async def block_race():
    class RaceDB(FakeREST):
        def __init__(self):
            super().__init__()
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def select(self, table, filters=None, **kwargs):
            # Representa uma leitura do banco pendente antes de publicar o motor em hub.engines.
            if table == "user_settings" and filters == {"user_id": UB} and not self.release.is_set():
                self.entered.set()
                await self.release.wait()
            return await super().select(table, filters, **kwargs)

    db = RaceDB()
    app, hub, _, http = build(db)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://local.invalid") as client:
        pending = asyncio.create_task(client.post("/api/pump/wallets", headers=token(UB),
                                                  json={"wallet": WALLET, "action": "add"}))
        await asyncio.wait_for(db.entered.wait(), timeout=5)
        blocked = await client.post("/api/admin/users/" + UB, headers=token(UA),
                                     json={"bloqueado": True})
        absent_immediately = UB not in hub.engines
        db.release.set()
        resumed = await pending
        later = await client.get("/api/pump", headers=token(UB))
        assert blocked.status_code == 200 and absent_immediately
        assert resumed.status_code == 200 and UB in hub.engines
        assert WALLET in hub.engines[UB].followed and later.status_code == 403
        print(json.dumps({"case": "block_during_engine_load",
                          "admin_result": blocked.json(), "absent_after_block": absent_immediately,
                          "pending_request_status": resumed.status_code,
                          "engine_present_after_pending_request": UB in hub.engines,
                          "blocked_user_still_following_wallet": WALLET in hub.engines[UB].followed,
                          "subsequent_request_status": later.status_code}, ensure_ascii=True))
    await http.aclose()


async def main():
    await unknown_kid()
    await quota_and_validation()
    await block_race()


if __name__ == "__main__":
    asyncio.run(main())
