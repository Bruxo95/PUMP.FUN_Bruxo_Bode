"""Monitor COMPARTILHADO: uma conexão com a rede para todos os usuários (etapa 6).

- WebSocket da Solana com a UNIÃO das carteiras seguidas por todos (mais o top dos leaderboards, só para o status
  online). Cada transação é lida UMA vez (getTransaction) e entregue ao motor de cada usuário que segue aquela
  carteira.
- Preço ao vivo (curva on-chain da pump.fun, Jupiter para graduados, DexScreener), concentração dos 10 maiores,
  saldo dos traders, detecção de robô e preço do SOL: tudo uma vez só, para todos.
- Leaderboard da Solana Tracker: cache por (período, trades mínimos, acerto mínimo) — usuários com os mesmos
  filtros dividem a mesma consulta; a chave usada é a do usuário (ou a emprestada pelo admin).
- Cada usuário tem a SUA fila de execução real (uma tarefa por motor).

A lógica é a do original (PumpFun.rpc_run / tx_worker / price_loop / trail_fast_loop / lb_loop); aqui ela só
olha para todos os motores em vez de um.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque

from .pumpfun import PUMP_PROGRAMS, PumpFun, now_iso
from .settings import PumpSettings
from .solana_wallet import UserWallet

log = logging.getLogger("monitor")



def _gm(e) -> set:
    """Tokens das estratégias fantasma de um motor (0.18.0); motores de teste sem fantasmas devolvem vazio."""
    out = set()
    for name in ("ghosts", "ghosts_auto"):                # 0.31.21: fantasmas das automáticas do Explorar também
        g = getattr(e, name, None)
        if g is not None:
            out |= g.mints()
    return out

class SharedMonitor:
    LOW_PER_MIN = 6                                 # 0.32.8: leituras/min por carteira não copiada
    def __init__(self, hub):
        self.hub = hub
        self.market = hub.market
        # "motor de serviço": mesma classe do usuário, sem dados de usuário — usado só para as funções públicas
        # (preços, curva, transações, robôs, saldo de trader, leaderboard)
        cfg = PumpSettings(None, hub.cfg.defaults)
        self.svc = PumpFun(cfg, None, hub.http, UserWallet("", "", hub.cfg.solana_rpc_public), market=self.market)
        self.svc.on_event = None
        self._tx_q: asyncio.Queue | None = None
        # 0.32.4: fila só das carteiras COPIADAS. Em 28/10 o status mostrou 139.115 lidas e 133.834 "atrasadas" (+2 min
        # na fila): as cópias esperavam atrás das carteiras de estudo/Maiores traders e quase tudo chegava velho demais.
        self._tx_hi: asyncio.Queue | None = None
        # 0.32.7 (pedido do dono): amostra das últimas leituras de cada tipo, para abrir e analisar no status do sistema
        self.rpc_log: dict[str, deque] = {k: deque(maxlen=300) for k in ("falha", "atrasado", "nao_trade", "trade")}
        self.rpc_why: dict[str, int] = {}
        self._low_lim: dict[str, deque] = {}            # 0.32.8: leituras por minuto de quem não é copiado
        self._pp_subs: set[str] = set()                 # 0.32.18: carteiras assinadas na PumpPortal (subscribeAccountTrade)
        self._done_sigs: deque = deque(maxlen=20000)    # 0.32.18: assinatura já entregue (PumpPortal e RPC não repetem)
        self._done_set: set = set()
        self._seen: deque = deque(maxlen=5000)
        self._subs: dict = {}
        self.lb_cache: dict = {}            # (dias, trades, acerto, plataforma) -> {"at", "rows", "status"}
        self._sol_at = 0.0
        self._tasks: list[asyncio.Task] = []

    # ------------------------------------------------------------------ quem segue quem
    def engines(self) -> list[PumpFun]:
        return list(self.hub.engines.values())

    def followers(self, w: str) -> list[PumpFun]:
        return [e for e in self.engines() if w in e.followed]

    def union_followed(self) -> set:
        out = set()
        for e in self.engines():
            out |= set(e.followed)
        return out

    def watch_set(self) -> set:
        """Carteiras assinadas no WebSocket: copiadas por alguém + carteiras em estudo + top 20 do leaderboard (status online).
        Limitado a 100 carteiras para evitar ultrapassar o limite de subscrições do RPC WebSocket."""
        out = self.union_followed()
        for e in self.engines():
            out |= set(getattr(e, "study", []) or [])          # carteiras em estudo (0.14.0)
        lb_wallets = set()
        for e in self.engines():
            lb_wallets |= {r["wallet"] for r in e.leaderboard[:20] if r.get("wallet")}
        # Adiciona carteiras do leaderboard até atingir o limite máximo de 100
        for w in sorted(lb_wallets):
            if len(out) >= 100:
                break
            out.add(w)
        return out

    # ------------------------------------------------------------------ entrega de um evento a todos
    def pp_wanted(self) -> set:
        """0.32.18: carteiras copiadas por alguém, se algum admin ligou pump_pp_copy e existe a chave PumpPortal do sistema."""
        if not self.hub.system_keys.get("pumpportal_api_key"):
            return set()
        if not any(getattr(e.cfg, "pump_pp_copy", False) and getattr(e, "role", None) == "admin" for e in self.engines()):
            return set()
        return set(self.union_followed())

    def _seen_sig(self, sig) -> bool:
        """True se esta transação já foi entregue aos motores (pela PumpPortal ou pelo RPC)."""
        if not sig:
            return False
        if sig in self._done_set:
            return True
        if len(self._done_sigs) == self._done_sigs.maxlen:
            self._done_set.discard(self._done_sigs[0])
        self._done_sigs.append(sig)
        self._done_set.add(sig)
        return False

    def dispatch(self, ev: dict, t: float | None = None, only: list | None = None) -> None:
        """Parte pública do evento UMA vez; depois cada motor reage (cópia de quem segue + stops de quem tem
        posição no token)."""
        t = t or time.time()
        lab = getattr(self.hub, "lab", None)
        if lab is not None and ev.get("txType") == "create":
            lab.on_create(ev, t)                                  # base própria da pump.fun (0.21.0)
        info = self.svc.ingest(ev, t)
        if not info:
            return
        for e in (only if only is not None else self.engines()):
            try:
                for m in e.react(ev, t, info):
                    e._emit(m)
            except Exception as ex:
                log.warning("cópia (%s…): %s", getattr(e, "user_id", "?")[:8], str(ex)[:160])

    # ------------------------------------------------------------------ WebSocket da Solana (grátis)
    async def rpc_run(self) -> None:
        import websockets
        backoff = 2.0
        if self._tx_q is None:
            self._tx_q = asyncio.Queue(maxsize=600)     # 0.32.8: fila curta (com 4000 tudo ficava velho antes de ser lido)
        if self._tx_hi is None:
            self._tx_hi = asyncio.Queue(maxsize=2000)
        st = self.market.rpc_status
        while True:
            if not self.hub.cfg.defaults.get("pump_enabled", True):
                st.update(ws=False, error="desligado no servidor (PUMP_ENABLED)")
                await asyncio.sleep(5)
                continue
            try:
                sys_rpc = self.hub.system_keys.get("rpc_url") or ""
                if sys_rpc:
                    url = sys_rpc.replace("https://", "wss://").replace("http://", "ws://")
                else:
                    url = str(self.hub.cfg.defaults.get("pump_rpc_ws") or "wss://api.mainnet-beta.solana.com")
                async with websockets.connect(url, open_timeout=15, ping_interval=20, max_size=2 ** 22) as ws:
                    connected_time = time.time()
                    if st.get("connected_at"):          # 0.32.3 (Bruxo): quantas vezes a conexão caiu e voltou
                        st["reconnects"] = st.get("reconnects", 0) + 1
                    st.update(ws=True, connected_at=now_iso(), error=None)
                    log.info("Monitor compartilhado conectado à Solana")
                    self._subs, pending, nid = {}, {}, 100
                    while True:
                        # Reset do backoff se a conexão permaneceu estável por mais de 30s
                        if time.time() - connected_time > 30.0:
                            backoff = 2.0

                        want = self.watch_set()
                        have = set(self._subs.values()) | set(pending.values())
                        for w in sorted(want - have):
                            nid += 1
                            pending[nid] = w
                            await ws.send(json.dumps({"jsonrpc": "2.0", "id": nid, "method": "logsSubscribe",
                                                      "params": [{"mentions": [w]}, {"commitment": "confirmed"}]}))
                            await asyncio.sleep(0.05)  # Throttle subscrições para evitar rate limit (1013)
                        for sid, w in list(self._subs.items()):
                            if w not in want:
                                nid += 1
                                del self._subs[sid]
                                await ws.send(json.dumps({"jsonrpc": "2.0", "id": nid, "method": "logsUnsubscribe",
                                                          "params": [sid]}))
                                await asyncio.sleep(0.05)
                        st["subs"] = len(self._subs)
                        try:
                            raw = await asyncio.wait_for(ws.recv(), 2.0)
                        except asyncio.TimeoutError:
                            continue
                        try:
                            msg = json.loads(raw)
                        except ValueError:
                            continue
                        if "id" in msg and msg.get("id") in pending:
                            w = pending.pop(msg["id"])
                            if "result" in msg:
                                self._subs[msg["result"]] = w
                            else:
                                st["error"] = str(msg.get("error"))[:120]
                            continue
                        if msg.get("method") == "logsNotification":
                            self.on_notification(msg)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                st.update(ws=False, error=f"{type(e).__name__}: {str(e)[:120]}")
                log.warning("Monitor compartilhado caiu (%s) — reconectando em %.0f s", str(e)[:100], backoff)
                await asyncio.sleep(backoff)
                backoff = min(60.0, backoff * 2)

    def on_notification(self, msg: dict) -> None:
        """Atualiza atividade e lê trades de carteiras copiadas ou em estudo."""
        st = self.market.rpc_status
        prm = msg.get("params") or {}
        w = self._subs.get(prm.get("subscription"))
        val = ((prm.get("result") or {}).get("value")) or {}
        sig = val.get("signature")
        st["notifs"] += 1
        seen_key = (w, sig)
        if not w or not sig or seen_key in self._seen:
            return
        self._seen.append(seen_key)
        act = self.market.activity.setdefault(w, {"last": None, "n": deque(maxlen=600), "pump": 0, "pump_last": None,
                                                   "other": 0, "pn": deque(maxlen=600)})
        now = time.time()
        act["last"] = now
        act["n"].append(now)
        fol = self.followers(w)
        studied = any(w in (getattr(e, "study", []) or []) for e in self.engines())
        # 0.31.95: os Maiores traders também são lidos (antes só eram "vistos" se ninguém os copiava, e por isso não
        # viravam sinal nem call). Ler não autoriza copiar: a cópia continua só para quem é seguido.
        el = getattr(getattr(self.hub, "elite", None), "wallets", None)
        studied = studied or bool(el and w in el())
        was_bot = act.get("bot_until", 0) > now
        is_bot = self.svc._is_bot(w, now)
        if is_bot:
            if not was_bot:
                for e in self.engines():               # refaz a lista de copiados de todos já
                    e._rank_at = 0
                    if e in fol:
                        e._emit(f"Pump.fun: {w[:4]}…{w[-4:]} parece robô ({act.get('bot_reason')}) — fora da cópia por 1 h")
            if not studied or not fol:
                # 0.32.8: robô que ninguém copia não é lido (só gastava a cota do RPC). Copiado continua sendo lido.
                if studied:
                    st["skipped_bot"] = st.get("skipped_bot", 0) + 1
                return
        else:
            self._fill_slot(w)
        if val.get("err"):
            return
        logs = " ".join(val.get("logs") or [])
        is_pump = any(pid in logs for pid in PUMP_PROGRAMS)
        if is_pump:
            act["pump"] += 1
            act["pump_last"] = now
            act.setdefault("pn", deque(maxlen=600)).append(now)
        else:
            act["other"] += 1
        if not fol and not studied:
            return                                     # só observando (status online do top)
        if is_pump and w in self._pp_subs:
            st["pp_skip"] = st.get("pp_skip", 0) + 1   # 0.32.18: chega pronta pela PumpPortal; não gasta o RPC
            return
        if not is_pump and not studied and not any(getattr(e.cfg, "pump_copy_other", True) for e in fol):
            return
        if not fol:
            # 0.32.8: carteira que ninguém copia (estudo / Maiores traders) lê no máximo LOW_PER_MIN transações por minuto.
            # Em 28/10 uma só carteira de estudo (8ekC…CDiF) ocupava quase todas as leituras e o RPC público devolvia 429.
            lim = self._low_lim.setdefault(w, deque(maxlen=self.LOW_PER_MIN))
            if len(lim) >= self.LOW_PER_MIN and now - lim[0] < 60:
                st["limited"] = st.get("limited", 0) + 1
                return
            lim.append(now)
        q = self._tx_hi if (fol and self._tx_hi is not None) else self._tx_q
        try:
            q.put_nowait((w, sig, now))
            st["queued"] = st.get("queued", 0) + 1     # 0.32.3: avisos que foram para leitura (funil do status)
            if q is self._tx_hi:
                st["queued_hi"] = st.get("queued_hi", 0) + 1
        except asyncio.QueueFull:
            st["dropped"] = st.get("dropped", 0) + 1

    def _rpc_note(self, kind: str, w: str, sig: str, t0: float, cop: bool, why: str, extra: str = "", mint=None) -> None:
        self.rpc_log[kind].append({"t": time.time(), "aviso_t": t0, "wallet": w, "sig": sig, "copiada": cop,
                                   "motivo": why, "extra": extra, "mint": mint})

    def rpc_report(self, kind: str) -> dict:
        """0.32.7: o que abrir ao clicar numa linha do funil do status (últimas 300 de cada tipo, só memória)."""
        rows = list(self.rpc_log.get(kind) or [])[::-1]
        def key(r):
            if kind == "falha":
                return r["motivo"]
            if kind == "trade":
                return r["motivo"].split(" ")[0]
            return "carteira copiada" if r["copiada"] else "estudo / maiores traders"
        mot: dict[str, int] = {}
        for r in rows:
            mot[key(r)] = mot.get(key(r), 0) + 1
        por: dict[str, dict] = {}
        for r in rows:
            p = por.setdefault(r["wallet"], {"wallet": r["wallet"], "n": 0, "copiada": r["copiada"]})
            p["n"] += 1
        return {"tipo": kind, "linhas": rows[:300], "motivos": sorted(({"motivo": k, "n": n} for k, n in mot.items()),
                                                                     key=lambda x: -x["n"]),
                "por_carteira": sorted(por.values(), key=lambda x: -x["n"])[:30],
                "motivos_falha_total": sorted(({"motivo": k, "n": n} for k, n in self.rpc_why.items()), key=lambda x: -x["n"]),
                "fila": {"copiadas": self._tx_hi.qsize() if self._tx_hi else 0, "outras": self._tx_q.qsize() if self._tx_q else 0}}

    async def tx_worker(self, hi: bool = False) -> None:
        while (self._tx_hi if hi else self._tx_q) is None:
            await asyncio.sleep(0.5)
        while True:
            w, sig, t0 = await (self._tx_hi if hi else self._tx_q).get()
            try:
                await self.handle_tx(w, sig, t0)
            except Exception as e:
                self.market.rpc_status["tx_errors"] += 1
                log.warning("transação %s: %s", sig[:12], str(e)[:160])

    async def handle_tx(self, w: str, sig: str, t0: float, tx: dict | None = None) -> None:
        st, svc = self.market.rpc_status, self.svc
        cop = bool(self.followers(w))
        if time.time() - t0 > (120 if cop else 60):     # atrasou demais (0.32.8: 60 s para quem não é copiado)
            st["stale"] = st.get("stale", 0) + 1
            if cop:
                st["stale_hi"] = st.get("stale_hi", 0) + 1
            self._rpc_note("atrasado", w, sig, t0, cop, f"{time.time() - t0:.0f} s na fila")
            return
        t1, why = time.time(), []
        tx = tx or await svc._get_tx(sig, why, low=not cop)
        if not tx:
            st["tx_errors"] += 1
            for x in set(why) or {"sem motivo"}:
                self.rpc_why[x] = self.rpc_why.get(x, 0) + 1
            self._rpc_note("falha", w, sig, t0, cop, " · ".join(dict.fromkeys(why)) or "sem motivo",
                           f"{time.time() - t1:.1f} s tentando, {len(why)} tentativas")
            return
        ev = svc.parse_trade(tx, w, self.market.sol_usd)
        if ev and self._seen_sig(f"{w}:{sig}"):
            st["dup"] = st.get("dup", 0) + 1            # 0.32.18: já veio pela PumpPortal
            return
        await self.handle_ev(w, sig, t0, ev, cop)

    async def handle_ev(self, w: str, sig: str, t0: float, ev: dict | None, cop: bool, via: str = "RPC") -> None:
        """Trade já decodificado (do RPC ou da PumpPortal, 0.32.18): estudo, maiores traders, calls e cópia."""
        st, svc = self.market.rpc_status, self.svc
        if ev and any(w in (getattr(e, "study", []) or []) for e in self.engines()):
            self.hub.record_trade(w, ev)                        # carteiras em estudo: guarda no banco
        if ev and w in self.hub.elite.wallets():
            self.elite_event(w, ev)                             # maiores traders (0.31.2)
        if not ev:
            st["not_trade"] = st.get("not_trade", 0) + 1     # transação lida, mas não era compra/venda de token
            self._rpc_note("nao_trade", w, sig, t0, cop, "não mexeu em token contra SOL")
            return
        self._rpc_note("trade", w, sig, t0, cop, f"{ev.get('txType')} {float(ev.get('solAmount') or 0):.3f} SOL",
                       f"{'pela PumpPortal' if via == 'PumpPortal' else 'lido'} {time.time() - t0:.1f} s depois do aviso",
                       mint=ev.get("mint"))
        st["parsed"] += 1
        st["last_event"] = time.time()
        try:
            if hasattr(self.hub, "calls_on_trade"):
                self.hub.calls_on_trade(w, ev)                  # 0.31.94: toda compra acompanhada vira uma call
        except Exception as e:
            log.warning("calls quentes: %s", str(e)[:120])
        # Observar não autoriza copiar. Robôs seguem bloqueados mesmo que estejam no estudo.
        if not self.followers(w) or (self.market.activity.get(w) or {}).get("bot_until", 0) > time.time():
            return
        mint = ev["mint"]
        tk0 = self.market.tokens.get(mint) or {}
        if not tk0.get("symbol") or tk0.get("liq_usd") is None or time.time() - (tk0.get("last_t") or 0) > 30:
            await svc._fetch_prices([mint])
        fol = self.followers(w)
        targets = None                                  # None = todos os motores (stops de quem tem o token)
        if not svc.is_pump(mint):
            ok = [e for e in fol if e._other_block(mint) is None]
            if not ok:
                st["ignored"] = st.get("ignored", 0) + 1
                ig = st.setdefault("ignored_by", {})
                ig[w] = ig.get(w, 0) + 1
                return
            ev["marketCapSol"] = (self.market.tokens.get(mint) or {}).get("mcap_sol")
            ev["other"] = True
            oc = st.setdefault("other_by", {})
            oc[w] = oc.get(w, 0) + 1
            blocked = set(fol) - set(ok)
            targets = [e for e in self.engines() if e not in blocked]
        if ev["txType"] == "buy" and fol:
            tk1 = self.market.tokens.get(mint) or {}
            if time.time() - (tk1.get("vol_t") or 0) > 20:
                await svc._fetch_prices([mint], set_price=not svc.is_pump(mint))
            try:
                await svc.holders_check(mint)
                if any(getattr(e.cfg, "pump_risk_check", True) for e in fol):
                    # chave de quem segue (própria) ou a do sistema; uma consulta por token serve para todos
                    key = next((e.lb_key() for e in fol if e.lb_key_own()), "") or self.hub.shared_st_key
                    await svc.risk_check(mint, key)
            except Exception:
                pass
        self.dispatch(ev, only=targets)

    # ------------------------------------------------------------------ PumpPortal (tokens novos, grátis)
    async def pumpportal_run(self) -> None:
        import websockets
        backoff = 2.0
        st = self.market.status
        while True:
            if not self.hub.cfg.defaults.get("pump_enabled", True):
                st.update(ws=False, error="desligado")
                await asyncio.sleep(5)
                continue
            try:
                url = str(self.hub.cfg.defaults.get("pump_ws_url") or "wss://pumpportal.fun/api/data")
                pk = self.hub.system_keys.get("pumpportal_api_key")
                if pk:
                    url += ("&" if "?" in url else "?") + "api-key=" + pk
                async with websockets.connect(url, open_timeout=15, ping_interval=20, max_size=2 ** 22) as ws:
                    st.update(ws=True, connected_at=now_iso(), error=None)
                    backoff = 2.0
                    await ws.send(json.dumps({"method": "subscribeNewToken"}))
                    self._pp_subs = set()                     # conexão nova: assina de novo
                    sync_at = 0.0
                    while True:
                        if time.time() - sync_at > 10:
                            sync_at = time.time()
                            await self._pp_sync(ws)
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=5)
                        except asyncio.TimeoutError:
                            continue
                        try:
                            ev = json.loads(raw)
                        except ValueError:
                            continue
                        if not isinstance(ev, dict) or not ev.get("txType"):
                            continue
                        w = ev.get("traderPublicKey")
                        if ev.get("txType") in ("buy", "sell") and w in self._pp_subs:
                            self._pp_trade(w, ev)
                        else:
                            self.dispatch(ev)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                from .logsafe import redact
                st.update(ws=False, error=redact(f"{type(e).__name__}: {str(e)[:120]}"))
                await asyncio.sleep(backoff)
                backoff = min(60.0, backoff * 2)

    async def _pp_sync(self, ws) -> None:
        """0.32.18: mantém a assinatura subscribeAccountTrade igual às carteiras copiadas (até 5.000 por mensagem, FAQ)."""
        want = self.pp_wanted()
        add, rem = sorted(want - self._pp_subs), sorted(self._pp_subs - want)
        for i in range(0, len(rem), 500):
            await ws.send(json.dumps({"method": "unsubscribeAccountTrade", "keys": rem[i:i + 500]}))
        for i in range(0, len(add), 500):
            await ws.send(json.dumps({"method": "subscribeAccountTrade", "keys": add[i:i + 500]}))
        self._pp_subs = set(want)
        self.market.status["acct_subs"] = len(want)

    def _pp_trade(self, w: str, ev: dict) -> None:
        """Trade de carteira copiada vindo pronto da PumpPortal: mesma rota do RPC, sem ler a transação."""
        stt = self.market.status
        stt["acct_trades"] = stt.get("acct_trades", 0) + 1
        stt["acct_last"] = time.time()
        sig = ev.get("signature")
        if self._seen_sig(f"{w}:{sig}"):                  # por carteira: 2 copiadas na mesma transação contam as duas
            stt["acct_dup"] = stt.get("acct_dup", 0) + 1
            return
        ev = dict(ev)
        try:                                                # mesmo formato que o motor já lê (on_message original)
            ev["solAmount"], ev["tokenAmount"] = float(ev.get("solAmount") or 0), float(ev.get("tokenAmount") or 0)
        except (TypeError, ValueError):
            return
        now = time.time()
        task = asyncio.get_event_loop().create_task(self.handle_ev(w, sig, now, ev, bool(self.followers(w)), via="PumpPortal"))
        pend = self.__dict__.setdefault("_pp_tasks", set())    # referência forte até terminar
        pend.add(task)
        task.add_done_callback(pend.discard)

    # ------------------------------------------------------------------ preços
    def ghost_mints(self) -> set:
        return {m for e in self.engines() for m in _gm(e)}

    def held(self) -> dict:
        """Tokens em posição (de todos) → quantidade somada; e tokens segurados pelos traders copiados."""
        qty, trader = {}, []
        for e in self.engines():
            for p in e.positions():
                qty[p["mint"]] = qty.get(p["mint"], 0.0) + float(p.get("tokens_left") or 0)
            trader += [p["mint"] for p in e.trader_positions()]
            trader += list(_gm(e))                        # estratégias fantasma (0.18.0) seguem o preço também
            from .auto_trades import follow_mints
            trader += list(follow_mints(getattr(e, "auto_rows", {}), time.time()))
        el = getattr(self.hub, "elite", None)
        if el is not None:
            trader += list(el.open_mints())               # sinais dos maiores traders: 60 min de preço (0.31.2)
        for e in self.engines():                          # 0.32.22: barrados do Explorar (entrar cedo) com preço ao vivo
            if getattr(e, "role", None) == "admin" and getattr(e.cfg, "pump_ex_auto_on", False):
                trader += e.barred_watch()
        return {"qty": qty, "trader": trader}

    def auto_after_once(self, now: float | None = None) -> int:
        from .auto_trades import observe_after
        now = time.time() if now is None else now
        changed = 0
        for engine in self.engines():
            dirty = observe_after(getattr(engine, "auto_rows", {}), self.market.tokens, now)
            engine._auto_dirty.update(dirty)
            changed += len(dirty)
        return changed

    async def price_once(self, do_ds: bool) -> None:
        svc, h = self.svc, self.held()
        held = list(dict.fromkeys(list(h["qty"]) + h["trader"]))[:100]
        if not held:
            self.auto_after_once()
            return
        pump = [m for m in held if svc.is_pump(m)]
        rest = [m for m in held if m not in pump]
        rest += await svc._curve_prices(pump) if pump else []
        if do_ds:
            if rest:
                await svc._fetch_prices(list(dict.fromkeys(rest)))
            mine = [m for m in h["qty"] if m not in rest]
            if mine:
                await svc._fetch_prices(mine, set_price=False)
        self.check_stops(set(h["qty"]) | self.ghost_mints())
        self.auto_after_once()
        self.market.rpc_status["price_at"] = now_iso()

    def check_stops(self, mints) -> None:
        for e in self.engines():
            mine = ({p["mint"] for p in e.positions()} | _gm(e)) & set(mints)
            for m in mine:
                for msg in e._check_stops(m, time.time()):
                    e._emit(msg)

    async def lab_once(self) -> int:
        """Fotos da base da pump.fun: market cap dos tokens novos aos 1, 5, 15 e 60 min (curva on-chain, em lotes)."""
        lab = getattr(self.hub, "lab", None)
        if lab is None:
            return 0
        now = time.time()
        due = lab.due(now)[:300]
        for i in range(0, len(due), 100):
            chunk = due[i:i + 100]
            await self.svc._curve_prices(chunk)
            lab.observe(now, chunk)
        return len(due)

    async def boost_once(self) -> int:
        """Boost pago na DexScreener (0.24.0): tokens de "Subindo agora" e os que alguém segura, no máx. 20 por minuto
        (limite público da DexScreener: 60/min) e cada um no máx. a cada 2 min."""
        lab = getattr(self.hub, "lab", None)
        want = [x["mint"] for x in (lab.rising(time.time()) if lab is not None else [])]
        want += list(self.held()["qty"])
        now, n = time.time(), 0
        for m in dict.fromkeys(want):
            if n >= 20:
                break
            if now - float((self.market.boosts.get(m) or {}).get("t") or 0) < 120:
                continue
            await self.svc.fetch_boost(m)
            n += 1
        return n

    async def explore_once(self) -> bool:
        ex = getattr(self.hub, "explore", None)
        if ex is None:
            return False
        key = next((e.lb_key() for e in self.engines() if e.lb_key_own()), "") or self.hub.shared_st_key
        if not key:
            ex.error = "sem chave da Solana Tracker (Configurações → Chaves, ou a chave do sistema em Administração)"
            return False
        try:
            data = await self.svc.fetch_explore(key)
        except Exception as e:
            from .logsafe import redact
            ex.error = redact(str(e)[:160])
            return False
        ex.update(data or {})
        return True

    async def explore_loop(self) -> None:
        from .explore import EVERY_S
        while True:
            try:
                await self.explore_once()
            except Exception as e:
                log.warning("explorar: %s", str(e)[:160])
            try:
                # 0.31.77: pools de cada token das listas (DexScreener grátis, 30 por consulta; ~3 consultas a cada 5 min)
                ex = getattr(self.hub, "explore", None)
                if ex is not None and not ex.error:
                    mints = list(dict.fromkeys(x["mint"] for c in ("graduating", "graduated") for x in (ex.lists.get(c) or [])[:45]))
                    if mints:
                        await self.svc._fetch_prices(mints, set_price=False)
            except Exception as e:
                log.warning("explorar (pools): %s", str(e)[:160])
            await asyncio.sleep(EVERY_S)

    async def explore_auto_once(self, now: float | None = None) -> int:
        """Entrada nova só com lista atual, conta admin ativa e cotação recente. Nunca usa cache do Explorar vencido."""
        from .explore import EVERY_S
        fixed_now = now
        now = time.time() if now is None else now
        ex = getattr(self.hub, "explore", None)
        if ex is None or ex.error or not ex.at or not 0 <= now - ex.at <= EVERY_S:
            return 0
        source_at = ex.at
        candidates = [e for e in self.engines() if getattr(e, "role", "user") == "admin"
                      and getattr(e.cfg, "pump_ex_auto_on", False)]
        if not candidates:
            return 0
        lists = {}
        wanted = set()
        for engine in candidates:
            snap = ex.snapshot(self.market.blacklist, self.market.creator_stats, engine.boost_info, now)
            lists[engine.user_id] = snap["lists"]
            for row in snap["lists"].get("graduating", []):
                if engine.explore_entry_reason(row) or engine.auto_guard(row["mint"], now):
                    continue
                wanted.add(row["mint"])
                token = self.market.tokens.setdefault(row["mint"], {})
                for key in ("symbol", "creator"):
                    if row.get(key) and not token.get(key):
                        token[key] = row[key]
        missing = [mint for mint in wanted if not (self.market.tokens.get(mint) or {}).get("price")
                   or now - float((self.market.tokens.get(mint) or {}).get("last_t") or 0) > 30]
        for offset in range(0, len(missing), 100):
            chunk = missing[offset:offset + 100]
            try:
                await self.svc._curve_prices(chunk, public_first=True)
                fallback = [mint for mint in chunk if not (self.market.tokens.get(mint) or {}).get("price")
                            or time.time() - float((self.market.tokens.get(mint) or {}).get("last_t") or 0) > 30]
                if fallback:
                    await self.svc._fetch_prices(fallback)
            except Exception as exc:
                log.warning("Preço da automática do Explorar indisponível: %s", type(exc).__name__)
        count = 0
        for engine in candidates:
            # Conferir depois dos awaits de preço: demissão de admin/bloqueio não pode liberar uma compra atrasada.
            try:
                profiles = await self.hub.db.select("profiles", {"user_id": engine.user_id}, columns="role,bloqueado")
                profile = profiles[0] if profiles else {}
                engine.role = profile.get("role") or "user"
                self.hub.check_active(engine.user_id, engine)
                if engine.role != "admin" or profile.get("bloqueado"):
                    engine.cfg.pump_ex_auto_on = False
                    continue
                stamp = time.time() if fixed_now is None else fixed_now
                if ex.error or ex.at != source_at or not 0 <= stamp - source_at <= EVERY_S:
                    continue
                fresh = [row for row in lists[engine.user_id].get("graduating", [])
                         if (tk := self.market.tokens.get(row["mint"]) or {}).get("price")
                         and 0 <= stamp - float(tk.get("last_t") or 0) <= 30]
                count += len(engine.explore_auto_check({"graduating": fresh}, stamp))
                # 0.31.88: log de análise do ciclo (salvo no banco quando muda)
                rec = engine.explore_cycle_note(source_at, len(lists[engine.user_id].get("graduating", [])), len(fresh), stamp)
                if rec is not None and hasattr(self.hub, "explore_cycle_save"):
                    await self.hub.explore_cycle_save(engine, rec)
            except Exception as exc:
                log.warning("Automática do Explorar não executada (%s…): %s", engine.user_id[:8], type(exc).__name__)
        return count

    async def fresh_once(self, limit: int = 4) -> int:
        """Carteiras novas (0.31.0) dos tokens que podem virar entrada: "Subindo agora" da Base e listas do Explorar sem
        veredito lixo. No máx. `limit` tokens por volta (cada um custa ~22 consultas no RPC público)."""
        want = []
        lab = getattr(self.hub, "lab", None)
        if lab is not None:
            want += [x["mint"] for x in lab.rising(time.time()) if (x.get("pred") or {}).get("verdict") not in ("lixo", "suspeito")]
        ex = getattr(self.hub, "explore", None)
        if ex is not None:
            for cat in ("graduating", "latest"):
                want += [x["mint"] for x in (ex.lists.get(cat) or [])[:20]]
        now, n = time.time(), 0
        for m in dict.fromkeys(want):
            if n >= limit:
                break
            if now - float(((self.market.tokens.get(m) or {}).get("fresh") or {}).get("t") or 0) < 180:
                continue
            await self.svc.fresh_check(m, now)
            n += 1
        return n

    async def fresh_loop(self) -> None:
        while True:
            try:
                await self.fresh_once()
            except Exception as e:
                log.warning("carteiras novas: %s", str(e)[:160])
            await asyncio.sleep(30)

    async def elite_info_once(self, limit: int = 3) -> int:
        """Saldo (SOL + USDC/USDT) e idade das carteiras dos maiores traders (0.31.3), poucas por volta (RPC grátis)."""
        el = getattr(self.hub, "elite", None)
        if el is None:
            return 0
        now, n = time.time(), 0
        for w in list(el.names):
            if n >= limit:
                break
            bal = self.market.wallet_usd.get(w)
            if (not bal or now - float(bal.get("t") or 0) > 1800) and self.market.sol_usd:
                v = await self.svc.wallet_value(w)
                if v:
                    self.market.wallet_usd[w] = v
                n += 1
            age = el.ages.get(w)
            if not age or now - float(age.get("t") or 0) > 12 * 3600:
                v = await self.svc.wallet_age(w)
                if v:
                    el.ages[w] = v
                n += 1
        return n

    async def boost_loop(self) -> None:
        while True:
            try:
                await self.boost_once()
            except Exception as e:
                log.warning("boost DexScreener: %s", str(e)[:160])
            try:
                await self.elite_info_once()
            except Exception as e:
                log.warning("saldo/idade dos maiores traders: %s", str(e)[:160])
            try:
                await self.wallet_facts_once()
            except Exception as e:
                log.warning("idade/saldo das carteiras em estudo: %s", str(e)[:160])
            await asyncio.sleep(60)

    async def wallet_facts_once(self, limit: int = 2) -> int:
        """0.32.9 (pedido do dono): idade, transações e saldo das carteiras em estudo e das que aparecem nas Decisões da IA.
        Poucas por volta (RPC grátis); idade/transações valem 12 h e o saldo 30 min."""
        now, n = time.time(), 0
        want = {w for e in self.engines() for w in (getattr(e, "study", None) or [])}
        want |= {w for w, t in (getattr(self.hub, "_facts_want", None) or {}).items() if now - t < 86400}
        for w in sorted(want, key=lambda x: (self.market.wallet_facts.get(x) or {}).get("t", 0)):
            if n >= limit:
                break
            fa = self.market.wallet_facts.get(w)
            if not fa or now - float(fa.get("t") or 0) > 12 * 3600:
                v = await self.svc.wallet_age(w)
                if v:
                    self.market.wallet_facts[w] = v
                n += 1
            bal = self.market.wallet_usd.get(w)
            if (not bal or now - float(bal.get("t") or 0) > 1800) and self.market.sol_usd:
                v = await self.svc.wallet_value(w)
                if v:
                    self.market.wallet_usd[w] = v
        return n

    def auto_once(self) -> int:
        """Compra automática da Base (0.27.0) de cada usuário que ligou: mesma lista "Subindo agora" da tela."""
        lab = getattr(self.hub, "lab", None)
        if lab is None:
            return 0
        engines = [e for e in self.engines() if getattr(e.cfg, "pump_auto_on", False)]
        if not engines:
            return 0
        rising, n = lab.rising(time.time()), 0
        for e in engines:
            try:
                n += len(e.auto_check(rising))
            except Exception as ex:
                log.warning("compra automática (%s…): %s", getattr(e, "user_id", "?")[:8], str(ex)[:160])
        return n

    ELITE = {"min_wallets": 2, "window_min": 10, "big_sol": 5.0, "top": 15}

    def elite_names(self) -> list[str]:
        return self.hub.elite.refresh_names([e.leaderboard for e in self.engines()], self.ELITE["top"])

    def elite_follow_sync(self) -> int:
        """Quem ligou "copiar os sugeridos" passa a seguir (copiar compra e venda) os maiores traders com 80%+ (0.31.4)."""
        rec = [r["wallet"] for r in self.hub.elite.recommended()]
        n = 0
        for e in self.engines():
            want = rec if getattr(e.cfg, "pump_el_copy80", True) and getattr(e, "role", "admin") == "admin" else []
            if list(getattr(e, "elite_follow", None) or []) != want:
                e.elite_follow = list(want)
                e.refresh_followed(force=True)
                n += 1
        return n

    def elite_event(self, w: str, ev: dict, t: float | None = None) -> dict | None:
        el = self.hub.elite
        t = time.time() if t is None else t
        s = el.on_trade(w, ev, t, self.ELITE)
        if ev.get("txType") == "sell":
            for e in self.engines():
                for msg in e.elite_sell(w, ev["mint"], el.label(w), t):
                    e._emit(msg)
        if s:
            for e in self.engines():
                try:
                    r = e.elite_auto(s, t)
                    if r and r.get("auto_id"):
                        e._emit(f"Maiores traders: compra automática em {s.get('symbol') or s['mint'][:6]} ({s['reason']})")
                except Exception as ex:
                    log.warning("maiores traders (%s…): %s", getattr(e, "user_id", "?")[:8], str(ex)[:160])
        return s

    async def lab_loop(self) -> None:
        while True:
            try:
                await self.lab_once()
                self.auto_once()
                self.elite_names()
                self.hub.elite.tick()
                self.elite_follow_sync()
                await self.explore_auto_once()
                for e in self.engines():                    # 0.32.21: barrados que subiram, só na fictícia
                    try:
                        e.barred_track()                    # 0.32.22: mede "entrar cedo" (+10/20/30/50%)
                        e.barred_auto()                     # o aviso sai do próprio manual_buy (compra automática)
                    except Exception as ex:
                        log.warning("barrados que subiram: %s", str(ex)[:160])
            except Exception as e:
                log.warning("base da pump.fun: %s", str(e)[:160])
            await asyncio.sleep(20)

    async def price_loop(self) -> None:
        last_ds = 0.0
        while True:
            try:
                ds = time.time() - last_ds >= float(self.hub.cfg.defaults.get("pump_ds_every_s", 10))
                if ds:
                    last_ds = time.time()
                await self.price_once(ds)
            except Exception as e:
                self.market.rpc_status["price_error"] = str(e)[:100]
            await asyncio.sleep(float(self.hub.cfg.defaults.get("pump_price_every_s", 3)))

    async def trail_once(self) -> float:
        """Posições com stop móvel ligado (de qualquer usuário): preço a cada ~1 s e stop na hora."""
        svc = self.svc
        ms, qty, dts = [], {}, []
        for e in self.engines():
            for p in e.positions():
                if p.get("trail_peak") is not None and not p.get("selling"):
                    ms.append(p["mint"])
                    qty[p["mint"]] = qty.get(p["mint"], 0.0) + float(p.get("tokens_left") or 0)
                    dts.append(float(getattr(e.cfg, "pump_trail_fast_s", 1.0) or 0))
        ms = list(dict.fromkeys(ms))
        dt = min([d for d in dts if d > 0], default=0)
        if ms and dt > 0:
            pump = [m for m in ms if svc.is_pump(m)]
            rest = await svc._curve_prices(pump, public_first=True) if pump else []
            rest += [m for m in ms if m not in pump]
            due = [m for m in rest if time.time() - (self.market.tokens.get(m) or {}).get("jq_t", 0) >= 3]
            for m in due:
                self.market.tokens.setdefault(m, {})["jq_t"] = time.time()
            if due:
                await svc._pumpswap_prices(due, public_first=True, qty=qty)
            self.check_stops(ms)
            self.market.rpc_status["trail_fast_at"] = now_iso()
        return dt

    async def trail_loop(self) -> None:
        while True:
            dt = 0.0
            try:
                dt = await self.trail_once()
            except Exception as e:
                self.market.rpc_status["trail_fast_error"] = str(e)[:100]
            await asyncio.sleep(max(0.3, dt) if dt > 0 else 2)

    # ------------------------------------------------------------------ por usuário a cada 2 s
    async def tick_once(self) -> None:
        if time.time() - self._sol_at > 30:
            self._sol_at = time.time()
            try:
                px = await self.market.jup.sol_price_usd() if self.market.jup else None
                if px:
                    self.market.sol_usd = px
            except Exception:
                pass
        for e in self.engines():
            try:
                await e._process_pending()
                e._purge_quote_positions()
                e.refresh_followed()
                for msg in e.check_timeouts():
                    e._emit(msg)
            except Exception as ex:
                log.warning("tick (%s…): %s", getattr(e, "user_id", "?")[:8], str(ex)[:160])
        if int(time.time()) % 60 < 2:
            self.prune()

    def prune(self, t: float | None = None) -> None:
        """Libera memória: carteiras sem atividade (que ninguém copia) e tokens velhos (que ninguém segura)."""
        t = t or time.time()
        win = float(self.hub.cfg.defaults.get("pump_rank_hours", 24)) * 3600
        fol = self.union_followed()
        m = self.market
        for w in [w for w, st in m.wallets.items() if t - st.get("last_t", 0) > win and w not in fol]:
            del m.wallets[w]
        for w in [w for w, x in m.creators.items() if t - x > win]:
            del m.creators[w]
        held = set(self.held()["qty"]) | set(self.held()["trader"]) | self.ghost_mints()
        for k in [k for k, tk in m.tokens.items() if t - tk.get("last_t", 0) > 6 * 3600 and k not in held]:
            del m.tokens[k]

    async def tick_loop(self) -> None:
        while True:
            try:
                await self.tick_once()
            except Exception as e:
                log.warning("tick: %s", str(e)[:160])
            await asyncio.sleep(2)

    def _fill_slot(self, w: str) -> None:
        """Um trader do top acabou de negociar (ficou online). Se algum usuário tem vaga sobrando na cópia, refaz a
        lista dele já, sem esperar os 10 min."""
        for e in self.engines():
            if w in e.followed or not e._c("pump_only_online", True):
                continue
            if len(e.followed) < int(e._c("pump_top_n", 10)) and any(r.get("wallet") == w for r in e.leaderboard):
                e._rank_at = 0

    # ------------------------------------------------------------------ leaderboard e saldo dos traders
    @staticmethod
    def lb_group(e: PumpFun) -> tuple:
        c = e.cfg
        return (int(c.pump_lb_days), int(c.pump_lb_min_trades), float(c.pump_min_winrate), str(c.pump_lb_platform))

    async def lb_once(self, force: bool = False) -> None:
        every = float(self.hub.cfg.defaults.get("pump_lb_every_s", 1800))
        groups: dict = {}
        for e in self.engines():
            groups.setdefault(self.lb_group(e), []).append(e)
        for key, es in groups.items():
            hit = self.lb_cache.get(key)
            fresh = hit and time.time() - hit["at"] < every and not force
            if not fresh:
                src = next((e for e in es if e.lb_key_own()), None) or next((e for e in es if e.lb_key()), None)
                if src is None:
                    for e in es:
                        e.lb_status.update(error="sem chave da Solana Tracker")
                    continue
                await src.refresh_leaderboard(force=True)
                hit = {"at": time.time(), "rows": [dict(r) for r in src.leaderboard], "status": dict(src.lb_status)}
                if src.lb_status.get("error") and not src.leaderboard:
                    hit["rows"] = (self.lb_cache.get(key) or {}).get("rows", [])
                self.lb_cache[key] = hit
            for e in es:
                if not e.lb_key():
                    e.lb_status.update(error="sem chave da Solana Tracker")
                    continue
                if e.leaderboard and fresh and e.lb_status.get("at") == hit["status"].get("at"):
                    continue
                e.leaderboard = [e._lb_judge(dict(r)) for r in hit["rows"]]
                e.lb_status.update(hit["status"])
                e.refresh_followed(force=True)

    async def wallet_values_once(self) -> None:
        es = [e for e in self.engines() if float(e.cfg.pump_min_wallet_usd or 0) > 0]
        if not es or not self.market.sol_usd:
            return
        cand = []
        for e in es:
            cand += [r["wallet"] for r in e.leaderboard] + list(e.manual)
        every = float(self.hub.cfg.defaults.get("pump_wallet_check_s", 1800))
        changed = False
        for w in dict.fromkeys(cand):
            old = self.market.wallet_usd.get(w)
            if old and time.time() - old["t"] < every:
                continue
            v = await self.svc.wallet_value(w)
            if v:
                self.market.wallet_usd[w] = v
                changed = True
            await asyncio.sleep(0.2)
        if changed:
            for e in es:
                e.refresh_followed(force=True)

    async def lb_loop(self) -> None:
        while True:
            try:
                await self.lb_once()
                await self.wallet_values_once()
            except Exception as e:
                log.warning("leaderboard: %s", str(e)[:160])
            await asyncio.sleep(30)

    # ------------------------------------------------------------------ início
    def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._tasks = [loop.create_task(c) for c in (self.rpc_run(), self.pumpportal_run(), self.price_loop(),
                                                     self.trail_loop(), self.tick_loop(), self.lb_loop(),
                                                     self.lab_loop(), self.boost_loop(), self.explore_loop(),
                                                     self.fresh_loop())]
        self._tasks += [loop.create_task(self.tx_worker()) for _ in range(4)]
        self._tasks += [loop.create_task(self.tx_worker(hi=True)) for _ in range(4)]     # 0.32.4: só as copiadas

    def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
