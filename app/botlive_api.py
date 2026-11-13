"""0.32.338 (pedido do dono, 13/11/2026): rotas do BOT LIVE. Carteira simulada própria (motor da Robinhood da 0.32.308, app/botlive.py),
separada da /hood. Só admin, só a própria conta. Nada aqui compra ou vende de verdade."""
from __future__ import annotations

from fastapi import Depends

from .db import audit

CARTEIRA = ("on", "saldo_inicial", "eth_por_compra", "max_abertas")


def add_routes(app, get_bot, admin_only, db) -> None:
    def off():
        return {"ligado": False, "motivo": "leitura da Robinhood Chain desligada no servidor (HOOD_ON=false)"}

    @app.get("/api/botlive/painel")
    async def botlive_painel(u: dict = Depends(admin_only)):
        c = get_bot()
        if c is None:
            return off()
        p = c.painel(u["id"])
        keep = ("cfg_sim", "padrao", "carteira", "posicoes", "trades", "eventos", "nomes", "eth_usd", "copiaria", "explorer")
        return {"ligado": True, "real": False, "seguindo": len(p.get("copiaria") or []), **{k: p.get(k) for k in keep}}

    @app.post("/api/botlive/carteira")
    async def botlive_carteira(body: dict, u: dict = Depends(admin_only)):
        c = get_bot()
        if c is None:
            return off()
        raw = {k: v for k, v in (body if isinstance(body, dict) else {}).items() if k in CARTEIRA}
        try:
            cfg = await c.save_book_cfg(u["id"], raw)
        except (TypeError, ValueError) as e:
            return {"error": "valor inválido: " + str(e)[:120]}
        await audit(db, u["id"], "BOT LIVE: carteira configurada", ", ".join(f"{k}={cfg.get(k)}" for k in raw))
        return {"ok": True, "cfg": {k: cfg.get(k) for k in CARTEIRA}, "carteira": c.book(u["id"]).wallet(__import__("time").time())}

    @app.post("/api/botlive/zerar")
    async def botlive_zerar(u: dict = Depends(admin_only)):
        c = get_bot()
        if c is None:
            return off()
        r = await c.reset_sim(u["id"])
        await audit(db, u["id"], "BOT LIVE: carteira zerada", "")
        return {"ok": True, **(r or {})}
