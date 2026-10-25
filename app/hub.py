"""Central dos usuários: um motor de cópia (PumpFun) por usuário, todos ligados ao MESMO mercado público.

Cada motor tem: configuração própria, dados próprios (SupabaseStore), chaves próprias (KeyRing, já abertas só na
memória) e carteira/execução real próprias (desligada ao iniciar).
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone

from .db import SupabaseStore, Vault, audit
from .jupiter import JupiterQuoter, JupiterWallet
from .keystore import KeyRing
from .pumpfun import PumpFun, PumpMarket, PumpReal
from .settings import PumpSettings
from .solana_wallet import UserWallet

log = logging.getLogger("hub")


class PumpHub:
    def __init__(self, cfg, http, db, box):
        self.cfg, self.http, self.db = cfg, http, db
        self.vault = Vault(db, box)
        self.market = PumpMarket(jup=JupiterQuoter(http))
        self.engines: dict[str, PumpFun] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._tasks: list[asyncio.Task] = []
        self.shared_st_key = ""                    # chave da Solana Tracker emprestada pelo admin
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
        pf = self.engines.get(uid)
        if pf is not None:
            return pf
        lock = self._locks.setdefault(uid, asyncio.Lock())
        async with lock:
            pf = self.engines.get(uid)
            if pf is None:
                pf = await self._load(uid)
                self.engines[uid] = pf
        return pf

    async def _load(self, uid: str) -> PumpFun:
        rows = await self.db.select("user_settings", {"user_id": uid})
        saved = (rows[0].get("settings") if rows else None) or {}
        cfg = PumpSettings(saved, self.cfg.defaults)          # pump_real_enabled sempre False aqui
        store = SupabaseStore(self.db, uid)
        await store.load()
        pf = PumpFun(cfg, store, self.http, None, market=self.market)
        pf.user_id = uid
        pf.keys = KeyRing(await self.vault.load(uid))
        pf.lb_key_fallback = lambda: self.shared_st_key
        self._wire_wallet(pf)
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
        jw = JupiterWallet(self.http, w, self.market.jup, priority_sol=float(pf.cfg.pump_priority_sol))
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
        """Chave da Solana Tracker do admin, se ele marcou "compartilhar com todos"."""
        try:
            rows = await self.db.select("user_settings", {"compartilhar_chave_st": True})
            admins = {r["user_id"] for r in await self.db.select("profiles", {"role": "admin"})}
            key = ""
            for r in rows:
                if r["user_id"] in admins:
                    pf = await self.engine(r["user_id"])
                    key = pf.keys.get("solanatracker_api_key") or key
            self.shared_st_key = key
        except Exception as e:
            log.warning("Chave compartilhada: %s", str(e)[:120])

    # ------------------------------------------------------------------ segundo plano
    async def flush_loop(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            for pf in list(self.engines.values()):
                try:
                    await pf.store.flush()
                except Exception as e:
                    log.warning("flush: %s", str(e)[:120])

    async def start(self) -> None:
        """Carrega todos os usuários (o bot copia mesmo com o painel fechado) e liga as tarefas."""
        try:
            for r in await self.db.select("profiles", None, columns="user_id,bloqueado"):
                if not r.get("bloqueado"):
                    await self.engine(r["user_id"])
        except Exception as e:
            log.warning("Não consegui carregar os usuários do Supabase: %s", str(e)[:160])
        await self.refresh_shared_key()
        self.running = True
        for pf in list(self.engines.values()):
            self._start_engine(pf)
        self._tasks.append(asyncio.create_task(self.flush_loop()))
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
            except Exception:
                pass

    # ------------------------------------------------------------------ gestão de usuários (admin)
    async def unload(self, uid: str) -> None:
        """Tira o motor do usuário da memória (conta bloqueada): para de copiar e a fila real é cancelada."""
        pf = self.engines.pop(uid, None)
        if pf is None:
            return
        pf.cfg.pump_real_enabled = False
        t = getattr(pf, "_real_task", None)
        if t:
            t.cancel()
        try:
            await pf.store.flush()
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
                "db_errors": [{"user": uid[:8] + "…", "error": p.store.last_error, "queued": len(p.store._q)}
                              for uid, p in self.engines.items() if p.store.last_error or len(p.store._q) > 50]}
