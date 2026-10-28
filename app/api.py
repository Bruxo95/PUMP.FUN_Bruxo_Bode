"""Rotas HTTP. Tudo em /api/* exige login (token do Supabase); o usuário vem SEMPRE do token.

Regras de segurança:
- Nenhuma rota devolve chave: só "configurada: sim/não" (e o endereço PÚBLICO da carteira).
- Ligar a execução real pede confirmação e fica no audit_log; volta a desligar quando o servidor reinicia.
- Salvar/remover chave, vender manual e trocar USDC→SOL também vão para o audit_log.
"""
from __future__ import annotations

import logging
import os
import re

from fastapi import Depends, FastAPI, HTTPException, Request
import hashlib

from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from .auth import AuthError
from .db import audit
from .hub import AccountBlocked
from .keystore import KEY_LINKS, SECRET_NAMES, SYSTEM_NAMES
from .settings import LB_DAYS
from .solana_wallet import check_rpc_url, parse_keypair
from .version import VERSION

UUID_ANY = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _started_at() -> str:
    """Hora em que este container subiu (= hora do último deploy), no fuso de Berlim."""
    from datetime import datetime, timezone
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(os.environ.get("TZ_PAINEL", "Europe/Berlin"))).strftime("%d/%m/%Y %H:%M:%S %Z")
    except Exception:
        return datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M:%S UTC")


STARTED_AT = _started_at()

