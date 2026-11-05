"""Rotas do Dormant (0.32.227). Só admin. Separadas de api.py, da BNB e da Robinhood para ficar isolado."""
from __future__ import annotations

import re

from fastapi import Depends

from .db import audit

KEY_NAME = "coingecko_key"
KEY_RE = re.compile(r"^[A-Za-z0-9_-]{10,80}$")


def add_routes(app, get_watch, admin_only, db, hub=None) -> None:
    @app.get("/api/dormant")
    async def dormant_state(u: dict = Depends(admin_only)):
        w = get_watch()
        if w is None:
            return {"ligado": False, "motivo": "Dormant desligado no servidor (DORMANT_ON=false)"}
        out = w.state()
        out["chave"] = bool(hub and (getattr(hub, "system_keys", None) or {}).get(KEY_NAME))
        return out

    @app.post("/api/dormant/cfg")
    async def dormant_cfg(body: dict, u: dict = Depends(admin_only)):
        w = get_watch()
        if w is None:
            return {"error": "Dormant desligado no servidor"}
        cfg = await w.save_cfg(body if isinstance(body, dict) else {})
        await audit(db, u["id"], "Dormant: regras mudadas", ", ".join(f"{k}={v}" for k, v in sorted(cfg.items())))
        return {"ok": True, "cfg": cfg}

    @app.post("/api/dormant/agora")
    async def dormant_now(u: dict = Depends(admin_only)):
        w = get_watch()
        if w is None:
            return {"error": "Dormant desligado no servidor"}
        w.refresh_now()
        return {"ok": True}

    # 0.32.228 (pedido do dono): adicionar moedas na tela, guardando o nome de quem adicionou
    @app.get("/api/dormant/buscar")
    async def dormant_search(q: str = "", u: dict = Depends(admin_only)):
        w = get_watch()
        if w is None:
            return {"error": "Dormant desligado no servidor"}
        try:
            return {"itens": await w.search(q[:120])}
        except RuntimeError as e:
            return {"error": str(e)}

    @app.post("/api/dormant/adicionar")
    async def dormant_add(body: dict, u: dict = Depends(admin_only)):
        w = get_watch()
        if w is None:
            return {"error": "Dormant desligado no servidor"}
        nome = u.get("nome") or (u.get("email") or "").split("@")[0] or "admin"
        try:
            e = await w.add(str((body or {}).get("id") or ""), nome, u["id"])
        except (ValueError, RuntimeError) as ex:
            return {"error": str(ex)}
        await audit(db, u["id"], "Dormant: moeda adicionada", f"{e['nome']} ({e['cg']})")
        return {"ok": True, "moeda": e}

    @app.post("/api/dormant/remover")
    async def dormant_remove(body: dict, u: dict = Depends(admin_only)):
        w = get_watch()
        if w is None:
            return {"error": "Dormant desligado no servidor"}
        key = str((body or {}).get("key") or "")
        if not await w.remove(key):
            return {"error": "só dá para tirar moedas adicionadas na tela"}
        await audit(db, u["id"], "Dormant: moeda removida", key)
        return {"ok": True}

    # chave Demo da CoinGecko: chave do sistema (cofre criptografado), só neste painel; o valor nunca volta para a tela
    @app.post("/api/dormant/chave")
    async def dormant_key(body: dict, u: dict = Depends(admin_only)):
        if hub is None:
            return {"error": "servidor sem o cofre de chaves"}
        value = str((body or {}).get("value") or "").strip()
        if not KEY_RE.match(value):
            return {"error": "isso não parece uma chave da CoinGecko (só letras, números, - e _)"}
        try:
            await hub.set_system_key(u["id"], KEY_NAME, value)          # o audit_log guarda o nome, nunca o valor
        except Exception:
            return {"error": "não consegui salvar no banco agora"}
        w = get_watch()
        if w is not None:
            w.refresh_now()
        return {"ok": True, "chave": True}

    @app.post("/api/dormant/chave/remover")
    async def dormant_key_del(u: dict = Depends(admin_only)):
        if hub is None:
            return {"error": "servidor sem o cofre de chaves"}
        await hub.remove_system_key(u["id"], KEY_NAME)
        return {"ok": True, "chave": False}
