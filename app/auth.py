"""Login: só Google, pelo Supabase Auth. O navegador manda o token (JWT) do Supabase em toda chamada /api/*
(cabeçalho Authorization: Bearer …) e aqui ele é conferido. O user_id usado em TODAS as consultas sai daqui.

Formas de conferir o token (a primeira que servir):
1. SUPABASE_JWT_SECRET no .env (projetos com chave HS256 antiga) — confere a assinatura localmente.
2. Chaves públicas do projeto (JWKS em /auth/v1/.well-known/jwks.json, projetos novos com ES256/RS256).
3. Perguntando ao próprio Supabase (/auth/v1/user) — guarda a resposta por 60 s.
"""
from __future__ import annotations

import hashlib
import json
import time

import jwt


class AuthError(Exception):
    pass


class Auth:
    def __init__(self, supabase_url: str, anon_key: str, http, jwt_secret: str = ""):
        self.url = (supabase_url or "").rstrip("/")
        self.anon_key = anon_key
        self.http = http
        self.secret = jwt_secret or ""
        self.issuer = f"{self.url}/auth/v1" if self.url else None
        self._jwks: dict = {}
        self._jwks_at = 0.0
        self._cache: dict = {}
        self._bad: dict = {}                    # hash do token recusado -> até quando lembrar (SEC-06, 2026-10-25)
        self._jwks_forced_at = 0.0

    async def _load_jwks(self, force: bool = False) -> dict:
        # lista vazia (ou falha) também fica guardada, por 1 min, para não buscar de novo a cada pedido (SEC-06)
        if not force and time.time() - self._jwks_at < (600 if self._jwks else 60):
            return self._jwks
        if force:
            # token com "kid" desconhecido forçava nova busca a cada pedido (SEC-06): no máximo 1 por minuto
            if time.time() - self._jwks_forced_at < 60:
                return self._jwks
            self._jwks_forced_at = time.time()
        try:
            r = await self.http.get(f"{self.url}/auth/v1/.well-known/jwks.json", timeout=8)
            keys = (r.json() or {}).get("keys") or [] if r.status_code == 200 else []
            self._jwks = {k.get("kid"): k for k in keys if k.get("kid")}
        except Exception:
            self._jwks = {}
        self._jwks_at = time.time()
        return self._jwks

    def _claims_ok(self, c: dict) -> dict:
        if not c.get("sub"):
            raise AuthError("token sem usuário")
        if c.get("role") not in (None, "authenticated"):
            raise AuthError("token não é de usuário logado")
        return c

    async def verify(self, token: str) -> dict:
        if not token or token.count(".") != 2:
            raise AuthError("faça login")
        hk = hashlib.sha256(token.encode()).hexdigest()
        if self._bad.get(hk, 0) > time.time():
            raise AuthError("token inválido")
        try:
            return await self._verify(token)
        except AuthError as e:
            if "Supabase" not in str(e):           # falha de rede com o Supabase não fica lembrada
                if len(self._bad) > 5000:
                    self._bad.clear()
                self._bad[hk] = time.time() + 60
            raise

    async def _verify(self, token: str) -> dict:
        try:
            head = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            raise AuthError("token inválido") from None
        alg = head.get("alg")
        opts = {"require": ["exp", "sub"]}
        kw = {"audience": "authenticated", "options": opts, "leeway": 30}
        if self.issuer:
            kw["issuer"] = self.issuer
        try:
            if alg == "HS256":
                if not self.secret:
                    return await self._remote(token)
                return self._claims_ok(jwt.decode(token, self.secret, algorithms=["HS256"], **kw))
            if alg in ("ES256", "RS256", "EdDSA"):
                keys = await self._load_jwks()
                jwk = keys.get(head.get("kid"))
                if jwk is None:
                    keys = await self._load_jwks(force=True)
                    jwk = keys.get(head.get("kid"))
                if jwk is None:
                    return await self._remote(token)
                key = jwt.PyJWK(jwk).key
                return self._claims_ok(jwt.decode(token, key, algorithms=[alg], **kw))
        except jwt.ExpiredSignatureError:
            raise AuthError("sessão expirada — entre de novo") from None
        except jwt.PyJWTError:
            raise AuthError("token inválido") from None
        raise AuthError("token inválido")

    async def _remote(self, token: str) -> dict:
        """Pergunta ao Supabase quem é o dono do token (guarda por 60 s)."""
        if not self.url:
            raise AuthError("Supabase não configurado")
        hk = hashlib.sha256(token.encode()).hexdigest()
        hit = self._cache.get(hk)
        if hit and hit[0] > time.time():
            return hit[1]
        try:
            r = await self.http.get(f"{self.url}/auth/v1/user", headers={"apikey": self.anon_key,
                                                                         "Authorization": f"Bearer {token}"}, timeout=8)
        except Exception:
            raise AuthError("não consegui falar com o Supabase") from None
        if r.status_code != 200:
            raise AuthError("sessão inválida ou expirada — entre de novo")
        u = r.json() or {}
        try:
            exp = int(json.loads(jwt.utils.base64url_decode(token.split(".")[1])).get("exp") or 0)
        except Exception:
            exp = 0
        claims = {"sub": u.get("id"), "email": u.get("email"), "user_metadata": u.get("user_metadata") or {},
                  "exp": exp, "role": "authenticated"}
        self._claims_ok(claims)
        self._cache[hk] = (min(time.time() + 60, exp or time.time() + 60), claims)
        if len(self._cache) > 5000:
            self._cache.clear()
        return claims
