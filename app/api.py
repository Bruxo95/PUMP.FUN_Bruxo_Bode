"""Rotas HTTP. Tudo em /api/* exige login (token do Supabase); o usuário vem SEMPRE do token.

Regras de segurança:
- Nenhuma rota devolve chave: só "configurada: sim/não" (e o endereço PÚBLICO da carteira).
- Ligar a execução real pede confirmação e fica no audit_log; volta a desligar quando o servidor reinicia.
- Salvar/remover chave, vender manual e trocar USDC→SOL também vão para o audit_log.
"""
from __future__ import annotations

import logging
import os

from fastapi import Depends, FastAPI, HTTPException, Request
import hashlib

from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .auth import AuthError
from .db import audit
from .hub import AccountBlocked
from .keystore import KEY_LINKS, SECRET_NAMES, SYSTEM_NAMES
from .settings import LB_DAYS
from .solana_wallet import check_rpc_url, parse_keypair
from .version import VERSION


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
        return {"id": claims["sub"], "email": prof.get("email") or claims.get("email"),
                "nome": prof.get("nome") or meta.get("full_name") or meta.get("name"),
                "avatar": prof.get("avatar_url") or meta.get("avatar_url") or meta.get("picture"),
                "role": prof.get("role") or "user"}

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
    async def pump_settings(body: dict, pf=Depends(engine)):
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
        return pf.ghosts.snapshot(pf.trades(100000))

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
        return hub.radar_snapshot(pf)

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
                "limit": MAX_WALLETS, "key": bool(hub._study_key()), "params": prm}

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
        pf._emit("Pump.fun: carteira fictícia zerada (volta ao saldo inicial)")
        return pf.reset_sim()

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
        return [{"acao": r.get("acao"), "detalhe": r.get("detalhe"), "at": r.get("at")} for r in rows]

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
        if len(value) < 16:
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

    @app.get("/api/admin/audit")
    async def admin_audit(user_id: str = "", limit: int = 200, u: dict = Depends(admin_only)):
        """Registro de segurança de todas as contas (o detalhe nunca contém chaves)."""
        if user_id and not UUID.match(user_id):
            return []
        limit = max(1, min(limit, 1000))
        rows = await hub.db.select("audit_log", {"user_id": user_id} if user_id else None, order="at.desc", limit=limit)
        emails = {p["user_id"]: p.get("email") for p in await hub.db.select("profiles", None, columns="user_id,email")}
        return [{"at": r.get("at"), "user_id": r.get("user_id"), "email": emails.get(r.get("user_id")),
                 "acao": r.get("acao"), "detalhe": r.get("detalhe")} for r in rows]

    NOVIDADES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "novidades.json")

    @app.get("/api/admin/novidades")
    async def admin_novidades(u: dict = Depends(admin_only)):
        """Histórico do que foi implementado (versão, onde fica, o que faz). Só admin, pedido do dono em 2026-10-25."""
        import json as _json
        with open(NOVIDADES, encoding="utf-8") as f:
            return {"itens": _json.load(f)["itens"]}

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
