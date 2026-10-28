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
        self._tune_at: dict[str, float] = {}        # usuário -> última volta do ajuste automático (0.31.14)
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
            data = (rows[0].get("data") if rows else None) or {}
            pf.ghosts.load(data)
            pf.ghosts_auto.load(data.get("auto"))
            pf._ex_funnel = dict(data.get("funil") or {})             # 0.31.41: funil do Explorar sobrevive ao reinício
        except Exception:
            pass
        self._wire_wallet(pf)
        pf.tg = lambda msg, _pf=pf: self.tg_queue(_pf, msg)
        pf.follow_user = str(saved.get("_follow_user") or "")        # 0.31.61: copiar os trades de outro usuário
        pf.brain_freeze = saved.get("_brain_freeze") if isinstance(saved.get("_brain_freeze"), dict) else None   # 0.31.85
        pf.leader_hook = lambda ev, p, why="", _pf=pf: self._on_leader(_pf, ev, p, why)
        pf.learn_pool = lambda _pf=pf: self._learn_pool(_pf)                 # 0.31.63: aprendizado geral
        pf.shadow_hook = self.shadow_note                                     # 0.31.72: entradas sombra
        # 0.31.28 (pedido do dono em 2026-10-27): o real ligado pelo usuário continua ligado depois de reiniciar o
        # servidor (cada versão nova reinicia). Antes desligava em todo deploy e parecia "desligar sozinho". Só volta
        # com a trava geral liberada, a carteira configurada e a conta liberada; desligar (usuário, admin, remover a
        # carteira) grava OFF.
        if saved.get("_real_on") and self.real_allowed and pf.sol_wallet and pf.sol_wallet.keypair and uid not in self._blocked:
            pf.cfg.pump_real_enabled = True
            pf._emit("[PUMP REAL] execução real continua LIGADA depois do reinício do servidor (ligada por você)")
            await audit(self.db, uid, "execução real religada após reinício", f"máx. {pf.cfg.pump_real_max_sol} SOL por compra")
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

    def ghosts_merged(self, pf: PumpFun, kind: str = "ghosts", trades: list | None = None) -> dict:
        """0.31.64 (pedido do dono: "tudo geral, uma base para todos"): Estratégias fantasma com os resultados de TODAS as
        contas somados por regra de saída (n_sua × n_conhecimento). "Suas regras atuais" continua sendo só a sua conta,
        para comparar por trade. É o que a tela e o Ajuste automático usam."""
        from .ghosts import _ts
        me = getattr(pf, kind)
        snap = me.snapshot(pf.trades(100000) if trades is None else trades)
        others = [getattr(e, kind) for e in list(self.engines.values()) if e is not pf and getattr(e, kind, None) is not None]
        sinces = [x for x in [me.since] + [g.since for g in others] if x]
        if sinces:
            snap["since"] = min(sinces, key=lambda s: _ts(s) or 0)
        rows = []
        for r in snap["variants"]:
            tot = {"trades": 0, "wins": 0, "pnl_sol": 0.0, "invested_sol": 0.0, "best_sum": 0.0}
            for g in [me] + others:
                s = g.stats.get(r["id"]) or {}
                for k in tot:
                    tot[k] += s.get(k, 0) or 0
            n = tot["trades"]
            rows.append(dict(r, trades=n, win_rate=(tot["wins"] / n) if n else None, pnl_sol=round(tot["pnl_sol"], 6),
                             roi_pct=round(tot["pnl_sol"] / tot["invested_sol"] * 100, 2) if tot["invested_sol"] else None,
                             avg_best_pct=round(tot["best_sum"] / n, 1) if n else None,
                             n_sua=(me.stats.get(r["id"]) or {}).get("trades", 0), n_conhecimento=n - (me.stats.get(r["id"]) or {}).get("trades", 0),
                             avg_sol=round(tot["pnl_sol"] / n, 6) if n else None))
        snap["variants"] = rows
        ranked = sorted([r for r in rows if r["trades"]], key=lambda r: -(r["avg_sol"] or 0))
        snap["best"] = ranked[0]["id"] if ranked else None
        snap["geral"] = True
        return snap

    def api_usage_view(self) -> list:
        """0.31.76: uso das APIs com o nome da chave da Solana Tracker (do sistema ou de quem é a chave pessoal)."""
        from .apiusage import Usage, key_tag
        us = getattr(self, "usage", None) or Usage()
        labels = {}
        if self.system_keys.get("solanatracker_api_key"):
            labels[key_tag(self.system_keys["solanatracker_api_key"])] = "chave do sistema"
        for e in list(self.engines.values()):
            k = e.keys.get("solanatracker_api_key") if getattr(e, "keys", None) else None
            if k and key_tag(k) not in labels:
                labels[key_tag(k)] = "chave pessoal de " + (getattr(e, "_nome_cache", None) or e.user_id[:8])
        return us.view(labels)

    async def usage_loop(self) -> None:
        from .apiusage import Usage
        us = self.__dict__.setdefault("usage", Usage())
        try:
            from datetime import datetime as _dt
            us.load(await self.db.select("api_usage", {"mes": _dt.now(timezone.utc).strftime("%Y-%m")}))
        except Exception as e:
            log.warning("uso das APIs não carregou: %s", str(e)[:120])
        while True:
            await asyncio.sleep(300)
            if not us.dirty:
                continue
            try:
                await self.db.insert("api_usage", [dict(r, atualizado_em=datetime.now(timezone.utc).isoformat()) for r in us.dump()],
                                     upsert=True, on_conflict="mes,api,chave")
                us.dirty = False
            except Exception as e:
                log.warning("uso das APIs não gravou: %s", str(e)[:120])

    def base_state(self, pf: PumpFun | None = None) -> dict:
        """0.31.71: o "cérebro" do robô — aprender com os erros + fantasmas das automáticas, de todas as contas."""
        from .autolearn import MAX_AVG_PCT, MAX_WR, MIN_N
        from .basegeral import history_days, maturity, state_summary, upcoming
        from .ghosts import _ts as gts
        pf = pf or next(iter(self.engines.values()), None)
        if pf is None:
            return {"error": "nenhuma conta carregada"}
        learned = pf.learned("explorar")
        ghosts = self.ghosts_merged(pf, "ghosts_auto")
        gdays = (time.time() - (gts(ghosts.get("since")) or time.time())) / 86400
        pool = [t for t in pf.learn_trades() if t.get("origem") == "explorar"]
        n = len(pool)
        wins = sum(1 for t in pool if (t.get("pnl_sol") or 0) > 0)
        pnl = sum(t.get("pnl_sol") or 0 for t in pool)
        from .autolearn import study_extra
        from .basegeral import filters_study, verdict_study
        from .raiox import study as xray_study
        return {"learned": learned, "ghosts": ghosts, "ghost_days": round(gdays, 2), "sinais": study_extra(pool),
                "veredito": verdict_study(self.__dict__.get("shadows") or {}, self.SHADOW_COST_PCT),
                "raiox": xray_study(self.__dict__.get("_xray") or {}, self.xray_outcomes()),
                "raiox_n": len(self.__dict__.get("_xray") or {}),
                "filtros": filters_study(self.__dict__.get("shadows") or {}, self.SHADOW_COST_PCT),
                "maturidade": maturity(learned, ghosts, history_days(pool), gdays),
                "por_vir": upcoming(learned, ghosts, gdays, MIN_N, MAX_WR, MAX_AVG_PCT),
                "resumo": dict(state_summary(learned, ghosts), acerto=round(wins / n, 3) if n else None,
                               media_trade=round(pnl / n, 6) if n else None, resultado=round(pnl, 6),
                               contas=len(self.engines), dias=history_days(pool))}

    async def base_tick(self) -> None:
        """Foto da base (gráfico) + log do que mudou desde a foto anterior. A cada 30 min (base_loop)."""
        from .basegeral import diff
        st = self.base_state()
        if st.get("error"):
            return
        cur = dict(st["resumo"], maturidade=st["maturidade"]["total"])
        prev = getattr(self, "_base_prev", None)
        if prev is None:
            try:
                rows = await self.db.select("base_snapshots", None, order="em.desc", limit=1)
                prev = (rows[0].get("data") if rows else None) or None
            except Exception:
                prev = None
        diffs = diff(prev, cur)
        for tipo, texto in diffs:
            await self.db.insert("base_log", {"tipo": tipo, "texto": texto, "data": {"maturidade": cur["maturidade"]}})
        await self.db.insert("base_snapshots", {"data": cur})
        self._base_prev = cur
        # 0.31.85: cada mudança do cérebro vira uma evolução numerada (E1, E2…) com a foto das faixas bloqueadas
        from .evolucoes import estado
        last = await self.db.select("base_evolutions", None, order="numero.desc", limit=1)
        mud = [texto for tipo, texto in diffs if tipo in ("bloqueou", "liberou", "melhor_regra")]
        if not last or mud:
            await self.db.insert("base_evolutions", {
                "numero": (last[0]["numero"] + 1) if last else 1, "em": datetime.now(timezone.utc).isoformat(),
                "estado": estado(st["learned"], cur.get("melhor_regra")),
                "mudancas": mud or [f"Começo do registro das evoluções: {len(cur.get('bloqueadas') or [])} faixa(s) bloqueada(s), "
                                    f"melhor regra de saída: {cur.get('melhor_regra') or '—'}."]})

    # ------------------------------------------------------------------ evoluções do cérebro (0.31.85)
    async def evo_list(self, pf: PumpFun) -> dict:
        from .auto_trades import ts
        from .evolucoes import relatorio
        rows = await self.db.select("base_evolutions", None, order="numero.asc", limit=1000)
        trades, real = pf.learn_trades(), [t for t in pf.trades(100000) if t.get("real")]
        out = []
        for i, r in enumerate(rows):
            ini = ts(r.get("em")) or 0
            fim = ts(rows[i + 1].get("em")) if i + 1 < len(rows) else None
            rep = relatorio(trades, ini, fim, real=real)
            out.append({"numero": r["numero"], "em": r.get("em"), "ate": rows[i + 1].get("em") if i + 1 < len(rows) else None,
                        "mudancas": r.get("mudancas") or [], "bloqueios": len((r.get("estado") or {}).get("bloqueios") or []),
                        "melhor_regra": (r.get("estado") or {}).get("melhor_regra"),
                        **{k: rep[k] for k in ("operacoes", "acerto", "lucro_sol", "por_trade", "sombras", "real_operacoes", "real_lucro_sol")}})
        return {"evolucoes": list(reversed(out)), "congelado": pf.brain_freeze}

    async def evo_report(self, pf: PumpFun, numero: int) -> dict:
        from .auto_trades import ts
        from .evolucoes import relatorio
        rows = await self.db.select("base_evolutions", None, order="numero.asc", limit=1000)
        idx = next((i for i, r in enumerate(rows) if r.get("numero") == numero), None)
        if idx is None:
            return {"error": "evolução não encontrada"}
        r = rows[idx]
        ini = ts(r.get("em")) or 0
        fim = ts(rows[idx + 1].get("em")) if idx + 1 < len(rows) else None
        ajustes = await self.db.select("auto_tune_log", {"user_id": pf.user_id}, order="em.desc", limit=500)
        rep = relatorio(pf.learn_trades(), ini, fim, r.get("mudancas"), ajustes, [t for t in pf.trades(100000) if t.get("real")])
        return dict(rep, numero=numero, em=r.get("em"), ate=rows[idx + 1].get("em") if idx + 1 < len(rows) else None,
                    estado=r.get("estado") or {})

    async def evo_rollback(self, pf: PumpFun, numero: int) -> dict:
        """Volta o cérebro desta conta para a evolução: faixas bloqueadas daquela foto e regras de saída de antes dos
        ajustes automáticos feitos depois dela. O Ajuste automático fica parado até "Voltar ao automático"."""
        from .auto_trades import ts
        from .evolucoes import reverter_ajustes
        rows = await self.db.select("base_evolutions", {"numero": numero}, limit=1)
        if not rows:
            return {"error": "evolução não encontrada"}
        r = rows[0]
        log_rows = await self.db.select("auto_tune_log", {"user_id": pf.user_id}, order="em.desc", limit=500)
        back = reverter_ajustes([x for x in log_rows if x.get("tipo") in ("saida", "saida_auto")], ts(r.get("em")) or 0)
        if back:
            pf.cfg.apply(back)
        pf.brain_freeze = {"numero": numero, "em": r.get("em"), "desde": datetime.now(timezone.utc).isoformat(),
                           "bloqueios": list((r.get("estado") or {}).get("bloqueios") or [])}
        await self.save_settings(pf)
        await audit(self.db, pf.user_id, "base geral: voltou para evolução",
                    f"E{numero} · {len(pf.brain_freeze['bloqueios'])} faixa(s) bloqueada(s)" + (f" · saída restaurada: {', '.join(sorted(back))}" if back else ""))
        pf._emit(f"Base geral: cérebro voltou para a evolução E{numero} (Ajuste automático parado até voltar ao automático)")
        return {"ok": True, "numero": numero, "saida_restaurada": sorted(back)}

    async def evo_auto(self, pf: PumpFun) -> dict:
        was = (pf.brain_freeze or {}).get("numero")
        pf.brain_freeze = None
        await self.save_settings(pf)
        await audit(self.db, pf.user_id, "base geral: voltou ao automático", f"saiu da E{was}" if was else "já estava no automático")
        pf._emit("Base geral: cérebro de volta ao automático (aprende e aplica sozinho)")
        return {"ok": True}

    async def base_loop(self) -> None:
        await asyncio.sleep(180)
        while True:
            try:
                await self.base_tick()
            except Exception as e:
                log.warning("base geral: %s", str(e)[:160])
            await asyncio.sleep(1800)

    def _learn_pool(self, me: PumpFun) -> list:
        """0.31.63: trades automáticos fechados de TODAS as contas (os da própria conta marcados como seus)."""
        out = []
        for e in list(self.engines.values()):
            mine = e is me
            out += [(mine, dict(t, _conta=e.user_id)) for t in e.trades(100000) if t.get("origem") in AUTO_ORIGINS and not t.get("real")]
        out += [(False, t) for t in self.shadow_trades()]                    # 0.31.72: o que teria acontecido
        return out

    # ------------------------------------------------------------------ entradas sombra (0.31.72)
    SHADOW_S = 900                 # o resultado da sombra é o preço 15 min depois de o Explorar barrar o token
    SHADOW_COST_PCT = 4.0          # taxas + slippage de uma compra e uma venda, aproximado
    SHADOW_SOL = 0.05

    def shadow_note(self, row: dict, why: str, t: float) -> None:
        """Token "chance alta" que alguma conta barrou: guarda os números do momento (uma vez por token, 24 h)."""
        sh = self.__dict__.setdefault("shadows", {})
        mint = row.get("mint")
        if not mint or (mint in sh and t - sh[mint].get("t0", 0) < 86400):
            return
        info = {k: copy.deepcopy(row.get(k)) for k in ("pressure", "holders", "curve_pct", "risk", "chg_5m", "boost")}
        from .explore import extra_info
        info.update(extra_info(row, self.market.tokens.get(mint) if hasattr(self.market, "tokens") else {}, t))   # 0.31.81
        sh[mint] = {"t0": t, "symbol": row.get("symbol"), "why": str(why)[:160], "info": info,
                    "veredito": (row.get("pred") or {}).get("verdict"),               # 0.31.86: estudo do veredito
                    "px0": (self.market.tokens.get(mint) or {}).get("price") if hasattr(self.market, "tokens") else None}

    def shadow_trades(self) -> list[dict]:
        from datetime import datetime as _dt
        out = []
        for mint, s in list((self.__dict__.get("shadows") or {}).items()):
            if s.get("ret") is None or s.get("veredito") not in (None, "chance alta"):
                continue
            pct = round(s["ret"] - self.SHADOW_COST_PCT, 2)
            out.append({"mint": mint, "symbol": s.get("symbol"), "origem": "explorar", "auto": True, "sombra": True,
                        "auto_info": s.get("info") or {}, "pnl_pct": pct, "pnl_sol": round(self.SHADOW_SOL * pct / 100, 6),
                        "opened_at": _dt.fromtimestamp(s["t0"], timezone.utc).isoformat(),
                        "closed_at": _dt.fromtimestamp(s["t0"] + self.SHADOW_S, timezone.utc).isoformat(), "reason": "sombra: " + s.get("why", "")})
        return out

    async def shadow_tick(self, now: float | None = None) -> int:
        """Preço de entrada (até 2 min) e de 15 min das sombras; grava as prontas. Sem preço no prazo: descarta (N/D)."""
        from .auto_trades import SUSPECT_PCT
        now = time.time() if now is None else now
        sh = self.__dict__.setdefault("shadows", {})
        svc = getattr(self.monitor, "svc", None) if self.monitor else None
        need = [m for m, s in sh.items() if s.get("ret") is None and ((s.get("px0") is None and now - s["t0"] <= 120)
                                                                      or (s.get("px0") and now - s["t0"] <= self.SHADOW_S + 1800))]
        if need and svc is not None:
            pump = [m for m in need if svc.is_pump(m)]
            rest = await svc._curve_prices(pump, public_first=True) if pump else []
            rest += [m for m in need if m not in pump]
            if rest:
                await svc._fetch_prices(list(dict.fromkeys(rest)))
        done = 0
        for m, s in list(sh.items()):
            px = (self.market.tokens.get(m) or {}).get("price") if hasattr(self.market, "tokens") else None
            if s.get("ret") is not None:
                continue
            if s.get("px0") is None:
                if px and now - s["t0"] <= 120:
                    s["px0"] = px
                elif now - s["t0"] > 120:
                    sh.pop(m, None)
                continue
            if px and s.get("px0"):
                s["pico"] = round(max(s.get("pico") or -100.0, (px / s["px0"] - 1) * 100), 2)    # 0.31.86: pico em 15 min
            if now - s["t0"] >= self.SHADOW_S:
                if px:
                    r = (px / s["px0"] - 1) * 100
                    if r >= SUSPECT_PCT:
                        sh.pop(m, None)
                        continue
                    s["ret"] = round(r, 2)
                    done += 1
                    try:
                        await self.db.insert("base_shadows", {"mint": m, "data": s}, upsert=True, on_conflict="mint")
                    except Exception as e:
                        log.warning("sombra não gravou: %s", str(e)[:120])
                elif now - s["t0"] > self.SHADOW_S + 1800:
                    sh.pop(m, None)
        return done

    async def shadow_loop(self) -> None:
        await asyncio.sleep(60)
        while True:
            try:
                await self.shadow_tick()
            except Exception as e:
                log.warning("entradas sombra: %s", str(e)[:160])
            await asyncio.sleep(60)

    # ------------------------------------------------------------------ log de análise dos robôs (0.31.89)
    RLOG_NAMES = {"copia": "Cópia de traders", "base": "Base da pump.fun (compra automática)", "elite": "Maiores traders (compra automática)"}

    async def rlog_flush(self) -> int:
        n = 0
        for pf in list(self.engines.values()):
            for rec in pf.rlog_pending():
                try:
                    await self.db.insert("robot_log", {"id": f"{pf.user_id}:{rec['mod']}:{int(rec['ini'])}", "user_id": pf.user_id,
                                                       "modulo": rec["mod"], "em": datetime.fromtimestamp(rec["ini"], timezone.utc).isoformat(),
                                                       "data": rec}, upsert=True, on_conflict="id")
                    n += 1
                except Exception as e:
                    log.warning("log dos robôs não gravou: %s", str(e)[:120])
        return n

    async def rlog_loop(self) -> None:
        while True:
            await asyncio.sleep(60)
            try:
                await self.rlog_flush()
            except Exception as e:
                log.warning("log dos robôs: %s", str(e)[:160])

    async def robot_log(self, pf: PumpFun, mod: str, hours: float = 24) -> dict:
        import re
        since = datetime.fromtimestamp(time.time() - hours * 3600, timezone.utc).isoformat()
        rows = await self.db.select("robot_log", {"user_id": pf.user_id, "modulo": mod}, order="em.desc", limit=600, gte={"em": since})
        blocos = [dict(r.get("data") or {}, em=r.get("em")) for r in rows]
        mot: dict[str, list] = {}
        for b in blocos:
            for m in b.get("motivos") or []:
                k = re.sub(r"[-+]?\d+(?:[.,]\d+)?", "#", m["motivo"])[:90]
                mot.setdefault(k, [0, m["motivo"]])[0] += m["n"]
        tot = sum(v[0] for v in mot.values()) or 1
        resumo = {"blocos": len(blocos), "analisados": sum(b.get("analisados") or 0 for b in blocos),
                  "entradas": sum(len(b.get("entrou") or []) for b in blocos),
                  "nomes": sorted({s for b in blocos for s in b.get("entrou") or []})[:20],
                  "motivos": sorted(({"motivo": v[1], "n": v[0], "pct": round(v[0] / tot * 100, 1)} for v in mot.values()), key=lambda m: -m["n"])[:10],
                  "ligado": {"copia": bool(getattr(pf.cfg, "pump_copy_enabled", True)), "base": bool(getattr(pf.cfg, "pump_auto_on", False)),
                             "elite": bool(getattr(pf.cfg, "pump_el_auto_on", False))}.get(mod)}
        return {"modulo": mod, "nome": self.RLOG_NAMES.get(mod, mod), "blocos": blocos[:288], "resumo": resumo}

    # ------------------------------------------------------------------ log de análise do Explorar (0.31.88)
    async def explore_cycle_save(self, pf: PumpFun, rec: dict) -> None:
        try:
            em = datetime.fromtimestamp(float(rec["lista_em"]), timezone.utc).isoformat()
            await self.db.insert("explore_cycles", {"id": f"{pf.user_id}:{int(float(rec['lista_em']))}", "user_id": pf.user_id,
                                                    "em": em, "data": rec}, upsert=True, on_conflict="id")
        except Exception as e:
            log.warning("log do Explorar não gravou: %s", str(e)[:120])

    async def explore_log(self, pf: PumpFun, hours: float = 24) -> dict:
        """Ciclos salvos desta conta + resumo das últimas `hours` + o que cada filtro barrou (sombras)."""
        from .basegeral import filters_study
        since = datetime.fromtimestamp(time.time() - hours * 3600, timezone.utc).isoformat()
        rows = await self.db.select("explore_cycles", {"user_id": pf.user_id}, order="em.desc", limit=400, gte={"em": since})
        cyc = [dict(r.get("data") or {}, em=r.get("em")) for r in rows]
        mot: dict[str, int] = {}
        ex: dict[str, str] = {}
        for c in cyc:
            for m in c.get("motivos") or []:
                import re
                k = re.sub(r"[-+]?\d+(?:[.,]\d+)?", "#", m["motivo"])[:90]
                mot[k] = mot.get(k, 0) + m["n"]
                ex.setdefault(k, m["motivo"])
        tot = sum(mot.values()) or 1
        resumo = {"ciclos": len(cyc), "analisados": sum(c.get("analisados") or 0 for c in cyc),
                  "sem_preco": sum(c.get("sem_preco") or 0 for c in cyc), "chance_alta": sum(c.get("chance_alta") or 0 for c in cyc),
                  "entradas": sorted({s for c in cyc for s in c.get("entrou") or []}),
                  "motivos": sorted(({"motivo": ex[k], "n": n, "pct": round(n / tot * 100, 1)} for k, n in mot.items()), key=lambda m: -m["n"])[:10],
                  "ligado": bool(getattr(pf.cfg, "pump_ex_auto_on", False)),
                  "lista_erro": getattr(getattr(self, "explore", None), "error", None)}
        return {"ciclos": cyc[:200], "resumo": resumo, "filtros": filters_study(self.__dict__.get("shadows") or {}, self.SHADOW_COST_PCT)}

    # ------------------------------------------------------------------ Raio-X do token (0.31.86)
    XRAY_TTL = 6 * 3600            # refaz no máximo a cada 6 h por token
    XRAY_AUTO_DAY = 10             # automáticos por dia (1 crédito da Solana Tracker cada)

    def _xray_key(self, pf: PumpFun | None = None) -> str:
        if pf is not None and pf.lb_key_own():
            return pf.lb_key()
        return next((e.lb_key() for e in self.engines.values() if e.lb_key_own()), "") or getattr(self, "shared_st_key", "")

    async def xray(self, pf: PumpFun | None, mint: str, force: bool = False) -> dict:
        from .raiox import PAGE, TRADES_URL, analyze, parse
        cache = self.__dict__.setdefault("_xray", {})
        hit = cache.get(mint)
        if hit and not force and time.time() - (hit.get("feito") or 0) < self.XRAY_TTL:
            return hit
        key = self._xray_key(pf)
        if not key:
            return {"error": "precisa da chave da Solana Tracker (pessoal ou do sistema)"}
        try:
            r = await self.http.get(TRADES_URL + mint, params={"limit": PAGE, "sortDirection": "ASC"},
                                    headers={"x-api-key": key, "Accept": "application/json"}, timeout=20)
            if r.status_code != 200:
                return {"error": f"Solana Tracker respondeu HTTP {r.status_code}"}
            rep = analyze(parse(r.json()))
        except Exception as e:
            return {"error": "Raio-X falhou: " + str(e)[:120]}
        tk = self.market.tokens.get(mint) or {}
        rep.update(mint=mint, symbol=tk.get("symbol"), feito=time.time())
        cache[mint] = rep
        try:
            await self.db.insert("token_xray", {"mint": mint, "em": datetime.now(timezone.utc).isoformat(), "data": rep},
                                 upsert=True, on_conflict="mint")
        except Exception as e:
            log.warning("raio-x não gravou: %s", str(e)[:120])
        return rep

    async def load_xrays(self) -> None:
        try:
            rows = await self.db.select("token_xray", None, order="em.desc", limit=3000)
            cache = self.__dict__.setdefault("_xray", {})
            for r in rows:
                if isinstance(r.get("data"), dict):
                    cache.setdefault(r["mint"], r["data"])
        except Exception as e:
            log.warning("raio-x não carregou: %s", str(e)[:120])

    def xray_outcomes(self) -> dict:
        """Resultado de cada token para cruzar com o Raio-X: operação do Explorar (base geral) ou sombra medida."""
        out = {}
        for s_mint, s in (self.__dict__.get("shadows") or {}).items():
            if s.get("ret") is not None:
                out[s_mint] = {"pnl_pct": s["ret"] - self.SHADOW_COST_PCT, "sombra": True}
        for e in list(self.engines.values()):
            for t in e.trades(100000):
                if t.get("origem") == "explorar" and not t.get("real") and t.get("mint"):
                    out[t["mint"]] = {"pnl_pct": t.get("pnl_pct"), "sombra": False}
        return out

    async def xray_auto_once(self, now: float | None = None) -> int:
        """Raio-X automático (até XRAY_AUTO_DAY por dia): operações do Explorar fechadas nas últimas 24 h e barrados que
        subiram 50%+ (pico das sombras)."""
        from .auto_trades import ts
        now = time.time() if now is None else now
        day = int(now // 86400)
        cnt = self.__dict__.setdefault("_xray_day", {})
        cache = self.__dict__.setdefault("_xray", {})
        if cnt.get(day, 0) >= self.XRAY_AUTO_DAY or not self._xray_key():
            return 0
        cand = []
        for e in list(self.engines.values()):
            cand += [t["mint"] for t in e.trades(500) if t.get("origem") == "explorar" and not t.get("real") and t.get("mint")
                     and now - (ts(t.get("closed_at")) or 0) < 86400]
        cand += [m for m, s in (self.__dict__.get("shadows") or {}).items() if (s.get("pico") or 0) >= 50 and now - s.get("t0", 0) < 86400]
        done = 0
        for m in dict.fromkeys(cand):
            if m in cache or cnt.get(day, 0) >= self.XRAY_AUTO_DAY:
                continue
            r = await self.xray(None, m)
            cnt[day] = cnt.get(day, 0) + 1
            done += 0 if r.get("error") else 1
        return done

    async def xray_loop(self) -> None:
        await asyncio.sleep(600)
        await self.load_xrays()
        while True:
            try:
                await self.xray_auto_once()
            except Exception as e:
                log.warning("raio-x automático: %s", str(e)[:160])
            await asyncio.sleep(1800)

    async def load_shadows(self) -> None:
        try:
            from datetime import datetime as _dt
            since = _dt.fromtimestamp(time.time() - 30 * 86400, timezone.utc).isoformat()
            rows = await self.db.select("base_shadows", None, order="em.desc", limit=40000, gte={"em": since})
            sh = self.__dict__.setdefault("shadows", {})
            for r in rows:
                if isinstance(r.get("data"), dict):
                    sh.setdefault(r["mint"], r["data"])
        except Exception as e:
            log.warning("entradas sombra não carregaram: %s", str(e)[:120])

    def _on_leader(self, leader: PumpFun, ev: str, p: dict, why: str = "") -> None:
        """0.31.61 (pedido do dono: "o que o Bruxo faz tem que acontecer no Pedro"): quando a conta seguida abre uma posição
        fictícia, cada conta que copia os trades dela abre a MESMA (mesmo token, mesmo valor, mesmas regras de saída); quando
        fecha, fecha junto. A real de quem copia segue o espelho dela (com o valor e os limites da carteira real dela)."""
        for pf2 in list(self.engines.values()):
            if pf2 is leader or getattr(pf2, "follow_user", "") != leader.user_id or pf2.user_id in self._blocked:
                continue
            nome = getattr(leader, "_nome_cache", None) or leader.user_id[:8]
            try:
                if ev == "open":
                    tk = pf2.tokens.setdefault(p["mint"], {})
                    if not tk.get("price") and p.get("price_now"):
                        tk.update(price=p["price_now"], last_t=time.time(), symbol=p.get("symbol"))
                    rules = {k: p[k] for k in PumpFun.FOLLOW_RULES if k in p}
                    r = pf2.manual_buy(p["mint"], auto=f"copiou a conta {nome}",
                                       follow={"sol": p.get("sol_in"), "rules": rules, "leader": leader.user_id, "pos": p["id"], "nome": nome})
                    if r.get("error") or (r.get("sim") and not str(r["sim"]).startswith("comprou")):
                        pf2._emit(f"[PUMP SIM] não copiou {p.get('symbol')} da conta {nome}: {r.get('error') or r.get('sim')}")
                elif ev == "close":
                    for q in pf2.positions():
                        if not q.get("real") and (q.get("follow_of") or {}).get("pos") == p["id"] and (q.get("follow_of") or {}).get("user") == leader.user_id:
                            px = (pf2.tokens.get(q["mint"]) or {}).get("price") or p.get("price_now")
                            msg = pf2._sell(q, 1.0, px, f"a conta {nome} fechou: {why}", time.time())
                            if msg:
                                pf2._emit(msg)
            except Exception as e:
                log.warning("copiar trades %s → %s: %s", leader.user_id[:8], pf2.user_id[:8], str(e)[:160])

    async def follow_set(self, pf: PumpFun, target: str) -> dict:
        target = (target or "").strip()
        if target:
            if target == pf.user_id:
                return {"error": "não dá para copiar a própria conta"}
            if target not in self.engines or target in self._blocked:
                return {"error": "usuário não encontrado ou bloqueado"}
            other = self.engines[target]
            if getattr(other, "follow_user", "") == pf.user_id:
                return {"error": "essa pessoa já copia os seus trades (cópia em círculo não é permitida)"}
            other._nome_cache = await self._nome(target)
        pf.follow_user = target
        await self.save_settings(pf)
        await audit(self.db, pf.user_id, "copiar trades de outro usuário", (await self._nome(target)) if target else "desligado")
        pf._emit(f"[PUMP SIM] copiar os trades de {(await self._nome(target)) if target else '—'}: {'LIGADO' if target else 'DESLIGADO'}")
        return {"ok": True, "follow_user": target, "nome": (await self._nome(target)) if target else ""}

    async def save_settings(self, pf: PumpFun) -> None:
        s = pf.cfg.user_dict()
        if getattr(pf.cfg, "pump_real_enabled", False):
            s["_real_on"] = True                       # 0.31.28: o real ligado sobrevive ao reinício (ver _load)
        if getattr(pf, "follow_user", ""):
            s["_follow_user"] = pf.follow_user         # 0.31.61: de quem esta conta copia os trades
        if getattr(pf, "brain_freeze", None):
            s["_brain_freeze"] = pf.brain_freeze       # 0.31.85: evolução para a qual o dono voltou
        await self.db.update("user_settings", {"user_id": pf.user_id},
                             {"settings": s, "atualizado_em": datetime.now(timezone.utc).isoformat()})

    async def set_secret(self, pf: PumpFun, name: str, value: str) -> None:
        await self.vault.save(pf.user_id, name, value)
        pf.keys.set(name, value)
        self._wire_wallet(pf)
        await audit(self.db, pf.user_id, "salvar chave", name)

    async def remove_secret(self, pf: PumpFun, name: str) -> None:
        await self.vault.delete(pf.user_id, name)
        pf.keys.set(name, "")
        if name == "wallet_private_key" and pf.cfg.pump_real_enabled:
            pf.cfg.pump_real_enabled = False
            await self.save_settings(pf)
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
            if not pf.ghosts.dirty and not pf.ghosts_auto.dirty and not getattr(pf, "_funnel_dirty", False):
                continue
            try:
                await self.db.insert("ghost_stats", {"user_id": uid, "data": {**pf.ghosts.dump(), "auto": pf.ghosts_auto.dump(),
                                                                              "funil": pf.funnel_dump()},
                                                     "atualizado_em": datetime.now(timezone.utc).isoformat()},
                                     upsert=True, on_conflict="user_id")
                pf.ghosts.dirty = pf.ghosts_auto.dirty = False
                pf._funnel_dirty = False
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
               "compra automática", "boost on", "aprendi com os erros", "estudo automático", "ajuste automático",
               "seu convite de configuração", "alterou a configuração")

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
                rep_today["real_report"] = build(pf, dia, None, real=True)   # 0.31.49: a real também fica guardada
                await self.db.insert("daily_report", {"user_id": uid, "dia": dia, "data": rep_today,
                                                      "atualizado_em": datetime.now(timezone.utc).isoformat()},
                                     upsert=True, on_conflict="user_id,dia")
                if getattr(pf, "_daily_closed", None) != prev:
                    old = await self.db.select("daily_report", {"user_id": uid, "dia": prev})
                    if old and not (old[0].get("data") or {}).get("closed"):
                        rep = build(pf, prev, (old[0].get("data") or {}).get("points"))
                        rep["modules"] = (old[0].get("data") or {}).get("modules") or []   # a última foto ao vivo do dia
                        rr = build(pf, prev, None, real=True)
                        saved_rr = (old[0].get("data") or {}).get("real_report") or {}
                        if len(saved_rr.get("real_misses") or []) > len(rr.get("real_misses") or []):
                            rr["real_misses"] = saved_rr["real_misses"]        # o feed em memória pode já ter rodado
                        rr["closed"] = True
                        rep["real_report"] = rr
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

    async def auto_tune(self, pf, now: float | None = None) -> dict:
        """Ajuste automático (0.31.14, app/autotune.py): aplica a regra de saída que os fantasmas mostram render mais,
        desfaz se piorar e pausa trader que só dá prejuízo. Só com a execução real desligada."""
        from .auto_trades import ts
        from .autotune import (AUTO_KEYS, AUTO_MIN_TRADES, KEYS, MIN_TRADES, PAUSE_H, REJECT_S, auto_variant_settings,
                               bad_traders, evaluate, pick_exit, variant_settings)
        from .reports import autopsy
        now = time.time() if now is None else now
        if getattr(pf, "role", "user") != "admin" or not getattr(pf.cfg, "pump_tune_on", True):
            return {"ok": False, "motivo": "desligado"}
        if getattr(pf.cfg, "pump_real_enabled", False):
            return {"ok": False, "motivo": "execução real ligada: o ajuste automático só mexe com o real desligado"}
        if getattr(pf, "brain_freeze", None):
            return {"ok": False, "motivo": f"cérebro congelado na evolução E{pf.brain_freeze.get('numero')} (Base geral)"}
        log_rows = await self.db.select("auto_tune_log", {"user_id": pf.user_id}, order="em.desc", limit=500)
        done: list[str] = []

        async def note(tipo, acao, motivo, detalhe):
            await self.db.insert("auto_tune_log", {"user_id": pf.user_id, "tipo": tipo, "acao": acao, "motivo": motivo,
                                                   "detalhe": detalhe, "em": datetime.fromtimestamp(now, timezone.utc).isoformat()})
            done.append(acao)
            pf._emit(f"Ajuste automático: {acao} — {motivo}")

        trades = pf.trades(100000)
        testing = False
        # 1) saída das cópias (fantasmas das cópias) e 2) saída das automáticas do Explorar (fantasmas das automáticas)
        for tipo, ghosts, mapper, keys, min_n, sel in (
                ("saida", pf.ghosts, variant_settings, KEYS, MIN_TRADES, lambda t: not t.get("manual") and not t.get("auto")),
                ("saida_auto", pf.ghosts_auto, auto_variant_settings, AUTO_KEYS, AUTO_MIN_TRADES,
                 lambda t: t.get("origem") == "explorar")):
            last = next((r for r in log_rows if r.get("tipo") == tipo), None)
            busy, undone = False, None
            if last and last.get("acao") == "aplicou":
                ev = evaluate(last, trades, now, ts, sel)
                det = last.get("detalhe") or {}
                if ev is None:
                    busy = testing = True
                else:
                    if ev[0] == "desfez":
                        pf.cfg.apply(det.get("antes") or {})
                        await self.save_settings(pf)
                        undone = det.get("variante")
                    await note(tipo, ev[0], f"{det.get('nome', det.get('variante'))}: {ev[1]}",
                               {"variante": det.get("variante"), "nome": det.get("nome")})
            if busy:
                continue
            rejected = {(r.get("detalhe") or {}).get("variante") for r in log_rows
                        if r.get("tipo") == tipo and r.get("acao") == "desfez" and now - (ts(r.get("em")) or 0) < REJECT_S}
            if undone:
                rejected.add(undone)
            snap = self.ghosts_merged(pf, "ghosts_auto" if tipo == "saida_auto" else "ghosts", trades)   # 0.31.64: base geral
            days = (now - (ts(snap.get("since")) or now)) / 86400
            pick = pick_exit(snap, days, rejected, mapper, min_n)
            new = mapper(pick["id"]) if pick else None
            if new:
                antes = {k: getattr(pf.cfg, k) for k in keys}
                if any(antes.get(k) != v for k, v in new.items()):
                    pf.cfg.apply(new)
                    await self.save_settings(pf)
                    alvo = "automáticas do Explorar" if tipo == "saida_auto" else "cópias"
                    await note(tipo, "aplicou", f"{alvo} · {pick['nome']}: {pick['avg']:+.5f} SOL/trade nos fantasmas "
                               f"({pick['trades']} trades) × suas regras {pick['mine_avg']:+.5f}; fica em teste 48 h",
                               {"variante": pick["id"], "nome": pick["nome"], "antes": antes, "depois": new})
        from .pumpfun import AUTO_ORIGINS
        # só cópias de trader: compras manuais e automáticas (Explorar, Base, elite) não têm trader para pausar
        week = [t for t in trades if not t.get("real") and not t.get("manual") and t.get("origem") not in AUTO_ORIGINS
                and pf.valid_addr(t.get("wallet") or "") and now - (ts(t.get("closed_at")) or 0) < 7 * 86400]
        for x in bad_traders(autopsy(week), set(pf.paused())):
            pf.pause(x["wallet"], PAUSE_H, f"ajuste automático: {x['trades']} cópias, acerto {x['acerto'] * 100:.0f}%, {x['pnl_sol']:+.4f} SOL")
            await note("trader", "pausou", f"{x['wallet'][:4]}…{x['wallet'][-4:]} por {PAUSE_H} h: {x['trades']} cópias, acerto "
                       f"{x['acerto'] * 100:.0f}%, {x['pnl_sol']:+.4f} SOL ({x['causa_nome']})", {"wallet": x["wallet"]})
        self._tune_at[pf.user_id] = now
        return {"ok": True, "acoes": done, "testando": testing}

    async def tune_loop(self) -> None:
        await asyncio.sleep(300)
        while True:
            for pf in list(self.engines.values()):
                try:
                    await self.auto_tune(pf)
                except Exception as e:
                    log.warning("ajuste automático (%s…): %s", pf.user_id[:8], str(e)[:160])
            await asyncio.sleep(6 * 3600)

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

    @staticmethod
    def explore_share_keys(part: str) -> list[str]:
        """Partes da configuração do Explorar que dá para compartilhar (0.31.16)."""
        from .settings import USER_KEYS
        filtros = [k for k in USER_KEYS if k.startswith("pump_ex_auto_") and k != "pump_ex_auto_on"]
        protecoes = [k for k in USER_KEYS if k.startswith("pump_ar_")]
        return {"filtros": filtros, "protecoes": protecoes, "tudo": ["pump_ex_auto_on"] + filtros + protecoes}.get(part, [])

    async def explore_share(self, pf, sender: dict, to_uid: str, part: str) -> dict:
        """Explorar → Compartilhar (0.31.16): vira um convite que a pessoa aceita ou recusa (0.31.17)."""
        keys = self.explore_share_keys(part)
        if not keys:
            return {"error": "parte inválida"}
        nome = {"filtros": "Explorar · filtros de entrada", "protecoes": "Explorar · proteções das automáticas",
                "tudo": "Explorar · toda a configuração"}[part]
        return await self.config_offer(pf, sender, to_uid, nome, keys)

    # ------------------------------------------------------------------ convites de configuração (0.31.17)
    SHARE_BLOCK = ("real", "pump_tg_")             # nunca vai junto: nada da carteira real nem do Telegram pessoal

    def share_filter(self, keys, admin: bool) -> list[str]:
        from .settings import USER_KEYS
        out = [k for k in keys if k in USER_KEYS and not any(b in k for b in self.SHARE_BLOCK)]
        if not admin:                               # quem não é admin não usa as opções do "Usar ou descartar"
            out = [k for k in out if not k.startswith(("pump_ex_auto_", "pump_ar_"))]
        return out

    async def share_targets(self, uid: str) -> list[dict]:
        out = []
        for p in await self.db.select("profiles", None, order="criado_em.asc", columns="user_id,nome,email,bloqueado,role"):
            if p["user_id"] == uid or p.get("bloqueado"):
                continue
            em = str(p.get("email") or "")
            nm, _, dom = em.partition("@")
            out.append({"user_id": p["user_id"], "nome": p.get("nome") or "", "admin": p.get("role") == "admin",
                        "email": (nm[:2] + "***@" + dom) if dom else ""})
        return out

    @staticmethod
    def _no_traders(rows):
        return [r for r in rows or [] if r.get("tipo") != "traders"]

    async def traders_offer(self, pf, sender: dict, to_uid: str) -> dict:
        """0.31.74 (pedido do dono): compartilhar a lista de traders adicionados à mão (Top traders) com outra pessoa,
        como convite — nada entra na lista dela até ela clicar em Aceitar."""
        if to_uid == pf.user_id:
            return {"error": "escolha outro usuário"}
        rows = await self.db.select("profiles", {"user_id": to_uid}, columns="user_id,bloqueado")
        if not rows or rows[0].get("bloqueado"):
            return {"error": "usuário não encontrado"}
        lst = list(pf.manual)
        if not lst:
            return {"error": "você não tem traders adicionados à mão para compartilhar"}
        de = (sender.get("nome") or (sender.get("email") or "").split("@")[0] or "outro usuário")[:60]
        parte = f"Lista de traders ({len(lst)} carteira{'s' if len(lst) != 1 else ''})"
        await self.db.insert("config_offers", {"de_user": pf.user_id, "para_user": to_uid, "de_nome": de, "parte": parte,
                                               "valores": {"_traders": lst}, "status": "pendente", "tipo": "traders"})
        other = self.engines.get(to_uid)
        if other is not None:
            other._emit(f"Traders: {de} quer compartilhar a lista de traders com você ({len(lst)}). Aceite ou recuse no topo do painel.")
        await audit(self.db, pf.user_id, "lista de traders compartilhada", f"{len(lst)} carteiras para {to_uid}")
        return {"ok": True, "carteiras": len(lst)}

    async def config_offer(self, pf, sender: dict, to_uid: str, parte: str, keys) -> dict:
        """Convite: o usuário X quer compartilhar a configuração dele (pedido do dono em 2026-10-26). Nada muda na conta
        de quem recebe até ela clicar em Aceitar e aplicar. Os valores vão no convite (como estavam ao enviar)."""
        if to_uid == pf.user_id:
            return {"error": "escolha outro usuário"}
        rows = await self.db.select("profiles", {"user_id": to_uid}, columns="user_id,bloqueado,role")
        if not rows or rows[0].get("bloqueado"):
            return {"error": "usuário não encontrado"}
        keys = self.share_filter(keys, rows[0].get("role") == "admin")
        if not keys:
            return {"error": "nada para compartilhar nesta parte"}
        de = (sender.get("nome") or (sender.get("email") or "").split("@")[0] or "outro usuário")[:60]
        await self.db.insert("config_offers", {"de_user": pf.user_id, "para_user": to_uid, "de_nome": de, "parte": str(parte)[:200],
                                               "valores": {k: getattr(pf.cfg, k) for k in keys}, "status": "pendente"})
        other = self.engines.get(to_uid)
        if other is not None:
            other._emit(f"Configuração: {de} quer compartilhar com você — {parte} ({len(keys)} opções). Aceite ou recuse no topo do painel.")
        await audit(self.db, pf.user_id, "convite de configuração", f"{parte} para {to_uid}")
        return {"ok": True, "opcoes": len(keys)}

    async def config_offers(self, uid: str) -> list[dict]:
        from .auto_trades import ts
        rows = await self.db.select("config_offers", {"para_user": uid, "status": "pendente"}, order="criado_em.desc", limit=20)
        now = time.time()
        out = []
        for r in rows:
            if now - (ts(r.get("criado_em")) or now) >= 7 * 86400:
                continue
            o = {"id": r["id"], "de": r.get("de_nome"), "parte": r.get("parte"), "opcoes": len(r.get("valores") or {}),
                 "nomes": sorted(r.get("valores") or {}), "valores": r.get("valores") or {}, "em": r.get("criado_em"),
                 "tipo": r.get("tipo") or "convite"}
            if o["tipo"] == "atualizacao":
                try:
                    o.update(await self._update_effect(r, uid))
                except Exception as e:
                    log.warning("efeito da atualização de configuração: %s", str(e)[:120])
            out.append(o)
        return out

    async def _update_effect(self, r: dict, uid: str) -> dict:
        """Atualização de configuração copiada (0.31.34): o que a origem mudou e quanto ela fez ANTES e DEPOIS da mudança,
        comparado com quem ficou com a configuração antiga no mesmo período."""
        from .compare import _ts, summary
        base = (await self.db.select("config_offers", {"id": r.get("base_id")}) or [{}])[0] if r.get("base_id") else {}
        old = base.get("valores") or {}
        mudou = [{"k": k, "antes": old.get(k), "agora": v} for k, v in (r.get("valores") or {}).items()
                 if k in old and str(old.get(k)) != str(v)]
        t0, t1 = _ts(base.get("respondido_em")) or 0, _ts(r.get("criado_em")) or time.time()
        x, y = self.engines.get(r["de_user"]), self.engines.get(uid)
        when = lambda t: _ts(t.get("closed_at")) or 0                                       # noqa: E731
        sel = lambda pf, a, b: [t for t in (pf.trades(3000) if pf else []) if not t.get("real") and a <= when(t) < b]   # noqa: E731
        res = lambda L: {k: summary(L)[k] for k in ("trades", "wins", "acerto", "pnl_sol")} | {   # noqa: E731
            "media_sol": round(summary(L)["pnl_sol"] / len(L), 6) if L else None}
        return {"mudou": mudou, "base_em": base.get("respondido_em"),
                "efeito": {"origem_antes": res(sel(x, t0, t1)), "origem_depois": res(sel(x, t1, 4e12)),
                           "voce_depois": res(sel(y, t1, 4e12))}}

    async def config_watch(self) -> int:
        """0.31.34 (pedido do dono em 2026-10-27): quem usa a configuração IDÊNTICA à de outra pessoa é avisado quando
        ela altera algo, e recebe um convite do tipo "atualizacao" para aplicar ou não. Só a cópia mais recente de cada
        par conta; quem já mudou a própria configuração não recebe (escolheu se afastar); a mesma alteração recusada não
        volta a ser oferecida."""
        from .compare import _eq
        rows = self._no_traders(await self.db.select("config_offers", {"status": "aceita"}, order="respondido_em.desc", limit=500))
        seen, n = set(), 0
        for o in rows:
            pair = (o.get("de_user"), o.get("para_user"))
            if pair in seen:
                continue
            seen.add(pair)
            x, y = self.engines.get(pair[0]), self.engines.get(pair[1])
            vals = o.get("valores") or {}
            if x is None or y is None or not vals or pair[0] == pair[1]:
                continue
            if any(not _eq(getattr(y.cfg, k, None), v) for k, v in vals.items()):
                continue                                   # não está mais idêntica: a pessoa mudou por conta própria
            ch = [k for k, v in vals.items() if not _eq(getattr(x.cfg, k, None), v)]
            if not ch:
                continue
            keys = self.share_filter(list(vals), getattr(y, "role", "user") == "admin")
            novo = {k: getattr(x.cfg, k) for k in keys}
            prev = await self.db.select("config_offers", {"de_user": pair[0], "para_user": pair[1], "tipo": "atualizacao", "base_id": o["id"]},
                                        order="criado_em.desc", limit=5)
            if any(p.get("status") in ("pendente", "recusada") and all(_eq((p.get("valores") or {}).get(k), v) for k, v in novo.items()) for p in prev):
                continue
            pend = [p for p in prev if p.get("status") == "pendente"]
            de = o.get("de_nome") or await self._nome(pair[0])
            parte = f"atualização da configuração de {de}: {len(ch)} opção(ões) mudaram"
            if pend:                                       # mudou de novo antes de a pessoa responder: atualiza o convite
                await self.db.update("config_offers", {"id": pend[0]["id"]}, {"valores": novo, "parte": parte})
            else:
                await self.db.insert("config_offers", {"de_user": pair[0], "para_user": pair[1], "de_nome": de, "parte": parte,
                                                       "valores": novo, "status": "pendente", "tipo": "atualizacao", "base_id": o["id"]})
            y._emit(f"Configuração: {de} alterou a configuração que você copiou ({len(ch)} opção(ões)). "
                    "No topo do painel aparece se ele ganhou ou perdeu mais depois da mudança; você escolhe aplicar ou não.")
            await audit(self.db, pair[1], "configuração copiada foi alterada pela origem", f"{de}: {len(ch)} opção(ões)")
            n += 1
        return n

    async def config_watch_loop(self) -> None:
        await asyncio.sleep(180)
        while True:
            try:
                await self.config_watch()
            except Exception as e:
                log.warning("vigiar configurações copiadas: %s", str(e)[:160])
            await asyncio.sleep(300)

    async def config_applied(self, uid: str) -> list[dict]:
        """Convites aceitos (60 dias): o painel compara com os valores de agora e diz se a configuração continua
        idêntica à de quem enviou (0.31.31, pedido do dono em 2026-10-27)."""
        from .auto_trades import ts
        rows = self._no_traders(await self.db.select("config_offers", {"para_user": uid, "status": "aceita"}, order="respondido_em.desc", limit=30))
        now = time.time()
        return [{"id": r["id"], "de": r.get("de_nome"), "parte": r.get("parte"), "em": r.get("respondido_em"),
                 "valores": r.get("valores") or {}, "antes": r.get("antes") or {}}
                for r in rows if now - (ts(r.get("respondido_em")) or now) < 60 * 86400]

    async def _nome(self, uid: str) -> str:
        try:
            r = await self.db.select("profiles", {"user_id": uid}, columns="nome,email")
            if r:
                return (r[0].get("nome") or (r[0].get("email") or "").split("@")[0] or "usuário")[:60]
        except Exception:
            pass
        return "usuário"

    async def config_users(self, uid: str) -> list[dict]:
        """0.31.37 (pedido do dono em 2026-10-27): quem está usando a SUA configuração — a cópia mais recente de cada
        pessoa, conferindo agora se ela continua idêntica (e quantas opções ela mudou depois)."""
        from .compare import _eq
        rows = self._no_traders(await self.db.select("config_offers", {"de_user": uid, "status": "aceita"}, order="respondido_em.desc", limit=200))
        seen, out = set(), []
        for r in rows:
            to = r.get("para_user")
            if to in seen or to == uid:
                continue
            seen.add(to)
            vals = r.get("valores") or {}
            other = self.engines.get(to)
            diff = None if other is None else sum(1 for k, v in vals.items() if not _eq(getattr(other.cfg, k, None), v))
            out.append({"nome": await self._nome(to), "parte": r.get("parte"), "em": r.get("respondido_em"), "opcoes": len(vals),
                        "mudou": diff, "identica": diff == 0, "offer_id": r["id"]})
        return out

    async def compare_list(self, uid: str) -> list[dict]:
        """Cópias de configuração em que esta conta participa (recebeu ou enviou), para a tela Comparar (0.31.34)."""
        rows = []
        for f in ({"para_user": uid, "status": "aceita"}, {"de_user": uid, "status": "aceita"}):
            rows += self._no_traders(await self.db.select("config_offers", f, order="respondido_em.desc", limit=30))
        seen, out = set(), []
        for r in sorted(rows, key=lambda r: str(r.get("respondido_em") or ""), reverse=True):
            if r["id"] in seen:
                continue
            seen.add(r["id"])
            out.append({"id": r["id"], "de": r.get("de_nome") or await self._nome(r["de_user"]), "para": await self._nome(r["para_user"]),
                        "eu_sou": "origem" if r["de_user"] == uid else "copiou", "parte": r.get("parte"), "em": r.get("respondido_em"),
                        "opcoes": len(r.get("valores") or {})})
        return out

    async def compare_one(self, uid: str, offer_id: int, origem: str | None = None, real: bool = False) -> dict:
        from .compare import compare
        rows = self._no_traders(await self.db.select("config_offers", {"id": offer_id, "status": "aceita"}))
        if not rows or uid not in (rows[0].get("de_user"), rows[0].get("para_user")):
            return {"error": "cópia não encontrada"}
        o = rows[0]
        x, y = await self.engine(o["de_user"]), await self.engine(o["para_user"])
        r = compare({"em": o.get("respondido_em"), "valores": o.get("valores") or {}}, x.trades(3000), y.trades(3000),
                    x.cfg.user_dict(), y.cfg.user_dict(), o.get("de_nome") or await self._nome(o["de_user"]), await self._nome(o["para_user"]),
                    origem=origem, real=real)
        r.update({"id": o["id"], "parte": o.get("parte")})
        # 0.31.41 (pedido do dono: "por que não rodou nos meus trades o que o Bruxo rodou?"): para cada token que só um
        # fez, o motivo que o funil da OUTRA conta anotou (aprender com os erros, pausa por perdas, limite por hora…)
        for lst, other in ((r["so_x"], y), (r["so_y"], x)):
            fn = getattr(other, "_ex_funnel", None) or {}
            for g in lst:
                e = fn.get(g["mint"])
                g["por_que_nao"] = (e.get("why") or "entrou, mas não fechou/abriu no mesmo período") if e and not e.get("entrou") \
                    else ("entrou depois (ainda aberta ou fora do período)" if e else
                          "não estava na lista dela quando a outra entrou (Explorar desligado, sem preço na hora, ou antes de o funil existir)")
        return r

    async def compare_save(self, uid: str, offer_id: int) -> dict:
        from .compare import ai_text
        r = await self.compare_one(uid, offer_id)
        if r.get("error"):
            return r
        txt = ai_text(r, r.get("parte") or "")
        await self.db.insert("config_compare_reports", {"user_id": uid, "offer_id": offer_id, "data": r, "texto": txt})
        await audit(self.db, uid, "salvou análise de configuração copiada", f"{r['x']['nome']} × {r['y']['nome']}")
        return {"ok": True, "texto": txt}

    async def compare_saved(self, uid: str) -> list[dict]:
        rows = await self.db.select("config_compare_reports", {"user_id": uid}, order="criado_em.desc", limit=30)
        return [{"id": r["id"], "offer_id": r.get("offer_id"), "em": r.get("criado_em"), "texto": r.get("texto"),
                 "x": ((r.get("data") or {}).get("x") or {}), "y": ((r.get("data") or {}).get("y") or {})} for r in rows]

    async def config_sync(self, pf, offer_id: int) -> dict:
        """0.31.35 (pedido do dono em 2026-10-27): "sua configuração ainda está diferente, quer deixar idêntica?" —
        aplica os valores ATUAIS de quem enviou, só nas opções daquela cópia, como uma nova cópia aceita (guarda o antes,
        o selo volta a "idêntica"). Nunca leva real, chaves ou Telegram."""
        rows = self._no_traders(await self.db.select("config_offers", {"id": offer_id, "para_user": pf.user_id, "status": "aceita"}))
        if not rows:
            return {"error": "cópia não encontrada"}
        o = rows[0]
        if o["de_user"] == pf.user_id:
            return {"error": "essa já é a sua configuração"}
        x = await self.engine(o["de_user"])
        keys = self.share_filter(list(o.get("valores") or {}), getattr(pf, "role", "user") == "admin")
        if not keys:
            return {"error": "nada para aplicar"}
        de = o.get("de_nome") or await self._nome(o["de_user"])
        parte = str(o.get("parte") or "configuração").split(" (deixada idêntica")[0][:150] + " (deixada idêntica)"
        await self.db.insert("config_offers", {"de_user": o["de_user"], "para_user": pf.user_id, "de_nome": de, "parte": parte,
                                               "valores": {k: getattr(x.cfg, k) for k in keys}, "status": "pendente"})
        got = await self.db.select("config_offers", {"de_user": o["de_user"], "para_user": pf.user_id, "status": "pendente", "parte": parte},
                                   order="criado_em.desc", limit=1)
        if not got:
            return {"error": "não consegui registrar"}
        r = await self.config_answer(pf, got[0]["id"], True, notify_sender=False)
        await audit(self.db, pf.user_id, "deixou a configuração idêntica", f"{parte} de {de}")
        return r

    async def admin_copy_config(self, pf, uid: str) -> dict:
        """0.31.33 (pedido do dono em 2026-10-27): o admin copia TODA a configuração de um usuário para a própria conta,
        pelo Admin → Usuários. Passa pelo mesmo caminho do convite aceito (guarda o antes, mostra o selo "idêntica à de
        X" e o "ver o que mudou"). Nunca leva real, chaves ou Telegram (`share_filter`). Quem foi copiado não é alterado."""
        from .settings import USER_KEYS
        if uid == pf.user_id:
            return {"error": "essa já é a sua configuração"}
        rows = await self.db.select("profiles", {"user_id": uid}, columns="user_id,nome,email")
        if not rows:
            return {"error": "usuário não encontrado"}
        src = await self.engine(uid)
        de = (rows[0].get("nome") or (rows[0].get("email") or "").split("@")[0] or "usuário")[:60]
        keys = self.share_filter(list(USER_KEYS), True)
        await self.db.insert("config_offers", {"de_user": uid, "para_user": pf.user_id, "de_nome": de, "parte": "toda a configuração (copiada no Admin)",
                                               "valores": {k: getattr(src.cfg, k) for k in keys}, "status": "pendente"})
        got = await self.db.select("config_offers", {"de_user": uid, "para_user": pf.user_id, "status": "pendente"}, order="criado_em.desc", limit=1)
        if not got:
            return {"error": "não consegui registrar a cópia"}
        r = await self.config_answer(pf, got[0]["id"], True, notify_sender=False)
        await audit(self.db, pf.user_id, "admin copiou configuração", f"toda a configuração de {de}")
        return r

    async def config_answer(self, pf, offer_id: int, accept: bool, notify_sender: bool = True) -> dict:
        rows = await self.db.select("config_offers", {"id": offer_id, "para_user": pf.user_id, "status": "pendente"})
        if not rows:
            return {"error": "convite não encontrado"}
        r = rows[0]
        applied = {}
        antes = {}
        if accept and r.get("tipo") == "traders":
            # 0.31.74: lista de traders — entra na lista "adicionados à mão" de quem aceitou (os que ela já tinha ficam)
            antes = {"_traders": list(pf.manual)}
            for w in (r.get("valores") or {}).get("_traders") or []:
                res = pf.add_manual(w)
                if not (res or {}).get("error"):
                    applied[w] = True
            await self.save_settings(pf)
            pf._emit(f"Traders de {r.get('de_nome')} adicionados: {len(applied)} carteira(s)")
        elif accept:
            vals = {k: v for k, v in (r.get("valores") or {}).items()
                    if k in self.share_filter([k], getattr(pf, "role", "user") == "admin")}
            antes = {k: getattr(pf.cfg, k, None) for k in vals}       # 0.31.31: para "ver o que mudou"
            applied, _ = pf.cfg.apply(vals)
            await self.save_settings(pf)
            pf._emit(f"Configuração de {r.get('de_nome')} aplicada: {r.get('parte')} ({len(applied)} opções)")
        upd = {"status": "aceita" if accept else "recusada", "respondido_em": datetime.now(timezone.utc).isoformat()}
        if accept:
            upd["antes"] = antes
        await self.db.update("config_offers", {"id": offer_id}, upd)
        # 0.31.23 (pedido do dono em 2026-10-27): quem compartilhou também é avisado (painel e Telegram, se ligado) e a
        # resposta fica no registro (audit_log) dos dois lados, com nomes; antes só avisava se o painel dele estivesse carregado.
        quem = "a pessoa"
        try:
            pr = await self.db.select("profiles", {"user_id": pf.user_id}, columns="nome,email")
            if pr:
                quem = (pr[0].get("nome") or (pr[0].get("email") or "").split("@")[0] or quem)[:60]
        except Exception:
            pass
        verbo = "aceitou e aplicou" if accept else "recusou"
        n = f" ({len(applied)} opções aplicadas)" if accept else ""
        await audit(self.db, pf.user_id, "aceitou configuração" if accept else "recusou configuração",
                    f"{r.get('parte')} de {r.get('de_nome') or r.get('de_user')}{n}")
        if not notify_sender:                          # cópia feita pelo admin: quem foi copiado não enviou convite
            return {"ok": True, "opcoes": len(applied)}
        await audit(self.db, r.get("de_user"), "convite de configuração aceito" if accept else "convite de configuração recusado",
                    f"{quem} {verbo}: {r.get('parte')}{n}")
        try:
            sender = await self.engine(r.get("de_user"))
            sender._emit(f"Configuração: {quem} {verbo} seu convite de configuração — {r.get('parte')}{n}.")
        except Exception as e:
            log.warning("aviso do convite não foi entregue: %s", str(e)[:120])
        return {"ok": True, "opcoes": len(applied)}

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
        await self.load_shadows()
        for pf in list(self.engines.values()):        # 0.31.62: nome de quem é copiado, para os avisos de quem copia
            lead = self.engines.get(getattr(pf, "follow_user", ""))
            if lead is not None:
                try:
                    lead._nome_cache = await self._nome(lead.user_id)
                except Exception:
                    pass
        self.running = True
        for pf in list(self.engines.values()):
            self._start_engine(pf)
        self._tasks.append(asyncio.create_task(self.flush_loop()))
        self._tasks.append(asyncio.create_task(self.learning_loop()))
        self._tasks.append(asyncio.create_task(self.ghosts_loop()))
        self._tasks.append(asyncio.create_task(self.daily_loop()))
        self._tasks.append(asyncio.create_task(self.study_auto_loop()))
        self._tasks.append(asyncio.create_task(self.tune_loop()))
        self._tasks.append(asyncio.create_task(self.base_loop()))           # 0.31.71: base geral
        self._tasks.append(asyncio.create_task(self.shadow_loop()))         # 0.31.72: entradas sombra
        self._tasks.append(asyncio.create_task(self.xray_loop()))           # 0.31.86: Raio-X do token
        self._tasks.append(asyncio.create_task(self.rlog_loop()))           # 0.31.89: log de análise dos robôs
        self._tasks.append(asyncio.create_task(self.usage_loop()))          # 0.31.76: uso das APIs
        self._tasks.append(asyncio.create_task(self.config_watch_loop()))
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
                await self.save_settings(pf)
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
