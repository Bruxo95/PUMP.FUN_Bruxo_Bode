"""Rotas do painel BNB (0.32.168). Só admin. Separadas de api.py para a BNB ficar isolada do que já funciona."""
from __future__ import annotations

from fastapi import Depends

from .db import audit

OFF = {"ligado": False, "motivo": "leitura da BNB desligada no servidor (BNB_ON=false)"}


def add_routes(app, get_watch, admin_only, db) -> None:
    @app.get("/api/pump/bnb")
    async def bnb_state(u: dict = Depends(admin_only)):
        w = get_watch()
        return OFF if w is None else w.state()

    @app.post("/api/pump/bnb/cfg")
    async def bnb_cfg(body: dict, u: dict = Depends(admin_only)):
        w = get_watch()
        if w is None:
            return {"error": "leitura da BNB desligada no servidor"}
        cfg = await w.save_cfg(body if isinstance(body, dict) else {})
        await audit(db, u["id"], "BNB: regra do ranking mudada", ", ".join(f"{k}={v}" for k, v in sorted(cfg.items())))
        return {"ok": True, "cfg": cfg}

    # 0.32.170: carteira fictícia da conta (Visão geral, Posições, Histórico, Semana × fim de semana, Abas, Configurações)
    @app.get("/api/pump/bnb/painel")
    async def bnb_painel(u: dict = Depends(admin_only)):
        w = get_watch()
        return OFF if w is None else {"ligado": True, **w.painel(u["id"])}

    @app.post("/api/pump/bnb/conta")
    async def bnb_conta(body: dict, u: dict = Depends(admin_only)):
        w = get_watch()
        if w is None:
            return {"error": "leitura da BNB desligada no servidor"}
        cfg = await w.save_book_cfg(u["id"], body if isinstance(body, dict) else {})
        await audit(db, u["id"], "BNB: configuração da cópia fictícia mudada", ", ".join(f"{k}={v}" for k, v in sorted(cfg.items())))
        return {"ok": True, "cfg": cfg}

    @app.post("/api/pump/bnb/fechar")
    async def bnb_fechar(body: dict, u: dict = Depends(admin_only)):
        w = get_watch()
        if w is None:
            return {"error": "leitura da BNB desligada no servidor"}
        tr = w.close_manual(u["id"], str((body or {}).get("id") or ""))
        if not tr:
            return {"error": "posição não encontrada (já fechou?)"}
        await w.flush_books()
        await audit(db, u["id"], "BNB: vendeu posição fictícia", f"{tr['token'][:10]}… {tr['pnl_bnb']:+.4f} BNB")
        return {"ok": True, "trade": tr}
