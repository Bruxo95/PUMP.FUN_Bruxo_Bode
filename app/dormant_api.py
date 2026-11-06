"""Rotas do Dormant (0.32.227). Só admin. Separadas de api.py, da BNB e da Robinhood para ficar isolado."""
from __future__ import annotations

import logging
import re

from fastapi import Depends, HTTPException

from .db import DBError, audit
from .dormant_buy import Buyer, BuyError

log = logging.getLogger("pump.dormant.compra")
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

    @app.get("/api/dormant/moeda")
    async def dormant_coin(key: str = "", u: dict = Depends(admin_only)):
        w = get_watch()
        if w is None:
            return {"error": "Dormant desligado no servidor"}
        r = await w.detail(key[:200])
        return r if r is not None else {"error": "moeda não está na lista"}

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

    # ------------------------------------------------------------------ 0.32.242: carteiras e compra na DEX (só a própria conta)
    def own(u: dict = Depends(admin_only)) -> dict:
        # "Visualizar tela" nunca chega aqui: carteiras e compras são só de quem está logado, nem outro admin vê
        if u.get("view_by"):
            raise HTTPException(403, "não disponível ao visualizar a tela de outra conta")
        return u

    def buyer():
        w = get_watch()
        if w is None or hub is None:
            raise HTTPException(503, "Dormant desligado no servidor")
        b = getattr(w, "buyer", None)
        if b is None:
            b = w.buyer = Buyer(w.http, db, hub.vault.box, w, allowed=lambda: hub.real_allowed,
                                sys_key=lambda n: (getattr(hub, "system_keys", None) or {}).get(n, ""))
        return b

    async def run(coro):
        """Erro previsto vira texto para a tela. Imprevisto: só o tipo no log e na resposta, nunca o conteúdo (a chave passa por aqui)."""
        try:
            return await coro
        except BuyError as e:
            return {"error": str(e)}
        except DBError as e:
            log.warning("Dormant compra: banco: %s", type(e).__name__)
            return {"error": "não consegui falar com o banco agora: nada foi enviado se a tela não mostrar a compra"}
        except Exception as e:
            log.error("Dormant compra: erro %s", type(e).__name__)
            return {"error": f"erro interno ({type(e).__name__})"}

    @app.get("/api/dormant/carteiras")
    async def wal_list(u: dict = Depends(own)):
        return await run(buyer().wallets(u["id"]))

    @app.get("/api/dormant/carteiras/saldos")
    async def wal_bal(u: dict = Depends(own)):
        return await run(buyer().balances(u["id"]))

    @app.post("/api/dormant/carteiras/salvar")
    async def wal_save(body: dict, u: dict = Depends(own)):
        async def go():
            b = body if isinstance(body, dict) else {}
            r = await buyer().save_wallet(u["id"], str(b.get("rede") or ""), b.get("chave"), b.get("senha"), bool(b.get("todas_evm")))
            await audit(db, u["id"], "Dormant: carteira salva", f"{', '.join(r['redes'])} · {r['endereco']}")     # nunca a chave
            return {"ok": True, **r}
        return await run(go())

    @app.post("/api/dormant/carteiras/remover")
    async def wal_del(body: dict, u: dict = Depends(own)):
        async def go():
            rede = str((body or {}).get("rede") or "")
            await buyer().remove_wallet(u["id"], rede)
            await audit(db, u["id"], "Dormant: carteira removida", rede)
            return {"ok": True}
        return await run(go())

    @app.post("/api/dormant/carteiras/senha")
    async def wal_pass(body: dict, u: dict = Depends(own)):
        async def go():
            b = body if isinstance(body, dict) else {}
            n = await buyer().change_password(u["id"], b.get("atual"), b.get("nova"))
            await audit(db, u["id"], "Dormant: senha de compra trocada", f"{n} carteiras")
            return {"ok": True, "carteiras": n}
        return await run(go())

    @app.post("/api/dormant/compra/ligar")
    async def buy_on(body: dict, u: dict = Depends(own)):
        async def go():
            b = body if isinstance(body, dict) else {}
            on = b.get("on") is True
            c = await buyer().set_on(u["id"], on, b.get("senha") or "", str(b.get("confirmar") or ""))
            await audit(db, u["id"], "Dormant: compras " + ("ligadas" if c["on"] else "desligadas"), "")
            return {"ok": True, "cfg": c}
        return await run(go())

    @app.post("/api/dormant/compra/limites")
    async def buy_limits(body: dict, u: dict = Depends(own)):
        async def go():
            b = body if isinstance(body, dict) else {}
            c = await buyer().save_limits(u["id"], b, b.get("senha") or "")
            await audit(db, u["id"], "Dormant: limites de compra", f"por compra US$ {c['max_usd']:g} · por dia US$ {c['dia_usd']:g} · folga {c['slip_pct']:g}%")
            return {"ok": True, "cfg": c}
        return await run(go())

    @app.post("/api/dormant/compra/cotar")
    async def buy_quote(body: dict, u: dict = Depends(own)):
        b = body if isinstance(body, dict) else {}
        return await run(buyer().preview(u["id"], str(b.get("key") or "")[:200], str(b.get("rede") or ""), b.get("valor")))

    @app.post("/api/dormant/compra/confirmar")
    async def buy_go(body: dict, u: dict = Depends(own)):
        async def go():
            b = body if isinstance(body, dict) else {}
            r = await buyer().buy(u["id"], str(b.get("quote_id") or ""), b.get("senha"), str(b.get("confirmar") or ""))
            await audit(db, u["id"], "Dormant: compra", f"{r.get('simbolo')} · US$ {float(r.get('usd_in') or 0):.2f} · {r.get('status')} · {r.get('tx')}")
            return {"ok": True, "compra": r}
        return await run(go())

    @app.get("/api/dormant/compras")
    async def buy_hist(u: dict = Depends(own)):
        return await run(buyer().history(u["id"]))
