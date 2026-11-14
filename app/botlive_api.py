"""0.32.338 (pedido do dono, 13/11/2026): rotas do BOT LIVE. Carteira simulada própria (motor da Robinhood da 0.32.308, app/botlive.py),
separada da /hood. Só admin, só a própria conta. Nada aqui compra ou vende de verdade."""
from __future__ import annotations

import asyncio
import urllib.parse

from fastapi import Depends
from fastapi.responses import JSONResponse, RedirectResponse

from .db import audit

CARTEIRA = ("on", "saldo_inicial", "eth_por_compra", "max_abertas", "stop_pct", "trail_on", "trail_ativa_pct", "trail_dist_pct", "max_hold_h")


def add_routes(app, get_bot, admin_only, db, base_url: str = "") -> None:
    def off():
        return {"ligado": False, "motivo": "leitura da Robinhood Chain desligada no servidor (HOOD_ON=false)"}

    @app.get("/api/botlive/painel")
    async def botlive_painel(u: dict = Depends(admin_only)):
        c = get_bot()
        if c is None:
            return off()
        return await painel_de(c, u["id"])

    # 0.32.347 (pedido do dono): o link do OBS abre a SALA LIVE direto, sem a tela de login. O código do link só lê o painel do BOT LIVE
    # dessa conta (carteira simulada, posições, trades e log); não dá acesso a mais nada. Gerar um novo derruba o anterior.
    @app.post("/api/botlive/obs-link")
    async def botlive_obs_link(u: dict = Depends(admin_only)):
        c = get_bot()
        if c is None:
            return off()
        k = c.obs_new(u["id"])
        await audit(db, u["id"], "BOT LIVE: link do OBS gerado", "o link anterior parou de valer")
        return {"ok": True, "k": k}

    @app.get("/api/botlive/obs/painel")
    async def botlive_obs_painel(k: str = ""):
        c = get_bot()
        if c is None:
            return off()
        uid = c.obs_user(k)
        if not uid:
            return JSONResponse({"error": "link do OBS inválido ou trocado: gere um novo em /botlive"}, status_code=403)
        return await painel_de(c, uid)

    # ------------------------------------------------------------------ 0.32.349: compras no chat da live do YouTube
    YT_KEYS = {"client_id": "youtube_client_id", "client_secret": "youtube_client_secret"}

    def yt_redirect() -> str:
        return (base_url or "").rstrip("/") + "/botlive/youtube/retorno"

    @app.get("/api/botlive/youtube")
    async def botlive_yt(u: dict = Depends(admin_only)):
        c = get_bot()
        if c is None:
            return off()
        return {"ok": True, **await c.yt.status(u["id"]), "retorno": yt_redirect()}

    @app.post("/api/botlive/youtube/chave")
    async def botlive_yt_key(body: dict, u: dict = Depends(admin_only)):
        c = get_bot()
        if c is None or c.yt.vault is None:
            return JSONResponse({"error": "cofre indisponível"}, status_code=503)
        nome = YT_KEYS.get(str(body.get("nome") or ""))
        valor = str(body.get("valor") or "").strip()
        if not nome or not (8 <= len(valor) <= 300) or any(ch.isspace() for ch in valor):
            return JSONResponse({"error": "valor inválido"}, status_code=400)
        await c.yt.vault.save(u["id"], nome, valor)
        c.yt.tok.pop(u["id"], None)
        await audit(db, u["id"], "salvar chave", nome)
        return {"ok": True, **await c.yt.status(u["id"])}

    @app.post("/api/botlive/youtube/remover")
    async def botlive_yt_remove(u: dict = Depends(admin_only)):
        c = get_bot()
        if c is None or c.yt.vault is None:
            return JSONResponse({"error": "cofre indisponível"}, status_code=503)
        for n in ("youtube_client_id", "youtube_client_secret", "youtube_refresh_token"):
            await c.yt.vault.delete(u["id"], n)
        c.yt.tok.pop(u["id"], None)
        c.yt.chat.pop(u["id"], None)
        c.yt.on.pop(u["id"], None)
        c.book(u["id"]).dirty_book = True
        await audit(db, u["id"], "remover chave", "YouTube do BOT LIVE (Client ID, Client Secret e autorização)")
        return {"ok": True, **await c.yt.status(u["id"])}

    @app.get("/api/botlive/youtube/conectar")
    async def botlive_yt_connect(u: dict = Depends(admin_only)):
        c = get_bot()
        if c is None:
            return off()
        k = await c.yt.keys(u["id"])
        if not k.get("youtube_client_id") or not k.get("youtube_client_secret"):
            return JSONResponse({"error": "salve o Client ID e o Client Secret primeiro"}, status_code=400)
        return {"ok": True, "url": c.yt.auth_url(u["id"], k["youtube_client_id"], yt_redirect())}

    @app.get("/botlive/youtube/retorno")
    async def botlive_yt_back(code: str = "", state: str = "", error: str = ""):
        """O Google volta para cá depois do "Permitir". Sem login: quem vale é o state (de uso único, 10 min)."""
        c = get_bot()
        uid = c.yt.take_state(state) if c is not None else None
        if not uid:
            return RedirectResponse("/botlive?yt=erro&msg=" + urllib.parse.quote("pedido vencido: clique em Conectar YouTube de novo"))
        if error or not code:
            return RedirectResponse("/botlive?yt=erro&msg=" + urllib.parse.quote("o Google não autorizou (" + (error or "sem código") + ")"))
        try:
            await c.yt.exchange(uid, code, yt_redirect())
        except Exception as e:
            return RedirectResponse("/botlive?yt=erro&msg=" + urllib.parse.quote(str(e)[:200]))
        await audit(db, uid, "salvar chave", "YouTube do BOT LIVE conectado")
        return RedirectResponse("/botlive?yt=ok")

    @app.post("/api/botlive/youtube/ligar")
    async def botlive_yt_on(body: dict, u: dict = Depends(admin_only)):
        c = get_bot()
        if c is None:
            return off()
        on = bool(body.get("on"))
        if on:
            c.yt.on[u["id"]] = True
        else:
            c.yt.on.pop(u["id"], None)
        c.book(u["id"]).dirty_book = True
        await audit(db, u["id"], "BOT LIVE: compras no chat do YouTube " + ("ligado" if on else "desligado"))
        return {"ok": True, **await c.yt.status(u["id"])}

    @app.post("/api/botlive/youtube/teste")
    async def botlive_yt_test(u: dict = Depends(admin_only)):
        c = get_bot()
        if c is None:
            return off()
        ok = await c.yt.send(u["id"], "🎧 Lofi Trading Bot is connected! Every bot buy will show up here.")
        return {"ok": ok, **await c.yt.status(u["id"])}

    async def painel_de(c, uid: str) -> dict:
        p = c.painel(uid)
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
