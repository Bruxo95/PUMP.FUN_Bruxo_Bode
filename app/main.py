"""Início do servidor: python -m app.main"""
from __future__ import annotations

import logging
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
    http = httpx.AsyncClient(timeout=15, follow_redirects=False, headers={"User-Agent": "pumpfun-bruxo-bode"})
    db = SupaREST(cfg.supabase_url, cfg.supabase_service_key, http)
    hub = PumpHub(cfg, http, db, SecretBox(cfg.encryption_key))
    auth = Auth(cfg.supabase_url, cfg.supabase_anon_key, http, cfg.supabase_jwt_secret)
    app = create_app(hub, auth, cfg)

    @asynccontextmanager
    async def lifespan(_app):
        log.info("PUMP.FUN Bruxo Bode %s iniciando — execução real DESLIGADA para todos", VERSION)
        await hub.start()
        yield
        await hub.stop()
        await http.aclose()

    app.router.lifespan_context = lifespan
    return app, cfg


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    install()
    for noisy in ("httpx", "httpcore", "websockets"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    app, cfg = build_app()
    uvicorn.run(app, host="0.0.0.0", port=cfg.port, log_level="warning", proxy_headers=True,
                forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
