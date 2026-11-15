"""0.32.368 (pedido do dono, 15/11/2026): rotas do Projeto Forex (rede nova do PUMP FUN COPY, página /forex, Sala /sala?rede=forex).

Etapa 1: só a carteira FICTÍCIA e a regra do lote; os mestres entram com o conector do cTrader (docs/FOREX.md, seção 6).
Tudo só para admin, como as outras redes em teste. Nenhuma rota manda ordem para corretora.
"""
from __future__ import annotations

import urllib.parse

from fastapi import Depends
from fastapi.responses import JSONResponse, RedirectResponse

from .db import audit

CT_KEYS = {"client_id": "ctrader_client_id", "client_secret": "ctrader_client_secret"}


def add_routes(app, get_fx, admin_only, db, base_url: str = ""):
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
        ranking = c.ct.ranking if c.ct is not None else []
        return {"ligado": True, "etapa": 2, "conectores": c.conectores(), **c.painel(u["id"], ranking)}

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

    @app.post("/api/forex/seguir")
    async def forex_seguir(body: dict, u: dict = Depends(admin_only)):
        """Liga ou desliga a cópia FICTÍCIA de um mestre do ranking (só entra na carteira quem estiver elegível)."""
        c = fx()
        if c is None:
            return off()
        mid = str((body or {}).get("id") or "")[:40]
        if not mid:
            return JSONResponse({"error": "mestre inválido"}, status_code=400)
        b = await c.carregar(u["id"])
        seg = [x for x in b.cfg.get("seguindo", []) if x != mid]
        if (body or {}).get("on"):
            seg.append(mid)
        cfg = await c.save_cfg(u["id"], {"seguindo": seg})
        await audit(db, u["id"], "Forex: " + ("seguir mestre (cópia fictícia)" if (body or {}).get("on") else "parar de seguir mestre"), mid)
        return {"ok": True, "seguindo": cfg.get("seguindo", [])}

    # ------------------------------------------------------------------ 0.32.370: conector do cTrader (etapa 2)
    def ct():
        c = fx()
        return None if c is None else c.ct

    def ct_redirect() -> str:
        return (base_url or "").rstrip("/") + "/forex/ctrader/retorno"

    @app.get("/api/forex/ctrader")
    async def forex_ct(u: dict = Depends(admin_only)):
        h = ct()
        if h is None:
            return off()
        return {"ok": True, **await h.status(u["id"]), "retorno": ct_redirect(), "mestres": h.mestres_da(u["id"]),
                "banco_local": None if h.store is None else h.store.st}

    @app.post("/api/forex/ctrader/chave")
    async def forex_ct_key(body: dict, u: dict = Depends(admin_only)):
        h = ct()
        if h is None or h.vault is None:
            return JSONResponse({"error": "cofre indisponível"}, status_code=503)
        nome = CT_KEYS.get(str((body or {}).get("nome") or ""))
        valor = str((body or {}).get("valor") or "").strip()
        if not nome or not (8 <= len(valor) <= 300) or any(ch.isspace() for ch in valor):
            return JSONResponse({"error": "valor inválido"}, status_code=400)
        await h.vault.save(u["id"], nome, valor)
        await audit(db, u["id"], "salvar chave", nome)
        return {"ok": True, **await h.status(u["id"])}

    @app.post("/api/forex/ctrader/remover")
    async def forex_ct_remove(u: dict = Depends(admin_only)):
        h = ct()
        if h is None or h.vault is None:
            return JSONResponse({"error": "cofre indisponível"}, status_code=503)
        await h.remove(u["id"])
        await audit(db, u["id"], "remover chave", "cTrader do Forex (Client ID, Client Secret e autorização)")
        return {"ok": True, **await h.status(u["id"])}

    @app.get("/api/forex/ctrader/conectar")
    async def forex_ct_connect(u: dict = Depends(admin_only)):
        h = ct()
        if h is None:
            return off()
        k = await h.keys(u["id"])
        if not k.get("ctrader_client_id") or not k.get("ctrader_client_secret"):
            return JSONResponse({"error": "salve o Client ID e o Client Secret primeiro"}, status_code=400)
        return {"ok": True, "url": h.auth_url(u["id"], k["ctrader_client_id"], ct_redirect())}

    @app.get("/forex/ctrader/retorno")
    async def forex_ct_back(code: str = "", state: str = "", error: str = ""):
        """A cTrader volta para cá depois do "Allow access". Sem login: quem vale é o state (uso único, 10 min)."""
        h = ct()
        uid = h.take_state(state) if h is not None else None
        if not uid:
            return RedirectResponse("/forex?ct=erro&msg=" + urllib.parse.quote("pedido vencido: clique em Conectar conta cTrader de novo") + "#conexoes")
        if error or not code:
            return RedirectResponse("/forex?ct=erro&msg=" + urllib.parse.quote("a cTrader não autorizou (" + (error or "sem código") + ")") + "#conexoes")
        try:
            await h.exchange(uid, code, ct_redirect())
        except Exception as e:
            return RedirectResponse("/forex?ct=erro&msg=" + urllib.parse.quote(str(e)[:200]) + "#conexoes")
        await audit(db, uid, "salvar chave", "cTrader do Forex conectado (só leitura)")
        return RedirectResponse("/forex?ct=ok#conexoes")

    @app.post("/api/forex/ctrader/conta")
    async def forex_ct_conta(body: dict, u: dict = Depends(admin_only)):
        """Liga ou pausa o acompanhamento de uma conta (mestre) do cTrader."""
        h = ct()
        if h is None:
            return off()
        cid, on = str((body or {}).get("id") or ""), bool((body or {}).get("on"))
        if not h.set_off(u["id"], cid, not on):
            return JSONResponse({"error": "conta não encontrada"}, status_code=404)
        await audit(db, u["id"], "Forex: " + ("acompanhar conta cTrader" if on else "pausar conta cTrader"), cid)
        return {"ok": True, **await h.status(u["id"])}

