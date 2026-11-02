"""Rotas da aba BNB (0.32.168). Só admin. Separadas de api.py para a BNB ficar isolada do que já funciona."""
from __future__ import annotations

from fastapi import Depends

from .db import audit


def add_routes(app, get_watch, admin_only, db) -> None:
    @app.get("/api/pump/bnb")
    async def bnb_state(u: dict = Depends(admin_only)):
        w = get_watch()
        if w is None:
            return {"ligado": False, "motivo": "leitura da BNB desligada no servidor (BNB_ON=false)"}
        return w.state()

    @app.post("/api/pump/bnb/cfg")
    async def bnb_cfg(body: dict, u: dict = Depends(admin_only)):
        w = get_watch()
        if w is None:
            return {"error": "leitura da BNB desligada no servidor"}
        cfg = await w.save_cfg(body if isinstance(body, dict) else {})
        await audit(db, u["id"], "BNB: regra do ranking mudada", ", ".join(f"{k}={v}" for k, v in sorted(cfg.items())))
        return {"ok": True, "cfg": cfg}
