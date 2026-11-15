"""0.32.368 (pedido do dono, 15/11/2026): rotas do Projeto Forex (rede nova do PUMP FUN COPY, página /forex, Sala /sala?rede=forex).

Etapa 1: só a carteira FICTÍCIA e a regra do lote; os mestres entram com o conector do cTrader (docs/FOREX.md, seção 6).
Tudo só para admin, como as outras redes em teste. Nenhuma rota manda ordem para corretora.
"""
from __future__ import annotations

from fastapi import Depends

from .db import audit


def add_routes(app, get_fx, admin_only, db):
    def fx():
        return get_fx()

    def off():
        return {"ligado": False, "motivo": "Forex desligado no servidor (FOREX_ON=false)"}

    @app.get("/api/forex/painel")
    async def forex_painel(u: dict = Depends(admin_only)):
        c = fx()
        if c is None:
            return off()
        await c.carregar(u["id"])
        return {"ligado": True, "etapa": 1, "conectores": c.conectores(), **c.painel(u["id"])}

    @app.post("/api/forex/conta")
    async def forex_conta(body: dict, u: dict = Depends(admin_only)):
        c = fx()
        if c is None:
            return off()
        cfg = await c.save_cfg(u["id"], body if isinstance(body, dict) else {})
        await audit(db, u["id"], "Forex: regra da cópia fictícia mudada",
                    ", ".join(f"{k}={v}" for k, v in sorted(cfg.items()) if k != "seguindo"))
        return {"ok": True, "cfg": cfg}

    @app.post("/api/forex/zerar")
    async def forex_zerar(u: dict = Depends(admin_only)):
        c = fx()
        if c is None:
            return off()
        await c.zerar(u["id"])
        await audit(db, u["id"], "Forex: carteira fictícia zerada", "")
        return {"ok": True}
