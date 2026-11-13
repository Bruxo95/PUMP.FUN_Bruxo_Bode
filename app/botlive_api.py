"""0.32.338 (pedido do dono, 13/11/2026): rotas do BOT LIVE. Carteira simulada própria (motor da Robinhood da 0.32.308, app/botlive.py),
separada da /hood. Só admin, só a própria conta. Nada aqui compra ou vende de verdade."""
from __future__ import annotations

import asyncio

from fastapi import Depends

from .db import audit

CARTEIRA = ("on", "saldo_inicial", "eth_por_compra", "max_abertas", "stop_pct", "trail_on", "trail_ativa_pct", "trail_dist_pct", "max_hold_h")


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
        out = {"ligado": True, "real": False, "seguindo": len(p.get("copiaria") or []), **{k: p.get(k) for k in keep}}
        # 0.32.341: nome dos tokens do log. O HoodWatch busca nomes para o motor da /hood; o BOT LIVE usa os dois.
        watch = getattr(c.w, "_w", None)
        hood_meta = getattr(getattr(watch, "copier", None), "meta", {}) or {}
        falta = list(dict.fromkeys(e.get("token") for e in out.get("eventos") or []
                                   if e.get("token") and e["token"] not in c.meta and e["token"] not in hood_meta))
        if falta and hasattr(watch, "fill_names"):                       # DexScreener, até 30 por vez; quem não veio tenta de novo em 10 min
            try:
                await asyncio.wait_for(watch.fill_names(falta), 4)
            except Exception:
                pass
        nomes = dict(out.get("nomes") or {})
        for e in out.get("eventos") or []:
            tk = e.get("token")
            if tk and tk not in nomes and (c.meta.get(tk) or hood_meta.get(tk)):
                nomes[tk] = c.meta.get(tk) or hood_meta.get(tk)
        out["nomes"] = nomes
        return out

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
