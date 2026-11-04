"""Rotas da Robinhood Chain (0.32.208). Só admin. Separadas de api.py e da BNB para ficar isolada do que já funciona."""
from __future__ import annotations

from fastapi import Depends

from .db import audit


def add_routes(app, get_watch, admin_only, db) -> None:
    @app.get("/api/hood")
    async def hood_state(u: dict = Depends(admin_only)):
        w = get_watch()
        if w is None:
            return {"ligado": False, "motivo": "leitura da Robinhood Chain desligada no servidor (HOOD_ON=false)"}
        return w.state()

    @app.post("/api/hood/cfg")
    async def hood_cfg(body: dict, u: dict = Depends(admin_only)):
        w = get_watch()
        if w is None:
            return {"error": "leitura da Robinhood Chain desligada no servidor"}
        cfg = await w.save_cfg(body if isinstance(body, dict) else {})
        await audit(db, u["id"], "Robinhood: regra do ranking mudada", ", ".join(f"{k}={v}" for k, v in sorted(cfg.items())))
        return {"ok": True, "cfg": cfg}
