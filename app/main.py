"""Início do servidor: python -m app.main"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

import httpx
import uvicorn

from .api import create_app
from .auth import Auth
from .crypto import SecretBox
from .db import SupaREST
from .hub import PumpHub
from .logsafe import add_secret, install
from .settings import ServerConfig
from .version import VERSION

log = logging.getLogger("main")


def build_app():
    cfg = ServerConfig()
    for s in (cfg.supabase_service_key, cfg.encryption_key, cfg.supabase_jwt_secret):
        add_secret(s)
    missing = [n for n, v in (("SUPABASE_URL", cfg.supabase_url), ("SUPABASE_ANON_KEY", cfg.supabase_anon_key),
                              ("SUPABASE_SERVICE_ROLE_KEY", cfg.supabase_service_key),
                              ("APP_ENCRYPTION_KEY", cfg.encryption_key)) if not v]
    if missing:
        raise SystemExit("Falta no .env: " + ", ".join(missing) + " (veja o .env.example)")
    from .apiusage import Usage
    usage = Usage()                                   # 0.31.76: conta cada chamada às APIs externas
    http = httpx.AsyncClient(timeout=15, follow_redirects=False, headers={"User-Agent": "pump-fun-copy"},
                             event_hooks={"request": [usage.hook], "response": [usage.resp_hook]})
    db = SupaREST(cfg.supabase_url, cfg.supabase_service_key, http)
    hub = PumpHub(cfg, http, db, SecretBox(cfg.encryption_key))
    hub.usage = usage
    # 0.32.168: leitura da BNB (Four.Meme), isolada: laço próprio, RPC grátis próprio e tabelas bnb_*; BNB_ON=false desliga
    hub.bnb = None
    if os.environ.get("BNB_ON", "true").lower() not in ("0", "false", "no", "off"):
        from .bnb import BnbWatch
        hub.bnb = BnbWatch(http, db)
        hub.bnb.vault = hub.vault                     # 0.32.172: chave da carteira BNB (cofre criptografado)
        hub.bnb.real_allowed = hub.real_allowed       # mesma trava geral da Solana (PUMP_REAL_ALLOWED)
        hub.bnb.key_fn = lambda: (getattr(hub, "system_keys", None) or {}).get("nodereal_bnb_key", "")   # 0.32.179
    auth = Auth(cfg.supabase_url, cfg.supabase_anon_key, http, cfg.supabase_jwt_secret)
    app = create_app(hub, auth, cfg)

    @asynccontextmanager
    async def lifespan(_app):
        log.info("PUMP FUN COPY %s iniciando — execução real DESLIGADA para todos", VERSION)
        # 0.32.121: em 01/11/2026 o site ficou em 404 sem dar para saber em que ponto a subida parava. A porta abre primeiro,
        # os dados carregam em segundo plano e o /health mostra a etapa e o erro, sem precisar do Portainer.
        boot = asyncio.create_task(hub.boot())
        bnb = asyncio.create_task(hub.bnb.run()) if hub.bnb is not None else None
        yield
        boot.cancel()
        if bnb is not None:
            bnb.cancel()
        await hub.stop()
        await http.aclose()

    app.router.lifespan_context = lifespan
    return app, cfg


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    install()
    from .logsafe import ring
    ring()
    for noisy in ("httpx", "httpcore", "websockets"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    app, cfg = build_app()
    uvicorn.run(app, host="0.0.0.0", port=cfg.port, log_level="warning", proxy_headers=True,
                forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