log = logging.getLogger("api")
WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def create_app(hub, auth, cfg) -> FastAPI:
    app = FastAPI(title="PUMP FUN COPY", version=VERSION, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        sb = cfg.supabase_url or ""
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; "
            f"img-src 'self' data: https:; connect-src 'self' {sb} {sb.replace('https://', 'wss://')}; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
        if request.url.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        elif request.url.path in ("/", "/app") or request.url.path.startswith("/static/"):
            resp.headers["Cache-Control"] = "no-cache"          # o navegador sempre confere se há versão nova
        return resp

    # ------------------------------------------------------------------ usuário logado
    async def user(request: Request) -> dict:
        h = request.headers.get("authorization") or ""
        token = h[7:].strip() if h.lower().startswith("bearer ") else ""
        try:
            claims = await auth.verify(token)
        except AuthError as e:
            raise HTTPException(401, str(e)) from None
        try:
            prof = await hub.ensure_profile(claims)
        except Exception as e:
            log.warning("perfil: %s", str(e)[:160])
            raise HTTPException(503, "banco indisponível, tente de novo em instantes") from None
        if prof.get("bloqueado"):
            raise HTTPException(403, "conta bloqueada pelo administrador")
        meta = claims.get("user_metadata") or {}
        me = {"id": claims["sub"], "email": prof.get("email") or claims.get("email"),
              "nome": prof.get("nome") or meta.get("full_name") or meta.get("name"),
              "avatar": prof.get("avatar_url") or meta.get("avatar_url") or meta.get("picture"),
              "role": prof.get("role") or "user"}
        va = (request.headers.get("x-view-as") or "").strip().lower()
        if not va:
            return me
        # 0.31.36 (pedido do dono em 2026-10-27): o admin vê a tela de um usuário como ele vê, SÓ LEITURA. Qualquer
        # escrita é recusada aqui, antes de qualquer rota; chaves, registro e Administração não abrem; não vai para o
        # audit_log (pedido do dono: visualizar não é registrado).
        if me["role"] != "admin":
            raise HTTPException(403, "só o admin")
        if request.method != "GET":
            raise HTTPException(403, "modo visualização: só leitura")
        if request.url.path.startswith(("/api/secrets", "/api/audit", "/api/admin")):
            raise HTTPException(403, "não disponível na visualização")
        if not UUID_ANY.fullmatch(va):
            raise HTTPException(400, "usuário inválido")
        rows = await hub.db.select("profiles", {"user_id": va}, columns="user_id,email,nome,avatar_url,role")
        if not rows:
            raise HTTPException(404, "usuário não encontrado")
        t = rows[0]
        return {"id": va, "email": t.get("email"), "nome": t.get("nome"), "avatar": t.get("avatar_url"),
                "role": t.get("role") or "user", "view_by": me["id"], "view_by_nome": me["nome"] or me["email"]}

    async def engine(u: dict = Depends(user)):
        return await hub.engine(u["id"])

    def admin_only(u: dict = Depends(user)) -> dict:
        if u["role"] != "admin":
            raise HTTPException(403, "só o admin")
        return u

    # menu "Usar ou descartar" (Carteiras em estudo, Radar, Relatórios, Aprendizado): só admin também no servidor,
    # pedido do dono em 2026-10-25 (0.17.4); antes só o painel escondia
    async def admin_engine(u: dict = Depends(admin_only)):
        return await hub.engine(u["id"])

    # ------------------------------------------------------------------ público
    @app.get("/health")
    def health():
        return {"ok": True, "version": VERSION, "no_ar_desde": STARTED_AT}

    @app.get("/api/public-config")
    def public_config():
        """O que o navegador precisa para o botão "Entrar com Google" (chave ANON é pública por natureza)."""
        return {"supabase_url": cfg.supabase_url, "supabase_anon_key": cfg.supabase_anon_key,
                "base_url": cfg.public_base_url, "version": VERSION,
                "configured": bool(cfg.supabase_url and cfg.supabase_anon_key)}

    # ------------------------------------------------------------------ conta
    @app.get("/api/me")
    async def me(u: dict = Depends(user)):
        return {**u, "version": VERSION}

    # ------------------------------------------------------------------ painel PUMP.FUN
    @app.get("/api/pump")
    async def pump(ev: int = 0, pf=Depends(engine)):
        snap = pf.snapshot()
        snap["events"] = pf.events_after(ev)
        snap["keys"] = pf.keys.configured()
        snap["lb_status"]["own_key"] = pf.lb_key_own()
        snap["real"]["allowed"] = hub.real_allowed
        snap["version"] = VERSION
        snap["started_at"] = STARTED_AT
        return snap

    @app.post("/api/pump/settings")
    async def pump_settings(body: dict, pf=Depends(engine), u: dict = Depends(user)):
        if u["role"] != "admin" and any(key.startswith(("pump_ex_auto_", "pump_ar_")) for key in body):
            raise HTTPException(403, "só o admin pode configurar as novas entradas automáticas")
        radar_keys = ("pump_radar_enabled", "pump_radar_min_wallets", "pump_radar_window_min")
        radar_before = {key: getattr(pf.cfg, key) for key in radar_keys}
        applied, errors = pf.cfg.apply(body or {})
        if applied:
            await hub.save_settings(pf)
            if any(key in applied and applied[key] != radar_before[key] for key in radar_keys):
                pf._radar_alerts = {}
            if {"pump_min_winrate", "pump_lb_min_trades", "pump_top_n", "pump_only_online", "pump_online_min"} & set(applied):
                pf.refresh_followed(force=True)
        return {"applied": applied, "errors": errors}

    @app.post("/api/pump/real")
    async def pump_real(body: dict, u: dict = Depends(user)):
        pf = await hub.engine(u["id"])
        on = bool(body.get("enabled"))
        if on:
            if not hub.real_allowed:
                return {"error": "a execução real está travada no servidor (PUMP_REAL_ALLOWED=false no .env)"}
            if body.get("confirm") != "LIGAR":
                return {"error": "confirmação obrigatória"}
            if not (pf.sol_wallet and pf.sol_wallet.keypair):
                return {"error": "configure a carteira Solana do bot antes"}
        hub.check_active(u["id"], pf)
        pf.cfg.pump_real_enabled = on
        await hub.save_settings(pf)                   # 0.31.28: fica ligado até o usuário desligar (sobrevive ao reinício)
        await audit(hub.db, u["id"], "ligar execução real" if on else "desligar execução real",
                    f"máx. {pf.cfg.pump_real_max_sol} SOL por compra" if on else "")
        pf._emit(f"[PUMP REAL] execução real {'LIGADA' if on else 'DESLIGADA'} por você")
        return {"ok": True, "enabled": on}

    @app.get("/api/pump/reports")
    async def pump_reports(days: int = 7, real: int = 0, pf=Depends(admin_engine)):
        """Aba Relatórios: resultado por trader copiado, por motivo de saída, cópias barradas e por dia."""
        from .reports import build
        d = days if days in (1, 7, 30, 90) else None                 # 0 ou outro valor = todo o histórico
        return build(pf.trades(100000), list(pf.feed), d, bool(real), pf.followed, list(pf.paused()))

    @app.get("/api/pump/aprendizado")
    async def pump_aprendizado(real: int = 0, pf=Depends(admin_engine)):
        """Aprendizado diário: resumo, o que os top traders fizeram e sugestões (nunca aplicadas sozinhas)."""
        from .learning import build
        hist, err = await hub.learning_history(pf.user_id)
        out = build(pf, bool(real), hist)
        out["history_error"] = "histórico ainda não disponível (tabela do aprendizado não criada no banco)" if err else None
        return out

    @app.get("/api/pump/token/{mint}")
    async def pump_token(mint: str, pf=Depends(engine)):
        """Ficha do token: o que o sistema já sabe (mercado, curva, compras × vendas, risco, maiores carteiras)."""
        if not pf.valid_addr(mint):
            return {"error": "endereço de token inválido"}
        return pf.token_card(mint)

    @app.get("/api/pump/ghosts")
    async def pump_ghosts(pf=Depends(admin_engine)):
        """Estratégias fantasma (0.18.0): mesmas entradas da cópia fictícia, saídas diferentes, lado a lado."""
        return hub.ghosts_merged(pf, "ghosts")                   # 0.31.64: todas as contas (base geral)

    @app.get("/api/pump/copy-diag")
    async def copy_diag(pf=Depends(engine)):
        """0.31.78: compras dos traders seguidos vistas nas últimas 24 h, quantas foram copiadas e por que não."""
        r = pf.copy_diag()
        r["filtros"] = {k: getattr(pf.cfg, k, None) for k in ("pump_min_trader_sol", "pump_min_mcap_sol", "pump_max_mcap_sol",
                                                                   "pump_max_open", "pump_copy_sol", "pump_copy_delay_s", "pump_copy_enabled")}
        return r

    @app.get("/api/pump/explore")
    async def pump_explore(pf=Depends(admin_engine)):
        """Explorar (0.28.0): novos, quase graduando, graduados e os que mais sobem, com veredito e o que aprendeu."""
        out = hub.explore.snapshot(hub.market.blacklist, hub.market.creator_stats, pf.boost_info)
        for rows in list(out.get("lists", {}).values()) + [out.get("movers") or []]:
            for x in rows:
                safety_marks(pf, x)
                if x.get("vol24_usd") is None:                # 0.31.76: volume 24 h da DexScreener quando a fonte não traz
                    x["vol24_usd"] = ((pf.tokens.get(x["mint"]) or {}).get("vol") or {}).get("h24")
                x["pools"] = (pf.tokens.get(x["mint"]) or {}).get("pools")      # 0.31.77: cada pool do token
                # 0.31.11: por que o automático compra ou não este token (só faz sentido na lista Quase graduando)
                if not getattr(pf.cfg, "pump_ex_auto_on", True):
                    x["auto"] = {"ok": False, "motivo": "entrada automática do Explorar desligada"}
                else:
                    why = pf.explore_entry_reason({**x, "cat": x.get("cat")}) or pf.auto_guard(x["mint"])
                    held = any(p["mint"] == x["mint"] for p in pf.positions())
                    x["auto"] = {"ok": not why, "motivo": "já comprou (posição aberta)" if held else (why or "entra na próxima leitura")}
        out["learned_auto"] = pf.learned("explorar")
        from .autolearn import compare
        trades = pf.trades(100000)
        out["compare_auto"] = compare(trades, "explorar")
        out["ghosts_auto"] = hub.ghosts_merged(pf, "ghosts_auto", trades)   # 0.31.64: base geral
        out["learn_on"] = bool(getattr(pf.cfg, "pump_ar_learn", True))
        out["funnel"] = pf.explore_funnel()
        return out

    @app.get("/api/pump/real/mirror")
    async def real_mirror(pf=Depends(engine)):
        """0.31.38: trades reais do espelho × o trade fictício par."""
        L = pf.mirror_pairs()
        dif = [x["dif_pct"] for x in L if x["dif_pct"] is not None]
        return {"pairs": L, "media_dif_pct": round(sum(dif) / len(dif), 2) if dif else None,
                "real_sol": round(sum(x["real_sol"] or 0 for x in L), 6), "sim_pct_medio": None,
                "misses": pf.mirror_misses(), "real_on": bool(getattr(pf.cfg, "pump_real_enabled", False)),
                "mirror_on": bool(getattr(pf.cfg, "pump_real_mirror", True))}

    def safety_marks(pf, x: dict) -> None:
        """0.31.0: carteiras novas e traders bons em cada token da tela; muita carteira nova vira "lixo" na hora."""
        fr = (pf.tokens.get(x["mint"]) or {}).get("fresh")
        x["fresh"] = {k: fr.get(k) for k in ("n", "of", "pct")} if fr else None
        x["smart"] = len(pf.smart_in(x["mint"]))
        if fr and getattr(pf.cfg, "pump_ar_fresh_on", True) and fr["pct"] >= float(pf._c("pump_ar_fresh_max_pct", 30)):
            p = dict(x.get("pred") or {})
            p["verdict"], p["why"] = "lixo", [f"{fr['n']} de {fr['of']} maiores detentores são carteiras novas (robôs)"] + list(p.get("why") or [])
            x["pred"] = p

    @app.get("/api/pump/auto-trades")
    async def auto_trades(origem: str = "explorar", days: int = 30, pf=Depends(admin_engine)):
        if origem not in ("base", "explorar", "elite"):
            raise HTTPException(422, "origem deve ser base, explorar ou elite")
        if days not in (1, 7, 30, 90):
            raise HTTPException(422, "período deve ser 1, 7, 30 ou 90 dias")
        return await hub.auto_history(pf, origem, days)

    @app.get("/api/pump/elite")
    async def pump_elite(pf=Depends(admin_engine)):
        """Maiores traders (0.31.2): quem são, o que fizeram minuto a minuto, sinais, estudo, sugestões e resultados."""
        out = hub.elite.snapshot()
        auto = await hub.auto_history(pf, "elite", 30)
        out["auto"] = auto
        out["suggestions"] = hub.elite.suggestions(out["study"], auto)
        out["recommended"] = [r["wallet"] for r in hub.elite.recommended()]
        out["followed"] = list(pf.followed)
        out["studying"] = list(getattr(pf, "study", []) or [])
        for s in out["open"]:
            s["boost"] = pf.boost_info(s["mint"])
            s["fresh"] = (pf.tokens.get(s["mint"]) or {}).get("fresh")
        out["settings_on"] = bool(getattr(pf.cfg, "pump_el_auto_on", False))
        out["has_key"] = bool(pf.lb_key())
        return out

    @app.get("/api/pump/daily")
    async def pump_daily(dia: str = "", real: int = 0, pf=Depends(admin_engine)):
        """Relatório do dia (0.31.5): números da Visão geral ao longo do dia, diagnóstico e sugestões; e os dias anteriores.
        real=1 (0.31.45): o mesmo relatório só com os trades da carteira REAL."""
        return await daily_data(pf, dia, bool(real))

    @app.get("/api/pump/daily/pdf")
    async def pump_daily_pdf(dia: str = "", real: int = 0, pf=Depends(admin_engine)):
        """PDF do relatório do dia (0.31.7) para ver e mandar para uma IA revisar."""
        from .daily import blocks
        from .pdf import make
        d = await daily_data(pf, dia, bool(real))
        rep = d["report"]
        pdf = make(blocks(rep, d["study"], VERSION), f"Relatório {rep['dia']}")
        return Response(pdf, media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="relatorio-{rep["dia"]}.pdf"'})

    @app.get("/api/pump/daily/ai")
    async def pump_daily_ai(dia: str = "", real: int = 0, pf=Depends(admin_engine)):
        """O relatório do dia em texto, já com as instruções para a IA revisar e corrigir (0.31.7)."""
        from .daily import ai_text
        d = await daily_data(pf, dia, bool(real))
        return PlainTextResponse(ai_text(d["report"], d["study"], VERSION),
                                 headers={"Content-Disposition": f'attachment; filename="relatorio-{d["report"]["dia"]}-para-ia.md"'})

    @app.get("/api/pump/changes")
    async def pump_changes(pf=Depends(admin_engine)):
        """Relatórios das mudanças feitas pela IA (app/relatorios_ia) com projeção × realizado (0.31.7)."""
        from .changes import load, realized
        try:
            rows = await hub.db.select("daily_report", {"user_id": pf.user_id}, order="dia.desc", limit=120)
        except Exception:
            rows = []
        days = [{"dia": str(r.get("dia")), "pnl_sol": (r.get("data") or {}).get("pnl_sol")} for r in rows]
        out = []
        for ch in load():
            if ch.get("erro"):
                out.append(ch)
                continue
            out.append({**{k: v for k, v in ch.items() if k != "texto"}, "resumo": ch["texto"][:400], "real": realized(ch, days)})
        return {"changes": out}

    @app.get("/api/pump/changes/{nome}")
    async def pump_change(nome: str, pdf: int = 0, pf=Depends(admin_engine)):
        from .changes import load
        from .pdf import make
        ch = next((c for c in load() if c.get("nome") == nome and not c.get("erro")), None)
        if not ch:
            raise HTTPException(404, "relatório não encontrado")
        if not pdf:
            return ch
        head = [("title", f"Mudança {ch['versao']} - {ch['data']}"),
                ("small", f"Autor: {ch['autor']} · baseado em: {ch['baseado_em']}"),
                ("h", "Projeção"),
                ("p", (f"{ch['projecao_sol_dia']:+.4f} SOL por dia (carteira fictícia). " if ch["projecao_sol_dia"] is not None else "Não estimada. ")
                 + ch["projecao_texto"]), ("h", "O que foi feito")]
        body = []
        for ln in ch["texto"].splitlines():
            body.append(("h", ln.lstrip("# ")) if ln.startswith("#") else ("p", ln))
        return Response(make(head + body, f"Mudança {ch['versao']}"), media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="mudanca-{nome}.pdf"'})

    async def daily_data(pf, dia: str = "", real: bool = False) -> dict:
        from .daily import build, day_of, kpis
        today = day_of(__import__("time").time())
        dia = dia if __import__("re").fullmatch(r"\d{4}-\d{2}-\d{2}", dia or "") else today
        if real:
            # 0.31.45: a carteira real não tem relatórios guardados; cada dia é calculado na hora dos trades reais
            from .daily import days_with_trades, study
            from .modules_report import build as menus
            allt = pf.trades(100000)
            try:
                srows = await hub.db.select("daily_report", {"user_id": pf.user_id}, order="dia.desc", limit=30)
            except Exception:
                srows = []
            kept = {str(r.get("dia")): (r.get("data") or {}).get("real_report") for r in srows}
            kept = {d: x for d, x in kept.items() if x and d != today}     # 0.31.49: dias fechados guardados da real
            days = [today] + sorted(set(days_with_trades(pf, today, 30, real=True, all_trades=allt)) | set(kept), reverse=True)
            reps = {d: kept.get(d) or build(pf, d, None, real=True, all_trades=allt) for d in days}
            if dia not in reps:
                reps[dia] = build(pf, dia, None, real=True, all_trades=allt)
            if dia == today:
                reps[today]["modules"] = menus(hub, pf, dia, True)
                try:
                    from .versions_report import build as vbuild, compact, load as vload
                    reps[today]["versoes"] = compact(vbuild(allt, vload(), real=True))
                except Exception:
                    pass
            hist = [{"dia": d, "pnl_sol": x.get("pnl_sol"), "trades": x.get("trades"), "acerto": x.get("acerto"),
                     "sugestoes": len(x.get("suggestions") or []), "closed": d != today} for d, x in reps.items()]
            return {"report": reps[dia], "days": hist, "today": today, "real": True,
                    "study": study([x for x in reps.values() if x.get("trades")] or [reps[today]])}
        try:
            rows = await hub.db.select("daily_report", {"user_id": pf.user_id}, order="dia.desc", limit=30)
        except Exception:
            rows = []
        saved = {str(r.get("dia")): (r.get("data") or {}) for r in rows}
        pts = list((saved.get(dia) or {}).get("points") or [])
        if dia == today:
            from .modules_report import build as menus
            rep = build(pf, dia, pts + [kpis(pf)])            # hoje: ao vivo, com a foto de agora no fim
            rep["modules"] = menus(hub, pf, dia, True)        # relatório de cada menu (0.31.9)
        else:
            rep = saved.get(dia) or build(pf, dia, pts)
        hist = [{"dia": d, "pnl_sol": x.get("pnl_sol"), "trades": x.get("trades"), "acerto": x.get("acerto"),
                 "sugestoes": len(x.get("suggestions") or []), "closed": bool(x.get("closed"))} for d, x in saved.items()]
        if not [d for d in saved if d != today]:                 # ainda sem dias passados guardados: refaz agora
            try:
                pf._daily_backfilled = False
                if await hub.backfill_daily():
                    rows = await hub.db.select("daily_report", {"user_id": pf.user_id}, order="dia.desc", limit=30)
                    saved = {str(r.get("dia")): (r.get("data") or {}) for r in rows}
                    hist = [{"dia": d, "pnl_sol": x.get("pnl_sol"), "trades": x.get("trades"), "acerto": x.get("acerto"),
                             "sugestoes": len(x.get("suggestions") or []), "closed": bool(x.get("closed"))} for d, x in saved.items()]
            except Exception:
                pass
        from .daily import study
        past = [x for d, x in saved.items() if d != today]
        try:
            from .versions_report import build as vbuild, compact, load as vload
            rep["versoes"] = compact(vbuild(pf.trades(100000), vload()))
        except Exception:
            pass
        return {"report": rep, "days": hist, "today": today, "study": study(past + [rep])}

    @app.get("/api/pump/elite/steps")
    async def pump_elite_steps(only80: int = 1, pf=Depends(admin_engine)):
        """Steps ao vivo (0.31.4): o que os maiores traders (só os 80%+, ou todos) fizeram e o que o robô fez junto."""
        rec = {r["wallet"] for r in hub.elite.recommended()}
        return {"steps": hub.elite.steps(list(pf.feed), pf.positions(), pf.trades(3000), rec if only80 else None),
                "copy80": bool(getattr(pf.cfg, "pump_el_copy80", True)), "recommended": sorted(rec),
                "following": [w for w in rec if w in pf.followed]}

    @app.get("/api/pump/base")
    async def pump_base(pf=Depends(admin_engine)):
        """Base própria da pump.fun (0.21.0): ficha de vida dos tokens novos, criadores e mercado por hora."""
        out = hub.lab.snapshot()
        for x in out.get("rising") or []:
            safety_marks(pf, x)
        out["hide_trash"] = bool(getattr(pf.cfg, "pump_base_hide_trash", False))
        # suas compras feitas pelo botão Comprar (abertas e fechadas nas últimas 48 h), com o boost de cada uma
        lim = __import__("time").time() - 172800
        mine = [{"mint": p["mint"], "symbol": p.get("symbol"), "open": True, "real": bool(p.get("real")),
                 "sol_in": p.get("sol_in"), "chg_pct": p.get("chg_pct"), "opened_at": p.get("opened_at"),
                 "mcap": (pf.tokens.get(p["mint"]) or {}).get("mcap_sol"), "boost": pf.boost_info(p["mint"])}
                for p in pf.positions() if p.get("origem") != "explorar" and (p.get("manual") or p.get("wallet") == "manual")]
        mine += [{"mint": t["mint"], "symbol": t.get("symbol"), "open": False, "real": bool(t.get("real")),
                  "sol_in": t.get("sol_in"), "pnl_sol": t.get("pnl_sol"), "pnl_pct": t.get("pnl_pct"),
                  "reason": t.get("reason"), "opened_at": t.get("opened_at"), "closed_at": t.get("closed_at"),
                  "boost": pf.boost_info(t["mint"])}
                 for t in pf.trades(3000) if t.get("origem") != "explorar" and (t.get("manual") or t.get("wallet") == "manual")
                 and (pf._ts(t.get("closed_at")) or 0) >= lim]
        out["mine"] = mine
        return out

    @app.post("/api/pump/manual-buy")
    async def manual_buy(body: dict, pf=Depends(admin_engine)):
        """Botão Comprar (0.23.0): compra manual na fictícia (e na real só se ela estiver ligada)."""
        mint = str(body.get("mint") or "").strip()
        if not pf.valid_addr(mint):
            return {"error": "endereço de token inválido"}
        if not (pf.tokens.get(mint) or {}).get("price") and hub.monitor is not None:
            try:                                                   # preço na hora, direto da curva on-chain
                await hub.monitor.svc._curve_prices([mint], public_first=True)
                if not (pf.tokens.get(mint) or {}).get("price"):        # já graduado: preço pela DexScreener
                    await hub.monitor.svc._fetch_prices([mint])
            except Exception:
                pass
        r = pf.manual_buy(mint)
        if not r.get("error"):
            await audit(hub.db, pf.user_id, "compra manual", f"{mint[:6]}… · fictícia: {r.get('sim')} · real: {r.get('real') or 'desligada'}")
        return r

    @app.post("/api/pump/telegram/test")
    async def telegram_test(pf=Depends(admin_engine)):
        ok, err = await hub.tg_send_now(pf, "PUMP FUN COPY: teste de aviso no Telegram ✅", force=True)
        return {"ok": True} if ok else {"error": err}

    @app.get("/api/pump/blacklist")
    async def blacklist_list(pf=Depends(admin_engine)):
        rows = sorted(hub.market.blacklist.items(), key=lambda kv: str(kv[1].get("criado_em") or ""), reverse=True)
        return {"items": [{"endereco": k, **v} for k, v in rows][:500], "count": len(rows),
                "on": bool(getattr(pf.cfg, "pump_blacklist_on", False))}

    @app.post("/api/pump/blacklist")
    async def blacklist_change(body: dict, u: dict = Depends(admin_only)):
        pf = await hub.engine(u["id"])
        addr, act = str(body.get("endereco") or "").strip(), str(body.get("action") or "add")
        tipo, motivo = str(body.get("tipo") or "dev"), str(body.get("motivo") or "adicionado pelo admin")[:120]
        if not pf.valid_addr(addr) or act not in ("add", "remove") or tipo not in ("dev", "carteira"):
            return {"error": "endereço, ação ou tipo inválido"}
        try:
            if act == "remove":
                await hub.blacklist_remove(addr)
            else:
                pf.blacklist_add(addr, tipo, motivo)
                await hub.flush_blacklist()
        except Exception as e:
            log.warning("lista negra: %s", str(e)[:120])
            return {"error": "não consegui salvar agora (tabela criada no banco?)"}
        await audit(hub.db, u["id"], "lista negra: " + ("remover" if act == "remove" else "adicionar"), f"{tipo} {addr[:6]}…")
        return {"ok": True}

    @app.get("/api/pump/radar")
    async def radar(pf=Depends(admin_engine)):
        r = hub.radar_snapshot(pf)
        r.update(hub.radar_calls(pf))                 # 0.31.96: compras e ondas guardadas
        # 0.31.97 (pedido do dono: "ver a lista dessas carteiras, não só números"): as carteiras da lista com apelido,
        # compras nas últimas 24 h e a última compra (das calls guardadas)
        try:
            rows = await hub.db.select("study_wallets", {"user_id": pf.user_id}, order="criado_em.asc")
        except Exception:
            rows = []
        # 0.31.98 (pedido do dono): 24 h, 48 h, 3 e 7 dias, do histórico que as Carteiras em estudo já guardam desde a
        # 0.14.0 (tabela wallet_trades), não só das calls (que começaram na 0.31.94)
        import time
        from datetime import datetime, timezone
        from .auto_trades import ts as _ts
        now = time.time()
        since = datetime.fromtimestamp(now - 7 * 86400, timezone.utc).isoformat()
        lst = []
        for x in rows:
            try:
                tr = await hub.db.select("wallet_trades", {"wallet": x["wallet"], "side": "buy"}, order="at.desc", limit=500, gte={"at": since})
            except Exception:
                tr = []
            ages = [now - (_ts(t.get("at")) or 0) for t in tr]
            last = tr[0] if tr else None
            lst.append({"wallet": x["wallet"], "apelido": x.get("apelido"), "desde": x.get("criado_em"),
                        "compras": {k: sum(1 for a in ages if a <= h * 3600) for k, h in (("24h", 24), ("48h", 48), ("3d", 72), ("7d", 168))},
                        "ultima": {"mint": last["mint"], "symbol": (hub.market.tokens.get(last["mint"]) or {}).get("symbol"), "t": _ts(last.get("at")),
                                   "sol": last.get("sol")} if last else None,
                        "online": pf.is_online(x["wallet"]) if hasattr(pf, "is_online") else None})
        r["lista"] = sorted(lst, key=lambda y: -((y["ultima"] or {}).get("t") or 0))
        return r

    # ------------------------------------------------------------------ carteiras em estudo (0.14.0)
    @app.get("/api/pump/study")
    async def study_list(pf=Depends(admin_engine)):
        from .study import MAX_WALLETS, copy_params, summary
        prm = copy_params(pf)
        try:
            rows = await hub.db.select("study_wallets", {"user_id": pf.user_id}, order="criado_em.asc")
        except Exception:
            return {"wallets": [], "error": "tabelas das carteiras em estudo ainda não criadas no banco"}
        out = []
        for r in rows:
            p = await hub.study_profile(r["wallet"], prm)
            out.append({"wallet": r["wallet"], "apelido": r.get("apelido"), "followed": r["wallet"] in pf.followed,
                        "summary": summary(p) if not p.get("error") else {}})
        # ranking de copiabilidade: quem renderia mais para VOCÊ copiando nos últimos 30 dias (0.15.0)
        ranked = sorted([x for x in out if (x["summary"].get("copy") or {}).get("n_30d")],
                        key=lambda x: -(x["summary"]["copy"]["pnl_30d"] or 0))
        return {"wallets": out, "ranking": [{"wallet": x["wallet"], "apelido": x["apelido"], "followed": x["followed"],
                                             **x["summary"]["copy"]} for x in ranked],
                "limit": MAX_WALLETS, "key": bool(hub._study_key()), "params": prm,
                "mine": study_my_results(pf, out), "auto": await study_auto_info(pf)}

    async def study_auto_info(pf) -> dict:
        from datetime import datetime, timezone
        from .autostudy import AUTO_TAG, rates
        try:
            log_rows = await hub.db.select("study_auto_log", {"user_id": pf.user_id}, order="em.desc", limit=1000)
        except Exception:
            log_rows = []
        last = hub._study_auto_at.get(pf.user_id)
        return {"on": bool(getattr(pf.cfg, "pump_st_auto_on", True)), "max": int(getattr(pf.cfg, "pump_st_auto_max", 15)),
                "tag": AUTO_TAG, "last_run": datetime.fromtimestamp(last, timezone.utc).isoformat() if last else None,
                "log": [{k: r.get(k) for k in ("wallet", "acao", "motivo", "em")} for r in log_rows[:60]],
                "counts": {a: sum(1 for r in log_rows if r.get("acao") == a) for a in ("adicionou", "aprovou", "descartou")},
                "rates": rates(log_rows)}

    @app.get("/api/pump/tune")
    async def tune_info(pf=Depends(admin_engine)):
        from datetime import datetime, timezone
        from .autotune import EVAL_S, EVAL_TRADES, MIN_DAYS, MIN_TRADES
        try:
            rows = await hub.db.select("auto_tune_log", {"user_id": pf.user_id}, order="em.desc", limit=200)
        except Exception:
            rows = []
        last = hub._tune_at.get(pf.user_id)
        sai = next((r for r in rows if r.get("tipo") == "saida"), None)
        return {"on": bool(getattr(pf.cfg, "pump_tune_on", True)), "real_on": bool(getattr(pf.cfg, "pump_real_enabled", False)),
                "last_run": datetime.fromtimestamp(last, timezone.utc).isoformat() if last else None,
                "testing": {"nome": (sai.get("detalhe") or {}).get("nome"), "desde": sai.get("em")} if sai and sai.get("acao") == "aplicou" else None,
                "rules": {"min_trades": MIN_TRADES, "min_days": MIN_DAYS, "eval_h": EVAL_S // 3600, "eval_trades": EVAL_TRADES},
                "log": [{k: r.get(k) for k in ("tipo", "acao", "motivo", "em")} for r in rows[:60]]}

    @app.post("/api/pump/tune/run")
    async def tune_run(pf=Depends(admin_engine)):
        try:
            return await hub.auto_tune(pf)
        except Exception as e:
            log.warning("ajuste automático: %s", str(e)[:120])
            return {"error": "não consegui rodar agora (tabela criada no banco?)"}

    @app.post("/api/pump/study/auto/run")
    async def study_auto_run(pf=Depends(admin_engine)):
        try:
            return await hub.study_auto(pf)
        except Exception as e:
            log.warning("estudo automático: %s", str(e)[:120])
            return {"error": "não consegui rodar agora (tabela criada no banco?)"}

    def study_my_results(pf, wallets: list[dict]) -> dict:
        """O SEU resultado de verdade copiando cada carteira em estudo (0.29.0, pedido do dono): trades fechados e
        posições abertas do próprio usuário com essa carteira, separados em fictício e real."""
        trades, poss = pf.trades(100000), pf.positions()
        rows, tot = [], {"sim": [0, 0, 0.0, 0.0], "real": [0, 0, 0.0, 0.0]}
        feed = list(pf.feed)
        for x in wallets:
            w = x["wallet"]
            # 0.31.2: por que ainda não há resultado (o dono viu "0" copiando 2 carteiras): o que o feed mostra
            F = [e for e in feed if e.get("wallet") == w and e.get("kind") == "buy"]
            skips: dict[str, int] = {}
            for e in F:
                if str(e.get("action") or "").endswith("não copiou"):
                    k = __import__("re").sub(r"[\d.,%$+−-]+", "#", str(e.get("reason") or "?"))[:70]
                    skips[k] = skips.get(k, 0) + 1
            diag = {"buys_seen": len(F), "copied": sum(1 for e in F if str(e.get("action") or "").startswith("copiou")),
                    "skipped": sum(skips.values()),
                    "top_skips": sorted(({"reason": k, "n": v} for k, v in skips.items()), key=lambda r: -r["n"])[:3]}
            for real in (False, True):
                T = [t for t in trades if t.get("wallet") == w and bool(t.get("real")) == real]
                P = [p for p in poss if p.get("wallet") == w and bool(p.get("real")) == real]
                if not T and not P and not (x.get("followed") and not real):
                    continue
                n, wins = len(T), sum(1 for t in T if (t.get("pnl_sol") or 0) > 0)
                pnl, inv = sum(t.get("pnl_sol") or 0 for t in T), sum(t.get("sol_in") or 0 for t in T)
                k = tot["real" if real else "sim"]
                k[0] += n; k[1] += wins; k[2] += pnl; k[3] += inv
                opened = min([str(t.get("opened_at") or "") for t in T] + [str(p.get("opened_at") or "") for p in P] or [""]) or None
                rows.append({"wallet": w, "apelido": x.get("apelido"), "followed": x.get("followed"), "real": real,
                             "since": opened, "trades": n, "win_rate": wins / n if n else None,
                             "pnl_sol": round(pnl, 6), "invested_sol": round(inv, 6),
                             "roi_pct": round(pnl / inv * 100, 2) if inv else None,
                             "open": len(P), "open_sol": round(sum(p.get("sol_in") or 0 for p in P), 6),
                             "open_chg": round(sum(p.get("chg_pct") or 0 for p in P) / len(P), 2) if P else None,
                             "last": max([str(t.get("closed_at") or "") for t in T] or [""]) or None,
                             "diag": diag if not real else None})
        rows.sort(key=lambda r: -r["pnl_sol"])
        return {"rows": rows, "total": {k: {"trades": v[0], "win_rate": v[1] / v[0] if v[0] else None,
                                            "pnl_sol": round(v[2], 6), "roi_pct": round(v[2] / v[3] * 100, 2) if v[3] else None}
                                        for k, v in tot.items()}}

    @app.post("/api/pump/study")
    async def study_change(body: dict, pf=Depends(admin_engine)):
        w, act = str(body.get("wallet") or "").strip(), str(body.get("action") or "add")
        if act not in ("add", "remove"):
            return {"error": "ação inválida"}
        if not pf.valid_addr(w):
            return {"error": "endereço de carteira inválido"}
        try:
            return await hub.study_set(pf, w, act, str(body.get("apelido") or ""))
        except Exception as e:
            log.warning("carteiras em estudo: %s", str(e)[:120])
            return {"error": "não consegui salvar agora (tabela criada no banco?)"}

    @app.post("/api/pump/explore/share")
    async def explore_share(body: dict, u: dict = Depends(admin_only)):
        pf = await hub.engine(u["id"])
        try:
            return await hub.explore_share(pf, u, str(body.get("to") or ""), str(body.get("part") or ""))
        except Exception as e:
            log.warning("compartilhar Explorar: %s", str(e)[:120])
            return {"error": "não consegui compartilhar agora"}

    @app.get("/api/pump/config/share-targets")
    async def config_share_targets(u: dict = Depends(admin_only)):
        return {"users": await hub.share_targets(u["id"])}

    @app.post("/api/pump/config/share")
    async def config_share(body: dict, u: dict = Depends(admin_only)):
        """Configurações → Compartilhar (0.31.17): uma seção (lista de opções da tela) ou tudo."""
        from .settings import USER_KEYS
        pf = await hub.engine(u["id"])
        keys = list(USER_KEYS) if body.get("all") else [str(k) for k in (body.get("keys") or [])][:300]
        parte = str(body.get("parte") or ("toda a configuração" if body.get("all") else "configuração"))[:200]
        try:
            return await hub.config_offer(pf, u, str(body.get("to") or ""), parte, keys)
        except Exception as e:
            log.warning("compartilhar configuração: %s", str(e)[:120])
            return {"error": "não consegui enviar agora (tabela criada no banco?)"}

    @app.get("/api/pump/config/offers")
    async def config_offers(u: dict = Depends(user)):
        try:
            return {"offers": await hub.config_offers(u["id"])}
        except Exception:
            return {"offers": []}

    @app.get("/api/pump/config/users")
    async def config_users(u: dict = Depends(user)):
        return {"users": await hub.config_users(u["id"])}

    @app.get("/api/pump/config/applied")
    async def config_applied(u: dict = Depends(user)):
        return {"applied": await hub.config_applied(u["id"])}

    @app.post("/api/pump/config/applied/{offer_id}/sync")
    async def config_sync(offer_id: int, u: dict = Depends(user)):
        pf = await hub.engine(u["id"])
        hub.check_active(u["id"], pf)
        return await hub.config_sync(pf, offer_id)

    @app.post("/api/pump/config/offers/{offer_id}")
    async def config_answer(offer_id: int, body: dict, u: dict = Depends(user)):
        pf = await hub.engine(u["id"])
        hub.check_active(u["id"], pf)
        return await hub.config_answer(pf, offer_id, bool(body.get("accept")))

    @app.get("/api/pump/study/share-targets")
    async def study_share_targets(u: dict = Depends(admin_only)):
        return {"users": await hub.study_share_targets(u["id"])}

    @app.post("/api/pump/study/share")
    async def study_share(body: dict, u: dict = Depends(admin_only)):
        w, to = str(body.get("wallet") or "").strip(), str(body.get("to") or "").strip()
        pf = await hub.engine(u["id"])
        if not pf.valid_addr(w) or not UUID.match(to):
            return {"error": "carteira ou usuário inválido"}
        try:
            return await hub.study_share(pf, u, w, to)
        except Exception as e:
            log.warning("compartilhar carteira em estudo: %s", str(e)[:120])
            return {"error": "não consegui compartilhar agora"}

    @app.get("/api/pump/study/{wallet}")
    async def study_profile(wallet: str, pf=Depends(admin_engine)):
        if not pf.valid_addr(wallet) or wallet not in (getattr(pf, "study", []) or []):
            return {"error": "carteira não está no seu estudo"}
        from .study import copy_params
        return await hub.study_profile(wallet, copy_params(pf))

    @app.get("/api/pump/wallet")
    async def pump_wallet(force: int = 0, pf=Depends(engine)):
        """Saldo REAL da carteira do bot: SOL (o que paga as compras) e USDC convertido em SOL."""
        sb = await pf.jw.sol_balances(force=bool(force))
        sol_usd = pf.sol_usd
        usdc = (sb.get("tokens") or {}).get(USDC, 0.0)
        return {"configured": bool(sb.get("configured")), "address": pf.sol_wallet.address if pf.sol_wallet else None,
                "error": sb.get("error"), "sol": sb.get("sol"), "usdc": usdc, "sol_usd": sol_usd,
                "usdc_in_sol": (usdc / sol_usd) if sol_usd else None, "reserve_sol": 0.02,
                "rpc": pf.sol_wallet.public() if pf.sol_wallet else None}

    @app.get("/api/pump/swap/quote")
    async def pump_swap_quote(usdc: float = 0, pf=Depends(engine)):
        return await pf.jw.usdc_to_sol(float(usdc), preview=True)

    @app.post("/api/pump/swap")
    async def pump_swap(body: dict, u: dict = Depends(user)):
        """Troca USDC → SOL na carteira do bot (transação REAL; o painel pede confirmação)."""
        pf = await hub.engine(u["id"])
        if body.get("confirm") is not True:
            return {"error": "confirmação obrigatória"}
        try:
            usdc = float(body.get("usdc") or 0)
        except (TypeError, ValueError):
            return {"error": "valor inválido"}
        hub.check_active(u["id"], pf)
        r = await pf.jw.usdc_to_sol(usdc)
        await audit(hub.db, u["id"], "trocar USDC→SOL",
                    f"{usdc:.2f} USDC → {'ok ' + format(r.get('sol_received') or 0, '.4f') + ' SOL' if r.get('ok') else 'falhou: ' + str(r.get('error') or r.get('reason'))[:120]}")
        if r.get("ok"):
            pf._emit(f"Carteira: trocou {r['usdc']:.2f} USDC → {r['sol_received']:.4f} SOL ({r.get('venue')})")
        elif r.get("reason"):
            pf._emit(f"Carteira: troca USDC→SOL falhou — {r['reason']}")
        return r

    @app.post("/api/pump/wallets")
    async def pump_wallets(body: dict, pf=Depends(engine)):
        w, act = str(body.get("wallet") or "").strip(), body.get("action") or "add"
        fn = {"add": pf.add_manual, "remove": pf.remove_manual, "ban": pf.ban, "unban": pf.unban,
              "pause": pf.pause, "resume": pf.resume}.get(act)
        if not fn:
            return {"error": "ação inválida"}
        if not pf.valid_addr(w):
            return {"error": "endereço de carteira inválido"}
        if act == "pause" and body.get("hours"):
            try:
                hrs = float(body["hours"])
            except (TypeError, ValueError):
                return {"error": "horas inválidas"}
            if not 0 < hrs <= 720:
                return {"error": "horas inválidas"}
            return pf.pause(w, hrs)
        return fn(w)

    @app.post("/api/pump/close")
    async def pump_close(body: dict, u: dict = Depends(user)):
        pf = await hub.engine(u["id"])
        pid = body.get("id")
        pos = next((p for p in pf.positions() if str(p["id"]) == str(pid)), None)
        if not pos:
            return {"error": "posição não encontrada"}
        hub.check_active(u["id"], pf)
        r = pf.close_position(pid)
        await audit(hub.db, u["id"], "vender manual",
                    f"{'REAL' if pos.get('real') else 'fictícia'} · {pos.get('symbol')} · {pos.get('mint')}")
        if r.get("msg"):
            pf._emit(r["msg"])
        return r

    @app.post("/api/pump/positions/hold")
    async def pump_hold(body: dict, u: dict = Depends(user)):
        """0.31.69 (sugestão do Bruxo): estender o tempo máximo de uma posição aberta, ou tirar o limite."""
        pf = await hub.engine(u["id"])
        hub.check_active(u["id"], pf)
        add = body.get("add_min")
        try:
            add = None if add in (None, "", "none") else float(add)
        except (TypeError, ValueError):
            return {"error": "valor inválido"}
        r = pf.extend_hold(body.get("id"), add)
        if r.get("ok"):
            await audit(hub.db, u["id"], "posição: tempo estendido", f"{body.get('id')} · " + ("sem limite" if add is None else f"+{add:g} min"))
        return r

    @app.post("/api/pump/positions/rule")
    async def pump_pos_rule(body: dict, u: dict = Depends(user)):
        """0.31.87 (Bruxo): desligar/ligar stop de perda, stop móvel ou venda em partes de uma posição aberta."""
        pf = await hub.engine(u["id"])
        hub.check_active(u["id"], pf)
        r = pf.position_rule(body.get("id"), str(body.get("regra") or ""), bool(body.get("on")))
        if r.get("ok"):
            await audit(hub.db, u["id"], "posição: regra de saída", f"{body.get('id')} · {r['regra']} {'ligado' if r['on'] else 'desligado'}")
        return r

    @app.post("/api/pump/leaderboard")
    async def pump_lb(body: dict, pf=Depends(engine)):
        """Troca o período do leaderboard (1/7/30/90 dias) e atualiza agora."""
        try:
            d = int(body.get("days") or 7)
        except (TypeError, ValueError):
            d = 7
        pf.cfg.pump_lb_days = d if d in LB_DAYS else 7
        await hub.save_settings(pf)
        wait = await pf.refresh_leaderboard_user()
        if wait:
            return {"ok": False, "error": wait, **{k: v for k, v in pf.lb_status.items() if k != "error"}}
        return {"ok": not pf.lb_status.get("error"), **pf.lb_status}

    @app.post("/api/pump/reset")
    async def pump_reset(pf=Depends(engine)):
        result = pf.reset_sim()
        if result.get("ok"):
            pf._emit("Pump.fun: carteira fictícia zerada (volta ao saldo inicial)")
        return result

    # ------------------------------------------------------------------ chaves pessoais
    @app.get("/api/secrets")
    async def secrets_list(pf=Depends(engine)):
        sysk = hub.system_keys
        return {"keys": {k: {"label": v, "configured": bool(pf.keys.get(k)), "system": bool(sysk.get(k)),
                             "link": KEY_LINKS.get(k)} for k, v in SECRET_NAMES.items()},
                "wallet": pf.sol_wallet.public() if pf.sol_wallet else None}

    @app.post("/api/secrets")
    async def secrets_save(body: dict, u: dict = Depends(user)):
        pf = await hub.engine(u["id"])
        name, value = str(body.get("name") or ""), str(body.get("value") or "").strip()
        if name not in SECRET_NAMES:
            return {"error": "chave desconhecida"}
        try:
            if name == "wallet_private_key":
                parse_keypair(value)
            elif name == "rpc_url":
                value = check_rpc_url(value)
            elif name == "telegram_chat_id":
                if not __import__("re").fullmatch(r"-?\d{3,20}", value):
                    raise ValueError("ID do chat inválido (só números, ex.: 123456789)")
            elif name == "telegram_bot_token":
                if not __import__("re").fullmatch(r"\d{5,15}:[A-Za-z0-9_-]{30,60}", value):
                    raise ValueError("token do bot inválido (formato 123456:ABC…)")
            elif len(value) < 16:
                raise ValueError("chave inválida (curta demais)")
        except ValueError as e:
            return {"error": str(e)}
        hub.check_active(u["id"], pf)
        try:
            await hub.set_secret(pf, name, value)
        except Exception as e:
            log.warning("salvar chave %s: %s", name, str(e)[:120])
            return {"error": "não consegui salvar no banco agora"}
        out = {"ok": True, "configured": True}
        if name == "solanatracker_api_key":
            await pf.refresh_leaderboard(force=True)
            st = pf.lb_status
            out.update(ok=not st.get("error"), error=st.get("error"), count=st.get("count"))
        if name == "wallet_private_key":
            out["address"] = pf.sol_wallet.address
        return out

    @app.post("/api/secrets/remove")
    async def secrets_remove(body: dict, u: dict = Depends(user)):
        pf = await hub.engine(u["id"])
        name = str(body.get("name") or "")
        if name not in SECRET_NAMES:
            return {"error": "chave desconhecida"}
        await hub.remove_secret(pf, name)
        if name == "solanatracker_api_key":
            pf.leaderboard = []
            pf.refresh_followed(force=True)
        return {"ok": True, "configured": False}

    @app.get("/api/audit")
    async def audit_list(u: dict = Depends(user)):
        rows = await hub.db.select("audit_log", {"user_id": u["id"]}, order="at.desc", limit=50)
        nm = await _names(rows)
        return [{"acao": r.get("acao"), "detalhe": nm(r.get("detalhe")), "at": r.get("at")} for r in rows]

    async def _names(rows):
        """0.31.31: o registro mostrava o código do usuário (uuid); troca pelo nome (ou começo do e-mail)."""
        if not any(UUID_ANY.search(str(r.get("detalhe") or "")) for r in rows):
            return lambda s: s
        try:
            ps = await hub.db.select("profiles", None, columns="user_id,nome,email")
        except Exception:
            return lambda s: s
        names = {p["user_id"]: (p.get("nome") or (p.get("email") or "").split("@")[0] or "usuário") for p in ps}
        return lambda s: UUID_ANY.sub(lambda m: names.get(m.group(0), m.group(0)), s or "")

    # ------------------------------------------------------------------ admin (status geral, nunca chaves)
    @app.get("/api/admin/status")
    async def admin_status(u: dict = Depends(admin_only)):
        profs = await hub.db.select("profiles", None, columns="user_id")
        return {**hub.admin_status(), "users_total": len(profs)}

    @app.get("/api/admin/keys")
    async def admin_keys(u: dict = Depends(admin_only)):
        """Chaves do SISTEMA (só "configurada: sim/não" — o valor nunca volta)."""
        return {"keys": await hub.system_keys_view()}

    @app.post("/api/admin/keys")
    async def admin_keys_save(body: dict, u: dict = Depends(admin_only)):
        name, value = str(body.get("name") or ""), str(body.get("value") or "").strip()
        if name not in SYSTEM_NAMES:
            return {"error": "chave desconhecida"}
        if name == "rpc_url":
            try:
                value = check_rpc_url(value)
            except ValueError as e:
                return {"error": str(e)}
        elif len(value) < 16:
            return {"error": "chave inválida (curta demais)"}
        try:
            await hub.set_system_key(u["id"], name, value)
        except Exception as e:
            log.warning("salvar chave do sistema %s: %s", name, str(e)[:120])
            return {"error": "não consegui salvar no banco agora"}
        out = {"ok": True, "configured": True}
        if name == "solanatracker_api_key" and hub.monitor:
            await hub.monitor.lb_once(force=True)
        return out

    @app.post("/api/admin/keys/remove")
    async def admin_keys_remove(body: dict, u: dict = Depends(admin_only)):
        name = str(body.get("name") or "")
        if name not in SYSTEM_NAMES:
            return {"error": "chave desconhecida"}
        await hub.remove_system_key(u["id"], name)
        return {"ok": True, "configured": False}

    # ------------------------------------------------------------------ admin: gestão de usuários e logs
    UUID = __import__("re").compile(r"^[0-9a-fA-F-]{36}$")

    @app.get("/api/admin/users")
    async def admin_users(u: dict = Depends(admin_only)):
        """Lista de contas com números de uso — nunca as chaves (só "configurada: sim/não")."""
        return {"users": await hub.admin_users(), "me": u["id"]}

    @app.post("/api/admin/users/{uid}")
    async def admin_user_update(uid: str, body: dict, u: dict = Depends(admin_only)):
        if not UUID.match(uid):
            return {"error": "usuário inválido"}
        allowed = {k: body[k] for k in ("role", "bloqueado", "real_off") if k in (body or {})}
        if not allowed:
            return {"error": "nada para alterar"}
        return await hub.admin_update_user(u["id"], uid, allowed)

    # ------------------------------------------------------------------ comparar configuração copiada (0.31.34, admin)
    @app.get("/api/pump/compare")
    async def compare_list(u: dict = Depends(admin_only)):
        try:
            saved = await hub.compare_saved(u["id"])
        except Exception:
            saved = []                                  # tabela ainda não criada
        return {"copias": await hub.compare_list(u["id"]), "salvas": saved}

    @app.get("/api/pump/compare/{offer_id}")
    async def compare_one(offer_id: int, origem: str = "", real: int = 0, u: dict = Depends(admin_only)):
        return await hub.compare_one(u["id"], offer_id, origem=origem if origem in ("explorar", "base", "elite") else None,
                                     real=bool(real))

    @app.get("/api/pump/calls")
    async def calls_view(pf=Depends(admin_engine)):
        """0.31.94: calls quentes pela blockchain (compras das carteiras acompanhadas), veredito e nota de cada caller."""
        return hub.calls_view()

    @app.get("/api/pump/robot-log/dias")
    async def robot_days(modulo: str, pf=Depends(admin_engine)):
        """0.31.91: aprendizado dos logs — um resumo por dia de cada robô, sem prazo (nada é apagado)."""
        if modulo != "explorar" and modulo not in hub.RLOG_NAMES:
            return {"error": "robô inválido"}
        return await hub.robot_days(pf, modulo)

    @app.get("/api/pump/robot-log")
    async def robot_log(modulo: str, horas: float = 24, pf=Depends(admin_engine)):
        """0.31.89: log de análise de um robô (copia, base, elite) desta conta, em blocos de 5 min."""
        if modulo not in hub.RLOG_NAMES:
            return {"error": "robô inválido"}
        return await hub.robot_log(pf, modulo, max(1.0, min(float(horas), 24 * 90)))

    @app.get("/api/pump/explore/log")
    async def explore_log(horas: float = 24, pf=Depends(admin_engine)):
        """0.31.88: log de análise do Explorar (cada lista de 5 min: o que analisou, o que entrou e por que não)."""
        return await hub.explore_log(pf, max(1.0, min(float(horas), 24 * 90)))

    @app.get("/api/pump/raiox/{mint}")
    async def raiox(mint: str, novo: int = 0, pf=Depends(admin_engine)):
        """0.31.86: Raio-X das primeiras 500 negociações do token (1 crédito da Solana Tracker; guardado por 6 h)."""
        if not pf.valid_addr(mint):
            return {"error": "endereço inválido"}
        return await hub.xray(pf, mint, force=bool(novo))

    @app.get("/api/pump/base/evolucoes")
    async def evo_list(pf=Depends(admin_engine)):
        """0.31.85: evoluções do cérebro (E1, E2…) com o resultado de cada uma e se a conta está congelada numa delas."""
        return await hub.evo_list(pf)

    @app.get("/api/pump/base/evolucoes/comparar")
    async def evo_compare(a: int, b: int, pf=Depends(admin_engine)):
        from .evolucoes import comparar
        ra, rb = await hub.evo_report(pf, a), await hub.evo_report(pf, b)
        if ra.get("error") or rb.get("error"):
            return {"error": ra.get("error") or rb.get("error")}
        return {"a": ra, "b": rb, "linhas": comparar(ra, rb)}

    @app.get("/api/pump/base/evolucoes/{numero}")
    async def evo_report(numero: int, pf=Depends(admin_engine)):
        return await hub.evo_report(pf, numero)

    @app.post("/api/pump/base/evolucoes/{numero}/voltar")
    async def evo_rollback(numero: int, pf=Depends(admin_engine)):
        return await hub.evo_rollback(pf, numero)

    @app.post("/api/pump/base/automatico")
    async def evo_auto(pf=Depends(admin_engine)):
        return await hub.evo_auto(pf)

    @app.get("/api/pump/base-geral")
    async def base_geral(pf=Depends(admin_engine)):
        """0.31.71: o cérebro do robô — maturidade, o que aprendeu, o que está por vir, gráfico e log."""
        st = hub.base_state(pf)
        try:
            st["fotos"] = list(reversed(await hub.db.select("base_snapshots", None, order="em.desc", limit=400)))
            st["log"] = await hub.db.select("base_log", None, order="em.desc", limit=150)
        except Exception:
            st["fotos"], st["log"] = [], []
        try:
            st["ajustes"] = await hub.db.select("auto_tune_log", None, order="em.desc", limit=40)
            for r in st["ajustes"]:
                r["nome"] = await hub._nome(r.pop("user_id", "") or "")
        except Exception:
            st["ajustes"] = []
        return st

    @app.post("/api/pump/traders/share")
    async def traders_share(body: dict, u: dict = Depends(user)):
        """0.31.74: compartilhar a lista de traders adicionados à mão (convite; a pessoa aceita ou não)."""
        pf = await hub.engine(u["id"])
        return await hub.traders_offer(pf, u, str((body or {}).get("to") or ""))

    @app.get("/api/pump/follow-user")
    async def follow_get(pf=Depends(admin_engine)):
        """0.31.61: de quem esta conta copia os trades (e quem copia os dela)."""
        tgt = getattr(pf, "follow_user", "")
        followers = [await hub._nome(u) for u, e in hub.engines.items() if getattr(e, "follow_user", "") == pf.user_id]
        return {"follow_user": tgt, "nome": (await hub._nome(tgt)) if tgt else "", "seguidores": followers}

    @app.post("/api/pump/follow-user")
    async def follow_post(body: dict, pf=Depends(admin_engine)):
        return await hub.follow_set(pf, str((body or {}).get("user_id") or ""))

    @app.get("/api/pump/versions")
    async def pump_versions(real: int = 0, pf=Depends(admin_engine)):
        """Resultado por versão (0.31.50): quanto ganhou/perdeu em cada versão e se ajudou ou piorou."""
        from .versions_report import build, load
        return build(pf.trades(100000), load(), real=bool(real))

    @app.get("/api/pump/versions/ai")
    async def pump_versions_ai(real: int = 0, pf=Depends(admin_engine)):
        from .versions_report import ai_text, build, load
        return PlainTextResponse(ai_text(build(pf.trades(100000), load(), real=bool(real)), VERSION),
                                 headers={"Content-Disposition": 'attachment; filename="resultado-por-versao-para-ia.md"'})

    @app.get("/api/pump/false-gains")
    async def false_gains(check: int = 1, pf=Depends(admin_engine)):
        """0.32.1: revisão dos ganhos de +1.900% ou mais de todas as contas (só leitura; nada é alterado)."""
        return await hub.false_gains(pf, check=bool(check))

    @app.get("/api/pump/false-gains/ai")
    async def false_gains_ai(pf=Depends(admin_engine)):
        from .ganhos_falsos import ai_text
        rep = getattr(hub, "_false_last", None) or await hub.false_gains(pf, check=False)
        return PlainTextResponse(ai_text(rep), headers={"Content-Disposition": 'attachment; filename="revisao-ganhos-falsos.md"'})

    @app.get("/api/pump/compare/{offer_id}/ai")
    async def compare_ai(offer_id: int, u: dict = Depends(admin_only)):
        from .compare import ai_text
        r = await hub.compare_one(u["id"], offer_id)
        return r if r.get("error") else {"texto": ai_text(r, r.get("parte") or "")}

    @app.post("/api/pump/compare/{offer_id}/save")
    async def compare_save(offer_id: int, u: dict = Depends(admin_only)):
        try:
            return await hub.compare_save(u["id"], offer_id)
        except Exception as e:
            log.warning("salvar comparação: %s", str(e)[:120])
            return {"error": "não consegui salvar agora"}

    @app.post("/api/admin/users/{uid}/copy-config")
    async def admin_copy_config(uid: str, u: dict = Depends(admin_only)):
        if not UUID.match(uid):
            return {"error": "usuário inválido"}
        pf = await hub.engine(u["id"])
        return await hub.admin_copy_config(pf, uid)

    @app.get("/api/admin/users/{uid}/trades")
    async def admin_user_trades(uid: str, u: dict = Depends(admin_only)):
        """0.31.33: trades fechados da carteira fictícia de um usuário (ganhos, perdas ou todos), para o Admin."""
        if not UUID.match(uid):
            return {"error": "usuário inválido"}
        rows = await hub.db.select("profiles", {"user_id": uid}, columns="user_id")
        if not rows:
            return {"error": "usuário não encontrado"}
        pf = await hub.engine(uid)
        out = [{"aberto": t.get("opened_at"), "fechado": t.get("closed_at"), "token": t.get("symbol"), "mint": t.get("mint"),
                "origem": t.get("origem") or ("manual" if t.get("wallet") == "manual" else "cópia"), "wallet": t.get("wallet"),
                "sol_in": t.get("sol_in"), "pnl_sol": t.get("pnl_sol"), "pnl_pct": t.get("pnl_pct"), "melhor_pct": t.get("best_pct"),
                "hold_s": t.get("hold_s"), "motivo": t.get("reason")} for t in pf.trades(2000) if not t.get("real")]
        return {"trades": out}

    @app.get("/api/admin/audit")
    async def admin_audit(user_id: str = "", limit: int = 200, u: dict = Depends(admin_only)):
        """Registro de segurança de todas as contas (o detalhe nunca contém chaves)."""
        if user_id and not UUID.match(user_id):
            return []
        limit = max(1, min(limit, 1000))
        rows = await hub.db.select("audit_log", {"user_id": user_id} if user_id else None, order="at.desc", limit=limit)
        emails = {p["user_id"]: p.get("email") for p in await hub.db.select("profiles", None, columns="user_id,email")}
        nm = await _names(rows)
        return [{"at": r.get("at"), "user_id": r.get("user_id"), "email": emails.get(r.get("user_id")),
                 "acao": r.get("acao"), "detalhe": nm(r.get("detalhe"))} for r in rows]

    NOVIDADES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "novidades.json")

    @app.get("/api/admin/novidades")
    async def admin_novidades(u: dict = Depends(admin_only)):
        """Histórico do que foi implementado (versão, onde fica, o que faz). Só admin, pedido do dono em 2026-10-25."""
        import json as _json
        with open(NOVIDADES, encoding="utf-8") as f:
            itens = _json.load(f)["itens"]
        # 0.31.57 (pedido do dono): hora, minuto e segundo em que cada versão entrou, de app/versoes.json (commit; o deploy
        # entra uns minutos depois)
        from .versions_report import load as vload
        when = {v["versao"]: v.get("inicio") for v in vload()}
        for x in itens:
            x["inicio"] = when.get(x.get("versao"))
        return {"itens": itens}

    @app.get("/api/admin/api-usage")
    async def admin_api_usage(u: dict = Depends(admin_only)):
        """0.31.76: uso de cada API externa no mês e por minuto, em % do limite grátis."""
        return {"apis": hub.api_usage_view()}

    @app.get("/api/admin/logs")
    async def admin_logs(after: int = 0, level: str = "INFO", q: str = "", limit: int = 400,
                         u: dict = Depends(admin_only)):
        """Logs do servidor em tempo real (sem precisar do Portainer). Segredos já vêm mascarados."""
        from .logsafe import ring
        h = ring()
        return {"logs": h.since(after, level, q, max(1, min(limit, 2000))), **h.counts()}

    @app.exception_handler(AccountBlocked)
    async def blocked_err(request: Request, exc: AccountBlocked):
        return JSONResponse({"error": "conta bloqueada pelo administrador", "detail": "conta bloqueada pelo administrador"},
                            status_code=403)

    # ------------------------------------------------------------------ páginas
    @app.exception_handler(HTTPException)
    async def http_err(request: Request, exc: HTTPException):
        return JSONResponse({"error": exc.detail, "detail": exc.detail}, status_code=exc.status_code)

    # cada versão nova muda o endereço dos arquivos (?v=…): depois do redeploy o navegador não usa os antigos
    VTAG = hashlib.sha256(VERSION.encode()).hexdigest()[:10]
    PAGES = {n: open(os.path.join(WEB, n), encoding="utf-8").read().replace("__V__", VTAG)
             .replace("__BASE__", (cfg.public_base_url or "").rstrip("/"))
             for n in ("index.html", "app.html")}

    @app.get("/")
    def landing():
        return HTMLResponse(PAGES["index.html"])

    @app.get("/app")
    def panel():
        return HTMLResponse(PAGES["app.html"])

    app.mount("/static", StaticFiles(directory=WEB), name="static")
    return app
