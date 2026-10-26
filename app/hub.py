"""Central dos usuários: um motor de cópia (PumpFun) por usuário, todos ligados ao MESMO mercado público.

Cada motor tem: configuração própria, dados próprios (SupabaseStore), chaves próprias (KeyRing, já abertas só na
memória) e carteira/execução real próprias (desligada ao iniciar).
"""
from __future__ import annotations

import asyncio
import copy
import logging
import math
import os
import time
from datetime import datetime, timezone

from .db import SupabaseStore, Vault, audit
from .jupiter import JupiterQuoter, JupiterWallet
from .keystore import KEY_LINKS, SYSTEM_NAMES, SYSTEM_OWNER, KeyRing
from .logsafe import add_secret
from .pumpfun import AUTO_ORIGINS, PumpFun, PumpMarket, PumpReal
from .radar import RadarBuffer, callout_policy
from .settings import PumpSettings
from .solana_wallet import UserWallet

log = logging.getLogger("hub")


class AccountBlocked(Exception):
    """Conta bloqueada pelo admin: nenhum motor é (re)carregado e nenhuma ação sensível segue."""


class PumpHub:
    def __init__(self, cfg, http, db, box):
        self.cfg, self.http, self.db = cfg, http, db
        self.vault = Vault(db, box)
        self.public_quoter = JupiterQuoter(http)       # sem chave: usado nas trocas de quem não tem chave própria
        self.market = PumpMarket(jup=self.public_quoter)
        self.system_keys: dict[str, str] = {}          # chaves do sistema (admin), já abertas, só na memória
        self.engines: dict[str, PumpFun] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._blocked: set[str] = set()            # contas bloqueadas (vale também para cargas já em andamento)
        self._trade_q: list[dict] = []             # operações das carteiras em estudo a gravar (0.14.0)
        self.radar = RadarBuffer()                # só observações ao vivo; não gera ordens
        from .tokenlab import TokenLab
        self.lab = TokenLab(self.market)          # base própria da pump.fun (0.21.0)
        from .explore import Explore
        self.explore = Explore()
        from .elite import Elite
        self.elite = Elite(self.market)           # maiores traders (0.31.2)                  # listas estilo pump.fun/explore pela Solana Tracker (0.28.0)
        self._study_at: dict[str, float] = {}      # carteira -> quando o histórico foi atualizado
        self._study_auto_at: dict[str, float] = {}  # usuário -> última volta do estudo automático (0.31.13)
        self._tasks: list[asyncio.Task] = []
        self.shared_st_key = ""                    # chave da Solana Tracker do sistema (visualização para todos)
        self.started_at = time.time()
        self.errors: list[dict] = []
        self._touched: dict[str, float] = {}
        # trava geral da execução real (no .env): enquanto false, ninguém liga o real
        self.monitor = None                        # SharedMonitor (ligado em start)
        self.running = False
        self.real_allowed = os.environ.get("PUMP_REAL_ALLOWED", "false").strip().lower() in ("1", "true", "sim", "yes")

    # ------------------------------------------------------------------ perfis
    async def ensure_profile(self, claims: dict) -> dict:
        uid = claims["sub"]
        rows = await self.db.select("profiles", {"user_id": uid})
        if rows:
            now = time.time()
            if now - self._touched.get(uid, 0) > 300:          # último acesso (no máx. 1 gravação a cada 5 min)
                self._touched[uid] = now
                try:
                    await self.db.update("profiles", {"user_id": uid},
                                         {"ultimo_acesso": datetime.now(timezone.utc).isoformat()})
                except Exception:
                    pass
            return rows[0]
        # o gatilho do banco já cria o perfil; isto é só uma garantia (ex.: usuário criado antes da migração)
        meta = claims.get("user_metadata") or {}
        anyone = await self.db.select("profiles", None, limit=1, columns="user_id")
        prof = {"user_id": uid, "email": claims.get("email"), "nome": meta.get("full_name") or meta.get("name"),
                "avatar_url": meta.get("avatar_url"), "role": "user" if anyone else "admin"}
        await self.db.insert("profiles", prof, upsert=True, on_conflict="user_id")
        await self.db.insert("user_settings", {"user_id": uid}, upsert=True, on_conflict="user_id")
        return (await self.db.select("profiles", {"user_id": uid}) or [prof])[0]

    # ------------------------------------------------------------------ motores por usuário
    async def engine(self, uid: str) -> PumpFun:
        # SEC-02 (auditoria 2026-10-25): uma carga iniciada antes do bloqueio terminava depois e recolocava a conta
        # no monitor. Agora carga e bloqueio usam a mesma trava e a carga confere o bloqueio antes de publicar.
        if uid in self._blocked:
            raise AccountBlocked(uid)
        pf = self.engines.get(uid)
        if pf is not None:
            return pf
        lock = self._locks.setdefault(uid, asyncio.Lock())
        async with lock:
            pf = self.engines.get(uid)
            if pf is None:
                pf = await self._load(uid)
                if uid in self._blocked:                # bloqueada enquanto carregava: descarta
                    self._stop_engine(pf)
                    raise AccountBlocked(uid)
                self.engines[uid] = pf
        return pf

    def check_active(self, uid: str, pf: PumpFun | None = None) -> None:
        """Antes de ação sensível (real, troca, venda, chave): a conta segue liberada e o motor é o atual."""
        if uid in self._blocked or (pf is not None and self.engines.get(uid) is not pf):
            raise AccountBlocked(uid)

    @staticmethod
    def _stop_engine(pf: PumpFun) -> None:
        pf.cfg.pump_real_enabled = False
        t = getattr(pf, "_real_task", None)
        if t:
            t.cancel()

    async def _load(self, uid: str) -> PumpFun:
        rows = await self.db.select("user_settings", {"user_id": uid})
        saved = (rows[0].get("settings") if rows else None) or {}
        cfg = PumpSettings(saved, self.cfg.defaults)          # pump_real_enabled sempre False aqui
        store = SupabaseStore(self.db, uid)
        await store.load()
        pf = PumpFun(cfg, store, self.http, None, market=self.market)
        pf.user_id = uid
        profiles = await self.db.select("profiles", {"user_id": uid}, columns="role")
        pf.role = (profiles[0].get("role") if profiles else None) or "user"
        await self.load_auto(pf)
        pf.keys = KeyRing(await self.vault.load(uid))
        pf.lb_key_fallback = lambda: self.shared_st_key
        try:                                       # carteiras em estudo (tabela pode ainda não existir)
            pf.study = [r["wallet"] for r in await self.db.select("study_wallets", {"user_id": uid}, order="criado_em.asc")]
        except Exception:
            pf.study = []
        try:                                       # estratégias fantasma (0.18.0; tabela pode ainda não existir)
            rows = await self.db.select("ghost_stats", {"user_id": uid})
            pf.ghosts.load(rows[0].get("data") if rows else None)
        except Exception:
            pass
        self._wire_wallet(pf)
        pf.tg = lambda msg, _pf=pf: self.tg_queue(_pf, msg)
        for p in pf.positions():                   # depois de reiniciar, nenhuma venda está "em andamento"
            if p.get("selling"):
                p["selling"] = False
                pf._save_pos(p)
        if self.running:
            self._start_engine(pf)
        return pf

    def _start_engine(self, pf: PumpFun) -> None:
        """Fila de execução REAL própria do usuário (uma de cada vez, espera a confirmação na blockchain)."""
        if getattr(pf, "_real_task", None) is None:
            pf._real_task = asyncio.get_running_loop().create_task(pf.real_loop())

    def _wire_wallet(self, pf: PumpFun) -> None:
        """(Re)monta carteira, Jupiter e execução real do usuário a partir das chaves dele."""
        k = pf.keys
        try:
            w = UserWallet(k.get("wallet_private_key"), k.get("rpc_url"), self.cfg.solana_rpc_public,
                           k.get("jupiter_api_key"))
        except ValueError:
            w = UserWallet("", k.get("rpc_url"), self.cfg.solana_rpc_public)
        pf.sol_wallet = w
        # trocas da carteira do usuário: chave Jupiter PRÓPRIA dele ou a API pública — nunca a chave do sistema
        jw = JupiterWallet(self.http, w, self.public_quoter, priority_sol=float(pf.cfg.pump_priority_sol))
        pf.jw = jw
        pf.real = PumpReal(pf.cfg, self.http, w, k, jup=jw)
        if not w.keypair:                            # sem carteira: real desliga
            pf.cfg.pump_real_enabled = False

    async def save_settings(self, pf: PumpFun) -> None:
        await self.db.update("user_settings", {"user_id": pf.user_id},
                             {"settings": pf.cfg.user_dict(), "atualizado_em": datetime.now(timezone.utc).isoformat()})

    async def set_secret(self, pf: PumpFun, name: str, value: str) -> None:
        await self.vault.save(pf.user_id, name, value)
        pf.keys.set(name, value)
        self._wire_wallet(pf)
        await audit(self.db, pf.user_id, "salvar chave", name)

    async def remove_secret(self, pf: PumpFun, name: str) -> None:
        await self.vault.delete(pf.user_id, name)
        pf.keys.set(name, "")
        if name == "wallet_private_key":
            pf.cfg.pump_real_enabled = False
        self._wire_wallet(pf)
        await audit(self.db, pf.user_id, "remover chave", name)

    async def refresh_shared_key(self) -> None:
        """Chaves do SISTEMA (configuradas pelo admin): servem para todo mundo VER a ferramenta funcionando —
        ranking de top traders (Solana Tracker), cotações (Jupiter) e a conexão com a PumpPortal. Nunca são
        usadas para executar nada em nome de ninguém."""
        try:
            keys = {}
            for r in await self.db.select("app_secrets", None):
                try:
                    keys[r["nome"]] = self.vault.box.decrypt(SYSTEM_OWNER, r["nome"], r["valor_criptografado"])
                    add_secret(keys[r["nome"]])
                except Exception:
                    log.warning("Chave do sistema %s não abriu (APP_ENCRYPTION_KEY trocada?)", r["nome"])
            self.system_keys = keys
        except Exception as e:
            log.warning("Chaves do sistema: %s", str(e)[:120])
        self.shared_st_key = self.system_keys.get("solanatracker_api_key", "")
        jk = self.system_keys.get("jupiter_api_key", "")
        if jk != getattr(self, "_jup_key_in_use", ""):
            self.market.jup = JupiterQuoter(self.http, jk) if jk else self.public_quoter
            self._jup_key_in_use = jk

    async def system_keys_view(self) -> dict:
        rows = {r["nome"]: r for r in await self.db.select("app_secrets", None, columns="nome,atualizado_em")}
        return {k: {"label": v, "configured": k in rows, "updated_at": (rows.get(k) or {}).get("atualizado_em"),
                    "link": KEY_LINKS.get(k)} for k, v in SYSTEM_NAMES.items()}

    async def set_system_key(self, admin_id: str, name: str, value: str) -> None:
        await self.db.insert("app_secrets", {"nome": name, "valor_criptografado": self.vault.box.encrypt(SYSTEM_OWNER, name, value),
                                             "atualizado_por": admin_id,
                                             "atualizado_em": datetime.now(timezone.utc).isoformat()},
                             upsert=True, on_conflict="nome")
        await self.refresh_shared_key()
        await audit(self.db, admin_id, "admin: salvar chave do sistema", name)

    async def remove_system_key(self, admin_id: str, name: str) -> None:
        await self.db.delete("app_secrets", {"nome": name})
        await self.refresh_shared_key()
        if name == "solanatracker_api_key":           # quem dependia dela fica sem ranking até pôr a própria
            for pf in self.engines.values():
                if not pf.lb_key_own():
                    pf.leaderboard = []
                    pf.refresh_followed(force=True)
        await audit(self.db, admin_id, "admin: remover chave do sistema", name)

    # ------------------------------------------------------------------ segundo plano
    async def flush_loop(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            for pf in list(self.engines.values()):
                try:
                    await pf.store.flush()
                    await self.save_auto(pf)
                except Exception as e:
                    log.warning("flush: %s", str(e)[:120])
            await self.flush_trades()

    # ------------------------------------------------------------------ operações automáticas (0.30.0)
    async def _auto_select(self, pf, *, gte=None, is_null=(), limit=10000) -> list[dict]:
        """Paginação explícita, sempre na conta; não depende do limite padrão de 1.000 do PostgREST."""
        out = []
        for offset in range(0, limit, 500):
            batch = await self.db.select("auto_trades", {"user_id": pf.user_id}, order="entrada_em.desc",
                                         limit=min(500, limit - offset), offset=offset, gte=gte, is_null=is_null)
            out.extend(batch)
            if len(batch) < 500:
                return out
        raise RuntimeError("histórico automático excede o limite de leitura; entradas pausadas")

    async def load_auto(self, pf) -> bool:
        from .auto_trades import iso, operation_row, ts
        pf.auto_ready = False
        pf._auto_loaded = False
        pf._auto_load_retry_at = time.time()
        now = time.time()
        day = datetime.fromtimestamp(now, timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        try:
            rows = await self._auto_select(pf, gte={"entrada_em": iso(now - 86400)})
            # Fechadas hoje / sequência de perdas: podem ter sido abertas antes das últimas 24 h.
            streak_since = now - max(86400, float(getattr(pf.cfg, "pump_ar_streak_h", 1)) * 3600)
            rows += await self._auto_select(pf, gte={"saida_em": iso(min(day, streak_since))})
            rows += await self._auto_select(pf, is_null=("saida_em",))
            restored = {str(row["id"]): {k: copy.deepcopy(v) for k, v in row.items() if k != "user_id"} for row in rows}
            # A recuperação pode coincidir com um fechamento; mudanças ainda não gravadas têm prioridade.
            for rid in getattr(pf, "_auto_dirty", set()):
                if rid in pf.auto_rows:
                    restored[rid] = copy.deepcopy(pf.auto_rows[rid])
            for trade in pf.trades(20000):
                if trade.get("auto") is True and trade.get("origem") in AUTO_ORIGINS:
                    rid = str(trade["id"])
                    if (rid not in restored and (ts(trade.get("opened_at")) or 0) < now - 86400
                            and (ts(trade.get("closed_at")) or 0) < min(day, streak_since)):
                        continue
                    # O histórico normal pode ter sido gravado antes de uma interrupção do flush automático.
                    row = operation_row(trade, previous=restored.get(rid), closed=True)
                    if row != restored.get(rid):
                        restored[rid] = row
                        pf._auto_dirty.add(rid)
            for pos in pf.positions():
                if pos.get("auto") is True and pos.get("origem") in AUTO_ORIGINS:
                    rid = str(pos["id"])
                    if (restored.get(rid) or {}).get("saida_em"):
                        raise RuntimeError("posição aberta diverge do registro automático fechado")
                    restored[rid] = operation_row(pos, previous=restored.get(rid))
                    pf._auto_dirty.add(rid)
            pf.auto_rows = restored
            pf._auto_loaded = True
            pf.auto_ready, pf.auto_error = True, None
            return True
        except Exception as exc:
            pf.auto_error = "histórico automático indisponível; novas entradas pausadas"
            log.warning("Operações automáticas não carregaram (%s…): %s", pf.user_id[:8], type(exc).__name__)
            return False

    async def save_auto(self, pf=None) -> int:
        total = 0
        for engine in ([pf] if pf is not None else list(self.engines.values())):
            if getattr(engine.store, "last_error", None):
                engine.auto_ready = False
                engine.auto_error = "gravação das posições indisponível; novas entradas pausadas"
                continue  # não confirmar um fechamento na tabela auxiliar antes de persistir posições/trades
            if not getattr(engine, "_auto_loaded", False):
                if time.time() - getattr(engine, "_auto_load_retry_at", 0) >= 30:
                    await self.load_auto(engine)
                if not getattr(engine, "_auto_loaded", False):
                    continue
            pending = {rid: copy.deepcopy(engine.auto_rows[rid]) for rid in list(engine._auto_dirty)
                       if rid in engine.auto_rows}
            if not pending:
                if not getattr(engine.store, "last_error", None):
                    engine.auto_ready, engine.auto_error = True, None
                continue
            try:
                await self.db.insert("auto_trades", [{**row, "user_id": engine.user_id} for row in pending.values()],
                                     upsert=True, on_conflict="id")
                for rid, row in pending.items():
                    if engine.auto_rows.get(rid) == row:
                        engine._auto_dirty.discard(rid)
                if not getattr(engine.store, "last_error", None):
                    engine.auto_ready, engine.auto_error = True, None
                total += len(pending)
            except Exception as exc:
                engine.auto_ready = False
                engine.auto_error = "gravação automática indisponível; novas entradas pausadas"
                log.warning("Operações automáticas não gravaram (%s…): %s", engine.user_id[:8], type(exc).__name__)
        return total

    def auto_status(self, pf, origem="explorar", now=None) -> dict:
        from .auto_trades import number, ts
        now = time.time() if now is None else now
        day = datetime.fromtimestamp(now, timezone.utc).date()
        rows = pf._auto_operations()
        day_rows = [row for row in rows if (closed := ts(row.get("saida_em"))) is not None
                    and closed <= now and datetime.fromtimestamp(closed, timezone.utc).date() == day]
        reason = pf.auto_guard(t=now)
        enabled = bool(getattr(pf.cfg, "pump_ex_auto_on", False)) if origem == "explorar" else bool(getattr(pf.cfg, "pump_auto_on", False))
        until = getattr(pf, "_auto_pause_until", None)
        opened = {str(pos["id"]) for pos in pf.positions() if pos.get("auto")}
        opened.update(rid for rid, row in pf.auto_rows.items() if not row.get("saida_em"))
        return {"enabled": enabled, "paused": bool(reason), "reason": reason, "until": until,
                "ready": bool(pf.auto_ready), "open": len(opened) + len(getattr(pf, "_auto_pending", {})),
                "entries_h": sum((entry := number(row.get("_entry_t")) or ts(row.get("entrada_em"))) is not None
                                 and now - 3600 <= entry <= now for row in rows),
                "day_pnl_sol": round(sum(number(row.get("pnl_sol")) or 0 for row in day_rows), 8)}

    async def auto_history(self, pf, origem="explorar", days=30) -> dict:
        from .auto_trades import api_item, iso, readiness, summary, ts
        now = time.time()
        error = None
        try:
            history = await self._auto_select(pf, gte={"entrada_em": iso(now - days * 86400)})
            merged = {str(row["id"]): row for row in history}
        except Exception:
            merged = {}
            error = "histórico automático indisponível; exibindo somente dados já carregados"
        merged.update({rid: copy.deepcopy(row) for rid, row in pf.auto_rows.items()})
        rows = [row for row in merged.values() if row.get("origem") == origem
                and ((entry := ts(row.get("entrada_em"))) is not None and entry >= now - days * 86400
                     or not row.get("saida_em"))]
        rows.sort(key=lambda row: ts(row.get("entrada_em")) or 0, reverse=True)
        simulated = [row for row in rows if not row.get("real")]
        today = datetime.fromtimestamp(now, timezone.utc).date()
        today_rows = [row for row in simulated if (closed := ts(row.get("saida_em"))) is not None
                      and datetime.fromtimestamp(closed, timezone.utc).date() == today]
        criterion = readiness(simulated)
        if error:
            criterion.update(recommended=False, reason="Ainda não recomendado para dinheiro real: histórico incompleto.")
        real = [row for row in rows if row.get("real")]
        real_today = [row for row in real if (closed := ts(row.get("saida_em"))) is not None
                      and datetime.fromtimestamp(closed, timezone.utc).date() == today]
        positions = {str(pos["id"]): pos for pos in pf.positions()}
        items = []
        for row in rows:
            item = api_item(row, now)
            pos = positions.get(str(row["id"]))
            if item["open"] and pos is not None:
                price = (pf.tokens.get(pos["mint"]) or {}).get("price") or pos.get("price_now")
                if price and pos.get("sol_in"):
                    marked = (pos.get("proceeds") or 0) + pf._exit_value(pos, price) - pos["sol_in"]
                    item.update(pnl_sol=round(marked, 8), pnl_pct=round(marked / pos["sol_in"] * 100, 4), estimated=True)
            items.append(item)
        return {"origem": origem, "days": days, "items": items,
                "status": self.auto_status(pf, origem, now), "summary": {"day": summary(today_rows), "period": summary(simulated)},
                "summary_mode": "simulado", "real_summary": {"day": summary(real_today), "period": summary(real)} if real else None,
                "readiness": criterion, "error": error or pf.auto_error}

    # ------------------------------------------------------------------ aprendizado diário (tabela learning_daily)
    async def learning_history(self, uid: str, days: int = 30) -> tuple[list[dict], str | None]:
        try:
            return await self.db.select("learning_daily", {"user_id": uid}, order="dia.desc", limit=days), None
        except Exception as e:                       # tabela ainda não criada no Supabase: a página segue sem histórico
            return [], str(e)[:160]

    async def save_learning(self) -> int:
        """Guarda o resumo do dia de cada conta carregada (uma linha por dia, atualizada a cada rodada)."""
        from .learning import build, snapshot
        dia, n = datetime.now(timezone.utc).date().isoformat(), 0
        for uid, pf in list(self.engines.items()):
            try:
                snap = snapshot(build(pf, bool(pf.cfg.pump_real_enabled)))
                await self.db.insert("learning_daily", {"user_id": uid, "dia": dia, "data": snap,
                                                        "atualizado_em": datetime.now(timezone.utc).isoformat()},
                                     upsert=True, on_conflict="user_id,dia")
                n += 1
            except Exception as e:
                log.warning("Aprendizado diário não gravou (%s…): %s", uid[:8], str(e)[:160])
                break                                    # tabela ausente/banco fora: tenta na próxima rodada
        return n

    async def save_ghosts(self) -> int:
        """Grava o resultado das estratégias fantasma de quem teve novidade (uma linha por usuário)."""
        n = 0
        for uid, pf in list(self.engines.items()):
            if not pf.ghosts.dirty:
                continue
            try:
                await self.db.insert("ghost_stats", {"user_id": uid, "data": pf.ghosts.dump(),
                                                     "atualizado_em": datetime.now(timezone.utc).isoformat()},
                                     upsert=True, on_conflict="user_id")
                pf.ghosts.dirty = False
                n += 1
            except Exception as e:
                log.warning("Estratégias fantasma não gravaram (%s…): %s", uid[:8], str(e)[:160])
                break
        return n

    async def ghosts_loop(self) -> None:
        n = 0
        while True:
            await asyncio.sleep(60)
            try:
                await self.flush_blacklist()
            except Exception:
                pass                                   # já registrado; tenta de novo na próxima volta
            n += 1
            if n % 2 == 0:
                try:
                    await self.save_lab(trim=n % 360 == 0)
                except Exception as e:
                    log.warning("Base da pump.fun não gravou: %s", str(e)[:120])
            if n % 5 == 0:
                await self.save_ghosts()
            if n % 2 == 0:
                try:
                    await self.save_elite()
                except Exception as e:
                    log.warning("Sinais dos maiores traders não gravaram: %s", str(e)[:120])

    # ------------------------------------------------------------------ maiores traders (0.31.2)
    async def save_elite(self) -> int:
        rows = self.elite.take_dirty()
        if rows:
            try:
                await self.db.insert("elite_signals", rows, upsert=True, on_conflict="id")
            except Exception:
                self.elite.dirty |= {r["id"] for r in rows}
                raise
        return len(rows)

    async def load_elite(self) -> None:
        try:
            self.elite.load(await self.db.select("elite_signals", None, order="criado_em.desc", limit=3000))
        except Exception as e:
            log.warning("Sinais dos maiores traders não carregaram (tabela criada?): %s", str(e)[:120])

    # ------------------------------------------------------------------ base própria da pump.fun (0.21.0)
    async def load_lab(self) -> None:
        try:
            hrs = await self.db.select("market_hourly", None, order="hora.desc", limit=48)
            crs = await self.db.select("creator_stats", None, limit=50000)
            self.lab.load(hrs, crs)
            st = await self.db.select("lab_state", {"id": "live"})
            recent = await self.db.select("token_life", None, order="criado_em.desc", limit=30000)
            self.lab.restore(st[0].get("data") if st else None, recent)
        except Exception as e:
            log.warning("Base da pump.fun não carregou (tabelas criadas?): %s", str(e)[:120])

    async def save_lab(self, trim: bool = False) -> int:
        tl, hrs, crs = self.lab.take_dirty()
        try:
            if tl:
                await self.db.insert("token_life", tl, upsert=True, on_conflict="mint")
            if hrs:
                await self.db.insert("market_hourly", hrs, upsert=True, on_conflict="hora")
            for i in range(0, len(crs), 500):
                await self.db.insert("creator_stats", crs[i:i + 500], upsert=True, on_conflict="creator")
            await self.db.insert("lab_state", {"id": "live", "data": self.lab.dump_live()}, upsert=True, on_conflict="id")
            if trim:                                     # guarda 14 dias de tokens (todos, para estudar; 0.24.0)
                await self.db.rpc("trim_token_life", {"p_days": 14})
        except Exception:
            self.lab.new_rows = [dict(r["data"], mint=r["mint"], creator=r["creator"], label=r["label"]) for r in tl] + self.lab.new_rows
            self.lab.dirty_hours |= {h["hora"] for h in hrs}
            self.lab.dirty_creators |= {c["creator"] for c in crs}
            raise
        return len(tl)

    # ------------------------------------------------------------------ lista negra compartilhada (0.20.0)
    async def load_blacklist(self) -> None:
        try:
            for r in await self.db.select("blacklist", None, limit=20000):
                self.market.blacklist[r["endereco"]] = {"tipo": r.get("tipo"), "motivo": r.get("motivo"),
                                                       "criado_em": r.get("criado_em")}
        except Exception as e:
            log.warning("Lista negra não carregou (tabela criada?): %s", str(e)[:120])

    async def flush_blacklist(self) -> int:
        new, self.market.bl_new = self.market.bl_new, []
        rows = [{"endereco": a, **{k: v for k, v in self.market.blacklist[a].items() if k in ("tipo", "motivo")}}
                for a in dict.fromkeys(new) if a in self.market.blacklist]
        if not rows:
            return 0
        try:
            await self.db.insert("blacklist", rows, upsert=True, on_conflict="endereco")
        except Exception as e:
            self.market.bl_new = new + self.market.bl_new          # tenta de novo na próxima volta
            log.warning("Lista negra não gravou: %s", str(e)[:120])
            raise
        return len(rows)

    async def blacklist_remove(self, addr: str) -> None:
        self.market.blacklist.pop(addr, None)
        self.market.bl_new = [a for a in self.market.bl_new if a != addr]
        await self.db.delete("blacklist", {"endereco": addr})

    # ------------------------------------------------------------------ avisos no Telegram (0.20.0)
    TG_KEYS = ("hot callout", "stop de perda", "dev vendeu", "pausado", "[pump real]", "graduou", "perdas seguidas",
               "compra automática", "boost on", "aprendi com os erros", "estudo automático")

    def tg_wanted(self, pf, msg: str) -> bool:
        if not getattr(pf.cfg, "pump_tg_on", False):
            return False
        if getattr(pf.cfg, "pump_tg_all", False):
            return True
        low = msg.lower()
        return any(k in low for k in self.TG_KEYS)

    def tg_queue(self, pf, msg: str) -> None:
        """Chamado por pf._emit: envia em segundo plano, sem travar o motor (fora de um loop, não faz nada)."""
        if not self.tg_wanted(pf, msg):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self.tg_send_now(pf, msg))

    async def tg_send_now(self, pf, msg: str, force: bool = False) -> tuple[bool, str]:
        tok, chat = pf.keys.get("telegram_bot_token"), pf.keys.get("telegram_chat_id")
        if not tok or not chat:
            return False, "configure o token do bot e o ID do chat em Configurações → Chaves pessoais"
        now = time.time()
        sent = [x for x in getattr(pf, "_tg_sent", []) if now - x < 60]
        if len(sent) >= 20 and not force:                       # no máx. 20 avisos por minuto por pessoa
            return False, "limite de avisos por minuto"
        pf._tg_sent = sent + [now]
        try:
            r = await self.http.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                                     json={"chat_id": chat, "text": msg[:3500], "disable_web_page_preview": True},
                                     timeout=10)
            if r.status_code == 200:
                return True, ""
            return False, f"o Telegram recusou (HTTP {r.status_code}) — confira o token e se você mandou /start ao bot"
        except Exception as e:
            return False, "não consegui falar com o Telegram: " + type(e).__name__

    # ------------------------------------------------------------------ relatório do dia (0.31.5)
    async def save_daily(self, now: float | None = None) -> int:
        """Foto dos números da Visão geral + relatório do dia (tabela daily_report). Na virada do dia (UTC) fecha o dia
        anterior e, com o Telegram ligado, manda o resumo com as sugestões."""
        from .daily import build, day_of, kpis, telegram_text
        now = time.time() if now is None else now
        dia, prev, n = day_of(now), day_of(now - 86400), 0
        for uid, pf in list(self.engines.items()):
            try:
                rows = await self.db.select("daily_report", {"user_id": uid, "dia": dia})
                pts = list(((rows[0].get("data") or {}).get("points") or [])) if rows else []
                pts.append(kpis(pf))
                from .modules_report import build as menus
                rep_today = build(pf, dia, pts)
                rep_today["modules"] = menus(self, pf, dia, True)      # relatório de cada menu (0.31.9)
                await self.db.insert("daily_report", {"user_id": uid, "dia": dia, "data": rep_today,
                                                      "atualizado_em": datetime.now(timezone.utc).isoformat()},
                                     upsert=True, on_conflict="user_id,dia")
                if getattr(pf, "_daily_closed", None) != prev:
                    old = await self.db.select("daily_report", {"user_id": uid, "dia": prev})
                    if old and not (old[0].get("data") or {}).get("closed"):
                        rep = build(pf, prev, (old[0].get("data") or {}).get("points"))
                        rep["modules"] = (old[0].get("data") or {}).get("modules") or []   # a última foto ao vivo do dia
                        rep["closed"] = True
                        await self.db.insert("daily_report", {"user_id": uid, "dia": prev, "data": rep,
                                                              "atualizado_em": datetime.now(timezone.utc).isoformat()},
                                             upsert=True, on_conflict="user_id,dia")
                        if getattr(pf.cfg, "pump_tg_on", False):
                            await self.tg_send_now(pf, telegram_text(rep), force=True)
                    pf._daily_closed = prev
                n += 1
            except Exception as e:
                log.warning("Relatório do dia não gravou (%s…): %s", uid[:8], str(e)[:160])
                break                                   # tabela ausente/banco fora: tenta na próxima rodada
        return n

    async def backfill_daily(self, now: float | None = None) -> int:
        """Relatórios dos dias que já passaram (0.31.6), refeitos a partir dos trades guardados: um por dia com trade,
        até 60 dias, só os que ainda não existem. Sem as fotos de 30 min (não existiam), com o saldo do fim do dia."""
        from .daily import build, day_of, days_with_trades
        now = time.time() if now is None else now
        n = 0
        for uid, pf in list(self.engines.items()):
            if getattr(pf, "_daily_backfilled", False):
                continue
            try:
                have = {str(r.get("dia")) for r in await self.db.select("daily_report", {"user_id": uid}, columns="dia", limit=400)}
                for d in days_with_trades(pf, day_of(now)):
                    if d in have:
                        continue
                    rep = build(pf, d, [])
                    from .modules_report import build as menus
                    rep.update(closed=True, backfilled=True, modules=menus(self, pf, d, False))
                    await self.db.insert("daily_report", {"user_id": uid, "dia": d, "data": rep,
                                                          "atualizado_em": datetime.now(timezone.utc).isoformat()},
                                         upsert=True, on_conflict="user_id,dia")
                    n += 1
                pf._daily_backfilled = True
            except Exception as e:
                log.warning("Relatórios dos dias passados não gravaram (%s…): %s", uid[:8], str(e)[:160])
                break
        return n

    async def daily_loop(self) -> None:
        await asyncio.sleep(60)
        try:
            await self.backfill_daily()
        except Exception as e:
            log.warning("relatórios passados: %s", str(e)[:160])
        while True:
            await self.save_daily()
            await asyncio.sleep(1800)

    async def study_auto(self, pf, now: float | None = None) -> dict:
        """Estudo automático (0.31.13, app/autostudy.py): julga as carteiras que o robô pôs no estudo, tira as que não
        compensam, põe candidatas novas nas vagas e aprende que tipo de carteira costuma compensar."""
        from .auto_trades import ts
        from .autostudy import AUTO_TAG, BAN_S, PER_CYCLE, candidates, features, judge, rates
        from .study import MAX_WALLETS, copy_params, summary
        now = time.time() if now is None else now
        if getattr(pf, "role", "user") != "admin" or not getattr(pf.cfg, "pump_st_auto_on", True):
            return {"ok": False, "motivo": "desligado"}
        rows = await self.db.select("study_wallets", {"user_id": pf.user_id}, order="criado_em.asc")
        log_rows = await self.db.select("study_auto_log", {"user_id": pf.user_id}, order="em.desc", limit=1000)
        info_of = {r["wallet"]: r.get("info") or {} for r in reversed(log_rows) if r.get("acao") == "adicionou"}
        approved = {r["wallet"] for r in log_rows if r.get("acao") == "aprovou"}
        prm = copy_params(pf)
        done = {"descartou": 0, "aprovou": 0, "adicionou": 0}
        out_now: set[str] = set()                   # descartadas nesta volta não podem voltar na mesma volta

        async def note(w, acao, motivo, info):
            await self.db.insert("study_auto_log", {"user_id": pf.user_id, "wallet": w, "acao": acao, "motivo": motivo,
                                                    "info": info, "em": datetime.fromtimestamp(now, timezone.utc).isoformat()})
            done[acao] += 1
            pf._emit(f"Estudo automático: {acao} {w[:4]}…{w[-4:]} — {motivo}")

        auto = [r for r in rows if str(r.get("apelido") or "").startswith(AUTO_TAG)]
        for r in auto:
            p = await self.study_profile(r["wallet"], prm)
            if p.get("error"):
                continue
            j = judge(ts(r.get("criado_em")) or now, summary(p), now)
            if not j or (j[0] == "aprovou" and r["wallet"] in approved):
                continue
            if j[0] == "descartou":
                await self.study_set(pf, r["wallet"], "remove")
                out_now.add(r["wallet"])
            await note(r["wallet"], j[0], j[1], info_of.get(r["wallet"], {}))
        cur = list(getattr(pf, "study", []) or [])
        n_auto = len(auto) - done["descartou"]
        free = min(int(getattr(pf.cfg, "pump_st_auto_max", 15)) - n_auto, MAX_WALLETS - len(cur), PER_CYCLE)
        recent_out = {r["wallet"] for r in log_rows if r.get("acao") == "descartou" and now - (ts(r.get("em")) or 0) < BAN_S}
        rt = rates(log_rows)
        pool = [{**x, "fonte": "ranking"} for x in (pf.leaderboard or [])]
        pool += [{"wallet": w, **n, "fonte": "maiores traders"} for w, n in self.elite.names.items() if not self.elite.bot_reason(w, now)]
        for c in candidates(pool, set(cur) | recent_out | out_now | set(getattr(pf, "banned", []) or []), rt)[:max(0, free)]:
            nome = (c.get("name") or c["fonte"])[:30]
            res = await self.study_set(pf, c["wallet"], "add", AUTO_TAG + nome)
            if res.get("ok") and not res.get("already"):
                await note(c["wallet"], "adicionou", f"{c['fonte']}, nota {c['nota']:.2f}, acerto no ranking "
                           + ("–" if c.get("winrate") is None else f"{c['winrate']:.0f}%"),
                           {"features": features(c), "nota": c["nota"], "fonte": c["fonte"]})
        self._study_auto_at[pf.user_id] = now
        return {"ok": True, **done}

    async def study_auto_loop(self) -> None:
        await asyncio.sleep(120)
        while True:
            for pf in list(self.engines.values()):
                try:
                    await self.study_auto(pf)
                except Exception as e:
                    log.warning("estudo automático (%s…): %s", pf.user_id[:8], str(e)[:160])
            await asyncio.sleep(1800)

    async def learning_loop(self) -> None:
        while True:
            await asyncio.sleep(1800)
            await self.save_learning()
            await self.refresh_study()

    # ------------------------------------------------------------------ carteiras em estudo (0.14.0)
    def radar_snapshot(self, pf) -> dict:
        enabled = bool(getattr(pf.cfg, "pump_radar_enabled", False))
        wallets = set(getattr(pf, "study", []) or [])
        minimum = int(getattr(pf.cfg, "pump_radar_min_wallets", 2))
        window = int(getattr(pf.cfg, "pump_radar_window_min", 5))
        running = bool(self.running and self.monitor is not None)
        connected = bool(self.market.rpc_status.get("ws"))
        data = (self.radar.snapshot(wallets, minimum, window, connected=running and connected) if enabled else
                {"observed_since": self.radar.observed_since, "event_count": 0, "truncated": False,
                 "callout_policy": callout_policy(minimum), "waves": []})
        for wave in data["waves"]:
            symbol = (self.market.tokens.get(wave["mint"]) or {}).get("symbol")
            wave["symbol"] = str(symbol)[:80] if symbol else None
        # Remoção da lista, janela vencida ou OFF suprimem os estados antigos.
        active = {w["mint"] for w in data["waves"]}
        pf._radar_alerts = {m: s for m, s in getattr(pf, "_radar_alerts", {}).items() if m in active}
        return {"enabled": enabled, "min_wallets": minimum, "window_min": window,
                "wallet_count": len(wallets), **data,
                "monitor": {"running": running, "connected": connected}}

    def _radar_notify(self, wallet: str) -> None:
        for pf in list(self.engines.values()):
            if not getattr(pf.cfg, "pump_radar_enabled", False):
                pf._radar_alerts = {}
                continue
            if wallet not in (getattr(pf, "study", []) or []):
                continue
            data = self.radar_snapshot(pf)
            states = pf._radar_alerts
            for wave in data["waves"]:
                mint = wave["mint"]
                state = states.get(mint)
                name = (wave["symbol"] or mint[:6] + "…" + mint[-4:])
                hot = wave["callout"]["state"] == "hot"
                if state is None:
                    if hot:
                        pf._emit(f"Radar: HOT callout em {name} — {wave['callout']['recent_wallets']} carteiras "
                                 f"distintas entraram em {data['callout_policy']['entry_window_s']} s "
                                 "(apenas observação)")
                    else:
                        pf._emit(f"Radar: onda em {name} — {wave['wallet_count']} carteiras em estudo compraram "
                                 f"em {data['window_min']} min (apenas observação)")
                    state = states[mint] = {"selling": False, "hot_sent": hot}
                elif hot and not state.get("hot_sent", False):
                    pf._emit(f"Radar: HOT callout em {name} — convergência recente de "
                             f"{wave['callout']['recent_wallets']} carteiras distintas (apenas observação)")
                    state["hot_sent"] = True
                if wave["sell_count"] and not state["selling"]:
                    pf._emit(f"Radar: vendas na onda de {name} — uma das carteiras compradoras começou a vender "
                             "(apenas observação)")
                    state["selling"] = True

    def record_trade(self, wallet: str, ev: dict) -> None:
        radar_new = self.radar.record(wallet, ev)
        sig = ev.get("signature")
        if not sig or ev.get("txType") not in ("buy", "sell"):
            return
        bt = ev.get("blockTime")
        try:
            at = datetime.fromtimestamp(float(bt), timezone.utc) if bt else datetime.now(timezone.utc)
            sol, tokens = float(ev.get("solAmount") or 0), float(ev.get("tokenAmount") or 0)
        except (TypeError, ValueError, OverflowError, OSError):
            return
        if not all(math.isfinite(v) and v >= 0 for v in (sol, tokens)):
            return
        self._trade_q.append({"signature": sig, "wallet": wallet, "mint": ev.get("mint"), "side": ev["txType"],
                              "sol": sol, "tokens": tokens,
                              "mcap_sol": ev.get("marketCapSol"), "at": at.isoformat()})
        del self._trade_q[:-5000]                    # banco fora do ar por muito tempo: não estoura a memória
        if radar_new:
            self._radar_notify(wallet)

    async def flush_trades(self) -> None:
        if not self._trade_q:
            return
        batch, self._trade_q = self._trade_q[:500], self._trade_q[500:]
        try:
            # PostgreSQL recusa atualizar a mesma PK duas vezes no mesmo INSERT.
            # O histórico legado admite só uma carteira por assinatura; o Radar
            # mantém os eventos de todas as carteiras separadamente em memória.
            unique = list({row["signature"]: row for row in batch}.values())
            await self.db.insert("wallet_trades", unique, upsert=True, on_conflict="signature")
        except Exception as e:
            self._trade_q = batch + self._trade_q
            log.warning("Carteiras em estudo: operações não gravadas (%s)", str(e)[:120])

    def _study_key(self) -> str:
        own = next((pf.lb_key() for pf in self.engines.values() if pf.lb_key_own()), "")
        return own or self.shared_st_key

    async def refresh_study_wallet(self, wallet: str, force: bool = False) -> str | None:
        """Histórico por token da Solana Tracker (até 200 posições dos últimos 30 dias) → study_positions."""
        from .pumpfun import ST_PNL
        from .study import compact_position
        key = self._study_key()
        if not key:
            return "sem chave da Solana Tracker (histórico só pelo monitor, a partir de agora)"
        if not force and time.time() - self._study_at.get(wallet, 0) < 1500:
            return None
        self._study_at[wallet] = time.time()
        try:
            r = await self.http.get(ST_PNL + wallet + "/positions", params={"limit": 200, "period": "30d"},
                                    headers={"x-api-key": key, "Accept": "application/json"}, timeout=20)
            if r.status_code != 200:
                return f"Solana Tracker HTTP {r.status_code}"
            rows = [c for c in (compact_position(p) for p in (r.json() or {}).get("positions") or []) if c]
        except Exception as e:
            return f"Solana Tracker: {type(e).__name__}"
        now = datetime.now(timezone.utc).isoformat()
        if rows:
            await self.db.insert("study_positions", [{"wallet": wallet, "token": c["token"], "data": c, "atualizado_em": now}
                                                     for c in rows], upsert=True, on_conflict="wallet,token")
        return None

    async def refresh_study(self) -> None:
        for w in sorted({w for pf in self.engines.values() for w in (getattr(pf, "study", []) or [])}):
            try:
                await self.refresh_study_wallet(w)
            except Exception as e:
                log.warning("Carteira em estudo %s…: %s", w[:6], str(e)[:120])

    async def study_set(self, pf, wallet: str, action: str, apelido: str = "") -> dict:
        from .study import MAX_WALLETS
        lst = list(getattr(pf, "study", []) or [])
        if action == "remove":
            await self.db.delete("study_wallets", {"user_id": pf.user_id, "wallet": wallet})
            pf.study = [w for w in lst if w != wallet]
            self.radar_snapshot(pf)
            return {"ok": True}
        if wallet in lst:
            return {"ok": True, "already": True}
        if len(lst) >= MAX_WALLETS:
            return {"error": f"limite de {MAX_WALLETS} carteiras em estudo"}
        await self.db.insert("study_wallets", {"user_id": pf.user_id, "wallet": wallet, "apelido": (apelido or "")[:40] or None},
                             upsert=True, on_conflict="user_id,wallet")
        pf.study = lst + [wallet]
        # o monitor relê watch_set() a cada volta e passa a assinar a carteira nova sozinho
        asyncio.get_running_loop().create_task(self.refresh_study_wallet(wallet, force=True))
        return {"ok": True}

    async def study_share_targets(self, uid: str) -> list[dict]:
        """Para quem dá para compartilhar: nome e e-mail mascarado; nunca a lista completa de e-mails (0.17.1)."""
        out = []
        for p in await self.db.select("profiles", None, order="criado_em.asc", columns="user_id,nome,email,bloqueado,role"):
            # só admin usa as Carteiras em estudo desde a 0.17.4; compartilhar com usuário comum não teria efeito
            if p["user_id"] == uid or p.get("bloqueado") or p.get("role") != "admin":
                continue
            em = str(p.get("email") or "")
            nm, _, dom = em.partition("@")
            out.append({"user_id": p["user_id"], "nome": p.get("nome") or "",
                        "email": (nm[:2] + "***@" + dom) if dom else ""})
        return out

    async def study_share(self, pf, sender: dict, wallet: str, to_uid: str) -> dict:
        """Coloca a carteira (que está no estudo de quem envia) na lista de estudo de outro usuário. Pedido do dono
        em 2026-10-25. Só acrescenta: nunca mexe no que o outro já tem nem copia nada."""
        from .study import MAX_WALLETS
        if wallet not in (getattr(pf, "study", []) or []):
            return {"error": "carteira não está no seu estudo"}
        if to_uid == pf.user_id:
            return {"error": "escolha outro usuário"}
        rows = await self.db.select("profiles", {"user_id": to_uid}, columns="user_id,bloqueado,role")
        if not rows or rows[0].get("bloqueado") or rows[0].get("role") != "admin":
            return {"error": "usuário não encontrado"}
        tem = [r["wallet"] for r in await self.db.select("study_wallets", {"user_id": to_uid}, columns="wallet")]
        if wallet in tem:
            return {"ok": True, "already": True}
        if len(tem) >= MAX_WALLETS:
            return {"error": "a lista dessa pessoa já está cheia"}
        mine = await self.db.select("study_wallets", {"user_id": pf.user_id, "wallet": wallet}, columns="apelido")
        de = "de " + ((sender.get("nome") or sender.get("email") or "").split("@")[0].split(" ")[0] or "outro usuário")
        apelido = ((mine[0].get("apelido") if mine else "") or de)[:40]
        await self.db.insert("study_wallets", {"user_id": to_uid, "wallet": wallet, "apelido": apelido},
                             upsert=True, on_conflict="user_id,wallet")
        other = self.engines.get(to_uid)
        if other is not None and wallet not in (getattr(other, "study", []) or []):
            other.study = list(getattr(other, "study", []) or []) + [wallet]
        await audit(self.db, pf.user_id, "compartilhar carteira em estudo", f"{wallet[:6]}… para {to_uid}")
        await audit(self.db, to_uid, "recebeu carteira em estudo", f"{wallet[:6]}… de {pf.user_id}")
        return {"ok": True}

    async def study_profile(self, wallet: str, prm: dict | None = None) -> dict:
        from .study import profile
        try:
            pos = await self.db.select("study_positions", {"wallet": wallet}, limit=500)
            trades = await self.db.select("wallet_trades", {"wallet": wallet}, order="at.desc", limit=2000)
        except Exception as e:
            return {"error": "tabelas das carteiras em estudo ainda não criadas no banco", "detail": str(e)[:120]}
        return profile(wallet, pos, trades, prm=prm)

    async def start(self) -> None:
        """Carrega todos os usuários (o bot copia mesmo com o painel fechado) e liga as tarefas."""
        try:
            for r in await self.db.select("profiles", None, columns="user_id,bloqueado"):
                if r.get("bloqueado"):
                    self._blocked.add(r["user_id"])
                else:
                    await self.engine(r["user_id"])
        except Exception as e:
            log.warning("Não consegui carregar os usuários do Supabase: %s", str(e)[:160])
        await self.refresh_shared_key()
        await self.load_blacklist()
        await self.load_lab()
        await self.load_elite()
        self.running = True
        for pf in list(self.engines.values()):
            self._start_engine(pf)
        self._tasks.append(asyncio.create_task(self.flush_loop()))
        self._tasks.append(asyncio.create_task(self.learning_loop()))
        self._tasks.append(asyncio.create_task(self.ghosts_loop()))
        self._tasks.append(asyncio.create_task(self.daily_loop()))
        self._tasks.append(asyncio.create_task(self.study_auto_loop()))
        from .monitor import SharedMonitor
        self.monitor = SharedMonitor(self)
        self.monitor.start()

    async def stop(self) -> None:
        if self.monitor:
            self.monitor.stop()
        for t in self._tasks:
            t.cancel()
        for pf in self.engines.values():
            if getattr(pf, "_real_task", None):
                pf._real_task.cancel()
        for pf in list(self.engines.values()):
            try:
                await pf.store.flush()
                await self.save_auto(pf)
            except Exception:
                pass
        try:
            await self.save_ghosts()
            await self.save_lab()
        except Exception:
            pass

    # ------------------------------------------------------------------ gestão de usuários (admin)
    async def unload(self, uid: str) -> None:
        """Tira o motor do usuário da memória (conta bloqueada): para de copiar e a fila real é cancelada."""
        self._blocked.add(uid)                         # antes da trava: cargas em andamento já enxergam o bloqueio
        async with self._locks.setdefault(uid, asyncio.Lock()):
            pf = self.engines.pop(uid, None)
        if pf is None:
            return
        self._stop_engine(pf)
        try:
            await pf.store.flush()
            await self.save_auto(pf)
        except Exception:
            pass

    def user_stats(self, uid: str) -> dict | None:
        pf = self.engines.get(uid)
        if pf is None:
            return None
        w, rw = pf.wallet(), pf.wallet(real=True)
        return {"loaded": True, "copy_enabled": bool(pf.cfg.pump_copy_enabled), "real_enabled": bool(pf.cfg.pump_real_enabled),
                "followed": len(pf.followed), "open": w["open"], "trades": w["count"], "pnl_sol": w["pnl_sol"],
                "win_rate": w["win_rate"], "real_open": rw["open"], "real_trades": rw["count"], "real_pnl_sol": rw["pnl_sol"],
                "keys": pf.keys.configured(), "wallet": bool(pf.sol_wallet and pf.sol_wallet.keypair),
                "db_error": pf.store.last_error, "db_queue": len(pf.store._q)}

    async def admin_users(self) -> list[dict]:
        out = []
        for p in await self.db.select("profiles", None, order="criado_em.asc"):
            uid = p["user_id"]
            out.append({"user_id": uid, "email": p.get("email"), "nome": p.get("nome"), "avatar_url": p.get("avatar_url"),
                        "role": p.get("role") or "user", "bloqueado": bool(p.get("bloqueado")),
                        "criado_em": p.get("criado_em"), "ultimo_acesso": p.get("ultimo_acesso"),
                        "stats": self.user_stats(uid)})
        return out

    async def admin_update_user(self, admin_id: str, uid: str, body: dict) -> dict:
        rows = await self.db.select("profiles", {"user_id": uid})
        if not rows:
            return {"error": "usuário não encontrado"}
        prof, done = rows[0], []
        who = prof.get("email") or uid[:8]
        if "role" in body:
            role = body["role"]
            if role not in ("admin", "user"):
                return {"error": "categoria inválida"}
            if role != prof.get("role"):
                if role == "user":
                    admins = await self.db.select("profiles", {"role": "admin"}, columns="user_id")
                    if len(admins) <= 1:
                        return {"error": "precisa existir pelo menos um admin"}
                await self.db.update("profiles", {"user_id": uid}, {"role": role})
                loaded = self.engines.get(uid)
                if loaded is not None:
                    loaded.role = role
                    if role != "admin":
                        loaded.cfg.pump_ex_auto_on = False
                        await self.save_settings(loaded)
                done.append(f"categoria → {'admin' if role == 'admin' else 'usuário'}")
                if role == "user" and prof.get("role") == "admin":
                    await self.refresh_shared_key()
        if "bloqueado" in body:
            blk = bool(body["bloqueado"])
            if blk and uid == admin_id:
                return {"error": "você não pode bloquear a própria conta"}
            if blk and prof.get("role") == "admin" and "role" not in body:
                return {"error": "tire a categoria admin antes de bloquear"}
            if blk != bool(prof.get("bloqueado")):
                await self.db.update("profiles", {"user_id": uid}, {"bloqueado": blk})
                if blk:
                    await self.unload(uid)
                else:
                    self._blocked.discard(uid)
                    await self.engine(uid)
                done.append("conta BLOQUEADA (parou de copiar)" if blk else "conta desbloqueada")
        if body.get("real_off"):
            pf = self.engines.get(uid)
            if pf is not None and pf.cfg.pump_real_enabled:
                pf.cfg.pump_real_enabled = False
                pf._emit("[PUMP REAL] execução real DESLIGADA pelo administrador")
            done.append("execução real desligada")
        if not done:
            return {"ok": True, "changed": []}
        txt = "; ".join(done)
        await audit(self.db, admin_id, "admin: alterou usuário", f"{who}: {txt}")
        if uid != admin_id:
            await audit(self.db, uid, "alterado pelo administrador", txt)
        log.info("Admin alterou usuário %s…: %s", uid[:8], txt)
        return {"ok": True, "changed": done}

    def admin_status(self) -> dict:
        m = self.market
        return {"users_loaded": len(self.engines), "uptime_s": round(time.time() - self.started_at),
                "real_allowed": self.real_allowed,
                "real_on": sum(1 for p in self.engines.values() if p.cfg.pump_real_enabled),
                "monitor": {"rpc": {k: m.rpc_status.get(k) for k in ("ws", "error", "subs", "parsed", "notifs",
                                                                       "tx_errors", "price_at", "price_error")},
                            "pumpportal": {k: m.status.get(k) for k in ("ws", "error", "new_tokens")},
                            "jupiter": m.jup.status if m.jup else None, "sol_usd": m.sol_usd,
                            "tokens": len(m.tokens), "wallets_seen": len(m.wallets)},
                "shared_st_key": bool(self.shared_st_key),
                "system_keys": {k: bool(self.system_keys.get(k)) for k in SYSTEM_NAMES},
                "db_errors": [{"user": uid[:8] + "…", "error": p.store.last_error, "queued": len(p.store._q)}
                              for uid, p in self.engines.items() if p.store.last_error or len(p.store._q) > 50]}
