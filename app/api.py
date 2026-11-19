"""Rotas HTTP. Tudo em /api/* exige login (token do Supabase); o usuário vem SEMPRE do token.

Regras de segurança:
- Nenhuma rota devolve chave: só "configurada: sim/não" (e o endereço PÚBLICO da carteira).
- Ligar a execução real pede confirmação e fica no audit_log; volta a desligar quando o servidor reinicia.
- Salvar/remover chave, vender manual e trocar USDC→SOL também vão para o audit_log.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time

from fastapi import Depends, FastAPI, HTTPException, Request
import hashlib

from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
import mimetypes
mimetypes.add_type("image/webp", ".webp")   # 0.32.357: a imagem do Python não conhece .webp (a arte da SALA LIVE vinha como octet-stream)

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
        # 0.32.326 (revisão de segurança de 12/11): o site só funciona em HTTPS (Cloudflare na frente); o navegador passa a recusar
        # http por 1 ano. Sem includeSubDomains: outros projetos do dono usam outros endereços de rachar.app.br.
        resp.headers["Strict-Transport-Security"] = "max-age=31536000"
        resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
        # 0.32.326: em toda página só o caminho exato do login (supabase-js 2.118.0, com SRI). Antes só o /dormant era assim;
        # /hood e /bnb também recebem chave privada, e o jsDelivr inteiro deixaria um script injetado baixar qualquer pacote de lá.
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.118.0/; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; "
            f"img-src 'self' data: https:; connect-src 'self' {sb} {sb.replace('https://', 'wss://')}; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
            # 0.32.234: só a página do Dormant mostra o gráfico da DEX (GeckoTerminal e DexScreener) dentro da janela da moeda
            + ("; frame-src https://www.geckoterminal.com https://dexscreener.com" if request.url.path == "/dormant" else ""))
        if request.url.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        elif request.url.path in ("/", "/app", "/entrar", "/bnb", "/hood", "/forex", "/dormant", "/sala", "/botlive", "/botlive/sala") or request.url.path.startswith("/static/"):
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
        return {"ok": True, "version": VERSION, "no_ar_desde": STARTED_AT, "subida": hub.boot_status()}

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
        # 0.32.3 (sugestão do Bruxo): os contadores do monitor recomeçam a cada reinício; o painel mostra desde quando
        # e o estado de cada API (ok / com erro) embaixo do menu
        snap["uptime_s"] = round(time.time() - hub.started_at)
        jst = (hub.market.jup.status if getattr(hub.market, "jup", None) else None) or {}
        snap["apis"] = {"jupiter": {"ok": jst.get("on"), "error": jst.get("error")},
                        "solana_tracker": {"ok": bool(pf.lb_key()) and not (pf.lb_status or {}).get("error"),
                                           "error": (pf.lb_status or {}).get("error"), "at": (pf.lb_status or {}).get("at"),
                                           # 0.32.62 (dono: "tenho crédito ainda"): qual chave esta conta usa — nunca a chave em si
                                           "fonte": pf.lb_key_src()},
                        "solana_tracker_cota": None,
                        # 0.32.235: estourou o limite grátis / RPC recusando / nenhuma leitura vira trade
                        "rpc": (al := hub.health_alerts())["rpc"],
                        "banco": {"ok": not getattr(pf.store, "last_error", None),
                                  "error": (str(getattr(pf.store, "last_error", "") or "")[:120]) or None,
                                  "fila": len(getattr(pf.store, "_q", []) or [])}}
        snap["apis"]["solana_tracker_cota"] = al["solana_tracker"]
        if al["solana_tracker"].get("estourou"):
            snap["apis"]["solana_tracker"]["ok"] = False
        return snap

    AUTO_SWITCHES = {"pump_sim_on", "pump_tab_gate_on", "pump_bar_auto_on", "pump_bar_real", "pump_bx_on", "pump_bx_real", "pump_ex_auto_on", "pump_calls_auto_on",
                     "pump_el_auto_on", "pump_auto_on", "pump_st_auto_copy", "pump_eq_on", "pump_guard_on", "pump_nc_on",
                     "pump_lanc_on", "pump_jt_real", "pump_calls_real", "pump_el_real", "pump_auto_real", "pump_st_real", "pump_eq_real",
                     "pump_ex_real_on", "pump_radar_enabled", "pump_top_on", "pump_st_copy_on", "pump_jt_wallet", "pump_el_copy80",
                     "pump_st_lucro_on", "pump_st_lucro_real", "pump_real_full_mirror", "pump_bm_on", "pump_bm_real"}

    @app.post("/api/pump/settings")
    async def pump_settings(body: dict, request: Request, pf=Depends(engine), u: dict = Depends(user)):
        if u["role"] != "admin" and any(key.startswith(("pump_ex_auto_", "pump_ar_")) for key in body):
            raise HTTPException(403, "só o admin pode configurar as novas entradas automáticas")
        radar_keys = ("pump_radar_enabled", "pump_radar_min_wallets", "pump_radar_window_min")
        radar_before = {key: getattr(pf.cfg, key) for key in radar_keys}
        body = dict(body or {})
        why = str(body.pop("_why", "") or "").strip()[:120]   # 0.32.221: de onde veio a troca (aparece no Histórico de config)
        applied, errors = pf.cfg.apply(body)
        if applied:
            # 0.32.56: a pessoa mudou na tela — um ajuste antigo pedido no chat não volta a mexer nessas opções
            from datetime import datetime, timezone
            ov = pf.__dict__.setdefault("_ov_user", {})
            for key in applied:
                ov[key] = datetime.now(timezone.utc).isoformat()
            pf._cfg_why = ("você " + why) if why else "você mudou na tela"
            await hub.save_settings(pf)
            if "pump_st_lucro_on" in applied:                # 0.32.211: a lista das que deram lucro sai na hora
                import asyncio as _aio
                _aio.get_running_loop().create_task(hub.study_lucro_sync(pf))
            # 0.32.58 (barrados voltavam a comprar depois de desligados): quem liga/desliga uma compra automática fica registrado,
            # com o navegador que mandou, para achar uma aba antiga do painel que grava a opção por cima
            for key in sorted(set(applied) & AUTO_SWITCHES):
                await audit(hub.db, pf.user_id, "compra automática mudada na tela",
                            f"{key} → {'ligada' if applied[key] else 'desligada'} · {str(request.headers.get('user-agent') or '')[:80]}")
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
        if on and not pf.cfg.pump_real_enabled:
            pf.real_on_at = time.time()               # 0.32.103: o cartão da Visão geral mostra desde quando
        pf.cfg.pump_real_enabled = on
        await hub.save_settings(pf)                   # 0.31.28: fica ligado até o usuário desligar (sobrevive ao reinício)
        await audit(hub.db, u["id"], "ligar execução real" if on else "desligar execução real",
                    f"máx. {pf.cfg.pump_real_max_sol} SOL por compra" if on else "")
        pf._emit(f"[PUMP REAL] execução real {'LIGADA' if on else 'DESLIGADA'} por você")
        return {"ok": True, "enabled": on}

    @app.get("/api/pump/real/lugares")
    async def pump_real_places(u: dict = Depends(user)):
        """0.32.103: onde a chave geral da execução real vale (a janela que abre ao desligar)."""
        return hub.real_places(await hub.engine(u["id"]))

    @app.get("/api/pump/top-lab")
    async def top_lab(pf=Depends(admin_engine)):
        """0.32.124: Laboratório do Top traders. Só mede."""
        return hub.top_lab(pf)

    @app.get("/api/pump/stop-ganho")
    async def stop_ganho(pf=Depends(engine)):
        """0.32.332 (pedido do dono): stop de ganho autônomo. O admin vê a conta de cada aba (tabela por nível e onde a entrada perde);
        a conta comum vê o nível que vale para cada aba dela (as somas são das operações de todas as contas)."""
        if getattr(pf, "role", "user") == "admin":
            return hub.sg_detail(pf)
        return pf.sg_view(detalhe=False)

    @app.get("/api/pump/traders-aba")
    async def traders_aba(aba: str, real: int = 0, pf=Depends(engine)):
        """0.32.140: traders de uma aba, em todo o tempo e nas últimas 24 h. Só os trades desta conta."""
        return hub.tr_tabela(pf, aba[:60], bool(real))

    @app.post("/api/pump/trader-report")
    async def trader_report(body: dict, pf=Depends(admin_engine)):
        aba = str((body or {}).get("aba") or "")
        if aba not in {*pf.ABA_ORIGEM.values(), "Top traders", "Copiar igual", "Carteiras em estudo", "Maiores traders (80%+)"}:
            raise HTTPException(400, "aba inválida")
        return await hub.tr_save(pf, aba, bool((body or {}).get("real")))

    @app.get("/api/pump/trader-report/base")
    async def trader_report_base(real: int = 0, pf=Depends(admin_engine)):
        return await hub.tr_base(bool(real))

    @app.get("/api/pump/trader-report/item")
    async def trader_report_item(id: str, pf=Depends(admin_engine)):
        R = await hub.tr_item(id)
        if R is None:
            raise HTTPException(404, "relatório não encontrado")
        return R

    @app.get("/api/pump/result-tabs")
    async def result_tabs(real: int = 0, pf=Depends(engine)):
        """0.32.123: resultado por aba da janela Resultado. Só os trades desta conta."""
        from . import weekparts
        L = [t for t in pf.trades(100000) if bool(t.get("real")) == bool(real)]
        return {"abas": pf.tabs(L, pf.aba_of), "semanas": weekparts.por_aba(L, pf.aba_of)}   # 0.32.161: fim de semana × dias de semana

    @app.get("/api/pump/trader-hist")
    async def trader_hist(real: int = 0, pf=Depends(engine)):
        """0.32.163 (pedido do dono): todos os traders que esta conta copiou, com o resultado de cada um. Os que só existem no
        guardado (ex.: depois de zerar a fictícia) vêm em `guardados`. O user_id vem só do token."""
        from . import traderhist
        L = [t for t in pf.trades(100000) if bool(t.get("real")) == bool(real)]
        rows = traderhist.resumo(L, pf.aba_of, hub.tr_names(), traderhist.lb_map(getattr(pf, "leaderboard", None)))
        live = {r["wallet"] for r in rows}
        guardados = [g for g in await hub.th_saved(pf, bool(real)) if g.get("wallet") not in live]
        # 0.32.251: se copia AGORA é calculado a cada pedido; `agora` nunca entra no que `hub.th_save` guarda
        return {"traders": [{**r, "agora": pf.copy_now(r["wallet"], bool(real))} for r in rows],
                "guardados": [{**g, "agora": pf.copy_now(g.get("wallet"), bool(real))} for g in guardados]}

    @app.get("/api/pump/trader-hist/w/{wallet}")
    async def trader_hist_one(wallet: str, pf=Depends(engine)):
        """0.32.163: tudo o que esta conta copiou de uma carteira, na fictícia e na real, com cada trade e as abertas agora."""
        from . import traderhist
        if not pf.valid_addr(wallet):
            raise HTTPException(400, "carteira inválida")
        r = traderhist.detalhe(pf.trades(100000), wallet, pf.aba_of, hub.tr_names(), traderhist.lb_map(getattr(pf, "leaderboard", None)),
                               pf.positions())
        saved = {g.get("wallet"): g for g in await hub.th_saved(pf, False) + await hub.th_saved(pf, True) if g.get("wallet") == wallet}
        g = saved.get(wallet) or {}
        r["ranking_dias"] = g.get("ranking_dias") or {}
        if not r.get("ranking"):
            r["ranking"] = g.get("ranking")
        r["agora"] = {"ficticia": pf.copy_now(wallet, False), "real": pf.copy_now(wallet, True)}
        return r

    @app.get("/api/pump/real/why")
    async def real_why(horas: float = 6, pf=Depends(engine)):
        """0.32.162 (pedido do dono): o que impede a REAL de comprar agora e por que ela ficou de fora nas últimas horas."""
        r = pf.real_why(min(max(float(horas), 1.0), 48.0))
        if not hub.real_allowed:
            r["agora"].insert(0, "a trava geral do servidor (PUMP_REAL_ALLOWED) está fechada")
            r["pode_comprar"] = False
        return r

    @app.get("/api/pump/weekparts")
    async def weekparts_view(real: int = 0, pf=Depends(engine)):
        """0.32.161 (pedido do dono): dias de semana × fins de semana desta conta — blocos ao vivo, resumo, por aba e por trader,
        e os blocos já guardados. O user_id vem só do token (ou da visualização do admin)."""
        from . import weekparts
        L = [t for t in pf.trades(100000) if bool(t.get("real")) == bool(real)]
        names = hub.tr_names()
        return {"blocos": weekparts.blocos(L, pf.aba_of, names), "resumo": weekparts.resumo(L, pf.aba_of, names),
                "guardados": await hub.week_saved(pf, bool(real))}

    @app.get("/api/pump/result-study")
    async def result_study(horas: float = 24, real: int = 0, pf=Depends(engine)):
        """0.32.114: de onde veio o resultado do período. O user_id vem só do token (ou da visualização do admin)."""
        h = horas if horas in (1, 6, 12, 24) else 24
        return {"estudo": hub.rs_study(pf, h, bool(real)), "guardados": await hub.rs_saved(pf, bool(real))}

    @app.post("/api/pump/result-study")
    async def result_study_save(body: dict, pf=Depends(engine)):
        h = body.get("horas") if body.get("horas") in (1, 6, 12, 24) else 24
        await hub.rs_save(pf, h, bool(body.get("real")))
        return {"ok": True}

    @app.get("/api/pump/result-study/marcas")
    async def result_study_marks(real: int = 0, pf=Depends(engine)):
        return await hub.rs_marks(pf, bool(real))

    @app.get("/api/pump/result-study/base")
    async def result_study_base(real: int = 0, pf=Depends(admin_engine)):
        return {"estudos": await hub.rs_base(bool(real))}

    @app.get("/api/pump/result-study/item")
    async def result_study_item(id: str, pf=Depends(admin_engine)):
        E = await hub.rs_item(id)
        if E is None:
            raise HTTPException(404, "estudo não encontrado")
        return E

    @app.get("/api/pump/result-study/learn")
    async def result_study_learn(real: int = 0, pf=Depends(admin_engine)):
        return hub.rs_learn(bool(real))

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
        # 0.32.238: a lista só é buscada enquanto alguém usa o Explorar; ao abrir a tela parada, busca na hora
        parada = time.time() - float(getattr(hub, "explore_seen", 0) or 0) > 1800
        hub.explore_seen = time.time()
        if parada and hub.monitor is not None and time.time() - float(getattr(hub.explore, "at", 0) or 0) > 300:
            asyncio.get_running_loop().create_task(hub.monitor.explore_once())
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
        from . import realgap
        A = pf.mirror_pairs(2000)
        L, miss = A[:100], pf.mirror_misses()
        dif = [x["dif_pct"] for x in L if x["dif_pct"] is not None]
        return {"pairs": L, "media_dif_pct": round(sum(dif) / len(dif), 2) if dif else None,
                "real_sol": round(sum(x["real_sol"] or 0 for x in L), 6), "sim_pct_medio": None,
                "resumo": realgap.summary(A, [t for t in pf.trades(5000) if t.get("real")], int(miss.get("total") or 0)),
                "misses": miss, "real_on": bool(getattr(pf.cfg, "pump_real_enabled", False)),
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
        if getattr(pf.cfg, "pump_guard_on", False) and hub.monitor is not None:
            try:                                                   # 0.32.53: a trava quer preço e detentores lidos agora
                if pf.graduated(mint) or (pf.tokens.get(mint) or {}).get("main_dex") not in (None, "pumpfun"):
                    await hub.monitor.svc._fetch_prices([mint])
                await asyncio.wait_for(hub.monitor.svc.holders_check(mint), timeout=3)
            except Exception:
                pass
        target = str(body.get("target") or "both")
        if target not in ("sim", "real", "both"):
            return {"error": "carteira inválida"}
        orig = str(body.get("origem") or "")
        orig = orig if orig in ("barrado_btn", "lancamento") else ""   # 0.32.78: Comprar do Lançamento sem trader         # 0.32.29: rótulo "barrado que subiu (você comprou)"
        r = pf.manual_buy(mint, target=target, origem=orig)  # 0.32.21: Comprar na fictícia, na real ou nas duas
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
                        "summary": summary(p) if not p.get("error") else {}, "facts": hub.wallet_facts(r["wallet"])})
        # ranking de copiabilidade: quem renderia mais para VOCÊ copiando nos últimos 30 dias (0.15.0)
        ranked = sorted([x for x in out if (x["summary"].get("copy") or {}).get("n_30d")],
                        key=lambda x: -(x["summary"]["copy"]["pnl_30d"] or 0))
        return {"wallets": out, "ranking": [{"wallet": x["wallet"], "apelido": x["apelido"], "followed": x["followed"],
                                             **x["summary"]["copy"]} for x in ranked],
                "limit": MAX_WALLETS, "key": bool(hub._study_key()), "params": prm,
                "mine": study_my_results(pf, out), "auto": await study_auto_info(pf, {x["wallet"]: x for x in out}, prm),
                "lucro": {"on": bool(getattr(pf.cfg, "pump_st_lucro_on", False)), "copiando": pf.study_lucro_wallets(),
                          "min_tokens": hub.LUCRO_MIN_TOKENS}}

    async def _log_rows(rows: list, known: dict, prm: dict | None) -> list:
        """0.32.10: cada decisão da IA leva o resumo da carteira (tokens que acertou/errou, pump.fun, última operação)."""
        from .study import summary
        extra, out = {}, []
        for r in rows:
            w = r.get("wallet")
            if w and w not in known and w not in extra and len(extra) < 15:
                p = await hub.study_profile(w, prm)
                extra[w] = {"summary": summary(p) if not p.get("error") else {}}
        for r in rows:
            w = r.get("wallet") or ""
            k = known.get(w) or extra.get(w) or {}
            out.append({**{x: r.get(x) for x in ("wallet", "acao", "motivo", "em")},
                        "facts": hub.wallet_facts(w) if w else {}, "digest": (k.get("summary") or {}).get("digest"),
                        "features": [v for v in ((r.get("info") or {}).get("features") or {}).values() if v],
                        "no_estudo": w in known})
        return out

    async def study_auto_info(pf, known: dict | None = None, prm: dict | None = None) -> dict:
        from datetime import datetime, timezone
        from .autostudy import AUTO_TAG, rates
        try:
            log_rows = await hub.db.select("study_auto_log", {"user_id": pf.user_id}, order="em.desc", limit=1000)
        except Exception:
            log_rows = []
        last = hub._study_auto_at.get(pf.user_id)
        return {"on": bool(getattr(pf.cfg, "pump_st_auto_on", True)), "max": int(getattr(pf.cfg, "pump_st_auto_max", 15)),
                "tag": AUTO_TAG, "last_run": datetime.fromtimestamp(last, timezone.utc).isoformat() if last else None,
                "log": await _log_rows(log_rows[:60], known or {}, prm),
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
        try:
            sugestoes = await hub.tune_suggest(pf)
        except Exception as e:
            log.warning("sugestões do ajuste: %s", str(e)[:120])
            sugestoes = []
        return {"sugestoes": sugestoes, "on": bool(getattr(pf.cfg, "pump_tune_on", True)), "real_on": bool(getattr(pf.cfg, "pump_real_enabled", False)),
                "last_run": datetime.fromtimestamp(last, timezone.utc).isoformat() if last else None,
                "testing": {"nome": (sai.get("detalhe") or {}).get("nome"), "desde": sai.get("em")} if sai and sai.get("acao") == "aplicou" else None,
                "rules": {"min_trades": MIN_TRADES, "min_days": MIN_DAYS, "eval_h": EVAL_S // 3600, "eval_trades": EVAL_TRADES},
                "log": [{k: r.get(k) for k in ("tipo", "acao", "motivo", "em")} for r in rows[:60]]}

    @app.post("/api/pump/tune/apply")
    async def tune_apply(body: dict, pf=Depends(admin_engine)):
        """0.32.118: a pessoa aplica uma sugestão do ajuste. Só o id vem do navegador; os valores são recalculados no servidor."""
        r = await hub.tune_apply(pf, str((body or {}).get("id") or ""))
        if r.get("ok"):
            await audit(hub.db, pf.user_id, "ajuste automático: sugestão aplicada", str(r.get("nome"))[:120])
        return r

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
                # 0.32.17 (pedido do dono): a real também aparece para quem está sendo copiado, dizendo se ela copia
                if not T and not P and not x.get("followed"):
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
                             "diag": diag if not real else None,
                             "real_state": None if not real else ("só fictícia (teste)" if pf.sim_only(w) else
                                                                 "copia na real" if getattr(pf.cfg, "pump_real_enabled", False)
                                                                 else "execução real desligada")})
        rows.sort(key=lambda r: -r["pnl_sol"])
        return {"rows": rows, "total": {k: {"trades": v[0], "win_rate": v[1] / v[0] if v[0] else None,
                                            "pnl_sol": round(v[2], 6), "roi_pct": round(v[2] / v[3] * 100, 2) if v[3] else None}
                                        for k, v in tot.items()}}

    @app.post("/api/pump/study/copy")
    async def study_copy(body: dict, pf=Depends(admin_engine)):
        """0.32.17 (pedido do dono): o botão Copiar das Carteiras em estudo copia SÓ na fictícia (teste); a real fica de fora."""
        w, on = str((body or {}).get("wallet") or "").strip(), (body or {}).get("on", True)
        target = str((body or {}).get("target") or "sim")           # 0.32.38: "sim" = só fictícia; "both" = fictícia e REAL
        if not pf.valid_addr(w):
            return {"error": "endereço de carteira inválido"}
        if on:
            if target == "both":
                pf.real_ok_list = list(dict.fromkeys(list(pf.real_ok_list or []) + [w]))
                pf.sim_only_list = [x for x in (pf.sim_only_list or []) if x != w]
            else:
                pf.sim_only_list = list(dict.fromkeys(list(pf.sim_only_list or []) + [w]))
                pf.real_ok_list = [x for x in (pf.real_ok_list or []) if x != w]
            if w not in (pf.manual or []):
                pf.add_manual(w)
        else:
            pf.sim_only_list = [x for x in (pf.sim_only_list or []) if x != w]
            pf.real_ok_list = [x for x in (pf.real_ok_list or []) if x != w]
            if w in (pf.manual or []):
                pf.remove_manual(w)
        await hub.save_settings(pf)
        pf.refresh_followed(force=True)
        await audit(hub.db, pf.user_id, ("estudo: copiar na fictícia e REAL" if target == "both" else "estudo: copiar só na fictícia") if on else "estudo: parou de copiar", w)
        return {"ok": True, "sim_only": pf.sim_only(w)}

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

    @app.post("/api/pump/config/peer")
    async def config_peer(body: dict, u: dict = Depends(admin_only)):
        """0.32.151: opções de outro usuário para comparar na janela Ajustes de Abas de trades (só leitura)."""
        try:
            return await hub.config_peer(u["id"], str(body.get("user") or ""), [str(k) for k in (body.get("keys") or [])][:1000])
        except Exception as e:
            log.warning("comparar configuração: %s", str(e)[:120])
            return {"error": "não consegui ler a configuração agora"}

    @app.get("/api/pump/buy-diff")
    async def buy_diff(peer: str = "", horas: float = 24, u: dict = Depends(admin_only)):
        """0.32.167: por que duas contas compraram moedas diferentes (só leitura)."""
        if not UUID_ANY.fullmatch(peer or ""):
            return {"error": "escolha um usuário"}
        try:
            return await hub.buy_diff(u["id"], peer, max(1.0, min(168.0, float(horas))))
        except Exception as e:
            log.warning("comparar compras: %s", str(e)[:120])
            return {"error": "não consegui comparar agora"}

    @app.get("/api/pump/config/offers")
    async def config_offers(u: dict = Depends(user)):
        try:
            return {"offers": await hub.config_offers(u["id"])}
        except Exception:
            return {"offers": []}

    @app.get("/api/pump/config/users")
    async def config_users(u: dict = Depends(user)):
        return {"users": await hub.config_users(u["id"])}

    # 0.32.199 (pedido do dono): histórico da configuração, com Voltar para uma versão
    @app.get("/api/pump/config/historico")
    async def cfg_hist(pf=Depends(engine)):
        return await hub.cfg_hist_list(pf)

    @app.get("/api/pump/config/historico/diff")
    async def cfg_hist_diff(n: int | None = None, offer: int | None = None, pf=Depends(engine)):
        return await hub.cfg_hist_diff(pf, n, offer)

    @app.post("/api/pump/config/real-da-ficticia")
    async def cfg_real_from_sim(u: dict = Depends(user)):
        pf = await hub.engine(u["id"])
        hub.check_active(u["id"], pf)
        return await hub.real_from_sim(pf)

    @app.post("/api/pump/config/real-da-ficticia/desfazer")
    async def cfg_real_from_sim_undo(body: dict, u: dict = Depends(user)):
        n = (body or {}).get("n")
        if not isinstance(n, int):
            return {"error": "versão inválida"}
        pf = await hub.engine(u["id"])
        hub.check_active(u["id"], pf)
        return await hub.real_from_sim_undo(pf, n)

    @app.post("/api/pump/config/historico/voltar")
    async def cfg_hist_back(body: dict, u: dict = Depends(user)):
        pf = await hub.engine(u["id"])
        n, offer = (body or {}).get("n"), (body or {}).get("offer")
        if not isinstance(n, int) and not isinstance(offer, int):
            return {"error": "versão inválida"}
        keys = (body or {}).get("keys")                 # 0.32.200: só as abas marcadas; sem keys volta tudo
        if keys is not None and not (isinstance(keys, list) and len(keys) <= 1000 and all(isinstance(k, str) for k in keys)):
            return {"error": "opções inválidas"}
        return await hub.cfg_hist_back(pf, n if isinstance(n, int) else None, offer if isinstance(offer, int) else None, set(keys) if keys is not None else None)

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

    @app.get("/api/pump/study/ai")
    async def study_ai(wallet: str = "", pf=Depends(admin_engine)):
        """0.32.47 (pedido do dono): relatório da carteira (ou de todas as do estudo) + prompt para o ChatGPT fazer a varredura
        das transações; a análise volta para o Claude. 0.32.48: cada relatório gerado fica no histórico."""
        mine = list(getattr(pf, "study", []) or [])
        if wallet and (not pf.valid_addr(wallet) or wallet not in mine):
            return {"error": "carteira não está no seu estudo"}
        row = await hub.study_ai_create(pf, [wallet] if wallet else mine)
        if row.get("error"):
            return row
        return {"id": row["id"], "text": row["texto"], "carteiras": len(row["carteiras"]), "status": row["status"]}

    @app.get("/api/pump/study/ai/reports")
    async def study_ai_list(pf=Depends(admin_engine)):
        """0.32.48: histórico dos relatórios para o ChatGPT, com o estado de cada um e as carteiras novas que ainda não entraram."""
        from .study_ai import AUTO_MIN, STATUS, pending_wallets
        reps = await hub.study_ai_reports(pf)
        out = []
        for r in reps:
            st = "analisado" if hub.study_ai_analysis(r["id"]) else r.get("status") or "gerado"
            out.append({"id": r["id"], "em": r.get("em"), "carteiras": r.get("carteiras") or [], "auto": bool(r.get("auto")),
                        "status": st, "status_txt": STATUS.get(st, st), "copiado_em": r.get("copiado_em"),
                        "resposta_em": r.get("resposta_em"), "tem_resposta": bool(r.get("resposta"))})
        pend = pending_wallets(list(getattr(pf, "study", []) or []), reps)
        return {"items": out, "novas": pend, "auto_min": AUTO_MIN}

    @app.post("/api/pump/study/ai/reports/novas")
    async def study_ai_new(pf=Depends(admin_engine)):
        """Gera agora o relatório só com as carteiras do estudo que ainda não entraram em nenhum."""
        from .study_ai import pending_wallets
        pend = pending_wallets(list(getattr(pf, "study", []) or []), await hub.study_ai_reports(pf))
        if not pend:
            return {"error": "nenhuma carteira nova sem relatório"}
        row = await hub.study_ai_create(pf, pend)
        return row if row.get("error") else {"id": row["id"]}

    @app.get("/api/pump/study/ai/reports/{rid}")
    async def study_ai_one(rid: str, pf=Depends(admin_engine)):
        from .study_ai import STATUS
        rows = [r for r in await hub.study_ai_reports(pf) if r["id"] == rid]
        if not rows:
            return {"error": "relatório não encontrado"}
        r = rows[0]
        an = hub.study_ai_analysis(rid)
        st = "analisado" if an else r.get("status") or "gerado"
        return {**{k: r.get(k) for k in ("id", "em", "carteiras", "texto", "resposta", "resposta_em", "copiado_em", "auto")},
                "status": st, "status_txt": STATUS.get(st, st), "analise": an}

    @app.post("/api/pump/study/ai/reports/{rid}")
    async def study_ai_update(rid: str, body: dict, pf=Depends(admin_engine)):
        """Copiou → "esperando a resposta do ChatGPT"; colou a resposta → "resposta recebida, traga para o Claude"."""
        from datetime import datetime, timezone
        rows = [r for r in await hub.study_ai_reports(pf) if r["id"] == rid]
        if not rows:
            return {"error": "relatório não encontrado"}
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        act = str((body or {}).get("acao") or "")
        if act == "copiado":
            if rows[0].get("status") in (None, "gerado"):
                await hub.db.update("study_ai_reports", {"id": rid, "user_id": pf.user_id}, {"status": "esperando", "copiado_em": now})
        elif act == "resposta":
            txt = str((body or {}).get("texto") or "").strip()
            if len(txt) < 20:
                return {"error": "cole a resposta do ChatGPT (texto muito curto)"}
            await hub.db.update("study_ai_reports", {"id": rid, "user_id": pf.user_id},
                                {"status": "resposta", "resposta": txt[:400000], "resposta_em": now})
        else:
            return {"error": "ação inválida"}
        return {"ok": True}

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
              "pause": pf.pause, "resume": pf.resume, "copy": pf.copy_again}.get(act)
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
        r = fn(w)
        # 0.32.224 (dono, dmuX 05/11): quem adiciona à mão passa a ser o dono da carteira na lista manual; se a IA do estudo
        # tinha posto antes, ela deixa de ser "da IA" (e a chave do estudo desligada não barra mais a cópia, ver tab_off)
        if (act == "add" or r.get("added")) and not r.get("error") and w in (getattr(pf, "ia_added", None) or []):
            pf.ia_added = [x for x in pf.ia_added if x != w]
            await hub.save_settings(pf)
        if act in ("copy", "pause") and not r.get("error"):      # 0.32.253: a tela diz o que ficou valendo, não o que se pediu
            r = {**r, "agora": {"ficticia": pf.copy_now(w, False), "real": pf.copy_now(w, True)}}
        return r

    @app.post("/api/pump/close")
    async def pump_close(body: dict, u: dict = Depends(user)):
        pf = await hub.engine(u["id"])
        pid = body.get("id")
        pos = next((p for p in pf.positions() if str(p["id"]) == str(pid)), None)
        if not pos:
            return {"error": "posição não encontrada"}
        hub.check_active(u["id"], pf)
        frac = body.get("frac", 1.0)
        r = pf.close_position(pid, frac)
        if r.get("error"):
            return r
        await audit(hub.db, u["id"], "vender manual",
                    f"{'REAL' if pos.get('real') else 'fictícia'} · {pos.get('symbol')} · {pos.get('mint')}"
                    + ("" if r.get("frac", 1.0) >= 1.0 else f" · {r['frac'] * 100:.0f}%"))
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

    @app.get("/api/pump/bruxo")
    async def bruxo_view(horas: float = 24, pf=Depends(admin_engine)):
        """0.32.41: Aba do Bruxo — sinais de top trader em moeda nova, o que a conta fez em cada um e o estudo."""
        return hub.bruxo_state(pf, max(1.0, min(168.0, horas)))

    @app.get("/api/pump/jev")
    async def jev_view(horas: float = 24, saida: str = "10", fonte: str = "ao_vivo", hold_min: int = 40, hold_cresc: float = 10,
                       hold_show: int = 40, pf=Depends(admin_engine)):
        """0.32.83: aba JEV — cada decisão do Jev (modo sombra) nos sinais da Aba do Bruxo × o que o token fez.
        0.32.84: `fonte` = ao_vivo | bruxo | explorar | base | todos (casos passados analisados pelo estudo do passado);
        horas=0 = tudo."""
        saida = saida if saida in ("5", "10", "25") else "10"
        fonte = fonte if fonte in ("ao_vivo", "bruxo", "explorar", "base", "todos") else "ao_vivo"
        out = hub.jev_state(pf, 0 if horas <= 0 else max(1.0, min(24 * 90, horas)), saida, fonte,
                            max(5, min(1000, hold_min)), max(0.0, min(500.0, hold_cresc)), max(0, min(1000, hold_show)))
        await hub.hold_market(out["detentores"])
        return out

    # 0.32.373 (pedido do dono): BOOST da migração (app/boostmig.py)
    @app.get("/api/pump/boost-migracao")
    async def boost_migracao(u: dict = Depends(admin_only)):
        # 0.32.376: número inválido (infinito/NaN) virava erro 500 sem texto ("resposta inválida do servidor" na tela)
        from .boostmig import finite
        try:
            return finite(hub.bm_state(await hub.engine(u["id"]), u["id"]))
        except Exception as e:
            log.exception("boost: tela")
            return JSONResponse({"error": f"BOOST: {type(e).__name__}: {str(e)[:160]}"}, status_code=500)

    @app.get("/api/pump/boost-migracao/dev/{creator}")
    async def boost_migracao_dev_one(creator: str, u: dict = Depends(admin_only)):
        """0.32.377: detalhes de um DEV (VIP, scam, resultados e os tokens dele em 24 h)."""
        from .boostmig import finite
        if not creator.isalnum() or len(creator) > 60:
            return JSONResponse({"error": "DEV inválido"}, status_code=400)
        return finite(hub.bm_dev(creator))

    @app.get("/api/pump/boost-migracao/historico")
    async def boost_migracao_hist(dias: float = 7, u: dict = Depends(admin_only)):
        """0.32.378: histórico de todo token que migrou (análise aos 20 min) e as métricas."""
        from .boostmig import finite
        return finite(await hub.bm_hist(max(0.04, min(90.0, float(dias)))))

    @app.get("/api/pump/boost-migracao/historico/{mint}")
    async def boost_migracao_hist_one(mint: str, u: dict = Depends(admin_only)):
        from .boostmig import finite
        if not mint.isalnum() or len(mint) > 60:
            return JSONResponse({"error": "token inválido"}, status_code=400)
        d = await hub.bm_hist_token(mint)
        return finite(d) if d else JSONResponse({"error": "token ainda não analisado"}, status_code=404)

    @app.post("/api/pump/boost-migracao/dev")
    async def boost_migracao_dev(body: dict, u: dict = Depends(admin_only)):
        """Tira um DEV da lista scam (engano) ou apaga o histórico de resultados dele (VIP)."""
        cr, ac = str((body or {}).get("creator") or "")[:60], str((body or {}).get("action") or "")
        if ac not in ("unscam", "unvip") or not hub.bm.dev_action(cr, ac):
            return JSONResponse({"error": "DEV não está na lista"}, status_code=404)
        await audit(hub.db, u["id"], "BOOST: " + ("tirou DEV da lista scam" if ac == "unscam" else "apagou histórico do DEV"), cr)
        return {"ok": True, **hub.bm_state(await hub.engine(u["id"]), u["id"])}

    @app.get("/api/pump/jev-trade")
    async def jev_trade(horas: float = 24, pf=Depends(admin_engine)):
        """0.32.87: aba Jev Trade. Simulação: o Jev decide entrada e saída nos tokens novos com 40+ detentores. Nunca compra."""
        return hub.jt_state(pf, 0 if horas <= 0 else max(1.0, min(24 * 7, horas)))

    @app.get("/api/pump/jev-trade/{mint}")
    async def jev_trade_token(mint: str, pf=Depends(admin_engine)):
        it = hub.jt.items.get(mint)
        if it is None:
            raise HTTPException(404, "token não acompanhado")
        return it

    @app.post("/api/pump/jev/passado")
    async def jev_past(body: dict, pf=Depends(admin_engine)):
        """0.32.84: liga/desliga o estudo do passado (o Jev analisa os casos guardados desde o início). Nunca compra."""
        on = bool((body or {}).get("on"))
        r = hub.jev_bt_set(on)
        if r.get("ok"):
            await audit(hub.db, pf.user_id, "jev: estudo do passado " + ("ligado" if on else "desligado"))
        return r

    @app.get("/api/pump/copy-equal/reports")
    async def copy_equal_reports(real: int = 0, pf=Depends(admin_engine)):
        """0.32.73: relatório do Copiar igual (6 h agora + guardados + aprendizado para a Base geral)."""
        return hub.eq_report_state(pf, bool(real))

    @app.get("/api/pump/bruxo/reports")
    async def bruxo_reports(em: str = "", pf=Depends(admin_engine)):
        """0.32.80: relatórios da Aba do Bruxo (30 min ao vivo, hoje, guardados e o aprendizado de 1 dia); `em` abre um guardado."""
        if em:
            return hub.bx_report_get(pf, em) or {"error": "relatório não encontrado"}
        return hub.bx_report_state(pf)

    @app.get("/api/pump/tab-reports")
    async def tab_reports(real: int = 0, pf=Depends(admin_engine)):
        """0.32.41: relatório de ganhos e perdas de cada aba (a cada 30 min), maiores ganhos/perdas com veredito e o aprendizado."""
        return hub.tab_state(pf, bool(real))

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

    @app.get("/api/pump/explore/chance-alta")
    async def explore_chance_alta(horas: float = 24, pf=Depends(admin_engine)):
        """0.32.64: os tokens de "chance alta" do período, um por linha (modal do cartão Chance alta em Logs)."""
        return await hub.chance_alta(pf, max(1.0, min(float(horas), 24 * 90)))

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
        from .evolucoes import comparar, veredito
        ra, rb = await hub.evo_report(pf, a), await hub.evo_report(pf, b)
        if ra.get("error") or rb.get("error"):
            return {"error": ra.get("error") or rb.get("error")}
        return {"a": ra, "b": rb, "linhas": comparar(ra, rb), "veredito": veredito(ra, rb)}

    @app.get("/api/pump/base/evolucoes/{numero}")
    async def evo_report(numero: int, pf=Depends(admin_engine)):
        return await hub.evo_report(pf, numero)

    @app.post("/api/pump/base/evolucoes/{numero}/voltar")
    async def evo_rollback(numero: int, pf=Depends(admin_engine)):
        return await hub.evo_rollback(pf, numero)

    @app.post("/api/pump/base/automatico")
    async def evo_auto(pf=Depends(admin_engine)):
        return await hub.evo_auto(pf)

    @app.get("/api/pump/base-geral/sombra")
    async def base_geral_sombra(pf=Depends(admin_engine)):
        """0.32.117: o que o cérebro teria barrado nas outras abas. Só mede."""
        return hub.brain_shadow()

    @app.get("/api/pump/base-geral")
    async def base_geral(pf=Depends(admin_engine)):
        """0.31.71: o cérebro do robô — maturidade, o que aprendeu, o que está por vir, gráfico e log."""
        st = hub.base_state(pf)
        try:
            st["fotos"] = list(reversed(await hub.db.select("base_snapshots", None, order="em.desc", limit=400)))
            st["log"] = await hub.db.select("base_log", None, order="em.desc", limit=150)
        except Exception:
            st["fotos"], st["log"] = [], []
        st["posicoes"] = await hub.pos_learn_state()        # 0.32.33: aprendizado das posições
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

    @app.get("/api/pump/monitor/leituras")
    async def monitor_reads(tipo: str = "falha", pf=Depends(admin_engine)):
        """0.32.7 (pedido do dono): abrir cada linha do funil do status (falhas, atrasados, não eram trade, trades)."""
        if tipo not in ("falha", "atrasado", "nao_trade", "trade") or hub.monitor is None:
            return {"error": "tipo inválido ou monitor parado"}
        return hub.monitor.rpc_report(tipo)

    @app.get("/api/pump/copy-equal")
    async def copy_equal_get(pf=Depends(admin_engine)):
        """0.32.4: "Copiar igual" — carteiras do leaderboard da pump.fun coladas à mão e o resultado de cada uma."""
        return hub.eq_status(pf)

    @app.get("/api/pump/copy-equal/wallet/{wallet}")
    async def copy_equal_wallet(wallet: str, pf=Depends(admin_engine)):
        """0.32.70: acompanhar UMA carteira do Copiar igual (monitor, atividade, decisões, posições)."""
        if not pf.valid_addr(wallet):
            return {"error": "endereço inválido"}
        return hub.eq_detail(pf, wallet)

    @app.post("/api/pump/copy-equal/mode")
    async def copy_equal_mode(body: dict, pf=Depends(admin_engine)):
        """0.32.65: botão Copiar de cada carteira do Copiar igual (sim = só fictícia, both = fictícia e REAL, off = parar)."""
        return await hub.eq_mode_set(pf, (body or {}).get("wallet"), str((body or {}).get("mode") or ""))

    @app.post("/api/pump/copy-equal")
    async def copy_equal_post(body: dict, pf=Depends(admin_engine)):
        ws = (body or {}).get("wallets")
        if isinstance(ws, str):
            ws = __import__("re").split(r"[\s,;]+", ws)
        return await hub.eq_set(pf, ws if isinstance(ws, list) else [])

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
        us = getattr(hub, "usage", None)
        return {"apis": hub.api_usage_view(), "janelas": us.windows() if us else [],      # 0.32.185: 1/6/12/24 h e total
                "por_aba": us.por_aba() if us else [], "desde": us.started if us else None}

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
             for n in ("index.html", "app.html", "entrar.html", "bnb.html", "hood.html", "forex.html", "dormant.html", "sala.html", "botlive.html", "botlive_sala.html")}

    @app.get("/")
    def landing():
        return HTMLResponse(PAGES["index.html"])

    @app.get("/app")
    def panel():
        return HTMLResponse(PAGES["app.html"])

    # 0.32.169 (pedido do dono): depois do login o admin escolhe o projeto; a BNB tem página própria, fora do painel da pump.fun
    @app.get("/entrar")
    def hub_pick():
        return HTMLResponse(PAGES["entrar.html"])

    # 0.32.266 (pedido do dono): Sala ao vivo — trader em pixel art que reage às compras e vendas da conta, para lives
    @app.get("/sala")
    def sala_page():
        return HTMLResponse(PAGES["sala.html"])

    # 0.32.336 (pedido do dono): BOT LIVE — a cena da Sala para lives lo-fi, com configuração própria e dados da Robinhood por padrão
    @app.get("/botlive")
    def botlive_page():
        return HTMLResponse(PAGES["botlive.html"])

    # 0.32.337 (pedido do dono): /botlive virou a configuração; a cena do BOT fazendo trades fica na SALA LIVE
    @app.get("/botlive/sala")
    def botlive_sala_page():
        return HTMLResponse(PAGES["botlive_sala.html"])

    @app.get("/bnb")
    def bnb_panel():
        return HTMLResponse(PAGES["bnb.html"])

    # 0.32.208 (pedido do dono): Robinhood Chain, mais um projeto isolado (hood.py/hood_api.py, página /hood)
    @app.get("/hood")
    def hood_panel():
        return HTMLResponse(PAGES["hood.html"])

    # 0.32.368 (pedido do dono): Projeto Forex, rede nova (forexcopy.py/forex_api.py, página /forex)
    @app.get("/forex")
    def forex_panel():
        return HTMLResponse(PAGES["forex.html"])

    from .forex_api import add_routes as forex_routes
    forex_routes(app, lambda: getattr(hub, "forex", None), admin_only, hub.db, cfg.public_base_url)
    from .hood_api import add_routes as hood_routes
    hood_routes(app, lambda: getattr(hub, "hood", None), admin_only, hub.db)
    from .botlive_api import add_routes as botlive_routes
    botlive_routes(app, lambda: getattr(hub, "botlive", None), admin_only, hub.db, cfg.public_base_url)

    # 0.32.227 (pedido do dono): Dormant, painel próprio (/dormant) para a watchlist da CoinMarketCap; só observa
    @app.get("/dormant")
    def dormant_panel():
        return HTMLResponse(PAGES["dormant.html"])

    from .dormant_api import add_routes as dormant_routes
    dormant_routes(app, lambda: getattr(hub, "dormant", None), admin_only, hub.db, hub=hub)

    # 0.32.168: aba BNB (Four.Meme) isolada em bnb.py/bnb_api.py; sem a leitura ligada as rotas só dizem "desligada"
    from .bnb_api import add_routes as bnb_routes
    bnb_routes(app, lambda: getattr(hub, "bnb", None), admin_only, hub.db, user, hub=hub)

    app.mount("/static", StaticFiles(directory=WEB), name="static")
    return app
