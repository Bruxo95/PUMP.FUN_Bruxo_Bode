"""Central dos usuários: um motor de cópia (PumpFun) por usuário, todos ligados ao MESMO mercado público.

Cada motor tem: configuração própria, dados próprios (SupabaseStore), chaves próprias (KeyRing, já abertas só na
memória) e carteira/execução real próprias (desligada ao iniciar).
"""
from __future__ import annotations

import asyncio
import base64
import copy
import logging
import math
import os
import time
from datetime import datetime, timezone

from . import detentores, jev, jevtrade, stkeys
from . import cfghist
from .apiusage import ORIGIN, run_as
from .db import SupabaseStore, Vault, audit
from .jupiter import JupiterQuoter, JupiterWallet
from .keystore import KEY_LINKS, SYSTEM_NAMES, SYSTEM_OWNER, KeyRing
from .logsafe import add_secret
from .pumpfun import AUTO_ORIGINS, EQ_SEED, PumpFun, PumpMarket, PumpReal
from .radar import RadarBuffer, callout_policy
from .settings import PumpSettings, SAIDAS_V, SAIDAS_WHY, saidas_upgrade
from .solana_wallet import UserWallet

B58_ADDR = __import__("re").compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")   # endereço Solana (0.32.4)
EQ_MAX = 100

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
        self.elite = Elite(self.market)           # maiores traders (0.31.2)
        from .calls import Calls
        self.calls = Calls()                      # 0.31.94: calls quentes pela blockchain
        from .bruxo import Bruxo
        self.bx_reports: dict[str, dict] = {}     # 0.32.80: relatórios da Aba do Bruxo por usuário {"30min": [...], "dia": [...]}
        self.bruxo = Bruxo()                      # 0.32.41: Aba do Bruxo (top trader em moeda nova)
        self.jt = jevtrade.JevTrade()             # 0.32.87: Jev Trade (simulação; o Jev decide entrada e saída)
        self.jt.on_event = self._jt_wallet        # 0.32.93: entradas e vendas também na carteira FICTÍCIA de quem ligou
        self._bx_base: tuple[float, dict] = (0.0, {})
        self._ov_recent: dict[str, list] = {}       # 0.32.52: ajustes aplicados há pouco (reafirmados por 20 min)
        self.eq_reports: dict[str, list] = {}      # 0.32.73: relatórios de 6 h do Copiar igual, por usuário
        self.tab_reports: dict[str, list] = {}     # 0.32.41: relatórios de cada aba (a cada 30 min), por usuário                  # listas estilo pump.fun/explore pela Solana Tracker (0.28.0)
        self._study_at: dict[str, float] = {}      # carteira -> quando o histórico foi atualizado
        self._study_auto_at: dict[str, float] = {}  # usuário -> última volta do estudo automático (0.31.13)
        self._tune_at: dict[str, float] = {}        # usuário -> última volta do ajuste automático (0.31.14)
        self._tasks: list[asyncio.Task] = []
        self.shared_st_key = ""                    # chave da Solana Tracker do sistema (visualização para todos)
        self.started_at = time.time()
        self.errors: list[dict] = []
        self._touched: dict[str, float] = {}
        # 0.32.229: perfil lido a cada pedido do painel era o 2º maior volume de leituras do Supabase (~2.500/h).
        # Guarda por PROFILE_TTL s; mudança de categoria/bloqueio pelo admin limpa na hora (admin_update_user).
        self._prof_cache: dict[str, tuple[float, dict]] = {}
        self._rlog_vazio: set[str] = set()                 # 0.32.229: dias fechados já vistos sem registro
        # trava geral da execução real (no .env): enquanto false, ninguém liga o real
        self.monitor = None                        # SharedMonitor (ligado em start)
        self.running = False
        self.real_allowed = os.environ.get("PUMP_REAL_ALLOWED", "false").strip().lower() in ("1", "true", "sim", "yes")

    # ------------------------------------------------------------------ perfis
    PROFILE_TTL = 30

    async def ensure_profile(self, claims: dict) -> dict:
        uid = claims["sub"]
        now = time.time()
        hit = self._prof_cache.get(uid)
        if hit and now - hit[0] < self.PROFILE_TTL:
            return hit[1]
        rows = await self.db.select("profiles", {"user_id": uid})
        if rows:
            self._prof_cache[uid] = (now, rows[0])
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
        if isinstance(saved.get("_study_copy"), list):                  # 0.32.11: aprovadas copiadas (só fictícia)
            pf.study_copy = [str(w) for w in saved["_study_copy"]][:50]
        for k, attr in (("_sim_only", "sim_only_list"), ("_ia_added", "ia_added"), ("_real_ok", "real_ok_list")):   # 0.32.17/0.32.38
            if isinstance(saved.get(k), list):
                setattr(pf, attr, [str(w) for w in saved[k]][:100])
        if isinstance(saved.get("_ov_user"), dict):                     # 0.32.56: opções que a pessoa mudou na tela (quando)
            pf._ov_user = {str(k): str(v) for k, v in saved["_ov_user"].items()}
        if isinstance(saved.get("_copy_equal"), list):                  # 0.32.4: Copiar igual (lista colada pelo dono)
            pf.copy_equal = [str(w) for w in saved["_copy_equal"]][:EQ_MAX]
        if isinstance(saved.get("_eq_mode"), dict):                     # 0.32.65: botão Copiar de cada carteira
            pf.eq_mode = {str(k): str(v) for k, v in saved["_eq_mode"].items() if v in ("sim", "both", "off")}
        pf.brain_freeze = saved.get("_brain_freeze") if isinstance(saved.get("_brain_freeze"), dict) else None   # 0.31.85
        pf.leader_hook = lambda ev, p, why="", _pf=pf: self._on_leader(_pf, ev, p, why)
        pf.learn_pool = lambda _pf=pf: self._learn_pool(_pf)                 # 0.31.63: aprendizado geral
        pf.shadow_hook = self.shadow_note                                     # 0.31.72: entradas sombra
        pf.top_hook = self.top_note                                           # 0.32.124: compras barradas do Top traders
        # 0.31.28 (pedido do dono em 2026-10-27): o real ligado pelo usuário continua ligado depois de reiniciar o
        # servidor (cada versão nova reinicia). Antes desligava em todo deploy e parecia "desligar sozinho". Só volta
        # com a trava geral liberada, a carteira configurada e a conta liberada; desligar (usuário, admin, remover a
        # carteira) grava OFF.
        pf.real_on_at, pf.real_off_at = saved.get("_real_on_at"), saved.get("_real_off_at")
        if saved.get("_real_on") and self.real_allowed and pf.sol_wallet and pf.sol_wallet.keypair and uid not in self._blocked:
            pf.cfg.pump_real_enabled = True
            if not pf.real_on_at:                      # ligada antes da 0.32.103: a hora está no registro de atividades
                try:
                    rows = await self.db.select("audit_log", {"user_id": uid, "acao": "ligar execução real"}, order="at.desc", limit=1)
                    pf.real_on_at = datetime.fromisoformat(str(rows[0]["at"]).replace("Z", "+00:00")).timestamp() if rows else None
                except Exception:
                    pass
            pf._emit("[PUMP REAL] execução real continua LIGADA depois do reinício do servidor (ligada por você)")
            await audit(self.db, uid, "execução real religada após reinício", f"máx. {pf.cfg.pump_real_max_sol} SOL por compra")
        # 0.32.33: ajustes pendentes do dono (settings_overrides) — no fim, com tudo da conta já carregado, para o salvar não
        # perder nada (study_copy, copy_equal, _real_on…)
        await self.cfg_hist_load(pf)               # 0.32.199: antes dos ajustes, para eles entrarem como versão
        await self._ajuste_saidas(pf, saved)       # 0.32.323: padrões novos de saída, uma vez por conta
        await self._apply_overrides(pf)
        await self._reassert_overrides(pf)
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
            pf._real_task = run_as("Execução real", pf.real_loop())         # 0.32.188: gasto por aba

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

    def health_alerts(self, now: float | None = None) -> dict:
        """0.32.235 (pedido do dono: "o RPC estourou e o status ficou ok"): o Status do sistema só dizia se a conexão estava de
        pé. Agora o Solana RPC e a Solana Tracker ficam "não ok" quando o serviço passou do limite grátis (mesma conta da
        tabela "Uso de cada serviço"), quando o RPC recusou leituras nos últimos 10 min ou quando nenhuma leitura vira trade."""
        now = time.time() if now is None else now
        mk, st = self.market, (getattr(self.market, "rpc_status", None) or {})
        us = self.__dict__.get("usage")
        try:
            cota = us.estourou(now) if us else {}
        except Exception:
            cota = {}
        rpc: list[str] = []
        prov = st.get("prov")
        c = cota.get(prov) if prov else None
        if c:
            rpc.append(f"{prov} passou do limite grátis ({c['pct']:.0f}% {'dos créditos do mês' if c['tipo'] == 'créditos' else 'das ' + c['tipo']}): "
                       "pode recusar leituras até virar o mês ou até trocar de plano/chave")
        t429, tok = getattr(mk, "rpc_429_at", 0.0) or 0.0, getattr(mk, "rpc_ok_at", 0.0) or 0.0
        if now - t429 < 600 and t429 > tok:
            rpc.append(f"o RPC está recusando as leituras (HTTP 429) — última recusa há {int(now - t429) // 60} min, "
                       + ("sem nenhuma leitura boa desde então" if tok else "nenhuma leitura boa desde o reinício"))
        tf = getattr(mk, "rpc_fail_at", 0.0) or 0.0
        if now - tf < 600 and tf > tok and now - t429 >= 600:
            rpc.append(f"o RPC respondeu erro nas leituras ({getattr(mk, 'rpc_fail_msg', '') or 'erro'}) há {int(now - tf) // 60} min")
        up = now - self.started_at
        if st.get("ws") and up > 1800 and (st.get("queued") or 0) >= 50 and not (st.get("parsed") or 0):
            rpc.append(f"{st.get('queued')} transações foram para leitura desde o reinício e nenhuma virou trade: as cópias não estão chegando")
        stc = cota.get("Solana Tracker")
        return {"rpc": {"ok": not rpc, "estourou": bool(c), "motivos": rpc},
                "solana_tracker": ({"estourou": True, "motivo": f"passou do limite grátis ({stc['pct']:.0f}% {'do mês' if stc.get('limite_mes') else 'por minuto'}"
                                    f"{', ' + format(stc['mes'] or 0, ',d').replace(',', '.') + ' de ' + format(stc['limite_mes'], ',d').replace(',', '.') + ' no mês' if stc.get('limite_mes') and stc.get('mes') else ''}"
                                    "): pode responder \"sem créditos\" até virar o mês"} if stc else {"estourou": False}),
                "cota": cota}

    async def arquivo_loop(self) -> None:
        """0.32.225: a cada 30 min passa para o Postgres da VPS o que já não precisa ficar no Supabase (app/arquivo.py).
        0.32.229: enquanto há fila, a cada 5 min."""
        await asyncio.sleep(120)                           # deixa a subida terminar antes
        while True:
            try:
                await self.arquivo.volta(self.db)
            except Exception as e:
                log.warning("arquivo: volta falhou: %s", str(e)[:120])
            await asyncio.sleep(self.arquivo.espera())

    async def usage_loop(self) -> None:
        from .apiusage import Usage
        us = self.__dict__.setdefault("usage", Usage())
        us.st_tags = self.st_tags
        us.rpc_tags = self.rpc_tags
        try:
            from datetime import datetime as _dt
            us.load(await self.db.select("api_usage", {"mes": _dt.now(timezone.utc).strftime("%Y-%m")}))
        except Exception as e:
            log.warning("uso das APIs não carregou: %s", str(e)[:120])
        try:                                            # 0.32.190: janelas de 24 h guardadas (não zeram na atualização)
            rows = await self.db.select("api_usage_janelas", {"k": "janelas"})
            if rows:
                us.load_win(rows[0].get("v"))
        except Exception as e:
            log.warning("janelas do uso não carregaram: %s", str(e)[:120])
        while True:
            await asyncio.sleep(300)
            try:
                await self.db.insert("api_usage_janelas", {"k": "janelas", "v": us.dump_win(), "atualizado_em": datetime.now(timezone.utc).isoformat()},
                                     upsert=True, on_conflict="k")
            except Exception as e:
                log.warning("janelas do uso não gravaram: %s", str(e)[:120])
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

    def brain_shadow(self) -> dict:
        """0.32.117: a regra do aprender com os erros medida nas outras abas, só com o passado de cada trade. Não bloqueia nada."""
        now = time.time()
        hit = self.__dict__.get("_brain_shadow")
        if hit and now - hit[0] < 60:
            return hit[1]
        from . import brainshadow
        rows = []
        for e in list(self.engines.values()):
            for t in e.trades(100000):
                nome = brainshadow.aba(t, e.aba_of)
                if nome:
                    rows.append((e.user_id, nome, t))
        out = brainshadow.run(rows)
        self.__dict__["_brain_shadow"] = (now, out)
        return out

    # ------------------------------------------------------------------ laboratório do Top traders (0.32.124)
    def top_barred(self):
        from .toplab import Barred
        return self.__dict__.setdefault("_top_barred", Barred())

    def top_note(self, who: str, mint: str, symbol, why: str, t: float) -> None:
        self.top_barred().note(who, mint, symbol, why, t)

    async def top_tick(self, now: float | None = None) -> int:
        """Preço das compras barradas em acompanhamento; grava as prontas. Não abre posição nenhuma."""
        now = time.time() if now is None else now
        b = self.top_barred()
        need, svc = b.mints(), getattr(self.monitor, "svc", None) if self.monitor else None
        if need and svc is not None:
            pump = [m for m in need if svc.is_pump(m)]
            rest = await svc._curve_prices(pump, public_first=True) if pump else []
            rest += [m for m in need if m not in pump]
            if rest:
                await svc._fetch_prices(list(dict.fromkeys(rest)))
        done = b.tick(lambda m: (self.market.tokens.get(m) or {}).get("price"), now)
        if done:
            await self.db.insert("top_shadows", [{"id": x["id"], "em": datetime.fromtimestamp(x["t0"], timezone.utc).isoformat(), "data": x} for x in done], upsert=True, on_conflict="id")
        return len(done)

    async def top_loop(self) -> None:
        await asyncio.sleep(30)
        while True:
            try:
                await self.top_tick()
            except Exception as e:
                log.warning("laboratório do top traders: %s", str(e)[:160])
            await asyncio.sleep(30)

    async def load_top(self) -> None:
        try:
            since = datetime.fromtimestamp(time.time() - 30 * 86400, timezone.utc).isoformat()
            self.top_barred().load([r.get("data") for r in await self.db.select("top_shadows", None, order="em.desc", limit=20000, gte={"em": since})])
        except Exception as e:
            log.warning("laboratório do top traders não carregou: %s", str(e)[:120])

    def top_lab(self, pf) -> dict:
        from . import toplab
        now, cache = time.time(), self.__dict__.setdefault("_top_lab", {})
        hit = cache.get(pf.user_id)
        if hit and now - hit[0] < 30:
            return hit[1]
        trades = pf.trades(100000)
        out = toplab.study(trades, pf.aba_of)
        out["barradas"] = self.top_barred().study()
        snap = self.ghosts_merged(pf, "ghosts", trades)
        out["saidas"] = {"yours": snap.get("yours") or {}, "variants": sorted([v for v in snap.get("variants") or [] if v.get("trades")], key=lambda v: -(v.get("avg_sol") or 0))[:14]}
        opts = ("pump_size_by_trader", "pump_size_by_score")
        out["opcoes"] = {k: bool(getattr(pf.cfg, k, False)) for k in opts}
        # 0.32.328: liga de candidatos (quem ganhou a vaga pelo resultado de quem copia e quem perdeu)
        out["liga"] = {"ligada": bool(getattr(pf.cfg, "pump_liga_on", True)), **(getattr(pf, "liga_count", None) or {}),
                       "fora": [{"wallet": w, "motivo": m} for w, m in list((getattr(pf, "liga_out", None) or {}).items())[:40]]}
        # 0.32.275: o que a regra "Copiar só quem dá resultado" faria com cada trader agora
        for x in out.get("traders") or []:
            n, m = pf.edge_stats().get(x["wallet"], (0, 0.0))
            x["regra"] = {"n": n, "media": round(m, 2), "real": pf.edge_why(x["wallet"], True), "ficticia": pf.edge_why(x["wallet"], False)}
        cache[pf.user_id] = (now, out)
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

    async def shadow_save_open(self) -> int:
        """0.31.99 (item 1): grava as sombras ainda abertas, para continuarem medindo depois de um reinício."""
        n = 0
        for m, s in list((self.__dict__.get("shadows") or {}).items()):
            if s.get("ret") is None and not s.get("_saved"):
                try:
                    await self.db.insert("base_shadows", {"mint": m, "data": {k: v for k, v in s.items() if k != "_saved"}},
                                         upsert=True, on_conflict="mint")
                    s["_saved"] = True
                    n += 1
                except Exception as e:
                    log.warning("sombra aberta não gravou: %s", str(e)[:120])
                    break
        return n

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
                if now - s["t0"] > self.SHADOW_S + 180:
                    # 0.31.99: passou da hora da foto de 15 min (ex.: servidor reiniciou) — medir agora mentiria; descarta
                    sh.pop(m, None)
                    continue
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
                await self.shadow_save_open()                      # 0.31.99: sobrevive ao reinício
                await self.shadow_tick()
            except Exception as e:
                log.warning("entradas sombra: %s", str(e)[:160])
            await asyncio.sleep(60)

    # ------------------------------------------------------------------ log de análise dos robôs (0.31.89)
    RLOG_NAMES = {"copia": "Cópia de traders", "base": "Base da pump.fun (compra automática)", "elite": "Maiores traders (compra automática)",
                  "calls": "Calls quentes"}

    # ------------------------------------------------------------------ calls quentes (0.31.94)
    def _call_label(self, w: str) -> tuple[str, str]:
        if w in self.elite.wallets():
            return self.elite.label(w), "maiores traders"
        for e in list(self.engines.values()):
            if w in (getattr(e, "study", None) or []):
                nick = (getattr(e, "study_names", None) or {}).get(w) if isinstance(getattr(e, "study_names", None), dict) else None
                return nick or f"{w[:4]}…{w[-4:]}", "carteira em estudo"
        return f"{w[:4]}…{w[-4:]}", "trader copiado"

    def _risk_of(self, mint: str):
        rk = (self.market.tokens.get(mint) or {}).get("risk")
        try:
            return float(rk.get("score")) if isinstance(rk, dict) and rk.get("score") is not None else (float(rk) if rk is not None else None)
        except (TypeError, ValueError):
            return None

    def _bl(self, mint: str) -> bool:
        tk = self.market.tokens.get(mint) or {}
        return mint in self.market.blacklist or (tk.get("creator") in self.market.blacklist if tk.get("creator") else False)

    def calls_on_trade(self, w: str, ev: dict, t: float | None = None) -> dict | None:
        t = time.time() if t is None else t
        label, fonte = self._call_label(w)
        tk = self.market.tokens.get(ev.get("mint")) or {}
        ev = dict(ev, symbol=ev.get("symbol") or tk.get("symbol"))
        c = self.calls.on_trade(w, ev, t, label, fonte, PumpFun.price_of(ev))
        if c is None:
            return None
        v = self.calls.verdict(c, self.calls.callers(), self._risk_of, self._bl)
        c["veredito_na_call"] = v
        self._calls_auto(c, v, t)
        for e in list(self.engines.values()):
            if getattr(e, "role", "user") == "admin":
                e.rlog("calls", c["id"], (c.get("symbol") or c["mint"][:6]) + " · " + label,
                       None if v["verdict"] == "chance alta" else f"veredito {v['verdict']} ({v['chance']}%): " + "; ".join(v["why"][:2]), t)
        return c

    def _calls_auto(self, c: dict, v: dict, t: float) -> None:
        """0.31.99 (item 4): compra automática das Calls quentes — só na fictícia, só admin com a opção ligada, veredito
        acima do mínimo, no máx. N por hora, com as proteções das automáticas (valor, stop, limites do dia)."""
        for e in list(self.engines.values()):
            cfg = e.cfg
            if getattr(e, "role", "user") != "admin" or not getattr(cfg, "pump_calls_auto_on", False):
                continue
            if v["chance"] < int(getattr(cfg, "pump_calls_auto_min", 65)) or v["verdict"] in ("lixo", "fraco"):
                continue
            done = e.__dict__.setdefault("_calls_done", [])
            done[:] = [x for x in done if t - x < 3600]
            if len(done) >= int(getattr(cfg, "pump_calls_auto_max_h", 3)):
                e.rlog("calls", c["id"] + ":auto", c.get("symbol") or c["mint"][:6], f"compra automática: limite de {len(done)} por hora", t)
                continue
            r = e.manual_buy(c["mint"], t, auto=f"call de {c.get('label')} ({v['chance']}%)", origem="calls",
                             info={"veredito": v["verdict"], "chance": v["chance"], "why": v["why"], "caller": c["wallet"], "call": c["id"]})
            if r.get("auto_id"):
                done.append(t)
                e._emit(f"Calls quentes: compra automática (fictícia) em {c.get('symbol') or c['mint'][:6]} — call de {c.get('label')} ({v['chance']}%)")

    async def calls_tick(self, now: float | None = None) -> int:
        now = time.time() if now is None else now
        svc = getattr(self.monitor, "svc", None) if self.monitor else None
        mints = self.calls.open_mints(now)
        if mints and svc is not None:
            for i in range(0, len(mints), 100):
                chunk = mints[i:i + 100]
                pump = [m for m in chunk if svc.is_pump(m)]
                rest = await svc._curve_prices(pump, public_first=True) if pump else []
                rest += [m for m in chunk if m not in pump]
                if rest:
                    await svc._fetch_prices(list(dict.fromkeys(rest))[:90])
        n = self.calls.tick(lambda m: (self.market.tokens.get(m) or {}).get("price"), now)
        for cid in list(self.calls.dirty)[:300]:
            self.calls.dirty.discard(cid)
            c = self.calls.calls.get(cid)
            if c is None:
                continue
            if not c.get("symbol"):
                c["symbol"] = (self.market.tokens.get(c["mint"]) or {}).get("symbol")
            try:
                await self.db.insert("calls", {"id": cid, "em": datetime.fromtimestamp(c["t"], timezone.utc).isoformat(), "data": c},
                                     upsert=True, on_conflict="id")
            except Exception as e:
                log.warning("call não gravou: %s", str(e)[:120])
                break
        return n

    async def calls_loop(self) -> None:
        await asyncio.sleep(60)
        while True:
            try:
                await self.calls_tick()
            except Exception as e:
                log.warning("calls quentes: %s", str(e)[:160])
            await asyncio.sleep(30)

    # ------------------------------------------------------------------ Aba do Bruxo (0.32.41)
    def bruxo_flow_base(self, now: float | None = None) -> dict:
        """Média inicial dos tokens novos (Base da pump.fun): quanto o market cap sobe por minuto no 1º e nos 5 primeiros
        minutos. É a régua do "volume de compra acima da média inicial" do prompt do Bruxo."""
        now = time.time() if now is None else now
        if now - self._bx_base[0] < 300:
            return self._bx_base[1]
        f1, f5 = [], []
        for r in list(self.lab.done)[-5000:]:
            m0, sn = r.get("mcap0"), r.get("snaps") or {}
            if not m0 or r.get("label") in ("bundle", "nasceu graduado", "sem dado"):
                continue
            if sn.get("1"):
                f1.append(min(300.0, max(0.0, sn["1"] - m0)))
            if sn.get("5"):
                f5.append(min(300.0, max(0.0, (sn["5"] - m0) / 5)))
        base = {"m1": round(sum(f1) / len(f1), 2) if len(f1) >= 30 else None, "n1": len(f1),
                "m5": round(sum(f5) / len(f5), 2) if len(f5) >= 30 else None, "n5": len(f5)}
        self._bx_base = (now, base)
        return base

    def bruxo_facts(self, mint: str, sol: float, now: float) -> dict:
        tk = self.market.tokens.get(mint) or {}
        age = (now - float(tk["created_t"])) / 60 if tk.get("creator") and tk.get("created_t") else None
        live = self.lab.live.get(mint) or {}
        m0 = live.get("mcap0") or 28.0
        mc = tk.get("mcap_sol")
        flow = round((mc - m0) / max(age, 0.25), 2) if mc and age is not None else None
        base = self.bruxo_flow_base(now)
        fb = (base.get("m1") if age is not None and age <= 2.5 else base.get("m5")) or base.get("m1")
        dev = None
        cr = tk.get("creator")
        if cr:
            dp = ((self.market.wallets.get(cr) or {}).get("pos") or {}).get(mint) or {}
            dev = round(float(dp.get("tok") or 0) / 1e9 * 100, 2)
        grad = tk.get("pool") in ("pumpswap", "pump-amm") or "pumpswap" in (tk.get("dexes") or [])
        return {"age_min": None if age is None else round(age, 2), "flow": flow, "flow_base": fb, "mcap": mc,
                "dev_pct": dev, "top10": tk.get("top10_pct") if now - float(tk.get("top10_t") or 0) < 120 else None,
                "trader_sol": round(sol, 4), "creator": cr, "graduated": grad}

    def _bx_tops(self, e) -> set:
        return set(getattr(e, "followed", None) or []) | set(self.elite.wallets())

    async def bruxo_on_trade(self, w: str, ev: dict, t: float | None = None) -> dict | None:
        """Compra de top trader → sinal da Aba do Bruxo (acompanhado 30 min) e entrada de quem ligou a aba. Venda de top
        trader → as posições da aba nesse token saem junto (se a opção estiver ligada)."""
        t = time.time() if t is None else t
        kind, mint = ev.get("txType"), ev.get("mint")
        if not mint or kind not in ("buy", "sell"):
            return None
        admins = [e for e in list(self.engines.values()) if getattr(e, "role", "user") == "admin"]
        tops = [e for e in admins if w in self._bx_tops(e)]
        if not tops:
            return None
        label = self._call_label(w)[0]
        if kind == "sell":
            for e in tops:
                try:
                    e.bruxo_sell(w, mint, label, t)
                except Exception as ex:
                    log.warning("aba do bruxo (venda): %s", str(ex)[:120])
            return None
        sol = float(ev.get("solAmount") or 0)
        f = self.bruxo_facts(mint, sol, t)
        if f["age_min"] is None or f["age_min"] > 30:
            return None                         # só moeda nova vira sinal (o estudo é sobre elas)
        tk = self.market.tokens.get(mint) or {}
        s, new = self.bruxo.on_buy(w, label, mint, tk.get("symbol") or ev.get("symbol"), sol, PumpFun.price_of(ev) or tk.get("price"),
                                   tk, f["age_min"], {k: f.get(k) for k in ("flow", "flow_base", "mcap", "dev_pct")}, t)
        if not new:
            return s
        want = [e for e in tops if getattr(e.cfg, "pump_bx_on", False)]
        if want and f["top10"] is None and not f["graduated"] and f["age_min"] <= max(float(getattr(e.cfg, "pump_bx_max_age_min", 5)) for e in want):
            try:
                await want[0].holders_check(mint)       # concentração dos maiores detentores (RPC grátis, cache 60 s)
            except Exception:
                pass
            f = self.bruxo_facts(mint, sol, time.time())
        s["filtros"] = {k: f.get(k) for k in ("age_min", "flow", "flow_base", "mcap", "dev_pct", "top10", "trader_sol")}
        for e in tops:
            try:
                why = e.bruxo_entry(s, f, t)
            except Exception as ex:
                why = f"erro: {str(ex)[:80]}"
            self.bruxo.decide(s, e.user_id, why)
        self.jev_shadow(s, f)
        return s

    # ---------------------------------------------------------------- 0.32.83: Jev em modo sombra (só opina, nunca compra)
    def jev_wanted(self) -> bool:
        if not self.system_keys.get("jev_api_key"):
            return False
        return any(getattr(e, "role", "user") == "admin" and getattr(e.cfg, "pump_jev_on", True) for e in self.engines.values())

    def jev_shadow(self, s: dict, facts: dict | None = None) -> bool:
        """Pergunta ao Jev em segundo plano (não atrasa o sinal nem a entrada). A resposta fica em s["jev"]."""
        if s.get("jev") or not self.jev_wanted():
            return False
        st = self.__dict__.setdefault("jev_stats", {})
        day = time.strftime("%Y-%m-%d", time.gmtime())
        if st.get("dia") != day:
            st.clear()
            st.update(dia=day, calls=0, erros=0, ms=0, tokens_in=0, ultimo_erro=None)
        if st["calls"] >= jev.DAY_MAX:
            return False
        st["calls"] += 1
        s["jev"] = {"pendente": True}
        extra = {"creator_tokens": ((facts or {}).get("creator") or {}).get("tokens") if isinstance((facts or {}).get("creator"), dict) else None,
                 "graduated": (facts or {}).get("graduated")}
        try:
            asyncio.get_running_loop().create_task(self._jev_run(s, jev.state_for(s, extra)))
        except RuntimeError:
            s.pop("jev", None)
            return False
        return True

    async def _jev_run(self, s: dict, state: dict) -> None:
        ORIGIN.set("JEV (sombra)")                      # 0.32.188: gasto por aba
        st = self.jev_stats
        key = self.system_keys.get("jev_api_key") or ""
        out: dict = {}
        for i in range(2):
            try:
                out = await jev.ask(self.http, key, state)
                break
            except Exception as e:
                msg = str(e)[:160].replace(key, "***") if key else str(e)[:160]
                out = {"erro": msg}
                if not any(c in msg for c in ("429", "529")) or i:
                    break
                await asyncio.sleep(2)
        out["em"] = time.time()
        s["jev"] = out
        if out.get("erro"):
            st["erros"] = st.get("erros", 0) + 1
            st["ultimo_erro"] = out["erro"]
        else:
            st["ms"] = st.get("ms", 0) + int(out.get("ms") or 0)
            st["tokens_in"] = st.get("tokens_in", 0) + int(out.get("tokens_in") or 0)
        self.bruxo.dirty.add(s["id"])
        await self._jev_save_decision(s, state, out)
        await self._jev_usage_save("ao_vivo")

    # ---------------------------------------------------------------- 0.32.85: toda análise do Jev no Supabase
    async def _jev_save_decision(self, s: dict, state: dict, out: dict) -> None:
        p = out.get("p") or {}
        row = {"em": datetime.fromtimestamp(out.get("em") or time.time(), timezone.utc).isoformat(),
               "fonte": "lancamento" if s.get("kind") == "lancamento" else "bruxo", "sinal_id": str(s.get("id") or ""),
               "mint": s.get("mint"), "symbol": s.get("symbol"), "acao": out.get("acao"),
               "p_entrar": p.get("entrar"), "p_esperar": p.get("esperar"), "p_evitar": p.get("evitar"),
               "confianca": out.get("conf"), "qualidade": out.get("qualidade"), "armadilha": out.get("armadilha"),
               "ms": out.get("ms"), "tokens_in": out.get("tokens_in"), "erro": out.get("erro"), "estado": state or {}, "modelo": out.get("modelo")}
        try:
            await self.db.insert("jev_decisions", row)
        except Exception as e:
            log.warning("decisão do Jev não gravou no banco: %s", str(e)[:120])

    async def _jev_usage_save(self, tipo: str, force: bool = False) -> None:
        """Uso do dia (perguntas, erros, tokens, tempo) em jev_usage; no máximo 1 gravação a cada 30 s por tipo."""
        last = self.__dict__.setdefault("_jev_usage_t", {})
        if not force and time.time() - last.get(tipo, 0) < 30:
            return
        last[tipo] = time.time()
        if tipo in ("ao_vivo", "trade"):
            st = self.jt.stats if tipo == "trade" else getattr(self, "jev_stats", {}) or {}
            dia, row = st.get("dia"), {"calls": st.get("calls", 0), "erros": st.get("erros", 0),
                                       "tokens_in": st.get("tokens_in", 0), "ms": st.get("ms", 0)}
        else:
            bt = self._bt()
            dia, row = bt.get("dia"), {"calls": bt.get("calls_dia", 0), "erros": bt.get("erros_dia", 0),
                                       "tokens_in": bt.get("tokens_dia", 0), "ms": bt.get("ms_dia", 0)}
        if not dia:
            return
        try:
            await self.db.insert("jev_usage", dict(row, dia=dia, tipo=tipo, atualizado=datetime.now(timezone.utc).isoformat()),
                                 upsert=True, on_conflict="dia,tipo")
        except Exception as e:
            log.warning("uso do Jev não gravou no banco: %s", str(e)[:120])

    async def jev_usage_load(self) -> None:
        """Contadores de hoje voltam do banco (o limite por dia continua valendo depois de um reinício)."""
        day = time.strftime("%Y-%m-%d", time.gmtime())
        try:
            rows = await self.db.select("jev_usage", {"dia": day})
        except Exception as e:
            log.warning("uso do Jev não carregou: %s", str(e)[:120])
            return
        for r in rows or []:
            if r.get("tipo") == "ao_vivo":
                st = self.__dict__.setdefault("jev_stats", {})
                st.update(dia=day, calls=int(r.get("calls") or 0), erros=int(r.get("erros") or 0),
                          tokens_in=int(r.get("tokens_in") or 0), ms=int(r.get("ms") or 0), ultimo_erro=st.get("ultimo_erro"))
            elif r.get("tipo") == "passado":
                self._bt().update(dia=day, calls_dia=int(r.get("calls") or 0), erros_dia=int(r.get("erros") or 0),
                                  tokens_dia=int(r.get("tokens_in") or 0), ms_dia=int(r.get("ms") or 0))
            elif r.get("tipo") == "trade":
                self.jt.day(time.time()).update(calls=int(r.get("calls") or 0), erros=int(r.get("erros") or 0),
                                                tokens_in=int(r.get("tokens_in") or 0), ms=int(r.get("ms") or 0))

    # ---------------------------------------------------------------- 0.32.84: Jev estuda os casos passados (backtest)
    def _bt(self) -> dict:
        return self.__dict__.setdefault("jev_bt", {"on": False, "fase": "parado", "msg": "", "feitos": {}, "total": {},
                                                   "dia": "", "calls_dia": 0, "erros": 0, "cases": {}, "task": None})

    async def hist_select(self, table: str, filters: dict | None, tcol: str, limit: int, since: str | None = None) -> list[dict]:
        """0.32.271: linhas mais novas primeiro, juntando o Supabase (dias recentes) e o arquivo (Postgres da VPS) quando a
        consulta pede mais dias do que o Supabase guarda (`arquivo.SPECS`). Arquivo fora do ar = só o Supabase."""
        from .arquivo import SPEC, _epoch
        rows = await self.db.select(table, filters, order=f"{tcol}.desc", limit=limit, gte={tcol: since} if since else None) or []
        arq, spec = getattr(self, "arquivo", None), SPEC.get(table)
        if arq is None or spec is None or len(rows) >= limit:
            return rows
        since_t = _epoch(since, "iso") if since else None
        if since_t is not None and since_t >= time.time() - spec["dias"] * 86400:
            return rows
        try:
            eq = {"tabela": table, **{f"dados->>{k}": v for k, v in (filters or {}).items()}}
            extra = await arq.rest.select("arquivo", eq, order="t.desc", limit=limit - len(rows), columns="dados",
                                          gte={"t": since_t} if since_t is not None else None) or []
        except Exception as e:
            log.warning("arquivo: leitura de %s: %s", table, str(e)[:120])
            return rows
        have = {r.get(spec["pk"]) for r in rows}
        return rows + [x["dados"] for x in extra if isinstance(x.get("dados"), dict) and x["dados"].get(spec["pk"]) not in have]

    async def _bt_pages(self, table: str, columns: str, order: str, page: int = 1000):
        off = 0
        while True:
            rows = await self.db.select(table, None, order=order, limit=page, columns=columns, offset=off)
            if not rows:
                return
            yield rows
            if len(rows) < page:
                return
            off += len(rows)

    async def jev_bt_load(self) -> None:
        """No início só lê se o estudo estava ligado. 0.32.192 (banco fora do ar em 04/11): os 120 mil casos guardados em
        jev_backtest eram relidos inteiros a cada reinício (115 MB); agora só quando a tela do JEV pede o passado ou quando
        o estudo volta a rodar (`jev_bt_cases`)."""
        bt = self._bt()
        try:
            for r in await self.db.select("jev_backtest", {"id": "_run"}, columns="id,fonte,data") or []:
                bt["want_on"] = bool((r.get("data") or {}).get("on"))
        except Exception as e:
            log.warning("estudo do passado do Jev não carregou: %s", str(e)[:120])
        if bt.get("want_on") and self.system_keys.get("jev_api_key"):
            self.jev_bt_set(True, quiet=True)

    async def jev_bt_cases(self) -> None:
        """Carrega os casos guardados uma vez (sob demanda)."""
        bt = self._bt()
        if bt.get("loaded"):
            return
        lock = bt.setdefault("lock", asyncio.Lock())
        async with lock:
            if bt.get("loaded"):
                return
            try:
                async for rows in self._bt_pages("jev_backtest", "id,fonte,data", "em.asc"):
                    for r in rows:
                        if r.get("fonte") != "_estado" and isinstance(r.get("data"), dict):
                            bt["cases"].setdefault(r["id"], dict(r["data"], fonte=r["fonte"]))
                arq = getattr(self, "arquivo", None)
                if arq is not None:                        # 0.32.225: os casos antigos ficam no Postgres da VPS
                    async for rows in arq.pages("jev_backtest"):
                        for r in rows:
                            if r.get("fonte") != "_estado" and isinstance(r.get("data"), dict):
                                bt["cases"].setdefault(r["id"], dict(r["data"], fonte=r["fonte"]))
            except Exception as e:
                log.warning("estudo do passado do Jev não carregou: %s", str(e)[:120])
                return
            bt["feitos"] = {}
            for c in bt["cases"].values():
                bt["feitos"][c["fonte"]] = bt["feitos"].get(c["fonte"], 0) + 1
            bt["loaded"] = True

    def jev_bt_set(self, on: bool, quiet: bool = False) -> dict:
        bt = self._bt()
        if on and not self.system_keys.get("jev_api_key"):
            return {"error": "Cole a chave do Jev em Administração → Chaves do sistema."}
        bt["on"] = on
        if on and not (bt.get("task") and not bt["task"].done()):
            try:
                bt["task"] = asyncio.get_running_loop().create_task(self._jev_bt_run())
            except RuntimeError:
                bt["on"] = False
        if not on:
            bt["fase"], bt["msg"] = "parado", "parado por você"
        if not quiet:
            try:
                asyncio.get_running_loop().create_task(self.db.insert("jev_backtest", {"id": "_run", "fonte": "_estado",
                    "em": datetime.now(timezone.utc).isoformat(), "data": {"on": on}}, upsert=True, on_conflict="id"))
            except Exception:
                pass
        return {"ok": True, "on": bt["on"]}

    async def _bt_cases(self, fonte: str):
        """Casos de cada fonte, do mais antigo para o mais novo (desde o início do que está guardado)."""
        if fonte == "bruxo":
            arq = getattr(self, "arquivo", None)
            if arq is not None:                            # 0.32.271: sinais com mais de 7 dias ficam no Postgres da VPS
                async for rows in arq.pages("bruxo_signals"):
                    for r in rows:
                        c = jev.case_bruxo(r.get("data") or {}) if isinstance(r.get("data"), dict) else None
                        if c:
                            yield c
            async for rows in self._bt_pages("bruxo_signals", "id,data", "em.asc"):
                for r in rows:
                    c = jev.case_bruxo(r.get("data") or {}) if isinstance(r.get("data"), dict) else None
                    if c:
                        yield c
        elif fonte == "explorar":
            async for rows in self._bt_pages("base_shadows", "mint,data", "em.asc"):
                for r in rows:
                    c = jev.case_explorar(r["mint"], r.get("data") or {}) if isinstance(r.get("data"), dict) else None
                    if c:
                        yield c
        elif fonte == "base":
            arq = getattr(self, "arquivo", None)
            if arq is not None:                            # 0.32.225: tokens com mais de 7 dias ficam no Postgres da VPS
                async for rows in arq.pages("token_life"):
                    for r in rows:
                        c = jev.case_base(r["mint"], r.get("data") or {}, r.get("criado_em")) if isinstance(r.get("data"), dict) else None
                        if c:
                            yield c
            async for rows in self._bt_pages("token_life", "mint,data,criado_em", "criado_em.asc"):
                for r in rows:
                    c = jev.case_base(r["mint"], r.get("data") or {}, r.get("criado_em")) if isinstance(r.get("data"), dict) else None
                    if c:
                        yield c

    async def _jev_bt_run(self, gap_s: float | None = None, rest_s: float = 6 * 3600) -> None:
        """Pergunta ao Jev caso a caso (meio segundo entre perguntas, até jev.BT_DAY_MAX por dia), grava em jev_backtest e
        repete a cada 6 h para pegar os casos novos. Nunca compra nada."""
        ORIGIN.set("JEV (sombra)")
        bt = self._bt()
        gap = jev.BT_GAP_S if gap_s is None else gap_s
        await self.jev_bt_cases()                          # 0.32.192: casos guardados só agora (não no início)
        while bt["on"]:
            for fonte in jev.BT_SOURCES:
                bt["fase"], bt["msg"] = fonte, "lendo os casos guardados"
                batch, total, fails = [], 0, 0
                async for c in self._bt_cases(fonte):
                    total += 1
                    bt["total"][fonte] = max(bt["total"].get(fonte, 0), total)
                    if not bt["on"]:
                        break
                    if c["id"] in bt["cases"]:
                        continue
                    day = time.strftime("%Y-%m-%d", time.gmtime())
                    if bt["dia"] != day:
                        bt.update(dia=day, calls_dia=0, erros_dia=0, tokens_dia=0, ms_dia=0)
                    while bt["calls_dia"] >= jev.BT_DAY_MAX and bt["on"]:
                        bt["msg"] = f"limite de {jev.BT_DAY_MAX} perguntas do dia; continua depois da meia-noite (UTC)"
                        await asyncio.sleep(300)
                        if time.strftime("%Y-%m-%d", time.gmtime()) != bt["dia"]:
                            bt.update(dia=time.strftime("%Y-%m-%d", time.gmtime()), calls_dia=0, erros_dia=0, tokens_dia=0, ms_dia=0)
                    key = self.system_keys.get("jev_api_key") or ""
                    if not key:
                        bt["on"], bt["msg"] = False, "sem a chave do Jev"
                        break
                    bt["calls_dia"] += 1
                    try:
                        out = await jev.ask(self.http, key, c["state"])
                        fails = 0
                    except Exception as e:
                        msg = str(e)[:160].replace(key, "***")
                        bt["erros"] += 1
                        bt["erros_dia"] = bt.get("erros_dia", 0) + 1
                        bt["ultimo_erro"] = msg
                        fails += 1
                        if fails >= 20:
                            bt["on"], bt["msg"] = False, "parou: 20 erros seguidos (" + msg + ")"
                            break
                        await asyncio.sleep(30 if ("429" in msg or "529" in msg) else 2)
                        continue
                    bt["tokens_dia"] = bt.get("tokens_dia", 0) + int(out.get("tokens_in") or 0)
                    bt["ms_dia"] = bt.get("ms_dia", 0) + int(out.get("ms") or 0)
                    row = jev.compact(c, out)
                    bt["cases"][c["id"]] = dict(row, fonte=fonte)
                    bt["feitos"][fonte] = bt["feitos"].get(fonte, 0) + 1
                    bt["ultimo"] = time.time()
                    bt["msg"] = "perguntando ao Jev"
                    batch.append({"id": c["id"], "fonte": fonte, "data": row,
                                  "em": datetime.fromtimestamp(c["t"], timezone.utc).isoformat()})
                    if len(batch) >= 50:
                        await self._bt_flush(batch)
                        batch = []
                    await asyncio.sleep(gap)
                await self._bt_flush(batch)
                if not bt["on"]:
                    break
            if not bt["on"]:
                break
            bt["fase"], bt["msg"] = "em dia", "todos os casos guardados já foram analisados; confere de novo a cada 6 h"
            await asyncio.sleep(rest_s)
        if bt["fase"] != "parado":
            bt["fase"] = "parado"

    async def _bt_flush(self, batch: list[dict]) -> None:
        if not batch:
            return
        try:
            await self.db.insert("jev_backtest", batch, upsert=True, on_conflict="id")
        except Exception as e:
            log.warning("estudo do passado do Jev não gravou: %s", str(e)[:120])
            self._bt()["msg"] = "não gravou no banco: " + str(e)[:80]
        await self._jev_usage_save("passado", force=True)

    def jev_bt_view(self, fonte: str, hours: float, saida: str) -> dict:
        bt = self._bt()
        if not bt.get("loaded") and fonte != "ao_vivo":        # 0.32.192: carrega na primeira vez que a tela pede
            t = bt.get("load_task")
            if not t or t.done():
                try:
                    bt["load_task"] = asyncio.get_running_loop().create_task(self.jev_bt_cases())
                except RuntimeError:
                    pass
        now = time.time()
        rows = [c for c in bt["cases"].values() if (fonte == "todos" or c.get("fonte") == fonte)
                and (not hours or now - float(c.get("t") or 0) <= hours * 3600)]
        rows.sort(key=lambda c: c.get("t") or 0, reverse=True)
        st = jev.study_rows(rows, saida)
        linhas = [{"t": c.get("t"), "fonte": c.get("fonte"), "kind": c.get("kind"), "mint": c.get("mint"), "symbol": c.get("symbol"),
                   "jev": c.get("jev"), "regra": c.get("regra"), "res_all": c.get("res"), "res": jev.pick(c.get("res") or {}, saida),
                   "pico": c.get("pico"), "n": c.get("n")} for c in rows[:500]]
        return {"estudo": st, "linhas": linhas}

    def jev_bt_status(self) -> dict:
        bt = self._bt()
        return {k: bt.get(k) for k in ("on", "fase", "msg", "feitos", "total", "calls_dia", "erros", "ultimo", "ultimo_erro", "tokens_dia")} | {
            "limite_dia": jev.BT_DAY_MAX, "fontes": jev.BT_SOURCES, "carregado": bool(bt.get("loaded"))}

    async def hold_market(self, D: dict) -> None:
        """0.32.103 (pedido do dono): volume, compras × vendas e valor de mercado de agora nas linhas dos detentores.
        DexScreener, no máximo 1 vez a cada 30 s e 90 tokens, só ao abrir a tela."""
        L = D.get("linhas") or []
        now = time.time()
        svc = getattr(self.monitor, "svc", None) if self.monitor else None
        old = [x["mint"] for x in L if now - float((self.market.tokens.get(x["mint"]) or {}).get("vol_t") or 0) > 60][:90]
        if old and svc is not None and now - self.__dict__.get("_hold_ds_t", 0) >= 30:
            self._hold_ds_t = now
            try:
                await svc._fetch_prices(old, set_price=False)
            except Exception as e:
                log.warning("volume dos detentores: %s", str(e)[:120])
        for x in L:
            tk = self.market.tokens.get(x["mint"]) or {}
            v = tk.get("vol") or {}
            nt = int(v.get("buys_h24") or 0) + int(v.get("sells_h24") or 0)
            px = tk.get("price")
            x.update(vol24=v.get("h24"), b5=v.get("buys_m5"), s5=v.get("sells_m5"), medio_usd=round(v["h24"] / nt, 2) if nt and v.get("h24") else None,
                     mc=round(x["mc0"] * px / x["px0"], 2) if px and x.get("px0") and x.get("mc0") else tk.get("mcap_sol"))
            if x.get("top10") is None:
                x["top10"] = tk.get("top10_pct")

    def jev_state(self, pf: PumpFun, hours: float = 24, exit_min: str = "10", fonte: str = "ao_vivo",
                  hold_min: int = detentores.MIN_HOLDERS, hold_cresc: float = detentores.MIN_GROW_PCT, hold_show: int = 0) -> dict:
        now = time.time()
        hours = hours or 24 * 365
        uid = pf.user_id
        sigs = self.bruxo.recent(hours, now)
        rows = []
        for s in sigs:
            j = s.get("jev")
            if not j:
                continue
            d = (s.get("decisoes") or {}).get(uid)
            s["entrou_regra"] = bool(d and d.get("entrou"))
            rows.append({k: s.get(k) for k in ("id", "em", "t", "kind", "mint", "symbol", "names", "age_min", "created_t", "holders",
                                                "filtros", "marks", "peak_pct", "peak_s", "low_pct", "hit100_s", "stop30_s", "done")}
                        | {"jev": j, "entrou_regra": s["entrou_regra"], "res": jev.sim_result(s, exit_min)})
        st = dict(getattr(self, "jev_stats", {}) or {})
        if st.get("calls"):
            ok = max(1, st["calls"] - st.get("erros", 0))
            st["ms_medio"] = round(st.get("ms", 0) / ok)
            st["custo_usd"] = round(st.get("tokens_in", 0) / 1e6 * 0.042, 5)
        out = {"modelo": jev.JEV_MODEL, "h5": jevtrade.h5_study(list(self.jt.h5.values()) if "jt" in self.__dict__ else []), "contagem_v2": self.__dict__.get("hv2"), "chave": bool(self.system_keys.get("jev_api_key")), "ligado": bool(getattr(pf.cfg, "pump_jev_on", True)),
               "ativo": self.jev_wanted(), "limite_dia": jev.DAY_MAX, "uso": st, "saida_min": exit_min, "fonte": fonte,
               "passado": self.jev_bt_status(), "detentores": detentores.study(sigs, exit_min, hold_min, hold_cresc, show=hold_show)}
        if fonte == "ao_vivo":
            return out | {"estudo": jev.study([s for s in sigs if s.get("jev")], exit_min), "linhas": rows[:500]}
        return out | self.jev_bt_view(fonte, hours, exit_min)

    async def bruxo_tick(self, now: float | None = None) -> int:
        now = time.time() if now is None else now
        await self._prices_for(self.bruxo.open_mints(now))
        self.bruxo_launch_scan(now)
        n = self.bruxo.tick(lambda m: (self.market.tokens.get(m) or {}).get("price"), now)
        for s, k in self.bruxo.holders_due(now):              # 0.32.82: detentores no sinal e aos 1/5/10/25 min
            try:
                s["holders"][k] = await self.holders_count(s["mint"])
            except Exception:
                s["holders"][k] = None
            if (s["holders"][k] or 0) >= self.bruxo.HOLD_WATCH and "top10" not in s:     # 0.32.103: uma vez por token
                await self._bruxo_top10(s, now)
            px = (self.market.tokens.get(s["mint"]) or {}).get("price")   # 0.32.86: preço de cada leitura (entrada simulada da regra)
            if px and s.get("px0"):
                s.setdefault("hpx", {})[k] = round((px / s["px0"] - 1) * 100, 1)
            self.bruxo.dirty.add(s["id"])
        for sid in list(self.bruxo.dirty)[:300]:
            self.bruxo.dirty.discard(sid)
            s = self.bruxo.signals.get(sid)
            if s is None:
                continue
            try:
                await self.db.insert("bruxo_signals", {"id": sid, "em": s["em"], "data": s}, upsert=True, on_conflict="id")
            except Exception as e:
                log.warning("sinal da aba do bruxo não gravou: %s", str(e)[:120])
                self.bruxo.dirty.add(sid)
                break
        self.bruxo.trim(now)
        return n

    async def _bruxo_top10(self, s: dict, now: float) -> None:
        s["top10"] = None
        svc = getattr(self.monitor, "svc", None) if self.monitor else None
        try:
            if svc is not None:
                await asyncio.wait_for(svc.holders_check(s["mint"]), timeout=3)
            s["top10"] = (self.market.tokens.get(s["mint"]) or {}).get("top10_pct")
            s["dev_pct"] = self.bruxo_facts(s["mint"], 0.0, now).get("dev_pct")
        except Exception:
            pass

    async def _prices_for(self, mints: list[str]) -> None:
        svc = getattr(self.monitor, "svc", None) if self.monitor else None
        if not mints or svc is None:
            return
        for i in range(0, len(mints), 100):
            chunk = mints[i:i + 100]
            pump = [m for m in chunk if svc.is_pump(m)]
            rest = await svc._curve_prices(pump, public_first=True) if pump else []
            rest += [m for m in chunk if m not in pump]
            if rest:
                await svc._fetch_prices(list(dict.fromkeys(rest))[:90])

    # ---------------------------------------------------------------- 0.32.87: Jev Trade (simulação, nunca compra de verdade)
    def jt_cfg(self) -> dict:
        """0.32.102: filtros do Jev Trade. A simulação é uma só: para cada opção vale o valor do admin que a mudou por último
        na tela (`_ov_user`); se nenhum mudou, o padrão. Devolve {nome do filtro: valor} + `_de` (quem definiu cada um)."""
        out, de = {}, {}
        for key, name in jevtrade.CFG_KEYS.items():
            best = None
            for e in getattr(self, "engines", {}).values():
                if getattr(e, "role", "user") != "admin":
                    continue
                when = (getattr(e, "_ov_user", None) or {}).get(key)
                if when and (best is None or str(when) > best[0]):
                    best = (str(when), getattr(e.cfg, key, None), getattr(e, "user_id", ""))
            if best and best[1] is not None:
                out[name], de[name] = best[1], best[2]
        out["_de"] = de
        return out

    def jt_wanted(self) -> bool:
        if not self.system_keys.get("jev_api_key"):
            return False
        return any(getattr(e, "role", "user") == "admin" and getattr(e.cfg, "pump_jt_on", True) for e in self.engines.values())

    async def _jt_jev(self, state: dict, questions: dict, now: float) -> dict | None:
        jt, key = self.jt, self.system_keys.get("jev_api_key") or ""
        if jt.jev_left(now) <= 0:
            return None
        st = jt.day(now)
        st["calls"] += 1
        for i in range(2):
            try:
                out = await jevtrade.ask(self.http, key, state, questions)
                st["ms"] += int(out.get("ms") or 0)
                st["tokens_in"] += int(out.get("tokens_in") or 0)
                return out
            except Exception as e:
                msg = str(e)[:160].replace(key, "***") if key else str(e)[:160]
                if i or not any(c in msg for c in ("429", "529")):
                    st["erros"] += 1
                    st["ultimo_erro"] = msg
                    return None
                await asyncio.sleep(2)
        return None

    async def _jt_scan(self, now: float) -> None:
        """Tokens novos vivos aos 5 min: conta os detentores uma vez; 40+ entram na observação."""
        jt, svc = self.jt, getattr(self.monitor, "svc", None) if self.monitor else None
        for r in jt.candidates(self.lab.live, getattr(self.market, "blacklist", None), now,
                                     getattr(self.market, "tokens", None))[:6]:
            if not jt.can_scan(now):
                break
            jt.note_scan(now)
            h = await self.holders_count(r["mint"])
            it = jt.on_checked(r, h, now, (self.market.creator_stats or {}).get(r.get("creator") or ""))
            if it is not None:                         # 0.32.91: a 1ª contagem (aos 5 min) também é uma leitura, com o preço
                tk0 = self.market.tokens.get(r["mint"]) or {}
                jt.add_read(it, h, tk0.get("price"), tk0.get("mcap_sol"), now)
            if it is not None and svc is not None:
                try:
                    await asyncio.wait_for(svc.holders_check(r["mint"]), timeout=3)      # top 10, uma vez por token
                except Exception:
                    pass

    async def _jt_read(self, it: dict, now: float) -> None:
        jt = self.jt
        aberta = it["estado"] == "aberta"
        d = jt.day(now)
        h = None
        if aberta and d["leituras"] < jevtrade.READS_DAY or d["leituras"] < jevtrade.READS_DAY * jevtrade.WATCH_SHARE:
            d["leituras"] += 1
            h = await self.holders_count(it["mint"])
        tk = self.market.tokens.get(it["mint"]) or {}
        jt.add_read(it, h, tk.get("price"), tk.get("mcap_sol"), now)
        if aberta and jt.holders_leaving(it) and tk.get("price"):        # 0.32.91: detentores saindo depois da entrada
            jt.sell(it, 1.0, tk["price"], now, f"detentores começaram a sair ({jevtrade.STRAT['saida_detentores_pct']:g}% abaixo do pico)")
            return
        if jt.holders_fell(it):
            if aberta and tk.get("price"):
                jt.sell(it, 1.0, tk["price"], now, f"detentores caíram {jevtrade.HOLD_DROP_PCT:g}% do pico")
            elif not aberta:
                jt.discard(it, f"detentores caíram {jevtrade.HOLD_DROP_PCT:g}% do pico", now)
            return
        out = await self._jt_jev(jevtrade.state_for(it, tk, now), jevtrade.Q_OUT if aberta else jevtrade.Q_IN, now)
        if out and out.get("modelo"):
            it["modelo"] = out["modelo"]
        if it["estado"] not in ("olhando", "aberta") or (out is None and aberta):
            return
        px = (self.market.tokens.get(it["mint"]) or {}).get("price")     # preço DEPOIS da resposta: é onde entraria de verdade
        (jt.on_exit if it["estado"] == "aberta" else jt.bruxo_entry)(it, out, px, now)

    @staticmethod
    def jt_wallet_rules(it: dict) -> dict:
        """0.32.96 (pedido do dono): a posição da carteira fictícia leva as MESMAS regras do Jev Trade (stop, empate, metade em
        +100%, stop móvel 25% abaixo do pico), executadas pelo motor a cada ~1 s e visíveis/ajustáveis no card da posição."""
        S = jevtrade.STRAT
        st = abs(float(it.get("stop") or 0)) or float(S["stop_pct"])
        return {"stop_pct": st, "tp_pct": 0.0, "boost_tp": None, "smart": False,
                "trail_on": True, "trail_start": float(S["trail_apos"]), "trail_dist": float(S["trail_pct"]),
                "trail_rel": float(S["trail_pct"]), "tp1_pct": float(S["parcial_em"]), "tp1_frac": float(S["parcial_frac"]) * 100,
                "be_after": float(S["empate_apos"]), "jt_rules": True,
                "max_hold_s": (jevtrade.MAX_HOLD_MIN + 10) * 60}

    def _jt_wallet_sync(self) -> None:
        """Posições do Jev Trade abertas antes da 0.32.96 (sem stop) recebem as regras; a parcial já feita conta como feita."""
        abertos = {x["mint"]: x for x in self.jt.items.values() if x.get("estado") == "aberta"}
        for pf in list(getattr(self, "engines", {}).values()):
            for p in (pf.positions() if hasattr(pf, "positions") else []):
                it = abertos.get(p.get("mint"))
                if it is None or p.get("real") or p.get("origem") != "jevtrade" or p.get("jt_rules"):
                    continue
                p.update(self.jt_wallet_rules(it))
                if it.get("parcial_feita") or float(p.get("proceeds") or 0) > 0:
                    p["tp1_done"] = True
                try:
                    pf._save_pos(p)
                except Exception:
                    pass

    def _jt_wallet(self, ev: str, it: dict, px: float | None, now: float, frac: float, why: str) -> None:
        """0.32.93 (pedido do dono): o Jev Trade entrou → a mesma entrada vai para a carteira FICTÍCIA de cada admin com
        "Também na carteira fictícia" ligado; cada venda do Jev Trade vende a mesma parte lá. Nunca vai para a REAL."""
        for uid, pf in list(getattr(self, "engines", {}).items()):
            if getattr(pf, "role", "user") != "admin" or not getattr(pf.cfg, "pump_jt_wallet", True) or not hasattr(pf, "manual_buy"):
                continue
            try:
                if ev == "abriu":
                    tk = pf.tokens.setdefault(it["mint"], {})
                    if px and not tk.get("price"):
                        tk.update(price=px, last_t=now, symbol=it.get("symbol"))
                    real = bool(getattr(pf.cfg, "pump_jt_real", False))        # 0.32.97: botão "Também na REAL" (OFF por padrão)
                    r = pf.manual_buy(it["mint"], t=now, auto="Jev Trade · " + why[:140], origem="jevtrade",
                                      target="both" if real else "sim",
                                      amt_sol=jevtrade.SOL, pos_rules=self.jt_wallet_rules(it))
                    it.setdefault("carteiras", {})[uid] = ((r or {}).get("sim") or (r or {}).get("error") or "") + (
                        f" · REAL: {r['real']}" if real and (r or {}).get("real") else "")
                    self.jt.dirty.add(it["id"])
                elif ev == "vendeu" and px:
                    for p in pf.positions():
                        if p.get("mint") == it["mint"] and not p.get("real") and p.get("origem") == "jevtrade" and not p.get("selling"):
                            if frac < 1.0:                 # parcial: o motor já faz a "venda em partes" (não vende duas vezes)
                                if p.get("tp1_done") or p.get("off_tp1"):
                                    continue
                                p["tp1_done"] = True
                            pf._sell(p, min(1.0, max(0.0, frac)), px, "Jev Trade · " + why[:120], now)
            except Exception as e:
                log.warning("jev trade → carteira fictícia: %s", str(e)[:120])

    async def jt_tick(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        jt = self.jt
        try:
            c = self.jt_cfg()
            c.pop("_de", None)
            jevtrade.apply_cfg(c)
        except Exception as e:
            log.warning("jev trade: filtros: %s", str(e)[:120])
        ativos = jt.active()
        try:
            self._jt_wallet_sync()
        except Exception as e:
            log.warning("jev trade: regras na carteira fictícia: %s", str(e)[:120])
        await self._prices_for([x["mint"] for x in ativos])
        for it in ativos:
            jt.on_price(it, (self.market.tokens.get(it["mint"]) or {}).get("price"), now)
        if self.jt_wanted():
            await self._jt_scan(now)
            due = jt.read_due(now)
            svc = getattr(self.monitor, "svc", None) if self.monitor else None
            if due and svc is not None and now - self.__dict__.get("_jt_ds_t", 0) >= 60:     # volume, compras e vendas (DexScreener)
                self._jt_ds_t = now
                await svc._fetch_prices([x["mint"] for x in due][:90], set_price=False)
            await asyncio.gather(*[self._jt_read(x, now) for x in due], return_exceptions=True)
            await self._jev_usage_save("trade")
        for k in list(jt.dirty)[:100]:
            jt.dirty.discard(k)
            it = jt.items.get(k)
            if it is None:
                continue
            try:
                await self.db.insert("jev_trades", {"id": k, "em": it["em"], "data": it}, upsert=True, on_conflict="id")
            except Exception as e:
                log.warning("jev trade não gravou: %s", str(e)[:120])
                jt.dirty.add(k)
                break
        jt.trim(now)
        await self.h5_tick(now)

    async def jt_loop(self) -> None:
        await asyncio.sleep(50)
        while True:
            try:
                await self.jt_tick()
            except Exception as e:
                log.warning("jev trade: %s", str(e)[:160])
            await asyncio.sleep(20)

    async def h5_tick(self, now: float) -> None:
        jt = self.jt
        due = jt.h5_due(now)
        if due:
            life = {r.get("mint"): r for r in list(self.lab.done)[-20000:]}
            for x in due:
                jt.h5_close(x, life.get(x["mint"]), now)
        for k in list(jt.h5_dirty)[:100]:
            jt.h5_dirty.discard(k)
            x = jt.h5.get(k)
            if x is None:
                continue
            try:
                await self.db.insert("holders_t5", {"mint": k, "em": datetime.fromtimestamp(x["t"], timezone.utc).isoformat(), "data": x}, upsert=True, on_conflict="mint")
            except Exception as e:
                log.warning("detentores aos 5 min não gravaram: %s", str(e)[:120])
                jt.h5_dirty.add(k)
                break
        for k in [k for k, x in jt.h5.items() if now - x["t"] > jevtrade.H5_KEEP_S]:
            jt.h5.pop(k, None)

    async def load_jt(self) -> None:
        try:
            since = datetime.fromtimestamp(time.time() - jevtrade.H5_KEEP_S, timezone.utc).isoformat()
            for r in await self.db.select("holders_t5", None, order="em.desc", limit=20000, gte={"em": since}):
                if isinstance(r.get("data"), dict):
                    self.jt.h5[r["mint"]] = r["data"]
        except Exception as e:
            log.warning("detentores aos 5 min não carregaram: %s", str(e)[:120])
        try:
            since = datetime.fromtimestamp(time.time() - jevtrade.KEEP_S, timezone.utc).isoformat()
            self.jt.load(await self.db.select("jev_trades", None, order="em.desc", limit=20000, gte={"em": since}), time.time())
        except Exception as e:
            log.warning("jev trade não carregou: %s", str(e)[:120])

    def jt_state(self, pf: PumpFun, hours: float = 24) -> dict:
        now, jt = time.time(), self.jt
        px = lambda x: (self.market.tokens.get(x["mint"]) or {}).get("price")
        L = sorted(jt.items.values(), key=lambda x: -(x.get("fechou_t") or x["t"]))
        since = now - hours * 3600 if hours else 0
        cfg = self.jt_cfg()
        de = {k: ("você" if v == getattr(pf, "user_id", None) else "outro admin") for k, v in cfg.pop("_de", {}).items()}
        filtros = {**jevtrade.apply_cfg(cfg), "_de": de}
        return {"ligado": bool(getattr(pf.cfg, "pump_jt_on", True)), "chave": bool(self.system_keys.get("jev_api_key")),
                "ativo": self.jt_wanted(), "rpc_falhou": now < jt.rpc_off_until, "hoje": dict(jt.day(now)),
                "limites": {"leituras": jevtrade.READS_DAY, "jev": jevtrade.JEV_DAY, "por_hora": jevtrade.SCAN_HOUR, "min_detentores": jevtrade.MIN_HOLDERS,
                            "max_abertas": jevtrade.MAX_OPEN, "sol": jevtrade.SOL},
                "estudo": jt.study(hours, now), "abertas": [jt.row(x, px(x), now) for x in jt.open()], "olhando": [jt.row(x, px(x), now) for x in jt.watching()],
                "estrategia": jevtrade.STRAT, "filtros": filtros,
                "regra_passado": jevtrade.backtest_rule(
                    [dict(x, fonte="Jev Trade") for x in L if x["t"] >= since] +
                    [b for b in (jevtrade.from_bruxo_signal(sg) for sg in (self.bruxo.recent(hours or 24 * 30, now) if getattr(self, "bruxo", None) else [])) if b]),
                "fechadas": [jt.row(x) for x in L if x["estado"] not in ("olhando", "aberta") and x["t"] >= since][:200], "ignorados": jt.ignorados}

    TOKEN_PROGRAMS = ("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb")

    @staticmethod
    def _raw_key(key: str | None) -> bytes | None:
        try:
            from solders.pubkey import Pubkey
            return bytes(Pubkey.from_string(key)) if key else None
        except Exception:
            return None

    # 0.32.106 (lote 8 de 31/10, conferido): getProgramAccountsV2 custa 1 crédito por página contra 10 do método atual. Roda AO LADO,
    # 1 em cada 5 contagens e no máximo 300 por dia, e só compara: a tela e as regras seguem usando a contagem atual.
    HV2_EVERY, HV2_DAY = 5, 300

    async def _holders_v2(self, mint: str, url: str) -> tuple[int, int]:
        import base64 as _b64
        owners: set[bytes] = set()
        pages = 0
        for prog in self.TOKEN_PROGRAMS:
            key = None
            for _ in range(6):
                cfg = {"encoding": "base64", "dataSlice": {"offset": 32, "length": 40}, "limit": 1000, "filters": [{"memcmp": {"offset": 0, "bytes": mint}}]}
                if key:
                    cfg["paginationKey"] = key
                r = await self.http.post(url, timeout=10, json={"jsonrpc": "2.0", "id": "h", "method": "getProgramAccountsV2", "params": [prog, cfg]})
                js = r.json()
                if "error" in js:
                    raise RuntimeError(str((js["error"] or {}).get("message"))[:100])
                res = js.get("result") or {}
                acc = res.get("accounts") or []
                pages += 1
                for a in acc:
                    raw = _b64.b64decode((a.get("account") or {}).get("data", [""])[0])
                    if len(raw) >= 40 and int.from_bytes(raw[32:40], "little") > 0:
                        owners.add(raw[:32])
                key = res.get("paginationKey")
                if not acc or not key:          # página curta não é o fim: só para sem contas ou sem chave
                    break
        return len(owners - {self._raw_key(PumpFun.curve_pda(mint))}), pages

    def _hv2_sample(self, mint: str, n: int) -> None:
        url = self.system_keys.get("rpc_url") or ""
        day = time.strftime("%Y-%m-%d", time.gmtime())
        st = self.__dict__.setdefault("hv2", {})
        if st.get("dia") != day:
            st.clear()
            st.update(dia=day, contagens=0, n=0, iguais=0, perto=0, dif_max=0, paginas=0, erros=0, ultimo_erro=None)
        st["contagens"] += 1
        if not url or st.get("rodando") or st["contagens"] % self.HV2_EVERY or st["n"] >= self.HV2_DAY:
            return
        st["rodando"] = True
        try:
            asyncio.get_running_loop().create_task(self._hv2_run(mint, n, url, st))
        except RuntimeError:
            st["rodando"] = False

    async def _hv2_run(self, mint: str, n: int, url: str, st: dict) -> None:
        try:
            v2, pages = await self._holders_v2(mint, url)
            dif = abs(v2 - n)
            st.update(n=st["n"] + 1, iguais=st["iguais"] + (dif == 0), perto=st["perto"] + (dif <= 1), dif_max=max(st["dif_max"], dif), paginas=st["paginas"] + pages)
        except RuntimeError as e:
            st.update(erros=st["erros"] + 1, ultimo_erro=str(e)[:100])
        except Exception as e:                         # o endereço do RPC leva a chave: nunca guardar o texto do erro de rede
            st.update(erros=st["erros"] + 1, ultimo_erro=type(e).__name__)
        finally:
            st["rodando"] = False

    async def holders_count(self, mint: str) -> int | None:
        """0.32.82 (pedido do dono): quantas carteiras têm o token agora. Usa o RPC do sistema (Helius: getTokenAccounts,
        10 créditos por página de 1.000) e, se o RPC não tiver esse método, getProgramAccounts nos dois programas de token.
        None = não deu para contar (RPC público não deixa). Guarda 45 s por token."""
        import base64 as _b64
        cache = self.__dict__.setdefault("_holders_cache", {})
        hit = cache.get(mint)
        if hit and time.time() - hit[0] < 45:
            return hit[1]
        urls = [u for u in dict.fromkeys([self.system_keys.get("rpc_url") or "", getattr(self.cfg, "solana_rpc_public", "") or ""]) if u]
        n = None
        curve = PumpFun.curve_pda(mint)                # 0.32.106: a conta da curva não é um investidor
        curve_raw = PumpHub._raw_key(curve)
        for u in urls:
            try:
                owners: set[str] = set()
                for page in range(1, 6):
                    r = await self.http.post(u, timeout=10, json={"jsonrpc": "2.0", "id": "h", "method": "getTokenAccounts",
                                                                  "params": {"mint": mint, "limit": 1000, "page": page}})
                    js = r.json()
                    if "error" in js:
                        raise LookupError("sem getTokenAccounts")
                    acc = (js.get("result") or {}).get("token_accounts") or []
                    owners |= {a.get("owner") for a in acc if a.get("owner") and int(a.get("amount") or 0) > 0}
                    if len(acc) < 1000:
                        break
                n = len(owners - {curve})
                break
            except LookupError:
                pass
            except Exception:
                continue
            try:
                owners = set()
                for prog in self.TOKEN_PROGRAMS:
                    r = await self.http.post(u, timeout=15, json={"jsonrpc": "2.0", "id": "h", "method": "getProgramAccounts", "params": [
                        prog, {"encoding": "base64", "dataSlice": {"offset": 32, "length": 40},
                               "filters": [{"memcmp": {"offset": 0, "bytes": mint}}]}]})
                    js = r.json()
                    if "error" in js:
                        raise RuntimeError(str(js["error"])[:80])
                    for a in js.get("result") or []:
                        raw = _b64.b64decode((a.get("account") or {}).get("data", [""])[0])
                        if len(raw) >= 40 and int.from_bytes(raw[32:40], "little") > 0:
                            owners.add(raw[:32])
                n = len(owners - {curve_raw})
                break
            except Exception:
                continue
        cache[mint] = (time.time(), n)
        sample = getattr(self, "_hv2_sample", None)
        if sample and n is not None:
            sample(mint, n)
        if len(cache) > 2000:
            for k in sorted(cache, key=lambda k: cache[k][0])[:500]:
                cache.pop(k, None)
        return n

    LANC_MAX_H = 12          # 0.32.59: no máximo 12 lançamentos estudados por hora (cada um lê o preço por 30 min)

    def bruxo_launch_scan(self, now: float) -> int:
        """0.32.59 (pedido do dono: "pegar do início, quando abre"): estuda — sem comprar — o token no 1º minuto de vida, sem
        esperar trader: criador sem histórico ruim (rugs, bundle, lançador) e compra do criador moderada. Cada um vira um sinal
        "lancamento" acompanhado 30 min como os da Aba do Bruxo; o estudo diz se entrar no lançamento compensa."""
        if not any(getattr(e.cfg, "pump_lanc_on", False) for e in self.engines.values()):
            return 0
        recent = [s for s in self.bruxo.signals.values() if s.get("kind") == "lancamento" and now - s["t"] < 3600]
        room = self.LANC_MAX_H - len(recent)
        n = 0
        for mint, r in list(self.lab.live.items()):
            if room <= 0:
                break
            age = now - float(r.get("t0") or now)
            if not (45 <= age <= 120) or f"lancamento:{mint}" in self.bruxo.by_mint:
                continue
            cs = self.market.creator_stats.get(r.get("creator") or "") or {}
            if cs.get("rugs", 0) >= 2 or cs.get("bundles", 0) >= 1 or cs.get("tokens", 0) >= 20:
                continue
            if not (0.05 <= float(r.get("dev_buy") or 0) <= 3.0):
                continue
            tk = self.market.tokens.get(mint) or {}
            if not tk.get("price"):
                continue
            f = self.bruxo_facts(mint, 0.0, now)
            s, new = self.bruxo.on_buy("lancamento", "lançamento (sem trader)", mint, r.get("symbol") or tk.get("symbol"), 0.0,
                                       tk.get("price"), tk, round(age / 60, 2), {k: f.get(k) for k in ("flow", "flow_base", "mcap", "dev_pct")},
                                       now, kind="lancamento")
            if new:
                s["filtros"] = {k: f.get(k) for k in ("age_min", "flow", "flow_base", "mcap", "dev_pct")} | {"dev_buy": r.get("dev_buy")}
                self.jev_shadow(s, f)
                room -= 1
                n += 1
        return n

    async def bruxo_loop(self) -> None:
        await asyncio.sleep(45)
        while True:
            try:
                await self.bruxo_tick()
            except Exception as e:
                log.warning("aba do bruxo: %s", str(e)[:160])
            await asyncio.sleep(20)

    async def load_bruxo(self) -> None:
        try:
            since = datetime.fromtimestamp(time.time() - 7 * 86400, timezone.utc).isoformat()
            self.bruxo.load(await self.db.select("bruxo_signals", None, order="em.desc", limit=20000, gte={"em": since}))
        except Exception as e:
            log.warning("sinais da aba do bruxo não carregaram: %s", str(e)[:120])

    def bruxo_state(self, pf: PumpFun, hours: float = 24) -> dict:
        from .bruxo import Bruxo
        now = time.time()
        sigs = [s for s in self.bruxo.recent(hours, now) if s.get("kind", "trader") == "trader"]
        uid = pf.user_id
        rows = []
        for s in sigs[:300]:
            d = (s.get("decisoes") or {}).get(uid)
            rows.append({k: s.get(k) for k in ("id", "em", "t", "created_t", "holders", "mint", "symbol", "names", "sol_traders", "age_min", "filtros", "marks",
                                                "peak_pct", "peak_s", "low_pct", "hit100_s", "stop30_s", "done")}
                        | {"entrou": bool(d and d.get("entrou")), "motivo": (d or {}).get("motivo") or ("não era top trader seu" if d is None else None)})
        mine_t = [dict(t, aba=pf.aba_of(t)) for t in pf.trades(5000) if t.get("origem") == "bruxo"]
        mine_p = [p for p in pf.positions() if p.get("origem") == "bruxo"]
        for t in mine_t:                                   # o que o token fez depois que a operação saiu
            s = self.bruxo.signals.get((t.get("bruxo") or {}).get("sinal") or "")
            if s:
                t["sinal_pico"], t["sinal_pico_s"] = s.get("peak_pct"), s.get("peak_s")
        sim = [t for t in mine_t if not t.get("real")]
        n = len(sim)
        w = sum(1 for t in sim if (t.get("pnl_sol") or 0) > 0)
        why: dict[str, int] = {}
        for r in rows:
            if not r["entrou"] and r["motivo"]:
                k = r["motivo"].split(" (")[0]
                why[k] = why.get(k, 0) + 1
        cfg = pf.cfg
        return {"on": bool(getattr(cfg, "pump_bx_on", False)), "real": bool(getattr(cfg, "pump_bx_real", False)),
                "real_enabled": bool(getattr(cfg, "pump_real_enabled", False)),
                "media_inicial": self.bruxo_flow_base(now), "sinais": rows,
                "estudo": Bruxo.study([s for s in self.bruxo.signals.values() if s.get("kind", "trader") == "trader"],
                                      float(getattr(cfg, "pump_bx_stop_pct", 30)), float(getattr(cfg, "pump_bx_tp1_pct", 100))),
                "lancamento": {"on": bool(getattr(cfg, "pump_lanc_on", False)),
                               "estudo": Bruxo.study([s for s in self.bruxo.signals.values() if s.get("kind") == "lancamento"]),
                               "sinais": [{k: s.get(k) for k in ("em", "t", "created_t", "holders", "mint", "symbol", "age_min", "filtros", "marks", "peak_pct", "peak_s", "hit100_s", "stop30_s", "done")}
                                          for s in self.bruxo.recent(hours, now) if s.get("kind") == "lancamento"][:100]},
                "nao_entrou": sorted(({"motivo": k, "n": v} for k, v in why.items()), key=lambda x: -x["n"]),
                "resultado": {"n": n, "ganhos": w, "acerto": round(w / n * 100) if n else None,
                              "pnl_sol": round(sum(t.get("pnl_sol") or 0 for t in sim), 5)},
                "trades": mine_t[:200], "abertas": mine_p}

    def _bx_report(self, pf: PumpFun, start: float, end: float, tipo: str) -> dict:
        from . import bruxoreport
        c = pf.cfg
        return bruxoreport.build(list(self.bruxo.signals.values()), pf.user_id, pf.trades(5000), pf.positions(), start, end, tipo,
                                 float(getattr(c, "pump_bx_stop_pct", 30)), float(getattr(c, "pump_bx_tp1_pct", 100)))

    async def bx_report_tick(self, now: float | None = None) -> int:
        """0.32.80 (pedido do dono): a cada 30 min um relatório de tudo da Aba do Bruxo e, na virada do dia (UTC), o do dia
        anterior. Só contas admin com a Aba do Bruxo ou o estudo de lançamentos ligado. Guardados em `bruxo_reports`."""
        from . import bruxoreport
        now = time.time() if now is None else now
        n = 0
        for e in list(self.engines.values()):
            if getattr(e, "role", "user") != "admin" or not (getattr(e.cfg, "pump_bx_on", False) or getattr(e.cfg, "pump_lanc_on", False)):
                continue
            R = self.bx_reports.setdefault(e.user_id, {"30min": [], "dia": []})
            todo = []
            last = R["30min"][-1]["t"] if R["30min"] else 0
            if now - last >= bruxoreport.EVERY_S - 60:
                todo.append(self._bx_report(e, now - bruxoreport.EVERY_S, now, "30min"))
            d0 = datetime.fromtimestamp(now, timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
            ontem = datetime.fromtimestamp(d0 - 86400, timezone.utc).date().isoformat()
            if not any(r.get("dia") == ontem for r in R["dia"]):
                todo.append(self._bx_report(e, d0 - 86400, d0, "dia"))
            for r in todo:
                R[r["tipo"]].append(r)
                del R[r["tipo"]][:-(336 if r["tipo"] == "30min" else 90)]
                try:
                    await self.db.insert("bruxo_reports", {"user_id": e.user_id, "tipo": r["tipo"], "dia": r.get("dia"), "em": r["em"], "data": r})
                except Exception as ex:
                    log.warning("relatório da Aba do Bruxo não gravou: %s", str(ex)[:120])
                n += 1
        return n

    async def bx_report_loop(self) -> None:
        try:
            since = datetime.fromtimestamp(time.time() - 90 * 86400, timezone.utc).isoformat()
            for r in reversed(await self.db.select("bruxo_reports", None, order="em.desc", limit=6000, gte={"em": since})):
                if isinstance(r.get("data"), dict) and r.get("tipo") in ("30min", "dia"):
                    self.bx_reports.setdefault(r["user_id"], {"30min": [], "dia": []})[r["tipo"]].append(r["data"])
        except Exception as e:
            log.warning("relatórios da Aba do Bruxo não carregaram: %s", str(e)[:120])
        await asyncio.sleep(300)
        while True:
            try:
                await self.bx_report_tick()
            except Exception as e:
                log.warning("relatório da Aba do Bruxo: %s", str(e)[:160])
            await asyncio.sleep(300)                       # confere a cada 5 min; grava a cada 30 min e uma vez por dia

    def bx_report_state(self, pf: PumpFun) -> dict:
        from . import bruxoreport
        now = time.time()
        R = self.bx_reports.get(pf.user_id, {"30min": [], "dia": []})
        d0 = datetime.fromtimestamp(now, timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        resumo = lambda r: {"em": r["em"], "tipo": r["tipo"], "dia": r.get("dia"), "veredito": r.get("veredito"), "sinais": (r.get("sinais") or {}).get("n"),
                            "entrou": (r.get("sinais") or {}).get("entrou"), "lanc": (r.get("lancamento") or {}).get("n"),
                            "operacoes": (r.get("operacoes") or {}).get("n"), "acerto": (r.get("operacoes") or {}).get("acerto"),
                            "pnl_sol": (r.get("operacoes") or {}).get("pnl_sol"), "licoes": len(r.get("licoes") or [])}
        return {"agora": self._bx_report(pf, now - bruxoreport.EVERY_S, now, "30min"), "hoje": self._bx_report(pf, d0, now, "dia"),
                "ultimo": R["30min"][-1] if R["30min"] else None,
                "historico": [resumo(r) for r in reversed(R["30min"][-48:])], "dias": [resumo(r) for r in reversed(R["dia"][-30:])],
                "aprendizado": bruxoreport.learn(R["dia"][-30:])}

    def bx_report_get(self, pf: PumpFun, em: str) -> dict | None:
        R = self.bx_reports.get(pf.user_id, {"30min": [], "dia": []})
        return next((r for k in ("dia", "30min") for r in R[k] if r.get("em") == em), None)

    # ------------------------------------------------------------------ relatório de cada aba (0.32.41)
    async def tab_report_tick(self, now: float | None = None) -> int:
        from . import tabreport
        now = time.time() if now is None else now
        n = 0
        for e in list(self.engines.values()):
            if getattr(e, "role", "user") != "admin":
                continue
            for real in (False, True):
                if real and not any(t.get("real") for t in e.trades(5000)):
                    continue
                rep = tabreport.build(e.trades(5000), e.positions(), e.aba_of, now, real)
                if not rep["abas"] and not rep["parados"]:
                    continue
                key = f"{e.user_id}:{int(real)}"
                L = self.tab_reports.setdefault(key, [])
                L.append(rep)
                del L[:-336]                        # 7 dias de relatórios em memória
                try:
                    await self.db.insert("tab_reports", {"user_id": e.user_id, "real": real, "em": rep["em"], "data": rep})
                except Exception as ex:
                    log.warning("relatório da aba não gravou: %s", str(ex)[:120])
                n += 1
        return n

    def _eq_report(self, e: PumpFun, now: float, real: bool = False) -> dict:
        from . import eqreport
        return eqreport.build(e.trades(5000), e.positions(), list(e.__dict__.get("_copy_diag") or []), list(e.copy_equal),
                              dict(getattr(e, "eq_mode", None) or {}), now, real)

    # ---------------------------------------------------------------- 0.32.114: estudo do Resultado por período
    def rs_study(self, pf: PumpFun, horas: float, real: bool, now: float | None = None) -> dict:
        from . import resultstudy
        now = time.time() if now is None else now
        return resultstudy.build(pf.trades(100000), now - horas * 3600, now, real, pf.aba_of, horas)

    async def rs_save(self, pf: PumpFun, horas: float, real: bool, now: float | None = None) -> dict:
        """Botão Estudar: guarda, e clicar de novo na mesma hora só atualiza a mesma linha."""
        now = time.time() if now is None else now
        E = self.rs_study(pf, horas, real, now)
        await self.db.insert("result_studies", {"id": f"{pf.user_id}:{int(real)}:{int(horas)}h:{int(now // 3600)}", "user_id": pf.user_id, "real": real, "origem": "manual",
                                                "em": datetime.fromtimestamp(now, timezone.utc).isoformat(), "data": E}, upsert=True, on_conflict="id")
        return E

    async def rs_saved(self, pf: PumpFun, real: bool) -> list[dict]:
        rows = await self.db.select("result_studies", {"user_id": pf.user_id, "real": real}, order="em.desc", limit=12)
        return [{"em": r.get("em"), "origem": r.get("origem"), "dia": r.get("dia"), **{k: (r.get("data") or {}).get(k) for k in ("horas", "trades", "acerto", "saldo_sol", "investido_sol")}} for r in rows]

    async def rs_marks(self, pf: PumpFun, real: bool) -> dict:
        """0.32.115: último estudo guardado de cada período, para o botão ficar verde."""
        rows = await self.db.select("result_studies", {"user_id": pf.user_id, "real": real, "origem": "manual"}, order="em.desc", limit=60)
        out: dict[str, str] = {}
        for r in rows:
            h = (r.get("data") or {}).get("horas")
            if h is not None:
                out.setdefault(str(int(h)), r.get("em"))
        return out

    # ------------------------------------------------------------------ relatório dos traders de cada aba (0.32.140)
    def tr_names(self) -> dict:
        return self.market.__dict__.get("trader_names") or {}

    def tr_tabela(self, pf: PumpFun, aba: str, real: bool) -> dict:
        from . import traderreport
        return traderreport.tabela(pf.trades(100000), aba, pf.aba_of, real, self.tr_names())

    async def tr_save(self, pf: PumpFun, aba: str, real: bool, origem: str = "manual", now: float | None = None) -> dict:
        from . import traderreport
        now = time.time() if now is None else now
        R = traderreport.build(pf.trades(100000), aba, pf.aba_of, real, self.tr_names(), now)
        await self.db.insert("trader_reports", {"id": f"{pf.user_id}:{int(real)}:{aba}:{int(now // 3600)}", "user_id": pf.user_id, "real": real, "aba": aba, "origem": origem,
                                                "em": datetime.fromtimestamp(now, timezone.utc).isoformat(), "data": R}, upsert=True, on_conflict="id")
        return R

    async def tr_base(self, real: bool, limit: int = 300) -> dict:
        from . import traderreport
        rows = await self.db.select("trader_reports", {"real": real}, order="em.desc", limit=limit)
        try:
            ps = await self.db.select("profiles", None, columns="user_id,nome,email")
            names = {p["user_id"]: p.get("nome") or (p.get("email") or "").split("@")[0] or "usuário" for p in ps}
        except Exception:
            names = {}
        return {"relatorios": [{"id": r.get("id"), "em": r.get("em"), "conta": names.get(r.get("user_id"), "usuário"), "aba": r.get("aba"), "origem": r.get("origem"),
                                "total": (r.get("data") or {}).get("total"), "total24": (r.get("data") or {}).get("total24")} for r in rows[:60]],
                "traders": traderreport.learn(rows)[:40]}

    async def tr_item(self, rid: str) -> dict | None:
        rows = await self.db.select("trader_reports", {"id": rid}, limit=1)
        return rows[0].get("data") if rows else None

    async def tr_tick(self, now: float | None = None) -> int:
        """Um relatório por dia do Top traders de cada admin, sem precisar clicar."""
        now = time.time() if now is None else now
        done, dia, n = self.__dict__.setdefault("_tr_done", set()), int(now // 86400), 0
        for e in list(self.engines.values()):
            key = (e.user_id, dia)
            if getattr(e, "role", "user") == "admin" and key not in done:
                await self.tr_save(e, "Top traders", False, "dia", now)
                done.add(key)
                n += 1
        return n

    async def tr_loop(self) -> None:
        await asyncio.sleep(600)
        while True:
            try:
                await self.tr_tick()
            except Exception as e:
                log.warning("relatório de traders: %s", str(e)[:160])
            await asyncio.sleep(3600)

    # ------------------------------------------------------------------ histórico de cada trader (0.32.163)
    async def th_save(self, pf: PumpFun, now: float | None = None) -> int:
        """Guarda o resumo de cada trader copiado (fictícia e real) quando muda, com o ranking dele por dia. Fica mesmo depois
        de zerar a carteira fictícia (pedido do dono: "quero guardar esse histórico")."""
        from . import traderhist
        now = time.time() if now is None else now
        cache = self.__dict__.setdefault("_th_data", {})
        trades, lb, names, n = pf.trades(100000), traderhist.lb_map(getattr(pf, "leaderboard", None)), self.tr_names(), 0
        hoje = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
        for real in (False, True):
            key0 = (pf.user_id, real)
            if key0 not in cache:                       # depois de reiniciar: o que já estava guardado (para não perder o ranking por dia)
                try:
                    rows = await self.db.select("trader_history", {"user_id": pf.user_id, "real": real}, limit=2000)
                except Exception:
                    rows = []
                cache[key0] = {r.get("wallet"): r.get("data") or {} for r in rows}
            saved = cache[key0]
            for row in traderhist.resumo([t for t in trades if bool(t.get("real")) == real], pf.aba_of, names, lb):
                antes = saved.get(row["wallet"])
                data = traderhist.guardar(row, antes, hoje)
                sig = lambda d: (d.get("trades"), d.get("falsos"), round(d.get("saldo_sol") or 0, 6), d.get("ultimo"), (d.get("ranking") or {}).get("rank"),
                                 (d.get("ranking") or {}).get("winrate"), len(d.get("ranking_dias") or {}))
                if antes is not None and sig(antes) == sig(data):
                    continue
                await self.db.insert("trader_history", {"id": f"{pf.user_id}:{int(real)}:{row['wallet']}", "user_id": pf.user_id, "real": real,
                                                        "wallet": row["wallet"], "em": datetime.fromtimestamp(now, timezone.utc).isoformat(), "data": data},
                                     upsert=True, on_conflict="id")
                saved[row["wallet"]] = data
                n += 1
        return n

    async def th_saved(self, pf: PumpFun, real: bool) -> list[dict]:
        try:
            rows = await self.db.select("trader_history", {"user_id": pf.user_id, "real": real}, limit=2000)
        except Exception:
            return []
        return [dict(r.get("data") or {}, wallet=r.get("wallet"), guardado_em=r.get("em")) for r in rows]

    async def th_tick(self, now: float | None = None) -> int:
        n = 0
        for e in list(self.engines.values()):
            try:
                n += await self.th_save(e, now)
            except Exception as ex:
                log.warning("histórico dos traders (%s): %s", e.user_id, str(ex)[:160])
        return n

    async def th_loop(self) -> None:
        await asyncio.sleep(600)
        while True:
            await self.th_tick()
            await asyncio.sleep(3600)

    # ------------------------------------------------------------------ semana × fim de semana (0.32.161)
    async def week_save(self, pf: PumpFun, now: float | None = None) -> int:
        """Guarda cada bloco FECHADO (seg–sex ou sáb–dom) da fictícia e da real desta conta. Upsert pelo id: repetir não duplica."""
        from . import weekparts
        now = time.time() if now is None else now
        done, n = self.__dict__.setdefault("_wk_done", set()), 0
        trades = pf.trades(100000)
        for real in (False, True):
            L = [t for t in trades if bool(t.get("real")) == real]
            for b in weekparts.blocos(L, pf.aba_of, self.tr_names(), now):
                rid = f"{pf.user_id}:{int(real)}:{b['key']}"
                if not b["fechado"] or rid in done:
                    continue
                await self.db.insert("week_results", {"id": rid, "user_id": pf.user_id, "real": real, "bloco": b["key"], "tipo": b["tipo"],
                                                      "inicio": datetime.fromtimestamp(b["ini"], timezone.utc).isoformat(),
                                                      "em": datetime.fromtimestamp(now, timezone.utc).isoformat(), "data": b},
                                     upsert=True, on_conflict="id")
                done.add(rid)
                n += 1
        return n

    async def week_saved(self, pf: PumpFun, real: bool, limit: int = 60) -> list[dict]:
        try:
            rows = await self.db.select("week_results", {"user_id": pf.user_id, "real": real}, order="inicio.desc", limit=limit)
        except Exception:
            return []
        return [r.get("data") or {} for r in rows]

    async def week_tick(self, now: float | None = None) -> int:
        n = 0
        for e in list(self.engines.values()):
            try:
                n += await self.week_save(e, now)
            except Exception as ex:
                log.warning("semana × fim de semana (%s): %s", e.user_id, str(ex)[:160])
        return n

    async def week_loop(self) -> None:
        await asyncio.sleep(900)
        while True:
            await self.week_tick()
            await asyncio.sleep(3600)

    async def rs_base(self, real: bool, limit: int = 100) -> list[dict]:
        """Seção da Base geral: estudos guardados pelo botão, de todas as contas (só admin vê)."""
        rows = await self.db.select("result_studies", {"origem": "manual", "real": real}, order="em.desc", limit=limit)
        try:
            ps = await self.db.select("profiles", None, columns="user_id,nome,email")
            names = {p["user_id"]: p.get("nome") or (p.get("email") or "").split("@")[0] or "usuário" for p in ps}
        except Exception:
            names = {}
        return [{"id": r.get("id"), "em": r.get("em"), "conta": names.get(r.get("user_id"), "usuário"),
                 **{k: (r.get("data") or {}).get(k) for k in ("horas", "trades", "acerto", "saldo_sol", "investido_sol", "retorno_pct")}} for r in rows]

    async def rs_item(self, sid: str) -> dict | None:
        rows = await self.db.select("result_studies", {"id": sid}, limit=1)
        return rows[0].get("data") if rows else None

    async def market_tick(self, now: float | None = None) -> int:
        """0.32.116: dados do dia na pumpdata.fun (limite 60 por minuto; aqui cerca de 1 por segundo no 1º uso, depois 1 por dia)."""
        from . import marketday
        now = time.time() if now is None else now
        M = self.__dict__.setdefault("market_days", {})
        today = int(now // 86400)
        n = 0
        for d in range(today - marketday.DIAS, today):
            dia = time.strftime("%Y-%m-%d", time.gmtime(d * 86400))
            if dia in M:
                continue
            try:
                r = await self.http.get(marketday.URL.format(dia), timeout=15)
                x = marketday.parse(r.json()) if r.status_code == 200 else None
            except Exception as e:
                log.warning("mercado do dia: %s", type(e).__name__)
                break
            if x is None:
                continue
            M[dia] = x
            n += 1
            try:
                await self.db.insert("market_days", {"dia": dia, "data": x}, upsert=True, on_conflict="dia")
            except Exception as e:
                log.warning("mercado do dia não gravou: %s", str(e)[:120])
            await asyncio.sleep(1.1)
        return n

    async def result_tick(self, now: float | None = None) -> int:
        """Grava sozinho cada dia fechado (UTC) dos últimos 7, de cada conta. É o que a Base geral soma: dias não se sobrepõem."""
        from . import resultstudy
        now = time.time() if now is None else now
        done = self.__dict__.setdefault("_rs_done", set())
        today = int(now // 86400)
        n = 0
        for e in list(self.engines.values()):
            T = e.trades(100000)
            for real in (False, True):
                for d in range(today - 7, today):
                    dia = time.strftime("%Y-%m-%d", time.gmtime(d * 86400))
                    key = f"{e.user_id}:{int(real)}:{dia}"
                    if key in done:
                        continue
                    E = resultstudy.build(T, d * 86400, (d + 1) * 86400, real, e.aba_of)
                    done.add(key)
                    if not E["trades"]:
                        continue
                    row = {"id": key, "user_id": e.user_id, "real": real, "origem": "dia", "dia": dia, "em": datetime.fromtimestamp((d + 1) * 86400, timezone.utc).isoformat(), "data": E}
                    try:
                        await self.db.insert("result_studies", row, upsert=True, on_conflict="id")
                        self.__dict__.setdefault("rs_days", []).append(row)
                        n += 1
                    except Exception as ex:
                        done.discard(key)
                        log.warning("estudo do resultado não gravou: %s", str(ex)[:120])
        return n

    # 0.32.116 (caso Bloom, 26/10: 48 carteiras drenadas em 94 s): avisa se sair SOL ou token da carteira real numa transação que não é
    # swap. O robô só compra e vende por pump.fun, PumpSwap e Jupiter, então transferência simples nunca é dele. Não bloqueia nada.
    WG_MIN_SOL = 0.002

    @classmethod
    def wallet_leak(cls, tx: dict, addr: str) -> dict | None:
        from .pumpfun import PUMP_PROGRAMS
        from .txguard import JUPITER, PUMPPORTAL_ROUTER
        meta = (tx or {}).get("meta") or {}
        if meta.get("err"):
            return None
        logs = " ".join(meta.get("logMessages") or [])
        if any(p in logs for p in (*PUMP_PROGRAMS, JUPITER, PUMPPORTAL_ROUTER)):
            return None
        keys = [k.get("pubkey") if isinstance(k, dict) else k for k in ((tx.get("transaction") or {}).get("message") or {}).get("accountKeys") or []]
        out_sol = 0.0
        if addr in keys:
            i = keys.index(addr)
            out_sol = (meta["preBalances"][i] - meta["postBalances"][i]) / 1e9
        tk = lambda L: {b.get("mint"): float((b.get("uiTokenAmount") or {}).get("uiAmount") or 0) for b in L or [] if b.get("owner") == addr}
        pre, post = tk(meta.get("preTokenBalances")), tk(meta.get("postTokenBalances"))
        tokens = sum(1 for m, v in pre.items() if v > post.get(m, 0.0))
        return {"sol": round(out_sol, 6), "tokens": tokens} if out_sol >= cls.WG_MIN_SOL or tokens else None

    async def wallet_guard_once(self, e, now: float | None = None) -> int:
        w = getattr(e, "sol_wallet", None)
        if not (w and getattr(w, "keypair", None) and getattr(w, "address", None)):
            return 0
        url = await w.safe_rpc_url()
        rpc = lambda m, p: self.http.post(url, timeout=10, json={"jsonrpc": "2.0", "id": 1, "method": m, "params": p})
        r = await rpc("getSignaturesForAddress", [w.address, {"limit": 20}])
        sigs = [x["signature"] for x in (r.json().get("result") or []) if not x.get("err")]
        last, n = getattr(e, "_wg_last", None), 0
        e._wg_last = sigs[0] if sigs else last
        e._wg_at = time.time() if now is None else now
        if last is None:                               # 1ª volta só marca o ponto de partida: não alerta o passado
            return 0
        for sig in sigs:
            if sig == last:
                break
            r = await rpc("getTransaction", [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1}])
            leak = self.wallet_leak(r.json().get("result") or {}, w.address)
            if not leak:
                continue
            n += 1
            msg = (f"[PUMP REAL] ALERTA da carteira: saíram {leak['sol']:.4f} SOL" + (f" e {leak['tokens']} token(s)" if leak["tokens"] else "") +
                   f" numa transação que NÃO é do robô ({sig[:8]}…). Se não foi você, tire o saldo e troque de carteira agora.")
            e._emit(msg)
            e.wallet_alerts = ([{"sig": sig, "sol": leak["sol"], "tokens": leak["tokens"], "t": e._wg_at}] + list(getattr(e, "wallet_alerts", [])))[:5]
            await audit(self.db, e.user_id, "alerta da carteira real", f"{sig} · {leak['sol']} SOL · {leak['tokens']} tokens")
        return n

    async def wallet_guard_loop(self) -> None:
        await asyncio.sleep(90)
        while True:
            for e in list(self.engines.values()):
                try:
                    await self.wallet_guard_once(e)
                except Exception as ex:
                    log.warning("vigia da carteira: %s", type(ex).__name__)    # o endereço do RPC leva a chave: nunca o texto do erro
            await asyncio.sleep(60)

    async def result_loop(self) -> None:
        try:
            since = datetime.fromtimestamp(time.time() - 60 * 86400, timezone.utc).isoformat()
            rows = await self.db.select("result_studies", {"origem": "dia"}, order="em.desc", limit=5000, gte={"em": since})
            self.rs_days = list(rows or [])
            self._rs_done = {r["id"] for r in self.rs_days}
            self.market_days = {str(r["dia"]): r["data"] for r in await self.db.select("market_days", None, order="dia.desc", limit=120)}
        except Exception as e:
            log.warning("estudos do resultado não carregaram: %s", str(e)[:120])
            return                                         # sem a lista, regravaria tudo a cada reinício
        await asyncio.sleep(120)
        while True:
            try:
                await self.market_tick()
                await self.result_tick()
            except Exception as e:
                log.warning("estudo do resultado: %s", str(e)[:160])
            await asyncio.sleep(3600)

    def rs_learn(self, real: bool = False) -> dict:
        from . import resultstudy
        from . import marketday
        rows = [r for r in self.__dict__.get("rs_days", []) if bool(r.get("real")) == real]
        marks = marketday.classify(self.__dict__.get("market_days", {}))
        return {**resultstudy.learn(rows), "mercado": resultstudy.by_market(rows, marks), "dias_mercado": [{"dia": d, "tipo": marks[d]} for d in sorted(marks)[-14:]]}

    async def eq_report_tick(self, now: float | None = None) -> int:
        """0.32.73 (pedido do dono): relatório do Copiar igual a cada 6 h, guardado (fictícia e, se houver, real)."""
        from . import eqreport
        now = time.time() if now is None else now
        n = 0
        for e in list(self.engines.values()):
            if getattr(e, "role", "user") != "admin":
                continue
            for real in (False, True):
                if not any(t.get("eq") and bool(t.get("real")) == real for t in e.trades(5000)) and not (
                        not real and getattr(e.cfg, "pump_eq_on", False)):
                    continue
                key = f"{e.user_id}:{int(real)}"
                L = self.eq_reports.setdefault(key, [])
                if L and now - float(L[-1].get("t") or 0) < eqreport.EVERY_S - 60:
                    continue                                   # já tem o deste período (reinício no meio)
                r = self._eq_report(e, now, real)
                L.append(r)
                del L[:-120]                                   # 30 dias em memória
                try:
                    await self.db.insert("eq_reports", {"user_id": e.user_id, "real": real, "em": r["em"], "data": r})
                except Exception as ex:
                    log.warning("relatório do Copiar igual não gravou: %s", str(ex)[:120])
                n += 1
        return n

    async def eq_report_loop(self) -> None:
        try:
            since = datetime.fromtimestamp(time.time() - 30 * 86400, timezone.utc).isoformat()
            for r in reversed(await self.db.select("eq_reports", None, order="em.desc", limit=3000, gte={"em": since})):
                if isinstance(r.get("data"), dict):
                    self.eq_reports.setdefault(f"{r['user_id']}:{int(bool(r.get('real')))}", []).append(r["data"])
        except Exception as e:
            log.warning("relatórios do Copiar igual não carregaram: %s", str(e)[:120])
        await asyncio.sleep(600)
        while True:
            try:
                await self.eq_report_tick()
            except Exception as e:
                log.warning("relatório do Copiar igual: %s", str(e)[:160])
            await asyncio.sleep(1800)                          # confere a cada 30 min; grava só quando passaram 6 h

    def eq_report_state(self, pf: PumpFun, real: bool = False) -> dict:
        from . import eqreport
        hist = self.eq_reports.get(f"{pf.user_id}:{int(real)}", [])
        return {"agora": self._eq_report(pf, time.time(), real), "historico": [
                    {"em": r["em"], "veredito": r.get("veredito"), "total": r.get("total"), "vistas": r.get("vistas"), "copiadas": r.get("copiadas")}
                    for r in reversed(hist[-60:])],
                "ultimo": hist[-1] if hist else None, "aprendizado": eqreport.learn(hist), "a_cada_h": eqreport.EVERY_S / 3600}

    async def tab_report_loop(self) -> None:
        await self.load_tab_reports()
        await asyncio.sleep(120)
        while True:
            try:
                await self.tab_report_tick()
            except Exception as e:
                log.warning("relatório das abas: %s", str(e)[:160])
            await asyncio.sleep(1800)

    async def load_tab_reports(self) -> None:
        try:
            since = datetime.fromtimestamp(time.time() - 7 * 86400, timezone.utc).isoformat()
            for r in reversed(await self.db.select("tab_reports", None, order="em.desc", limit=5000, gte={"em": since})):
                if isinstance(r.get("data"), dict):
                    self.tab_reports.setdefault(f"{r['user_id']}:{int(bool(r.get('real')))}", []).append(r["data"])
        except Exception as e:
            log.warning("relatórios das abas não carregaram: %s", str(e)[:120])

    def tab_state(self, pf: PumpFun, real: bool = False) -> dict:
        from . import tabreport
        now = time.time()
        hist = self.tab_reports.get(f"{pf.user_id}:{int(real)}", [])
        live = tabreport.build(pf.trades(5000), pf.positions(), pf.aba_of, now, real)
        return {"agora": live, "ultimo": hist[-1] if hist else None,
                "historico": [{"em": r["em"], "total24": r["total24"],
                               "abas": [{"aba": a["aba"], "veredito": a["veredito"], "pnl24": a["h24"]["pnl_sol"]} for a in r["abas"]]}
                              for r in hist[-48:]],
                "aprendizado": tabreport.learn(hist)}

    async def load_calls(self) -> None:
        try:
            since = datetime.fromtimestamp(time.time() - 7 * 86400, timezone.utc).isoformat()
            for r in await self.db.select("calls", None, order="em.desc", limit=20000, gte={"em": since}):
                if isinstance(r.get("data"), dict):
                    self.calls.calls.setdefault(r["id"], r["data"])
        except Exception as e:
            log.warning("calls não carregaram: %s", str(e)[:120])

    def radar_calls(self, pf: PumpFun) -> dict:
        """0.31.96 (pedido do dono): no Radar, as últimas compras das Carteiras em estudo e as ondas calculadas a partir das
        calls guardadas no banco (não somem quando o servidor reinicia)."""
        wallets = set(getattr(pf, "study", []) or [])
        buys = self.calls.for_wallets(wallets, 24)
        names = getattr(pf, "study_names", None) if isinstance(getattr(pf, "study_names", None), dict) else {}
        for c in buys:
            c["symbol"] = c.get("symbol") or (self.market.tokens.get(c["mint"]) or {}).get("symbol")
        window = int(getattr(pf.cfg, "pump_radar_window_min", 5)) * 60
        minimum = int(getattr(pf.cfg, "pump_radar_min_wallets", 2))
        return {"compras": [dict(c, nome=names.get(c["wallet"]) or c.get("label"), resultado=self.calls.result(c)) for c in buys[:150]],
                "ondas_guardadas": self.calls.waves(buys, minimum, window)[:50], "carteiras_n": len(wallets)}

    def calls_view(self) -> dict:
        s = self.calls.summary(risk_of=self._risk_of, blacklisted=self._bl)
        for r in s["agora"]:
            tk = self.market.tokens.get(r["mint"]) or {}
            r["symbol"] = r.get("symbol") or tk.get("symbol")
            px = tk.get("price")
            r["agora_pct"] = round((px / r["px1"] - 1) * 100, 1) if px and r.get("px1") else None
        return s

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
        n = 0
        while True:
            await asyncio.sleep(60)
            try:
                await self.rlog_flush()
            except Exception as e:
                log.warning("log dos robôs: %s", str(e)[:160])
            n += 1
            if n % 60 == 5:                                 # 0.31.91: resumo do dia, de hora em hora (só dias fechados)
                try:
                    await self.rlog_daily()
                except Exception as e:
                    log.warning("aprendizado dos logs: %s", str(e)[:160])

    async def rlog_daily(self, now: float | None = None, max_days: int = 60) -> int:
        """0.31.91 (pedido do dono: "depois de 14 dias criar um aprendizado e não deletar"): para cada conta e robô,
        resume cada dia fechado (UTC) que ainda não tem resumo em robot_daily. Os registros de 5 min nunca são apagados."""
        from datetime import timedelta
        from .robotlog import rollup
        now = time.time() if now is None else now
        today = datetime.fromtimestamp(now, timezone.utc).date()
        done = 0
        for pf in list(self.engines.values()):
            have = {r.get("id") for r in await self.db.select("robot_daily", {"user_id": pf.user_id}, columns="id", limit=5000)}
            for mod in ("explorar", *self.RLOG_NAMES):
                for back in range(1, max_days + 1):
                    dia = today - timedelta(days=back)
                    rid = f"{pf.user_id}:{mod}:{dia.isoformat()}"
                    if rid in have or rid in self._rlog_vazio:
                        continue
                    ini = datetime(dia.year, dia.month, dia.day, tzinfo=timezone.utc)
                    rng = {"gte": {"em": ini.isoformat()}, "lte": {"em": (ini + timedelta(days=1) - timedelta(seconds=1)).isoformat()}}
                    if mod == "explorar":
                        rows = await self.db.select("explore_cycles", {"user_id": pf.user_id}, limit=2000, **rng)
                    else:
                        rows = await self.db.select("robot_log", {"user_id": pf.user_id, "modulo": mod}, limit=2000, **rng)
                    if not rows:
                        # 0.32.229: dia fechado sem registro não ganha registro depois; antes era consultado de novo
                        # toda hora (60 dias × robôs × contas = o maior volume de leituras do Supabase, ~2.600/h).
                        if back >= 2:
                            self._rlog_vazio.add(rid)
                        continue
                    await self.db.insert("robot_daily", {"id": rid, "user_id": pf.user_id, "modulo": mod, "dia": dia.isoformat(),
                                                         "data": rollup([r.get("data") or {} for r in rows])}, upsert=True, on_conflict="id")
                    done += 1
        return done

    async def robot_days(self, pf: PumpFun, mod: str) -> dict:
        from .robotlog import trend
        rows = await self.db.select("robot_daily", {"user_id": pf.user_id, "modulo": mod}, order="dia.desc", limit=400)
        return {"modulo": mod, "dias": rows, "tendencia": trend(rows)}

    async def robot_log(self, pf: PumpFun, mod: str, hours: float = 24) -> dict:
        import re
        since = datetime.fromtimestamp(time.time() - hours * 3600, timezone.utc).isoformat()
        rows = await self.hist_select("robot_log", {"user_id": pf.user_id, "modulo": mod}, "em", 600, since)
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
        resumo["dicas"] = self.rlog_tips(pf, mod, resumo["motivos"])
        return {"modulo": mod, "nome": self.RLOG_NAMES.get(mod, mod), "blocos": blocos[:288], "resumo": resumo}

    TIPS = (("compra pequena", "pump_min_trader_sol", "Configurações → compra mínima do trader: hoje {v} SOL. Se estes traders compram pouco, baixar copia mais (e também mais compras de teste deles)."),
            ("market cap", "pump_max_mcap_sol", "Configurações → faixa de market cap (máximo hoje {v} SOL): o token estava fora da faixa."),
            ("limite de", "pump_max_open", "Configurações → posições abertas ao mesmo tempo: hoje {v}. Estava cheio quando o trader comprou."),
            ("pausado", None, "Traders pausados (por prejuízo ou pelo Ajuste automático): veja em Top traders → pausados."),
            ("aguardando", "pump_copy_delay_s", "Configurações → espera antes de copiar: hoje {v} s. A cópia só acontece se o trader continuar no token."),
            ("robô", None, "Carteira com cara de robô (muitas compras por minuto): fica fora da cópia por 1 h, de propósito."),
            ("risco", None, "Checagem de risco do token (Solana Tracker) barrou: é proteção."),
            ("subiu", "pump_chase_block", "Configurações → não copiar se o preço já subiu X% desde o trader: hoje {v}%."))

    def rlog_tips(self, pf: PumpFun, mod: str, motivos: list) -> list[str]:
        """0.31.99 (item 7): o que ajustar, a partir dos motivos que mais barraram (só sugestão; nada muda sozinho)."""
        out = []
        for m in motivos[:5]:
            low = str(m["motivo"]).lower()
            for key, cfg, txt in self.TIPS:
                if key in low:
                    v = getattr(pf.cfg, cfg, None) if cfg else None
                    t = f"{m['pct']:.0f}% das recusas — " + txt.format(v=v if v is not None else "?")
                    if t not in out:
                        out.append(t)
                    break
        return out[:4]

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
        rows = await self.hist_select("explore_cycles", {"user_id": pf.user_id}, "em", 400, since)
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

    async def chance_alta(self, pf: PumpFun, hours: float = 24, now: float | None = None) -> dict:
        """0.32.64 (pedido do dono: "clicar em Chance alta e ver os tokens, porcentagem, tempo"): cada token que o veredito
        do Explorar deu "chance alta" no período, UMA linha por token (o cartão soma as vezes em todas as listas de 5 min):
        quando apareceu, quantas listas, se comprou ou o que barrou, quanto variou desde que foi visto, o pico e o resultado
        em 15 min (sombras) e, se comprou, o resultado da operação."""
        import re
        from .ghosts import _ts
        now = time.time() if now is None else now
        since = now - hours * 3600
        out: dict[str, dict] = {}

        def row(m: str, sym) -> dict:
            return out.setdefault(m, {"mint": m, "symbol": sym, "first_t": None, "last_t": None, "listas": 0, "entrou": False, "motivo": None})

        def seen(r: dict, t) -> None:
            if t:
                r["first_t"] = min(r["first_t"] or t, t)
                r["last_t"] = max(r["last_t"] or t, t)
        try:
            rows = await self.hist_select("explore_cycles", {"user_id": pf.user_id}, "em", 400,
                                          datetime.fromtimestamp(since, timezone.utc).isoformat())
        except Exception:
            rows = []
        for c in rows:
            t = _ts(c.get("em"))
            for x in (c.get("data") or {}).get("chance_alta_barrados") or []:
                if x.get("mint"):
                    r = row(x["mint"], x.get("symbol"))
                    r["listas"] += 1
                    r["motivo"] = r["motivo"] or x.get("motivo")
                    seen(r, t)
        for m, g in (getattr(pf, "_ex_funnel", None) or {}).items():           # memória (24 h): também os que entraram
            if g.get("chance") != "chance alta" or float(g.get("t") or 0) < since:
                continue
            r = row(m, g.get("symbol"))
            seen(r, g.get("first_t"))
            seen(r, g.get("t"))
            r["listas"] = max(r["listas"], 1)
            r["entrou"] = r["entrou"] or bool(g.get("entrou"))
            r["motivo"] = None if r["entrou"] else (g.get("why") or r["motivo"])
            r["px0"] = g.get("px0")
        sh = self.__dict__.get("shadows") or {}
        trades = [t for t in pf.trades(5000) if not t.get("real") and t.get("origem") == "explorar"]
        pos = [p for p in pf.positions() if not p.get("real") and p.get("origem") == "explorar"]
        for m, r in out.items():
            tk = self.market.tokens.get(m) or {}
            s = sh.get(m) or {}
            px0 = r.get("px0") or s.get("px0")
            px = tk.get("price")
            r["agora_pct"] = round((px / px0 - 1) * 100, 1) if px and px0 else None
            r["pico15_pct"], r["ret15_pct"] = s.get("pico"), s.get("ret")
            info = s.get("info") or {}
            r["curva_pct"] = info.get("curve_pct")
            r["holders"] = info.get("holders")
            r["idade_min"] = info.get("age_min")
            r["mcap_sol"] = tk.get("mcap_sol")
            r["graduou"] = tk.get("pool") in ("pumpswap", "pump-amm") or (tk.get("main_dex") not in (None, "pumpfun"))
            tr = next((t for t in trades if t.get("mint") == m), None)
            op = next((p for p in pos if p.get("mint") == m), None)
            if tr or op:
                r["entrou"] = True
                r["motivo"] = None
                r["op"] = ({"aberta": False, "pnl_pct": tr.get("pnl_pct"), "pnl_sol": tr.get("pnl_sol"), "saiu": tr.get("reason"),
                            "hold_s": tr.get("hold_s")} if tr else
                           {"aberta": True, "pnl_pct": op.get("chg_pct"), "hold_s": round(now - float(op.get("open_t") or now))})
            r["first_em"] = datetime.fromtimestamp(r["first_t"], timezone.utc).isoformat() if r["first_t"] else None
            r["visto_s"] = round((r["last_t"] or 0) - (r["first_t"] or 0)) if r["first_t"] else None
        L = sorted(out.values(), key=lambda r: -(r["first_t"] or 0))
        med = [r["agora_pct"] for r in L if r.get("agora_pct") is not None]
        r15 = [r["ret15_pct"] for r in L if r.get("ret15_pct") is not None]
        resumo = {"tokens": len(L), "entrou": sum(1 for r in L if r["entrou"]), "barrados": sum(1 for r in L if not r["entrou"]),
                  "subiram_agora": sum(1 for x in med if x > 0), "com_preco": len(med),
                  "media_agora_pct": round(sum(med) / len(med), 1) if med else None,
                  "medidos_15": len(r15), "ganhariam_15": sum(1 for x in r15 if x > 4),
                  "media_15_pct": round(sum(r15) / len(r15), 1) if r15 else None,
                  "pico_50": sum(1 for r in L if (r.get("pico15_pct") or 0) >= 50)}
        mot: dict[str, list] = {}
        for r in L:
            if not r["entrou"] and r.get("motivo"):
                k = re.sub(r"[-+]?\d+(?:[.,]\d+)?", "#", str(r["motivo"]))[:90]
                mot.setdefault(k, [0, str(r["motivo"])[:120]])[0] += 1
        resumo["motivos"] = sorted(({"motivo": v[1], "n": v[0]} for v in mot.values()), key=lambda x: -x["n"])[:6]
        return {"resumo": resumo, "tokens": [{k: v for k, v in r.items() if k not in ("first_t", "last_t", "px0")} for r in L[:300]]}

    # ------------------------------------------------------------------ Raio-X do token (0.31.86)
    XRAY_TTL = 6 * 3600            # refaz no máximo a cada 6 h por token
    XRAY_AUTO_DAY = 10             # automáticos por dia (1 crédito da Solana Tracker cada)

    def _xray_key(self, pf: PumpFun | None = None) -> str:
        if pf is not None and pf.lb_key_own():
            return pf.lb_key()
        return self.st_pick()

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

    # ------------------------------------------------------------------ revisão dos ganhos falsos (0.32.1)
    ST_PRICE_TS = "https://data.solanatracker.io/price/history/timestamp"
    FALSE_MAX_PRICED = 30            # tokens consultados na Solana Tracker por revisão (2 créditos cada)

    async def false_gains(self, pf: PumpFun | None = None, check: bool = True) -> dict:
        """Todos os trades de +1.900% ou mais de TODAS as contas, com a moeda da curva lida on-chain e o preço de mercado
        (Solana Tracker) na entrada e na saída. Só leitura e marca; nada é alterado. Pedido do dono em 2026-10-28."""
        from . import ganhos_falsos as gf
        accounts = []
        for uid, e in list(self.engines.items()):
            try:
                accounts.append((uid, await self._nome(uid), e.trades(100000)))
            except Exception:
                continue
        items = gf.collect(accounts)
        gf.pair_real(items, {uid: T for uid, _, T in accounts})
        chain: dict[str, dict] = {}
        prices: dict[str, dict] = {}
        svc = getattr(self.monitor, "svc", None) if self.monitor else None
        mints = list(dict.fromkeys(i["mint"] for i in items if i.get("mint")))
        if check and svc is not None and mints:
            for k in range(0, len(mints), 100):
                part = mints[k:k + 100]
                pdas = {m: svc.curve_pda(m) for m in part}
                keys = [v for v in pdas.values() if v]
                vals = await svc._rpc_multi(keys, "base64", True) if keys else None
                by = dict(zip(keys, vals)) if vals is not None else {}
                for m, pda in pdas.items():
                    if vals is None or not pda:
                        chain[m] = {"quote": "não lida"}
                        continue
                    acc = by.get(pda)
                    try:
                        raw = base64.b64decode(acc["data"][0]) if acc else b""
                    except Exception:
                        raw = b""
                    chain[m] = {"quote": "sem curva"} if len(raw) < 49 else {"quote": svc.curve_quote(raw) or "SOL"}
        key = self._xray_key(pf) if check else ""
        cache = self.__dict__.setdefault("_false_px", {})
        if key:
            todo = [i for i in items if (i.get("pnl_pct") or 0) >= gf.SUSPECT_PCT and i.get("mint")][: self.FALSE_MAX_PRICED]
            for i in todo:
                got = {}
                for side, ts in (("in_usd", i.get("opened_at")), ("out_usd", i.get("closed_at"))):
                    t = gf._ts(ts)
                    if not t:
                        continue
                    ck = (i["mint"], int(t))
                    if ck not in cache:
                        try:
                            r = await self.http.get(self.ST_PRICE_TS, params={"token": i["mint"], "timestamp": int(t)},
                                                    headers={"x-api-key": key, "Accept": "application/json"}, timeout=15)
                            p = float((r.json() or {}).get("price") or 0) if r.status_code == 200 else 0.0
                        except Exception:
                            p = 0.0
                        cache[ck] = p or None
                    got[side] = cache[ck]
                prices[i["id"]] = got
        items = [gf.judge(i, chain.get(i.get("mint")), prices.get(i.get("id"))) for i in items]
        rep = gf.report(items, accounts)
        rep["consultou_precos"] = bool(key)
        self._false_last = rep
        return rep

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

    def wallet_facts(self, w: str, want: bool = True) -> dict:
        """0.32.9 (pedido do dono): idade, saldo em US$, transações e tokens criados de uma carteira (o que já foi lido).
        Tokens criados = os que a Base da pump.fun viu essa carteira criar (não é o total da vida dela)."""
        if want:
            self._facts_want = getattr(self, "_facts_want", {})
            self._facts_want[w] = time.time()
            if len(self._facts_want) > 300:
                for k in sorted(self._facts_want, key=self._facts_want.get)[:100]:
                    self._facts_want.pop(k, None)
        fa = self.market.wallet_facts.get(w) or (getattr(self.elite, "ages", {}) or {}).get(w) or {}
        bal = self.market.wallet_usd.get(w) or {}
        lab = getattr(self, "lab", None)
        cs = (getattr(lab, "creators", None) or {}).get(w) or self.market.creator_stats.get(w) or {}
        return {"age_days": fa.get("age_days"), "age_more": bool(fa.get("more")), "txs": fa.get("txs"),
                "usd": bal.get("usd"), "sol": bal.get("sol"), "criados": cs.get("tokens"), "rugs": cs.get("rugs"),
                "lido": bool(fa or bal)}

    async def _reassert_overrides(self, pf: PumpFun) -> None:
        """0.32.52 (barrados do dono voltaram a entrar às 11:05 depois da 0.32.44): na troca de versão o servidor ANTIGO fica
        alguns instantes no ar e pode gravar a configuração da memória por cima do ajuste recém-aplicado. Por 20 min depois de
        aplicar, o ajuste é conferido de novo ao carregar a conta e a cada 5 min; só repõe o que estiver diferente."""
        # 0.32.56 (MAS comprado pelos barrados às 11:40 CET, depois de 20 min do ajuste): o ajuste vale até a PESSOA mudar
        # aquela opção na tela (`pump_settings` grava a chave em `_ov_user`); os mais novos ganham dos mais antigos (id).
        try:
            rows = await self.db.select("settings_overrides", {"user_id": pf.user_id}, order="id.asc")
        except Exception:
            rows = []
        mine = dict(getattr(pf, "_ov_user", None) or {})
        want: dict = {}
        for r in rows:
            if not r.get("aplicado_em"):
                continue
            at = r.get("aplicado_em")
            for k, v in dict(r.get("settings") or {}).items():
                if str(mine.get(k) or "") < str(at):              # a pessoa não mexeu nessa opção depois do ajuste
                    want[k] = v
        now = time.time()
        for t0, st in self._ov_recent.get(pf.user_id, []):
            if now - t0 < 1200:
                want.update(st)
        self._ov_recent[pf.user_id] = [x for x in self._ov_recent.get(pf.user_id, []) if now - x[0] < 1200]
        diff = {k: v for k, v in want.items() if getattr(pf.cfg, k, None) != v}
        if not diff:
            return
        applied, _err = pf.cfg.apply(diff)
        if applied:
            pf._cfg_why = "ajuste pedido no chat"
            await self.save_settings(pf)
            log.info("ajuste do dono reposto (o servidor antigo tinha gravado por cima): %s", ", ".join(applied))

    async def _ajuste_saidas(self, pf: PumpFun, saved: dict) -> None:
        """0.32.323 (pedido do dono, 11/11/2026: "se precisa alterar configuração também faz" → "Sim, aplica"): a conta que ainda
        está no padrão antigo das saídas recebe o novo, uma vez. Não mexe no que a pessoa mudou pela tela, não liga nem desliga
        carteira nenhuma, e a configuração de antes fica no Histórico de config (dá para voltar)."""
        try:
            ch = saidas_upgrade(saved, pf.cfg.user_dict(), set(getattr(pf, "_ov_user", None) or {}))
            pf._saidas_v = SAIDAS_V                # vai junto no próximo salvar da conta: o ajuste não roda de novo
            if ch:
                applied, _err = pf.cfg.apply(ch)
                pf._cfg_why = SAIDAS_WHY
                pf._emit("Configuração ajustada (padrões novos): " + ", ".join(f"{k} = {v}" for k, v in applied.items())
                         + ". A anterior está em Carteiras → Histórico de config.")
                await audit(self.db, pf.user_id, "ajuste de configuração aplicado", SAIDAS_WHY + ": " + ", ".join(applied))
                await self.save_settings(pf)
        except Exception as e:
            log.warning("ajuste das saídas não aplicou (%s…): %s", pf.user_id[:8], str(e)[:160])

    async def _apply_overrides(self, pf: PumpFun) -> None:
        """0.32.33: aplica os ajustes de `settings_overrides` ainda não aplicados (só o servidor novo lê essa tabela, então o
        servidor antigo não consegue sobrescrever como acontecia gravando direto em user_settings)."""
        try:
            rows = await self.db.select("settings_overrides", {"user_id": pf.user_id}, order="id.asc", is_null=("aplicado_em",))
        except Exception as e:
            log.warning("ajustes pendentes: não li settings_overrides: %s", str(e)[:160])
            return
        for r in rows:
            try:
                applied, _err = pf.cfg.apply(dict(r.get("settings") or {}))
                self._ov_recent.setdefault(pf.user_id, []).append((time.time(), dict(r.get("settings") or {})))
                pf._cfg_why = "ajuste pedido no chat"
                await self.save_settings(pf)
                await self.db.update("settings_overrides", {"id": r["id"]}, {"aplicado_em": datetime.now(timezone.utc).isoformat()})
                pf._emit(f"Configuração ajustada a pedido do dono: {', '.join(applied)}")
                await audit(self.db, pf.user_id, "ajuste de configuração aplicado", f"{r.get('motivo') or ''}: {', '.join(applied)}")
            except Exception as e:
                log.warning("ajustes pendentes: não apliquei %s: %s", r.get("id"), str(e)[:160])

    async def flush_pos_learn(self) -> None:
        """0.32.33: grava as posições fechadas já com o "depois da saída" medido (aprendizado das posições)."""
        for pf in list(self.engines.values()):
            rows = pf.__dict__.get("_learn_out") or []
            if not rows:
                continue
            pf._learn_out = []
            try:
                for d in rows:
                    await self.db.insert("position_learn", {"user_id": pf.user_id, "pos_id": str(d.get("pos_id")), "mint": d.get("mint"),
                                                            "real": bool(d.get("real")), "fechou_em": d.get("closed_at"), "data": d})
            except Exception as e:
                pf._learn_out = rows + pf.__dict__.get("_learn_out", [])
                log.warning("aprendizado das posições não gravou: %s", str(e)[:120])

    async def pos_learn_state(self, days: int = 14) -> dict:
        from .poslearn import aggregate
        since = datetime.fromtimestamp(time.time() - days * 86400, timezone.utc).isoformat()
        try:
            rows = await self.db.select("position_learn", None, order="em.desc", limit=3000, gte={"em": since})
        except Exception:
            rows = []
        out = aggregate(rows)
        out["recentes"] = [r.get("data") for r in rows[:30]]
        return out

    async def eq_set(self, pf: PumpFun, wallets: list) -> dict:
        """0.32.4: lista do "Copiar igual" (endereços colados da página da pump.fun)."""
        seen, out, bad = set(), [], []
        for w in wallets or []:
            w = str(w).strip()
            if not w or w in seen:
                continue
            (out if B58_ADDR.fullmatch(w) else bad).append(w)
            seen.add(w)
        if len(out) > EQ_MAX:
            return {"error": f"no máximo {EQ_MAX} carteiras"}
        pf.copy_equal = out
        await self.save_settings(pf)
        pf.refresh_followed(force=True)
        await audit(self.db, pf.user_id, "copiar igual: lista", f"{len(out)} carteiras")
        return {"ok": True, "wallets": out, "invalidas": bad[:20]}

    async def eq_mode_set(self, pf: PumpFun, wallet: str, mode: str) -> dict:
        """0.32.65 (pedido do dono: "botão copiar aqui, pergunta se no fictício ou real, copiar tudo que a carteira faz"):
        modo de UMA carteira do Copiar igual. Copiar liga o modo (pump_eq_on) se estava desligado; a REAL vale só para
        esta carteira e só sai com a Execução real ligada."""
        wallet = str(wallet or "").strip()
        if mode not in ("sim", "both", "off"):
            return {"error": "modo inválido"}
        if wallet == "*":                                      # 0.32.72 (pedido do dono): "Copiar todas" no topo da lista
            if not pf.copy_equal:
                return {"error": "a lista está vazia"}
            for w in pf.copy_equal:
                pf.eq_mode[w] = mode
            ligou = False
            if mode != "off" and not getattr(pf.cfg, "pump_eq_on", False):
                pf.cfg.apply({"pump_eq_on": True})
                ligou = True
            await self.save_settings(pf)
            pf.refresh_followed(force=True)
            nome = {"sim": "só FICTÍCIA", "both": "FICTÍCIA e REAL", "off": "parou de copiar"}[mode]
            await audit(self.db, pf.user_id, "copiar igual: todas", f"{len(pf.copy_equal)} carteiras → {nome}")
            return {"ok": True, "wallet": "*", "n": len(pf.copy_equal), "mode": mode, "ligou_modo": ligou,
                    "real_ligada": bool(getattr(pf.cfg, "pump_real_enabled", False))}
        if not B58_ADDR.fullmatch(wallet):
            return {"error": "endereço inválido"}
        if wallet not in pf.copy_equal:
            if len(pf.copy_equal) >= EQ_MAX:
                return {"error": f"no máximo {EQ_MAX} carteiras"}
            pf.copy_equal.append(wallet)
        pf.eq_mode[wallet] = mode
        ligou = False
        if mode != "off" and not getattr(pf.cfg, "pump_eq_on", False):
            pf.cfg.apply({"pump_eq_on": True})
            ligou = True
        await self.save_settings(pf)
        pf.refresh_followed(force=True)
        nome = {"sim": "só FICTÍCIA", "both": "FICTÍCIA e REAL", "off": "parou de copiar"}[mode]
        await audit(self.db, pf.user_id, "copiar igual: carteira", f"{wallet[:6]}…{wallet[-4:]} → {nome}")
        return {"ok": True, "wallet": wallet, "mode": mode, "ligou_modo": ligou,
                "real_ligada": bool(getattr(pf.cfg, "pump_real_enabled", False))}

    def eq_detail(self, pf: PumpFun, wallet: str, now: float | None = None) -> dict:
        """0.32.70 (pedido do dono: "onde acompanho o que está fazendo depois que cliquei Copiar?"): tudo de UMA carteira do
        Copiar igual — se o monitor está ouvindo, a última atividade, o que ela fez (Feed), o que o robô decidiu, as
        posições abertas e as fechadas."""
        from .ghosts import _ts
        now = time.time() if now is None else now
        mon = self.monitor
        st = self.market.rpc_status if hasattr(self.market, "rpc_status") else {}
        try:
            ouvindo = bool(mon is not None and wallet in mon.union_followed())
        except Exception:
            ouvindo = False
        ls = pf.last_seen(wallet)
        feed = [x for x in list(pf.feed) if x.get("wallet") == wallet and now - (_ts(x.get("at")) or 0) <= 86400]
        diag = [x for x in pf.__dict__.get("_copy_diag") or [] if x[1] == wallet and now - x[0] <= 86400]
        pos = [p for p in pf.positions() if p.get("wallet") == wallet and p.get("eq")]
        trs = [t for t in pf.trades(5000) if t.get("wallet") == wallet and t.get("eq")]
        return {"wallet": wallet, "modo": (pf.eq_mode or {}).get(wallet, "off"), "ligado": bool(getattr(pf.cfg, "pump_eq_on", False)),
                "ouvindo": ouvindo, "monitor_ok": bool(st.get("ws")), "monitor_erro": st.get("error"),
                "pp_copy": bool(getattr(pf.cfg, "pump_pp_copy", False)),
                "ultima_atividade": datetime.fromtimestamp(ls, timezone.utc).isoformat() if ls else None,
                "online": bool(ls and now - ls <= 600),
                "eventos": [{"em": x.get("at"), "acao": x.get("action"), "token": x.get("symbol"), "mint": x.get("mint"),
                             "sol": x.get("sol"), "motivo": x.get("reason"), "tipo": x.get("kind")} for x in reversed(feed[-100:])],
                "decisoes": [{"em": datetime.fromtimestamp(x[0], timezone.utc).isoformat(), "o_que": x[2]} for x in reversed(diag[-50:])],
                "abertas": [{"id": p.get("id"), "token": p.get("symbol"), "mint": p.get("mint"), "real": bool(p.get("real")),
                             "investido": p.get("sol_in"), "agora_pct": p.get("chg_pct"), "aberta_em": p.get("opened_at")} for p in pos],
                "fechadas": [{"token": t.get("symbol"), "mint": t.get("mint"), "real": bool(t.get("real")), "pnl_sol": t.get("pnl_sol"),
                              "pnl_pct": t.get("pnl_pct"), "motivo": t.get("reason"), "fechou_em": t.get("closed_at"),
                              "hold_s": t.get("hold_s")} for t in trs[:50]]}

    def eq_status(self, pf: PumpFun) -> dict:
        diag = pf.__dict__.get("_copy_diag") or []
        now = time.time()
        pos = [p for p in pf.positions() if p.get("eq")]
        trs = [t for t in pf.trades(5000) if t.get("eq")]
        rows = []
        for w in pf.copy_equal:
            vis = [x for x in diag if x[1] == w and now - x[0] <= 86400]
            cop = sum(1 for x in vis if x[2] == "copiou")
            mt = [t for t in trs if t.get("wallet") == w and not t.get("real")]
            rows.append({"wallet": w, "vistas_24h": len(vis), "copiadas_24h": cop, "modo": (pf.eq_mode or {}).get(w, "off"),
                         "ultimo_motivo": next((x[2] for x in reversed(vis) if x[2] != "copiou"), None),
                         "abertas": sum(1 for p in pos if p["wallet"] == w and not p.get("real")),
                         "fechadas": len(mt), "ganhos": sum(1 for t in mt if (t.get("pnl_sol") or 0) > 0),
                         "pnl_sol": round(sum(t.get("pnl_sol") or 0 for t in mt), 6),
                         "pnl_real_sol": round(sum(t.get("pnl_sol") or 0 for t in trs if t.get("wallet") == w and t.get("real")), 6),
                         "online": (lambda ls: bool(ls and now - ls <= 600))(pf.last_seen(w))})
        c = pf.cfg
        return {"on": bool(getattr(c, "pump_eq_on", False)), "real": bool(getattr(c, "pump_eq_real", False)),
                "seguidas": sum(1 for w in pf.copy_equal if w in pf.followed), "padrao": list(EQ_SEED),
                "wallets": rows, "abertas": len([p for p in pos if not p.get("real")]),
                "pnl_sol": round(sum(t.get("pnl_sol") or 0 for t in trs if not t.get("real")), 6),
                "fechadas": len([t for t in trs if not t.get("real")])}

    # 0.32.103 (pedido do dono): tudo que compra na REAL. A chave geral (pump_real_enabled) barra todos; a opção de cada aba não
    # muda, e ao religar cada aba volta como estava. (aba, opção, o que faz, só admin)
    REAL_PLACES = (("Top traders", None, "copia as compras dos traders", False),
                   ("Espelho da fictícia", "pump_real_mirror", "repete na REAL o que a fictícia comprou", False),
                   ("Botão Comprar", None, "pergunta FICTÍCIA ou REAL a cada compra", False),
                   ("Explorar", "pump_ex_real_on", "compra automática", True), ("Explorar: barrados", "pump_bar_real", "barrados que subiram", True),
                   ("Base da pump.fun", "pump_auto_real", "compra automática", True), ("Maiores traders", "pump_el_real", "compra automática", True),
                   ("Calls quentes", "pump_calls_real", "compra automática", True), ("Aba do Bruxo", "pump_bx_real", "compra automática", True),
                   ("Jev Trade", "pump_jt_real", "compra do Jev", True), ("Copiar igual", "pump_eq_real", "cópia das carteiras da lista", True),
                   ("Carteiras em estudo", "pump_st_real", "cópia das carteiras estudadas", True),
                   ("Estudo · deram lucro", "pump_st_lucro_real", "cópia das carteiras do estudo que deram lucro", True),
                   ("Tokens fora da pump.fun", "pump_copy_other_real", "cópia pela Jupiter", False))

    def real_places(self, pf: PumpFun) -> dict:
        adm = getattr(pf, "role", "user") == "admin"
        rows = [{"aba": a, "o_que": t, "opcao": None if k is None else bool(getattr(pf.cfg, k, False))} for a, k, t, so in self.REAL_PLACES if adm or not so]
        both = sum(1 for v in (getattr(pf, "eq_mode", None) or {}).values() if v == "both")
        for r in rows:
            if r["aba"] == "Copiar igual" and both:
                r.update(opcao=True, o_que=f"{both} carteiras copiadas na REAL")
        return {"enabled": bool(getattr(pf.cfg, "pump_real_enabled", False)), "on_at": getattr(pf, "real_on_at", None), "off_at": getattr(pf, "real_off_at", None),
                "abertas": sum(1 for p in pf.positions() if p.get("real")), "lugares": rows}

    async def save_settings(self, pf: PumpFun) -> None:
        s = pf.cfg.user_dict()
        if getattr(pf.cfg, "pump_real_enabled", False):
            s["_real_on"] = True                       # 0.31.28: o real ligado sobrevive ao reinício (ver _load)
        elif getattr(pf, "real_on_at", None) and float(getattr(pf, "real_off_at", 0) or 0) < pf.real_on_at:
            pf.real_off_at = time.time()               # 0.32.103: vale para todo jeito de desligar (você, admin, carteira removida)
        for k in ("real_on_at", "real_off_at"):
            if getattr(pf, k, None):
                s["_" + k] = getattr(pf, k)
        if getattr(pf, "follow_user", ""):
            s["_follow_user"] = pf.follow_user         # 0.31.61: de quem esta conta copia os trades
        if getattr(pf, "study_copy", None):
            s["_study_copy"] = list(pf.study_copy)     # 0.32.11: aprovadas pelo estudo automático
        for k, attr in (("_sim_only", "sim_only_list"), ("_ia_added", "ia_added"), ("_real_ok", "real_ok_list")):   # 0.32.17/0.32.38
            if getattr(pf, attr, None):
                s[k] = list(getattr(pf, attr))
        if getattr(pf, "_ov_user", None):
            s["_ov_user"] = dict(pf._ov_user)          # 0.32.56: a pessoa mudou estas opções (o ajuste do chat não volta)
        if getattr(pf, "_saidas_v", None):
            s["_saidas_v"] = pf._saidas_v              # 0.32.323: esta conta já recebeu o ajuste das saídas
        if list(getattr(pf, "copy_equal", None) or []) != list(EQ_SEED):
            s["_copy_equal"] = list(pf.copy_equal)     # 0.32.4: Copiar igual (só grava se mudou a lista de 28/10)
        if getattr(pf, "eq_mode", None):
            s["_eq_mode"] = dict(pf.eq_mode)           # 0.32.65: Copiar igual por carteira (fictícia / fictícia e REAL / parado)
        if getattr(pf, "brain_freeze", None):
            s["_brain_freeze"] = pf.brain_freeze       # 0.31.85: evolução para a qual o dono voltou
        await self.db.update("user_settings", {"user_id": pf.user_id},
                             {"settings": s, "atualizado_em": datetime.now(timezone.utc).isoformat()})
        await self.cfg_hist_note(pf)

    # ------------------------------------------------------------------ histórico de configuração (0.32.199)
    async def cfg_hist_load(self, pf: PumpFun) -> None:
        pf._cfg_last, pf._cfg_row = None, {"n": 0}
        try:
            rows = await self.db.select("config_versions", {"user_id": pf.user_id}, order="n.desc", limit=1)
            cur = cfghist.snap(pf.cfg.user_dict())
            if rows:
                pf._cfg_row = {"n": rows[0]["n"], "origem": rows[0].get("origem"), "t": 0, "base": None}
                pf._cfg_last = rows[0].get("settings") or {}
                if pf._cfg_last != cur:
                    pf._cfg_why = "mudou enquanto o histórico não estava olhando"
                    await self.cfg_hist_note(pf)
            else:
                pf._cfg_last = cur
                pf._cfg_row = {"n": 1, "origem": "início", "t": 0, "base": None}
                await self.db.insert("config_versions", {"user_id": pf.user_id, "n": 1, "origem": "início do histórico", "settings": cur, "mudou": []})
        except Exception as e:
            log.warning("histórico de configuração não carregou (%s…): %s", pf.user_id[:8], str(e)[:160])

    async def cfg_hist_note(self, pf: PumpFun) -> None:
        """Toda configuração salva passa aqui: se mudou alguma opção, guarda a versão nova. Falha não atrapalha quem salvou."""
        last = getattr(pf, "_cfg_last", None)
        if last is None:
            return
        cur = cfghist.snap(pf.cfg.user_dict())
        why = pf.__dict__.pop("_cfg_why", None) or "mudança do sistema"
        mud = cfghist.diff(last, cur)
        if not mud:
            return
        pf._cfg_last = cur
        row, now = pf._cfg_row, time.time()
        try:
            if why == cfghist.TELA and row.get("origem") == why and row.get("base") is not None and now - row.get("t", 0) < cfghist.JUNTA_S:
                row["t"] = now
                await self.db.update("config_versions", {"user_id": pf.user_id, "n": row["n"]}, {"settings": cur, "mudou": cfghist.diff(row["base"], cur)})
            else:
                n = row.get("n", 0) + 1
                pf._cfg_row = {"n": n, "origem": why, "t": now, "base": last}
                await self.db.insert("config_versions", {"user_id": pf.user_id, "n": n, "origem": why, "settings": cur, "mudou": mud})
        except Exception as e:
            log.warning("histórico de configuração não gravou (%s…): %s", pf.user_id[:8], str(e)[:160])

    async def cfg_hist_list(self, pf: PumpFun) -> dict:
        rows = await self.db.select("config_versions", {"user_id": pf.user_id}, order="n.desc", limit=200, columns="n,em,origem,mudou")
        aceitas = [{"id": o["id"], "de": o["de"], "parte": o["parte"], "em": o["em"], "keys": [k for k in (o.get("antes") or {}) if not k.startswith("_")]}
                   for o in await self.config_applied(pf.user_id)]
        for a in aceitas:
            a["n"] = len(a["keys"])
        # 0.32.200: a tela só oferece Voltar no quadro quando a opção pode voltar (REAL e Telegram nunca voltam)
        volta = set(self.share_filter(list({x.get("k") for r in rows for x in (r.get("mudou") or [])}), getattr(pf, "role", "user") == "admin"))
        rows = [{**r, "mudou": [{**x, "volta": x.get("k") in volta} for x in (r.get("mudou") or [])]} for r in rows]
        return {"versoes": rows, "atual": pf._cfg_row.get("n") if getattr(pf, "_cfg_row", None) else None, "aceitas": [a for a in aceitas if a["n"]]}

    async def _cfg_hist_target(self, pf: PumpFun, n=None, offer=None) -> tuple[dict | None, str]:
        if offer is not None:
            r = await self.db.select("config_offers", {"id": int(offer), "para_user": pf.user_id, "status": "aceita"})
            if not r:
                return None, ""
            return {k: v for k, v in (r[0].get("antes") or {}).items() if not k.startswith("_")}, f"antes de aceitar a configuração de {r[0].get('de_nome') or 'outra conta'}"
        r = await self.db.select("config_versions", {"user_id": pf.user_id, "n": int(n)})
        return (r[0].get("settings") or {}, f"versão {int(n)}") if r else (None, "")

    async def cfg_hist_diff(self, pf: PumpFun, n=None, offer=None) -> dict:
        vals, nome = await self._cfg_hist_target(pf, n, offer)
        if vals is None:
            return {"error": "versão não encontrada"}
        cur = pf.cfg.user_dict()
        ok = set(self.share_filter(list(vals), getattr(pf, "role", "user") == "admin"))
        d = [x for x in cfghist.diff({k: cur.get(k) for k in vals}, vals)]
        return {"nome": nome, "mudaria": [x for x in d if x["k"] in ok], "fora": [x for x in d if x["k"] not in ok]}

    async def real_from_sim(self, pf: PumpFun) -> dict:
        """0.32.206 (pedido do dono): copia para a REAL os valores da FICTÍCIA que existem nas duas carteiras. Fica salvo como
        versão no histórico de config (dá para voltar). Não liga nem desliga a carteira REAL."""
        c = pf.cfg.user_dict()
        vals = {r: c.get(s) for s, r in cfghist.SIM2REAL if c.get(s) is not None and c.get(s) != c.get(r)}
        if not vals:
            return {"ok": True, "mudou": 0}
        antes = {k: c.get(k) for k in vals}
        applied, errors = pf.cfg.apply(vals)
        if applied:
            ov = pf.__dict__.setdefault("_ov_user", {})
            for k in applied:
                ov[k] = datetime.now(timezone.utc).isoformat()
            pf._cfg_why = cfghist.REAL_DA_FICTICIA
            await self.save_settings(pf)
            await audit(self.db, pf.user_id, "configuração: REAL igual à FICTÍCIA",
                        " · ".join(f"{k}: {antes[k]} → {applied[k]}" for k in applied)[:500])
        row = getattr(pf, "_cfg_row", None) or {}
        return {"ok": not errors, "mudou": len(applied), "erros": errors, "versao": row.get("n")}

    async def real_from_sim_undo(self, pf: PumpFun, n: int) -> dict:
        """0.32.206: desfaz UMA aplicação da FICTÍCIA na REAL (versão n): volta os valores da REAL que ela trocou. Só as opções
        de cfghist.VOLTA_REAL e só se a versão for dessa origem. Não liga nem desliga a carteira REAL."""
        r = await self.db.select("config_versions", {"user_id": pf.user_id, "n": int(n)})
        if not r or r[0].get("origem") != cfghist.REAL_DA_FICTICIA:
            return {"error": "essa versão não é uma aplicação da FICTÍCIA na REAL"}
        vals = {x["k"]: x.get("de") for x in (r[0].get("mudou") or []) if x.get("k") in cfghist.VOLTA_REAL and x.get("de") is not None}
        cur = pf.cfg.user_dict()
        vals = {k: v for k, v in vals.items() if cur.get(k) != v}
        if not vals:
            return {"ok": True, "mudou": 0}
        applied, errors = pf.cfg.apply(vals)
        if applied:
            ov = pf.__dict__.setdefault("_ov_user", {})
            for k in applied:
                ov[k] = datetime.now(timezone.utc).isoformat()
            pf._cfg_why = f"desfez a aplicação da FICTÍCIA na REAL (versão {int(n)})"
            await self.save_settings(pf)
            await audit(self.db, pf.user_id, "configuração: desfez REAL igual à FICTÍCIA", f"versão {int(n)} · {len(applied)} opções")
        return {"ok": not errors, "mudou": len(applied), "erros": errors}

    async def cfg_hist_back(self, pf: PumpFun, n=None, offer=None, keys=None) -> dict:
        """Volta as opções para a versão escolhida. Nunca mexe na REAL (valores e chaves), no Telegram nem na chave da FICTÍCIA.
        Para desfazer um "aplicar a configuração da FICTÍCIA na REAL" existe real_from_sim_undo.
        keys (0.32.200, pedido do dono): volta só estas opções, as das abas que a pessoa marcou; sem keys, volta tudo."""
        d = await self.cfg_hist_diff(pf, n, offer)
        if d.get("error"):
            return d
        vals = {x["k"]: x["para"] for x in d["mudaria"] if keys is None or x["k"] in keys}
        if not vals:
            return {"ok": True, "nome": d["nome"], "mudou": 0}
        applied, errors = pf.cfg.apply(vals)
        ov = pf.__dict__.setdefault("_ov_user", {})      # um ajuste antigo pedido no chat não volta a mexer nestas opções
        for k in applied:
            ov[k] = datetime.now(timezone.utc).isoformat()
        pf._cfg_why = f"você voltou para: {d['nome']}" + ("" if keys is None else " · só as abas escolhidas")
        await self.save_settings(pf)
        pf.refresh_followed(force=True)
        await audit(self.db, pf.user_id, "configuração: voltou para outra versão", f"{d['nome']} · {len(applied)} opções")
        return {"ok": True, "nome": d["nome"], "mudou": len(applied), "erros": errors}

    async def set_secret(self, pf: PumpFun, name: str, value: str) -> None:
        antes = pf.keys.get(name) if hasattr(pf.keys, "get") else ""
        await self.vault.save(pf.user_id, name, value)
        if name in ("rpc_url", "solanatracker_api_key") and (antes or "") != value:
            self.key_changed(name, antes or "", value)      # 0.32.236: chave pessoal trocada também zera a contagem
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
            old = dict(getattr(self, "system_keys", None) or {})
            self.system_keys = keys
            self.market.sys_rpc = keys.get("rpc_url") or ""      # 0.32.236: as leituras de transação usam esta chave
            if old != keys and getattr(self, "_keys_loaded", False):
                for nome in ("rpc_url", "solanatracker_api_key"):
                    if (old.get(nome) or "") != (keys.get(nome) or ""):
                        self.key_changed(nome, old.get(nome) or "", keys.get(nome) or "")
            self._keys_loaded = True
        except Exception as e:
            log.warning("Chaves do sistema: %s", str(e)[:120])
        self.shared_st_key = self.system_keys.get("solanatracker_api_key", "")
        jk = self.system_keys.get("jupiter_api_key", "")
        if jk != getattr(self, "_jup_key_in_use", ""):
            self.market.jup = JupiterQuoter(self.http, jk) if jk else self.public_quoter
            self._jup_key_in_use = jk

    def st_tags(self) -> set:
        """0.32.237: marcas (hash) das chaves da Solana Tracker em uso agora: a do sistema e as pessoais das contas carregadas."""
        from .apiusage import key_tag
        ks = {(self.system_keys or {}).get("solanatracker_api_key") or ""}
        for pf in list(self.engines.values()):
            try:
                ks.add(pf.keys.get("solanatracker_api_key") or "")
            except Exception:
                pass
        return {key_tag(k) for k in ks if k}

    def rpc_tags(self) -> set:
        """0.32.240: marcas das chaves do Helius em uso (chave do sistema, variável do Portainer e RPC pessoal das contas)."""
        from urllib.parse import parse_qs, urlparse
        from .apiusage import key_tag
        urls = {(self.system_keys or {}).get("rpc_url") or "", str(self.cfg.defaults.get("pump_rpc_http") or ""),
                str(self.cfg.defaults.get("pump_rpc_ws") or ""), getattr(self.cfg, "solana_rpc_public", "") or ""}
        for pf in list(self.engines.values()):
            try:
                urls.add(pf.keys.get("rpc_url") or "")
            except Exception:
                pass
        out = set()
        for u in urls:
            k = (parse_qs(urlparse(u).query).get("api-key") or [""])[0] if u else ""
            if k:
                out.add(key_tag(k))
        return out

    def key_changed(self, nome: str, antes: str, depois: str) -> None:
        """0.32.236 (pedido do dono: "o sistema tem que ver quando troco as chaves e zerar a contagem de uso"): chave de RPC
        ou da Solana Tracker trocada = zera a contagem daquela API e as marcas de recusa/falha do RPC (o Status recomeça)."""
        from urllib.parse import urlparse
        from .apiusage import classify
        us = self.__dict__.get("usage")
        if nome == "rpc_url":
            mk = self.market
            for a in ("rpc_429_at", "rpc_ok_at", "rpc_fail_at", "rpc_cool_until"):
                setattr(mk, a, 0.0)
            mk.rpc_429_streak, mk.rpc_fail_msg = 0, ""
            st = getattr(mk, "rpc_status", None)
            if isinstance(st, dict):
                for k in ("tx_errors", "stale", "stale_hi", "queued", "queued_hi", "parsed", "not_trade", "dropped"):
                    if k in st:
                        st[k] = 0
            if us is not None:
                for u in {antes, depois} - {""}:
                    api = classify(urlparse(u).hostname or "")
                    if api:
                        us.zerar(api)
        elif nome in ("solanatracker_api_key",) and us is not None:
            us.zerar("Solana Tracker", antes or None)
        log.info("Chave %s trocada: contagem de uso zerada", nome)
        self.__dict__.setdefault("key_resets", {})[nome] = time.time()

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
            try:
                await self.flush_pos_learn()                # 0.32.33: aprendizado das posições
            except Exception:
                pass
            if n % 5 == 0:                                  # 0.32.34: ajuste pendente que falhou ao subir tenta de novo
                for pf in list(self.engines.values()):
                    if getattr(pf, "role", None) == "admin":
                        await self._apply_overrides(pf)
                        await self._reassert_overrides(pf)
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
            if trim and getattr(self, "arquivo", None) is None:   # 14 dias (0.24.0); com o arquivo ligado, ele move (0.32.225)
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
        from .autostudy import AUTO_TAG, BAN_S, PER_CYCLE, candidates, facts_features, features, judge, rates
        from .study import MAX_WALLETS, copy_params, summary
        now = time.time() if now is None else now
        if getattr(pf, "role", "user") != "admin" or not getattr(pf.cfg, "pump_st_auto_on", True):
            return {"ok": False, "motivo": "desligado"}
        rows = await self.db.select("study_wallets", {"user_id": pf.user_id}, order="criado_em.asc")
        log_rows = await self.db.select("study_auto_log", {"user_id": pf.user_id}, order="em.desc", limit=1000)
        info_of = {r["wallet"]: r.get("info") or {} for r in reversed(log_rows) if r.get("acao") == "adicionou"}
        approved = {r["wallet"] for r in log_rows if r.get("acao") == "aprovou"}
        prm = copy_params(pf)
        done = {"descartou": 0, "aprovou": 0, "adicionou": 0, "parou_de_copiar": 0, "sugere_parar": 0, "copiou_lucro": 0}
        out_now: set[str] = set()                   # descartadas nesta volta não podem voltar na mesma volta

        done_now: dict[str, str] = {}

        async def note(w, acao, motivo, info):
            await self.db.insert("study_auto_log", {"user_id": pf.user_id, "wallet": w, "acao": acao, "motivo": motivo,
                                                    "info": info, "em": datetime.fromtimestamp(now, timezone.utc).isoformat()})
            done[acao] += 1
            if acao in ("aprovou", "descartou"):
                done_now[w] = acao
            pf._emit(f"Estudo automático: {acao} {w[:4]}…{w[-4:]} — {motivo}")

        auto = [r for r in rows if str(r.get("apelido") or "").startswith(AUTO_TAG)]
        for r in auto:
            p = await self.study_profile(r["wallet"], prm)
            if p.get("error"):
                continue
            j = judge(ts(r.get("criado_em")) or now, summary(p), now)
            nc = pf.uncopiable(r["wallet"], now) if getattr(pf.cfg, "pump_nc_on", False) else None
            if nc:
                j = ("descartou", "não copiável: " + nc)          # 0.32.57: lançador / alta frequência
            if not j or (j[0] == "aprovou" and r["wallet"] in approved):
                continue
            if j[0] == "descartou":
                await self.study_set(pf, r["wallet"], "remove")
                out_now.add(r["wallet"])
            inf = dict(info_of.get(r["wallet"], {}))
            fx = self.wallet_facts(r["wallet"], want=False)
            if fx.get("lido"):                          # 0.32.9: idade/saldo/transações/criados entram no estudo
                inf["facts"] = fx
                inf["features"] = {**(inf.get("features") or {}), **facts_features(fx)}
            await note(r["wallet"], j[0], j[1], inf)
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
        await self.study_copy_sync(pf, log_rows, done_now)
        await self.study_copy_judge(pf, log_rows, info_of, now, note)
        try:
            await self.study_ai_auto(pf, now)          # 0.32.48: relatório automático das carteiras novas
        except Exception as e:
            log.warning("relatório automático das carteiras: %s", str(e)[:120])
        self._study_auto_at[pf.user_id] = now
        return {"ok": True, **done}

    # ------------------------------------------------------------------ relatórios para o ChatGPT (0.32.47/0.32.48)
    async def study_ai_build(self, pf, wallets: list[str]) -> str:
        from .study import copy_params
        from .study_ai import ai_text, wallet_block
        names = getattr(pf, "study_names", None) if isinstance(getattr(pf, "study_names", None), dict) else {}
        prm = copy_params(pf)
        blocks = []
        for w in wallets[:30]:
            prof = await self.study_profile(w, prm)
            if prof.get("error"):
                blocks.append(f"## Carteira {w}\n- (o sistema não conseguiu ler os dados: {prof['error']})")
                continue
            T = [t for t in pf.trades(5000) if t.get("wallet") == w and not t.get("real")]
            blocks.append(wallet_block(w, names.get(w), prof, self.wallet_facts(w, want=False),
                                       {"trades": len(T), "pnl_sol": sum(t.get("pnl_sol") or 0 for t in T)} if T else None))
        return ai_text(blocks)

    async def study_ai_reports(self, pf) -> list[dict]:
        try:
            return await self.db.select("study_ai_reports", {"user_id": pf.user_id}, order="em.desc", limit=200)
        except Exception as e:
            log.warning("relatórios das carteiras: %s", str(e)[:120])
            return []

    async def study_ai_create(self, pf, wallets: list[str], auto: bool = False) -> dict:
        import secrets as _s
        mine = list(getattr(pf, "study", []) or [])
        wallets = [w for w in dict.fromkeys(wallets) if w in mine][:30]
        if not wallets:
            return {"error": "nenhuma carteira do seu estudo para o relatório"}
        now = datetime.now(timezone.utc)
        rid = now.strftime("%Y%m%d-%H%M") + "-" + _s.token_hex(2)
        texto = await self.study_ai_build(pf, wallets)
        row = {"id": rid, "user_id": pf.user_id, "em": now.isoformat(timespec="seconds"), "carteiras": wallets,
               "texto": texto, "status": "gerado", "auto": auto}
        await self.db.insert("study_ai_reports", row)
        if auto:
            pf._emit(f"Carteiras em estudo: relatório automático {rid} pronto com {len(wallets)} carteira(s) nova(s) — copie e mande para o ChatGPT")
        return row

    async def study_ai_auto(self, pf, now: float) -> dict | None:
        """Relatório automático (0.32.48, "você decide quantas"): sai quando 5 carteiras novas entram no estudo sem relatório,
        ou quando a mais antiga sem relatório já espera 24 h. Uma por volta do estudo automático (30 min)."""
        from .auto_trades import ts
        from .study_ai import auto_due, pending_wallets
        if getattr(pf, "role", "user") != "admin":
            return None
        reps = await self.study_ai_reports(pf)
        pend = pending_wallets(list(getattr(pf, "study", []) or []), reps)
        try:
            rows = await self.db.select("study_wallets", {"user_id": pf.user_id}, columns="wallet,criado_em")
        except Exception:
            rows = []
        added = {r["wallet"]: ts(r.get("criado_em")) or now for r in rows}
        if not auto_due(pend, added, now):
            return None
        return await self.study_ai_create(pf, pend, auto=True)

    def study_ai_analysis(self, rid: str) -> str | None:
        """Análise do Claude: arquivo app/analises_carteiras/<id>.md (vem com a versão nova; o relatório vira "analisado")."""
        import pathlib
        f = pathlib.Path(__file__).parent / "analises_carteiras" / f"{rid}.md"
        try:
            return f.read_text(encoding="utf-8") if f.is_file() else None
        except Exception:
            return None

    async def study_copy_judge(self, pf, log_rows: list, info_of: dict, now: float, note) -> None:
        """0.32.38 (pedido do dono: "isso tem que ser estudado e aprendido pela IA"): o resultado DE VERDADE de copiar cada
        carteira do estudo (trades fechados da conta nos últimos 7 dias) vira decisão e aprendizado:
        - 8+ trades no prejuízo com acerto abaixo de 40%: a IA para de copiar as que ela mesma pôs ("parou_de_copiar"); nas
          que o dono escolheu, só registra a sugestão ("sugere_parar") — a escolha dele não muda sozinha;
        - 8+ trades no lucro: "copiou_lucro". Essas decisões contam como aprovação/descarte no "O que ela aprendeu".
        Uma decisão do mesmo tipo por carteira a cada 24 h."""
        from .auto_trades import ts
        from .autostudy import facts_features
        copied = set(getattr(pf, "study_copy", None) or []) | set(getattr(pf, "sim_only_list", None) or []) | set(getattr(pf, "real_ok_list", None) or [])
        copied |= set(getattr(pf, "study", None) or []) & set(pf.manual or [])
        if not copied:
            return
        last: dict = {}
        for r in log_rows:
            if r.get("acao") in ("parou_de_copiar", "sugere_parar", "copiou_lucro"):
                last.setdefault((r.get("wallet"), r.get("acao")), ts(r.get("em")) or 0)
        cut = now - 7 * 86400
        trades = [t for t in pf.trades(5000) if not t.get("real") and (ts(t.get("closed_at")) or 0) >= cut]
        for w in sorted(copied):
            T = [t for t in trades if t.get("wallet") == w]
            if len(T) < 8:
                continue
            wins = sum(1 for t in T if (t.get("pnl_sol") or 0) > 0)
            pnl = sum(t.get("pnl_sol") or 0 for t in T)
            acerto = wins / len(T) * 100
            inf = dict(info_of.get(w, {}))
            fx = self.wallet_facts(w, want=False)
            inf["features"] = {**(inf.get("features") or {}), **(facts_features(fx) if fx.get("lido") else {})}
            inf["copia"] = {"trades": len(T), "acerto": round(acerto), "pnl_sol": round(pnl, 6)}
            txt = f"copiando de verdade (fictícia, 7 dias): {len(T)} trades, acerto {acerto:.0f}%, {pnl:+.4f} SOL"
            if pnl < 0 and acerto < 40:
                ia = w in (getattr(pf, "study_copy", None) or [])
                acao = "parou_de_copiar" if ia else "sugere_parar"
                if now - last.get((w, acao), 0) < 86400:
                    continue
                if ia:
                    pf.study_copy = [x for x in pf.study_copy if x != w]
                    if w in (getattr(pf, "ia_added", None) or []) and w in (pf.manual or []):
                        pf.remove_manual(w)
                    pf.ia_added = [x for x in (getattr(pf, "ia_added", None) or []) if x != w]
                    await self.save_settings(pf)
                    pf.refresh_followed(force=True)
                await note(w, acao, txt + (" — a IA parou de copiar" if ia else " — sugestão: parar de copiar (foi você quem escolheu)"), inf)
            elif pnl > 0 and now - last.get((w, "copiou_lucro"), 0) >= 86400:
                await note(w, "copiou_lucro", txt, inf)

    async def study_copy_sync(self, pf, log_rows: list, done_now: dict | None = None) -> None:
        """0.32.11 (pedido do dono): com pump_st_auto_copy, as carteiras aprovadas que continuam no estudo são copiadas
        (só fictícia). Descartada ou tirada do estudo sai da cópia. Com a opção desligada, a lista fica vazia."""
        done_now = done_now or {}
        last: dict[str, str] = {}
        for r in reversed(log_rows):                          # do mais antigo para o mais novo: fica a última decisão
            if r.get("acao") in ("aprovou", "descartou"):
                last[r["wallet"]] = r["acao"]
        last.update(done_now)
        cur = set(getattr(pf, "study", []) or [])
        new = sorted(w for w, a in last.items() if a == "aprovou" and w in cur) if getattr(pf.cfg, "pump_st_auto_copy", False) else []
        # 0.32.13 (pedido do dono: "aprovou vai direto para o Top traders, cópia manual, só fictício"): a aprovada entra na
        # lista manual de Top traders, marcada como da IA (study_copy) para nunca ir para a real. Carteira que o dono já
        # tinha posto à mão fica como estava (sem marca, segue a regra dele).
        # 0.32.17: a aprovada fica SÓ na fictícia mesmo que o dono já a tivesse posto à mão (pedido do dono: "por enquanto
        # só fictícia, pra testes"); a IA só tira da lista manual as que ela mesma pôs (ia_added).
        old = list(getattr(pf, "study_copy", None) or [])
        if new != old:
            add = [w for w in new if w not in old]
            rem = [w for w in old if w not in new]
            pf.study_copy = new
            for w in add:
                if w not in (pf.manual or []):
                    pf.add_manual(w)
                    pf.ia_added = list(dict.fromkeys(list(pf.ia_added or []) + [w]))
            for w in rem:
                if w in (pf.ia_added or []) and w in (pf.manual or []) and w not in (pf.sim_only_list or []):
                    pf.remove_manual(w)
                pf.ia_added = [x for x in (pf.ia_added or []) if x != w]
            await self.save_settings(pf)
            pf.refresh_followed(force=True)
            if add:
                pf._emit("Estudo automático: copiando (só fictícia) " + ", ".join(f"{w[:4]}…{w[-4:]}" for w in add))
            if rem:
                pf._emit("Estudo automático: parou de copiar " + ", ".join(f"{w[:4]}…{w[-4:]}" for w in rem))

    @staticmethod
    def _tune_kinds() -> tuple:
        from .autotune import AUTO_KEYS, AUTO_MIN_TRADES, KEYS, MIN_TRADES, auto_variant_settings, variant_settings
        return (("saida", variant_settings, KEYS, MIN_TRADES, lambda t: not t.get("manual") and not t.get("auto")),
                ("saida_auto", auto_variant_settings, AUTO_KEYS, AUTO_MIN_TRADES, lambda t: t.get("origem") == "explorar"))

    async def tune_suggest(self, pf, now: float | None = None) -> list[dict]:
        """0.32.118: com a execução real ligada o ajuste não muda nada sozinho (as opções valem para as duas carteiras), então ficava parado
        e a base não evoluía. Faz as mesmas contas de `auto_tune` e devolve o que faria, para a pessoa aplicar com um clique."""
        from .auto_trades import ts
        from .autotune import PAUSE_H, REJECT_S, bad_traders, evaluate, pick_exit
        from .pumpfun import AUTO_ORIGINS
        from .reports import autopsy
        now = time.time() if now is None else now
        if (getattr(pf, "role", "user") != "admin" or not getattr(pf.cfg, "pump_tune_on", True) or getattr(pf, "brain_freeze", None)
                or not getattr(pf.cfg, "pump_real_enabled", False)):
            return []
        log_rows = await self.db.select("auto_tune_log", {"user_id": pf.user_id}, order="em.desc", limit=500)
        trades = pf.trades(100000)
        out: list[dict] = []
        for tipo, mapper, keys, min_n, sel in self._tune_kinds():
            alvo = "automáticas do Explorar" if tipo == "saida_auto" else "cópias"
            last = next((r for r in log_rows if r.get("tipo") == tipo), None)
            if last and last.get("acao") == "aplicou":
                det = last.get("detalhe") or {}
                ev = evaluate(last, trades, now, ts, sel)
                if ev is None:
                    continue                                   # ainda em teste: uma mudança de cada vez
                if ev[0] == "desfez":
                    antes = det.get("antes") or {}
                    mud = [{"opcao": k, "antes": getattr(pf.cfg, k, None), "depois": v} for k, v in antes.items() if getattr(pf.cfg, k, None) != v]
                    if mud:
                        out.append({"id": f"{tipo}:voltar", "tipo": tipo, "acao": "desfez", "alvo": alvo, "variante": det.get("variante"),
                                    "nome": f"Voltar ao que era antes de {det.get('nome')}", "motivo": ev[1], "mudancas": mud})
                    continue
            rejected = {(r.get("detalhe") or {}).get("variante") for r in log_rows
                        if r.get("tipo") == tipo and r.get("acao") == "desfez" and now - (ts(r.get("em")) or 0) < REJECT_S}
            snap = self.ghosts_merged(pf, "ghosts_auto" if tipo == "saida_auto" else "ghosts", trades)
            pick = pick_exit(snap, (now - (ts(snap.get("since")) or now)) / 86400, rejected, mapper, min_n)
            new = mapper(pick["id"]) if pick else None
            antes = {k: getattr(pf.cfg, k) for k in keys}
            mud = [{"opcao": k, "antes": antes.get(k), "depois": v} for k, v in (new or {}).items() if antes.get(k) != v]
            if mud:
                out.append({"id": f"{tipo}:{pick['id']}", "tipo": tipo, "acao": "aplicou", "alvo": alvo, "variante": pick["id"], "nome": pick["nome"],
                            "motivo": f"{pick['avg']:+.5f} SOL/trade nos fantasmas ({pick['trades']} trades) × suas regras {pick['mine_avg']:+.5f}",
                            "mudancas": mud, "antes": antes})
        week = [t for t in trades if not t.get("real") and not t.get("manual") and t.get("origem") not in AUTO_ORIGINS
                and pf.valid_addr(t.get("wallet") or "") and now - (ts(t.get("closed_at")) or 0) < 7 * 86400]
        for x in bad_traders(autopsy(week), set(pf.paused())):
            out.append({"id": "trader:" + x["wallet"], "tipo": "trader", "acao": "pausou", "alvo": "cópias", "wallet": x["wallet"], "horas": PAUSE_H,
                        "nome": f"Pausar {x['wallet'][:4]}…{x['wallet'][-4:]} por {PAUSE_H} h", "mudancas": [],
                        "motivo": f"{x['trades']} cópias, acerto {x['acerto'] * 100:.0f}%, {x['pnl_sol']:+.4f} SOL ({x['causa_nome']})"})
        return out

    async def tune_apply(self, pf, sid: str, now: float | None = None) -> dict:
        """Aplica uma sugestão de `tune_suggest`. Refaz a conta aqui: nada do que o navegador manda vira valor de opção."""
        now = time.time() if now is None else now
        sug = next((x for x in await self.tune_suggest(pf, now) if x["id"] == sid), None)
        if not sug:
            return {"error": "essa sugestão não vale mais; atualize a tela"}
        det = {"variante": sug.get("variante"), "nome": sug["nome"]}
        if sug["tipo"] == "trader":
            pf.pause(sug["wallet"], sug["horas"], "sugestão do ajuste automático: " + sug["motivo"])
            det = {"wallet": sug["wallet"]}
        else:
            vals = {m["opcao"]: m["depois"] for m in sug["mudancas"]}
            applied, errors = pf.cfg.apply(vals)
            if errors:
                return {"error": "não consegui aplicar: " + str(errors)[:120]}
            quando = datetime.fromtimestamp(now, timezone.utc).isoformat()
            ov = pf.__dict__.setdefault("_ov_user", {})        # foi a pessoa que clicou: ajuste antigo do chat não volta por cima
            for key in applied:
                ov[key] = quando
            pf._cfg_why = "ajuste automático que você aplicou"
            await self.save_settings(pf)
            if sug["acao"] == "aplicou":
                det.update(antes=sug["antes"], depois=vals)
        await self.db.insert("auto_tune_log", {"user_id": pf.user_id, "tipo": sug["tipo"], "acao": sug["acao"], "motivo": f"você aplicou · {sug['alvo']} · {sug['nome']}: {sug['motivo']}",
                                               "detalhe": det, "em": datetime.fromtimestamp(now, timezone.utc).isoformat()})
        pf._emit(f"Ajuste automático: você aplicou — {sug['nome']}")
        return {"ok": True, "nome": sug["nome"]}

    async def auto_tune(self, pf, now: float | None = None) -> dict:
        """Ajuste automático (0.31.14, app/autotune.py): aplica a regra de saída que os fantasmas mostram render mais,
        desfaz se piorar e pausa trader que só dá prejuízo. Só com a execução real desligada."""
        from .auto_trades import ts
        from .autotune import PAUSE_H, REJECT_S, bad_traders, evaluate, pick_exit
        from .reports import autopsy
        now = time.time() if now is None else now
        if getattr(pf, "role", "user") != "admin" or not getattr(pf.cfg, "pump_tune_on", True):
            return {"ok": False, "motivo": "desligado"}
        if getattr(pf.cfg, "pump_real_enabled", False):
            return {"ok": False, "motivo": "execução real ligada: o ajuste não muda nada sozinho; veja as sugestões na tela"}
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
        for tipo, mapper, keys, min_n, sel in self._tune_kinds():
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
                        pf._cfg_why = "ajuste automático"
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
                    pf._cfg_why = "ajuste automático"
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

    LUCRO_MIN_TOKENS = 3

    async def study_lucro_sync(self, pf) -> list[str]:
        """0.32.211 (pedido do dono): "deram lucro" = carteiras em estudo com resultado positivo na cópia simulada de 30 dias
        (com atraso e taxas; o mesmo cálculo do Ranking: quem compensa copiar) e pelo menos 3 tokens fechados. Só calcula com a
        chave do quadro ligada; o motor copia essas carteiras só na FICTÍCIA."""
        if not getattr(pf.cfg, "pump_st_lucro_on", False):
            pf.study_lucro = []
            return []
        from .study import copy_params, summary
        prm = copy_params(pf)
        out = []
        for r in await self.db.select("study_wallets", {"user_id": pf.user_id}, order="criado_em.asc"):
            p = await self.study_profile(r["wallet"], prm)
            cp = (summary(p) if not p.get("error") else {}).get("copy") or {}
            if (cp.get("n_30d") or 0) >= self.LUCRO_MIN_TOKENS and (cp.get("pnl_30d") or 0) > 0:
                out.append(r["wallet"])
        pf.study_lucro = out
        pf.refresh_followed(force=True)
        return out

    async def study_auto_loop(self) -> None:
        await asyncio.sleep(120)
        while True:
            for pf in list(self.engines.values()):
                try:
                    await self.study_auto(pf)
                except Exception as e:
                    log.warning("estudo automático (%s…): %s", pf.user_id[:8], str(e)[:160])
                try:
                    await self.study_lucro_sync(pf)
                except Exception as e:
                    log.warning("estudo · deram lucro (%s…): %s", pf.user_id[:8], str(e)[:160])
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
        return self.st_pick()

    def st_pick(self, prefer=()) -> str:
        """0.32.71: chave da Solana Tracker para consulta compartilhada: primeiro as de `prefer`, depois as pessoais de
        todos, por fim a do sistema — pulando a que respondeu "Insufficient credits" na última hora."""
        own = [e.keys.get("solanatracker_api_key") for e in self.engines.values() if e.lb_key_own()]
        return stkeys.pick(list(prefer) + own + [getattr(self, "shared_st_key", "")])

    STUDY_EVERY_S = 6 * 3600

    async def refresh_study_wallet(self, wallet: str, force: bool = False) -> str | None:
        """Histórico por token da Solana Tracker (até 200 posições dos últimos 30 dias) → study_positions."""
        from .pumpfun import ST_PNL
        from .study import compact_position
        key = self._study_key()
        if not key:
            return "sem chave da Solana Tracker (histórico só pelo monitor, a partir de agora)"
        # 0.32.238 (dono: "gasta muita Solana Tracker"): o histórico de 30 dias de cada carteira em estudo era buscado a cada
        # 30 min (~1.450 consultas/dia com 30 carteiras); agora a cada 6 h. O monitor segue registrando ao vivo.
        if not force and time.time() - self._study_at.get(wallet, 0) < self.STUDY_EVERY_S:
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
        out = [k for k in keys if k in USER_KEYS and k != "pump_sim_on" and not any(b in k for b in self.SHARE_BLOCK)]   # ligar a carteira é de cada um
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

    async def config_peer(self, uid: str, peer: str, keys) -> dict:
        """0.32.151 (pedido do dono): Abas de trades → Ajustes compara as opções da aba com as de outro usuário (só admin,
        só leitura). Mesmas regras do compartilhar: nada da carteira real nem do Telegram."""
        if peer == uid:
            return {"error": "escolha outro usuário"}
        rows = await self.db.select("profiles", {"user_id": peer}, columns="user_id,bloqueado,role,nome,email")
        if not rows or rows[0].get("bloqueado"):
            return {"error": "usuário não encontrado"}
        keys = self.share_filter(keys, True)
        other = self.engines.get(peer) or await self.engine(peer)
        nome = rows[0].get("nome") or (rows[0].get("email") or "").split("@")[0] or "outro usuário"
        return {"user_id": peer, "nome": nome, "valores": {k: getattr(other.cfg, k) for k in keys}}

    async def buy_diff(self, uid: str, peer: str, horas: float) -> dict:
        """0.32.167 (pedido do dono): compras FICTÍCIAS de duas contas lado a lado e, moeda a moeda, por que a outra não
        comprou. Só leitura."""
        if peer == uid:
            return {"error": "escolha outro usuário"}
        rows = await self.db.select("profiles", {"user_id": peer}, columns="user_id,bloqueado,role,nome,email")
        if not rows or rows[0].get("bloqueado"):
            return {"error": "usuário não encontrado"}
        from . import buydiff
        a = self.engines.get(uid) or await self.engine(uid)
        b = self.engines.get(peer) or await self.engine(peer)
        r = buydiff.compare(a, b, horas)
        r["outro"] = rows[0].get("nome") or (rows[0].get("email") or "").split("@")[0] or "outro usuário"
        r["nomes"] = dict(a.market.__dict__.get("trader_names") or {})
        return r

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
        return [{"id": r["id"], "de": r.get("de_nome"), "de_user": r.get("de_user"), "parte": r.get("parte"), "em": r.get("respondido_em"),
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
            pf._cfg_why = f"aplicou a configuração de {r.get('de_nome') or 'outra conta'}"
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
            trades = await self.hist_select("wallet_trades", {"wallet": wallet}, "at", 2000)
        except Exception as e:
            return {"error": "tabelas das carteiras em estudo ainda não criadas no banco", "detail": str(e)[:120]}
        return profile(wallet, pos, trades, prm=prm)

    def _step(self, etapa: str) -> None:
        self.__dict__.setdefault("boot_info", {})["etapa"] = etapa

    def boot_status(self) -> dict:
        """Para o /health, que é público: só o nome da etapa, o tempo e o tipo do erro, nunca a mensagem."""
        b = self.__dict__.get("boot_info") or {}
        if not b:
            return {}
        return {"etapa": b.get("etapa"), "carregando": bool(b.get("carregando")), "erro": b.get("erro"),
                "segundos": b.get("segundos") if b.get("segundos") is not None else round(time.time() - b.get("inicio", time.time()), 1)}

    async def boot(self) -> None:
        """Roda `start` em segundo plano. Se falhar, o servidor fica de pé dizendo onde parou, em vez de reiniciar sem parar."""
        t0 = time.time()
        self.boot_info = {"etapa": "começando", "inicio": t0, "carregando": True}
        try:
            await self.start()
            self.boot_info.update(etapa="pronto", segundos=round(time.time() - t0, 1), carregando=False)
        except Exception as e:
            self.boot_info.update(segundos=round(time.time() - t0, 1), erro=type(e).__name__, carregando=False, falhou=True)
            log.error("a subida parou em %s: %s", self.boot_info.get("etapa"), str(e)[:300])

    async def start(self) -> None:
        """Carrega todos os usuários (o bot copia mesmo com o painel fechado) e liga as tarefas."""
        self._step("contas")
        try:
            for r in await self.db.select("profiles", None, columns="user_id,bloqueado"):
                if r.get("bloqueado"):
                    self._blocked.add(r["user_id"])
                else:
                    await self.engine(r["user_id"])
        except Exception as e:
            log.warning("Não consegui carregar os usuários do Supabase: %s", str(e)[:160])
        for nome, carga in (("chave compartilhada", self.refresh_shared_key), ("lista negra", self.load_blacklist), ("base pump.fun", self.load_lab),
                            ("maiores traders", self.load_elite), ("sombras", self.load_shadows), ("calls", self.load_calls),
                            ("aba do bruxo", self.load_bruxo), ("jev trade", self.load_jt), ("uso do jev", self.jev_usage_load),
                            ("passado do jev", self.jev_bt_load), ("top traders", self.load_top)):                # 0.32.84: estudo do passado do Jev
            self._step(nome)
            await carga()
        self._step("ligando o monitor")
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
        self._tasks.append(run_as("Gravação no banco", self.flush_loop()))
        self._tasks.append(run_as("Aprendizado diário", self.learning_loop()))
        self._tasks.append(run_as("Estratégias fantasma", self.ghosts_loop()))
        self._tasks.append(run_as("Relatório do dia", self.daily_loop()))
        self._tasks.append(run_as("Carteiras em estudo", self.study_auto_loop()))
        self._tasks.append(run_as("Ajuste automático", self.tune_loop()))
        self._tasks.append(run_as("Base geral", self.base_loop()))           # 0.31.71: base geral
        self._tasks.append(run_as("Explorar (sombras)", self.shadow_loop()))         # 0.31.72: entradas sombra
        self._tasks.append(run_as("Top traders (laboratório)", self.top_loop()))            # 0.32.124: compras barradas do Top traders
        self._tasks.append(run_as("Relatórios", self.tr_loop()))             # 0.32.140: relatório dos traders
        self._tasks.append(run_as("Relatórios", self.week_loop()))           # 0.32.161: semana × fim de semana guardados
        self._tasks.append(run_as("Relatórios", self.th_loop()))             # 0.32.163: histórico de cada trader guardado
        self._tasks.append(run_as("Raio-X do token", self.xray_loop()))           # 0.31.86: Raio-X do token
        self._tasks.append(run_as("Logs dos robôs", self.rlog_loop()))           # 0.31.89: log de análise dos robôs
        self._tasks.append(run_as("Calls quentes", self.calls_loop()))          # 0.31.94: calls quentes
        self._tasks.append(run_as("Aba do Bruxo", self.bruxo_loop()))
        self._tasks.append(run_as("Jev Trade", self.jt_loop()))             # 0.32.87: Jev Trade
        self._tasks.append(run_as("Aba do Bruxo", self.bx_report_loop()))      # 0.32.80: relatórios da Aba do Bruxo (30 min e 1 dia)          # 0.32.41: Aba do Bruxo
        self._tasks.append(run_as("Relatórios", self.tab_report_loop()))
        self._tasks.append(run_as("Execução real", self.wallet_guard_loop()))   # 0.32.116: alerta de saída da carteira real
        self._tasks.append(run_as("Relatórios", self.result_loop()))         # 0.32.114: estudo do Resultado (dias fechados)
        self._tasks.append(run_as("Copiar igual", self.eq_report_loop()))      # 0.32.73: relatório do Copiar igual (6 h)     # 0.32.41: relatório de cada aba (30 min)
        self._tasks.append(run_as("Sistema", self.usage_loop()))          # 0.31.76: uso das APIs
        if getattr(self, "arquivo", None) is not None:                     # 0.32.225: histórico no Postgres da VPS
            self._tasks.append(run_as("Sistema", self.arquivo_loop()))
        self._tasks.append(run_as("Sistema", self.config_watch_loop()))
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
                if not (self.__dict__.get("boot_info") or {}).get("carregando"):
                    await self.save_auto(pf)
            except Exception:
                pass
        b = self.__dict__.get("boot_info") or {}
        if b.get("carregando") or b.get("falhou"):
            return                                     # 0.32.121: dados pela metade na memória; salvar agora apagaria o que está no banco
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
        self._prof_cache.pop(uid, None)
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
                "arquivo": self.arquivo.status() if getattr(self, "arquivo", None) is not None else {"ligado": False},
                "db_errors": [{"user": uid[:8] + "…", "error": p.store.last_error, "queued": len(p.store._q)}
                              for uid, p in self.engines.items() if p.store.last_error or len(p.store._q) > 50]}
