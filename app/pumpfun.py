"""PUMP.FUN — copia os 10 melhores traders da pump.fun (carteira FICTÍCIA em SOL; execução real preparada, desligada).

Trazido da aba PUMP.FUN do hermes-jev-trader. A lógica de cópia é a MESMA; o que mudou para o modo multiusuário:
- `PumpMarket` guarda os dados PÚBLICOS (tokens, preços, carteiras vistas, atividade, saldo dos traders) — um só
  para todos os usuários (o monitor compartilhado em app/hub.py alimenta ele).
- `PumpFun` é o motor de cópia de UM usuário: configuração própria (`cfg`), dados próprios (`store`: posições,
  histórico, listas, feed) e chaves próprias (`keys`).

Dados ao vivo: PumpPortal (WebSocket público, sem chave, UMA conexão só):
  {"method": "subscribeNewToken"}                         → cada token novo criado na pump.fun
  {"method": "subscribeTokenTrade",   "keys": [mints]}     → compras/vendas desses tokens (até 100 por mensagem)
  {"method": "subscribeAccountTrade", "keys": [carteiras]} → compras/vendas dessas carteiras (os traders copiados)
  evento de trade: mint, traderPublicKey, txType (buy/sell/create), solAmount, tokenAmount, newTokenBalance,
                   vSolInBondingCurve, vTokensInBondingCurve, marketCapSol, pool, signature

Ranking próprio dos melhores traders (não depende de site de terceiros): o bot acompanha os trades dos tokens
novos e calcula, por carteira, o lucro REALIZADO em SOL nas últimas 24 h (preço médio de compra × venda), a taxa de
acerto por token fechado, quantos tokens fechou e o tempo médio que segura cada token. Ficam de fora: quem criou
tokens (dev), robôs sniper (seguram poucos segundos — impossível copiar a tempo), robôs de alta frequência e
carteiras banidas por você. Os 10 primeiros por lucro (mais as carteiras que você adicionar na mão) são copiados.

Cópia (simulada): quando um trader copiado COMPRA, o bot "compra" um valor fixo em SOL no preço logo depois da
compra dele + slippage extra (você entra depois dele), pagando a taxa da pump.fun e a priority fee. Quando ele
VENDE, o bot vende a mesma proporção. Proteções: stop de perda, alvo opcional, tempo máximo, limite de posições.
"""
from __future__ import annotations

import asyncio
import base64
import copy
import json
import logging
import math
import statistics
import re
import time
from collections import deque
from datetime import datetime, timezone

import httpx

from . import apiusage, stkeys, stopganho, txguard
from .settings import USER_KEYS

log = logging.getLogger("pumpfun")

WS_URL = "wss://pumpportal.fun/api/data"
TRADE_LOCAL_URL = "https://pumpportal.fun/api/trade-local"
SELL_FEE_CAP_SOL = 0.02          # teto de SOL para terceiros numa venda (taxa da PumpPortal)
SELL_PENDING_HOLD_S = 300        # venda sem confirmação: não reenvia por 5 min (o blockhash vence em ~1-2 min)
SOL_MINT = "So11111111111111111111111111111111111111112"
# Monitor GRÁTIS dos traders copiados: WebSocket da própria Solana (logsSubscribe por carteira) + getTransaction.
# (A PumpPortal passou a cobrar 0,01 SOL/10 mil eventos para trades de contas/tokens; só tokens novos são grátis.)
SOL_WS = "wss://api.mainnet-beta.solana.com"
SOL_HTTP = "https://api.mainnet-beta.solana.com"
DS_TOKENS = "https://api.dexscreener.com/tokens/v1/solana/"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
# 0.32.4 (pedido do dono, 28/10): as 20 carteiras do https://pump.fun/leaderboard (semana) vistas na tela nesse dia.
# Só são copiadas com "Copiar igual" ligado; o dono cola outras na tela quando quiser.
EQ_SEED = ("4ugDhHJ8XDXAeABmrNmGffFaLbJb9BkPyiFGVSV9ocwo", "4UrFSCrGxgoCtCUBAEZq7ZmPK3Pczkxx7PwYnkBMi1KR",
           "Bmi9zf27MNN5pjCtyv2Y15TDQoYgcbcmPTxvEoQ6UwWs", "4XVFYAg8fHinxnNTjicpq2Xti5JGz5oJx3ZNbCvR9eTB",
           "HDixbrzwwLXczhDBk1JVrurPQsuLE8FUKnW2pucSXN3o", "2p8oSST3XGoAs7YCgn3LkRPenVcq3vZNkepcLiTEK1D5",
           "HsQnUgdVVUJNTTEe5mzpQFFi55oXq4UwcjByEFb3Rd52", "HJvA1AuetuTPYdeEqntxroXWjw8iTBwx1Ly5w6UsJxXp",
           "BQ4KBzzXXk6ZMxVQb4mePuUbJfe85MerzYj53eatzUWd", "834ZWiqnaK9Byucxq2yWRK59qwjtUvP4pjYK2Zj1SZjS",
           "8tU3fy9cUEsnpnFZ86nvPmD7hkppsVnQbjHyLV2YC7DW", "2M2vLX34LXMg24dMEnjWHvRXS1tshpEDRWzmXgV8ENNZ",
           "HRQfqHxmj126YSJKrEtYZuWXJmkUwWFXJ4DACpDHyCGG", "FniZYxox48b6FPfJC9XZVAdVT3fQ6dUiXzQ5ZBjUCyz6",
           "2xHVdUu6NZKi9hVeBmmrj9jwAYSPCaoHSE2njCGH6CeE", "3ypWuTN9c5gWir4uCYC5hWem4AkPuDNhTQacx43jS74y",
           "AusMtCwzrPnPoJUSHYUH9iogVwpWh2ESHC6xWU75tBDo", "64w4qRu9VGio7U1Asc6B68QDpS8L1McmSn2yyExC6Fii",
           "Hzvs4kQ3pSeVpPqFgiQLfgKS4tpTDyk3GmKT1k8BQPBm", "EFdEVbaVJ7HXguXvFsX4yW2FBL8bWy6fXn2GDwuK1i1D")
QUOTES = {SOL_MINT, USDC, USDT}                    # moedas de pagamento: nunca são "o token" do trade
NO_COPY = {                                          # staking de SOL (não é trade de token)
    "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So", "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",
    "bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1", "jupSoLaHXQiZZTSfEWMTRRgpnyFm8f6sZdosWBjx93v",
    "7dHbWXmci3dT8UFYWYZweBLXgycu7Y3iL6trKn1Y7ARj", "5oVNBeEEQvYi1cX3ir8Dx5n1P7pdxydbGF2X4TxVusJm"}
PUMP_DEX = {"pumpfun", "pumpswap", "pump.fun", "pumpfun-amm"}
PUMP_PROGRAMS = ("6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",   # pump.fun (curva)
                 "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA")   # PumpSwap (depois de migrar)
# Leaderboard dos melhores traders do app da pump.fun (o mesmo de solanatracker.io/leaderboard/pumpfun).
# Precisa de chave GRÁTIS da Solana Tracker (plano free: 10 mil requisições/mês; o bot usa ~1,5 mil).
LB_URL = "https://data.solanatracker.io/v2/pnl/leaderboard/top"
ST_PNL = "https://data.solanatracker.io/v2/pnl/wallets/"   # + {carteira}/positions (carteiras em estudo, 0.14.0)
# Nota de risco do token (mint/freeze authority, bundlers, insiders, concentração…) — mesma chave do ranking.
TOKEN_URL = "https://data.solanatracker.io/tokens/"
STATS_URL = "https://data.solanatracker.io/stats/"   # por janela: compradores/vendedores únicos e volume (0.13.0)


AUTO_ORIGINS = ("explorar", "base", "elite", "calls")   # origens das compras automáticas com proteções e registro (0.31.2: elite)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def short(addr: str) -> str:
    return (addr[:4] + "…" + addr[-4:]) if addr and len(addr) > 10 else (addr or "")


def _ts(x) -> float | None:
    """ISO ou número → segundos (None se não der)."""
    if isinstance(x, (int, float)):
        return float(x)
    try:
        d = datetime.fromisoformat(str(x).replace("Z", "+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()
    except (TypeError, ValueError):
        return None


class PumpMarket:
    """Dados PÚBLICOS da rede, compartilhados por todos os usuários (um conjunto só no servidor)."""

    def __init__(self, jup=None):
        self.tokens: dict[str, dict] = {}          # mint -> {symbol, name, creator, price, mcap_sol, created_t, last_t}
        self.wallets: dict[str, dict] = {}         # carteira -> {"pos": {mint: {...}}, "closed": deque, "trades": deque}
        self.creators: dict[str, float] = {}       # carteira que criou token -> quando
        self.activity: dict = {}                   # carteira -> atividade na rede (online/offline)
        self.wallet_usd: dict = {}                 # carteira do trader -> {"usd", "sol", "stable", "t"}
        self.wallet_facts: dict = {}               # 0.32.9: carteira -> idade/transações (wallet_age), lido aos poucos
        self.px_hist: dict = {}                    # 0.32.33: token -> [(t, preço)] a cada ~20 s, 40 min (aprendizado das posições)
        self.blacklist: dict[str, dict] = {}       # 0.20.0: lista negra compartilhada (endereço -> tipo, motivo)
        self.bl_new: list[str] = []                # endereços novos ainda não gravados no banco
        self.creator_stats: dict[str, dict] = {}   # 0.21.0: criador -> tokens, x2, rugs (base da pump.fun)
        self.boosts: dict[str, dict] = {}          # 0.24.0: mint -> boost/pedidos pagos na DexScreener
        self.sol_usd = 0.0
        self.jup = jup                             # JupiterQuoter (cotações compartilhadas)
        self.status = {"ws": None, "connected_at": None, "error": None, "events": 0, "last_event": None,
                       "new_tokens": 0, "trades": 0}
        self.rpc_status = {"ws": None, "connected_at": None, "error": None, "subs": 0, "notifs": 0, "parsed": 0,
                           "last_event": None, "tx_errors": 0, "price_at": None, "price_error": None}


class PumpFun:
    def __init__(self, cfg, store=None, http=None, wallet=None, market: PumpMarket | None = None):
        from .store import MemStore
        self.cfg, self.http, self.sol_wallet = cfg, http, wallet
        self.store = store if store is not None else MemStore()
        self.market = market if market is not None else PumpMarket()
        self.sub_tokens: deque = deque()           # mints com trades assinados (os mais novos)
        self.followed: list[str] = []              # carteiras copiadas agora
        self.top_active: list[str] = []            # 0.32.43: os top traders ATIVOS copiados agora (vagas próprias)
        self._followed_sent: set[str] = set()
        self.live: deque = deque(maxlen=400)       # monitor: entradas/saídas dos traders copiados
        self.events: deque = deque(maxlen=300)     # mensagens para o painel (notificações/sons)
        self._ev_id = 0
        self.ranking_cache: list[dict] = []
        self._rank_at = 0.0
        self._out: list[dict] = []                 # mensagens para enviar no WebSocket
        self._want_tokens: list[str] = []
        self._drop_tokens: list[str] = []
        self._rpc_subs: dict = {}                  # id da assinatura -> carteira
        self._rpc_want: set = set()
        self._tx_q: asyncio.Queue | None = None
        self._seen_sigs: deque = deque(maxlen=3000)
        self.price_fn = None                       # função que devolve o preço do SOL em US$
        self.real = None                           # PumpReal (execução real — desligada)
        self.on_event = None
        self._real_q: list = []
        self._rq: asyncio.Queue | None = None        # fila de execução REAL (compras/vendas na blockchain)
        # 0.31.61 (pedido do dono): "copiar os trades de outro usuário" — quem esta conta segue (user_id) e o aviso para
        # o hub quando ESTA conta abre/fecha uma posição fictícia (o hub repassa para quem segue esta conta)
        self.follow_user: str = ""
        self.copy_equal: list[str] = list(EQ_SEED)      # 0.32.4: "Copiar igual" (salvo em _copy_equal; ver hub._load)
        self.eq_mode: dict[str, str] = {}                # 0.32.65: por carteira "sim" | "both" | "off" (salvo em _eq_mode)
        self.study_copy: list[str] = []                  # 0.32.11: aprovadas pelo estudo automático, copiadas só na fictícia
        self.sim_only_list: list[str] = []               # 0.32.17: copiadas pelo botão Copiar do estudo (só fictícia, teste)
        self.ia_added: list[str] = []                    # 0.32.17: as que a IA pôs na lista manual (só essas ela tira)
        self.real_ok_list: list[str] = []                # 0.32.38: copiadas do estudo que o dono liberou também na REAL
        self.brain_freeze: dict | None = None          # 0.31.85: cérebro congelado numa evolução (Base geral → Voltar)
        self.leader_hook = None
        # 0.31.63 (pedido do dono): aprendizado geral — o hub entrega aqui os trades automáticos de TODAS as contas
        self.learn_pool = None
        self.bm_growth_hook = None                    # 0.32.380: crescimento das compras de um token do BOOST (o hub liga)
        self.bm_view_hook = None                      # 0.32.427: dados do BOOST para o card da posição (o hub liga)
        self.top_hook = None                          # 0.32.124: compra barrada do Top traders vira acompanhamento
        self.shadow_hook = None                       # 0.31.72: token "chance alta" barrado vira entrada sombra (hub)
        self._real_buying: _Buying = _Buying()
        self.bm_real_note: dict[str, dict] = {}           # 0.32.398: BOOST — o que aconteceu com a compra REAL de cada token
        self.bm_sim_after: dict[str, dict] = {}           # 0.32.400: BOOST — fictícia que entra quando a compra REAL terminar
        self._pending: dict = {}                     # (trader, token) -> compra aguardando os X s de espera
        self.keys = None                           # KeyRing do usuário (chave da Solana Tracker etc.)
        self.leaderboard: list[dict] = []          # top traders da pump.fun (Solana Tracker), julgados p/ este usuário
        self.lb_status = {"at": None, "error": None, "count": 0, "days": None}
        self._lb_at = 0.0
        from .ghosts import Ghosts
        self.ghosts = Ghosts(self)                   # estratégias fantasma (0.18.0): mesmas entradas, saídas diferentes
        from .ghosts import AUTO_BASE, AUTO_VARIANTS
        # 0.31.21: fantasmas das compras automáticas do Explorar (mesma compra, saídas diferentes)
        self.ghosts_auto = Ghosts(self, AUTO_VARIANTS, AUTO_BASE, mine=lambda t: t.get("origem") == "explorar")
        # 0.32.332 (pedido do dono, 13/11/2026): stop de ganho autônomo. O hub liga sg_pool (decisões com os trades de TODAS as
        # contas); a sombra segue o preço depois que ele vende, para o robô saber o que as regras normais teriam feito.
        self.sg_pool = None
        self.sg_sombra = stopganho.Sombras(salvar=self._sg_salvar)
        try:
            self.sg_sombra.restaurar(self.store.trades(5000), time.time())
        except Exception:
            pass
        self._halt_until = 0.0                       # pausa geral por sequência de perdas (0.19.0; só memória)
        self.tg = None                               # avisos no Telegram (0.20.0; ligado pelo hub)
        self.auto_rows: dict[str, dict] = {}           # operações próprias; o hub carrega antes de liberar entradas
        self._auto_dirty: set[str] = set()
        self._auto_pending: dict[str, float] = {}      # reservas automáticas na fila real, ainda sem posição
        self.auto_ready = True                        # motores avulsos dos testes; o hub bloqueia até carregar
        self.auto_error = None

    # ------------------------------------------------------------------ dados públicos (compartilhados)
    @property
    def tokens(self) -> dict:
        return self.market.tokens

    @property
    def wallets(self) -> dict:
        return self.market.wallets

    @property
    def creators(self) -> dict:
        return self.market.creators

    @property
    def activity(self) -> dict:
        return self.market.activity

    @activity.setter
    def activity(self, v: dict) -> None:
        self.market.activity = v

    @property
    def wallet_usd(self) -> dict:
        return self.market.wallet_usd

    @wallet_usd.setter
    def wallet_usd(self, v: dict) -> None:
        self.market.wallet_usd = v

    @property
    def sol_usd(self) -> float:
        return self.market.sol_usd

    @sol_usd.setter
    def sol_usd(self, v: float) -> None:
        self.market.sol_usd = v

    @property
    def status(self) -> dict:
        return self.market.status

    @property
    def rpc_status(self) -> dict:
        return self.market.rpc_status

    @property
    def feed(self) -> deque:
        """O que os traders copiados fizeram e o que o bot fez (últimos 500, guardado no banco)."""
        return self.store._feed

    @feed.setter
    def feed(self, v) -> None:
        items = list(v)
        self.store._feed.clear()
        self.store._feed.extend(items)

    # ------------------------------------------------------------------ config / listas
    def _c(self, k: str, d):
        return getattr(self.cfg, k, d)

    def _meta(self, key: str, default):
        return self.store.meta_get(key, None) or default

    def _meta_set(self, key: str, val) -> None:
        self.store.meta_set(key, val)

    @property
    def manual(self) -> list[str]:
        return list(self._meta("pump_manual", []))

    @property
    def banned(self) -> list[str]:
        return list(self._meta("pump_banned", []))

    @staticmethod
    def valid_addr(a: str) -> bool:
        import re
        return bool(re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", (a or "").strip()))

    def add_manual(self, wallet: str) -> dict:
        w = (wallet or "").strip()
        if not self.valid_addr(w):
            return {"error": "endereço de carteira inválido"}
        m = [x for x in self.manual if x != w] + [w]
        self._meta_set("pump_manual", m)
        self._meta_set("pump_banned", [x for x in self.banned if x != w])
        self.refresh_followed(force=True)
        return {"ok": True, "manual": m}

    def remove_manual(self, wallet: str) -> dict:
        self._meta_set("pump_manual", [x for x in self.manual if x != wallet])
        self.refresh_followed(force=True)
        return {"ok": True}

    def ban(self, wallet: str) -> dict:
        b = [x for x in self.banned if x != wallet] + [wallet]
        self._meta_set("pump_banned", b)
        self._meta_set("pump_manual", [x for x in self.manual if x != wallet])
        self.refresh_followed(force=True)
        return {"ok": True}

    # ------------------------------------------------------------------ pausar trader
    def paused(self) -> dict:
        """{carteira: {"until": ts|None (manual), "reason", "at"}} — pausas vencidas são limpas."""
        d = dict(self._meta("pump_paused", {}) or {})
        now = time.time()
        live = {w: v for w, v in d.items() if not v.get("until") or v["until"] > now}
        if len(live) != len(d):
            self._meta_set("pump_paused", live)
            for w in set(d) - set(live):
                self._emit(f"Pump.fun: {short(w)} voltou a ser copiado (pausa de {d[w].get('hours', 24):.0f} h acabou)")
        return live

    def is_paused(self, w: str) -> bool:
        return w in self.paused()

    def pause(self, wallet: str, hours: float | None = None, reason: str = "pausado por você") -> dict:
        d = self.paused()
        d[wallet] = {"until": (time.time() + hours * 3600) if hours else None, "hours": hours, "reason": reason,
                     "at": now_iso()}
        self._meta_set("pump_paused", d)
        self.refresh_followed(force=True)
        return {"ok": True}

    def resume(self, wallet: str) -> dict:
        d = self.paused()
        d.pop(wallet, None)
        self._meta_set("pump_paused", d)
        self.refresh_followed(force=True)
        return {"ok": True}

    def _after_close(self, tr: dict) -> None:
        """Regra automática: o trader copiado que fizer a posição bater o STOP DE PERDA N vezes em 24 h fica
        pausado por X h (padrão: 2 stops → 24 h)."""
        own_auto = tr.get("auto") is True and tr.get("origem") in AUTO_ORIGINS
        if not own_auto:
            self._streak_check(tr)
        if str(tr.get("reason") or "").startswith("dev vendeu") and (tr.get("pnl_sol") or 0) < 0:
            cr = (self.tokens.get(tr.get("mint")) or {}).get("creator")
            if cr:
                self.blacklist_add(cr, "dev", f"vendeu {tr.get('symbol') or 'token'} e a cópia fechou no prejuízo")
        if own_auto:
            return                                  # pausa das automáticas não pausa traders nem cópias
        if not str(tr.get("reason") or "").startswith("stop de perda"):
            return
        n = int(self._c("pump_autopause_stops", 2))
        hrs = float(self._c("pump_autopause_hours", 24))
        if not n or not hrs:
            return
        w = tr["wallet"]
        if self.is_paused(w):
            return
        day = time.time() - 86400
        cnt = 0
        for t in self.trades(500):
            if t.get("auto") is True and t.get("origem") in AUTO_ORIGINS:
                continue
            if t.get("wallet") != w or not str(t.get("reason") or "").startswith("stop de perda"):
                continue
            try:
                ts = datetime.fromisoformat(t["closed_at"]).timestamp()
            except Exception:
                continue
            if ts >= day:
                cnt += 1
        if cnt >= n:
            self.pause(w, hrs, f"{cnt} stops de perda em 24 h")
            self._emit(f"Pump.fun: {short(w)} PAUSADO por {hrs:.0f} h — {cnt} stops de perda em 24 h")

    def unban(self, wallet: str) -> dict:
        self._meta_set("pump_banned", [x for x in self.banned if x != wallet])
        self.refresh_followed(force=True)
        return {"ok": True}

    # ------------------------------------------------------------------ trava de preço
    # 0.32.207 (ZEC, 04/11: preço de 133.500 SOL por ZEC, ~10.000× o real de ~13,7; a cópia em "segurar até ficar positivo"
    # vendeu nele e marcou +1.017 SOL falsos na FICTÍCIA). Um preço novo que salta 20× ou mais (para cima ou para baixo)
    # em relação ao anterior fica ESPERANDO: só vale quando outra fonte (ex.: DexScreener depois de um trade visto) ou
    # 3 leituras seguidas em 30 s+ confirmarem um valor parecido. Até lá o preço anterior continua e nenhuma saída usa o
    # salto. A curva da pump.fun (lida direto da blockchain) não passa por aqui.
    PX_JUMP_X = 20.0
    PX_HOLD_S = 180.0

    def _px_ok(self, mint: str, tk: dict, px: float, t: float, src: str) -> bool:
        old = float(tk.get("price") or 0)
        if not old or not px or px <= 0 or t - float(tk.get("last_t") or 0) > 1800:
            tk.pop("px_hold", None)
            return True
        r = px / old
        if 1 / self.PX_JUMP_X < r < self.PX_JUMP_X:
            tk.pop("px_hold", None)
            return True
        h = tk.get("px_hold")
        if h and t - h["t0"] <= self.PX_HOLD_S and 1 / 3 <= px / h["px"] <= 3:
            h["n"] += 1
            h["srcs"] = sorted(set(h["srcs"]) | {src})
            if len(h["srcs"]) >= 2 or (h["n"] >= 3 and t - h["t0"] >= 30):
                tk.pop("px_hold", None)
                log.info("preço de %s confirmado depois de salto de %.0f×: %s (%s)", mint[:8], max(r, 1 / r), px, " + ".join(h["srcs"]))
                return True
            return False
        tk["px_hold"] = {"px": px, "t0": t, "n": 1, "srcs": [src], "old": old}
        tk["px_jumps"] = int(tk.get("px_jumps") or 0) + 1
        log.warning("preço de %s recusado: %s → %s (%.0f×, %s); espera outra leitura confirmar", mint[:8], old, px, max(r, 1 / r), src)
        return False

    PX_MKT_S = 600.0        # preço de mercado vale para a conferência por 10 min
    PX_MKT_BAND = 1.35      # o preço lido do trade pode ficar até 35% acima/abaixo do mercado

    def px_mismatch(self, mint: str, px: float | None, t: float, ev: dict | None = None) -> str | None:
        """0.32.331 (estudo de 13/11: PUMP, WBTC, SPCX, AMD… entravam na fictícia a 1/3 do preço de mercado e fechavam em
        "+190%" em segundos; esses ganhos falsos liberavam o trader para a REAL): o preço de um trade fora da curva é o SOL que
        saiu da carteira ÷ tokens que entraram, e sai errado quando o trader paga parte com outra moeda ou com alavancagem.
        Confere com o preço de mercado (DexScreener) dos últimos 10 min. Devolve o motivo, ou None se bate (ou não há como conferir).
        Trade da curva (vSol/vTokens da própria pump.fun) não precisa: o preço vem das reservas."""
        if not px or (ev and float(ev.get("vSolInBondingCurve") or 0) > 0):
            return None
        tk = self.tokens.get(mint) or {}
        mk, mt = float(tk.get("mkt_px") or 0), float(tk.get("mkt_t") or 0)
        if not mk or t - mt > self.PX_MKT_S:
            return None
        r = px / mk
        if 1 / self.PX_MKT_BAND <= r <= self.PX_MKT_BAND:
            return None
        return (f"o preço lido do trade ({px:.3g} SOL) não bate com o do mercado ({mk:.3g} SOL): o trader pagou parte com outra "
                "moeda ou a leitura veio errada")

    def px_check_block(self, mint: str, ev: dict, t: float) -> str | None:
        """Filtro da cópia (opção `pump_px_check_on`): preço do trade que não bate com o mercado, ou token de fora da pump.fun
        sem preço de mercado para conferir."""
        if not getattr(self.cfg, "pump_px_check_on", True):
            return None
        why = self.px_mismatch(mint, self.price_of(ev), t, ev)
        if why:
            return why
        tk = self.tokens.get(mint) or {}
        if (getattr(self.cfg, "pump_px_need_mkt", True) and ev.get("source") == "rpc" and not self.is_pump(mint)
                and not (tk.get("mkt_px") and t - float(tk.get("mkt_t") or 0) <= self.PX_MKT_S)):
            return "token de fora da pump.fun sem preço de mercado para conferir o preço do trade"
        return None

    def runup_block(self, mint: str, px: float | None, t: float) -> str | None:
        """0.32.331 (estudo de 13/11, 427 cópias com histórico de preço): cópia em token que já tinha subido 100% ou mais nos
        15 min anteriores deu em média −24% (44 cópias). Opção `pump_runup_max_pct` (0 = desliga). Sem histórico, não bloqueia."""
        mx = float(self._c("pump_runup_max_pct", 0) or 0)
        if mx <= 0 or not px:
            return None
        from .poslearn import entry_context
        ctx = entry_context(list(self.market.px_hist.get(mint) or []), t, px)
        up = (ctx or {}).get("subiu_antes_pct")
        if up is not None and up >= mx:
            return f"o token já subiu {up:.0f}% nos 15 min antes da compra do trader (máximo {mx:.0f}%): entrada no topo"
        return None

    def _ev_px(self, ev: dict, tk: dict) -> float | None:
        """Preço do trade, a não ser que a trava acabou de recusá-lo (aí a cópia usa o último preço confiável)."""
        px, h = self.price_of(ev), tk.get("px_hold")
        if px and h and tk.get("price") and abs(px / h["px"] - 1) < 1e-6:
            return None
        return px

    # ------------------------------------------------------------------ eventos
    @staticmethod
    def price_of(ev: dict) -> float | None:
        """Preço em SOL por token depois do trade (curva: vSol ÷ vTokens); senão SOL ÷ tokens do trade."""
        try:
            vs, vt = float(ev.get("vSolInBondingCurve") or 0), float(ev.get("vTokensInBondingCurve") or 0)
            if vs > 0 and vt > 0:
                return vs / vt
            sa, ta = float(ev.get("solAmount") or 0), float(ev.get("tokenAmount") or 0)
            return sa / ta if sa > 0 and ta > 0 else None
        except (TypeError, ValueError):
            return None

    def on_message(self, ev: dict, t: float | None = None) -> list[str]:
        """Processa 1 mensagem do WebSocket. Devolve mensagens para a aba Eventos (cópias).
        = parte pública (ingest, uma vez por evento) + reação DESTE usuário (react)."""
        t = t or time.time()
        info = self.ingest(ev, t)
        return self.react(ev, t, info) if info else []

    def ingest(self, ev: dict, t: float) -> dict | None:
        """Parte PÚBLICA do evento (preço/mcap do token, carteiras vistas, devs). No modo multiusuário roda uma vez
        só, no monitor compartilhado. Devolve o que cada usuário precisa para reagir (ou None)."""
        if not isinstance(ev, dict) or "txType" not in ev:
            return None
        self.status["events"] += 1
        self.status["last_event"] = t
        mint, kind, who = ev.get("mint"), ev.get("txType"), ev.get("traderPublicKey")
        if not mint:
            return None
        px = self.price_of(ev)
        tk = self.tokens.setdefault(mint, {"created_t": t})
        if px and self.px_mismatch(mint, px, t, ev) is None and self._px_ok(mint, tk, px, t, "trade " + str(ev.get("source") or "pumpportal")):
            tk["price"] = px
        if ev.get("marketCapSol") is not None:
            tk["mcap_sol"] = float(ev["marketCapSol"])
        tk["last_t"] = t
        for k in ("symbol", "name"):
            if ev.get(k):
                tk[k] = ev[k]
        if ev.get("pool"):
            tk["pool"] = ev["pool"]
        if kind == "create":
            self.status["new_tokens"] += 1
            tk["creator"] = who
            if who:
                self.creators[who] = t
            self._track_token(mint)
            if who and float(ev.get("solAmount") or 0) > 0:   # compra inicial do dev conta como compra dele
                self._wallet_trade(who, mint, "buy", float(ev.get("solAmount") or 0),
                                   float(ev.get("initialBuy") or ev.get("tokenAmount") or 0), t)
                dp = ((self.wallets.get(who) or {}).get("pos") or {}).get(mint)
                if dp is not None:
                    dp["dev"] = True                     # 0.32.49: é a compra do criador no lançamento, não uma compra copiável
            return None
        if kind not in ("buy", "sell"):
            return None
        self.status["trades"] += 1
        sol, tok = float(ev.get("solAmount") or 0), float(ev.get("tokenAmount") or 0)
        wp = ((self.wallets.get(who) or {}).get("pos") or {}).get(mint) if who else None
        before = wp.get("tok", 0.0) if wp else 0.0
        avg_before = (wp["cost"] / wp["tok"]) if wp and wp.get("tok") else None
        if who:
            self._wallet_trade(who, mint, kind, sol, tok, t)
        if kind == "sell" and who and who == tk.get("creator") and tok > 0:
            tk["dev_sold_t"] = t                           # 0.19.0: saída quando o criador vende
        return {"mint": mint, "kind": kind, "who": who, "sol": sol, "tok": tok, "before": before,
                "avg_before": avg_before}

    def react(self, ev: dict, t: float, info: dict) -> list[str]:
        """Parte DESTE usuário: monitor ao vivo + cópia (se segue o trader) + stops das posições no token."""
        mint, kind, who, sol, tok = info["mint"], info["kind"], info["who"], info["sol"], info["tok"]
        before, avg_before = info["before"], info["avg_before"]
        msgs = []
        if kind == "sell" and who and (who in self.followed or who in (getattr(self, "study", None) or [])):
            for p in self.positions():
                if p["mint"] == mint and p["wallet"] != who and who not in p.setdefault("kol_sellers", []):
                    p["kol_sellers"].append(who)
                    self._save_pos(p)
        if who in self.followed:
            self._live(who, mint, kind, sol, tok, ev, before, avg_before, t)
            msgs += self._copy(who, mint, kind, sol, tok, ev, before, t)
        msgs += self._check_stops(mint, t)
        return msgs

    def _live(self, who, mint, kind, sol, tok, ev, before, avg_before, t) -> None:
        """Monitor ao vivo: cada entrada/saída de um trader copiado, com o resultado dele no token."""
        tk = self.tokens.get(mint) or {}
        if mint not in self.sub_tokens:            # garante preço ao vivo do token que ele está segurando
            self._track_token(mint)
        px = (sol / tok) if sol > 0 and tok > 0 else self.price_of(ev)
        nb = ev.get("newTokenBalance")
        left = float(nb) if nb is not None else max(0.0, before + (tok if kind == "buy" else -tok))
        if kind == "buy":
            action = "aumentou" if before > 0 else "entrou"
            pnl_pct = None
        else:
            action = "saiu" if left <= max(before, tok) * 0.01 else "vendeu parte"
            pnl_pct = ((px / avg_before) - 1) * 100 if px and avg_before else None
        frac = (tok / before * 100) if kind == "sell" and before > 0 else None
        self.live.appendleft({"t": t, "at": now_iso(), "wallet": who, "short": short(who), "mint": mint,
                              "symbol": tk.get("symbol") or ev.get("symbol") or short(mint), "kind": kind,
                              "action": action, "sol": round(sol, 4), "tokens": tok, "price": px,
                              "mcap_sol": tk.get("mcap_sol"), "pnl_pct": None if pnl_pct is None else round(pnl_pct, 1),
                              "sold_pct": None if frac is None else round(min(100.0, frac)), "signature": ev.get("signature")})

    def trader_positions(self) -> list[dict]:
        """Posições abertas dos traders copiados (o que eles compraram e ainda seguram), com preço ao vivo."""
        out, now = [], time.time()
        for w in self.followed:
            for mint, p in ((self.wallets.get(w) or {}).get("pos") or {}).items():
                if p.get("tok", 0) <= 0:
                    continue
                tk = self.tokens.get(mint) or {}
                avg = p["cost"] / p["tok"] if p["tok"] else None
                px = tk.get("price")
                out.append({"wallet": w, "short": short(w), "mint": mint, "symbol": tk.get("symbol") or short(mint),
                            "invested_sol": round(p["cost"], 4), "avg_price": avg, "price": px,
                            "chg_pct": round((px / avg - 1) * 100, 1) if px and avg else None,
                            "value_sol": round(p["tok"] * px, 4) if px else None, "mcap_sol": tk.get("mcap_sol"),
                            "held_s": round(now - p.get("first_t", now)), "last_t": tk.get("last_t"),
                            "dev": bool(p.get("dev"))})
        out.sort(key=lambda x: x["held_s"] or 0)          # mais recentes primeiro
        return out

    def _track_token(self, mint: str) -> None:
        self.sub_tokens.append(mint)
        self._want_tokens.append(mint)
        held = {p["mint"] for p in self.positions()}
        mx = int(self._c("pump_track_tokens", 300))
        while len(self.sub_tokens) > mx:
            old = self.sub_tokens.popleft()
            if old not in held:
                self._drop_tokens.append(old)

    def _wallet_trade(self, w: str, mint: str, kind: str, sol: float, tok: float, t: float) -> None:
        st = self.wallets.setdefault(w, {"pos": {}, "closed": deque(maxlen=500), "trades": deque(maxlen=2000)})
        st["trades"].append(t)
        st["last_t"] = t
        p = st["pos"].get(mint)
        if kind == "buy":
            if p is None:
                p = st["pos"][mint] = {"tok": 0.0, "cost": 0.0, "first_t": t, "pnl": 0.0, "bought": 0.0,
                                       "mcap_in": (self.tokens.get(mint) or {}).get("mcap_sol")}   # aprendizado diário
            p["tok"] += tok
            p["cost"] += sol
            p["bought"] += tok
            return
        if not p or p["tok"] <= 0 or tok <= 0:
            return                                       # vendeu algo que não vimos comprar: fora do cálculo
        frac = min(1.0, tok / p["tok"])
        cost = p["cost"] * frac
        p["pnl"] += sol - cost
        p["cost"] -= cost
        p["tok"] = max(0.0, p["tok"] - tok)
        if p["tok"] <= p["bought"] * 0.01:              # fechou o token
            st["closed"].append({"t": t, "pnl": p["pnl"], "hold": t - p["first_t"], "mint": mint,
                                 "mcap_in": p.get("mcap_in")})
            del st["pos"][mint]

    # ------------------------------------------------------------------ ranking
    def ranking(self, limit: int = 50) -> list[dict]:
        """Carteiras ordenadas por lucro realizado (SOL) nas últimas 24 h, com os filtros anti-robô."""
        now = time.time()
        win_s = float(self._c("pump_rank_hours", 24)) * 3600
        min_closed = int(self._c("pump_min_closed", 3))
        min_wr = float(self._c("pump_min_winrate", 50))
        min_hold = float(self._c("pump_min_hold_s", 20))
        max_th = float(self._c("pump_max_trades_h", 120))
        banned = set(self.banned)
        out = []
        for w, st in self.wallets.items():
            closed = [c for c in st["closed"] if now - c["t"] <= win_s]
            if len(closed) < min_closed:
                continue
            pnl = sum(c["pnl"] for c in closed)
            wins = sum(1 for c in closed if c["pnl"] > 0)
            wr = wins / len(closed) * 100
            hold = statistics.median(c["hold"] for c in closed)
            th = sum(1 for x in st["trades"] if now - x <= 3600)
            flags = []
            if w in self.creators and now - self.creators[w] <= win_s:
                flags.append("criou token (dev)")
            if hold < min_hold:
                flags.append(f"robô sniper (segura {hold:.0f} s)")
            if th > max_th:
                flags.append(f"alta frequência ({th} trades/h)")
            if wr < min_wr:
                flags.append(f"acerto {wr:.0f}% < {min_wr:.0f}%")
            if w in banned:
                flags.append("banida por você")
            out.append({"wallet": w, "short": short(w), "pnl_sol": round(pnl, 4), "closed": len(closed), "wins": wins,
                        "winrate": round(wr, 1), "hold_s": round(hold), "trades_h": th, "open": len(st["pos"]),
                        "last_t": st.get("last_t"), "eligible": not flags and pnl > 0, "flags": flags})
        out.sort(key=lambda x: (not x["eligible"], -x["pnl_sol"]))
        return out[:limit]

    def refresh_followed(self, force: bool = False) -> None:
        wr = (float(self._c("pump_min_winrate", 50)), int(self._c("pump_lb_min_trades", 1000)))
        if wr != getattr(self, "_wr_used", wr):          # mudou acerto/trades mínimos no painel: refaz já
            force, self._lb_at = True, 0.0
        self._wr_used = wr
        if not force and time.time() - self._rank_at < float(self._c("pump_rank_every_s", 600)):
            return
        self._rank_at = time.time()
        self.ranking_cache = self.ranking(100)
        n = int(self._c("pump_top_n", 10))
        banned = set(self.banned)
        from . import consultas                          # 0.32.379: Configurações → Consultas do servidor
        q_top, q_est = consultas.on("pump_q_top"), consultas.on("pump_q_estudo")
        man = [w for w in self.manual if w not in banned] if q_top else []
        # sugeridos dos Maiores traders (80%+ de acerto, 0.31.4): entram como se fossem manuais enquanto estiverem lá
        man += [w for w in (getattr(self, "elite_follow", None) or []) if w not in banned and w not in man]
        now = time.time()
        bots = {w for w, a in self.activity.items() if a.get("bot_until", 0) > now}
        bots |= set(self.paused())                       # pausados também ficam fora (entra o próximo do top)
        if getattr(self.cfg, "pump_nc_on", False):       # 0.32.57: lançador de token / alta frequência nunca é copiado
            cand = set(man) | set(self.study_copy_wallets()) | set(self.study_lucro_wallets()) | {r.get("wallet") for r in self.leaderboard} | {r.get("wallet") for r in self.ranking_cache}
            bots |= {w for w in cand if w and self.uncopiable(w)}
        man = [w for w in man if w not in bots]
        # 0.32.4: "Copiar igual" — entram sempre (sem filtro de robô/pausa) enquanto o modo estiver ligado
        man += [w for w in self.eq_wallets() if w not in banned and w not in man]
        # 0.32.11: aprovadas pelo estudo automático (só fictícia; passam pelos filtros normais de cópia)
        if q_est:
            man += [w for w in self.study_copy_wallets() if w not in banned and w not in man and w not in bots]
            man += [w for w in self.study_lucro_wallets() if w not in banned and w not in man and w not in bots]
        self.leaderboard = [self._lb_judge(r) for r in self.leaderboard]
        lb = [r["wallet"] for r in self.leaderboard if r["eligible"] and r["wallet"] not in man
              and r["wallet"] not in banned and r["wallet"] not in bots]
        own = [r["wallet"] for r in self.ranking_cache if r["eligible"] and r["wallet"] not in man and r["wallet"] not in lb]
        # fonte: leaderboard da pump.fun (Solana Tracker); sem chave/sem dados → ranking próprio
        auto = (lb + own if self.leaderboard else own) if q_top else []
        if self._c("pump_liga_on", True):              # 0.32.328: vagas pelo resultado de quem copia (liga de candidatos)
            auto = self.liga_order(auto)
        off: dict[str, float | None] = {}
        if self._c("pump_only_online", True):
            # só entra quem está ONLINE (negociou nos últimos X min); o melhor do top que estiver online ocupa a vaga
            win = float(self._c("pump_online_min", 10)) * 60
            keep = []
            for w in auto:
                ls = self.last_seen(w)
                (keep.append(w) if ls and now - ls <= win else off.__setitem__(w, ls))
            auto = keep
        if self._c("pump_only_online", True):
            # 0.32.43 (pedido do dono: "copiar os 10 top traders ATIVOS"): os N melhores do top que estão online têm vagas
            # próprias; as carteiras manuais (botão Copiar, listas compartilhadas, estudo, sugeridos) não tiram essas vagas
            self.top_active = auto[:n]
            new = man + self.top_active
        else:
            new = (man + auto)[:max(n, len(man))]        # comportamento original (testes de referência)
            self.top_active = [w for w in new if w not in man]
        # quem já tem posição copiada continua sendo seguido até a posição fechar (para copiar a venda)
        held = [p["wallet"] for p in self.positions() if p["wallet"] not in new]
        new = new + list(dict.fromkeys(held))
        if new != self.followed:
            add = [w for w in new if w not in self._followed_sent]
            rem = [w for w in self._followed_sent if w not in new]
            if rem:
                self._out.append({"method": "unsubscribeAccountTrade", "keys": rem})
            if add:
                self._out.append({"method": "subscribeAccountTrade", "keys": add})
            self._followed_sent = set(new)
            if self._c("pump_only_online", True) and self.followed:
                gone = [w for w in self.followed if w not in new and w in off]
                came = [w for w in new if w not in self.followed and w not in man]
                if gone or came:
                    def ago(w):
                        return f"há {int((now - off[w]) // 60)} min" if off.get(w) else "sem atividade"
                    self._emit("Top traders atualizados: " + "; ".join(
                        ([f"entrou {short(w)} (online)" for w in came]) +
                        ([f"saiu {short(w)} (inativo, último trade {ago(w)})" for w in gone])))
            if self.followed or new:
                log.info("Pump.fun: copiando %d carteiras (%d manuais, %d do ranking)", len(new), len(man),
                         len([w for w in new if w not in man]))
            self.followed = new

    def follow_info(self, w: str) -> dict:
        """0.32.167 (pedido do dono: "configuração igual, compras diferentes"): se esta conta copia a carteira e de onde ela
        veio, ou por que não copia. A configuração não inclui a lista de traders: manual, IA, pausas e banidos são de cada conta."""
        if not w or w == "manual":
            return {"segue": False, "por": "não é cópia de trader"}
        if w in self.banned:
            return {"segue": False, "por": "banido nesta conta"}
        pz = self.paused().get(w)
        if pz:
            return {"segue": False, "por": "pausado nesta conta" + (f" ({pz.get('reason')})" if pz.get("reason") else "")}
        if w in self.followed:
            if w in self.eq_wallets():
                por = "Copiar igual"
            elif w in self.manual:
                por = "lista manual (botão Copiar ou lista recebida)"
            elif w in (getattr(self, "elite_follow", None) or []):
                por = "sugerido dos Maiores traders (80%+)"
            elif w in self.study_copy_wallets():
                por = "aprovado pelo estudo automático (IA)"
            elif w in self.study_lucro_wallets():
                por = "deu lucro no estudo (Estudo · deram lucro)"
            elif w in (getattr(self, "top_active", None) or []):
                por = "Top traders (entre os ativos do ranking)"
            else:
                por = "tem posição aberta dele (segue até fechar)"
            return {"segue": True, "por": por}
        if ((self.activity.get(w) or {}).get("bot_until") or 0) > time.time():
            return {"segue": False, "por": "marcado como robô"}
        if getattr(self.cfg, "pump_nc_on", False):
            u = self.uncopiable(w)
            if u:
                return {"segue": False, "por": u}
        r = next((r for r in self.leaderboard if r.get("wallet") == w), None)
        if r is None:
            if w in (getattr(self, "study", None) or []):
                return {"segue": False, "por": "está em Carteiras em estudo desta conta, mas o estudo só observa (não foi aprovada para copiar)"}
            return {"segue": False, "por": "não está na lista desta conta (não é manual, nem aprovada pela IA, nem está no ranking)"}
        if not r.get("eligible"):
            return {"segue": False, "por": "está no ranking, mas os filtros barram: " + "; ".join(r.get("flags") or [])}
        if self._c("pump_only_online", True) and not self.is_online(w):
            ls = self.last_seen(w)
            return {"segue": False, "por": "fora do ar" + (f" (último trade há {int((time.time() - ls) // 60)} min)" if ls else "")}
        return {"segue": False, "por": f"apto no ranking, mas fora dos {int(self._c('pump_top_n', 10))} melhores ativos desta conta"}

    def copy_now(self, w: str, real: bool = False) -> dict:
        """0.32.251 (pedido do dono, 07/11: "essas carteiras estão sendo copiadas?"): a resposta para UMA carteira (FICTÍCIA ou REAL).
        Estar na lista não basta: chave da aba, cópia de traders ou a própria carteira desligada também param a cópia."""
        c = self.cfg
        eq = self.is_eq(w) and w not in self.banned              # 0.32.253: o Copiar igual ignora pausa (ver refresh_followed e _copy)
        f = {"segue": True, "por": "Copiar igual"} if eq else self.follow_info(w)
        if not f["segue"]:
            return {"estado": "nao", "por": f["por"]}
        r = self._copy_now(w, f, eq, real)
        return {**r, "eq": True} if eq else r

    def copy_again(self, w: str) -> dict:
        """0.32.253 (pedido do dono, 07/11): "voltar a copiar" tem que resultar em cópia. Tirar a pausa de quem saiu do ranking
        não bastava: nesse caso a carteira entra na lista manual (e aí deixa de esperar a prova da fictícia, ver needs_proof)."""
        self.resume(w)
        if self.follow_info(w)["segue"]:
            return {"ok": True, "added": False}
        return {**self.add_manual(w), "added": True}

    def _copy_now(self, w: str, f: dict, eq: bool, real: bool) -> dict:
        c = self.cfg
        if not getattr(c, "pump_copy_enabled", True):
            return {"estado": "parado", "por": "na lista, mas a Cópia de traders está desligada"}
        off = None if eq else self.tab_off(w)                    # o Copiar igual vem antes da chave da aba (_copy → _copy_eq)
        if off:
            return {"estado": "parado", "por": "na lista, mas " + off.replace("aba ", "a aba ", 1).replace(" desligada", " está desligada")}
        if not real:
            if not getattr(c, "pump_sim_on", True):
                return {"estado": "parado", "por": "na lista, mas a carteira FICTÍCIA está desligada"}
            return {"estado": "sim", "por": f["por"]}
        if self.real is None or not getattr(c, "pump_real_enabled", False):
            return {"estado": "parado", "por": "na lista, mas a carteira REAL está desligada"}
        if eq:
            if not getattr(c, "pump_eq_real", False) and (getattr(self, "eq_mode", None) or {}).get(w) != "both":
                return {"estado": "so_ficticia", "por": "Copiar igual desta carteira está só na FICTÍCIA"}
        elif self.sim_only(w):
            return {"estado": "so_ficticia", "por": self.sim_only_why(w)}
        return {"estado": "sim", "por": f["por"]}

    def is_online(self, w: str) -> bool:
        ls = self.last_seen(w)
        return bool(ls and time.time() - ls <= float(self._c("pump_online_min", 10)) * 60)

    def last_seen(self, w: str) -> float | None:
        """Último momento em que a carteira negociou: o que o WebSocket viu, o que entrou no ranking próprio ou o
        "último trade" informado pela Solana Tracker (vale logo depois de reiniciar, antes de o WebSocket ver algo)."""
        ts = [(self.activity.get(w) or {}).get("last"), (self.wallets.get(w) or {}).get("last_t")]
        r = next((r for r in self.leaderboard if r.get("wallet") == w), None)
        if r:
            ts.append(self._ts(r.get("last_trade")))
        ts = [float(t) for t in ts if t]
        return max(ts) if ts else None

    @staticmethod
    def _ts(x) -> float | None:
        """Data em segundos a partir de número (s ou ms) ou texto ISO."""
        if x in (None, ""):
            return None
        try:
            v = float(x)
            return v / 1000 if v > 1e11 else v
        except (TypeError, ValueError):
            pass
        try:
            from datetime import datetime
            return datetime.fromisoformat(str(x).replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None

    # ------------------------------------------------------------------ leaderboard pump.fun (Solana Tracker)
    lb_key_fallback = None                      # chave emprestada pelo admin ("compartilhar com todos")

    def _lb_fb(self) -> str:
        if self.lb_key_fallback is None:
            return ""
        try:
            return self.lb_key_fallback() or ""
        except Exception:
            return ""

    def lb_key(self) -> str:
        own = self.keys.get("solanatracker_api_key") if self.keys is not None else ""
        if not own:
            return self._lb_fb()
        if stkeys.is_dead(own):                 # 0.32.71: sua chave sem créditos → usa a do sistema enquanto isso
            fb = self._lb_fb()
            if fb and fb != own and not stkeys.is_dead(fb):
                return fb
        return own

    def lb_key_src(self) -> str:
        """0.32.71: de onde vem a chave usada agora (para o Status), nunca a chave."""
        own = self.lb_key_own()
        k = self.lb_key()
        if not k:
            return "nenhuma"
        if own and k == (self.keys.get("solanatracker_api_key") or ""):
            return "sua chave" + (" (sem créditos)" if stkeys.is_dead(k) else "")
        return "chave do sistema" + (" (a sua está sem créditos)" if own else "") + (" (sem créditos)" if stkeys.is_dead(k) else "")

    def lb_key_own(self) -> bool:
        return bool(self.keys.get("solanatracker_api_key")) if self.keys is not None else False

    @staticmethod
    def _num(x):
        try:
            return None if x is None else float(x)
        except (TypeError, ValueError):
            return None

    def _parse_lb(self, js: dict) -> list[dict]:
        out = []
        min_wr = float(self._c("pump_min_winrate", 50))
        for i, t in enumerate((js or {}).get("traders") or []):
            w = t.get("wallet")
            if not w:
                continue
            per, idn = t.get("period") or {}, t.get("identity") or {}
            cnt, tok, tim = t.get("counts") or {}, t.get("tokens") or {}, t.get("timing") or {}
            wr = self._num(t.get("winRate"))
            if wr is not None and wr <= 1:
                wr *= 100
            flags = []
            if idn.get("bot"):
                flags.append("robô (" + str((idn.get("bot") or {}).get("name") or "bot") + ")")
            if idn.get("developer"):
                flags.append("dev de token")
            if idn.get("exchange"):
                flags.append("corretora")
            if idn.get("hacker") or idn.get("spamDusting"):
                flags.append("carteira suspeita")
            if w in self.banned:
                flags.append("banida por você")
            if idn.get("name"):
                self.market.__dict__.setdefault("trader_names", {})[w] = str(idn["name"])[:40]    # 0.32.138: fica depois que ele sai do ranking
            out.append({"rank": i + 1, "wallet": w, "short": short(w), "name": idn.get("name"),
                        "twitter": idn.get("twitter"), "avatar": idn.get("avatar"),
                        "realized_usd": self._num(per.get("realized")), "roi": self._num(per.get("roi")),
                        "volume_usd": self._num(per.get("volume")), "winrate": wr,
                        "trades": cnt.get("trades"), "tokens": cnt.get("tokensTraded"),
                        "closed": tok.get("closed"), "last_trade": tim.get("lastTrade"),
                        "days_active": per.get("tradingDays"), "base_flags": flags})
        return [self._lb_judge(r) for r in out]

    def _lb_judge(self, r: dict) -> dict:
        """Apto para copiar: sem bandeiras e acerto (histórico de tokens com lucro) ACIMA do mínimo (padrão 50%).
        Recalculado sempre, então mudar o mínimo no painel vale na hora."""
        min_wr = float(self._c("pump_min_winrate", 50))
        flags = list(r.get("base_flags") or [])
        wr = r.get("winrate")
        mt = int(self._c("pump_lb_min_trades", 1000))
        if mt and (r.get("trades") or 0) < mt:
            flags.append(f"{r.get('trades') or 0} trades (precisa ≥ {mt})")
        if wr is None:
            flags.append("acerto desconhecido")
        elif wr <= min_wr:
            flags.append(f"acerto {wr:.0f}% (precisa > {min_wr:.0f}%)")
        mw = float(self._c("pump_min_wallet_usd", 5000))
        wv = self.wallet_usd.get(r["wallet"])
        if mw:
            if wv is None:
                flags.append("conferindo saldo da carteira…")
            elif wv["usd"] < mw:
                flags.append(f"carteira ${wv['usd']:,.0f} < ${mw:,.0f}".replace(",", "."))
        r["wallet_usd"] = wv["usd"] if wv else None
        if r["wallet"] in self.banned and "banida por você" not in flags:
            flags.append("banida por você")
        r["flags"], r["eligible"] = flags, not flags
        return r

    # SEC-05 (auditoria 2026-10-25): cada clique forçava uma consulta com a chave do sistema, sem limite.
    LB_USER_COOLDOWN_S = 60                     # por conta
    LB_SHARED_PER_MIN = 6                       # soma de todas as contas usando a chave do sistema
    _lb_shared_calls: deque = deque()

    async def refresh_leaderboard_user(self) -> str | None:
        """Atualização pedida pelo painel. Devolve o motivo quando precisa esperar (nada é consultado)."""
        now = time.time()
        wait = self.LB_USER_COOLDOWN_S - (now - self._lb_at)
        if wait > 0:
            return f"o ranking acabou de ser atualizado; tente de novo em {int(wait) + 1} s"
        if self.lb_key() and not self.lb_key_own():
            q = PumpFun._lb_shared_calls
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.LB_SHARED_PER_MIN:
                return "muitas atualizações com a chave do sistema agora; tente em 1 minuto (ou use sua chave)"
            q.append(now)
        await self.refresh_leaderboard(force=True)
        return None

    async def refresh_leaderboard(self, force: bool = False) -> None:
        key = self.lb_key()
        if not key or self.http is None:
            self.lb_status.update(error=None if key else "sem chave da Solana Tracker")
            return
        if not force and time.time() - self._lb_at < float(self._c("pump_lb_every_s", 1800)):
            return
        self._lb_at = time.time()
        days = int(self._c("pump_lb_days", 7))
        params = {"sort": "realized", "direction": "desc", "days": days, "limit": 50,
                  "minTrades": int(self._c("pump_lb_min_trades", 1000)), "minDays": 1 if days == 1 else 3,
                  "minWinRate": float(self._c("pump_min_winrate", 50))}
        plat = str(self._c("pump_lb_platform", "pumpfun-app") or "")
        if plat:
            params["platform"] = plat
        try:
            r = await self.http.get(LB_URL, params=params, headers={"x-api-key": key, "Accept": "application/json"},
                                    timeout=20)
            if r.status_code != 200:
                msg = {401: "chave inválida", 403: "chave sem permissão para este endpoint",
                       429: "limite de requisições da Solana Tracker"}.get(r.status_code, f"HTTP {r.status_code}")
                if stkeys.no_credits(r.text):   # 0.32.69: não é falta de permissão, é o plano do mês que acabou
                    msg = "créditos do mês acabaram nesta chave (plano da Solana Tracker)"
                    stkeys.mark_dead(key)        # 0.32.71: fica de fora 1 h; a próxima consulta usa outra chave
                self.lb_status.update(error=msg + " · " + r.text[:120].replace(key, "***"))
                return
            stkeys.clear(key)
            lb = self._parse_lb(r.json())
            self.leaderboard = lb
            self.lb_status.update(at=now_iso(), error=None, count=len(lb), days=days)
            log.info("Pump.fun: leaderboard Solana Tracker com %d traders (%d dias)", len(lb), days)
            self.refresh_followed(force=True)
        except Exception as e:
            self.lb_status.update(error=f"{type(e).__name__}: {str(e)[:120].replace(key, '***')}")

    async def wallet_value(self, w: str) -> dict | None:
        """Saldo da carteira do trader: SOL + USDC + USDT (RPC grátis), em US$.
        0.32.238: só no RPC público grátis (antes ia para o Helius do Portainer e gastava créditos com dado não urgente)."""
        urls = [SOL_HTTP]
        for u in urls:
            try:
                b = (await self.http.post(u, json={"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [w]},
                                          timeout=8)).json()["result"]["value"] / 1e9
                st = 0.0
                for mint in (USDC, USDT):
                    js = (await self.http.post(u, json={"jsonrpc": "2.0", "id": 1, "method": "getTokenAccountsByOwner",
                                                        "params": [w, {"mint": mint}, {"encoding": "jsonParsed"}]},
                                               timeout=8)).json()
                    for a in ((js.get("result") or {}).get("value") or []):
                        st += float(a["account"]["data"]["parsed"]["info"]["tokenAmount"].get("uiAmountString") or 0)
                return {"sol": round(b, 4), "stable": round(st, 2), "usd": round(b * (self.sol_usd or 0) + st, 2),
                        "t": time.time()}
            except Exception:
                continue
        return None

    async def wallet_age(self, w: str, pages: int = 4) -> dict | None:
        """Idade da carteira (0.31.3): hora da transação mais antiga, lendo até `pages` páginas de 1.000 assinaturas no
        RPC grátis. Carteira muito ativa passa disso: aí a idade é "pelo menos" (more=True).
        0.32.238: só no RPC público grátis (antes o Helius do Portainer: até 4 consultas por carteira)."""
        url = SOL_HTTP
        before, oldest, n = None, None, 0               # n (0.32.9): transações contadas (até pages × 1.000)
        for _ in range(pages):
            opts = {"limit": 1000, **({"before": before} if before else {})}
            try:
                js = (await self.http.post(url, json={"jsonrpc": "2.0", "id": 1, "method": "getSignaturesForAddress",
                                                      "params": [w, opts]}, timeout=15)).json()
            except Exception:
                return None
            res = js.get("result")
            if not isinstance(res, list):
                return None
            if not res:
                break
            n += len(res)
            bt = [float(x["blockTime"]) for x in res if x.get("blockTime")]
            if bt:
                oldest = min(bt + ([oldest] if oldest else []))
            before = res[-1].get("signature")
            if len(res) < 1000:
                return {"first_t": oldest, "age_days": round((time.time() - oldest) / 86400, 1) if oldest else None,
                        "more": False, "txs": n, "t": time.time()}
        return {"first_t": oldest, "age_days": round((time.time() - oldest) / 86400, 1) if oldest else None,
                "more": True, "txs": n, "t": time.time()}

    async def refresh_wallet_values(self) -> None:
        if not float(self._c("pump_min_wallet_usd", 5000)) or not self.sol_usd:
            return
        cand = [r["wallet"] for r in self.leaderboard] + list(self.manual)
        changed = False
        for w in dict.fromkeys(cand):
            old = self.wallet_usd.get(w)
            if old and time.time() - old["t"] < float(self._c("pump_wallet_check_s", 1800)):
                continue
            v = await self.wallet_value(w)
            if v:
                self.wallet_usd[w] = v
                changed = True
            await asyncio.sleep(0.2)
        if changed:
            self.refresh_followed(force=True)

    async def lb_loop(self) -> None:
        while True:
            try:
                if getattr(self.cfg, "pump_enabled", True):
                    await self.refresh_leaderboard()
                    await self.refresh_wallet_values()
            except Exception as e:
                log.warning("Pump.fun leaderboard: %s", e)
            await asyncio.sleep(30)

    # ------------------------------------------------------------------ carteira fictícia
    def positions(self) -> list[dict]:
        return self.store.positions()

    def _save_pos(self, p: dict) -> None:
        if "api0" not in p and p.get("mint"):          # 0.32.220: foto do gasto das APIs desta moeda na abertura
            p["api0"], p["api0_boot"] = apiusage.mint_snapshot(p["mint"]), apiusage.BOOT
        self.store.save_pos(p)
        self._auto_record(p, closed=False)

    def _del_pos(self, p: dict) -> None:
        self.store.del_pos(p)

    def trades(self, limit: int = 1000) -> list[dict]:
        return self.store.trades(limit)

    @staticmethod
    def api_used(p: dict) -> dict:
        """0.32.220 (pedido do dono): requisições de cada API gastas com esta posição desde que abriu."""
        return apiusage.mint_used(p.get("mint") or "", p.get("api0"), p.get("api0_boot"))

    def _save_trade(self, t: dict) -> None:
        self.store.save_trade(t)
        self._auto_record(t, closed=True)

    def _auto_record(self, p: dict, closed: bool) -> None:
        if p.get("auto") is not True or p.get("origem") not in AUTO_ORIGINS:
            return
        from .auto_trades import operation_row
        key = str(p["id"])
        previous = self.auto_rows.get(key)
        row = operation_row(p, previous=previous, closed=closed)
        if row != previous:
            self.auto_rows[key] = row
            self._auto_dirty.add(key)

    PERIODS_H = (1, 6, 12, 24)
    TAB_ITENS = 60

    @classmethod
    def periods(cls, closed: list[dict], balance: float, now: float | None = None) -> list[dict]:
        """0.32.113 (pedido do dono): ganhos, perdas, saldo e investido dos trades FECHADOS nas últimas 1/6/12/24 h.
        `saldo_antes` = caixa da carteira no início do período, sem as posições abertas."""
        now = time.time() if now is None else now
        out = {h: {"horas": h, "trades": 0, "ganhos": 0, "perdas": 0, "ganhos_sol": 0.0, "perdas_sol": 0.0, "investido_sol": 0.0, "_w": set()} for h in cls.PERIODS_H}
        for t in closed:
            try:
                age = now - datetime.fromisoformat(str(t.get("closed_at")).replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
            pnl = float(t.get("pnl_sol") or 0)
            for h, g in out.items():
                if age <= h * 3600:
                    g["trades"] += 1
                    g["investido_sol"] += float(t.get("sol_in") or 0)
                    g["ganhos" if pnl > 0 else "perdas"] += 1
                    g["ganhos_sol" if pnl > 0 else "perdas_sol"] += pnl
                    if t.get("wallet") not in (None, "", "manual"):
                        g["_w"].add(t["wallet"])               # 0.32.136: carteiras copiadas com trade fechado no período
        res = []
        for g in out.values():
            saldo = g["ganhos_sol"] + g["perdas_sol"]
            res.append({**{k: v for k, v in g.items() if k != "_w"}, "traders": len(g["_w"]), "ganhos_sol": round(g["ganhos_sol"], 6), "perdas_sol": round(g["perdas_sol"], 6), "investido_sol": round(g["investido_sol"], 6),
                        "saldo_sol": round(saldo, 6), "saldo_antes": round(balance - saldo, 6)})
        return res

    @classmethod
    def tabs(cls, closed: list[dict], aba_of, now: float | None = None) -> list[dict]:
        """0.32.123 (pedido do dono): resultado de cada aba, no total e em 1/6/12/24 h. O percentual é o saldo sobre o que entrou
        nos trades fechados da aba. Roda só quando a janela abre: conta todos os trades e não cabe no snapshot de cada 2 s."""
        from .resultstudy import _group, motivo
        g: dict[str, list] = {}
        for t in closed:
            g.setdefault(aba_of(t), []).append(t)
        pct = lambda saldo, inv: round(saldo / inv * 100, 2) if inv else None
        campos = ("symbol", "mint", "opened_at", "closed_at", "sol_in", "pnl_sol", "pnl_pct", "hold_s", "best_pct", "reason")
        out = []
        for nome, L in g.items():
            pnl = [float(t.get("pnl_sol") or 0) for t in L]
            inv = sum(float(t.get("sol_in") or 0) for t in L)
            per = [{k: v for k, v in p.items() if k != "saldo_antes"} | {"pct": pct(p["saldo_sol"], p["investido_sol"])} for p in cls.periods(L, 0.0, now)]
            out.append({"aba": nome, "trades": len(L), "ganhos": sum(p > 0 for p in pnl), "perdas": sum(p <= 0 for p in pnl), "acerto": round(sum(p > 0 for p in pnl) / len(L) * 100),
                        "ganhos_sol": round(sum(p for p in pnl if p > 0), 6), "perdas_sol": round(sum(p for p in pnl if p <= 0), 6), "saldo_sol": round(sum(pnl), 6),
                        "investido_sol": round(inv, 6), "pct": pct(sum(pnl), inv), "periodos": per, "motivos": _group([(motivo(t.get("reason")), t) for t in L])})
            por = {}
            for t in sorted(L, key=lambda t: str(t.get("closed_at") or ""), reverse=True):      # 0.32.126: moedas e horários de cada motivo
                por.setdefault(motivo(t.get("reason")), []).append({k: t.get(k) for k in campos})
            for m in out[-1]["motivos"]:
                m["itens"] = por[m["nome"]][:cls.TAB_ITENS]
        return sorted(out, key=lambda x: -x["saldo_sol"])

    def sim_counts(self, x: dict) -> bool:
        """0.32.465 (pedido do dono, 25/11/2026: "resetar o saldo e colocar 1 SOL, mantendo o histórico"): depois de recomeçar, a
        carteira FICTÍCIA conta só o que ABRIU a partir do recomeço. Nada é apagado: os trades antigos seguem no Histórico."""
        since = getattr(self, "sim_since", None)
        if not since:
            return True
        t = x.get("open_t")
        if t is None:
            try:
                t = datetime.fromisoformat(str(x.get("opened_at") or x.get("closed_at")).replace("Z", "+00:00")).timestamp()
            except ValueError:
                return False
        return float(t) >= float(since)

    def wallet(self, real: bool = False) -> dict:
        start = 0.0 if real else float(self._c("pump_sim_balance_sol", 5.0))
        closed = [t for t in self.trades(100000) if bool(t.get("real")) == real and (real or self.sim_counts(t))]
        pos = [p for p in self.positions() if bool(p.get("real")) == real and (real or self.sim_counts(p))]
        realized = sum(t["pnl_sol"] for t in closed)
        open_cash = sum(p.get("proceeds", 0.0) - p["sol_in"] for p in pos)
        mark = sum(self._exit_value(p, p.get("price_now") or p["price_in"]) for p in pos)
        cash = start + realized + open_cash
        equity = cash + mark
        wins = [t for t in closed if t["pnl_sol"] > 0]
        return {"start_sol": start, "cash_sol": round(cash, 6), "equity_sol": round(equity, 6),
                "pnl_sol": round(equity - start, 6), "realized_sol": round(realized, 6),
                "open": len(pos), "open_value_sol": round(mark, 6), "count": len(closed), "wins": len(wins),
                "losses": len(closed) - len(wins), "win_rate": round(len(wins) / len(closed), 3) if closed else None,
                "gains_sol": round(sum(t["pnl_sol"] for t in wins), 6),
                "losses_sol": round(sum(t["pnl_sol"] for t in closed if t["pnl_sol"] <= 0), 6),
                "sol_usd": self.sol_usd, "periodos": self.periods(closed, start + realized),
                "since": None if real else getattr(self, "sim_since", None)}

    def curve(self, real: bool = False) -> list[list]:
        bal, pts = (0.0 if real else float(self._c("pump_sim_balance_sol", 5.0))), []
        for t in reversed([t for t in self.trades(5000) if bool(t.get("real")) == real and (real or self.sim_counts(t))]):
            bal += t["pnl_sol"]
            pts.append([t["closed_at"], round(bal, 6)])
        return pts

    # ------------------------------------------------------------------ cópia
    def _feed(self, **kw) -> None:
        kw.setdefault("at", now_iso())
        self.store.feed_add(kw)

    RLOG_S = 300                   # 0.31.89: um registro do log de análise a cada 5 min por robô

    def rlog(self, mod: str, key: str, label: str, why: str | None, t: float | None = None) -> None:
        """0.31.89 (pedido do dono: "log de análise para os outros robôs também"): decisão de um robô (copia, base, elite)
        sobre um item (key). Agrupa em blocos de 5 min; a mesma key no mesmo bloco guarda só a última decisão (robôs que
        reavaliam a lista a cada 20 s não contam o mesmo token 15 vezes). why=None = entrou/copiou."""
        t = time.time() if t is None else t
        b = int(t // self.RLOG_S) * self.RLOG_S
        logs = self.__dict__.setdefault("_rlog", {})
        rec = logs.setdefault((mod, b), {"mod": mod, "ini": b, "tok": {}, "dirty": True})
        cur = {"s": str(label)[:40], "w": None if why is None else str(why)[:160]}
        if rec["tok"].get(key) != cur:
            rec["tok"][key] = cur
            rec["dirty"] = True
        for k in sorted(k for k in logs if k[0] == mod)[:-3]:
            logs.pop(k, None)

    @staticmethod
    def rlog_summary(rec: dict) -> dict:
        import re
        toks = list(rec["tok"].values())
        mot: dict[str, list] = {}
        for x in toks:
            if x["w"]:
                k = re.sub(r"[-+]?\d+(?:[.,]\d+)?", "#", x["w"])[:90]
                mot.setdefault(k, [0, x["w"]])[0] += 1
        motivos = sorted(({"motivo": v[1], "n": v[0]} for v in mot.values()), key=lambda m: -m["n"])[:12]
        return {"mod": rec["mod"], "ini": rec["ini"], "analisados": len(toks), "entrou": sorted({x["s"] for x in toks if not x["w"]})[:30],
                "motivos": motivos, "gargalo": motivos[0]["motivo"] if motivos else None,
                "itens": [{"s": x["s"], "motivo": x["w"]} for x in toks if x["w"]][:40]}

    def rlog_pending(self) -> list[dict]:
        out = []
        for rec in (self.__dict__.get("_rlog") or {}).values():
            if rec.get("dirty"):
                rec["dirty"] = False
                out.append(self.rlog_summary(rec))
        return out

    def _copy_note(self, who: str, outcome: str, t: float | None = None, mint: str | None = None) -> None:
        """0.31.78 (pedido do dono: "não há cópia dos top traders nas últimas 24 h"): cada compra de trader seguido que o
        robô viu e o que fez com ela (copiou / motivo de não copiar). Só memória, 24 h (o Feed guarda só os últimos 500)."""
        d = self.__dict__.setdefault("_copy_diag", deque(maxlen=50000))
        d.append((time.time() if t is None else t, who, str(outcome)[:160]))
        if mint:     # 0.32.167: com a moeda, para dizer por que outra conta comprou e esta não (Por que compramos diferente)
            self.__dict__.setdefault("_copy_mint", deque(maxlen=50000)).append((d[-1][0], who, mint, d[-1][2]))
        n = self.__dict__["_rlog_n"] = self.__dict__.get("_rlog_n", 0) + 1         # cada compra vista é um item
        self.rlog("copia", f"{who}:{n}", short(who), None if outcome == "copiou" else outcome, t)

    def copy_diag(self, hours: float = 24, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        rows = [x for x in self.__dict__.get("_copy_diag") or [] if now - x[0] <= hours * 3600]
        motivos, ex, por = {}, {}, {}
        for _t, who, out in rows:
            key = re.sub(r"[-+]?\d+(?:[.,]\d+)?", "#", out)[:90]
            motivos[key] = motivos.get(key, 0) + 1
            ex.setdefault(key, out)
            p = por.setdefault(who, {"wallet": who, "vistas": 0, "copiadas": 0, "motivo": {}})
            p["vistas"] += 1
            if out == "copiou":
                p["copiadas"] += 1
            else:
                p["motivo"][ex[key]] = p["motivo"].get(ex[key], 0) + 1
        for p in por.values():
            p["principal"] = max(p["motivo"].items(), key=lambda kv: kv[1])[0] if p["motivo"] else None
            p.pop("motivo")
        return {"desde_reinicio": round((now - (rows[0][0] if rows else now)) / 3600, 1), "vistas": len(rows),
                "copiadas": sum(1 for r in rows if r[2] == "copiou"), "seguidos": len(self.followed),
                "motivos": sorted(({"motivo": ex[k], "n": n} for k, n in motivos.items()), key=lambda m: -m["n"])[:12],
                "traders": sorted(por.values(), key=lambda p: -p["vistas"])[:30]}

    def study_lucro_wallets(self) -> list[str]:
        """0.32.211 (pedido do dono): carteiras do estudo que deram lucro na cópia simulada de 30 dias (lista refeita pelo hub a
        cada 30 min e quando a chave muda). Copiadas só na FICTÍCIA, com os filtros normais, enquanto pump_st_lucro_on estiver ligada."""
        return list(getattr(self, "study_lucro", None) or []) if getattr(self.cfg, "pump_st_lucro_on", False) else []

    def study_copy_wallets(self) -> list[str]:
        """0.32.11: carteiras aprovadas pelo estudo automático que esta conta copia (só fictícia)."""
        return list(getattr(self, "study_copy", None) or []) if getattr(self.cfg, "pump_st_auto_copy", False) else []

    GATE_ORIGINS = ("explorar", "barrado", "base", "elite", "calls", "bruxo", "jevtrade")
    # 0.32.392 (dono, 20/11: "essa regra não funciona no BOOST, ela estava no copy trade"): o BOOST da migração vai para a REAL
    # pela chave dele (pump_bm_real), sem a trava por tela. A fictícia dele continua contando na tela, só não segura a REAL.
    TAB_GATE_SKIP = ("BOOST da migração",)

    def tab_gate_stats(self) -> dict:
        """0.32.325: {tela: (operações, soma em SOL)} das operações FICTÍCIAS fechadas nos últimos `pump_tab_gate_days` dias, já
        depois das taxas. Fora: REAL, ganho suspeito (preço falso) e fictícia desfeita. Cache por minuto."""
        from .auto_trades import SUSPECT_PCT
        tr = self.store.trades(100000)
        now, days = time.time(), int(self._c("pump_tab_gate_days", 7) or 7)
        key = (len(tr), tr[0].get("id") if tr else None, int(now // 60), days)
        if getattr(self, "_tgate_key", None) != key:
            cut, acc = now - days * 86400, {}
            for t in tr:
                if t.get("real") or float(t.get("pnl_pct") or 0) >= SUSPECT_PCT:
                    continue
                try:
                    ct = datetime.fromisoformat(str(t.get("closed_at")).replace("Z", "+00:00")).timestamp()
                except ValueError:
                    continue
                if ct >= cut and not self.px_tainted(t, ct):
                    a = acc.setdefault(self.aba_of(t), [0, 0.0])
                    a[0] += 1
                    a[1] += float(t.get("pnl_sol") or 0)
            self._tgate = {k: (n, s) for k, (n, s) in acc.items()}
            self._tgate_key = key
        return self._tgate

    def tab_gate_why(self, aba: str) -> str | None:
        """0.32.325 (pedido do dono): por que esta tela ainda não compra na REAL, ou None se já provou (ou a trava está desligada)."""
        if not getattr(self.cfg, "pump_tab_gate_on", False) or not aba:
            return None
        if aba in self.TAB_GATE_SKIP:                  # 0.32.392 (dono): "essa regra não funciona no BOOST"
            return None
        need, days = int(self._c("pump_tab_gate_n", 20) or 20), int(self._c("pump_tab_gate_days", 7) or 7)
        n, s = self.tab_gate_stats().get(aba, (0, 0.0))
        onde = "Carteiras → REAL → Espelho → \"Tela só vai para a REAL depois de dar lucro\""
        if n < need:
            return f"trava por tela: {aba} tem {n} de {need} operações fictícias fechadas em {days} dias; a REAL espera a prova ({onde})"
        if s <= 0:
            return (f"trava por tela: {aba} está com {s:+.4f} SOL na fictícia em {days} dias ({n} operações); a REAL só compra "
                    f"com a tela no positivo ({onde})")
        return None

    def tab_gate_view(self) -> list[dict]:
        """A situação de cada tela que já fechou operação na fictícia, para a tela mostrar (liberada ou o que falta)."""
        need = int(self._c("pump_tab_gate_n", 20) or 20)
        out = [{"aba": a, "n": n, "sol": round(s, 4), "precisa": need, "liberada": a in self.TAB_GATE_SKIP or (n >= need and s > 0),
                "sem_trava": a in self.TAB_GATE_SKIP}
               for a, (n, s) in self.tab_gate_stats().items()]
        return sorted(out, key=lambda x: (not x["liberada"], -x["sol"]))

    def sim_only(self, who: str) -> bool:
        """Cópia que não vai para a carteira REAL: as regras de sempre (`_sim_only_base`) ou a trava por tela (0.32.325)."""
        if not who:
            return False
        return self._sim_only_base(who) or bool(self.tab_gate_why(self.aba_of({"wallet": who})))

    def _sim_only_base(self, who: str) -> bool:
        """0.32.11: cópia que nunca vai para a carteira real (aprovadas do estudo automático, sem ser manual)."""
        # 0.32.17 (pedido do dono: "por enquanto copiar do estudo somente fictícia, desabilita a real pra testes")
        # 0.32.20 (pedido do dono: "quero padrão só na fictícia, por que está na real?"): toda carteira que está em Carteiras em
        # estudo copia só na fictícia, a menos que o dono ligue pump_st_real. Carteiras fora do estudo seguem a regra normal.
        if not who:
            return False
        if getattr(self.cfg, "pump_real_full_mirror", False):
            # 0.32.277 (pedido do dono, 10/11/2026: "a fictícia compra com lucro e a REAL não; tem que ser o espelho"): o Espelho total
            # ignora o "só fictícia" do estudo (Copiar, estudo automático, deram lucro, carteira em estudo). Ficam as travas com chave
            # própria: "REAL só depois de lucro na fictícia" e "Copiar só quem dá resultado".
            return self.needs_proof(who) or bool(self.edge_why(who, True))
        if who in (getattr(self, "real_ok_list", None) or []):
            return False                                  # 0.32.38: o dono escolheu "fictícia e REAL" no Copiar do estudo
        if who in self.study_copy_wallets() or who in (getattr(self, "sim_only_list", None) or []):
            return True
        if who in self.study_lucro_wallets():
            # 0.32.211: "deram lucro" copia só na fictícia; 0.32.213 (pedido do dono): com pump_st_lucro_real, também na REAL
            return not getattr(self.cfg, "pump_st_lucro_real", False)
        if who in (getattr(self, "study", None) or []) and not getattr(self.cfg, "pump_st_real", False):
            return True
        return self.needs_proof(who) or bool(self.edge_why(who, True))

    PROOF_WINDOW_S = 24 * 3600

    def proven_wallets(self) -> set:
        """0.32.251: carteiras com uma cópia FICTÍCIA fechada com lucro (depois das taxas).
        0.32.265 (pedido do dono): só valem as fechadas nas últimas 24 h — a cada 24 h a prova recomeça. Recalculado quando muda
        o número de trades guardados ou a cada minuto."""
        tr = self.store.trades(100000)
        now = time.time()
        key = (len(tr), tr[0].get("id") if tr else None, int(now // 60))
        if getattr(self, "_proven_key", None) != key:
            cut = now - self.PROOF_WINDOW_S
            out = set()
            for t in tr:
                if t.get("real") or t.get("follow_of") or not t.get("wallet") or float(t.get("pnl_sol") or 0) <= 0:
                    continue
                try:
                    ct = datetime.fromisoformat(str(t.get("closed_at")).replace("Z", "+00:00")).timestamp()
                except ValueError:
                    continue
                if ct >= cut:
                    out.add(t["wallet"])
            self._proven, self._proven_key = out, key
        return self._proven

    PX_FIX_T = 1794553200.0     # 13/11/2026 07:00 UTC: a partir daqui o preço do trade é conferido com o mercado (0.32.331)

    def px_tainted(self, t: dict, closed_t: float) -> bool:
        """Cópia fictícia de token de fora da pump.fun (Orca, Raydium, Meteora…) aberta antes da conferência de preço: o preço
        de entrada podia estar errado (ganhos falsos de +100% a +190%). Não conta para liberar trader ou tela para a REAL."""
        if not str(t.get("venue") or "").startswith("DEX "):
            return False
        try:
            ot = datetime.fromisoformat(str(t.get("opened_at")).replace("Z", "+00:00")).timestamp()
        except ValueError:
            ot = closed_t
        return ot < self.PX_FIX_T

    def edge_stats(self) -> dict:
        """0.32.275: {carteira: (cópias, média % por cópia)} das cópias FICTÍCIAS fechadas nos últimos `pump_edge_days` dias
        (resultado depois das taxas; ignora REAL, cópia de outra conta e ganho suspeito). Cache por minuto."""
        from .auto_trades import SUSPECT_PCT
        tr = self.store.trades(100000)
        now, days = time.time(), int(self._c("pump_edge_days", 7) or 7)
        key = (len(tr), tr[0].get("id") if tr else None, int(now // 60), days)
        if getattr(self, "_edge_key", None) != key:
            cut, acc = now - days * 86400, {}
            holds: dict[str, list] = {}
            for t in tr:
                w = t.get("wallet")
                if t.get("real") or t.get("follow_of") or not w or len(w) < 32 or float(t.get("pnl_pct") or 0) >= SUSPECT_PCT:
                    continue
                try:
                    ct = datetime.fromisoformat(str(t.get("closed_at")).replace("Z", "+00:00")).timestamp()
                except ValueError:
                    continue
                if ct >= cut and not self.px_tainted(t, ct):
                    a = acc.setdefault(w, [0, 0.0])
                    a[0] += 1
                    a[1] += float(t.get("pnl_pct") or 0)
                    if t.get("hold_s") is not None:
                        holds.setdefault(w, []).append(float(t.get("hold_s") or 0))
            self._edge = {w: (n, sm / n) for w, (n, sm) in acc.items()}
            # 0.32.328: quanto tempo as cópias de cada trader ficam abertas (mediana), para a liga de candidatos
            self._edge_hold = {w: sorted(h)[len(h) // 2] for w, h in holds.items() if h}
            self._edge_key = key
        return self._edge

    def liga_order(self, auto: list[str]) -> list[str]:
        """0.32.328 (pedido do dono: "copiar os maiores traders não estava dando certo"): liga de candidatos. Quem tem base
        (`pump_edge_min_n` cópias fictícias fechadas em `pump_edge_days` dias) e média por cópia ≥ `pump_edge_min_pct` sobe para o
        começo (maior média primeiro); quem ainda não tem base fica em teste, na ordem do ranking; quem tem base e média abaixo do
        mínimo, ou cujas cópias duram menos que `pump_liga_min_hold_s` (vende rápido demais para dar tempo de copiar), sai das vagas.
        O motivo de cada um que saiu fica em `liga_out` para a tela."""
        st, hold = self.edge_stats(), getattr(self, "_edge_hold", {}) or {}
        need, mn = int(self._c("pump_edge_min_n", 5)), float(self._c("pump_edge_min_pct", 0))
        mh, days = float(self._c("pump_liga_min_hold_s", 60) or 0), int(self._c("pump_edge_days", 7))
        prov, trial, out = [], [], {}
        for w in auto:
            n, m = st.get(w, (0, 0.0))
            if n >= need and mh and w in hold and hold[w] < mh:
                out[w] = f"vende rápido demais para copiar: as cópias duram {hold[w]:.0f} s (mediana de {n} em {days} dias)"
            elif n >= need and m < mn:
                out[w] = f"média de {m:+.1f}% por cópia nas últimas {n} ({days} dias)"
            elif n >= need:
                prov.append((m, w))
            else:
                trial.append(w)
        self.liga_out = out
        self.liga_count = {"comprovados": len(prov), "em_teste": len(trial), "rebaixados": len(out)}
        return [w for _, w in sorted(prov, key=lambda x: -x[0])] + trial

    def edge_why(self, who: str, for_real: bool) -> str | None:
        """0.32.275 (pedido do dono): com `pump_edge_on`, só copia quem tem média por cópia ≥ `pump_edge_min_pct` nas
        últimas cópias fictícias. Sem base ainda (menos de `pump_edge_min_n` cópias): a fictícia copia para aprender e a REAL
        espera. Devolve o motivo de não copiar, ou None."""
        if not getattr(self.cfg, "pump_edge_on", False) or not who or len(who) < 32:
            return None
        if not for_real and getattr(self.cfg, "pump_edge_real_only", True):
            return None
        n, m = self.edge_stats().get(who, (0, 0.0))
        need, days, mn = int(self._c("pump_edge_min_n", 5)), int(self._c("pump_edge_days", 7)), float(self._c("pump_edge_min_pct", 0))
        if n < need:
            return None if not for_real else (f"trader ainda sem base: {n} de {need} cópias fictícias fechadas em {days} dias "
                                               "(a REAL espera a média — Top traders → Copiar só quem dá resultado)")
        if m < mn:
            return f"média de {m:+.1f}% por cópia nas últimas {n} ({days} dias); o mínimo é {mn:+.0f}% (Copiar só quem dá resultado)"
        return None

    def needs_proof(self, who: str) -> bool:
        """0.32.251 (pedido do dono, caso Fvgs…pTkL: carteira com 59 SOL fez uma compra de 0,01 SOL e se esvaziou logo depois):
        trader sem cópia fictícia com lucro vai SÓ para a fictícia; depois de uma cópia fictícia fechada com lucro, as seguintes
        vão também para a REAL. 0.32.265 (pedido do dono): o lucro tem que ser das últimas 24 h, e a regra vale também para
        os traders da lista manual."""
        if not getattr(self.cfg, "pump_real_need_win", True) or not who or len(who) < 32:
            return False
        return who not in self.proven_wallets()

    def sim_only_why(self, who: str) -> str:
        if not self._sim_only_base(who):
            gw = self.tab_gate_why(self.aba_of({"wallet": who}))
            if gw:
                return gw
        ew = self.edge_why(who, True)
        if ew and not self.needs_proof(who):
            return ew
        return self._sim_only_why(who)

    def _sim_only_why(self, who: str) -> str:
        if self.needs_proof(who) and getattr(self.cfg, "pump_real_full_mirror", False):
            return ("sem cópia fictícia com lucro nas últimas 24 h: fica só na fictícia até uma fechar com lucro "
                    "(Carteiras → REAL → Espelho → \"REAL só depois de lucro na fictícia\")")
        if self.needs_proof(who) and not (who in (getattr(self, "study", None) or []) or who in self.study_copy_wallets()
                                          or who in (getattr(self, "sim_only_list", None) or []) or who in self.study_lucro_wallets()):
            return ("sem cópia fictícia com lucro nas últimas 24 h: fica só na fictícia até uma fechar com lucro "
                    "(Carteiras → REAL → \"REAL só depois de lucro na fictícia\")")
        """0.32.162: por que esta carteira copia só na fictícia (o texto aparece no feed e nas Operações recentes do modo REAL)."""
        if who in (getattr(self, "sim_only_list", None) or []):
            return "você escolheu 'só fictícia' no Copiar desta carteira (Carteiras em estudo)"
        if who in self.study_copy_wallets():
            return "carteira aprovada pelo estudo automático: cópia só na fictícia"
        if who in self.study_lucro_wallets():
            return "carteira que deu lucro no estudo: cópia só na fictícia (ligue \"Estudo · deram lucro na REAL\" para ir à real)"
        return "carteira em Carteiras em estudo: copia só na fictícia (para ir à real, ligue a REAL do estudo ou escolha 'fictícia e REAL' no Copiar)"

    def eq_wallets(self) -> list[str]:
        """0.32.4: carteiras do "Copiar igual" (vazio com o modo desligado)."""
        if not getattr(self.cfg, "pump_eq_on", False):
            return []
        mode = getattr(self, "eq_mode", None) or {}               # 0.32.65: botão Copiar de cada carteira (Parar = fora)
        # 0.32.67 (dono: "cliquei copiar UMA carteira e acionou todas"): só copia a carteira em que a pessoa clicou Copiar
        return [w for w in (getattr(self, "copy_equal", None) or []) if mode.get(w, "off") != "off"]

    def is_eq(self, who: str) -> bool:
        return bool(who) and who in self.eq_wallets()

    def _copy_eq(self, who: str, mint: str, kind: str, sol: float, tok: float, ev: dict, before: float, t: float) -> list[str]:
        """0.32.4 (pedido do dono, 28/10: "copiar exatamente o que eles fazem"): carteira do "Copiar igual". Compra na
        hora (sem espera, sem filtros de token/nota/preço, sem pausa) com o valor próprio do modo; vende a mesma
        proporção quando ela vende. Sem stop, stop móvel, alvo ou saídas inteligentes; só o tempo máximo do modo e o stop
        opcional (0 = sem stop), porque uma venda que o monitor perder deixaria a posição aberta para sempre.
        A real só entra pelo espelho e só com pump_eq_real."""
        c = self.cfg
        tk = self.tokens.get(mint) or {}
        sym = tk.get("symbol") or ev.get("symbol") or short(mint)
        px = self._ev_px(ev, tk) or tk.get("price")
        allpos = self.positions()
        base = {"wallet": who, "short": short(who), "mint": mint, "symbol": sym, "kind": kind, "sol": round(sol, 4),
                "mcap_sol": tk.get("mcap_sol"), "signature": ev.get("signature")}
        if kind != "buy":
            frac = self._sell_frac(ev, tok, before)
            mine = sorted((p for p in allpos if p["mint"] == mint and p["wallet"] == who and p.get("eq")),
                          key=lambda x: not x.get("real"))          # a real vende primeiro
            if not mine or frac < 0.01:
                return []
            out = []
            for p in mine:
                if p.get("real"):
                    self._real_sell(p, frac, f"copiar igual: carteira vendeu {frac * 100:.0f}%")
                    self._feed(**base, action="REAL: vendendo", reason=f"copiar igual: vendendo {frac * 100:.0f}%")
                    continue
                out.append(self._sell(p, frac, px or p.get("price_now"), f"copiar igual: carteira vendeu {frac * 100:.0f}%", t))
                self._feed(**base, action="copiou venda", reason=f"copiar igual: vendeu {frac * 100:.0f}% da posição")
            return [m for m in out if m]
        why = None
        amt = round(float(self._c("pump_eq_sol", 0.05)), 6)
        eqpos = [p for p in allpos if p.get("eq") and not p.get("real")]
        if not getattr(c, "pump_copy_enabled", True):
            why = "cópia desligada"
        elif not getattr(c, "pump_sim_on", True):
            why = "carteira FICTÍCIA desligada"
        elif not px:
            why = "sem preço do token"
        elif any(p["mint"] == mint and p["wallet"] == who and p.get("eq") and not p.get("real") for p in allpos):
            why = "copiar igual: já tem a posição desta carteira neste token"
        elif len(eqpos) >= int(self._c("pump_eq_max_open", 20)):
            why = f"copiar igual: limite de {int(self._c('pump_eq_max_open', 20))} posições"
        elif self.wallet()["cash_sol"] < amt + float(self._c("pump_priority_sol", 0.0005)):
            why = "saldo fictício insuficiente"
        if why:
            self._feed(**base, action="não copiou", reason=why)
            self._copy_note(who, why, t, mint)
            return []
        fr = self._fee_rates(mint)
        slip, prio = fr["slip"], fr["prio"]
        fee = fr["venue"] + fr["portal"]
        price_in = px * (1 + slip)
        net_in = amt * (1 - fee)
        tokens = net_in / price_in
        bt = ev.get("blockTime")
        lag = round(max(0.0, t - float(bt)), 1) if bt else None
        rules = {"eq": True, "off_stop": True, "off_trail": True, "off_tp1": True,
                 "max_hold_s": float(self._c("pump_eq_max_hold_h", 24)) * 3600}
        p = {"opened_at": now_iso(), "open_t": t, "wallet": who, "mint": mint, "symbol": sym,
             "sol_in": round(amt + prio, 9), "tokens": tokens, "tokens_left": tokens, "price_in": price_in,
             "price_now": px, "trader_price": px, "trader_sol": sol, "proceeds": 0.0, "fees_sol": amt * fee + prio,
             "mcap_in": tk.get("mcap_sol"), "real": False, "venue_in": fr["venue_name"], "lag_s": lag,
             "grad_in": self.graduated(mint), "trader_px": self.price_of(ev), **rules}
        self._addfee(p, platform=amt * fr["venue"], portal=amt * fr["portal"], network=prio,
                     slippage=net_in - net_in / (1 + slip))
        self._save_pos(p)
        self._feed(**base, action="copiou compra", reason=f"copiar igual: comprou {amt:.3f} SOL a {price_in:.3e}"
                   + (f" · atraso {lag:.0f} s" if lag is not None else ""))
        self._copy_note(who, "copiou", t, mint)
        msgs = [f"[PUMP SIM] copiar igual {short(who)}: compra {sym} {amt:.3f} SOL (carteira comprou {sol:.3f} SOL)"]
        # 0.32.65: "FICTÍCIA e REAL" no botão Copiar da carteira vale para ela (sem ligar a REAL das outras)
        if getattr(c, "pump_eq_real", False) or (getattr(self, "eq_mode", None) or {}).get(who) == "both":
            if self._mirror_real(p, trader_sol=sol, block_t=bt, pos_cfg=dict(rules)) and self.exact_on():
                return []                                  # 0.32.160: a real não entrou, a fictícia foi desfeita
        elif self.real is not None and getattr(c, "pump_real_enabled", False):
            self._feed(**base, action="REAL não copiou", reason="copiar igual: real desligada neste modo (só fictícia)",
                       sim_id=p["id"])
        self._lead("open", p)
        return msgs

    def _copy(self, who: str, mint: str, kind: str, sol: float, tok: float, ev: dict, before: float, t: float) -> list[str]:
        c = self.cfg
        if self.is_eq(who):
            return self._copy_eq(who, mint, kind, sol, tok, ev, before, t)
        tk = self.tokens.get(mint) or {}
        sym = tk.get("symbol") or ev.get("symbol") or short(mint)
        px = (tk.get("price") if ev.get("_delayed") and tk.get("price") else None) or self._ev_px(ev, tk) or tk.get("price")
        # 0.32.262 (dono, caso yarl: a fictícia deu +18% e a REAL −23% no mesmo trade): na cópia com espera a fictícia usava o
        # último preço guardado do token, que no PumpSwap pode estar ANTES da compra do trader (1,28e-6 contra 1,82e-6 que
        # ele pagou). Quem copia nunca compra mais barato que o trader que acabou de empurrar o preço: usa o maior dos dois.
        if kind == "buy" and ev.get("_delayed") and px:
            tpx = self.price_of(ev)
            if tpx and px < tpx:
                px = tpx
        allpos = self.positions()
        mine = [p for p in allpos if p["mint"] == mint]
        base = {"wallet": who, "short": short(who), "mint": mint, "symbol": sym, "kind": kind, "sol": round(sol, 4),
                "mcap_sol": tk.get("mcap_sol"), "signature": ev.get("signature")}
        delay = float(self._c("pump_copy_delay_s", 0) or 0)
        if kind == "buy" and self.is_paused(who):
            pz = self.paused().get(who) or {}
            self._feed(**base, action="não copiou", reason="trader pausado" + (f" ({pz.get('reason')})" if pz.get("reason") else ""))
            self._copy_note(who, "trader pausado", t, mint)
            return []
        if kind == "buy" and delay > 0 and not ev.get("_delayed"):
            key = (who, mint)
            if key not in self._pending:
                self._pending[key] = {"due": t + delay, "t": t, "who": who, "mint": mint, "sol": sol, "tok": tok,
                                      "ev": dict(ev), "before": before}
                self._feed(**base, action="aguardando", reason=f"copia em {delay:.0f} s se o trader continuar no token")
                self._copy_note(who, "aguardando a espera configurada antes de copiar", t, mint)
            return []
        if kind == "buy":
            why = None
            score, sparts = self.entry_score(who, mint, self.price_of(ev), px)
            if not getattr(c, "pump_copy_enabled", True):
                why = "cópia desligada"
            elif self.tab_off(who):
                why = self.tab_off(who)
            elif getattr(c, "pump_streak_on", False) and self._halt_until > time.time():
                why = "pausa por sequência de perdas até " + datetime.fromtimestamp(self._halt_until).strftime("%H:%M")
            elif not px:
                why = "sem preço do token"
            elif sol < float(self._c("pump_min_trader_sol", 0.2)):
                why = f"compra pequena do trader ({sol:.3f} SOL < mínimo {float(self._c('pump_min_trader_sol', 0.2)):.2f})"
            else:
                mc, lo, hi = tk.get("mcap_sol"), float(self._c("pump_min_mcap_sol", 0)), float(self._c("pump_max_mcap_sol", 0))
                if mc is not None and lo and mc < lo:
                    why = f"market cap {mc:.0f} SOL abaixo do mínimo {lo:.0f}"
                elif mc is not None and hi and mc > hi:
                    why = f"market cap {mc:.0f} SOL acima do máximo {hi:.0f}"
                if not why:
                    why = self.token_block(mint)
                if not why:
                    why = self.px_check_block(mint, ev, t)
                if not why:
                    why = self.chase_block(self.price_of(ev), px)
                if not why:
                    why = self.runup_block(mint, px, t)
                if not why:
                    why = self.curve_block(mint)
                if not why:
                    why = self.flow_block(mint)
                if not why:
                    why = self.dump_block(mint)
                if not why and getattr(c, "pump_nc_on", False) and who not in self.eq_wallets():
                    why = self.uncopiable(who)
                if not why:
                    why = self.edge_why(who, False)          # 0.32.275: com "travar também a fictícia"
                if not why:
                    why = self.blacklist_block(who, mint)
                mn = self._onv("pump_score_min_on", "pump_score_min")
                if not why and mn and score < mn:
                    why = f"nota da entrada {score:.0f} abaixo do mínimo {mn:.0f}"
                if not why:
                    why = self.sg_entry_block(who, tk, ev, t, score)
            if why:
                self._feed(**base, action="não copiou", reason=why)
                self._copy_note(who, why, t, mint)
                self._top_barred(who, mint, why, t)
                return []
            msgs = []
            # REAL (se ligado): compra de verdade, com o valor de "SOL por compra". Com o espelho (0.31.37) o real só
            # entra DEPOIS que o fictício abriu a posição (ver _mirror_real, no fim deste bloco)
            # 0.32.3 — sugestão do Bruxo (áudio de 28/10, SPCX): com o espelho, a real só entrava quando a FICTÍCIA abria; se a
            # fictícia já tinha o token, a real ficava de fora ("já tem posição copiada"). Agora as duas carteiras têm posições
            # separadas: a fictícia já ter o token não impede a real de comprar (ela segue as vendas do trader e os stops).
            # 0.32.198 (pedido do dono): com a chave da FICTÍCIA desligada, a cópia de trader vai só para a REAL (se ligada), pelo mesmo caminho
            sim_off = not getattr(c, "pump_sim_on", True)
            hold_sim = any(not p.get("real") for p in mine)
            # 0.32.214 (clippy do dono, 04/11): na CÓPIA EXATA as duas carteiras têm as mesmas posições. Se a fictícia já tinha o
            # token (comprado quando a REAL estava desligada), a REAL não abre uma posição separada, em outro preço e outra hora.
            exact_hold = (hold_sim and not sim_off and self.exact_on() and self.real is not None
                          and getattr(c, "pump_real_enabled", False) and not any(p.get("real") for p in mine))
            alone = (self.real is not None and getattr(c, "pump_real_enabled", False) and getattr(c, "pump_real_mirror", True)
                     and (sim_off or (hold_sim and not self.exact_on())))
            if self.sim_only(who) and self.real is not None and getattr(c, "pump_real_enabled", False):
                self._feed(**base, action="REAL não copiou", reason=self.sim_only_why(who))
            elif exact_hold:
                self._feed(**base, action="REAL não copiou", reason="cópia exata: a fictícia já tinha este token de antes (a REAL não abre posição separada, em outro preço)")
            elif self.real is not None and getattr(c, "pump_real_enabled", False) and (alone or not getattr(c, "pump_real_mirror", True)):
                rwhy = None
                if not self.is_pump(mint) and not getattr(c, "pump_copy_other_real", False):
                    rwhy = "fora da pump.fun: real desligado para outras DEXs (só fictício)"
                self._real_buying.prune()
                rmine = [p for p in mine if p.get("real")] or ([1] if mint in self._real_buying else [])
                if rwhy:
                    pass
                elif rmine:
                    rwhy = "já tem posição REAL neste token"
                elif len([p for p in allpos if p.get("real")]) + len(self._real_buying) >= int(self._c("pump_real_max_open", 5)):
                    rwhy = f"limite de {int(self._c('pump_real_max_open', 5))} posições reais"
                if rwhy:
                    self._feed(**base, action="REAL não copiou", reason=rwhy)
                else:
                    self._real_buying.add(mint)
                    self._rq_put(("buy", {"wallet": who, "mint": mint, "symbol": sym, "trader_sol": sol,
                                          "trader_price": self.price_of(ev) or px, "mcap_in": tk.get("mcap_sol"), "t": t,
                                          "block_t": ev.get("blockTime")}))
                    self._feed(**base, action="REAL: comprando", reason=f"enviando compra de {float(self._c('pump_real_max_sol', 0.05)):.3f} SOL"
                               + (" · fictícia desligada; só a real entra" if sim_off else " · a fictícia já tinha este token; a real entra separada" if alone else ""))
            if sim_off:
                self._feed(**base, action="não copiou", reason="carteira FICTÍCIA desligada")
                self._copy_note(who, "carteira FICTÍCIA desligada", t, mint)
                return msgs
            # FICTÍCIO (roda com a chave da fictícia ligada, para comparar)
            smine = [p for p in mine if not p.get("real")]
            mult, mwhy = self.trust_mult(who)
            if getattr(c, "pump_size_by_score", False):
                mult *= 0.5 + score / 100
                mwhy = (mwhy + " · " if mwhy else "") + f"×{0.5 + score / 100:.2f} pela nota {score:.0f}"
            cold = self.cold_market()
            if cold:
                mult *= 0.5
                mwhy = (mwhy + " · " if mwhy else "") + cold
            amt = round(float(self._c("pump_copy_sol", 0.1)) * mult, 6)
            bt = ev.get("blockTime")
            lag = round(max(0.0, t - float(bt)), 1) if bt else None     # do trade do trader até a nossa cópia
            swhy = None
            # 0.32.159 (pedido do dono: "a real sempre primeiro"): na cópia exata quem decide é a real — os limites e o saldo da
            # fictícia não barram a compra; valem os da real (conferidos em _mirror_real)
            follow_real = self.exact_on() and not self.sim_only(who)
            if smine:
                swhy = "já tem posição copiada neste token (fictícia)"
            elif not follow_real and len([p for p in allpos if not p.get("real") and not p.get("eq") and p.get("origem") != "barrado"]) >= int(self._c("pump_max_open", 10)):
                # 0.32.255 (dono: "por que limita em 20 se configurei 40?"): o 40 era o da REAL; este é o da FICTÍCIA
                swhy = (f"limite de {int(self._c('pump_max_open', 10))} posições abertas na FICTÍCIA (Carteira FICTÍCIA → "
                        f"Posições ao mesmo tempo; a REAL tem o limite próprio: {int(self._c('pump_real_max_open', 5))})")
            elif not follow_real and self.wallet()["cash_sol"] < amt + float(self._c("pump_priority_sol", 0.0005)):
                swhy = "saldo fictício insuficiente"
            if swhy:
                self._copy_note(who, swhy, t, mint)
                self._top_barred(who, mint, swhy, t)
                self._feed(**base, action="não copiou", reason=swhy)
                return msgs
            fr = self._fee_rates(mint)
            slip, prio = fr["slip"], fr["prio"]
            fee = fr["venue"] + fr["portal"]
            price_in = px * (1 + slip)                      # você entra depois dele: preço pior
            net_in = amt * (1 - fee)
            tokens = net_in / price_in
            p = {"opened_at": now_iso(), "open_t": t, "wallet": who, "mint": mint, "symbol": sym,
                 "sol_in": round(amt + prio, 9), "tokens": tokens, "tokens_left": tokens, "price_in": price_in,
                 "price_now": px, "trader_price": px, "trader_sol": sol, "proceeds": 0.0, "fees_sol": amt * fee + prio,
                 "mcap_in": tk.get("mcap_sol"), "real": False, "venue_in": fr["venue_name"], "lag_s": lag,
                 "score": score, "score_parts": sparts, "grad_in": self.graduated(mint),
                 "trader_px": self.price_of(ev)}
            self._addfee(p, platform=amt * fr["venue"], portal=amt * fr["portal"], network=prio,
                         slippage=net_in - net_in / (1 + slip))
            self._save_pos(p)
            self.ghosts.on_open(p, t)
            self._feed(**base, action="copiou compra", reason=f"comprou {amt:.3f} SOL a {price_in:.3e} · nota {score:.0f}"
                       + (f" · atraso {lag:.0f} s" if lag is not None else "") + (f" · {mwhy}" if mwhy else ""))
            self._copy_note(who, "copiou", t, mint)
            msgs.append(f"[PUMP SIM] copiou {short(who)}: compra {sym} {amt:.3f} SOL (trader comprou {sol:.3f} SOL)")
            if not self.sim_only(who):
                if self._mirror_real(p, trader_sol=sol, block_t=ev.get("blockTime")) and self.exact_on():
                    return []                              # 0.32.158: a real não entrou, a fictícia foi desfeita
            self._lead("open", p)
            return msgs
        # venda do trader enquanto a cópia ainda estava esperando: se ele saiu, não copia
        pend = self._pending.get((who, mint))
        if pend:
            nb = ev.get("newTokenBalance")
            left = float(nb) if nb is not None else ((self.wallets.get(who) or {}).get("pos") or {}).get(mint, {}).get("tok", 0.0)
            if left <= pend["tok"] * 0.05:
                self._pending.pop((who, mint), None)
                self._feed(**base, action="não copiou",
                           reason=f"trader saiu em {t - pend['t']:.0f} s (antes dos {float(self._c('pump_copy_delay_s', 0)):.0f} s de espera)")
                return []
        # venda do trader: vende a mesma proporção da nossa posição copiada dele
        frac = self._sell_frac(ev, tok, before)
        if self.ghosts.open:
            self.ghosts.on_trader_sell(who, mint, frac, px or tk.get("price"), t)
        if self.sg_sombra.abertas:                         # 0.32.332: a sombra também vende junto com o trader
            self.sg_sombra.trader(who, mint, frac, px or tk.get("price"), t)
        mine = [p for p in mine if p["wallet"] == who]
        if not mine:
            return []
        if frac < 0.01:                                  # venda irrelevante (<1% do que ele tinha): não mexe
            return []
        out = []
        # 0.32.156 (pedido do dono, casos inu e WB de 01/11: "a prioridade é sempre a real"): com as duas carteiras no token do
        # mesmo trader, a REAL decide junto com a fictícia e sai PRIMEIRO. Antes cada uma olhava o próprio preço de entrada:
        # a real, que entra mais caro, ficava "segurando até ficar positivo" enquanto a fictícia vendia no lucro (WB: a
        # fictícia saiu em +20,8% e a real caiu até o stop de −40%).
        def _chg(q):
            pxn = px or q.get("price_now") or q["price_in"]
            left_cost = q["sol_in"] * (q["tokens_left"] / q["tokens"])
            return (self._exit_value(q, pxn) / left_cost - 1) * 100 if left_cost else 0.0
        hold_on = getattr(self.cfg, "pump_hold_until_profit", True)
        lim = float(self._c("pump_hold_min_profit_pct", 0.0))
        lead = next((q for q in mine if not q.get("real")), None)
        if self.exact_on():                               # 0.32.160: na cópia exata a REAL decide (a fictícia tem a entrada dela)
            lead = next((q for q in mine if q.get("real")), lead)
        lead_hold = bool(lead and (lead.get("hold_profit") or (hold_on and _chg(lead) < lim)))
        for p in sorted(mine, key=lambda q: not q.get("real")):              # real primeiro
            if p.get("hold_profit"):
                continue                                  # já está segurando até ficar positivo
            if hold_on:
                chg = _chg(p)
                follow = lead is not None and p is not lead
                if (lead_hold if follow else chg < lim):
                    # trader saiu e NÓS estamos no prejuízo (já contando as taxas de saída): segura até ficar positivo
                    p["hold_profit"] = True
                    p["hold_since"] = now_iso()
                    p["hold_chg_in"] = round(chg, 2)
                    p["chg_pct"] = round(chg, 2)
                    self._save_pos(p)
                    self._feed(**base, action="segurando",
                               reason=f"trader saiu, mas a posição está {chg:+.1f}% depois das taxas — vende quando ficar positiva"
                               + (" (a real segue a fictícia)" if follow else ""))
                    out.append(f"[PUMP {'REAL' if p.get('real') else 'SIM'}] {p['symbol']}: trader saiu no prejuízo "
                               f"({chg:+.1f}%) — segurando até ficar positivo")
                    continue
            if p.get("real"):
                p["_paired_sell_t"] = t                    # a fictícia vende logo em seguida: não repete a venda real
                self._real_sell(p, frac, f"trader vendeu {frac * 100:.0f}%")
                self._feed(**base, action="REAL: vendendo", reason=f"vendendo {frac * 100:.0f}% da posição real")
                continue
            out.append(self._sell(p, frac, px or p.get("price_now"), f"trader vendeu {frac * 100:.0f}%", t))
            self._feed(**base, action="copiou venda", reason=f"vendeu {frac * 100:.0f}% da posição")
        return [m for m in out if m]

    @staticmethod
    def _sell_frac(ev: dict, tok: float, before: float) -> float:
        nb = ev.get("newTokenBalance")
        if nb is not None and tok > 0:
            frac = min(1.0, tok / (tok + float(nb)))
        elif before > 0:
            frac = min(1.0, tok / before)
        else:
            frac = 1.0
        return 1.0 if frac >= 0.97 else frac

    # 0.31.82: taxa total por lado do pool canônico da PumpSwap para tokens cotados em SOL, por valor de mercado em SOL
    # (preço × 1 bilhão). Fonte: pump.fun/docs/fees, "Last Updated: 17 October 2026", lida em 2026-10-28. Até 420 SOL
    # é 1,25% — o valor fixo antigo de 0,30% só vale acima de 98.240 SOL.
    SWAP_FEE_TABLE = ((420, 1.25), (1470, 1.20), (2460, 1.15), (3440, 1.10), (4420, 1.05), (9820, 1.00), (14740, 0.95),
                      (19650, 0.90), (24560, 0.85), (29470, 0.80), (34380, 0.75), (39300, 0.70), (44210, 0.65),
                      (49120, 0.60), (54030, 0.55), (58940, 0.525), (63860, 0.50), (68770, 0.475), (73681, 0.45),
                      (78590, 0.425), (83500, 0.40), (88400, 0.375), (93330, 0.35), (98240, 0.325))

    @classmethod
    def swap_fee_official(cls, mcap_sol: float | None) -> float | None:
        if not mcap_sol or mcap_sol <= 0:
            return None
        for hi, fee in cls.SWAP_FEE_TABLE:
            if mcap_sol < hi:
                return fee
        return 0.30

    def _fee_rates(self, mint: str, real: bool = False) -> dict:
        """Taxas REAIS por lado: pump.fun na curva 1,25% (0,95% pump.fun + 0,30% criador) ou PumpSwap ~0,30% depois
        de graduar; PumpPortal 0,5% (API que o modo real usa); priority fee fixa por transação."""
        tk = self.tokens.get(mint) or {}
        if not self.is_pump(mint):                     # fora da pump.fun: DEX via Jupiter, sem PumpPortal
            return {"venue": float(self._c("pump_other_fee_pct", 0.30)) / 100,
                    "venue_name": "DEX " + str(tk.get("main_dex") or "Jupiter"), "portal": 0.0,
                    "prio": float(self._c("pump_priority_sol", 0.0005)),
                    "slip": float(self._c("pump_other_slip_pct", 1.0)) / 100}
        dexes = set(tk.get("dexes") or [])
        graduated = tk.get("pool") in ("pump-amm", "pumpswap") or ("pumpswap" in dexes)
        venue = float(self._c("pump_swap_fee_pct", 0.30) if graduated else self._c("pump_fee_pct", 1.25)) / 100
        # 0.32.0 (pedido do dono): a tabela oficial vale só para a FICTÍCIA (testes); a real usa o valor do campo
        if graduated and not real and self._c("pump_swap_fee_official", False) and tk.get("quote") in (None, "SOL"):
            # cotado em USDC/outra moeda segue o valor do campo (a tabela abaixo é só a de SOL)
            px = tk.get("price")
            off = self.swap_fee_official(px * 1e9 if px else tk.get("mcap_sol"))
            if off is not None:
                venue = off / 100
        return {"venue": venue, "venue_name": "PumpSwap" if graduated else "pump.fun (curva)",
                "portal": float(self._c("pump_portal_fee_pct", 0.5)) / 100,
                "prio": float(self._c("pump_priority_sol", 0.0005)),
                # 0.32.335: o padrão novo de 1,5% é só para a fictícia; a posição REAL de quem está nesse padrão continua estimada com
                # os 3% de antes. Valor escolhido pela pessoa vale igual nas duas, como sempre.
                "slip": self._slip_pct(real) / 100}

    def _slip_pct(self, real: bool = False) -> float:
        v = float(self._c("pump_extra_slip_pct", 3.0))
        return 3.0 if real and v == float(USER_KEYS["pump_extra_slip_pct"][1]) and v < 3.0 else v

    def _exit_value(self, p: dict, px: float) -> float:
        """Quanto entraria vendendo agora, já com TODAS as taxas de saída (plataforma, PumpPortal, rede, slippage)."""
        fr = self._fee_rates(p["mint"], bool(p.get("real")))
        return max(0.0, p["tokens_left"] * px * (1 - fr["slip"]) * (1 - fr["venue"] - fr["portal"]) - fr["prio"])

    @staticmethod
    def _addfee(p: dict, **kw) -> None:
        fp = p.setdefault("fee_parts", {"platform": 0.0, "portal": 0.0, "network": 0.0, "slippage": 0.0})
        for k, v in kw.items():
            fp[k] = fp.get(k, 0.0) + v

    def _sell(self, p: dict, frac: float, px: float | None, why: str, t: float, from_real: bool = False) -> str | None:
        if p.get("real"):
            if not self._real_sell(p, frac, why):
                return None                                # já vendendo ou esperando depois de uma falha (0.32.62)
            return f"[PUMP REAL] {p['symbol']}: vendendo {frac * 100:.0f}% ({why})"
        if not px:
            return None
        if not from_real and self._waits_real(p):
            # 0.31.47 (pedido do dono: "com a real ativada a prioridade de entrada e saída é da real"): a compra real
            # desta posição ainda está saindo; a fictícia não sai antes dela. A saída fica guardada e acontece assim
            # que a real confirmar (ou desistir), junto com a venda real.
            if p.get("exit_wait"):
                return None
            p["exit_wait"] = {"frac": frac, "why": why}
            self._save_pos(p)
            return f"[PUMP SIM] {p['symbol']}: saída ({why}) espera a compra REAL confirmar — a real tem prioridade"
        full = frac >= 1.0 or p["tokens_left"] * (1 - frac) <= p["tokens"] * 0.005
        tw = [] if from_real else self.real_twins(p)
        # 0.32.400 (dono, HELI 20/11 23:58: "a real tem que entrar primeiro… e sair quando for para sair"): no BOOST com a REAL
        # seguindo a fictícia, a REAL vende primeiro e a fictícia acompanha no preço que a REAL conseguiu (como a cópia exata)
        bm_pair = p.get("origem") == "boostmig" and not p.get("real") and any(not r.get("bm_own") and r.get("sim_id") == p["id"] for r in tw)
        exact = (self.exact_on() or bm_pair) and not from_real
        for rp in tw:                                    # 0.31.47/0.32.156: a venda real sai primeiro
            if rp.get("selling") or rp.get("_paired_sell_t") == t:
                continue
            if why.startswith("venda em partes"):
                if rp.get("tp1_done") and not full:
                    continue
                rp["tp1_done"] = True                    # a parte da real sai junto e não repete depois pelo preço dela
            if full:
                self._real_sell(rp, 1.0, f"espelho do fictício: {why}" if rp.get("sim_id") == p["id"] else f"junto com a fictícia: {why}")
            elif exact or why.startswith("venda em partes"):
                self._real_sell(rp, frac, f"junto com a fictícia: {why}")
        if exact and tw:
            # 0.32.160 (pedido do dono: "a real sempre prioridade antes em todas as ações"): na cópia exata a fictícia NÃO sai
            # antes; fica esperando a venda real confirmar e sai no mesmo preço que a real conseguiu (ver _sim_follow)
            if p.get("exit_follow"):
                return None
            p["exit_follow"] = {"frac": frac, "why": why, "t": t}
            self._save_pos(p)
            return f"[PUMP SIM] {p['symbol']}: saída ({why}) espera a venda REAL — a real tem prioridade"
        pre = {"tokens": p["tokens_left"], "proceeds": p.get("proceeds", 0.0)}      # 0.32.332: a sombra parte daqui
        fr = self._fee_rates(p["mint"])
        slip, prio = fr["slip"], fr["prio"]
        fee = fr["venue"] + fr["portal"]
        qty = p["tokens_left"] * frac
        price_out = px * (1 - slip)
        gross_out = qty * price_out
        got = gross_out * (1 - fee) - prio
        p["tokens_left"] -= qty
        p["proceeds"] = p.get("proceeds", 0.0) + got
        p["fees_sol"] = p.get("fees_sol", 0.0) + gross_out * fee + prio
        self._addfee(p, platform=gross_out * fr["venue"], portal=gross_out * fr["portal"], network=prio,
                     slippage=qty * px * slip)
        p["price_now"] = px
        p.setdefault("sells", []).append({"at": now_iso(), "frac": round(frac, 4), "price": price_out, "sol": round(got, 6),
                                          "why": why})
        if p["tokens_left"] <= p["tokens"] * 0.005 or frac >= 1.0:
            pnl = p["proceeds"] - p["sol_in"]
            tr = {"opened_at": p["opened_at"], "closed_at": now_iso(), "wallet": p["wallet"], "mint": p["mint"],
                  "symbol": p["symbol"], "sol_in": p["sol_in"], "sol_out": round(p["proceeds"], 6),
                  "pnl_sol": round(pnl, 6), "pnl_pct": round(pnl / p["sol_in"] * 100, 2), "price_in": p["price_in"],
                  "sim_entry_px": (p.get("sim_entry") or {}).get("price_in") or p["price_in"],
                  "price_out": price_out, "fees_sol": round(p["fees_sol"], 6), "reason": why,
                  "fee_parts": {k: round(v, 6) for k, v in (p.get("fee_parts") or {}).items()},
                  "gross_sol": round(pnl + p["fees_sol"], 6),       # resultado antes das taxas (já com slippage)
                  "venue": p.get("venue_in"),
                  "hold_s": round(t - p.get("open_t", t)), "sells": p.get("sells", []), "real": bool(p.get("real")),
                  "mcap_in": p.get("mcap_in"), "mcap_out": (self.tokens.get(p["mint"]) or {}).get("mcap_sol")}
            tr["lag_s"] = p.get("lag_s")
            tr["best_pct"], tr["worst_pct"] = p.get("best_pct"), p.get("worst_pct")
            tr["score"] = p.get("score")
            tr["score_parts"] = p.get("score_parts")       # 0.32.117: cérebro em sombra mede pressão, curva e criador na entrada
            tr["trader_px"] = p.get("trader_px") or p.get("trader_price")
            tr["late"] = p.get("late")                     # 0.32.124: preço do mercado 5/15/30 s depois da cópia
            tr["manual"] = bool(p.get("manual")) or p.get("wallet") == "manual"
            if p.get("auto") is True and p.get("origem") in AUTO_ORIGINS:
                tr.update(id=p["id"], auto=True, origem=p["origem"], auto_info=copy.deepcopy(p.get("auto_info") or {}),
                          closed_t=t, closed_at=datetime.fromtimestamp(t, timezone.utc).isoformat(), exit_price=px)
            tr["pos_id"] = p["id"]                         # 0.31.38: par real × fictícia (espelho)
            tr["entrou_porque"] = self.entry_why(p)         # 0.32.60: motivo da entrada guardado junto com o da saída
            if self.sign_out(p):
                tr["sinal"] = self.sign_out(p)              # 0.32.423: tempo no positivo × negativo
            self._sg_trade(p, tr, pre, px, why, t)          # 0.32.332: stop de ganho (e a sombra, quando foi ele que vendeu)
            if p.get("follow_of"):
                tr["follow_of"] = p["follow_of"]           # 0.31.63: cópia de outra conta não entra no aprendizado geral
            if p.get("origem") and "origem" not in tr:
                tr["origem"] = p["origem"]                 # 0.32.21: ex.: "barrado"
            if p.get("eq"):
                tr["eq"] = True                            # 0.32.4: Copiar igual
            self._post_open(p, tr, px, t)                  # 0.32.33: segue o preço 15/30/60 min depois da saída
            tr["api"] = self.api_used(p)                  # 0.32.220: gasto das APIs com esta moeda
            self._save_trade(tr)
            self._del_pos(p)
            self._after_close(tr)
            self._lead("close", p, why)
            src = self.aba_of(p) if p.get("wallet") == "manual" or p.get("manual") else f"{self.aba_of(p)} · {short(p['wallet'])}"
            return (f"[PUMP SIM] fechou {p['symbol']} copiado de {src} ({why}) → "
                    f"{pnl:+.4f} SOL ({tr['pnl_pct']:+.1f}%)")
        self._save_pos(p)
        return f"[PUMP SIM] {p['symbol']}: vendeu {frac * 100:.0f}% ({why}) → {got:.4f} SOL"

    def real_twins(self, p: dict) -> list[dict]:
        """0.32.156: posições REAIS que andam junto com esta fictícia: o par do espelho (sim_id) e, sem espelho, a real do
        mesmo token copiada do mesmo trader."""
        if p.get("real"):                    # a venda real não depende da chave da execução real (0.32.103)
            return []
        mirror = getattr(self.cfg, "pump_real_mirror", True)
        bm = p.get("origem") == "boostmig"
        return [rp for rp in self.positions() if rp.get("real") and rp["mint"] == p["mint"]
                and ((mirror and rp.get("sim_id") == p["id"])
                     or (bm and rp.get("origem") == "boostmig" and not rp.get("bm_own"))   # 0.32.387 (0.32.394: menos com regras próprias)
                     or (not rp.get("sim_id") and rp.get("wallet") == p.get("wallet") and p.get("wallet") not in (None, "manual")))]

    def bm_follows_sim(self, rp: dict) -> bool:
        """0.32.387 (pedido do dono: "a real segue 100% a fictícia no BOOST"): REAL do BOOST com a fictícia do mesmo token aberta
        não decide nada sozinha (stop, stop móvel, venda em partes, fim do BOOST, tempo): só vende quando a fictícia vende."""
        # 0.32.394: com "REAL usa regras próprias" (pump_bmr_on) a REAL do BOOST tem stop e saída dela (gravados na posição)
        return bool(rp.get("real") and rp.get("origem") == "boostmig" and getattr(self.cfg, "pump_bm_real_follow", True)
                    and not rp.get("bm_own") and any(not x.get("real") and x["mint"] == rp["mint"] and x.get("origem") == "boostmig" for x in self.positions()))

    def _waits_real(self, p: dict) -> bool:
        """Fictícia com a compra REAL do espelho ainda saindo (real ligada): a real tem prioridade (0.31.47)."""
        if p.get("real") or not getattr(self.cfg, "pump_real_mirror", True) or not getattr(self.cfg, "pump_real_enabled", False):
            return False
        if p["mint"] not in self._real_buying:
            return False
        return not any(x.get("real") and x.get("sim_id") == p["id"] for x in self.positions())

    def _align_to_real(self, real: dict) -> None:
        """0.31.47: a fictícia par passa a ter a MESMA entrada da real (hora e preço efetivo, já com taxas), para as duas
        andarem juntas e saírem pelas mesmas regras no mesmo momento. Só antes de qualquer venda parcial."""
        sim = next((x for x in self.positions() if x["id"] == real.get("sim_id") and not x.get("real")), None)
        if not sim or sim.get("sells") or not sim.get("tokens") or not real.get("tokens"):
            return
        sim_eff, real_eff = sim["sol_in"] / sim["tokens"], real["sol_in"] / real["tokens"]
        k = real_eff / sim_eff if sim_eff else 0
        if not k or (not 0.2 <= k <= 5 and not self.exact_on()):   # leitura estranha da real: não mexe na fictícia
            return
        if not 0.2 <= k <= 5:
            # 0.32.214 (MEOWTH do dono, 05/11: fictícia entrou a 1,19e-9 e a REAL a 3,9e-7, 328×; a fictícia "ganhou" +7.027%):
            # na cópia exata o preço que a REAL pagou é a verdade, então a fictícia é corrigida mesmo com diferença grande, e o
            # pico/stop móvel calculados com o preço errado são apagados
            for k_ in ("trail_peak", "trail_exit", "trail_since", "best_pct", "worst_pct", "_chk", "sus_noted"):
                sim.pop(k_, None)
            self._feed(wallet=sim.get("wallet") or "manual", short=short(sim.get("wallet") or "manual"), mint=sim["mint"],
                       symbol=sim.get("symbol"), kind="buy", action="preço corrigido",
                       reason=f"a fictícia tinha entrado num preço {max(k, 1 / k):.0f}× diferente do que a REAL pagou; ficou o preço da REAL")
        sim.setdefault("sim_entry", {"open_t": sim.get("open_t"), "opened_at": sim.get("opened_at"), "price_in": sim.get("price_in")})
        sim["tokens"] = sim["tokens"] / k
        sim["tokens_left"] = sim["tokens_left"] / k
        sim["price_in"] = (sim.get("price_in") or 0) * k
        sim["open_t"], sim["opened_at"] = real["open_t"], real["opened_at"]
        if self.exact_on() and sim.get("sol_in") and real.get("sol_in"):
            # 0.32.158: cópia exata também no valor — a fictícia passa a ter o mesmo SOL da real (resultado igual em SOL e em %)
            f = real["sol_in"] / sim["sol_in"]
            for k in ("sol_in", "tokens", "tokens_left", "fees_sol"):
                if sim.get(k) is not None:
                    sim[k] = sim[k] * f
            sim["fee_parts"] = {k: v * f for k, v in (sim.get("fee_parts") or {}).items()}
        sim["entrou_com_a_real"] = True
        self._save_pos(sim)
        if sim.get("auto") is True and sim.get("origem") in AUTO_ORIGINS:
            self._auto_record(sim, False)

    def _bm_open_sim(self, mint: str) -> None:
        """0.32.400 (pedido do dono: "a real tem que entrar primeiro"): no BOOST com a REAL ligada a compra REAL sai primeiro; quando
        ela termina (comprou ou não), a fictícia entra. Se a REAL comprou, a fictícia fica com a mesma entrada (hora e preço da
        REAL) e as duas passam a sair juntas, a REAL primeiro."""
        args = (getattr(self, "bm_sim_after", None) or {}).pop(mint, None)
        if not args:
            return
        try:
            r = self.manual_buy(mint, t=time.time(), auto=args.get("auto") or "BOOST da migração", origem="boostmig", target="sim",
                                amt_sol=args.get("amt_sol"), pos_rules=args.get("pos_rules"))
        except Exception as e:
            log.warning("BOOST: fictícia depois da REAL não abriu: %s", str(e)[:120])
            return
        sim = next((x for x in self.positions() if x["mint"] == mint and not x.get("real") and x.get("origem") == "boostmig"), None)
        rp = next((x for x in self.positions() if x["mint"] == mint and x.get("real") and x.get("origem") == "boostmig"
                   and not x.get("bm_own") and x.get("sim_id") is None), None)
        if sim and rp:
            rp["sim_id"] = sim["id"]
            self._save_pos(rp)
            self._align_to_real(rp)
        if not sim:
            self.bm_sim_note = dict(getattr(self, "bm_sim_note", None) or {}, **{mint: str(r.get("sim") or "não abriu")})

    def _release_sim_exit(self, sim_id) -> None:
        """Executa a saída da fictícia que esperava a compra real (confirmou ou desistiu)."""
        sim = next((x for x in self.positions() if x["id"] == sim_id and not x.get("real")), None)
        if not sim or not sim.get("exit_wait"):
            return
        ew = sim.pop("exit_wait")
        px = (self.tokens.get(sim["mint"]) or {}).get("price") or sim.get("price_now")
        msg = self._sell(sim, float(ew.get("frac") or 1.0), px, ew.get("why") or "saída", time.time())
        if msg:
            self._emit(msg)

    def _note_suspect_price(self, mint: str, px) -> None:
        """0.31.51 (Jewlon, 27/10: a real fechou em "alvo (+150%)" com −13% e "melhor momento" +7.612%): preço 20× acima da
        entrada é quase sempre leitura errada (curva da pump.fun cotada em outro token, não em SOL). Aqui só ANOTA no feed,
        uma vez por posição, para o relatório do dia e o aprendizado contarem; nenhuma regra de compra/venda muda."""
        if not px:
            return
        for p in self.positions():
            if p["mint"] != mint or p.get("sus_noted") or not p.get("price_in"):
                continue
            x = px / p["price_in"]
            if x >= 20:
                p["sus_noted"] = True
                self._save_pos(p)
                self._feed(wallet=p.get("wallet") or "manual", short=short(p.get("wallet") or "manual"), mint=mint, symbol=p.get("symbol"),
                           kind="sell", action="preço suspeito", real=bool(p.get("real")),
                           reason=f"preço {x:,.0f}× a entrada em {'posição REAL' if p.get('real') else 'posição fictícia'} — provável leitura errada (token cotado em outra moeda)")

    @staticmethod
    def _sign_note(p: dict, px: float, t: float) -> None:
        """0.32.423 (pedido do dono, 21/11): soma, a cada leitura de preço, quanto tempo a posição ficou no POSITIVO e no
        NEGATIVO (preço acima/abaixo do preço de entrada, sem taxas) e quantas vezes trocou. O trecho entre duas leituras fica
        com o estado da leitura anterior. Vai para o trade quando fecha."""
        # 0.32.424: referência = preço de mercado na entrada (trader_px), sem a taxa embutida no price_in; senão o começo da
        # posição contava como negativo só por causa da taxa
        ref = float(p.get("trader_px") or p.get("trader_price") or 0) or float(p.get("price_in") or 0)
        if not ref or not px or px <= 0:
            return
        g = p.setdefault("sinal", {"pos_s": 0.0, "neg_s": 0.0, "trocas": 0})
        up = px >= ref
        last_t, last_up = g.get("t"), g.get("up")
        if last_t is not None and t > last_t:
            g["pos_s" if last_up else "neg_s"] = round(float(g.get("pos_s" if last_up else "neg_s") or 0) + (t - last_t), 1)
        if last_up is not None and up != last_up:
            g["trocas"] = int(g.get("trocas") or 0) + 1
        if up:
            g.pop("neg_since", None)                   # 0.32.426: início do trecho negativo atual (para o "sem trocar")
        elif last_up is not False or g.get("neg_since") is None:
            g["neg_since"] = t
        g["t"], g["up"] = t, up

    def _tneg_check(self, p: dict, t: float) -> None:
        """0.32.426 (pedido do dono, 21/11): stop por tempo no negativo. Quando a posição SOMA `sum_s` no negativo (todas as
        trocas) ou fica `streak_s` SEGUIDOS no negativo sem voltar ao positivo, o stop de perda (padrão 25%) é ligado nela —
        se o preço já estiver abaixo, vende na próxima leitura. Só arma uma vez."""
        r, g = p.get("bm_tneg") or {}, p.get("sinal") or {}
        neg = float(g.get("neg_s") or 0)
        streak = (t - float(g["neg_since"])) if (g.get("up") is False and g.get("neg_since") is not None) else 0.0
        why = None
        if r.get("sum_s") and neg >= float(r["sum_s"]):
            why = f"{neg:.0f} s no negativo somando as trocas (limite {float(r['sum_s']):.0f} s)"
        elif r.get("streak_s") and streak >= float(r["streak_s"]):
            why = f"{streak:.0f} s seguidos no negativo sem voltar ao positivo (limite {float(r['streak_s']):.0f} s)"
        if not why:
            return
        stop = float(r.get("stop") or 25)
        cur = float(p.get("stop_pct") or 0)
        p["bm_tneg_why"] = why
        if cur <= 0 or cur > stop:
            p["stop_pct"] = stop
        self._save_pos(p)
        self._feed(wallet=p.get("wallet") or "manual", short=short(p.get("wallet") or "manual"), mint=p["mint"], symbol=p.get("symbol"),
                   kind="sell", action="stop por tempo armado", real=bool(p.get("real")),
                   reason=f"{why}: stop de perda de {float(p.get('stop_pct') or stop):.0f}% ligado")

    @staticmethod
    def sign_out(p: dict) -> dict | None:
        g = p.get("sinal") or {}
        if g.get("t") is None:
            return None
        pos, neg = float(g.get("pos_s") or 0), float(g.get("neg_s") or 0)
        return {"pos_s": round(pos), "neg_s": round(neg), "trocas": int(g.get("trocas") or 0),
                "neg_pct": round(neg / (pos + neg) * 100) if pos + neg else None}

    def _late_note(self, p: dict, px: float, t: float) -> None:
        """0.32.124: a cópia fictícia entra no preço do próprio trader, o que é otimista. Guarda o preço do mercado 5/15/30 s depois.
        Só registra: não muda entrada, saída nem resultado. Leitura muito atrasada fica vazia, em vez de valer como preço daquela marca."""
        if p.get("real") or p.get("manual") or p.get("wallet") == "manual" or not p.get("open_t"):
            return
        late, age, mudou = p.setdefault("late", {}), t - float(p["open_t"]), False
        for s in (5, 15, 30):
            if str(s) not in late and age >= s:
                late[str(s)] = px if age <= s + 20 else None
                mudou = True
        if mudou:
            self._save_pos(p)

    # 0.32.127 (pedido do dono: focar em uma aba): a chave geral da cópia também para o Copiar igual, então estas duas abas ganharam chave própria
    TAB_SWITCH = {"Top traders": "pump_top_on", "Carteiras em estudo": "pump_st_copy_on", "Estudo · deram lucro": "pump_st_lucro_on"}

    def tab_off(self, who: str) -> str | None:
        aba = self.aba_of({"wallet": who})
        key = self.TAB_SWITCH.get(aba)
        if not key or getattr(self.cfg, key, True):
            return None
        # 0.32.222 (dono, PODCAT 05/11: o Bruxo copiou e ele não): carteira que você mesmo pôs na lista manual, ou que está no top
        # ativo, também estava em Carteiras em estudo; a chave do estudo desligada barrava a cópia. Agora vale a chave do Top traders.
        if aba != "Top traders" and getattr(self.cfg, "pump_top_on", True) and (
                who in (getattr(self, "top_active", None) or []) or (who in (getattr(self, "manual", None) or []) and who not in (getattr(self, "ia_added", None) or []))):
            return None
        return f"aba {aba} desligada"

    def _top_barred(self, who: str, mint: str, why: str, t: float) -> None:
        if self.top_hook is not None and why and not why.startswith(("já tem posição", "aba ", "cópia desligada")):
            self.top_hook(who, mint, (self.tokens.get(mint) or {}).get("symbol"), why, t)

    def _check_stops(self, mint: str, t: float) -> list[str]:
        out = []
        px = (self.tokens.get(mint) or {}).get("price")
        stop, tp = float(self._c("pump_stop_pct", 40)), float(self._c("pump_tp_pct", 0))
        if px and self.ghosts.open:
            self.ghosts.on_price(mint, px, t)
        if px and self.ghosts_auto.open:
            self.ghosts_auto.on_price(mint, px, t)
        if px and self.sg_sombra.abertas:                   # 0.32.332: o que teria acontecido sem o stop de ganho
            self.sg_sombra.preco(mint, px, t)
        self._note_suspect_price(mint, px)
        for p in sorted([p for p in self.positions() if p["mint"] == mint], key=lambda q: not q.get("real")):   # 0.32.160: real primeiro
            if px:
                self._sign_note(p, px, t)                  # 0.32.423: tempo no positivo × negativo (REAL e fictícia)
                if p.get("bm_tneg") and not p.get("bm_tneg_why"):
                    self._tneg_check(p, t)
            if self.bm_follows_sim(p):                     # 0.32.387: a REAL do BOOST não tem regra própria; segue a fictícia
                # 0.32.463 (dono: "positivo × negativo sem medição" nas REAIS do BOOST): a posição vem como CÓPIA da memória;
                # sem gravar, o tempo no positivo × negativo, o melhor e o pior momento da REAL se perdiam a cada leitura
                if px and p.get("tokens") and not p.get("selling"):
                    left_cost = p["sol_in"] * (p["tokens_left"] / p["tokens"])
                    if left_cost:
                        chg = (self._exit_value(p, px) / left_cost - 1) * 100
                        p["price_now"], p["chg_pct"] = px, round(chg, 2)
                        p["best_pct"] = round(max(chg, p.get("best_pct", chg)), 2)
                        p["worst_pct"] = round(min(chg, p.get("worst_pct", chg)), 2)
                    self._save_pos(p)
                continue
            if not px or p.get("selling"):
                continue
            if p.get("exit_follow") and not p.get("real"):
                # 0.32.160: fictícia esperando a venda real (cópia exata). Sem a real (vendida por fora), sai pelo preço de agora;
                # com a real parada depois de uma falha, pede a venda de novo (respeita a espera entre tentativas)
                ef, tw = p["exit_follow"], self.real_twins(p)
                if not tw:
                    p.pop("exit_follow", None)
                    out.append(self._sell(p, float(ef.get("frac") or 1.0), px, ef.get("why") or "saída", t, from_real=True))
                elif not any(r.get("selling") for r in tw):
                    for r in tw:
                        self._real_sell(r, float(ef.get("frac") or 1.0), f"junto com a fictícia: {ef.get('why') or 'saída'}")
                continue
            self._late_note(p, px, t)
            dfix = (self.tokens.get(mint) or {}).get("dec_fix_t")
            if dfix and float(p.get("dec_fix_t") or 0) < dfix:
                # 0.32.65: o preço desta posição vinha com as casas decimais erradas; pico e stop móvel eram falsos
                p["dec_fix_t"] = dfix
                had = p.get("trail_peak")
                for k_ in ("trail_peak", "trail_exit", "trail_since", "best_pct", "worst_pct", "_chk", "sus_noted",
                           "sell_error", "sell_fails", "sell_retry_at"):
                    p.pop(k_, None)
                self._save_pos(p)
                self._feed(wallet=p.get("wallet") or "manual", short=short(p.get("wallet") or "manual"), mint=mint,
                           symbol=p.get("symbol"), kind="sell", action="preço corrigido", real=bool(p.get("real")),
                           reason="o preço era lido com as casas decimais erradas"
                                  + (f"; o pico falso de {had:+.0f}% do stop móvel foi apagado" if had is not None else ""))
            if p.get("sell_error") and t - float(p.get("sell_retry_at") or 0) > 900:
                # 0.32.67 (PEPE, 29/10 21:47): a venda que falhou não é mais tentada há 15 min (o motivo da saída sumiu,
                # ex.: pico falso apagado) — o erro antigo saía do card
                for k_ in ("sell_error", "sell_fails", "sell_retry_at"):
                    p.pop(k_, None)
                self._save_pos(p)
            p["price_now"] = px
            left_cost = p["sol_in"] * (p["tokens_left"] / p["tokens"])
            val = self._exit_value(p, px)
            chg = (val / left_cost - 1) * 100 if left_cost else 0
            prev = p.get("_chk")                           # 0.32.61: leitura anterior (para explicar stop que passou do limite)
            p["_chk"] = (t, round(chg, 2), float((self.tokens.get(mint) or {}).get("last_t") or t))
            p["chg_pct"] = round(chg, 2)
            # pós-trade (0.18.0): melhor e pior momento da posição, para ver quanto ficou na mesa
            p["best_pct"] = round(max(chg, p.get("best_pct", chg)), 2)
            p["worst_pct"] = round(min(chg, p.get("worst_pct", chg)), 2)
            self._sg_marcas(p, chg, t)
            own_auto = p.get("auto") is True and p.get("origem") in AUTO_ORIGINS
            max_hold = self._auto_num(p.get("max_hold_s"))
            if max_hold is not None and t - p.get("open_t", t) >= max_hold:
                out.append(self._sell(p, 1.0, px, p.get("hold_why") or f"tempo máximo ({max_hold / 60:g} min)", t))   # 0.32.373: BOOST
                continue
            # 0.32.19: posições com regras próprias (botão Comprar, automáticas, Copiar igual) não usam as regras novas das cópias
            own_rules = own_auto or bool(p.get("manual")) or p.get("stop_pct") is not None or bool(p.get("eq"))
            ts_on = getattr(self.cfg, "pump_timestop_on", False) and not own_rules
            if ts_on and t - p.get("open_t", t) >= float(self._c("pump_timestop_s", 180)):
                gain = float(self._c("pump_timestop_gain_pct", 0))
                if float(p.get("best_pct", chg)) < gain:
                    out.append(self._sell(p, 1.0, px, f"stop por tempo: {float(self._c('pump_timestop_s', 180)):.0f} s sem passar de {gain:+.0f}% ({chg:+.1f}% líquido)", t))
                    continue
            if p.get("eq"):                                # 0.32.4: Copiar igual sai só quando a carteira vende
                eqs = float(self._c("pump_eq_stop_pct", 0) or 0)
                if eqs and chg <= -eqs:
                    out.append(self._sell(p, 1.0, px, f"copiar igual: stop do modo (-{eqs:.0f}%)", t))
                else:
                    self._save_pos(p)
                continue
            # STOP MÓVEL: liga quando o líquido (após taxas) passa de X%; depois sai se cair Y pontos do pico
            trail_on = p["trail_on"] if "trail_on" in p else getattr(self.cfg, "pump_trail_enabled", True)
            trail_on = trail_on and not p.get("off_trail")          # 0.31.87 (Bruxo): desligado nesta posição
            t_start = float(p.get("trail_start") or self._c("pump_trail_start_pct", 20))
            t_dist = float(p.get("trail_dist") or self._c("pump_trail_dist_pct", 10))
            sp = p.get("stop_pct")                         # 0.26.0: compra do botão / automáticas têm o seu
            stop = float(sp) if sp is not None else float(self._c("pump_stop_pct", 40))
            no_stop = sp is not None and float(sp) == 0     # 0.32.35 (pedido do dono): stop 0 = sem stop de perda
            tp = float(p["tp_pct"]) if p.get("tp_pct") is not None else float(self._c("pump_tp_pct", 0))
            if trail_on and (p.get("trail_peak") is not None or chg >= t_start):
                if p.get("trail_peak") is None:
                    p["trail_since"] = now_iso()
                p["trail_peak"] = round(max(chg, p.get("trail_peak") or chg), 2)
                p["trail_exit"] = round(max(p["trail_peak"] - t_dist, float(self._c("pump_trail_min_lock_pct", 2))), 2)
                if p.get("trail_rel"):                     # 0.32.96 (Jev Trade): sai X% abaixo do PICO do preço, não X pontos
                    rel = float(p["trail_rel"]) / 100
                    p["trail_exit"] = round(max(((1 + p["trail_peak"] / 100) * (1 - rel) - 1) * 100,
                                                float(self._c("pump_trail_min_lock_pct", 2))), 2)
            tp1 = float(p["tp1_pct"]) if p.get("tp1_pct") is not None else self._onv("pump_tp1_on", "pump_tp1_pct")
            prog = None
            cx = self._onv("pump_curve_exit_on", "pump_curve_exit_pct")
            if cx and getattr(self.cfg, "pump_cx_copies_only", False) and (own_auto or p.get("manual") or p.get("origem")):
                cx = 0                                     # 0.32.59: só nas cópias de traders
            if p.get("cx_pct"):
                cx = float(p["cx_pct"])                    # 0.32.59: regra da própria posição (Aba do Bruxo)
            if cx and self.is_pump(mint) and not self.graduated(mint):
                prog = self.curve_progress((self.tokens.get(mint) or {}).get("mcap_sol"))
            if cx and prog is not None and prog >= cx:
                out.append(self._sell(p, 1.0, px, f"saiu antes da graduação (curva em {prog:.0f}%, {chg:+.1f}% líquido)", t))
                continue
            smart = self.smart_exit(p, t, force=p.get("smart") is True)
            if smart:
                out.append(self._sell(p, 1.0, px, f"{smart} ({chg:+.1f}% líquido)", t))
                continue
            # 0.32.332 (pedido do dono, 13/11/2026: "ganhou 10% saiu fora"): stop de ganho autônomo. O nível de cada aba vem do
            # histórico (stopganho.decidir); antes do alvo antigo, da venda em partes e do stop móvel, que só ligava em +25%.
            sgn = self.sg_level(p)
            if sgn is not None and chg >= sgn:
                out.append(self._sell(p, 1.0, px, f"{stopganho.MOTIVO}: +{sgn:g}% ({chg:+.1f}% líquido)", t))
                continue
            # Saltos diretos ao alvo/Boost encerram a automática inteira, sem começar por uma parcial.
            if own_auto and p.get("boost_tp") and chg >= float(p["boost_tp"]) and self.boost_info(mint).get("active"):
                out.append(self._sell(p, 1.0, px, f"boost ON: alvo +{float(p['boost_tp']):.0f}% ({chg:+.1f}% líquido)", t))
                continue
            if own_auto and tp and chg >= tp:
                out.append(self._sell(p, 1.0, px, f"alvo (+{tp:.0f}%)", t))
                continue
            if tp1 and not p.get("off_tp1") and not p.get("tp1_done") and chg >= tp1 and p["tokens_left"] > p["tokens"] * 0.05:
                p["tp1_done"] = True
                frac = float(p["tp1_frac"]) if p.get("tp1_frac") is not None else float(self._c("pump_tp1_frac_pct", 50))
                frac /= 100
                out.append(self._sell(p, frac, px, f"venda em partes: realizou {frac * 100:.0f}% em {chg:+.1f}% líquido", t))
                continue
            # 0.32.19 (Configuração do Trader): 2º alvo, só nas cópias (posições com regras próprias não têm)
            tp2 = 0.0 if own_rules else float(self._c("pump_tp2_pct", 0) or 0)
            if (tp2 and tp1 and p.get("tp1_done") and not p.get("off_tp1") and not p.get("tp2_done") and chg >= tp2
                    and p["tokens_left"] > p["tokens"] * 0.05):
                p["tp2_done"] = True
                want = float(self._c("pump_tp2_frac_pct", 25)) / 100 * p["tokens"]        # % da posição original
                frac = min(1.0, want / p["tokens_left"]) if p["tokens_left"] else 1.0
                out.append(self._sell(p, frac, px, f"2º alvo: realizou {float(self._c('pump_tp2_frac_pct', 25)):.0f}% da posição em {chg:+.1f}% líquido", t))
                continue
            if trail_on and p.get("trail_peak") is not None and chg <= p["trail_exit"]:
                out.append(self._sell(p, 1.0, px, f"stop móvel (pico {p['trail_peak']:+.1f}% → saiu em {chg:+.1f}% líquido)", t))
            elif (p.get("be_after") and not p.get("off_stop") and float(p.get("best_pct") or 0) >= float(p["be_after"])
                  and chg <= 0):                           # 0.32.96 (Jev Trade): depois de +X% o stop vira 0% (empate)
                out.append(self._sell(p, 1.0, px, f"empate: passou de +{float(p['be_after']):.0f}% e voltou a {chg:+.1f}%", t))
            elif p.get("hold_profit") and chg > float(self._c("pump_hold_min_profit_pct", 0.0)):
                out.append(self._sell(p, 1.0, px, f"segurou até ficar positivo ({chg:+.1f}% líquido)", t))
            elif chg <= -stop and not p.get("off_stop") and not no_stop:
                out.append(self._sell(p, 1.0, px, f"stop de perda (−{stop:.0f}%)" + self._stop_gap(prev, chg, stop, t, mint), t))
            elif p.get("boost_tp") and chg >= float(p["boost_tp"]) and self.boost_info(mint).get("active"):
                out.append(self._sell(p, 1.0, px, f"boost ON: alvo +{float(p['boost_tp']):.0f}% ({chg:+.1f}% líquido)", t))
            elif tp and chg >= tp:
                out.append(self._sell(p, 1.0, px, f"alvo (+{tp:.0f}%)", t))
            else:
                self._save_pos(p)
        return [m for m in out if m]

    def _stop_gap(self, prev, chg: float, stop: float, t: float, mint: str) -> str:
        """0.32.61 (pedido do dono: "prejuízo de 32, 60 e 100% com stop, analisar o que aconteceu"): o stop vende no preço que
        o robô VÊ; se passou mais de 5 pontos do limite, diz no motivo de onde o preço pulou e em quanto tempo — para separar
        queda numa transação só (despejo/rug, nenhum stop segura) de preço parado (leitura atrasada)."""
        if chg > -stop - 5 or not prev:                # sem leitura anterior não há o que comparar
            return ""
        gap_s = max(0.0, t - float(prev[0]))
        age_s = max(0.0, t - float(prev[2])) if len(prev) > 2 else gap_s
        kind = "preço parado (leitura atrasada)" if age_s >= 15 else "queda de uma vez (despejo/rug: nenhum stop segura)"
        return f" · pulou de {float(prev[1]):+.0f}% para {chg:+.0f}% em {gap_s:.0f} s — {kind}"

    # ------------------------------------------------------------------ stop de ganho autônomo (0.32.332)
    # Abas em que ele não age: Copiar igual (sai só quando a carteira vende, pedido do dono na 0.32.4), Botão Comprar e as compras
    # de botão (as regras são as que você escolheu ao clicar) e Copiar trades de usuário (sai junto com a conta seguida). O Explorar
    # está dando lucro e a lógica dele não muda sem OK do dono: só com a chave própria (pump_sg_explorar).
    SG_FORA = ("Copiar igual", "Botão Comprar", "Copiar trades de usuário")
    SG_BOTAO = ("botao", "barrado_btn", "lancamento")

    def sg_level(self, p: dict) -> float | None:
        """Nível do stop de ganho desta posição (None = não age aqui). Guarda na posição o nível e de onde veio, para a tela."""
        nivel, fonte = self._sg_nivel(p)
        if p.get("sg_nivel") != nivel or p.get("sg_fonte") != fonte:
            p["sg_nivel"], p["sg_fonte"] = nivel, fonte
        return nivel

    def _sg_nivel(self, p: dict) -> tuple[float | None, str]:
        c = self.cfg
        if not getattr(c, "pump_sg_on", False):
            return None, "desligado"
        if p.get("off_sg"):
            return None, "desligado nesta posição"
        if p.get("real") and p.get("origem") != "boostmig":     # 0.32.399: no BOOST quem decide são as Regras do BOOST
            # opção nova de REAL começa desligada (regra do dono). A REAL que é par de uma fictícia (espelho) sai junto dela
            # pelas regras do espelho, então quem decide é a fictícia.
            if not getattr(c, "pump_sg_real", False):
                return None, "REAL sem stop de ganho próprio"
            if p.get("sim_id") or any(not x.get("real") and x["mint"] == p["mint"] and x.get("wallet") == p.get("wallet")
                                      for x in self.positions()):
                return None, "segue a fictícia"
        if p.get("eq") or p.get("follow_of") or p.get("origem") in self.SG_BOTAO:
            return None, "fora"
        aba = self.aba_of(p)
        if aba in self.SG_FORA:
            return None, "fora"
        if aba == "Explorar" and not getattr(c, "pump_sg_explorar", False):
            return None, "Explorar sem stop de ganho"
        if p.get("origem") == "boostmig" and p.get("bm_sg_after", getattr(c, "pump_bm_sg_after", True)) and not p.get("bm_sg_armed"):
            # 0.32.386 (pedido do dono): durante o BOOST vale o stop móvel; o autônomo só arma no fim, se estiver negativo
            return None, "BOOST: stop móvel (o autônomo só arma no fim do BOOST, se estiver negativo)"
        return stopganho.nivel_de(self.sg_decisions().get(aba), self._c("pump_sg_fixo_pct", 0))

    @staticmethod
    def sg_itens(conta, aba_of, trades, now: float) -> list[tuple]:
        """Operações FICTÍCIAS fechadas na janela, no formato do cérebro: (conta, aba, token, abertura, linha)."""
        out = []
        for t in trades:
            if t.get("real") or t.get("follow_of"):
                continue
            tf = stopganho.ts_de(t.get("closed_at"))
            if tf is None or now - tf > stopganho.JANELA_S:
                continue
            t0 = stopganho.ts_de(t.get("opened_at"))
            if str(t.get("venue") or "").startswith("DEX ") and (t0 or tf) < PumpFun.PX_FIX_T:
                continue                                   # preço de entrada errado antes da 0.32.331 (ganho falso): fora da conta
            x = {"hora": stopganho.hora_berlim(t0), "atraso": t.get("lag_s"), "mcap": t.get("mcap_in"), "nota": t.get("score")}
            r = stopganho.linha(t.get("pnl_pct"), t.get("best_pct"), tf, t.get("sg"), x)
            if r is not None:
                out.append((conta, aba_of(t), t.get("mint"), t0, r))
        return out

    def sg_decisions(self) -> dict:
        """{aba: decisão}. Com o hub, das operações de TODAS as contas (sg_pool); sem ele (testes), só desta conta."""
        if self.sg_pool is not None:
            try:
                return self.sg_pool() or {}
            except Exception as e:
                log.warning("stop de ganho: cérebro falhou: %s", str(e)[:120])
                return {}
        now, tr = time.time(), self.store.trades(100000)
        key = (len(tr), tr[0].get("id") if tr else None, sum(1 for t in tr[:50] if (t.get("sg") or {}).get("sem") is not None))
        hit = self.__dict__.get("_sg_local")
        if hit and hit[0] == key and now - hit[1] < stopganho.CACHE_S:
            return hit[2]
        rows = stopganho.dedup(self.sg_itens(getattr(self, "user_id", "local"), self.aba_of, tr, now))
        decs = stopganho.decidir_grupos(rows, antes=hit[2] if hit else None)
        self.__dict__["_sg_local"] = (key, now, decs)
        return decs

    SG_EXPLORA = 5      # 1 em cada 5 entradas numa faixa ruim passa: sem isso a faixa nunca mais teria dado e ficaria barrada para sempre

    def sg_entry_block(self, who: str, tk: dict, ev: dict, t: float, score) -> str | None:
        """0.32.335 (dono, 13/11: "você decide, só fictícia"): a entrada cai numa faixa que o cérebro marcou como ruim na aba (15+
        operações em 4+ dias, média de −5% ou pior mesmo com o alvo, até 30% chegando lá, no máximo metade da aba)? Não copia."""
        if not getattr(self.cfg, "pump_sg_entrada_on", False):
            return None
        d = self.sg_decisions().get(self.aba_of({"wallet": who})) or {}
        ruins = d.get("ruins") or []
        if not ruins:
            return None
        bt = ev.get("blockTime")
        x = {"hora": stopganho.hora_berlim(t), "atraso": max(0.0, t - float(bt)) if bt else None, "mcap": tk.get("mcap_sol"), "nota": score}
        f = stopganho.na_faixa(ruins, x)
        if not f:
            return None
        n = self.__dict__["_sg_exp"] = self.__dict__.get("_sg_exp", 0) + 1
        if n % self.SG_EXPLORA == 0:
            return None
        return (f"entrada ruim pelo histórico: {f['nome'].lower()} {f['faixa']} deu média {f['media']:+.1f}% em {f['n']} operações "
                "(Carteiras → Regras → Stop de ganho → Onde a entrada perde)")

    @staticmethod
    def _sg_marcas(p: dict, chg: float, t: float) -> None:
        stopganho.marcar(p, chg, t)

    def _sg_trade(self, p: dict, tr: dict, pre: dict, px, why: str, t: float) -> None:
        if p.get("sg_hits"):
            tr["sg_hits"] = p["sg_hits"]
        sp = p.get("stop_pct")
        tr["sg_stop"] = float(sp) if sp is not None else float(self._c("pump_stop_pct", 40))      # 0.32.335: stop que valia
        if p.get("trader_sol") is not None:
            tr["trader_sol"] = p.get("trader_sol")         # tamanho da compra do trader, para estudar a entrada
        nivel, fonte = p.get("sg_nivel"), p.get("sg_fonte")
        if str(why).startswith(stopganho.MOTIVO):
            tr["sg"] = {"nivel": nivel, "fonte": fonte, "saiu": True}
            if not p.get("real") and px:
                self.sg_sombra.abrir(tr, self._sg_estado(p, pre, px, t))
        elif nivel is not None:
            tr["sg"] = {"nivel": nivel, "fonte": fonte, "saiu": False}

    def _sg_estado(self, p: dict, pre: dict, px: float, t: float) -> dict:
        """Regras normais desta posição para a sombra seguir depois da venda pelo stop de ganho."""
        fr = self._fee_rates(p["mint"])
        tokens = float(pre.get("tokens") or 0)
        left_cost = p["sol_in"] * (tokens / p["tokens"]) if p.get("tokens") else 0.0
        sp = p.get("stop_pct")
        stop = float(sp) if sp is not None else float(self._c("pump_stop_pct", 40))
        if p.get("off_stop"):
            stop = 0.0
        trail_on = (p["trail_on"] if "trail_on" in p else getattr(self.cfg, "pump_trail_enabled", True)) and not p.get("off_trail")
        trail = [float(p.get("trail_start") or self._c("pump_trail_start_pct", 20)), float(p.get("trail_dist") or self._c("pump_trail_dist_pct", 10)),
                 float(self._c("pump_trail_min_lock_pct", 2))] if trail_on else None
        tp = float(p["tp_pct"]) if p.get("tp_pct") is not None else float(self._c("pump_tp_pct", 0))
        hold = self._auto_num(p.get("max_hold_s"))
        hold = hold if hold is not None else float(self._c("pump_max_hold_h", 6)) * 3600
        copia = p.get("wallet") not in (None, "manual") and not p.get("manual")
        segura = float(self._c("pump_hold_min_profit_pct", 0.0)) if copia and getattr(self.cfg, "pump_hold_until_profit", False) else None
        return {"token": p["mint"], "wallet": p.get("wallet"), "t": t, "ate": float(p.get("open_t") or t) + hold, "tokens": tokens,
                "mult": (1 - fr["slip"]) * (1 - fr["venue"] - fr["portal"]), "fixo": fr["prio"], "custo": left_cost,
                "inv": p["sol_in"], "realizado": float(pre.get("proceeds") or 0), "base": "resto", "stop": stop, "trail": trail,
                "alvo": tp, "segue": copia, "segura": segura, "segurando": bool(p.get("hold_profit")), "pico": p.get("trail_peak"),
                "best": float(p.get("best_pct") or 0), "px": px}

    def _sg_salvar(self, tr: dict) -> None:
        """A sombra terminou: grava o trade de novo, agora com o resultado sem o stop de ganho (upsert pelo id)."""
        try:
            self.store._persist("trade_insert", dict(tr))
        except Exception as e:
            log.warning("stop de ganho: sombra não gravou: %s", str(e)[:120])

    def sg_view(self, detalhe: bool = False) -> dict:
        """O que o stop de ganho decidiu para cada aba e se vale nesta conta. detalhe = tabela por nível e faixas da entrada."""
        c = self.cfg
        fora = tuple(self.SG_FORA) + (() if getattr(c, "pump_sg_explorar", False) else ("Explorar",))
        abas = stopganho.tela(self.sg_decisions(), float(self._c("pump_sg_fixo_pct", 0) or 0), getattr(c, "pump_sg_on", False), fora)
        if not detalhe:
            for a in abas:
                a.pop("tabela", None)
        sh = self.sg_sombra.abertas
        return {"ligado": bool(getattr(c, "pump_sg_on", False)), "real": bool(getattr(c, "pump_sg_real", False)),
                "explorar": bool(getattr(c, "pump_sg_explorar", False)), "fixo": float(self._c("pump_sg_fixo_pct", 0) or 0),
                "inicial": stopganho.INICIAL, "janela_dias": stopganho.JANELA_S // 86400, "min_n": stopganho.MIN_N,
                "min_dias": stopganho.MIN_DIAS, "folga": stopganho.FOLGA, "abas": abas, "sombras_abertas": len(sh),
                "sombras_feitas": self.sg_sombra.feitas}

    def check_timeouts(self, t: float | None = None) -> list[str]:
        t = t or time.time()
        mx = float(self._c("pump_max_hold_h", 6)) * 3600
        out = []
        if self.ghosts.open:
            self.ghosts.on_time(t)
        if self.ghosts_auto.open:
            self.ghosts_auto.on_time(t)
        if self.sg_sombra.abertas:                         # 0.32.332: sombra do stop de ganho chegando ao tempo máximo
            self.sg_sombra.tempo(t, lambda m: (self.tokens.get(m) or {}).get("price"))
        for p in self.positions():
            if self.bm_follows_sim(p):                     # 0.32.387: a REAL do BOOST sai junto com a fictícia
                continue
            hold = self._auto_num(p.get("max_hold_s"))
            hold = hold if hold is not None else mx
            ext = p.get("bm_ext")
            if ext and not p.get("selling") and t >= float(ext.get("end_t") or 0) and t - p.get("open_t", t) < hold:
                msg = self._bm_ext_check(p, ext, t)          # 0.32.380: fim do BOOST — fica ou sai
                if msg:
                    out.append(msg)
                continue
            if t - p.get("open_t", t) >= hold and not p.get("selling"):
                out.append(self._sell(p, 1.0, (self.tokens.get(p["mint"]) or {}).get("price") or p.get("price_now"),
                                      p.get("hold_why") or (f"tempo máximo ({hold / 60:g} min)" if p.get("max_hold_s") is not None else f"tempo máximo ({hold / 3600:.0f} h)"), t))
        return [m for m in out if m]

    NO_LIMIT_S = 10 * 365 * 86400.0

    def _bm_ext_check(self, p: dict, ext: dict, t: float) -> str | None:
        """0.32.380 (pedido do dono): o BOOST chegou ao fim (X%). Fica enquanto as compras crescem e/ou até ficar +X%; enquanto
        fica, o stop de perda vira o máximo da opção (padrão 25%). Senão vende tudo com o motivo."""
        from .boostmig import ext_decide
        px = (self.tokens.get(p["mint"]) or {}).get("price") or p.get("price_now")
        pnl = None
        if px and p.get("sol_in"):
            pnl = (float(p.get("proceeds") or 0) + self._exit_value(p, px) - p["sol_in"]) / p["sol_in"] * 100
        growth = None
        if self.bm_growth_hook is not None:
            try:
                growth = self.bm_growth_hook(p["mint"], t)
            except Exception:
                growth = None
        # 0.32.386 (pedido do dono): o stop de ganho autônomo do BOOST só arma no fim do BOOST e só se a posição estiver
        # negativa: segura até subir e aí ele vende. Positiva no fim = segue as regras do BOOST (stop móvel, compras crescendo).
        if "bm_end_pnl" not in p:
            p["bm_end_pnl"] = None if pnl is None else round(pnl, 1)
            if pnl is not None and pnl < 0 and p.get("bm_sg_after", getattr(self.cfg, "pump_bm_sg_after", True)):
                p["bm_sg_armed"] = True
        lvl = self.sg_level(p) if p.get("bm_sg_armed") else None
        if lvl is not None:
            stop = float(ext.get("stop") or 25)
            if pnl is not None and pnl <= -stop:
                keep, why = False, f"BOOST acabou: perda de {pnl:.0f}% (máximo {stop:g}%)"
            else:
                keep, why = True, f"negativo no fim do BOOST: esperando subir até o stop de ganho autônomo (+{lvl:g}%)"
        else:
            keep, why = ext_decide(ext, pnl, growth)
        if keep:
            if not p.get("bm_ext_t"):
                p["bm_ext_t"] = t
                p["stop_pct"] = float(ext.get("stop") or 25)       # perda máxima enquanto fica depois do BOOST
                self._emit(f"BOOST: {p.get('symbol') or p['mint'][:6]} continua depois do fim do BOOST ({why})")
            if p.get("bm_ext_why") != why:
                p["bm_ext_why"] = why
                self._save_pos(p)
            return None
        return self._sell(p, 1.0, px, why, t)

    def extend_hold(self, pid, add_min: float | None) -> dict:
        """0.31.69 (sugestão do Bruxo): estende o tempo máximo de UMA posição aberta (add_min minutos) ou tira o limite
        (add_min None). Vale também para o par do espelho (fictícia × real), para um não fechar o outro antes."""
        pos = self.positions()
        p = next((x for x in pos if str(x["id"]) == str(pid)), None)
        if p is None:
            return {"error": "posição não encontrada"}
        twins = [p] + [x for x in pos if x is not p and ((p.get("real") and str(x["id"]) == str(p.get("sim_id")))
                                                          or (not p.get("real") and str(x.get("sim_id")) == str(p["id"])))]
        cur = self._auto_num(p.get("max_hold_s"))
        cur = cur if cur is not None else float(self._c("pump_max_hold_h", 6)) * 3600
        if add_min is None:
            new = self.NO_LIMIT_S
        else:
            add = max(1.0, min(float(add_min), 7 * 24 * 60)) * 60
            base = max(cur, time.time() - float(p.get("open_t") or time.time()))     # se já passou do limite, conta de agora
            new = base + add
        for x in twins:
            x["max_hold_s"] = new
            self._save_pos(x)
        txt = "sem limite de tempo" if add_min is None else f"tempo máximo agora {new / 60:,.0f} min".replace(",", ".")
        self._emit(f"[PUMP {'REAL' if p.get('real') else 'SIM'}] {p.get('symbol')}: {txt} (estendido por você)")
        return {"ok": True, "max_hold_s": new, "pares": len(twins)}

    POS_RULES = {"stop": ("off_stop", "stop de perda"), "trail": ("off_trail", "stop móvel"), "tp1": ("off_tp1", "venda em partes")}

    def position_rule(self, pid, regra: str, on: bool) -> dict:
        """0.31.87 (Bruxo, áudio de 28/10): liga/desliga stop de perda, stop móvel ou venda em partes de UMA posição aberta
        (token que vai demorar dias para subir). Vale também para o par do espelho (fictícia × real)."""
        if regra not in self.POS_RULES:
            return {"error": "regra inválida"}
        key, nome = self.POS_RULES[regra]
        pos = self.positions()
        p = next((x for x in pos if str(x["id"]) == str(pid)), None)
        if p is None:
            return {"error": "posição não encontrada"}
        twins = [p] + [x for x in pos if x is not p and ((p.get("real") and str(x["id"]) == str(p.get("sim_id")))
                                                          or (not p.get("real") and str(x.get("sim_id")) == str(p["id"])))]
        for x in twins:
            x[key] = not on
            self._save_pos(x)
        self._emit(f"[PUMP {'REAL' if p.get('real') else 'SIM'}] {p.get('symbol')}: {nome} {'ligado' if on else 'DESLIGADO'} nesta posição (por você)")
        return {"ok": True, "regra": regra, "on": on, "pares": len(twins)}

    def close_position(self, pid, frac: float = 1.0) -> dict:
        """Fecha (100%) ou vende só uma parte (0.32.40, botões Vender 25%/50% dos cards de Posições)."""
        try:
            frac = float(frac)
        except (TypeError, ValueError):
            return {"error": "parte inválida"}
        if not 0.05 <= frac <= 1.0:
            return {"error": "parte inválida (de 5% a 100%)"}
        for p in self.positions():
            if str(p["id"]) == str(pid):
                if p.get("selling"):
                    return {"error": "esta posição já está vendendo"}
                px = (self.tokens.get(p["mint"]) or {}).get("price") or p.get("price_now")
                why = "fechada por você" if frac >= 1.0 else f"venda parcial por você ({frac * 100:.0f}%)"
                msg = self._sell(p, frac, px, why, time.time())
                return {"ok": True, "msg": msg, "frac": frac}
        return {"error": "posição não encontrada"}

    def reset_sim(self) -> dict:
        if (any(not p.get("real") and p.get("auto") is True and p.get("origem") in AUTO_ORIGINS
                for p in self.positions())
                or any(not row.get("real") and not row.get("saida_em") for row in self.auto_rows.values())):
            return {"error": "feche as posições automáticas simuladas antes de zerar a carteira fictícia"}
        self.store.reset_sim()
        self.sim_since = None                              # apagou tudo: não há mais o que separar
        self.store.feed_clear()
        self.ghosts.reset()
        self.ghosts_auto.reset()
        return {"ok": True}

    def prune(self, t: float | None = None) -> None:
        """Libera memória: carteiras sem atividade há mais de 24 h e tokens velhos."""
        t = t or time.time()
        win = float(self._c("pump_rank_hours", 24)) * 3600
        for w in [w for w, st in self.wallets.items() if t - st.get("last_t", 0) > win and w not in self.followed]:
            del self.wallets[w]
        for w in [w for w, x in self.creators.items() if t - x > win]:
            del self.creators[w]
        held = {p["mint"] for p in self.positions()}
        for m in [m for m, tk in self.tokens.items() if t - tk.get("last_t", 0) > 6 * 3600 and m not in held]:
            del self.tokens[m]

    # ------------------------------------------------------------------ WebSocket
    def _url(self) -> str:
        url = str(self._c("pump_ws_url", WS_URL))
        key = self.real.api_key() if self.real is not None else ""
        return url + (("&" if "?" in url else "?") + "api-key=" + key if key else "")

    def _paid(self) -> bool:
        """Streams de trades da PumpPortal são PAGOS (chave + carteira com saldo). Só usa se você LIGAR
        (PUMP_PAID_STREAM); ter a chave salva não basta — antes isso desligava a atualização de preços."""
        return bool(getattr(self.cfg, "pump_paid_stream", False) and self.real is not None and self.real.api_key())

    def _flush_subs(self) -> list[dict]:
        out, self._out = self._out, []
        if not self._paid():
            self._want_tokens, self._drop_tokens = [], []
            return []
        held = {p["mint"] for p in self.positions()}
        want = list(dict.fromkeys(self._want_tokens + [m for m in held if m not in self.sub_tokens]))
        drop = [m for m in dict.fromkeys(self._drop_tokens) if m not in held]
        self._want_tokens, self._drop_tokens = [], []
        for i in range(0, len(want), 100):
            out.append({"method": "subscribeTokenTrade", "keys": want[i:i + 100]})
        for i in range(0, len(drop), 100):
            out.append({"method": "unsubscribeTokenTrade", "keys": drop[i:i + 100]})
        return out

    async def run(self) -> None:
        import websockets
        backoff = 2.0
        while True:
            if not getattr(self.cfg, "pump_enabled", True):
                self.status.update(ws=False, error="desligado")
                await asyncio.sleep(5)
                continue
            try:
                async with websockets.connect(self._url(), open_timeout=15, ping_interval=20, max_size=2 ** 22) as ws:
                    self.status.update(ws=True, connected_at=now_iso(), error=None)
                    log.info("Pump.fun: conectado à PumpPortal")
                    backoff = 2.0
                    self._followed_sent = set()
                    await ws.send(json.dumps({"method": "subscribeNewToken"}))
                    self.refresh_followed(force=True)
                    if self._paid() and self.followed and not any(m.get("method") == "subscribeAccountTrade" for m in self._out):
                        self._out.append({"method": "subscribeAccountTrade", "keys": list(self.followed)})
                        self._followed_sent = set(self.followed)
                    self._want_tokens = list(dict.fromkeys(list(self.sub_tokens) + self._want_tokens))
                    last_tick = 0.0
                    while True:
                        try:
                            raw = await asyncio.wait_for(ws.recv(), 2.0)
                            try:
                                ev = json.loads(raw)
                            except ValueError:
                                ev = None
                            for msg in self.on_message(ev) if ev else []:
                                self._emit(msg)
                        except asyncio.TimeoutError:
                            pass
                        if time.time() - last_tick >= 2.0:
                            last_tick = time.time()
                            for m in self._flush_subs():
                                await ws.send(json.dumps(m))
            except asyncio.CancelledError:
                raise
            except Exception as e:
                err = str(e)
                k = self.real.api_key() if self.real is not None else ""
                if k:
                    err = err.replace(k, "***")
                self.status.update(ws=False, error=f"{type(e).__name__}: {err[:120]}")
                log.warning("Pump.fun: WebSocket caiu (%s) — reconectando em %.0f s", err[:100], backoff)
                await asyncio.sleep(backoff)
                backoff = min(60.0, backoff * 2)

    # ------------------------------------------------------------------ monitor grátis (RPC da Solana)
    async def aux_loops(self) -> None:
        for p in self.positions():                 # depois de reiniciar, nenhuma venda está "em andamento"
            if p.get("selling"):
                p["selling"] = False
                self._save_pos(p)
        await asyncio.gather(self.rpc_run(), *(self.tx_worker() for _ in range(4)), self.price_loop(), self.tick_loop(),
                             self.real_loop(), self.trail_fast_loop())

    async def tick_loop(self) -> None:
        while True:
            try:
                await self._tick()
            except Exception as e:
                log.warning("Pump.fun tick: %s", e)
            await asyncio.sleep(2)

    def _ws_url(self) -> str:
        return str(self._c("pump_rpc_ws", SOL_WS) or SOL_WS)

    async def rpc_run(self) -> None:
        """Uma conexão WebSocket com a Solana; uma assinatura logsSubscribe (mentions) por carteira copiada.
        Cada transação confirmada da carteira chega na hora; os detalhes vêm de getTransaction (grátis)."""
        import websockets
        backoff = 2.0
        if self._tx_q is None:
            self._tx_q = asyncio.Queue(maxsize=2000)
        while True:
            if not getattr(self.cfg, "pump_enabled", True):
                self.rpc_status.update(ws=False, error="desligado")
                await asyncio.sleep(5)
                continue
            try:
                async with websockets.connect(self._ws_url(), open_timeout=15, ping_interval=20,
                                              max_size=2 ** 22) as ws:
                    connected_time = time.time()
                    self.rpc_status.update(ws=True, connected_at=now_iso(), error=None)
                    log.info("Pump.fun: monitor de carteiras conectado (Solana RPC)")
                    self._rpc_subs, pending, nid = {}, {}, 100
                    while True:
                        if time.time() - connected_time > 30.0:
                            backoff = 2.0
                        # copiados + todos do top (só para o status online; trades só dos copiados viram cópia)
                        lb_wallets = {r["wallet"] for r in self.leaderboard[:20] if r.get("wallet")}
                        want = set(self.followed) | lb_wallets
                        have = set(self._rpc_subs.values()) | set(pending.values())
                        for w in sorted(want - have):
                            nid += 1
                            pending[nid] = w
                            await ws.send(json.dumps({"jsonrpc": "2.0", "id": nid, "method": "logsSubscribe",
                                                      "params": [{"mentions": [w]}, {"commitment": "confirmed"}]}))
                            await asyncio.sleep(0.05)
                        for sid, w in list(self._rpc_subs.items()):
                            if w not in want:
                                nid += 1
                                del self._rpc_subs[sid]
                                await ws.send(json.dumps({"jsonrpc": "2.0", "id": nid, "method": "logsUnsubscribe",
                                                          "params": [sid]}))
                                await asyncio.sleep(0.05)
                        self.rpc_status["subs"] = len(self._rpc_subs)
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
                                self._rpc_subs[msg["result"]] = w
                            else:
                                self.rpc_status["error"] = str(msg.get("error"))[:120]
                            continue
                        if msg.get("method") == "logsNotification":
                            prm = msg.get("params") or {}
                            w = self._rpc_subs.get(prm.get("subscription"))
                            val = ((prm.get("result") or {}).get("value")) or {}
                            sig = val.get("signature")
                            self.rpc_status["notifs"] += 1
                            if not w or not sig or sig in self._seen_sigs:
                                continue
                            self._seen_sigs.append(sig)
                            act = self.activity.setdefault(w, {"last": None, "n": deque(maxlen=600), "pump": 0,
                                                               "pump_last": None, "other": 0, "pn": deque(maxlen=600)})
                            now = time.time()
                            act["last"] = now
                            act["n"].append(now)
                            if self._is_bot(w, now):
                                continue
                            if val.get("err"):
                                continue
                            logs = " ".join(val.get("logs") or [])
                            if w not in self.followed:           # só observando (status online do top)
                                if any(pid in logs for pid in PUMP_PROGRAMS):
                                    act["pump"] += 1
                                    act["pump_last"] = now
                                    act.setdefault("pn", deque(maxlen=600)).append(now)
                                else:
                                    act["other"] += 1
                                continue
                            # só transações que passam pela pump.fun/PumpSwap viram consulta (o resto — SOL↔USDC,
                            # transferências, outras DEXs — é descartado aqui, sem gastar consulta nenhuma)
                            if not any(pid in logs for pid in PUMP_PROGRAMS):
                                act["other"] += 1
                                if not getattr(self.cfg, "pump_copy_other", True):
                                    continue
                            else:
                                act["pump"] += 1
                                act["pump_last"] = now
                                act.setdefault("pn", deque(maxlen=600)).append(now)
                            try:
                                self._tx_q.put_nowait((w, sig, now))
                            except asyncio.QueueFull:
                                self.rpc_status["dropped"] = self.rpc_status.get("dropped", 0) + 1
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.rpc_status.update(ws=False, error=f"{type(e).__name__}: {str(e)[:120]}")
                log.warning("Pump.fun: monitor de carteiras caiu (%s) — reconectando em %.0f s", str(e)[:100], backoff)
                await asyncio.sleep(backoff)
                backoff = min(60.0, backoff * 2)

    async def _get_tx(self, sig: str, why: list | None = None, low: bool = False) -> dict | None:
        """`why` (0.32.7): recebe o motivo de cada tentativa que falhou, para a tela de falhas de leitura do monitor.
        `low` (0.32.8): leitura de carteira que NÃO é copiada (estudo / Maiores traders): espera a pausa conjunta do 429
        e tenta só 2 vezes. As copiadas não esperam a pausa e tentam 4 vezes, com intervalo curto."""
        mk = getattr(self, "market", None) or self
        urls = []
        own = getattr(self.sol_wallet, "rpc_url", None) if self.sol_wallet is not None else None
        if own and "api.mainnet-beta.solana.com" not in own:
            urls.append(own)                       # RPC da carteira (ex.: Helius) primeiro: o público dá 429 rápido
        # 0.32.236 (dono: "troquei as chaves e ainda não lê"): as leituras usavam só o RPC do Portainer (SOLANA_RPC_PUBLIC);
        # a chave do sistema (Administração → Chaves do sistema → RPC próprio) servia só ao WebSocket. Agora ela vem antes.
        sys_rpc = getattr(mk, "sys_rpc", "") or ""
        if sys_rpc and sys_rpc not in urls:
            urls.append(sys_rpc)
        env_rpc = str(self._c("pump_rpc_http", SOL_HTTP) or SOL_HTTP)
        if env_rpc not in urls:
            urls.append(env_rpc)
        if low:
            # 0.32.238 (dono: "só o Top traders ligado e gasta muito"): carteira que ninguém copia (estudo, Maiores traders,
            # Calls) é lida só no RPC público grátis; os créditos do Helius ficam para as carteiras copiadas.
            urls = [SOL_HTTP]
        # 0.32.236: transação versão 1 (nova na Solana, set/2026; Helius e Ankr já entregam) só vem com
        # maxSupportedTransactionVersion 1; com 0 o RPC responde -32015 "Transaction version (1) is not supported".
        opts = {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1, "commitment": "confirmed"}
        body = {"jsonrpc": "2.0", "id": 1, "method": "getTransaction", "params": [sig, opts]}
        tries = 2 if low else 4
        for attempt in range(tries):
            for u in urls:
                if low:
                    # 0.32.8: em 28/10 100% das falhas eram HTTP 429 do RPC público; cada leitor insistindo sozinho piorava.
                    # Com 429 recente, todos os leitores de baixa prioridade esperam juntos (até 8 s).
                    wait = getattr(mk, "rpc_cool_until", 0.0) - time.time()
                    if wait > 0:
                        await asyncio.sleep(min(wait, 8.0))
                try:
                    r = await self.http.post(u, json=body, timeout=10)
                    if r.status_code == 429:
                        mk.rpc_429_at = time.time()                # 0.32.235: o Status mostra "recusando" (antes ficava "ok")
                        if why is not None:
                            why.append("HTTP 429 (limite do RPC)")
                        n = getattr(mk, "rpc_429_streak", 0) + 1
                        mk.rpc_429_streak = n
                        mk.rpc_cool_until = max(getattr(mk, "rpc_cool_until", 0.0), time.time() + min(8.0, 0.5 * 2 ** min(n, 4)))
                        continue
                    if r.status_code >= 400:
                        mk.rpc_fail_at, mk.rpc_fail_msg = time.time(), f"HTTP {r.status_code}"
                        if why is not None:
                            why.append(f"HTTP {r.status_code}")
                        continue
                    js = r.json() or {}
                    res = js.get("result")
                    if res:
                        mk.rpc_429_streak = 0
                        mk.rpc_ok_at = time.time()
                        return res
                    err = js.get("error") or {}
                    if err and "maxSupportedTransactionVersion" not in str(err.get("message") or ""):
                        mk.rpc_fail_at, mk.rpc_fail_msg = time.time(), str(err.get("message") or err)[:120]
                    if err and "maxSupportedTransactionVersion" in str(err.get("message") or "") and opts["maxSupportedTransactionVersion"] == 0:
                        opts["maxSupportedTransactionVersion"] = 1        # 0.32.8: transação no formato novo (versão 1)
                        r = await self.http.post(u, json=body, timeout=10)
                        res = ((r.json() or {}).get("result")) if r.status_code == 200 else None
                        if res:
                            return res
                    if why is not None:
                        why.append(f"erro do RPC: {str(err.get('message') or err)[:80]}" if err
                                   else "transação ainda não disponível (result vazio)")
                except Exception as e:
                    if why is not None:
                        why.append(type(e).__name__)
                    continue
            if attempt < tries - 1:
                await asyncio.sleep(0.5 + 0.5 * attempt if not low else 1.0 + attempt)
        return None

    @staticmethod
    def parse_trade(tx: dict, wallet: str, sol_usd: float = 0.0) -> dict | None:
        """Transação → evento de trade (mesmo formato da PumpPortal): token que a carteira ganhou/perdeu e o SOL
        (+ wSOL) que saiu/entrou. Funciona para pump.fun, PumpSwap e outras DEXs."""
        meta, msg = tx.get("meta") or {}, ((tx.get("transaction") or {}).get("message") or {})
        if meta.get("err"):
            return None
        keys = [k.get("pubkey") if isinstance(k, dict) else k for k in (msg.get("accountKeys") or [])]
        if wallet not in keys:
            return None
        i = keys.index(wallet)
        pre, post = meta.get("preBalances") or [], meta.get("postBalances") or []
        if i >= len(pre) or i >= len(post):
            return None
        sol = (post[i] - pre[i]) / 1e9
        if i == 0:
            sol += (meta.get("fee") or 0) / 1e9          # taxa da rede não é preço do token
        deltas: dict = {}
        for side, arr in ((-1, meta.get("preTokenBalances") or []), (1, meta.get("postTokenBalances") or [])):
            for b in arr:
                if b.get("owner") != wallet:
                    continue
                amt = float(((b.get("uiTokenAmount") or {}).get("uiAmountString")) or
                            ((b.get("uiTokenAmount") or {}).get("uiAmount")) or 0)
                d = deltas.setdefault(b.get("mint"), {"delta": 0.0, "post": 0.0})
                d["delta"] += side * amt
                if side == 1:
                    d["post"] += amt
        wsol = deltas.pop(SOL_MINT, None)
        if wsol:
            sol += wsol["delta"]
        for st in (USDC, USDT):                       # pagou/recebeu em dólar: converte para SOL
            d_ = deltas.pop(st, None)
            if d_ and abs(d_["delta"]) > 0:
                if not sol_usd:
                    return None
                sol += d_["delta"] / sol_usd
        if not deltas:
            return None
        mint, d = max(deltas.items(), key=lambda kv: abs(kv[1]["delta"]))
        tok = d["delta"]
        if tok > 0 and sol < 0:
            kind = "buy"
        elif tok < 0 and sol > 0:
            kind = "sell"
        else:
            return None
        sig = ((tx.get("transaction") or {}).get("signatures") or [None])[0]
        return {"txType": kind, "traderPublicKey": wallet, "mint": mint, "solAmount": abs(sol),
                "tokenAmount": abs(tok), "newTokenBalance": d["post"], "signature": sig,
                "marketCapSol": abs(sol) / abs(tok) * 1e9 if tok else None,   # pump.fun: 1 bilhão de tokens
                "source": "rpc", "blockTime": tx.get("blockTime")}

    def _is_bot(self, w: str, now: float) -> bool:
        """Robô de alta frequência (sniper/MEV/spam): mais de N transações pump.fun por minuto, ou centenas de
        transações (mesmo falhas) por minuto. Impossível copiar: sai da cópia por 1 h e entra o próximo do top."""
        a = self.activity.get(w) or {}
        if a.get("bot_until", 0) > now:
            return True
        lim_p = float(self._c("pump_max_tx_min", 10))
        pn = sum(1 for x in a.get("pn") or [] if now - x <= 60)
        n = sum(1 for x in a.get("n") or [] if now - x <= 60)
        if pn > lim_p or n > lim_p * 12:
            a["bot_until"] = now + 3600
            a["bot_reason"] = f"robô: {pn} trades pump.fun/min, {n} transações/min"
            if w in self.followed:
                self._emit(f"Pump.fun: {short(w)} parece robô ({a['bot_reason']}) — fora da cópia por 1 h")
            self._rank_at = 0                          # refaz a lista de copiados já
            return True
        return False

    def activity_view(self, w: str) -> dict:
        a = self.activity.get(w) or {}
        now = time.time()
        last, pl = a.get("last"), a.get("pump_last")
        per_min = sum(1 for x in a.get("n") or [] if now - x <= 60)
        if a.get("bot_until", 0) > now:
            st = "robô"
        elif last and now - last <= 600:
            st = "online"
        elif last:
            st = "inativo"
        else:
            st = "sem atividade"
        return {"status": st, "last": last, "pump_last": pl, "pump": a.get("pump", 0), "other": a.get("other", 0),
                "tx_min": per_min, "bot_reason": a.get("bot_reason") if st == "robô" else None}

    def token_block(self, mint: str) -> str | None:
        """Filtros do TOKEN antes de copiar (evita token só do criador/insiders, sem negociação de verdade):
        market cap mínimo em US$, volume da última hora, número de negociações e concentração nos 10 maiores."""
        tk = self.tokens.get(mint) or {}
        su = self.sol_usd or 0
        mn_mc = float(self._c("pump_min_mcap_usd", 10000))
        if mn_mc and tk.get("mcap_sol") is not None and su and tk["mcap_sol"] * su < mn_mc:
            return f"market cap ${tk['mcap_sol'] * su:,.0f} < ${mn_mc:,.0f}".replace(",", ".")
        v = tk.get("vol") or {}
        mn_v = float(self._c("pump_min_vol_h1_usd", 5000))
        if mn_v and float(v.get("h1") or 0) < mn_v:
            return (f"volume 1 h ${float(v.get('h1') or 0):,.0f} < ${mn_v:,.0f}".replace(",", ".")
                    if v else "sem volume (token sem negociação / só do criador)")
        mn_t = int(self._c("pump_min_txns_h1", 30))
        n = int(v.get("buys_h1") or 0) + int(v.get("sells_h1") or 0)
        if mn_t and n < mn_t:
            return f"só {n} negociações na última hora (mínimo {mn_t})"
        mx_top = float(self._c("pump_max_top10_pct", 35))
        top = tk.get("top10_pct")
        if mx_top and top is not None and top > mx_top:
            return f"10 maiores carteiras têm {top:.0f}% (máx. {mx_top:.0f}%) — risco de insiders/dev"
        return self.risk_block(tk)

    @staticmethod
    def curve_progress(mcap_sol: float | None) -> float | None:
        """% da curva da pump.fun já preenchida, a partir do market cap em SOL (curva x*y=k: começa com 30 SOL
        virtuais e gradua com 115, ~28 SOL → ~410 SOL de market cap)."""
        if not mcap_sol or mcap_sol <= 0:
            return None
        return max(0.0, min(100.0, ((32.19 * mcap_sol) ** 0.5 - 30) / 85 * 100))

    def graduated(self, mint: str) -> bool:
        tk = self.tokens.get(mint) or {}
        return tk.get("pool") in ("pumpswap", "pump-amm") or "pumpswap" in (tk.get("dexes") or [])

    def curve_block(self, mint: str) -> str | None:
        """Filtros de token da pump.fun (0.12.0): já graduado e velocidade da curva (o sinal mais forte do estudo)."""
        if not self.is_pump(mint):
            return None
        if getattr(self.cfg, "pump_skip_graduated", False) and self.graduated(mint):
            return "token já graduou (PumpSwap) — depois da graduação o risco de derrubada é maior"
        tk = self.tokens.get(mint) or {}
        if getattr(self.cfg, "pump_entry_curve_on", False) and self.graduated(mint):
            return "token já graduou (a faixa da curva só copia no começo)"     # 0.32.59: pedido do dono, "pegar do início"
        if getattr(self.cfg, "pump_entry_curve_on", False) and not self.graduated(mint):      # 0.32.19: faixa da curva
            prog = self.curve_progress(tk.get("mcap_sol"))
            lo, hi = float(self._c("pump_entry_curve_min", 0)), float(self._c("pump_entry_curve_max", 85))
            if prog is not None and not (lo <= prog <= hi):
                return f"curva em {prog:.0f}% (faixa de entrada {lo:.0f}% a {hi:.0f}%)"
        mn = self._onv("pump_curve_speed_on", "pump_min_curve_speed")
        if mn and not self.graduated(mint) and tk.get("creator"):      # só com a hora de criação vista de verdade
            prog = self.curve_progress(tk.get("mcap_sol"))
            mins = max(0.1, (time.time() - float(tk.get("created_t") or time.time())) / 60)
            if prog is not None and prog / mins < mn:
                return f"curva enchendo devagar ({prog / mins:.1f}%/min, mínimo {mn:.1f}%/min)"
        return None

    def trust_mult(self, who: str) -> tuple[float, str]:
        """Valor da cópia conforme o SEU resultado copiando este trader nos últimos 7 dias (mín. 5 trades)."""
        if not getattr(self.cfg, "pump_size_by_trader", False):
            return 1.0, ""
        real = bool(getattr(self.cfg, "pump_real_enabled", False))
        lim = datetime.now(timezone.utc).timestamp() - 7 * 86400
        mine = [t for t in self.trades(5000) if t.get("wallet") == who and bool(t.get("real")) == real
                and (self._ts(t.get("closed_at")) or 0) >= lim]
        if len(mine) < 5:
            return 1.0, ""
        pnl = sum(t.get("pnl_sol") or 0 for t in mine)
        wins = sum(1 for t in mine if (t.get("pnl_sol") or 0) > 0) / len(mine)
        if pnl > 0 and wins >= 0.5:
            return 1.5, f"×1,5: você lucra copiando este trader ({len(mine)} trades)"
        if pnl < 0:
            return 0.5, f"×0,5: você perde copiando este trader ({len(mine)} trades)"
        return 1.0, ""

    # ------------------------------------------------------------------ 0.19.0: saídas inteligentes, nota e banca
    def smart_exit(self, p: dict, t: float, force: bool = False) -> str | None:
        """Saídas que não dependem do preço da posição (todas começam desligadas): dev vendeu, token graduou,
        pressão de compra virou, outras carteiras seguidas/estudadas vendendo."""
        if p.get("origem") == "boostmig":
            return None                                 # 0.32.399: o BOOST sai só pelas Regras do BOOST (fictícia e REAL)
        tk = self.tokens.get(p["mint"]) or {}
        opened = float(p.get("open_t") or 0)
        if (force or getattr(self.cfg, "pump_exit_dev_sell", False)) and tk.get("dev_sold_t") and tk["dev_sold_t"] >= opened:
            return "dev vendeu"
        sm = float(self._c("pump_exit_stale_min", 45)) if getattr(self.cfg, "pump_exit_stale_on", False) else 0
        if sm and t and t - opened >= sm * 60 and p.get("chg_pct") is not None \
                and abs(float(p["chg_pct"])) <= float(self._c("pump_exit_stale_band", 5)):
            return f"parado há {(t - opened) / 60:.0f} min"
        # 0.32.324: a opção geral (agora ligada por padrão) não vale para a posição com regras próprias que pediu "sem saídas
        # inteligentes" (smart False: Aba do Bruxo, Jev Trade); elas têm a própria regra de graduação
        if ((p.get("grad_exit", True) if force else (getattr(self.cfg, "pump_exit_migrate", False) and p.get("smart") is not False))
                and p.get("grad_in") is False and self.graduated(p["mint"])):
            return "token graduou (PumpSwap)"
        pm = p.get("press_min")                     # 0.31.21: atraso da saída por pressão nas automáticas (0 = não usa)
        if force:
            mn, wait = (40.0 if pm is None or pm > 0 else 0.0), (float(pm) if pm else 1.0) * 60
        else:
            mn, wait = self._onv("pump_exit_pressure_on", "pump_exit_pressure_pct"), 60
        if mn and (not t or t - opened >= wait):
            pr, src = self.pressure(p["mint"])
            if pr is not None and pr < mn:
                return f"pressão de compra virou ({pr:.0f}% de compras, {src})"
        n = int(self._c("pump_exit_kol_n", 2)) if getattr(self.cfg, "pump_exit_kol_on", False) else 0
        if n and len(p.get("kol_sellers") or []) >= n:
            return f"{len(p['kol_sellers'])} carteiras seguidas/estudadas vendendo"
        return None

    def entry_score(self, who: str, mint: str, trader_px: float | None, px: float | None) -> tuple[float, dict]:
        """Nota da entrada de 0 a 100: junta trader, risco, pressão, curva, quanto o preço já subiu e quantas outras
        carteiras seguidas/estudadas estão no token. Parte sem dado fica de fora (o peso se redistribui)."""
        tk = self.tokens.get(mint) or {}
        parts: dict[str, float] = {}
        tr = []
        row = next((r for r in self.leaderboard if r.get("wallet") == who), None)
        if row and row.get("winrate") is not None:
            tr.append(min(1.0, float(row["winrate"]) / 100))
        mine = [x for x in self.trades(2000) if x.get("wallet") == who and not x.get("real")][:30]
        if len(mine) >= 3:
            tr.append(sum(1 for x in mine if (x.get("pnl_sol") or 0) > 0) / len(mine))
        if tr:
            parts["trader"] = sum(tr) / len(tr)
        rk = tk.get("risk") or {}
        if rk.get("rugged"):
            parts["risco"] = 0.0
        elif isinstance(rk.get("score"), (int, float)):
            parts["risco"] = max(0.0, 1 - float(rk["score"]) / 10)
        pr, _ = self.pressure(mint)
        if pr is not None:
            parts["pressão"] = pr / 100
        if self.is_pump(mint) and not self.graduated(mint) and tk.get("creator") and tk.get("created_t"):
            prog = self.curve_progress(tk.get("mcap_sol"))
            if prog is not None:
                mins = max(0.1, (time.time() - float(tk["created_t"])) / 60)
                parts["curva"] = min(1.0, prog / mins / 10)
        if trader_px and px:
            parts["preço"] = max(0.0, 1 - max(0.0, px / trader_px - 1) / 0.5)
        cs = self.market.creator_stats.get(tk.get("creator") or "")
        if cs and cs.get("tokens", 0) >= 2:                                   # histórico do criador (0.21.0)
            parts["criador"] = max(0.0, min(1.0, 0.5 + (cs.get("x2", 0) - cs.get("rugs", 0)) / (2 * cs["tokens"])))
        others = (set(self.followed) | set(getattr(self, "study", None) or [])) - {who}
        n = sum(1 for w in others if (((self.wallets.get(w) or {}).get("pos") or {}).get(mint) or {}).get("tok", 0) > 0)
        parts["onda"] = min(1.0, 0.2 + n / 3)
        W = {"trader": 25, "risco": 20, "pressão": 15, "curva": 15, "preço": 15, "onda": 10, "criador": 10}
        tot = sum(W[k] for k in parts)
        score = round(sum(parts[k] * W[k] for k in parts) / tot * 100, 1) if tot else 50.0
        return score, {k: round(v * 100) for k, v in parts.items()}

    @staticmethod
    def _auto_num(value) -> float | None:
        if isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return number if math.isfinite(number) else None

    def auto_rules(self) -> dict:
        """Regras próprias da operação automática; o botão manual mantém seus valores."""
        return {"stop_pct": float(self._c("pump_ar_stop_pct", 25)),
                "tp_pct": float(self._c("pump_ar_tp_pct", 150)), "trail_on": True,
                "trail_start": float(self._c("pump_ar_trail_start", 40)),
                "trail_dist": float(self._c("pump_ar_trail_dist", 15)),
                "boost_tp": float(self._c("pump_manual_boost_tp", 80)) if getattr(self.cfg, "pump_manual_boost_on", True) else None,
                "tp1_pct": float(self._c("pump_ar_tp1_pct", 40)),
                "tp1_frac": float(self._c("pump_ar_tp1_frac", 50)),
                "max_hold_s": float(self._c("pump_ar_max_hold_min", 30)) * 60,
                "smart": bool(getattr(self.cfg, "pump_ar_smart", True)),
                # 0.31.21: ajustáveis pelo ajuste automático a partir dos fantasmas das automáticas
                "press_min": float(self._c("pump_ar_press_min", 1.0)),
                "grad_exit": bool(getattr(self.cfg, "pump_ar_exit_grad", True))}

    def _auto_operations(self) -> list[dict]:
        """Histórico carregado + posições/legado da Base, sem duplicar uma entrada já conhecida."""
        rows = {str(key): dict(row) for key, row in self.auto_rows.items()}
        for p in self.positions():
            if not p.get("auto"):
                continue
            key = str(p.get("id"))
            if key not in rows:
                rows[key] = {"id": key, "mint": p.get("mint"), "real": bool(p.get("real")),
                             "entrada_em": p.get("opened_at"), "_entry_t": p.get("open_t"), "saida_em": None}
        for tr in self.trades(100000):
            if not tr.get("auto"):
                continue
            key = str(tr.get("id"))
            if key not in rows:
                rows[key] = {"id": key, "mint": tr.get("mint"), "real": bool(tr.get("real")),
                             "entrada_em": tr.get("opened_at"), "saida_em": tr.get("closed_at"),
                             "pnl_sol": tr.get("pnl_sol")}
        for mint, entered in getattr(self, "_auto_done", {}).items():
            if not any(row.get("mint") == mint for row in rows.values()):
                rows["legacy:" + mint] = {"id": "legacy:" + mint, "mint": mint, "_entry_t": entered,
                                          "entrada_em": None, "saida_em": None, "legacy": True}
        for mint, entered in self._auto_pending.items():
            rows["pending:" + mint] = {"id": "pending:" + mint, "mint": mint, "_entry_t": entered,
                                      "entrada_em": None, "saida_em": None, "real": True}
        return [r for r in rows.values() if not str(r.get("motivo_saida") or "").startswith("desfeita")]

    def auto_guard(self, mint: str | None = None, t: float | None = None) -> str | None:
        """Travas só das automáticas, antes de reservar saldo ou criar uma posição."""
        t = time.time() if t is None else t
        self._auto_pause_until = None                # derivado novamente do histórico, nunca estende ao consultar
        if not self.auto_ready:
            return "histórico das automáticas indisponível; aguardando o banco"
        # 0.31.42 (sugestão do Bruxo, R1R2L1R2 não foi para a real): com o espelho, a real é a CÓPIA da fictícia e segue
        # só os limites da carteira real. Então as travas das automáticas (posições abertas, por hora, perda do dia,
        # perdas seguidas) contam SÓ a fictícia — antes a compra real ocupava vaga da fictícia e a fictícia recém-aberta
        # bloqueava a real na última vaga da hora.
        mirror = bool(getattr(self.cfg, "pump_real_mirror", True))
        # Uma linha aberta persistida também reserva vaga se o processo caiu entre as duas gravações.
        opened = {str(p["id"]) for p in self.positions() if p.get("auto") and not (mirror and p.get("real"))}
        opened.update(str(key) for key, row in self.auto_rows.items() if not row.get("saida_em") and not (mirror and row.get("real")))
        maximum = int(self._c("pump_ar_max_open", 3))
        if len(opened) + (0 if mirror else len(self._auto_pending)) >= maximum:
            return f"limite de {maximum} posições automáticas abertas"
        rows = [row for row in self._auto_operations() if not (mirror and row.get("real"))]

        def entered(row):
            at = self._auto_num(row.get("_entry_t"))
            return at if at is not None else self._ts(row.get("entrada_em"))

        entries = [(row, entered(row)) for row in rows]
        if mint and any(row.get("mint") == mint and at is not None and 0 <= t - at < 86400 for row, at in entries):
            return "token já teve entrada automática nas últimas 24 h"
        hourly = sum(at is not None and 0 <= t - at < 3600 for _row, at in entries)
        maximum = int(self._c("pump_ar_max_h", 4))
        if hourly >= maximum:
            return f"limite de {maximum} entradas automáticas por hora"
        day = datetime.fromtimestamp(t, timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        closed = []
        for row in rows:
            at, pnl = self._ts(row.get("saida_em")), self._auto_num(row.get("pnl_sol"))
            if at is not None and at <= t and pnl is not None:
                closed.append((at, pnl))
        ordered = sorted(closed)
        day_result, day_low = 0.0, 0.0
        for at, pnl in ordered:
            if at >= day:
                day_result += pnl
                day_low = min(day_low, day_result)
        limit = float(self._c("pump_ar_daily_loss", 0.25))
        if limit and day_low <= -limit:
            self._auto_pause_until = day + 86400
            return f"perda do dia atingiu {day_low:+.4f} SOL; pausada até 00:00 UTC"
        streak = int(self._c("pump_ar_streak_n", 3))
        count, until = 0, None
        if streak:
            hours = float(self._c("pump_ar_streak_h", 1)) * 3600
            for at, pnl in ordered:
                count = count + 1 if pnl < 0 else 0
                if count >= streak:
                    until = max(until or 0, at + hours)
        if until is not None and until > t:
            self._auto_pause_until = until
            hour = datetime.fromtimestamp(until, timezone.utc).strftime("%H:%M UTC")
            return f"{streak} perdas seguidas até {hour}"
        return None

    def _auto_blocked(self, reason: str, mint: str, origem: str, t: float) -> None:
        # 0.31.79 (pedido do dono: o Feed ao vivo ficava lotado de "compra automática pausada" do mesmo token a cada minuto,
        # escondendo o que os traders fizeram e empurrando os registros antigos para fora): "já teve entrada nas últimas
        # 24 h" é o comportamento normal e não vai mais para o Feed (fica só no funil do Explorar); os outros motivos
        # aparecem no máximo uma vez a cada 6 h por token
        if reason.startswith("token já teve entrada automática"):
            return
        notices = self.__dict__.setdefault("_auto_notices", {})
        key = (origem, reason, mint)
        if t - notices.get(key, -1e30) < 6 * 3600:
            return
        notices[key] = t
        self._auto_notices = {k: at for k, at in notices.items() if t - at < 6 * 3600}
        msg = "compra automática pausada: " + reason
        self._feed(wallet="manual", short="automático", mint=mint, symbol=(self.tokens.get(mint) or {}).get("symbol"),
                   kind="buy", action="compra automática pausada", reason=reason, origem=origem)
        self._emit("[PUMP SIM] " + msg)

    def learn_trades(self) -> list[dict]:
        """Trades para o aprender com os erros (0.31.63, pedido do dono: "não faz sentido só uma conta aprender"): os desta
        conta (marcados _mine) + os de todas as outras contas como CONHECIMENTO. Ficam de fora: a cópia de trades de outra
        conta (contaria o mesmo trade duas vezes) e os ganhos de preço lido errado (+1.900% ou mais, SEALLIS/R1R2L1R2,
        antes da correção 0.31.52). Nada disso entra no histórico ou na carteira de ninguém."""
        from .auto_trades import SUSPECT_PCT
        pool = self.learn_pool() if self.learn_pool is not None else [(True, t) for t in self.trades(100000)]
        out, kept = [], {}
        # 0.31.72: o MESMO token comprado por várias contas com até 10 min de diferença conta uma vez só (Bruxo e Pedro
        # com a mesma configuração compravam juntos e o token pesava em dobro); a conta aberta tem preferência
        for mine, t in sorted(pool, key=lambda x: (not x[0], str(x[1].get("opened_at") or ""))):
            if t.get("real") or t.get("follow_of") or (t.get("pnl_pct") or 0) >= SUSPECT_PCT:
                continue
            if not t.get("sombra"):
                # só entre contas DIFERENTES: a mesma conta comprando o mesmo token de novo conta normalmente
                at, conta = _ts(t.get("opened_at")) or _ts(t.get("closed_at")) or 0, t.get("_conta")
                if conta is not None and any(c != conta and abs(at - x) <= 600 for x, c in kept.get(t.get("mint"), [])):
                    continue
                kept.setdefault(t.get("mint"), []).append((at, conta))
            out.append(dict(t, _mine=mine))
        return out

    def learned(self, origem: str, t: float | None = None) -> dict:
        """Aprender com os erros (0.31.12, app/autolearn.py): faixas das compras automáticas fechadas; avisa quando uma
        faixa nova passa a ser bloqueada. Recalculado do histórico a cada 60 s."""
        from .autolearn import study
        t = time.time() if t is None else t
        cache = self.__dict__.setdefault("_learned", {})
        hit = cache.get(origem)
        if hit and t - hit[0] < 60:
            return hit[1]
        st = study(self.learn_trades(), origem)
        before = {(x["feature"], x["faixa"]) for x in (hit[1]["bloqueios"] if hit else [])}
        for x in st["bloqueios"]:
            if hit and (x["feature"], x["faixa"]) not in before:
                self._emit(f"Aprendi com os erros ({origem}): não entro mais com {x['nome']} {x['faixa']} — perdeu em {x['n']} "
                           f"operações (acerto {x['acerto'] * 100:.0f}%, média {x['media_pct']:+.0f}%)")
        cache[origem] = (t, st)
        return st

    def learned_for_entry(self, origem: str) -> dict:
        """0.31.85: faixas que barram a entrada. Com o cérebro congelado numa evolução (o dono voltou para ela), valem as
        faixas guardadas na foto daquela evolução; o estudo e a Base geral continuam mostrando o aprendizado atual."""
        fz = self.brain_freeze
        if fz and origem == "explorar":
            return {"bloqueios": list(fz.get("bloqueios") or []), "congelado": fz.get("numero")}
        st = self.learned(origem)
        if getattr(self.cfg, "pump_ar_learn_wilson", False):
            # 0.31.99, item 3: bloqueia só quando o acerto máximo provável (Wilson 90%) fica abaixo de 50% e a média é ruim
            return dict(st, bloqueios=[x for x in st.get("faixas") or [] if x.get("bloq_wilson")])
        return st

    def explore_entry_reason(self, row: dict) -> str | None:
        """Filtros da lista Quase graduando; dado obrigatório ausente não libera entrada."""
        if not isinstance(row, dict) or not isinstance(row.get("mint"), str) or not self.valid_addr(row["mint"]):
            return "endereço do token inválido"
        if row.get("cat") not in (None, "graduating"):
            return "só entra na lista Quase graduando"
        if self.graduated(row["mint"]):
            return "token já graduou desde a lista do Explorar"
        pred = row.get("pred") if isinstance(row.get("pred"), dict) else {}
        possivel = pred.get("verdict") == "possível" and getattr(self.cfg, "pump_ex_possivel_on", False)   # 0.31.99, item 2
        if pred.get("verdict") != "chance alta" and not possivel:
            return "veredito não é chance alta"
        if row.get("rugged"):
            return "token marcado como rug"
        creator = row.get("creator") or (self.tokens.get(row["mint"]) or {}).get("creator")
        if creator and creator in self.market.blacklist:
            return "criador na lista negra"
        history = self.market.creator_stats.get(creator or "") or {}
        if (self._auto_num(history.get("rugs")) or 0) >= 2:
            return "criador com 2 ou mais tokens despencados"
        pressure, holders = self._auto_num(row.get("pressure")), self._auto_num(row.get("holders"))
        curve, change = self._auto_num(row.get("curve_pct")), self._auto_num(row.get("chg_5m"))
        if pressure is None or not 0 <= pressure <= 100 or pressure < float(self._c("pump_ex_auto_min_pressure", 60)):
            return "pressão de compra ausente ou abaixo do mínimo"
        if holders is None or holders < 0 or holders < int(self._c("pump_ex_auto_min_holders", 100)):
            return "holders ausentes ou abaixo do mínimo"
        if row.get("risk") is not None:
            risk = self._auto_num(row["risk"])
            if risk is None or not 0 <= risk <= int(self._c("pump_ex_auto_max_risk", 6)):
                return "risco inválido ou acima do máximo"
        if curve is None or not float(self._c("pump_ex_auto_curve_min", 60)) <= curve <= float(self._c("pump_ex_auto_curve_max", 95)):
            return "curva ausente ou fora da faixa"
        if change is None or not 0 <= change <= float(self._c("pump_ex_auto_max_chg5", 150)):
            return "variação em 5 min ausente ou fora da faixa"
        created = self._auto_num(row.get("created"))
        age = None
        if created:
            age = (time.time() - (created / 1000 if created > 1e12 else created)) / 60
        # 0.32.36 (sugestão do Bruxo): idade máxima do token no Explorar; sem a idade, não entra (dado obrigatório)
        mx = float(self._c("pump_ex_max_age_min", 0) or 0)
        if mx:
            if age is None:
                return "idade do token ausente (limite de idade ligado)"
            if age > mx:
                return f"token com {age:.0f} min de vida (máximo {mx:.0f} no Explorar)"
        row = dict(row, age_min=age)                       # a idade também entra no aprender com os erros
        if getattr(self.cfg, "pump_ar_learn", True):
            from .autolearn import blocked_reason
            why = blocked_reason(self.learned_for_entry("explorar"), row)
            if why:
                return why
        return self.auto_safety(row["mint"], age, "explorar")

    def explore_auto_check(self, lists: dict, t: float | None = None) -> list[str]:
        if not getattr(self.cfg, "pump_ex_auto_on", False) or getattr(self, "role", None) != "admin":
            return []
        t = time.time() if t is None else t
        out = []
        for row in (lists.get("graduating") or [])[:40]:
            why = self.explore_entry_reason(row)
            if why:
                self._funnel_note(row, why, t)
                continue
            mint = row["mint"]
            guard = self.auto_guard(mint, t)
            if guard:
                self._funnel_note(row, guard, t)
                self._auto_blocked(guard, mint, "explorar", t)
                continue
            pred = row["pred"]
            info = {"veredito": pred["verdict"], "chance": self._auto_num(pred.get("chance")),
                    **{k: copy.deepcopy(row.get(k)) for k in ("pressure", "holders", "curve_pct", "risk", "chg_5m", "boost")},
                    "creator": row.get("creator") or (self.tokens.get(mint) or {}).get("creator"),
                    "score": self._auto_num(row.get("score")), "why": copy.deepcopy(pred.get("why") or []), "source": "explorar"}
            from .explore import extra_info
            info.update(extra_info(row, self.tokens.get(mint), t))            # 0.31.81: item A (só anotação)
            result = self.manual_buy(mint, t, auto="automático: chance alta", origem="explorar", info=info)
            self._funnel_note(row, None if result.get("auto_id") else (result.get("error") or result.get("sim") or "não entrou"), t)
            if result.get("auto_id"):
                out.append(mint)
        return out

    def explore_cycle_note(self, source_at: float, n_list: int, n_fresh: int, stamp: float) -> dict | None:
        """0.31.88 (pedido do dono: "log de análise do que foi feito ou não, salvo"): um registro por lista do Explorar
        (a cada 5 min): quantos tokens vieram, quantos tinham preço recente (só esses são analisados), o que cada um
        decidiu e o motivo mais comum. Atualizado a cada volta (~20 s) enquanto a lista vale; devolve o registro só
        quando mudou, para gravar no banco."""
        import json
        import re
        cyc = self.__dict__.setdefault("_ex_cycles", {})
        rec = cyc.get(source_at) or {"lista_em": source_at, "voltas": 0, "na_lista": 0, "com_preco": 0, "tok": {}}
        rec["voltas"] += 1
        rec["na_lista"], rec["com_preco"] = max(rec["na_lista"], n_list), max(rec["com_preco"], n_fresh)
        for mint, g in (getattr(self, "_ex_funnel", None) or {}).items():
            if g.get("t") == stamp:
                rec["tok"][mint] = {"s": g.get("symbol"), "v": g.get("chance"), "w": g.get("why"), "e": bool(g.get("entrou"))}
        toks = rec["tok"].values()
        motivos: dict[str, list] = {}
        for x in toks:
            if x["w"]:
                k = re.sub(r"[-+]?\d+(?:[.,]\d+)?", "#", str(x["w"]))[:90]
                motivos.setdefault(k, [0, str(x["w"])[:140]])[0] += 1
        out = {"lista_em": source_at, "analisados": len(rec["tok"]), "na_lista": rec["na_lista"], "com_preco": rec["com_preco"],
               "sem_preco": max(0, rec["na_lista"] - rec["com_preco"]),
               "chance_alta": sum(1 for x in toks if x["v"] == "chance alta"),
               "entrou": sorted({x["s"] or "?" for x in toks if x["e"]}),
               "motivos": sorted(({"motivo": v[1], "n": v[0]} for v in motivos.values()), key=lambda m: -m["n"])[:12],
               "chance_alta_barrados": [{"symbol": x["s"], "mint": m, "motivo": str(x["w"])[:140]}
                                        for m, x in rec["tok"].items() if x["v"] == "chance alta" and x["w"]][:40]}
        out["gargalo"] = out["motivos"][0]["motivo"] if out["motivos"] else None
        sig = json.dumps(out, sort_keys=True, default=str)
        changed = sig != rec.get("_sig")
        rec["_sig"] = sig
        cyc[source_at] = rec
        for k in sorted(cyc)[:-3]:
            cyc.pop(k, None)
        return out if changed else None

    def _funnel_note(self, row: dict, why: str | None, t: float) -> None:
        """0.31.38 — sugestão do Bruxo + aprendizagem do bot: funil do filtro do Explorar (só memória, 24 h). Guarda a
        última decisão de cada token e o preço da primeira vez que foi visto, para mostrar quantos foram barrados por
        cada motivo e se os barrados subiram ou caíram depois (o filtro está barrando os bons?)."""
        fn = getattr(self, "_ex_funnel", None)
        if fn is None:
            fn = self._ex_funnel = {}
        mint = row.get("mint")
        if not mint:
            return
        g = fn.get(mint) or {"first_t": t, "symbol": row.get("symbol") or short(mint), "px0": (self.tokens.get(mint) or {}).get("price"),
                             "chance": (row.get("pred") or {}).get("verdict")}
        if row.get("vol24_usd") is not None:
            g["vol"] = row.get("vol24_usd")            # 0.32.21: volume 24 h (US$) para a entrada dos barrados que sobem
        if g.get("px0") is None:
            g["px0"] = (self.tokens.get(mint) or {}).get("price")
        if g.get("why") is None and g.get("t") and why is not None and g.get("entrou"):
            pass                                           # já entrou: não volta a contar como barrado
        else:
            g["why"], g["entrou"] = why, (why is None) or g.get("entrou", False)
        g["t"] = t
        fn[mint] = g
        # 0.31.86 (pedido do dono, item A): TODO token barrado vira sombra, também os barrados pelo veredito. Só as de
        # "chance alta" entram no aprender com os erros (o resto mede se o veredito acerta, em estudo separado).
        if why and self.shadow_hook is not None:
            try:
                self.shadow_hook(row, why, t)
            except Exception as e:
                log.warning("entrada sombra: %s", str(e)[:120])
        self._funnel_dirty = True
        if len(fn) > 3000:
            for k in sorted(fn, key=lambda k: fn[k]["t"])[:500]:
                fn.pop(k, None)

    def funnel_dump(self, now: float | None = None) -> dict:
        """0.31.41: o funil vai junto com os fantasmas para o banco (ghost_stats) e sobrevive ao reinício; só 24 h."""
        now = time.time() if now is None else now
        fn = {k: v for k, v in (getattr(self, "_ex_funnel", None) or {}).items() if now - v.get("t", 0) < 86400}
        keep = sorted(fn, key=lambda k: fn[k].get("t", 0), reverse=True)[:800]
        return {k: fn[k] for k in keep}

    def explore_funnel(self, now: float | None = None) -> dict:
        import re
        now = time.time() if now is None else now
        fn = {k: v for k, v in (getattr(self, "_ex_funnel", None) or {}).items() if now - v["t"] < 86400}
        self._ex_funnel = fn
        motivos, barr, exemplo = {}, [], {}
        for mint, g in fn.items():
            if g.get("entrou"):
                continue
            key = re.sub(r"[-+]?\d+(?:[.,]\d+)?", "#", str(g.get("why") or "outro"))[:90]
            motivos[key] = motivos.get(key, 0) + 1
            exemplo.setdefault(key, str(g.get("why") or "outro")[:120])     # 0.31.67: mostra o texto real, sem "#"
            px, px0 = (self.tokens.get(mint) or {}).get("price"), g.get("px0")
            if px and px0:
                barr.append({"mint": mint, "symbol": g.get("symbol"), "chg_pct": round((px / px0 - 1) * 100, 1), "motivo": g.get("why"),
                             "hi": g.get("hi"), "lo": g.get("lo"), "auto_st": g.get("auto_st"),
                             "seguranca": not self._bar_soft(g), "suspeito": bool(g.get("suspeito"))})
        barr.sort(key=lambda b: -b["chg_pct"])
        # 0.32.31: a lista vai até o gatilho da entrada automática (antes só +50%) e mostra até 30
        alta = [b for b in barr if b["chg_pct"] >= min(50.0, float(self._c("pump_bar_min_gain", 50)))]
        return {"vistos": len(fn), "chance_alta": sum(1 for g in fn.values() if g.get("chance") == "chance alta"),
                "entrou": sum(1 for g in fn.values() if g.get("entrou")), "barrados": len(fn) - sum(1 for g in fn.values() if g.get("entrou")),
                "motivos": sorted(({"motivo": exemplo.get(k, k), "n": v} for k, v in motivos.items()), key=lambda m: -m["n"])[:12],
                "barrados_com_preco": len(barr), "subiram_50": len(alta), "cairam_30": sum(1 for b in barr if b["chg_pct"] <= -30),
                "top_subiram": alta[:30], "cedo": self.barred_sim()}

    # 0.32.21: motivos de barragem que são SEGURANÇA — esses nunca entram, mesmo subindo
    BAR_HARD = ("lista negra", "rug", "criador", "risco", "bundle", "carteiras novas", "lixo", "suspeito", "mayhem", "dev ")

    # ------------------------------------------------------------------ 0.32.33: aprendizado das posições (app/poslearn.py)
    def pos_snapshots(self, now: float | None = None) -> None:
        """Foto de cada posição aberta a cada 15 min e, na primeira vez, onde a entrada ficou nos 15 min anteriores."""
        from .poslearn import SNAP_S, entry_context
        now = time.time() if now is None else now
        for p in self.positions():
            ch = False
            if "antes" not in p:
                p["antes"] = entry_context(list(self.market.px_hist.get(p["mint"]) or []), float(p.get("open_t") or now),
                                           p.get("trader_px") or p.get("trader_price") or p.get("price_in"))
                ch = True
            last = float(p.get("snap_t") or p.get("open_t") or now)
            if now - last >= SNAP_S:
                snaps = p.setdefault("snaps", [])
                snaps.append({"t": round(now), "min": round((now - float(p.get("open_t") or now)) / 60), "chg": p.get("chg_pct"),
                              "best": p.get("best_pct"), "worst": p.get("worst_pct"), "px": p.get("price_now"),
                              "mcap": (self.tokens.get(p["mint"]) or {}).get("mcap_sol")})
                del snaps[:-100]
                p["snap_t"] = now
                ch = True
            if ch:
                self._save_pos(p)

    def _post_open(self, p: dict, tr: dict, px, t: float) -> None:
        from .poslearn import entry_label, exit_kind, origin_of
        w = self.__dict__.setdefault("_post_watch", {})
        if len(w) > 300:
            return
        w[str(p.get("id"))] = {"pos_id": p.get("id"), "mint": p["mint"], "symbol": p.get("symbol"), "real": bool(p.get("real")),
                               "origem_nome": origin_of({**p, **tr}), "saida_tipo": exit_kind(tr.get("reason")), "motivo": tr.get("reason"),
                               "opened_at": tr.get("opened_at"), "closed_at": tr.get("closed_at"), "hold_s": tr.get("hold_s"),
                               "pnl_pct": tr.get("pnl_pct"), "pnl_sol": tr.get("pnl_sol"), "best_pct": p.get("best_pct"),
                               "worst_pct": p.get("worst_pct"), "antes": p.get("antes"), "entrada": entry_label(p.get("antes")),
                               "fotos": list(p.get("snaps") or [])[-20:], "px_out": px, "t_out": t, "depois": {}}

    def post_watch_mints(self) -> list[str]:
        return list({x["mint"] for x in (self.__dict__.get("_post_watch") or {}).values()})[:40]

    def post_tick(self, now: float | None = None) -> None:
        """Preço 15/30/60 min depois da saída; quando completa (ou passa de 75 min), vira linha do aprendizado."""
        from .poslearn import AFTER_MIN, exit_label
        now = time.time() if now is None else now
        w = self.__dict__.get("_post_watch") or {}
        for k, x in list(w.items()):
            tk = self.tokens.get(x["mint"]) or {}
            px, fresh = tk.get("price"), now - float(tk.get("last_t") or 0) <= 120
            for m in AFTER_MIN:
                if str(m) not in x["depois"] and now >= x["t_out"] + m * 60 and px and x.get("px_out") and fresh:
                    x["depois"][str(m)] = round((px / x["px_out"] - 1) * 100, 1)
            if len(x["depois"]) == len(AFTER_MIN) or now > x["t_out"] + 75 * 60:
                x["saida"] = exit_label(x["depois"], x.get("pnl_pct"))
                x.pop("t_out", None)
                self.__dict__.setdefault("_learn_out", []).append(x)
                del w[k]

    def recent_closed(self, hours: float = 3) -> list[dict]:
        """0.32.33 (pedido do dono): em Posições, as que acabaram de fechar (stop, alvo, tempo…) para ver que terminou."""
        from .auto_trades import ts
        cut = time.time() - hours * 3600
        return [t for t in self.trades(200) if (ts(t.get("closed_at")) or 0) >= cut][:30]

    BAR_TRIGGERS = (10, 20, 30, 50)                # 0.32.22: gatilhos testados em "entrar cedo"
    BAR_FEES_PCT = 4.0                              # ida e volta estimada (curva 1,25% + PumpPortal 0,5% + slippage), por lado ×2

    def _bar_soft(self, g: dict) -> bool:
        why = str(g.get("why") or "")
        return bool(why) and not any(h in why.lower() for h in self.BAR_HARD)

    def barred_watch(self, now: float | None = None) -> list[str]:
        """0.32.22: tokens barrados (não por segurança) da última hora que precisam de preço ao vivo; antes o preço deles
        só mudava com a lista do Explorar (5 min), e "entrar cedo" ficava impossível."""
        now = time.time() if now is None else now
        fn = getattr(self, "_ex_funnel", None) or {}
        live = [(g.get("first_t") or 0, m) for m, g in fn.items()
                if not g.get("entrou") and self._bar_soft(g) and now - float(g.get("first_t") or 0) < 4 * 3600]
        return [m for _, m in sorted(live, reverse=True)[:40]]

    def barred_track(self, now: float | None = None) -> None:
        """0.32.22 (pedido do dono: "entrar bem cedo, a maioria subiu mas também teve queda"): para cada barrado (não por
        segurança), guarda o pico e a pior queda desde que foi visto e simula entrar quando ele sobe +10/+20/+30/+50%,
        saindo pelas regras do botão Comprar (stop, alvo, stop móvel) ou em 30 min, já descontando ~4% de taxas.
        Só mede: nada é comprado aqui. O resultado mostra qual gatilho teria dado lucro."""
        from .auto_trades import SUSPECT_PCT
        now = time.time() if now is None else now
        r = self.manual_rules()
        stop, tp = float(r["stop_pct"]), float(r["tp_pct"] or 0)
        ton, tst, tdi = bool(r["trail_on"]), float(r["trail_start"]), float(r["trail_dist"])
        for mint, g in list((getattr(self, "_ex_funnel", None) or {}).items()):
            if g.get("entrou") or not self._bar_soft(g):
                continue
            tk = self.tokens.get(mint) or {}
            px, px0 = tk.get("price"), g.get("px0")
            if not px or not px0 or now - float(tk.get("last_t") or 0) > 120:
                continue
            chg = (px / px0 - 1) * 100
            # 0.32.30 (HOUSECOIN +5.505% com "pior queda" +4.182%, 28/10): alta de 20× ou mais é quase sempre preço errado
            # (curva cotada em outra moeda). O token sai da simulação e da entrada automática.
            if chg >= SUSPECT_PCT or g.get("suspeito"):
                g["suspeito"] = True
                continue
            g["hi"] = round(max(chg, g.get("hi", chg)), 1)
            g["lo"] = round(min(chg, g.get("lo", chg)), 1)
            v = g.setdefault("v", {})
            for T in self.BAR_TRIGGERS:
                k = str(T)
                tr = v.get(k)
                if tr is None:
                    if chg >= T and now - float(g.get("first_t") or now) < 5400:
                        v[k] = {"in": px, "t": now, "peak": 0.0}
                    continue
                if "out" in tr:
                    continue
                ret = (px / tr["in"] - 1) * 100
                tr["peak"] = max(tr["peak"], ret)
                why = None
                if ret <= -stop:
                    why = "stop"
                elif tp and ret >= tp:
                    why = "alvo"
                elif ton and tr["peak"] >= tst and ret <= tr["peak"] - tdi:
                    why = "stop móvel"
                elif now - tr["t"] >= 1800:
                    why = "30 min"
                if why:
                    tr.update(out=round(ret - self.BAR_FEES_PCT, 1), why=why, t_out=now)

    def barred_sim(self) -> list[dict]:
        rows = []
        for T in self.BAR_TRIGGERS:
            tr = [(g.get("v") or {}).get(str(T)) for g in (getattr(self, "_ex_funnel", None) or {}).values() if not g.get("suspeito")]
            done = [x for x in tr if x and "out" in x]
            opn = [x for x in tr if x and "out" not in x]
            wins = sum(1 for x in done if x["out"] > 0)
            rows.append({"gatilho": T, "entradas": len(done), "abertas": len(opn), "ganhos": wins,
                         "acerto": round(wins / len(done) * 100) if done else None,
                         "media_pct": round(sum(x["out"] for x in done) / len(done), 1) if done else None,
                         "soma_005": round(sum(x["out"] for x in done) / 100 * 0.05, 4) if done else None})
        return rows

    def barred_auto(self, now: float | None = None) -> list[dict]:
        """0.32.21 (pedido do dono: "essas moedas que foram barradas e subiram já entrar automático, no fictício, nunca no
        real, explicando o motivo"): token do Explorar barrado por um filtro que NÃO é de segurança, que já subiu +X% desde
        que foi visto (e volume ≥ $Y, se configurado), entra na FICTÍCIA com as regras do botão Comprar. Um por token.
        0.32.31 (pedido do dono: "tem alguns que não foram, eles sempre devem ir na fictícia"): cada barrado guarda o que o
        automático fez com ele (`auto_st`: entrou / por que não), só marca como feito quando a compra saiu de verdade e tem
        limite de posições próprio (não disputa as vagas das cópias)."""
        c = self.cfg
        if not getattr(c, "pump_bar_auto_on", False) or getattr(self, "role", None) != "admin":
            return []
        from .auto_trades import SUSPECT_PCT
        now = time.time() if now is None else now
        done = self.__dict__.setdefault("_bar_done", {})
        per_h = int(self._c("pump_bar_max_h", 4))
        hour = [x for x in done.values() if now - x < 3600]
        gain, vol_min = float(self._c("pump_bar_min_gain", 50)), float(self._c("pump_bar_min_vol_usd", 20000))
        sim_pos = {p["mint"]: p for p in self.positions() if not p.get("real")}
        out = []
        for mint, g in list((getattr(self, "_ex_funnel", None) or {}).items()):
            if g.get("entrou"):
                continue
            if now - float(g.get("t") or 0) > 3 * 3600:     # 0.32.33: 1 h → 3 h depois que saiu da lista do Explorar
                if mint not in done and self._bar_soft(g):
                    g["auto_st"] = "fora: saiu da lista do Explorar há mais de 3 h"
                continue
            if mint in done:
                g["auto_st"] = "entrou"
                continue
            why = str(g.get("why") or "")
            if not why or any(h in why.lower() for h in self.BAR_HARD):
                continue
            px, px0 = (self.tokens.get(mint) or {}).get("price"), g.get("px0")
            if not px or not px0:
                continue
            chg = (px / px0 - 1) * 100
            if chg >= SUSPECT_PCT or g.get("suspeito"):
                g["auto_st"] = "fora: alta de 20× ou mais (preço provavelmente errado)"
                continue
            vol = g.get("vol")
            if chg < gain:
                continue
            if vol_min > 0 and (vol is None or float(vol) < vol_min):
                g["auto_st"] = f"esperando: volume 24 h abaixo de ${vol_min:,.0f}"
                continue
            if mint in sim_pos:
                g["auto_st"] = "já tem na fictícia (comprado antes)"
                continue
            if now - float((self.tokens.get(mint) or {}).get("last_t") or 0) > 180:
                g["auto_st"] = "esperando preço atualizado"
                continue
            if len(hour) + len(out) >= per_h:
                g["auto_st"] = f"esperando: limite de {per_h} entradas por hora"
                continue
            motivo = (f"barrado que subiu: estava fora por \"{why[:70]}\", mas subiu {chg:+.0f}% desde que foi visto"
                      + (f" e tem ${float(vol):,.0f} de volume em 24 h" if vol is not None else "")
                      + " — entrou só na fictícia para teste")
            r = self.manual_buy(mint, t=now, auto=motivo, origem="barrado",
                                target="both" if getattr(c, "pump_bar_real", False) else "sim",
                                amt_sol=float(self._c("pump_bar_sol", 0.05)))
            if str(r.get("sim") or "").startswith("comprou"):
                done[mint] = now
                g["auto_st"] = "entrou"
                out.append({"mint": mint, "symbol": g.get("symbol"), "chg": round(chg, 1), "r": r})
            else:
                g["auto_st"] = "não entrou: " + str(r.get("error") or r.get("sim") or "?")[:80]
        return out

    FOLLOW_RULES = ("stop_pct", "tp_pct", "trail_on", "trail_start", "trail_dist", "boost_tp", "tp1_pct", "tp1_frac",
                    "max_hold_s", "smart", "press_min", "exit_grad", "manual")

    def _lead(self, ev: str, p: dict, why: str = "") -> None:
        """Avisa o hub (0.31.61) que esta conta abriu/fechou uma posição FICTÍCIA, para as contas que copiam os trades
        dela fazerem o mesmo. Posição que já veio de outra conta não é repassada (sem cópia em cadeia)."""
        if self.leader_hook is None or p.get("real") or p.get("follow_of"):
            return
        try:
            self.leader_hook(ev, copy.deepcopy(p), why)
        except Exception as e:
            log.warning("cópia de trades para outra conta: %s", str(e)[:160])

    def manual_buy(self, mint: str, t: float | None = None, auto: str = "", origem: str = "", info: dict | None = None,
                   follow: dict | None = None, target: str = "both", amt_sol: float | None = None,
                   pos_rules: dict | None = None) -> dict:
        """Compra manual (0.23.0, botão Comprar da Base da pump.fun): sem os filtros de cópia, porque foi você que
        decidiu. Sempre compra na carteira fictícia (valor de "SOL por cópia"); na real só se a execução real estiver
        ligada, pela mesma fila, limites e verificações da compra real. Depois segue stops e saídas normais."""
        t = time.time() if t is None else t
        own_auto = bool(auto) and origem in AUTO_ORIGINS
        if own_auto:
            if not self.valid_addr(mint):
                return {"error": "endereço do token inválido"}
            if origem == "explorar" and self.graduated(mint):
                return {"error": "token já graduou desde a lista do Explorar"}
            guard = self.auto_guard(mint, t)
            if guard:
                self._auto_blocked(guard, mint, origem, t)
                return {"error": guard}
        if not own_auto and not follow and origem in self.GUARD_ORIGINS:
            g = self.entry_guard(mint, t)
            if g:
                return {"error": "trava de segurança: " + g}
        tk = self.tokens.get(mint) or {}
        px = tk.get("price")
        if own_auto:
            px = self._auto_num(px)
            if px is not None and px <= 0:
                px = None
        if not px:
            return {"error": "sem preço do token agora; tente de novo em alguns segundos"}
        sym = tk.get("symbol") or short(mint)
        allpos = self.positions()
        base = {"wallet": "manual", "short": "automático" if auto else "você", "mint": mint, "symbol": sym, "kind": "buy",
                "mcap_sol": tk.get("mcap_sol")}
        out: dict = {"ok": True, "sim": None, "real": None}
        amt = float(self._c("pump_ar_sol", 0.05) if own_auto else self._c("pump_manual_sol", 0.1))
        if amt_sol:
            amt = float(amt_sol)                    # 0.32.21: valor próprio (entrada automática dos barrados que subiram)
        if own_auto and origem == "explorar" and (info or {}).get("veredito") == "possível":
            amt *= float(self._c("pump_ex_possivel_pct", 50)) / 100      # 0.31.99, item 2: "possível" entra com menos
        rules = self.auto_rules() if own_auto else (pos_rules or self.manual_rules())   # 0.32.41: regras da Aba do Bruxo
        if follow:                                  # 0.31.61: mesmo valor e mesmas regras de saída da conta copiada
            amt = float(follow.get("sol") or amt)
            rules = dict(follow.get("rules") or rules)
        fr = self._fee_rates(mint)
        sim_pos = None
        # 0.32.160 (pedido do dono: "a real sempre primeiro"): na cópia exata os limites e o saldo da fictícia não barram; quem
        # decide é a real. A fictícia que passar do limite dela só fica se a real comprar (ver o fim desta função).
        exact = self.exact_on() and target != "sim" and origem != "boostmig"   # 0.32.399: cópia exata não desfaz a fictícia do BOOST
        over = None
        if exact:
            if len([p for p in allpos if not p.get("real") and self._slot(p.get("origem")) == self._slot(origem)]) >= (
                    int(self._c(self.OWN_SLOTS[self._slot(origem)][0], self.OWN_SLOTS[self._slot(origem)][1]))
                    if self._slot(origem) else int(self._c("pump_max_open", 10))):
                over = "limite de posições da fictícia"
            elif self.wallet()["cash_sol"] < amt + fr["prio"]:
                over = "saldo fictício insuficiente"
        # 0.32.21 (pedido do dono): o botão Comprar escolhe a carteira — "sim" (só fictícia), "real" (só real) ou "both"
        sim_off = not getattr(self.cfg, "pump_sim_on", True)     # 0.32.198: chave geral da FICTÍCIA
        if target == "real":
            out["sim"] = "não pedida (só real)"
        elif sim_off:
            out["sim"] = "carteira FICTÍCIA desligada"
        elif any(p["mint"] == mint and not p.get("real") for p in allpos):
            out["sim"] = "já tem posição fictícia neste token"
        elif not exact and len([p for p in allpos if not p.get("real") and self._slot(p.get("origem")) == self._slot(origem)]) >= (
                int(self._c(self.OWN_SLOTS[self._slot(origem)][0], self.OWN_SLOTS[self._slot(origem)][1]))
                if self._slot(origem) else int(self._c("pump_max_open", 10))):
            # 0.32.31: os barrados têm vagas próprias (pump_bar_max_open) e não tiram vaga das cópias; 0.32.41: a Aba do Bruxo também
            out["sim"] = "limite de posições abertas na FICTÍCIA" + (self.OWN_SLOTS[self._slot(origem)][2] if self._slot(origem) else f" ({int(self._c('pump_max_open', 10))})")
        elif not exact and self.wallet()["cash_sol"] < amt + fr["prio"]:
            out["sim"] = "saldo fictício insuficiente"
        else:
            slip, prio, fee = fr["slip"], fr["prio"], fr["venue"] + fr["portal"]
            price_in, net_in = px * (1 + slip), amt * (1 - fee)
            tokens = net_in / price_in
            score, sparts = self.entry_score("manual", mint, None, px)
            p = {"opened_at": now_iso(), "open_t": t, "wallet": "manual", "mint": mint, "symbol": sym,
                 "sol_in": round(amt + prio, 9), "tokens": tokens, "tokens_left": tokens, "price_in": price_in,
                 "price_now": px, "trader_price": px, "trader_sol": 0.0, "proceeds": 0.0, "fees_sol": amt * fee + prio,
                 "mcap_in": tk.get("mcap_sol"), "real": False, "venue_in": fr["venue_name"], "lag_s": None,
                 "score": score, "score_parts": sparts, "grad_in": self.graduated(mint), "manual": True, **rules,
                 "auto": auto or None}
            if origem and not own_auto:
                p["origem"] = origem                # 0.32.21: ex.: "barrado" (entrada automática só fictícia)
            if follow:
                p["follow_of"] = {"user": follow.get("leader"), "pos": follow.get("pos"), "nome": follow.get("nome")}
            if own_auto:
                p.update(auto=True, origem=origem, auto_info=copy.deepcopy(info or {}),
                         opened_at=datetime.fromtimestamp(t, timezone.utc).isoformat())
                p["auto_info"]["score"] = score
            self._addfee(p, platform=amt * fr["venue"], portal=amt * fr["portal"], network=prio,
                         slippage=net_in - net_in / (1 + slip))
            self._save_pos(p)
            sim_pos = p
            if own_auto:
                out["auto_id"] = str(p["id"])
                if origem == "explorar":
                    self.ghosts_auto.on_open(p, t)
            self._feed(**base, sol=round(amt, 4), action="comprou (automático)" if auto else "comprou (manual)",
                       reason=(f"{auto} · " if auto else "você ") + f"comprou {amt:.3f} SOL a {price_in:.3e} · nota {score:.0f}")
            self._emit(f"[PUMP SIM] compra {'automática' if auto else 'manual'}: {sym} {amt:.3f} SOL" + (f" ({auto})" if auto else ""))
            out["sim"] = f"comprou {amt:.3f} SOL na carteira fictícia"
        st = {"tried": False, "sent": False}
        try:
            # 0.32.3 — sugestão do Bruxo (28/10, SPCX): a fictícia JÁ TER o token não é falha; a real tem posições separadas e
            # pode entrar mesmo assim. Qualquer outro motivo da fictícia (limite, saldo) continua barrando a real automática.
            sim_has = out["sim"] == "já tem posição fictícia neste token"
            if own_auto and not out.get("auto_id") and not sim_has:
                return out                              # uma falha fictícia não dispara compra real automática
            if sim_off and auto and origem != "boostmig":    # 0.32.399: o BOOST só obedece às Regras do BOOST
                return out                              # 0.32.198: as telas automáticas seguem a fictícia; sem ela, não compram sozinhas na real
            bar_real = origem == "barrado" and getattr(self.cfg, "pump_bar_real", False)    # 0.32.33: botão "Também na REAL"
            bx_real = origem == "bruxo" and getattr(self.cfg, "pump_bx_real", False)       # 0.32.41: Aba do Bruxo, REAL só se ligar
            if origem == "bruxo" and not bx_real:
                return out
            # 0.32.61: cada compra automática só vai para a REAL com o botão REAL da própria aba (o espelho não basta)
            gate = {"calls": "pump_calls_real", "elite": "pump_el_real", "base": "pump_auto_real", "": "pump_auto_real"}.get(origem)
            if auto and not follow and gate and not getattr(self.cfg, gate, False):
                if self.real is not None and getattr(self.cfg, "pump_real_enabled", False):
                    out["real"] = "REAL desligada nesta aba (só fictícia)"
                return out
            if (origem == "barrado" and not bar_real) or (target == "sim" and not bar_real and not bx_real):
                return out                              # só fictícia (Calls 0.31.99; barrados 0.32.21, a não ser que ligue a REAL)
            if target == "real" and not (self.real is not None and getattr(self.cfg, "pump_real_enabled", False)):
                out["real"] = "execução real desligada"
                return out
            # 0.32.325: trava por tela nas compras que o robô faz sozinho (o seu clique no botão Comprar não passa por ela)
            if origem in self.GATE_ORIGINS or (auto and not origem) or follow:
                gw = self.tab_gate_why(self.aba_of({"wallet": "manual", "origem": origem or ("base" if auto and not follow else ""),
                                                    "follow_of": follow or None}))
                if gw:
                    if self.real is not None and getattr(self.cfg, "pump_real_enabled", False):
                        out["real"] = gw
                        self._feed(**base, action="REAL não copiou", reason=gw, sim_id=(sim_pos or {}).get("id"))
                    return out
            mirror = getattr(self.cfg, "pump_real_mirror", True)
            if own_auto and origem == "explorar" and not getattr(self.cfg, "pump_ex_real_on", True):
                if self.real is not None and getattr(self.cfg, "pump_real_enabled", False):
                    out["real"] = "desligada nas Proteções das automáticas (só fictícia)"
                    self._feed(**base, action="REAL não copiou", reason="Explorar: 'Também na carteira REAL' desligado (só fictícia)",
                               sim_id=(sim_pos or {}).get("id"))
                return out
            if origem == "boostmig" and not getattr(self.cfg, "pump_bm_real", False):
                return out                              # 0.32.373: BOOST da migração só vai para a REAL com a chave da aba
            jt_real = origem == "jevtrade" and target == "both" and getattr(self.cfg, "pump_jt_real", False)   # 0.32.97
            # 0.32.393 (dono, DATACENTER 20/11 22:22): o BOOST com "Também na REAL" ligado não comprava na REAL quando o espelho
            # e a Base automática na REAL estavam desligados — saía aqui sem aviso. A chave do BOOST basta (a de cima já conferiu).
            bm_real = origem == "boostmig"
            real_ok = self.real is not None and getattr(self.cfg, "pump_real_enabled", False)
            if real_ok and auto and not (mirror or jt_real or bm_real or getattr(self.cfg, "pump_auto_real", False)):
                out["real"] = "espelho e compra automática na REAL desligados (só fictícia)"
                self._feed(**base, action="REAL não copiou", reason=out["real"], sim_id=(sim_pos or {}).get("id"))
            if real_ok and (not auto or mirror or jt_real or bm_real or getattr(self.cfg, "pump_auto_real", False)):
                st["tried"] = True
                self._real_buying.prune()
                if any(p["mint"] == mint and p.get("real") for p in allpos) or mint in self._real_buying:
                    out["real"] = "já tem posição REAL neste token"
                elif origem != "boostmig" and len([p for p in allpos if p.get("real")]) + len(self._real_buying) >= int(self._c("pump_real_max_open", 5)):
                    out["real"] = f"limite de {int(self._c('pump_real_max_open', 5))} posições reais"
                elif own_auto and not mirror and (guard := self.auto_guard(t=t)):
                    out["real"] = guard
                    self._auto_blocked(guard, mint, origem, t)
                else:
                    self._real_buying.add(mint)
                    st["sent"] = True
                    if own_auto:
                        self._auto_pending[mint] = t
                    self._rq_put(("buy", {"wallet": "manual", "mint": mint, "symbol": sym, "trader_sol": 0.0, "amt_sol": amt_sol,
                                          "trader_price": px, "mcap_in": tk.get("mcap_sol"), "t": t, "block_t": t,
                                          "sim_id": (sim_pos or {}).get("id") if mirror and sim_pos else None,
                                          "pos_cfg": {**rules, "manual": True,
                                                      **({"origem": origem} if origem else {}),   # 0.32.101: Jev Trade etc.
                                                      **({"auto": True, "origem": origem,
                                                          "auto_info": copy.deepcopy((sim_pos or {}).get("auto_info") or info or {})} if own_auto else {})}}))
                    self._feed(**base, action="REAL: comprando", reason="compra manual enviada para a fila real"
                               + (" · a fictícia já tinha este token; a real entra separada" if sim_has else ""))
                    out["real"] = f"enviando compra real de até {float(self._c('pump_real_max_sol', 0.05)):.3f} SOL"
            return out
        finally:
            # 0.32.160 (cópia exata): a fictícia só fica se a real comprou; senão é desfeita (dinheiro volta, não vira trade)
            if sim_pos is not None:
                if (st["tried"] or over) and not st["sent"] and self.exact_on():
                    self._cancel_sim(sim_pos["id"], out.get("real") or over or "a real não comprou")
                    out["sim"] = "desfeita: cópia exata — a real não comprou" + (f" ({out['real']})" if out.get("real") else "")
                    out.pop("auto_id", None)
                else:
                    self._lead("open", sim_pos)

    @staticmethod
    def parse_orders(js, now: float | None = None) -> dict:
        """Pedidos pagos na DexScreener (GET /orders/v1/solana/{token}, documentado em docs.dexscreener.com; formato
        conferido em 2026-10-26): "boosts" (valor e hora do pagamento) e "orders" (perfil, anúncio, CTO…).
        Boost ON = algum boost pago nas últimas 24 h (a duração exata do boost não é documentada: estimativa)."""
        now = now or time.time()
        js = js if isinstance(js, dict) else {}
        day = (now - 86400) * 1000
        bs = [b for b in js.get("boosts") or [] if isinstance(b, dict)]
        recent = [b for b in bs if float(b.get("paymentTimestamp") or 0) >= day]
        paid = sorted({str(o.get("type")) for o in js.get("orders") or [] if isinstance(o, dict)
                       and o.get("status") in ("approved", "processing", "on-hold")
                       and float(o.get("paymentTimestamp") or 0) >= (now - 7 * 86400) * 1000})
        last = max([float(b.get("paymentTimestamp") or 0) for b in bs] or [0]) / 1000
        return {"t": now, "active": bool(recent), "amount_24h": sum(int(b.get("amount") or 0) for b in recent),
                "boosts_total": len(bs), "last_boost": last or None, "paid": paid}

    async def fetch_explore(self, key: str) -> dict | None:
        """Explorar (0.28.0): listas novos / quase graduando / graduados da Solana Tracker (ver app/explore.py)."""
        from .explore import URL, parse
        if not key:
            return None
        r = await self.http.get(URL, params={"limit": 40, "reduceSpam": "true"},
                                headers={"x-api-key": key, "Accept": "application/json"}, timeout=20)
        if r.status_code != 200:
            raise RuntimeError(f"Solana Tracker respondeu HTTP {r.status_code}")
        return parse(r.json())

    async def fetch_boost(self, mint: str) -> dict | None:
        try:
            r = await self.http.get(f"https://api.dexscreener.com/orders/v1/solana/{mint}", timeout=10)
            if r.status_code != 200:
                return None
            info = self.parse_orders(r.json())
        except Exception:
            return None
        self.market.boosts[mint] = info
        return info

    def boost_info(self, mint: str) -> dict:
        b = dict(self.market.boosts.get(mint) or {})
        if (self.tokens.get(mint) or {}).get("boost_active"):
            b["active"], b["pair_active"] = True, int(self.tokens[mint]["boost_active"])
        return b

    def auto_check(self, rising: list[dict], t: float | None = None) -> list[str]:
        """Compra automática da Base da pump.fun (0.27.0, pedido do dono: "não vamos estar online"). Roda no servidor a
        cada ~20 s. Entra com os valores do botão Comprar quando o token (até X min de vida, sem veredito lixo/suspeito)
        está com Boost ON e/ou com previsão "chance alta". No máx. N por hora e uma vez por token."""
        if not getattr(self.cfg, "pump_auto_on", False):
            return []
        t = t or time.time()
        done = self.__dict__.setdefault("_auto_done", {})
        recent = [x for x in done.values() if t - x < 3600]
        out = []
        for x in rising:
            mint, pred = x["mint"], x.get("pred") or {}
            lab = x.get("symbol") or short(mint)
            if len(recent) >= int(self._c("pump_auto_max_h", 5)):
                self.rlog("base", mint, lab, f"limite de {int(self._c('pump_auto_max_h', 5))} compras por hora", t)   # 0.31.89
                break
            if mint in done:
                continue
            if pred.get("verdict") in ("lixo", "suspeito"):
                self.rlog("base", mint, lab, f"veredito {pred.get('verdict')}", t)
                continue
            if x.get("age_min", 99) > float(self._c("pump_auto_max_age", 45)):
                self.rlog("base", mint, lab, f"token velho demais (mais de {float(self._c('pump_auto_max_age', 45)):g} min)", t)
                continue
            safe = self.auto_safety(mint, x.get("age_min"))
            if safe:
                self.rlog("base", mint, lab, safe, t)
                continue                                    # 0.31.0: idade mínima, carteiras novas, trader bom
            why = []
            if getattr(self.cfg, "pump_auto_boost", True) and (x.get("boost") or {}).get("active"):
                why.append("Boost ON")
            if getattr(self.cfg, "pump_auto_chance", False) and pred.get("verdict") == "chance alta":
                why.append(f"chance alta ({pred.get('chance') or 0:.0f}%)")
            if not why:
                self.rlog("base", mint, lab, "sem gatilho (nem Boost ON nem chance alta ligada)", t)
                continue
            done[mint] = t
            r = self.manual_buy(mint, t, auto="automático: " + " + ".join(why))
            if r.get("error") or (r.get("sim") or "").startswith(("já tem", "limite", "saldo")):
                self.rlog("base", mint, lab, r.get("error") or r.get("sim"), t)
                if r.get("error"):
                    done.pop(mint, None)                    # sem preço ainda: tenta de novo na próxima volta
                continue
            self.rlog("base", mint, lab, None, t)
            recent.append(t)
            out.append(mint)
        return out

    def elite_auto(self, s: dict, t: float | None = None) -> dict | None:
        """Maiores traders (0.31.2): compra sozinho no sinal, com as proteções das automáticas (pump_ar_*)."""
        if getattr(self, "role", "admin") != "admin":
            return None
        r = self._elite_auto(s, t)
        # 0.31.89: log de análise de cada sinal (entrou ou por que não)
        lab = s.get("symbol") or short(s["mint"])
        why = ("compra automática desligada" if r is None and not getattr(self.cfg, "pump_el_auto_on", False)
               else "sinal fora das regras (compra grande desligada ou poucas carteiras)" if r is None
               else None if r.get("auto_id") else (r.get("error") or r.get("sim") or "não entrou"))
        self.rlog("elite", str(s.get("id") or s["mint"]), lab, why, t)
        return r

    def _elite_auto(self, s: dict, t: float | None = None) -> dict | None:
        if not getattr(self.cfg, "pump_el_auto_on", False):
            return None
        big = s.get("reason", "").startswith("compra grande")
        if big and not getattr(self.cfg, "pump_el_auto_big", False):
            return None
        if not big and len(s.get("wallets") or []) < int(self._c("pump_el_auto_min_wallets", 2)):
            return None
        fr = (self.tokens.get(s["mint"]) or {}).get("fresh")
        if fr and getattr(self.cfg, "pump_ar_fresh_on", True) and fr["pct"] >= float(self._c("pump_ar_fresh_max_pct", 30)):
            return {"error": "muitas carteiras novas entre os maiores detentores"}
        info = {"veredito": "sinal dos maiores traders", "chance": None, "wallets": list(s.get("wallets") or []),
                "names": list(s.get("names") or []), "sinal": s.get("id"), "why": [s.get("reason")], "sol_traders": s.get("sol")}
        return self.manual_buy(s["mint"], t, auto="maiores traders: " + ", ".join((s.get("names") or [])[:3]),
                               origem="elite", info=info)

    def elite_sell(self, w: str, mint: str, name: str, t: float | None = None) -> list[str]:
        """Um trader do sinal vendeu: as compras automáticas desse sinal saem junto (opção pump_el_follow_sell)."""
        if not getattr(self.cfg, "pump_el_follow_sell", True):
            return []
        t = time.time() if t is None else t
        px = (self.tokens.get(mint) or {}).get("price")
        out = []
        for p in self.positions():
            if p.get("origem") == "elite" and p["mint"] == mint and not p.get("selling") \
                    and w in ((p.get("auto_info") or {}).get("wallets") or []):
                out.append(self._sell(p, 1.0, px or p.get("price_now"), f"trader da elite vendeu ({name})", t))
        return [m for m in out if m]

    # 0.32.41: origens com vagas próprias (opção do limite, padrão, texto do aviso)
    OWN_SLOTS = {"barrado": ("pump_bar_max_open", 20, " dos barrados"), "bruxo": ("pump_bx_max_open", 5, " da Aba do Bruxo"),
                 "lancamento": ("pump_lanc_max_open", 30, " dos lançamentos"),
                 "jevtrade": ("pump_jt_wallet_max", 10, " do Jev Trade"),
                 "boostmig": ("pump_bm_max_open", 3, " do BOOST da migração")}       # 0.32.93: entradas do Jev Trade na fictícia   # 0.32.78: Comprar todas não esbarra nas vagas das cópias

    def _slot(self, origem) -> str | None:
        o = str(origem or "")
        return o if o in self.OWN_SLOTS else None

    # ------------------------------------------------------------------ Aba do Bruxo (0.32.41)
    def bruxo_rules(self) -> dict:
        """Saída do prompt do Bruxo: vende 50% em +100% e deixa o resto no stop móvel; + stop de perda e tempo máximo."""
        tp1 = float(self._c("pump_bx_tp1_pct", 100))
        return {"stop_pct": float(self._c("pump_bx_stop_pct", 30)), "tp_pct": 0.0, "trail_on": True,
                "trail_start": tp1, "trail_dist": float(self._c("pump_bx_trail_dist", 20)), "boost_tp": None,
                "tp1_pct": tp1, "tp1_frac": float(self._c("pump_bx_tp1_frac", 50)),
                "max_hold_s": float(self._c("pump_bx_max_hold_min", 25)) * 60, "smart": False,
                "cx_pct": float(self._c("pump_bx_grad_exit", 0)) or None}

    def bruxo_reason(self, s: dict, f: dict, t: float) -> str | None:
        """Por que NÃO entrar neste sinal (None = entra). `f` = números do token lidos na hora do sinal."""
        if getattr(self, "role", "admin") != "admin":
            return "só para admin"
        if not getattr(self.cfg, "pump_bx_on", False):
            return "Aba do Bruxo desligada"
        mint = s["mint"]
        if f.get("graduated"):
            return "token já graduou"
        mx = float(self._c("pump_bx_max_age_min", 5))
        if f.get("age_min") is None:
            return "idade do token desconhecida (a criação não foi vista)"
        if f["age_min"] > mx:
            return f"token com {f['age_min']:.1f} min (máximo {mx:g})"
        mn = float(self._c("pump_bx_min_trader_sol", 0.2))
        if f.get("trader_sol", 0) < mn:
            return f"compra do trader pequena ({f.get('trader_sol', 0):.3f} SOL; mínimo {mn:g})"
        if mint in self.market.blacklist or (f.get("creator") and f["creator"] in self.market.blacklist):
            return "token ou criador na lista negra"
        cs = self.market.creator_stats.get(f.get("creator") or "") or {}
        if cs.get("rugs", 0) >= 2 or cs.get("bundles", 0) >= 2:
            return "criador com 2+ tokens que despencaram ou bundle"
        cm = float(self._c("pump_bx_curve_max", 100))
        prog = self.curve_progress(f.get("mcap")) if f.get("mcap") else None
        if cm < 100 and prog is not None and prog > cm:
            return f"curva em {prog:.0f}% (só entra no começo, até {cm:g}%)"
        mc = float(self._c("pump_bx_min_mcap", 32))
        if mc and (f.get("mcap") or 0) < mc:
            return f"pouca liquidez (market cap {f.get('mcap') or 0:.1f} SOL; mínimo {mc:g})"
        dv = float(self._c("pump_bx_dev_max", 10))
        if f.get("dev_pct") is not None and f["dev_pct"] > dv:
            return f"criador com {f['dev_pct']:.1f}% do token (máximo {dv:g}%)"
        mult = float(self._c("pump_bx_flow_mult", 1))
        if mult and f.get("flow") is not None and f.get("flow_base"):
            if f["flow"] < f["flow_base"] * mult:
                return f"ritmo de compra {f['flow']:.1f} SOL/min abaixo da média inicial ({f['flow_base']:.1f} x {mult:g})"
        top = float(self._c("pump_bx_top10_max", 35))
        # 0.32.58 (dono: "cadê as compras da Aba do Bruxo?"): o RPC grátis quase não responde e TODO sinal parava aqui; sem a
        # leitura dos detentores a entrada segue (os outros filtros e a trava de segurança continuam valendo)
        if f.get("top10") is not None and f["top10"] > top:
            return f"10 maiores detentores com {f['top10']:.0f}% (máximo {top:g}%)"
        if any(p["mint"] == mint and not p.get("real") for p in self.positions()):
            return "já tem posição fictícia neste token"
        done = self.__dict__.setdefault("_bx_done", {})
        for k in [k for k, v in done.items() if t - v > 86400]:
            done.pop(k)
        if mint in done:
            return "já entrou neste token nas últimas 24 h"
        hr = [v for v in done.values() if t - v < 3600]
        if len(hr) >= int(self._c("pump_bx_max_h", 6)):
            return f"limite de {int(self._c('pump_bx_max_h', 6))} entradas por hora"
        return None

    def bruxo_entry(self, s: dict, f: dict, t: float | None = None) -> str | None:
        """Entra no sinal (fictícia; REAL só com pump_bx_real). Devolve None se entrou, senão o motivo."""
        t = time.time() if t is None else t
        why = self.bruxo_reason(s, f, t)
        if why:
            return why
        r = self.manual_buy(s["mint"], t, auto="Aba do Bruxo: top trader " + ", ".join(s["names"][:2]), origem="bruxo",
                            target="sim", amt_sol=float(self._c("pump_bx_sol", 0.05)), pos_rules=self.bruxo_rules())
        p = next((p for p in self.positions() if p["mint"] == s["mint"] and p.get("origem") == "bruxo" and not p.get("real")), None)
        if p is None:
            return r.get("error") or r.get("sim") or "não entrou"
        p["bruxo"] = {"sinal": s["id"], "wallets": list(s["wallets"]), "names": list(s["names"]),
                      **{k: f.get(k) for k in ("age_min", "flow", "flow_base", "top10", "dev_pct", "mcap", "trader_sol")}}
        self._save_pos(p)
        self.__dict__.setdefault("_bx_done", {})[s["mint"]] = t
        return None

    def bruxo_sell(self, w: str, mint: str, name: str, t: float | None = None) -> list[str]:
        """O top trader do sinal vendeu: a posição da Aba do Bruxo sai junto (pump_bx_follow_sell)."""
        if not getattr(self.cfg, "pump_bx_follow_sell", True):
            return []
        t = time.time() if t is None else t
        px = (self.tokens.get(mint) or {}).get("price")
        out = []
        for p in self.positions():
            if p.get("origem") == "bruxo" and p["mint"] == mint and not p.get("selling") \
                    and w in ((p.get("bruxo") or {}).get("wallets") or []):
                out.append(self._sell(p, 1.0, px or p.get("price_now"), f"top trader do sinal vendeu ({name})", t))
        return [m for m in out if m]

    def manual_rules(self) -> dict:
        """Stop, alvo e stop móvel que o botão Comprar grava na posição (configurados na Base da pump.fun)."""
        return {"stop_pct": float(self._c("pump_manual_stop_pct", 30)),
                "tp_pct": float(self._c("pump_manual_tp_pct", 100)),
                "trail_on": bool(getattr(self.cfg, "pump_manual_trail_on", True)),
                "trail_start": float(self._c("pump_manual_trail_start", 30)),
                "trail_dist": float(self._c("pump_manual_trail_dist", 15)),
                "boost_tp": float(self._c("pump_manual_boost_tp", 80)) if getattr(self.cfg, "pump_manual_boost_on", True) else None}

    def uncopiable(self, w: str, now: float | None = None) -> str | None:
        """0.32.57 (análise das 26 carteiras em estudo): o "acerto de 99%" de quem cria o próprio token e vende em segundos
        não passa para quem copia — a cópia chega depois e é para ela que eles vendem. Devolve o motivo, ou None."""
        now = time.time() if now is None else now
        cs = self.market.creator_stats.get(w) or {}
        mn = int(self._c("pump_nc_launch_min", 20))
        if cs.get("tokens", 0) >= mn:
            return f"lançador de token: criou {cs['tokens']} tokens (vistos pela Base em 14 dias)"
        st = self.wallets.get(w) or {}
        day = sum(1 for x in (st.get("trades") or []) if now - x <= 86400)
        hf = int(self._c("pump_nc_hft_day", 150))
        if day >= hf:
            return f"robô de alta frequência: {day} trades em 24 h"
        holds = sorted(c["hold"] for c in (st.get("closed") or []) if now - c.get("t", 0) <= 7 * 86400 and c.get("hold") is not None)
        hm = float(self._c("pump_nc_hold_min_s", 30))
        if hm and len(holds) >= 8 and holds[len(holds) // 2] < hm:
            return f"segura {holds[len(holds) // 2]:.0f} s na mediana (menos que o atraso da cópia)"
        return None

    def blacklist_add(self, addr: str, tipo: str, motivo: str) -> None:
        """Lista negra COMPARTILHADA (0.20.0): o que um usuário descobre protege todos. Entra sozinho o criador de
        token que deu rug ou que vendeu e deixou a cópia no prejuízo; o admin também adiciona e remove."""
        bl = self.market.blacklist
        if not addr or addr in bl:
            return
        bl[addr] = {"tipo": tipo, "motivo": motivo[:120], "criado_em": now_iso()}
        self.market.bl_new.append(addr)

    def blacklist_block(self, who: str, mint: str) -> str | None:
        if not getattr(self.cfg, "pump_blacklist_on", False):
            return None
        bl = self.market.blacklist
        cr = (self.tokens.get(mint) or {}).get("creator")
        if cr and cr in bl:
            return f"criador na lista negra ({bl[cr].get('motivo')})"
        if who in bl:
            return f"trader na lista negra ({bl[who].get('motivo')})"
        return None

    def cold_market(self) -> str:
        """Mercado frio (0.19.0): as últimas 10 cópias fictícias fechadas nas últimas 2 h acertaram pouco."""
        mn = self._onv("pump_cold_on", "pump_cold_wr")
        if not mn:
            return ""
        lim = time.time() - 7200
        last = [x for x in self.trades(200) if not x.get("real")
                and not (x.get("auto") is True and x.get("origem") in AUTO_ORIGINS)
                and (self._ts(x.get("closed_at")) or 0) >= lim][:10]
        if len(last) < 5:
            return ""
        wr = sum(1 for x in last if (x.get("pnl_sol") or 0) > 0) / len(last) * 100
        return f"×0,5: mercado frio (acerto {wr:.0f}% nas últimas {len(last)} cópias em 2 h)" if wr < mn else ""

    def _streak_check(self, tr: dict) -> None:
        if tr.get("auto") is True and tr.get("origem") in AUTO_ORIGINS:
            return
        if not getattr(self.cfg, "pump_streak_on", False) or (tr.get("pnl_sol") or 0) >= 0:
            return
        n = int(self._c("pump_streak_n", 4))
        last = [x for x in self.trades(max(50, n)) if bool(x.get("real")) == bool(tr.get("real"))
                and not (x.get("auto") is True and x.get("origem") in AUTO_ORIGINS)][:n]
        if len(last) >= n and all((x.get("pnl_sol") or 0) < 0 for x in last):
            hrs = float(self._c("pump_streak_h", 2))
            self._halt_until = time.time() + hrs * 3600
            self._emit(f"Pump.fun: {n} perdas seguidas — robô PAUSADO por {hrs:g} h (novas cópias)")

    def _onv(self, on_key: str, val_key: str) -> float:
        """Valor de uma opção com botão ON/OFF: 0 quando desligada (ou com 0 no campo)."""
        return float(self._c(val_key, 0) or 0) if getattr(self.cfg, on_key, False) else 0.0

    def chase_block(self, trader_px: float | None, now_px: float | None) -> str | None:
        """Não "correr atrás" do preço (pesquisa de 2026-10-25): quem copia entra depois e mais caro, e é essa
        diferença que faz o copiador perder mesmo quando o trader ganha. 0 desliga."""
        mx = self._onv("pump_chase_on", "pump_max_chase_pct")
        if not mx or not trader_px or not now_px or now_px <= trader_px * (1 + mx / 100):
            return None
        return f"preço já subiu {(now_px / trader_px - 1) * 100:.0f}% desde a compra do trader (máx. {mx:.0f}%)"

    @staticmethod
    def parse_flow(js) -> dict | None:
        """Estatísticas por janela da Solana Tracker. Formato não confirmado em documentação pública (2026-10-25):
        lê de forma defensiva e devolve None se não reconhecer — nada depende disso para funcionar."""
        if not isinstance(js, dict):
            return None
        out = {}
        for key, name in (("5m", "m5"), ("1h", "h1"), ("24h", "h24")):
            w = js.get(key)
            if not isinstance(w, dict):
                continue
            vol = w.get("volume") if isinstance(w.get("volume"), dict) else {}

            def num(x):
                return float(x) if isinstance(x, (int, float)) else None
            out[name] = {"buyers": num(w.get("buyers")), "sellers": num(w.get("sellers")),
                         "buys": num(w.get("buys")), "sells": num(w.get("sells")),
                         "buy_vol": num(vol.get("buys")), "sell_vol": num(vol.get("sells"))}
        return out or None

    def pressure(self, mint: str) -> tuple[float | None, str]:
        """% de compras na janela mais recente com movimento: volume de compra (Solana Tracker) se houver; senão
        número de compras × vendas da DexScreener (5 min com 10+ negociações, senão 1 h)."""
        tk = self.tokens.get(mint) or {}
        for w in ("m5", "h1"):
            f = ((tk.get("flow") or {}).get(w)) or {}
            if f.get("buy_vol") is not None and f.get("sell_vol") is not None and f["buy_vol"] + f["sell_vol"] > 0:
                return f["buy_vol"] / (f["buy_vol"] + f["sell_vol"]) * 100, f"volume {w.replace('m', '').replace('h', '')}{'min' if w == 'm5' else 'h'}"
        v = tk.get("vol") or {}
        for w, mn in (("m5", 10), ("h1", 1)):
            b, s = int(v.get("buys_" + w) or 0), int(v.get("sells_" + w) or 0)
            if b + s >= mn:
                return b / (b + s) * 100, ("negociações 5 min" if w == "m5" else "negociações 1 h")
        return None, ""

    GUARD_ORIGINS = ("", "barrado", "barrado_btn", "bruxo", "lancamento")     # 0.32.53: botão Comprar, barrados e Aba do Bruxo

    def entry_guard(self, mint: str, t: float | None = None) -> str | None:
        """0.32.53: trava das entradas que não são cópia nem Explorar. Um stop não protege de queda de uma vez (o próximo preço
        já vem −92%): o que protege é não entrar em token graduado com preço não confirmado, pouca liquidez ou cara de despejo."""
        if not getattr(self.cfg, "pump_guard_on", False):
            return None
        t = time.time() if t is None else t
        tk = self.tokens.get(mint) or {}
        if self.graduated(mint) or tk.get("main_dex") not in (None, "pumpfun"):
            if tk.get("main_dex") in (None, "pumpfun"):
                return "token graduado sem preço confirmado da PumpSwap/DEX"
            if t - float(tk.get("last_t") or 0) > 30:
                return f"preço do token graduado velho ({t - float(tk.get('last_t') or 0):.0f} s; máximo 30 s)"
            mn = float(self._c("pump_guard_min_liq_usd", 15000))
            if mn and (tk.get("liq_usd") is None or float(tk["liq_usd"]) < mn):
                return f"liquidez baixa (US$ {float(tk.get('liq_usd') or 0):,.0f}; mínimo US$ {mn:,.0f})"
        return self.dump_block(mint, force=True)

    def dump_block(self, mint: str, force: bool = False) -> str | None:
        """0.32.50: não copiar token com cara de despejo — concentração nos 10 maiores, fatia do criador e carteiras novas.
        Sem a leitura dos detentores (RPC não respondeu), não bloqueia: só os números lidos contam."""
        if not (force or getattr(self.cfg, "pump_dump_on", False)) or not self.is_pump(mint):
            return None
        tk = self.tokens.get(mint) or {}
        top = float(self._c("pump_dump_top10_max", 35))
        if tk.get("top10_pct") is not None and time.time() - float(tk.get("top10_t") or 0) < 600 and tk["top10_pct"] > top:
            return f"despejo: 10 maiores detentores com {tk['top10_pct']:.0f}% (máximo {top:g}%)"
        cr = tk.get("creator")
        if cr:
            dp = ((self.market.wallets.get(cr) or {}).get("pos") or {}).get(mint) or {}
            dev = float(dp.get("tok") or 0) / 1e9 * 100
            dv = float(self._c("pump_dump_dev_max", 10))
            if dev > dv:
                return f"despejo: criador com {dev:.1f}% do token (máximo {dv:g}%)"
        fr = tk.get("fresh")
        fx = float(self._c("pump_dump_fresh_max", 30))
        if fr and fr.get("pct", 0) > fx:
            return f"despejo: {fr['pct']:.0f}% de carteiras novas entre os maiores detentores (máximo {fx:g}%)"
        return None

    def flow_block(self, mint: str) -> str | None:
        mn = self._onv("pump_buy_pressure_on", "pump_min_buy_pressure_pct")
        if not mn:
            return None
        pr, src = self.pressure(mint)
        if pr is not None and pr < mn:
            return f"pressão de compra fraca: {pr:.0f}% de compras ({src}; mínimo {mn:.0f}%)"
        return None

    def token_card(self, mint: str) -> dict:
        """Ficha do token (painel): mercado, curva, compras × vendas, risco, maiores carteiras e o que é seu nele."""
        tk = dict(self.tokens.get(mint) or {})
        su = self.sol_usd or 0
        fol = set(self.followed)
        holders = [{**h, "creator": h["owner"] == tk.get("creator"), "followed": h["owner"] in fol}
                   for h in tk.get("holders_top") or []]
        pr, src = self.pressure(mint)
        mine = [p for p in self.positions() if p["mint"] == mint]
        trades = [t for t in self.trades(3000) if t.get("mint") == mint][:20]
        traders = [x for x in self.trader_positions() if x["mint"] == mint]
        return {"mint": mint, "symbol": tk.get("symbol"), "name": tk.get("name"), "price_sol": tk.get("price"),
                "mcap_sol": tk.get("mcap_sol"), "mcap_usd": (tk["mcap_sol"] * su) if tk.get("mcap_sol") and su else None,
                "liq_usd": tk.get("liq_usd"), "dex": tk.get("main_dex"), "graduated": self.graduated(mint),
                "curve_pct": None if self.graduated(mint) else self.curve_progress(tk.get("mcap_sol")),
                "age_min": round((time.time() - tk["created_t"]) / 60, 1) if tk.get("creator") and tk.get("created_t") else None,
                "vol": tk.get("vol"), "chg": tk.get("chg"), "flow": tk.get("flow"), "pressure": pr, "pressure_src": src,
                "risk": tk.get("risk"), "top10_pct": tk.get("top10_pct"), "holders": holders, "creator": tk.get("creator"),
                "my_positions": [{k: p.get(k) for k in ("symbol", "sol_in", "chg_pct", "real", "opened_at", "wallet")} for p in mine],
                "my_trades": [{k: t.get(k) for k in ("closed_at", "pnl_sol", "pnl_pct", "reason", "real", "wallet")} for t in trades],
                "traders_in": traders, "seen": bool(self.tokens.get(mint)), "boost": self.boost_info(mint)}

    def risk_block(self, tk: dict) -> str | None:
        """Nota de risco da Solana Tracker (pesquisa de 2026-10-25: copiar sem olhar o token deixa quem copia como
        "saída" de bundles e insiders). Sem chave ou sem resposta, não bloqueia — o painel mostra que não checou."""
        rk = tk.get("risk")
        if not getattr(self.cfg, "pump_risk_check", True) or not rk:
            return None
        if rk.get("rugged"):
            return "risco: token já sem liquidez (rug)"
        if rk.get("danger"):
            return "risco: " + ", ".join(rk["danger"][:3])
        mx = int(self._c("pump_max_risk_score", 7))
        if rk.get("score") is not None and rk["score"] > mx:
            return f"risco {rk['score']}/10 acima do máximo {mx}" + (f" ({', '.join(rk['warn'][:2])})" if rk.get("warn") else "")
        return None

    async def risk_check(self, mint: str, key: str) -> None:
        return await apiusage.for_mints([mint], self._risk_check_run(mint, key))     # 0.32.220

    async def _risk_check_run(self, mint: str, key: str) -> None:
        """Busca a nota de risco do token (cache de 10 min; falha tenta de novo em 1 min). Só com chave."""
        tk = self.tokens.setdefault(mint, {"created_t": time.time()})
        if not key or time.time() < (tk.get("risk_next") or 0):
            return
        tk["risk_next"] = time.time() + 60
        try:
            r = await self.http.get(TOKEN_URL + mint, headers={"x-api-key": key, "Accept": "application/json"}, timeout=8)
            if r.status_code != 200:
                return
            rk = (r.json() or {}).get("risk") or {}
        except Exception:
            return
        risks = [x for x in rk.get("risks") or [] if isinstance(x, dict)]
        score = rk.get("score")
        try:
            rs = await self.http.get(STATS_URL + mint, headers={"x-api-key": key, "Accept": "application/json"}, timeout=8)
            tk["flow"] = self.parse_flow(rs.json()) if rs.status_code == 200 else tk.get("flow")
        except Exception:
            pass
        tk["risk"] = {"score": int(score) if isinstance(score, (int, float)) else None, "rugged": bool(rk.get("rugged")),
                      "danger": [str(x.get("name"))[:60] for x in risks if x.get("level") == "danger"],
                      "warn": [str(x.get("name"))[:60] for x in risks if x.get("level") == "warn"], "t": time.time()}
        tk["risk_next"] = time.time() + 600
        if tk["risk"]["rugged"] and tk.get("creator"):
            self.blacklist_add(tk["creator"], "dev", f"token {tk.get('symbol') or short(mint)} deu rug (Solana Tracker)")

    async def holders_check(self, mint: str) -> None:
        return await apiusage.for_mints([mint], self._holders_check_run(mint))       # 0.32.220

    async def _holders_check_run(self, mint: str) -> None:
        """% do token nas 10 maiores carteiras (sem contar a curva/pool) — RPC grátis, cache de 60 s."""
        tk = self.tokens.setdefault(mint, {"created_t": time.time()})
        if time.time() - (tk.get("top10_t") or 0) < 60:
            return
        tk["top10_t"] = time.time()
        urls = []
        own = getattr(self.sol_wallet, "rpc_url", None) if self.sol_wallet is not None else None
        if own:
            urls.append(own)
        urls.append(str(self._c("pump_rpc_http", SOL_HTTP) or SOL_HTTP))

        async def rpc(method, params):
            for u in urls:
                try:
                    r = await self.http.post(u, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=8)
                    js = r.json()
                    if "result" in js:
                        return js["result"]
                except Exception:
                    continue
            return None
        sup = await rpc("getTokenSupply", [mint])
        big = await rpc("getTokenLargestAccounts", [mint])
        if not sup or not big:
            return
        total = float((sup.get("value") or {}).get("uiAmountString") or 0)
        accs = (big.get("value") or [])[:21]
        if not total or not accs:
            return
        info = await rpc("getMultipleAccounts", [[a["address"] for a in accs], {"encoding": "jsonParsed"}])
        owners = []
        for a in (info or {}).get("value") or []:
            try:
                owners.append(a["data"]["parsed"]["info"]["owner"])
            except Exception:
                owners.append(None)
        curve = self.curve_pda(mint)
        graduated = (tk.get("pool") == "pumpswap") or ("pumpswap" in (tk.get("dexes") or []))
        holders = []
        for i_, a in enumerate(accs):
            own_ = owners[i_] if i_ < len(owners) else None
            if own_ == curve:
                continue                                       # reserva da curva da pump.fun: não é holder
            holders.append(float(a.get("uiAmountString") or a.get("uiAmount") or 0))
        if graduated and holders:
            holders = holders[1:]                              # maior conta = pool da PumpSwap
        tk["top10_pct"] = round(sum(holders[:10]) / total * 100, 1)
        top = []
        for i_, a in enumerate(accs):
            own_ = owners[i_] if i_ < len(owners) else None
            if own_ == curve or not own_:
                continue
            top.append({"owner": own_, "pct": round(float(a.get("uiAmountString") or a.get("uiAmount") or 0) / total * 100, 2)})
        tk["holders_top"] = (top[1:] if graduated else top)[:12]
        tk["holder_owners"] = [h["owner"] for h in (top[1:] if graduated else top)][:20]   # 0.31.0: carteiras novas

    async def fresh_check(self, mint: str, now: float | None = None) -> dict | None:
        """Carteiras novas entre os 20 maiores detentores (0.31.0, pedido do dono: "muita carteira nova = robô inflando
        a moeda"). Nova = menos de 25 transações na vida e a primeira há menos de 72 h (RPC grátis; cache de 3 min).
        A pump.fun mostra o total de "Carteira nova" de TODOS os detentores; aqui só dá para olhar os 20 maiores."""
        now = time.time() if now is None else now
        tk = self.tokens.setdefault(mint, {"created_t": now})
        if now - float((tk.get("fresh") or {}).get("t") or 0) < 180:
            return tk.get("fresh")
        await self.holders_check(mint)
        owners = list(tk.get("holder_owners") or [])[:20]
        if not owners:
            return None
        urls = [SOL_HTTP]                          # 0.32.238: RPC público grátis (antes o Helius: ~20 consultas por token)
        fresh = checked = 0
        for w in owners:
            sigs = None
            for u in urls:
                try:
                    r = await self.http.post(u, json={"jsonrpc": "2.0", "id": 1, "method": "getSignaturesForAddress",
                                                      "params": [w, {"limit": 25}]}, timeout=8)
                    js = r.json()
                    if isinstance(js.get("result"), list):
                        sigs = js["result"]
                        break
                except Exception:
                    continue
            if sigs is None:
                continue
            checked += 1
            first = min([float(s.get("blockTime") or now) for s in sigs] or [now])
            if len(sigs) < 25 and now - first < 72 * 3600:
                fresh += 1
        if not checked:
            return None
        tk["fresh"] = {"n": fresh, "of": checked, "pct": round(fresh / checked * 100, 1), "t": now}
        return tk["fresh"]

    def smart_in(self, mint: str) -> list[str]:
        """Traders bons que estão no token agora (0.31.0, "triangulação" pedida pelo dono): carteiras que você copia,
        aptas do ranking e carteiras em estudo, com saldo do token visto pelo monitor."""
        good = set(self.followed) | set(getattr(self, "study", None) or [])
        good |= {r["wallet"] for r in self.leaderboard if r.get("eligible") and r.get("wallet")}
        return sorted(w for w in good if (((self.wallets.get(w) or {}).get("pos") or {}).get(mint) or {}).get("tok", 0) > 0)

    def auto_safety(self, mint: str, age_min: float | None, origem: str = "base") -> str | None:
        """Travas extras de TODA entrada automática (Base e Explorar), 0.31.0. No Explorar (0.31.11, pedido do dono: "tem
        muita chance alta e nada foi feito") o trader bom só é exigido com pump_ex_auto_need_smart, e carteira nova ainda
        não checada não trava (muita carteira nova já checada continua travando)."""
        mn = float(self._c("pump_ar_min_age_min", 20) or 0)
        if origem == "explorar" and float(self._c("pump_ex_min_age_min", -1)) >= 0:
            mn = float(self._c("pump_ex_min_age_min", -1))     # 0.32.36: idade mínima própria do Explorar
        if mn and age_min is not None and age_min < mn:
            return f"token com {age_min:.0f} min de vida (mínimo {mn:.0f})"
        if getattr(self.cfg, "pump_ar_fresh_on", True):
            fr = (self.tokens.get(mint) or {}).get("fresh")
            if not fr and origem != "explorar":
                return "esperando checar as carteiras novas dos maiores detentores"
            if not fr:
                fr = {"pct": 0.0, "n": 0, "of": 0}
            if fr["pct"] >= float(self._c("pump_ar_fresh_max_pct", 30)):
                return f"{fr['n']} de {fr['of']} maiores detentores são carteiras novas (robôs)"
        need_smart = getattr(self.cfg, "pump_ar_smart_on", True) if origem != "explorar" else \
            getattr(self.cfg, "pump_ex_auto_need_smart", False)
        if need_smart:
            n = len(self.smart_in(mint))
            need = int(self._c("pump_ar_smart_min", 1))
            if n < need:
                return f"nenhum trader bom no token ainda ({n} de {need})"
        return None

    def _other_block(self, mint: str) -> str | None:
        """Pode copiar este token FORA da pump.fun? (Raydium, Meteora, Orca… via Jupiter)"""
        if not getattr(self.cfg, "pump_copy_other", True):
            return "cópia fora da pump.fun desligada"
        if mint in QUOTES or mint in NO_COPY:
            return "não é trade de token"
        liq = (self.tokens.get(mint) or {}).get("liq_usd")
        mn = float(self._c("pump_other_min_liq_usd", 20000))
        if liq is None:
            return "sem pool conhecida"
        if liq < mn:
            return f"liquidez ${liq:,.0f} < ${mn:,.0f}"
        return None

    def is_pump(self, mint: str) -> bool:
        """Token da pump.fun: endereço termina em 'pump' (padrão da pump.fun) ou a DexScreener mostra pool
        pump.fun/PumpSwap."""
        if mint in QUOTES:
            return False
        if mint.endswith("pump"):
            return True
        return bool(set((self.tokens.get(mint) or {}).get("dexes") or []) & PUMP_DEX)

    async def tx_worker(self) -> None:
        while self._tx_q is None:
            await asyncio.sleep(0.5)
        while True:
            w, sig, t0 = await self._tx_q.get()
            if time.time() - t0 > 120:                  # atrasou demais: copiar agora não faz sentido
                self.rpc_status["stale"] = self.rpc_status.get("stale", 0) + 1
                continue
            try:
                tx = await self._get_tx(sig)
                if not tx:
                    self.rpc_status["tx_errors"] += 1
                    continue
                ev = self.parse_trade(tx, w, self.sol_usd)
                if not ev:
                    continue
                self.rpc_status["parsed"] += 1
                self.rpc_status["last_event"] = time.time()
                tk0 = self.tokens.get(ev["mint"]) or {}
                if not tk0.get("symbol") or tk0.get("liq_usd") is None or time.time() - (tk0.get("last_t") or 0) > 30:
                    await self._fetch_prices([ev["mint"]])
                if not self.is_pump(ev["mint"]):
                    why = self._other_block(ev["mint"])
                    if why:
                        # fora da pump.fun e não copiável (cópia fora desligada, staking, pool pequena…)
                        self.rpc_status["ignored"] = self.rpc_status.get("ignored", 0) + 1
                        ig = self.rpc_status.setdefault("ignored_by", {})
                        ig[w] = ig.get(w, 0) + 1
                        continue
                    ev["marketCapSol"] = (self.tokens.get(ev["mint"]) or {}).get("mcap_sol")
                    ev["other"] = True
                    oc = self.rpc_status.setdefault("other_by", {})
                    oc[w] = oc.get(w, 0) + 1
                if ev["txType"] == "buy" and w in self.followed:
                    tk1 = self.tokens.get(ev["mint"]) or {}
                    if time.time() - (tk1.get("vol_t") or 0) > 20:
                        await self._fetch_prices([ev["mint"]], set_price=not self.is_pump(ev["mint"]))
                    try:
                        await self.holders_check(ev["mint"])
                        if getattr(self.cfg, "pump_risk_check", True):
                            await self.risk_check(ev["mint"], self.lb_key())
                    except Exception:
                        pass
                for m in self.on_message(ev):
                    self._emit(m)
            except Exception as e:
                self.rpc_status["tx_errors"] += 1
                log.warning("Pump.fun: transação %s: %s", sig[:12], e)

    async def _fetch_prices(self, mints: list[str], set_price: bool = True) -> None:
        # 0.32.220: o gasto das APIs desta consulta fica dividido entre as moedas consultadas
        return await apiusage.for_mints(mints, self._fetch_prices_run(mints, set_price))

    async def _fetch_prices_run(self, mints: list[str], set_price: bool = True) -> None:
        """Preço (em SOL), símbolo, market cap e VOLUME pela DexScreener (até 30 tokens por consulta, grátis).
        set_price=False: só os dados de mercado (o preço vem da curva on-chain, mais rápido)."""
        sol_usd = self.sol_usd or 0
        for i in range(0, len(mints), 30):
            chunk = mints[i:i + 30]
            try:
                r = await self.http.get(DS_TOKENS + ",".join(chunk), timeout=10)
                js = r.json() if r.status_code == 200 else []
            except Exception as e:
                self.rpc_status["price_error"] = str(e)[:100]
                continue
            best: dict = {}
            vols: dict = {}
            pools: dict = {}
            # 0.32.41 (print do dono, 29/10: MTS, WW3, Mike, BRAVEGOY, specs... parados em −11% por 8–12 h com market cap ~420 SOL
            # = preço FINAL da curva): a trava da 0.32.28 só valia quando o motor já tinha marcado o token como graduado. Se o
            # mesmo token tem outro par (PumpSwap, Meteora...), o par "pumpfun" é a curva já encerrada e não dá preço.
            other_pair = {(p.get("baseToken") or {}).get("address") for p in (js if isinstance(js, list) else [])
                          if p.get("dexId") and p.get("dexId") != "pumpfun"}
            for p in js if isinstance(js, list) else []:
                base = (p.get("baseToken") or {}).get("address")
                if base not in chunk:
                    continue
                # 0.31.77 (pedido do dono, caso LILY: pump.fun mostra $0,10 e o nosso $147): cada pool do token, com volume e
                # compras × vendas de 24 h — o mesmo token pode ter PumpSwap, Meteora etc. com números bem diferentes
                t24 = (p.get("txns") or {}).get("h24") or {}
                pools.setdefault(base, []).append({"dex": p.get("dexId"), "quote": (p.get("quoteToken") or {}).get("symbol"),
                                                   "vol24": float((p.get("volume") or {}).get("h24") or 0),
                                                   "buys24": int(t24.get("buys") or 0), "sells24": int(t24.get("sells") or 0),
                                                   "liq": float((p.get("liquidity") or {}).get("usd") or 0)})
                v = vols.setdefault(base, {"m5": 0.0, "h1": 0.0, "h6": 0.0, "h24": 0.0, "buys_h1": 0, "sells_h1": 0,
                                           "buys_m5": 0, "sells_m5": 0, "buys_h24": 0, "sells_h24": 0})
                for k_ in ("m5", "h1", "h6", "h24"):
                    v[k_] += float((p.get("volume") or {}).get(k_) or 0)
                for w_ in ("m5", "h1", "h24"):                 # compras × vendas por janela (ficha e pressão)
                    tx_ = (p.get("txns") or {}).get(w_) or {}
                    v["buys_" + w_] += int(tx_.get("buys") or 0)
                    v["sells_" + w_] += int(tx_.get("sells") or 0)
                pca = p.get("pairCreatedAt")                 # 0.32.433: nascimento do token (o par mais antigo = a curva)
                if isinstance(pca, (int, float)) and pca > 0:
                    tkb = self.tokens.setdefault(base, {"created_t": time.time()})
                    tkb["born_t"] = min(float(tkb.get("born_t") or 1e12), pca / 1000.0)
                dx = self.tokens.setdefault(base, {"created_t": time.time()}).setdefault("dexes", [])
                if p.get("dexId") and p["dexId"] not in dx:
                    dx.append(p["dexId"])
                if p.get("dexId") == "pumpswap" and p.get("pairAddress"):
                    self.tokens[base]["pumpswap_pool"] = p["pairAddress"]
                ba = int(((p.get("boosts") or {}).get("active")) or 0)     # 0.24.0: boost ativo no par
                if ba:
                    self.tokens[base]["boost_active"] = max(ba, int(self.tokens[base].get("boost_active") or 0))
                liq = float((p.get("liquidity") or {}).get("usd") or 0)
                # 0.32.28 (print do dono, 28/10: BRAVEGOY e Mike parados em 4.108e-7, o preço FINAL da curva): depois que a
                # curva completa, a DexScreener ainda devolve o par antigo da curva ("pumpfun") com liquidez, e ele ganhava
                # do par da PumpSwap. Token já graduado não usa mais esse par para o preço.
                if p.get("dexId") == "pumpfun" and ((self.tokens.get(base) or {}).get("pool") in ("pumpswap", "pump-amm")
                                                    or base in other_pair):
                    continue
                if base in best and best[base][0] >= liq:
                    continue
                best[base] = (liq, p)
            now = time.time()
            for m, L in pools.items():
                tkp = self.tokens.setdefault(m, {"created_t": now})
                tkp["pools"] = sorted(L, key=lambda x: -x["vol24"])[:6]
                tkp["pools_t"] = now
            for m, (liq, p) in best.items():
                q = (p.get("quoteToken") or {}).get("address")
                pn, pu = float(p.get("priceNative") or 0), float(p.get("priceUsd") or 0)
                px = pn if q == SOL_MINT and pn > 0 else (pu / sol_usd if sol_usd and pu else None)
                tk = self.tokens.setdefault(m, {"created_t": now})
                tk["liq_usd"] = liq
                tk["main_dex"] = p.get("dexId")
                if px:
                    tk["mkt_px"], tk["mkt_t"] = px, now     # 0.32.331: preço de mercado, para conferir o preço lido do trade
                tk["chg"] = {k_: float(v_) for k_, v_ in (p.get("priceChange") or {}).items()
                             if k_ in ("m5", "h1", "h6", "h24") and isinstance(v_, (int, float))}
                if m in vols:
                    tk["vol"] = {k_: round(v_, 2) if isinstance(v_, float) else v_ for k_, v_ in vols[m].items()}
                    tk["vol_t"] = now
                if px and (set_price or not tk.get("price") or now - (tk.get("last_t") or 0) > 30) and self._px_ok(m, tk, px, now, "DexScreener"):
                    tk["price"] = px
                    tk["last_t"] = now
                sym = (p.get("baseToken") or {}).get("symbol")
                if sym:
                    tk["symbol"] = sym
                nm = (p.get("baseToken") or {}).get("name")      # 0.32.373: nome (BOOST confere nome repetido e cópias)
                if nm:
                    tk["name"] = nm
                if p.get("marketCap") and sol_usd:
                    tk["mcap_sol"] = float(p["marketCap"]) / sol_usd
            self.rpc_status.update(price_at=now_iso(), price_error=None)

    @staticmethod
    def curve_pda(mint: str) -> str | None:
        try:
            from solders.pubkey import Pubkey
            return str(Pubkey.find_program_address([b"bonding-curve", bytes(Pubkey.from_string(mint))],
                                                   Pubkey.from_string(PUMP_PROGRAMS[0]))[0])
        except Exception:
            return None

    @staticmethod
    def curve_quote(raw: bytes) -> str | None:
        """Mint da moeda de cotação da curva (bytes 83..115 da conta, layout de 166 bytes conferido on-chain em
        2026-10-27). None = SOL (zeros ou o mint do SOL)."""
        if len(raw) < 115:
            return None
        b = raw[83:115]
        if not any(b):
            return None
        alpha = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
        n, out = int.from_bytes(b, "big"), ""
        while n:
            n, r = divmod(n, 58)
            out = alpha[r] + out
        out = "1" * (len(b) - len(b.lstrip(b"\0"))) + out
        return None if out == SOL_MINT else out

    async def _rpc_multi(self, keys: list[str], enc: str, public_first: bool = False):
        urls = []
        own = getattr(self.sol_wallet, "rpc_url", None) if self.sol_wallet is not None else None
        pub = str(self._c("pump_rpc_http", SOL_HTTP) or SOL_HTTP)
        urls = ([pub] + ([own] if own else [])) if public_first else (([own] if own else []) + [pub])
        for u in urls:
            try:
                r = await self.http.post(u, json={"jsonrpc": "2.0", "id": 1, "method": "getMultipleAccounts",
                                                  "params": [keys, {"encoding": enc, "commitment": "confirmed"}]},
                                         timeout=6)
                vals = ((r.json() or {}).get("result") or {}).get("value")
                if vals is not None:
                    return vals
            except Exception:
                continue
        return None

    async def token_decimals(self, mint: str) -> int | None:
        """0.32.65 (PEPE do Bruxo, 29/10: preço 100× acima, stop móvel em "+9547%" falso): a cotação da Jupiter usava 6 casas
        decimais para todo token. Os da pump.fun têm 6; o PEPE (Raydium) tem 4, então a cotação vendia 100× mais tokens do
        que a posição tem. Lê as casas na blockchain (getTokenSupply) uma vez e guarda. None = não deu para ler."""
        tk = self.tokens.setdefault(mint, {"created_t": time.time()})
        if tk.get("decimals") is not None:
            return int(tk["decimals"])
        if mint.endswith("pump"):
            tk["decimals"] = 6
            return 6
        if time.time() - float(tk.get("dec_try_t") or 0) < 60:
            return None
        tk["dec_try_t"] = time.time()
        try:
            r = await self.http.post(str(self._c("pump_rpc_http", SOL_HTTP) or SOL_HTTP), timeout=8,
                                     json={"jsonrpc": "2.0", "id": 1, "method": "getTokenSupply", "params": [mint]})
            dec = int(((r.json().get("result") or {}).get("value") or {})["decimals"])
        except Exception:
            return None
        tk["decimals"] = dec
        if dec != 6:
            tk["dec_fix_t"] = time.time()        # o motor zera o pico/stop móvel calculado com o preço errado
        return dec

    async def _pumpswap_prices(self, mints: list[str], public_first: bool = False, qty: dict | None = None) -> list[str]:
        # 0.32.220: o gasto das APIs desta consulta fica dividido entre as moedas consultadas
        return await apiusage.for_mints(mints, self._pumpswap_prices_run(mints, public_first, qty))

    async def _pumpswap_prices_run(self, mints: list[str], public_first: bool = False, qty: dict | None = None) -> list[str]:
        """Preço AO VIVO de tokens já graduados (PumpSwap/outras DEXs): cotação da Jupiter para VENDER a quantidade
        que o bot segura (preço executável de verdade, com impacto). Obs.: o saldo dos cofres do pool NÃO dá o preço
        certo (testado: ~9% de diferença), por isso a cotação. Devolve os que não deu para cotar.
        qty: quantidade por token (o monitor compartilhado soma a de todos os usuários)."""
        jup = self.market.jup
        if jup is None:
            jup = getattr(getattr(self.real, "jup", None), "dex", None) if self.real is not None else None
        if jup is None:
            return mints
        rest, now = [], time.time()
        if qty is None:
            qty = {}
            for p in self.positions():
                qty[p["mint"]] = qty.get(p["mint"], 0.0) + float(p.get("tokens_left") or 0)
        for m in mints:
            q_tok = qty.get(m) or 0.0
            if q_tok <= 0:
                rest.append(m)
                continue
            dec = await self.token_decimals(m)
            if dec is None:                      # 0.32.65: sem as casas decimais não dá para cotar certo
                rest.append(m)
                continue
            try:
                q = await jup._quote(m, SOL_MINT, int(q_tok * 10 ** dec), None, direct=False)
            except Exception:
                q = None
            out = int((q or {}).get("outAmount") or 0) / 1e9
            if out <= 0:
                rest.append(m)
                continue
            fee = self._fee_rates(m)["venue"]
            tk = self.tokens.setdefault(m, {"created_t": now})
            px_j = out / q_tok / max(1e-9, 1 - fee)
            if not self._px_ok(m, tk, px_j, now, "Jupiter"):
                continue
            tk["price"] = px_j                                     # tira a taxa da pool (o cálculo de saída aplica de novo)
            tk["last_t"], tk["price_src"] = now, "cotação Jupiter (venda da posição)"
        return rest

    async def trail_fast_loop(self) -> None:
        """Posições com STOP MÓVEL ligado: preço on-chain a cada ~1 s (curva da pump.fun ou pool da PumpSwap) e
        checagem do stop — só para essas posições (as outras seguem no ritmo normal de ~3 s)."""
        while True:
            dt = float(self._c("pump_trail_fast_s", 1.0))
            try:
                ms = list(dict.fromkeys(p["mint"] for p in self.positions()
                                        if p.get("trail_peak") is not None and not p.get("selling")))
                if ms and dt > 0:
                    pump = [m for m in ms if self.is_pump(m)]
                    rest = await self._curve_prices(pump, public_first=True) if pump else []
                    rest += [m for m in ms if m not in pump]
                    # graduados: cotação Jupiter no máx. a cada 3 s por token (não sobrecarrega as outras abas)
                    due = [m for m in rest if time.time() - (self.tokens.get(m) or {}).get("jq_t", 0) >= 3]
                    for m in due:
                        self.tokens.setdefault(m, {})["jq_t"] = time.time()
                    if due:
                        await self._pumpswap_prices(due, public_first=True)
                    for m in ms:
                        for msg in self._check_stops(m, time.time()):
                            self._emit(msg)
                    self.rpc_status["trail_fast_at"] = now_iso()
            except Exception as e:
                self.rpc_status["trail_fast_error"] = str(e)[:100]
            await asyncio.sleep(max(0.3, dt) if dt > 0 else 5)

    async def _curve_prices(self, mints: list[str], public_first: bool = False) -> list[str]:
        # 0.32.220: o gasto das APIs desta consulta fica dividido entre as moedas consultadas
        return await apiusage.for_mints(mints, self._curve_prices_run(mints, public_first))

    async def _curve_prices_run(self, mints: list[str], public_first: bool = False) -> list[str]:
        """Preço AO VIVO direto da curva da pump.fun (conta on-chain: reservas virtuais) — 1 consulta para até 100
        tokens, grátis. Devolve os tokens que já graduaram (curva completa) ou que não são da curva."""
        pdas = {m: self.curve_pda(m) for m in mints}
        keys = [v for v in pdas.values() if v]
        if not keys:
            return mints
        vals = await self._rpc_multi(keys, "base64", public_first)
        if vals is None:
            return mints
        by_pda = dict(zip(keys, vals))
        rest, now = [], time.time()
        for m, pda in pdas.items():
            acc = by_pda.get(pda) if pda else None
            try:
                raw = base64.b64decode(acc["data"][0]) if acc else b""
            except Exception:
                raw = b""
            if len(raw) < 49:
                rest.append(m)
                continue
            vt = int.from_bytes(raw[8:16], "little")
            vs = int.from_bytes(raw[16:24], "little")
            complete = raw[48] == 1
            tk = self.tokens.setdefault(m, {"created_t": now})
            # 0.31.52 (SEALLIS +133.475%, R1R2L1R2 e Jewlon: a real vendeu no "alvo" falso com −13%; aplicado com OK do dono em 2026-10-27): a pump.fun agora tem curvas cotadas em OUTRA
            # moeda (ex.: SPCX, ZEC). O mint da cotação fica nos bytes 83..115 (zeros = SOL) e as reservas "vs" vêm na
            # unidade dessa moeda (6–8 casas), então (vs/1e9)/(vt/1e6) dava um preço ~1.000× menor na entrada e a saída
            # (DexScreener/Jupiter, em SOL de verdade) virava um "ganho" de 1.000×. Esses tokens não usam a conta da
            # curva: o preço vem da DexScreener (convertido de USD) ou da cotação da Jupiter.
            quote = self.curve_quote(raw)
            # 0.31.81 (item A, só anotação para a Base geral): modo Mayhem (byte 81) e a moeda da curva
            if len(raw) >= 82:
                tk["mayhem"] = raw[81] == 1
            tk["quote"] = "SOL" if quote is None else ("USDC" if quote.startswith("EPjFWdd5") else "outra moeda")
            if quote is not None or vs < 29_000_000_000:
                tk["quote_mint"] = quote or "desconhecida"
                tk["price_src"] = "cotação em outra moeda: preço pela DexScreener/Jupiter"
                rest.append(m)
                continue
            if complete or not vt:
                tk["pool"] = "pumpswap" if complete else tk.get("pool")
                rest.append(m)
                continue
            tk["price"] = (vs / 1e9) / (vt / 1e6)
            tk["mcap_sol"] = tk["price"] * 1e9
            tk["last_t"] = now
            tk["price_src"] = "curva pump.fun (on-chain)"
        return rest

    async def price_loop(self) -> None:
        """A cada ~3 s: preço ao vivo dos tokens que o bot (fictício e REAL) e os traders copiados seguram —
        direto da curva da pump.fun on-chain; tokens graduados/fora da pump.fun pela DexScreener (a cada ~10 s).
        Depois aplica stop/alvo/segurar-até-lucro e atualiza a variação."""
        last_ds = 0.0
        while True:
            try:
                held = [p["mint"] for p in self.positions()]
                held += [p["mint"] for p in self.trader_positions()]
                held = list(dict.fromkeys(held))[:100]
                if held:
                    pump = [m for m in held if self.is_pump(m)]
                    rest = [m for m in held if m not in pump]
                    rest += await self._curve_prices(pump) if pump else []
                    if time.time() - last_ds >= float(self._c("pump_ds_every_s", 10)):
                        last_ds = time.time()
                        if rest:
                            await self._fetch_prices(list(dict.fromkeys(rest)))
                        mine = [m for m in dict.fromkeys(p["mint"] for p in self.positions()) if m not in rest]
                        if mine:                            # volume/mcap dos tokens da curva (preço já veio on-chain)
                            await self._fetch_prices(mine, set_price=False)
                    for m in {p["mint"] for p in self.positions()}:
                        for msg in self._check_stops(m, time.time()):
                            self._emit(msg)
                    self.rpc_status["price_at"] = now_iso()
            except Exception as e:
                self.rpc_status["price_error"] = str(e)[:100]
            await asyncio.sleep(float(self._c("pump_price_every_s", 3)))

    def _purge_quote_positions(self) -> None:
        if any(e.get("mint") in QUOTES for e in self.feed) or any(e.get("mint") in QUOTES for e in self.live):
            self.feed = deque([e for e in self.feed if e.get("mint") not in QUOTES], maxlen=300)
            self.live = deque([e for e in self.live if e.get("mint") not in QUOTES], maxlen=400)
        for p in self.positions():
            if p["mint"] in QUOTES:
                self._del_pos(p)
                self._emit(f"Pump.fun: posição fictícia em {p.get('symbol')} removida (não é memecoin — era um "
                           f"trade SOL↔dólar do trader; valor devolvido à carteira fictícia)")

    async def _process_pending(self) -> None:
        """Cópias com espera: depois de X s, se o trader ainda segura o token, copia no preço de AGORA."""
        now = time.time()
        for key, pd in list(self._pending.items()):
            if pd["due"] > now:
                continue
            self._pending.pop(key, None)
            who, mint = pd["who"], pd["mint"]
            held = ((self.wallets.get(who) or {}).get("pos") or {}).get(mint, {}).get("tok", 0.0)
            if held <= pd["tok"] * 0.05:
                continue
            try:
                await self._fetch_prices([mint])               # preço atualizado (você entra agora, não no preço dele)
            except Exception:
                pass
            ev = dict(pd["ev"], _delayed=True)
            for m in self._copy(who, mint, "buy", pd["sol"], pd["tok"], ev, pd["before"], now):
                self._emit(m)

    async def _tick(self) -> None:
        await self._process_pending()
        self._purge_quote_positions()
        self.refresh_followed()
        for msg in self.check_timeouts():
            self._emit(msg)
        if int(time.time()) % 60 < 2:
            self.prune()
        if self.price_fn:
            try:
                self.sol_usd = float(self.price_fn() or 0) or self.sol_usd
            except Exception:
                pass
        if self.real is not None and self._real_q:
            await self._real_process()

    def _emit(self, msg: str) -> None:
        log.info(msg)
        self._ev_id += 1
        self.events.append({"id": self._ev_id, "at": now_iso(), "msg": msg})
        if self.tg is not None:
            try:
                self.tg(msg)
            except Exception:
                pass
        if self.on_event:
            self.on_event("pump", msg)

    def events_after(self, after: int = 0) -> list[dict]:
        return [e for e in self.events if e["id"] > after]

    # ------------------------------------------------------------------ real (preparado, desligado)
    @staticmethod
    def _px_gap(real, sim) -> float | None:
        return round((real / sim - 1) * 100, 2) if real and sim else None

    def mirror_pairs(self, limit: int = 100) -> list[dict]:
        """0.31.38 — sugestão do Bruxo + aprendizagem do bot: cada trade real do espelho ao lado do trade fictício par,
        para ver quanto do resultado simulado sobra no dinheiro de verdade (atraso, slippage e taxas)."""
        T = self.trades(5000)
        sim = {}
        for t in T:
            if not t.get("real"):
                for k in ("pos_id", "id"):
                    if t.get(k) is not None:
                        sim.setdefault(str(t[k]), t)
        out = []
        for r in T:
            if not r.get("real") or r.get("sim_id") is None:
                continue
            s = sim.get(str(r["sim_id"]))
            out.append({"token": r.get("symbol"), "mint": r.get("mint"), "fechou": r.get("closed_at"),
                        "real_sol": r.get("pnl_sol"), "real_pct": r.get("pnl_pct"), "real_in": r.get("sol_in"),
                        "sim_sol": s.get("pnl_sol") if s else None, "sim_pct": s.get("pnl_pct") if s else None,
                        "dif_pct": round((r.get("pnl_pct") or 0) - (s.get("pnl_pct") or 0), 2) if s else None,
                        "atraso_s": r.get("lag_s"), "lat": r.get("lat"), "motivo_real": r.get("reason"), "motivo_sim": s.get("reason") if s else None,
                        "entrada_pct": self._px_gap(r.get("price_in"), s.get("sim_entry_px")) if s else None,   # 0.32.107: preço original da fictícia
                        "saida_pct": self._px_gap(r.get("price_out"), s.get("price_out")) if s else None})
        out.sort(key=lambda x: str(x.get("fechou") or ""), reverse=True)
        return out[:limit]

    MISS_TIPS = (("outra moeda", "Token de 'par personalizado' (a curva é cotada em SPCX, ZEC, USDC…, não em SOL). A PumpPortal só compra com SOL; desde a 0.31.83 a real tenta pela Jupiter. Se a Jupiter também não tiver rota, a fictícia compra e a real não."),
                 ("não deu para simular", "O RPC não respondeu à simulação nem depois de 3 tentativas. Um RPC próprio (Configurações → Chaves, ex.: Helius) evita o limite do RPC público."),
                 ("limite de", "Aumente \"Posições ao mesmo tempo\" em Carteiras → REAL, ou confira se há posição real antiga presa aberta."),
                 ("perda do dia", "A real parou no limite \"Parar no dia se perder\"; volta sozinha no dia seguinte (UTC)."),
                 ("já tem posição real", "A real já estava nesse token (de outra cópia); normal."),
                 ("desligad", "A execução real ou a entrada automática estava desligada nessa hora."),
                 ("saldo", "Falta SOL na carteira do bot para o \"SOL por compra\" + taxas."),
                 ("subiu", "O preço fugiu antes de a real comprar (corrigido na 0.31.43 para o espelho)."),
                 ("erro", "Falha ao enviar: confira o RPC e o saldo; veja Administração → Logs."),
                 ("falh", "A rede recusou ou não confirmou; confira saldo e slippage da real."),
                 ("verificação", "A trava de segurança recusou a transação montada pela PumpPortal (formato novo). Mande o print para corrigir; a trava nunca é desligada."),
                 ("simulação", "A simulação antes de assinar recusou a transação (SOL demais ou outro token mexido). Mande o print."),
                 ("slippage", "O preço andou mais que a slippage da real na hora da compra: aumente a slippage da real com cuidado."),
                 ("recusad", "A rede recusou ou não confirmou; confira saldo e slippage da real."))

    MISS_ACTIONS = ("REAL não copiou", "REAL falhou", "FICTÍCIA desfeita")

    def real_why(self, hours: float = 6, now: float | None = None) -> dict:
        """0.32.162 (pedido do dono: "por que só a fictícia está funcionando?"): o que impede a REAL de comprar agora e, nas
        últimas horas, quantas compras a fictícia fez, quantas a real fez e por que a real ficou de fora em cada token."""
        now = time.time() if now is None else now
        c = self.cfg
        self._real_buying.prune()
        ro = [p for p in self.positions() if p.get("real")]
        lim_open = int(self._c("pump_real_max_open", 5))
        lim_loss = float(self._c("pump_real_daily_loss_sol", 0.5) or 0)
        T = self.trades(2000)
        loss = self.real.today_loss(T) if self.real is not None else 0.0
        agora = []
        if not getattr(c, "pump_real_enabled", False):
            agora.append("a Execução real está desligada")
        if not (self.sol_wallet and getattr(self.sol_wallet, "keypair", None)):
            agora.append("a carteira real não está configurada (Configurações → Chaves pessoais)")
        if len(ro) + len(self._real_buying) >= lim_open:
            agora.append(f"limite de {lim_open} posições reais ao mesmo tempo ({len(ro)} abertas"
                         + (f", {len(self._real_buying)} comprando" if self._real_buying else "") + ") — Carteiras → REAL → Posições ao mesmo tempo")
        if lim_loss and loss >= lim_loss:
            agora.append(f"a perda de hoje na real ({loss:.4f} SOL) chegou ao limite de {lim_loss:g} SOL — volta a comprar às 00:00 UTC")
        ini = now - hours * 3600
        F = [f for f in list(self.feed or []) if (self._ts(f.get("at")) or 0) >= ini]
        motivos: dict = {}
        itens = []
        for f in F:                                            # o feed vem do mais novo para o mais antigo
            a = str(f.get("action") or "")
            if not a.startswith(self.MISS_ACTIONS):
                continue
            why = str(f.get("reason") or "sem motivo")
            k = re.sub(r"[-+]?\d+(?:[.,]\d+)?", "#", why)[:80]
            g = motivos.setdefault(k, {"motivo": why[:160], "n": 0, "ultimo": f.get("at"), "tokens": [], "acao": a,
                                       "dica": next((tp for key, tp in self.MISS_TIPS if key in why.lower()), "")})
            g["n"] += 1
            if f.get("symbol") and f.get("symbol") not in g["tokens"] and len(g["tokens"]) < 6:
                g["tokens"].append(f.get("symbol"))
            if len(itens) < 60:
                itens.append({"at": f.get("at"), "acao": a, "token": f.get("symbol"), "mint": f.get("mint"), "motivo": why[:200],
                              "carteira": f.get("wallet")})
        compras = lambda acts: sum(1 for f in F if str(f.get("action") or "") in acts)
        abertas = [p.get("open_t") or self._ts(p.get("opened_at")) for p in ro]
        fechadas = [self._ts(t.get("opened_at")) for t in T if t.get("real")]
        ult = max([x for x in abertas + fechadas if x] or [0]) or None
        return {"pode_comprar": not agora, "agora": agora, "horas": hours, "espelho": bool(getattr(c, "pump_real_mirror", True)),
                "exata": self.exact_on(), "valor_sol": float(self._c("pump_real_max_sol", 0.05)), "abertas": len(ro), "max_abertas": lim_open,
                "comprando": len(self._real_buying), "perda_hoje": round(loss, 6), "max_perda": lim_loss,
                "compras_ficticia": compras(("copiou compra", "comprou (automático)", "comprou (manual)")),
                "compras_real": compras(("REAL comprou",)), "nao_copiou_real": sum(g["n"] for g in motivos.values()),
                "ultima_real_t": ult, "motivos": sorted(motivos.values(), key=lambda g: -g["n"]), "itens": itens}

    def mirror_misses(self, hours: float = 48, now: float | None = None) -> dict:
        """0.31.43 — trades da fictícia que NÃO tiveram par na real (com o espelho ligado), com o motivo anotado no feed
        e a dica do que ajustar. É o que alimenta o aprendizado: motivos que se repetem."""
        now = time.time() if now is None else now
        T = self.trades(5000)
        paired = {str(r["sim_id"]) for r in T if r.get("real") and r.get("sim_id") is not None}
        paired |= {str(p["sim_id"]) for p in self.positions() if p.get("real") and p.get("sim_id") is not None}
        feed = [f for f in list(self.feed or [])                       # mais novo primeiro
                if str(f.get("action") or "").startswith(("REAL não copiou", "REAL falhou"))]
        out, por = [], {}
        for t in T:
            if t.get("real"):
                continue
            pid = t.get("pos_id") if t.get("pos_id") is not None else t.get("id")
            closed = self._ts(t.get("closed_at")) or 0
            if pid is None or str(pid) in paired or now - closed > hours * 3600:
                continue
            f = next((x for x in feed if str(x.get("sim_id")) == str(pid)), None) or \
                next((x for x in feed if x.get("mint") == t.get("mint")), None)
            why = (f or {}).get("reason") or "sem registro: a real estava desligada, ou foi antes da 0.31.43"
            tip = next((tp for key, tp in self.MISS_TIPS if key in why.lower()), "")
            out.append({"token": t.get("symbol"), "mint": t.get("mint"), "fechou": t.get("closed_at"), "sim_sol": t.get("pnl_sol"),
                        "sim_pct": t.get("pnl_pct"), "origem": t.get("origem") or ("manual" if t.get("wallet") == "manual" else "cópia"),
                        "motivo": why, "dica": tip})
            k = re.sub(r"[-+]?\d+(?:[.,]\d+)?", "#", why)[:80]
            g = por.setdefault(k, {"motivo": why[:80], "n": 0, "sim_sol": 0.0, "dica": tip})   # 0.31.54: texto real, sem "#.#"
            g["n"] += 1
            g["sim_sol"] = round(g["sim_sol"] + (t.get("pnl_sol") or 0), 6)
        out.sort(key=lambda x: str(x.get("fechou") or ""), reverse=True)
        return {"lista": out[:100], "por_motivo": sorted(por.values(), key=lambda g: -g["n"]), "total": len(out),
                "perdido_sol": round(sum(x["sim_sol"] or 0 for x in out if (x["sim_sol"] or 0) > 0), 6)}

    def _mirror_real(self, p: dict, trader_sol: float = 0.0, block_t=None, pos_cfg: dict | None = None) -> str | None:
        """0.31.37 — sugestão do Bruxo (2026-10-27): com a Execução real ligada, TODO trade que abriu na carteira
        fictícia também é comprado na real. O valor NUNCA é o da fictícia: `_real_buy` usa "SOL por compra" da real
        (`pump_real_max_sol`, reduzido pela confiança no trader), e valem os limites da real (posições reais ao mesmo
        tempo, perda do dia, preço que fugiu). Devolve o motivo quando a real não entra (fica no feed)."""
        c = self.cfg
        if self.real is None or not getattr(c, "pump_real_enabled", False) or not getattr(c, "pump_real_mirror", True):
            return None
        self._real_buying.prune()
        mint, allpos = p["mint"], self.positions()
        base = {"wallet": p["wallet"], "short": short(p["wallet"]), "mint": mint, "symbol": p.get("symbol"), "kind": "buy"}
        gw = self.tab_gate_why(self.aba_of(p))            # 0.32.325: tela sem prova na fictícia não compra na REAL
        if gw:
            self._feed(**base, action="REAL não copiou", reason=gw, sim_id=p["id"])
            return None                                   # não é falha da REAL: a fictícia continua, é ela que faz a prova
        why = None
        if any(x["mint"] == mint and x.get("real") for x in allpos) or mint in self._real_buying:
            why = "já tem posição REAL neste token"
        elif len([x for x in allpos if x.get("real")]) + len(self._real_buying) >= int(self._c("pump_real_max_open", 5)):
            why = f"limite de {int(self._c('pump_real_max_open', 5))} posições reais (regra da carteira real)"
        if why:
            self._feed(**base, action="REAL não copiou", reason=why, sim_id=p["id"])
            self._cancel_sim(p["id"], why)
            return why
        self._real_buying.add(mint)
        self._rq_put(("buy", {"wallet": p["wallet"], "mint": mint, "symbol": p.get("symbol"), "trader_sol": trader_sol,
                              "trader_price": p.get("trader_price") or p.get("price_now"), "mcap_in": p.get("mcap_in"),
                              "t": p.get("open_t") or time.time(), "block_t": block_t or p.get("open_t"), "sim_id": p["id"],
                              **({"pos_cfg": pos_cfg} if pos_cfg else {})}))
        self._feed(**base, action="REAL: comprando",
                   reason=f"espelho do fictício · até {float(self._c('pump_real_max_sol', 0.05)):.3f} SOL (regra da carteira real)")
        return None

    def exact_on(self) -> bool:
        """0.32.158: cópia exata ligada (real manda, fictícia acompanha). Só com espelho e execução real ligados."""
        c = self.cfg
        return bool(getattr(c, "pump_real_exact", False) and getattr(c, "pump_real_mirror", True)
                    and getattr(c, "pump_real_enabled", False) and self.real is not None)

    def _cancel_sim(self, sim_id, why: str) -> None:
        """0.32.158 (pedido do dono: "a fictícia tem que ser a cópia exata da real"): a real não comprou, então a fictícia par
        é desfeita como se não tivesse entrado (o dinheiro volta; não vira trade)."""
        if not self.exact_on():
            return
        sim = next((x for x in self.positions() if x["id"] == sim_id and not x.get("real")), None)
        if not sim or sim.get("sells"):
            return
        self._del_pos(sim)
        key = str(sim["id"])
        if key in self.auto_rows:                        # 0.32.160: a operação automática some das contas (não entrou de verdade)
            self.auto_rows[key] = dict(self.auto_rows[key], saida_em=now_iso(), pnl_sol=None, pnl_pct=None,
                                       motivo_saida=f"desfeita: cópia exata (a real não comprou: {why})"[:200])
            self._auto_dirty.add(key)
        self._lead("close", sim, "desfeita: a real não comprou")
        self._feed(wallet=sim["wallet"], short=short(sim["wallet"]), mint=sim["mint"], symbol=sim.get("symbol"), kind="buy",
                   action="FICTÍCIA desfeita", reason=f"cópia exata: a real não comprou ({why})", sim_id=sim_id)

    def _rq_put(self, item) -> None:
        if self._rq is None:
            self._rq = asyncio.Queue()
        self._rq.put_nowait(item)

    SELL_BACKOFF_S = (10, 30, 60, 120, 300)

    def _real_sell(self, p: dict, frac: float, why: str) -> bool:
        """Põe a venda REAL na fila. 0.32.62 (PEPE do Bruxo, 29/10 20:55: "vendendo 100%" + erro a cada 3 s, sem parar): depois
        de uma venda que falhou, espera 10 s, 30 s, 1 min, 2 min e 5 min antes de tentar de novo; venda pedida por você
        na tela não espera. Devolve False quando não pôs na fila."""
        if p.get("selling"):
            return False
        # 0.32.422 (FTL, 21/11 14:41: 9 tentativas em 20 s): só a venda pedida por você DIRETO na tela pula a espera; a REAL que
        # acompanha uma fictícia fechada por você respeita a espera entre tentativas
        by_you = "por você" in why and not why.startswith(("junto com a fictícia", "espelho do fictício"))
        if time.time() < float(p.get("sell_retry_at") or 0) and not by_you:
            return False
        p["selling"] = True
        self._save_pos(p)
        self._rq_put(("sell", {"id": p["id"], "frac": frac, "why": why}))
        return True

    def _sell_failed(self, p: dict, reason: str) -> None:
        """0.32.62: marca a falha da venda real e quando pode tentar de novo (espera crescente)."""
        n = int(p.get("sell_fails") or 0)
        wait = self.SELL_BACKOFF_S[min(n, len(self.SELL_BACKOFF_S) - 1)]
        p["sell_fails"] = n + 1
        p["sell_retry_at"] = time.time() + wait
        p["sell_error"] = reason
        p["selling"] = False
        self._save_pos(p)
        self._emit(f"[PUMP REAL] venda {p.get('symbol')} NÃO feita: {reason} — tenta de novo em {wait} s (tentativa {n + 1})")

    async def _real_process(self) -> None:          # compatibilidade (fila antiga)
        self._real_q = []

    REAL_PARALLEL = 6

    async def real_loop(self) -> None:
        """Executa as compras/vendas REAIS assim que chegam.
        0.31.46 (pedido do dono: "a real tem que acontecer junto com a fictícia, sem delay"): antes era UMA de cada vez —
        uma compra esperando confirmar (às vezes 60 s) segurava a venda de outro token na fila. Agora cada ordem sai na
        hora, em paralelo (até REAL_PARALLEL); só as do MESMO token esperam a anterior (compra antes da venda).
        O SOL gasto/recebido vem da própria transação (`_sol_change`), então ordens simultâneas não se misturam."""
        if self._rq is None:
            self._rq = asyncio.Queue()
        sem, locks, tasks = asyncio.Semaphore(self.REAL_PARALLEL), {}, set()
        while True:
            kind, it = await self._rq.get()
            mint = it.get("mint") or next((p["mint"] for p in self.positions() if p["id"] == it.get("id")), None) or str(it.get("id"))
            lock = locks.setdefault(mint, asyncio.Lock())
            task = asyncio.get_running_loop().create_task(self._real_run(kind, it, lock, sem))
            tasks.add(task)
            task.add_done_callback(tasks.discard)
            if len(locks) > 500:
                for k in [k for k, v in locks.items() if not v.locked()][:250]:
                    locks.pop(k, None)

    async def _real_run(self, kind: str, it: dict, lock: asyncio.Lock, sem: asyncio.Semaphore) -> None:
        from . import rpcprio
        async with lock, sem:
            with rpcprio.real_scope():                   # 0.32.395: a REAL passa na frente no RPC; o resto espera até 1 s depois
                try:
                    if kind == "buy":
                        await self._real_buy(it)
                    else:
                        await self._real_do_sell(it)
                except Exception as e:
                    if kind == "buy":
                        self._emit(f"[PUMP REAL] {kind} {it.get('symbol') or it.get('id')}: erro {type(e).__name__}: {str(e)[:120]}")
                    if kind == "buy":
                        self._real_buying.discard(it.get("mint"))
                        self._auto_pending.pop(it.get("mint"), None)
                    else:
                        p = next((x for x in self.positions() if x["id"] == it.get("id")), None)
                        if p is not None:
                            self._sell_failed(p, f"{type(e).__name__}: {str(e)[:120]}")
                        else:
                            self._unmark_selling(it.get("id"))

    def _unmark_selling(self, pid) -> None:
        for p in self.positions():
            if p["id"] == pid and p.get("selling"):
                p["selling"] = False
                self._save_pos(p)

    async def token_age_min(self, mint: str, need_min: float) -> float | None:
        """0.32.254: idade do token em minutos (None = não deu para saber). Usa a hora da criação vista pelo monitor; senão a
        transação mais antiga do token no RPC (até 3 páginas de 1.000). Resposta guardada no token (`born_t`)."""
        tk = self.tokens.setdefault(mint, {"created_t": time.time()})
        now = time.time()
        if tk.get("born_t"):
            return (now - float(tk["born_t"])) / 60
        if tk.get("creator") and tk.get("created_t"):
            return (now - float(tk["created_t"])) / 60
        urls = []
        own = getattr(self.sol_wallet, "rpc_url", None) if self.sol_wallet is not None else None
        for u in (own, getattr(self.market, "sys_rpc", "") or "", str(self._c("pump_rpc_http", SOL_HTTP) or SOL_HTTP), SOL_HTTP):
            if u and u not in urls:
                urls.append(u)
        before, oldest = None, None
        for _ in range(3):
            opts = {"limit": 1000, **({"before": before} if before else {})}
            res = None
            for u in urls:
                try:
                    js = (await self.http.post(u, json={"jsonrpc": "2.0", "id": 1, "method": "getSignaturesForAddress",
                                                        "params": [mint, opts]}, timeout=8)).json()
                    if isinstance(js.get("result"), list):
                        res = js["result"]
                        break
                except Exception:
                    continue
            if res is None:
                return None
            bt = [float(x["blockTime"]) for x in res if x.get("blockTime")]
            if bt:
                oldest = min(bt + ([oldest] if oldest else []))
            if oldest and (now - oldest) / 60 >= need_min:
                return (now - oldest) / 60                    # já passou do mínimo: não precisa achar a criação
            if len(res) < 1000:
                if oldest:
                    tk["born_t"] = oldest                     # achou a primeira transação: é a criação
                return (now - oldest) / 60 if oldest else None
            before = res[-1].get("signature")
        return (now - oldest) / 60 if oldest else None        # 3 mil transações sem passar do mínimo: novo e agitado

    async def _real_buy(self, it: dict) -> None:
        return await apiusage.for_mints([it.get("mint")], self._real_buy_run(it))     # 0.32.220: gasto da compra REAL na moeda

    async def _real_buy_run(self, it: dict) -> None:
        it.setdefault("t_run", time.time())             # 0.32.431: quanto a ordem esperou na fila (lat.fila_ms)
        mint, sym = it["mint"], it["symbol"]
        # 0.31.43 (sugestão do Bruxo + aprendizagem do bot: "a real não replica a fictícia"): toda desistência da compra
        # real fica no feed com o motivo e o par fictício (sim_id). A tela Real × fictícia junta isso e diz o que ajustar.
        mirrored = getattr(self.cfg, "pump_real_mirror", True) and it.get("sim_id") is not None

        bm_buy = (it.get("pos_cfg") or {}).get("origem") == "boostmig"

        def miss(why: str, action: str = "REAL não copiou") -> None:
            self._feed(wallet=it["wallet"], short=short(it["wallet"]), mint=mint, symbol=sym, kind="buy",
                       action=action, reason=why, sim_id=it.get("sim_id"))
            if bm_buy:                                  # 0.32.398: a lista do BOOST mostra que a REAL não comprou e por quê
                self.bm_real_note[mint] = {"estado": "fora", "motivo": why, "t": time.time()}
        try:
            lim = float(self._c("pump_real_daily_loss_sol", 0.5))
            if not getattr(self.cfg, "pump_real_enabled", False):
                miss("execução real desligada quando a compra ia sair")
                return
            own_auto = (it.get("pos_cfg") or {}).get("auto") is True
            if own_auto and not mirrored and (not getattr(self.cfg, "pump_auto_real", False) or not self.auto_ready):
                return
            if own_auto and (getattr(self, "role", None) != "admin"
                             or ((it.get("pos_cfg") or {}).get("origem") == "explorar"
                                 and not getattr(self.cfg, "pump_ex_auto_on", False))):
                miss("entrada automática do Explorar desligada (ou conta sem admin) quando a compra ia sair")
                return
            if own_auto and not (getattr(self.cfg, "pump_real_mirror", True) and it.get("sim_id") is not None):
                reserved = self._auto_pending.pop(mint, None)
                guard = self.auto_guard(t=time.time())
                if reserved is not None:
                    self._auto_pending[mint] = reserved
                if guard:
                    self._auto_blocked(guard, mint, (it.get("pos_cfg") or {}).get("origem", "explorar"), time.time())
                    return
            # 0.32.399 (dono: "todas as regras fora do BOOST são desconsideradas no BOOST"): a compra REAL do BOOST não passa pelas
            # travas da Execução real (perda do dia, fora da curva, valor por trader, preço fugiu, vagas, valor máximo);
            # vale só o que está nas Regras do BOOST.
            if lim and not bm_buy and self.real.today_loss(self.trades(2000)) >= lim:
                miss(f"perda do dia da REAL chegou a {lim} SOL (Carteiras → REAL → Parar no dia se perder)")
                return
            # 0.32.254 (pedido do dono): a REAL só compra token com pelo menos N min de vida (padrão 10; 0 = desliga)
            min_age = float(self._c("pump_real_min_age_min", 10) or 0)
            # 0.32.398 (dono, Brenter 20/11 23:34: "o real comprou só no status"): o BOOST compra logo depois da migração e muito
            # token migra com 2–5 min de vida; a idade mínima (feita para as cópias) barrava toda compra REAL do BOOST.
            if min_age > 0 and not bm_buy:
                age = await self.token_age_min(mint, min_age)
                if age is None:
                    miss(f"não deu para conferir a idade do token (mínimo da REAL: {min_age:.0f} min)")
                    return
                if age < min_age:
                    miss(f"token com {age:.1f} min de vida (a REAL só compra com {min_age:.0f} min ou mais)")
                    return
            # 0.32.330: a REAL não compra token ainda na curva da pump.fun (taxa 1,25% por lado, rug e venda travada)
            if (getattr(self.cfg, "pump_real_no_curve", False) and not bm_buy and self.is_pump(mint)
                    and self._fee_rates(mint, True)["venue_name"] == "pump.fun (curva)"):
                miss("token ainda na curva da pump.fun (a REAL só compra depois de graduar — Execução real → REAL fora da curva)")
                return
            mult, mwhy = (1.0, "") if bm_buy else self.trust_mult(it["wallet"])
            amt = float(self._c("pump_real_max_sol", 0.05)) * min(1.0, mult)
            ar_real = float(self._c("pump_ar_real_sol", 0) or 0)
            if bm_buy and it.get("amt_sol"):
                # 0.32.399: o valor da REAL do BOOST é o "Valor por entrada" das Regras do BOOST (o da REAL, se ela usa regras
                # próprias); o máximo da Execução real não vale no BOOST
                amt = float(it["amt_sol"])
            if own_auto and (it.get("pos_cfg") or {}).get("origem") == "explorar" and ar_real > 0:
                # 0.32.32: valor próprio das automáticas do Explorar na real, sem passar do máximo da Execução real
                amt = min(ar_real, float(self._c("pump_real_max_sol", 0.05)))
            # a compra real sai da fila depois: confere de novo se o preço já não fugiu da entrada do trader.
            # 0.31.43: no ESPELHO não — a fictícia já passou pelos filtros e os tokens que mais sobem (ex.: R1R2L1R2,
            # +150% em 12 s) eram justamente os barrados aqui; a proteção da real é a slippage da carteira real.
            chase = None if (mirrored or bm_buy) else self.chase_block(it.get("trader_price"), (self.tokens.get(mint) or {}).get("price"))
            if chase:
                miss(chase)
                return
            try:
                tk_ = self.tokens.get(mint) or {}
                hints = getattr(self.real, "pool_hint", None)
                if isinstance(hints, dict) and ((bm_buy and not tk_.get("bm_curva")) or tk_.get("pool") == "pumpswap" or tk_.get("graduated")):
                    hints[mint] = "pump-amm"               # 0.32.430: já graduou → compra direto na PumpSwap
                res = await self.real.buy(mint, amt, other=not self.is_pump(mint))
            except Exception as e:
                miss(f"erro ao enviar a compra: {type(e).__name__}: {str(e)[:120]}", "REAL falhou")
                raise
            if not res.get("ok"):
                miss(res.get("reason") or res.get("status") or "a compra não confirmou", "REAL falhou")
                self._emit(f"[PUMP REAL] compra {sym} NÃO feita: {res.get('reason') or res.get('status')}")
                return
            fr = self._fee_rates(mint, True)
            spent, toks = res["sol_spent"], res["tokens"]
            p = {"opened_at": now_iso(), "open_t": time.time(), "wallet": it["wallet"], "mint": mint, "symbol": sym,
                 "sol_in": round(spent, 9), "tokens": toks, "tokens_left": toks, "price_in": spent / toks,
                 "price_now": it.get("trader_price"), "trader_price": it.get("trader_price"),
                 "trader_sol": it.get("trader_sol"), "proceeds": 0.0, "mcap_in": it.get("mcap_in"), "real": True,
                 "venue_in": fr["venue_name"], "signature": res.get("signature"), "fees_sol": 0.0,
                 "lag_s": round(max(0.0, time.time() - float(it.get("block_t") or it.get("t") or time.time())), 1),
                 "lat": dict(res.get("lat") or {}, total_ms=round(max(0.0, time.time() - float(it.get("t") or time.time())) * 1000),
                             fila_ms=round(max(0.0, float(it.get("t_run") or 0) - float(it.get("t") or 0)) * 1000) if it.get("t") else None)}
            # 0.32.449 (dono, Zeus 25/11): a PumpPortal na PumpSwap gasta mais SOL que o pedido (0,126 com 0,1 configurado) e
            # esse excesso entrava como "taxa de rede" (0,025 SOL), embora tenha virado token. A rede é só a da transação; as
            # taxas do pool contam sobre o que de fato foi trocado. O aluguel da conta do token volta no fechamento.
            swap = max(0.0, spent - fr["prio"]) / (1 + fr["venue"] + fr["portal"])
            self._addfee(p, platform=swap * fr["venue"], portal=swap * fr["portal"], network=fr["prio"])
            p["fees_sol"] = sum((p.get("fee_parts") or {}).values())
            p.update(it.get("pos_cfg") or {})              # compra do botão: stop/alvo próprios (0.26.0)
            if own_auto:
                p["opened_at"] = datetime.fromtimestamp(p["open_t"], timezone.utc).isoformat()
            if it.get("sim_id") is not None:
                p["sim_id"] = it["sim_id"]                 # 0.31.37: par na carteira fictícia (espelho)
            self._save_pos(p)
            if bm_buy:
                self.bm_real_note[mint] = {"estado": "entrou", "motivo": f"REAL comprou {spent:.4f} SOL", "t": time.time()}
            if it.get("sim_id") is not None:
                self._align_to_real(p)
            if it.get("sim_id") is not None and not any(x["id"] == it["sim_id"] for x in self.positions()):
                self._real_sell(p, 1.0, "espelho: o fictício já fechou enquanto a compra real saía")
            self._feed(wallet=it["wallet"], short=short(it["wallet"]), mint=mint, symbol=sym, kind="buy",
                       action="REAL comprou", reason=f"gastou {spent:.4f} SOL · recebeu {toks:,.0f} tokens",
                       signature=res.get("signature"))
            self._emit(f"[PUMP REAL] comprou {sym}: {spent:.4f} SOL (copiando {short(it['wallet'])})")
        finally:
            self._real_buying.discard(mint)
            self._auto_pending.pop(mint, None)
            if bm_buy:
                self._bm_open_sim(mint)                   # 0.32.400: no BOOST a fictícia entra DEPOIS da REAL
            if it.get("sim_id") is not None:
                if not any(x.get("real") and x.get("sim_id") == it["sim_id"] for x in self.positions()) and not any(
                        t.get("real") and t.get("sim_id") == it["sim_id"] for t in self.trades(50)):
                    self._cancel_sim(it["sim_id"], "a compra real não saiu")
                self._release_sim_exit(it["sim_id"])

    async def _real_do_sell(self, it: dict) -> None:
        pm = next((x for x in self.positions() if x["id"] == it["id"]), None)
        return await apiusage.for_mints([(pm or {}).get("mint")], self._real_do_sell_run(it))   # 0.32.220

    async def _real_do_sell_run(self, it: dict) -> None:
        p = next((x for x in self.positions() if x["id"] == it["id"]), None)
        if not p:
            return
        frac, why = float(it["frac"]), it["why"]
        pend = p.get("sell_pending")
        if pend:
            # SEC-04: venda anterior ficou sem confirmação (gravada na posição, vale também depois de reiniciar).
            # Só monta outra quando a anterior confirmou, falhou ou já não pode mais entrar (blockhash vencido).
            try:
                st = await self.real.signature_status(pend["signature"])
            except Exception:
                st = None
            if st is None and time.time() - float(pend.get("at") or 0) < SELL_PENDING_HOLD_S:
                p["selling"] = False
                p["sell_retry_at"] = time.time() + 10       # 0.32.62: não pergunta de novo a cada 3 s
                self._save_pos(p)
                self._emit(f"[PUMP REAL] venda {p['symbol']} adiada: a anterior ainda não confirmou ({why})")
                return
            p.pop("sell_pending", None)
            if st == "confirmada":
                self._emit(f"[PUMP REAL] a venda pendente de {p['symbol']} confirmou depois; o saldo já reflete isso")
        tk_ = self.tokens.get(p["mint"]) or {}
        hints = getattr(self.real, "pool_hint", None)
        if isinstance(hints, dict) and ((p.get("origem") == "boostmig" and not tk_.get("bm_curva")) or tk_.get("pool") == "pumpswap"
                                        or tk_.get("graduated")):
            hints[p["mint"]] = "pump-amm"              # 0.32.422: já graduou → PumpSwap direto
        res = await self.real.sell(p["mint"], frac, other=not self.is_pump(p["mint"]))
        p["sell_tries"] = (p.get("sell_tries") or []) + list(res.get("tentativas") or [])
        p["sell_tries"] = p["sell_tries"][-40:]
        if res.get("status") == "pendente" and res.get("signature"):
            p["sell_pending"] = {"signature": res["signature"], "at": time.time()}
        if not res.get("ok"):
            self._sell_failed(p, f"{res.get('reason') or res.get('status')} ({why})")
            return
        p.pop("sell_retry_at", None)
        p.pop("sell_fails", None)
        got, left = res["sol_received"], res["tokens_left"]
        ext = None
        if res.get("reason") == "sem saldo do token" and hasattr(self.real, "external_sold"):
            try:                                          # 0.32.459: o SOL que entrou na venda feita fora do robô
                ext = await self.real.external_sold(p["mint"], float(p.get("open_t") or 0) - 5,
                                                    {p.get("signature")} | {x.get("signature") for x in p.get("sells") or []})
            except Exception:
                ext = None
        if ext and ext[0] > 0:
            got = ext[0]
            why = why + f" · vendido fora do robô (na carteira): {ext[0]:.6f} SOL"
            p["fora_do_robo"] = True
            p["fora_sigs"] = ext[2]
            if len(ext) > 3 and ext[3] > 0:               # aluguel da conta do token fechada na carteira
                p["proceeds"] = p.get("proceeds", 0.0) + ext[3]
                p["conta_devolvida_sol"] = round(ext[3], 6)
        elif res.get("reason") == "sem saldo do token":
            # 0.32.182: o token já não estava na carteira (vendido no app da carteira, por exemplo). O robô não sabe quanto
            # SOL entrou nessa venda: o resultado fica −100% no histórico, mas o motivo diz isso para não parecer perda.
            why = why + " · o token já não estava na carteira (vendido fora do robô?): o SOL dessa venda não entra na conta"
            p["fora_do_robo"] = True
        fr = self._fee_rates(p["mint"], True)
        sold = max(0.0, p["tokens_left"] - left)
        p["proceeds"] = p.get("proceeds", 0.0) + got
        p["tokens_left"] = left
        p["price_now"] = (got / sold) if sold else p.get("price_now")
        gross_out = got / max(1e-9, 1 - fr["venue"] - fr["portal"])
        self._addfee(p, platform=gross_out * fr["venue"], portal=gross_out * fr["portal"], network=fr["prio"])
        p["fees_sol"] = sum((p.get("fee_parts") or {}).values())
        p.setdefault("sells", []).append({"at": now_iso(), "frac": round(frac, 4), "sol": round(got, 6), "why": why,
                                          "signature": res.get("signature")})
        p["selling"] = False
        if left <= p["tokens"] * 0.005 or frac >= 1.0:
            # 0.32.215: venda total sem sobra → fecha a conta do token e o aluguel (~0,002 SOL) volta para a carteira e para o trade
            back = 0.0
            if left <= 0 and not any(x.get("real") and x["mint"] == p["mint"] and x["id"] != p["id"] for x in self.positions()):
                fn = getattr(self.real, "close_empty", None)
                back = (await fn(p["mint"])) if fn else 0.0
            if back > 0:
                p["proceeds"] += back
                p["conta_devolvida_sol"] = round(back, 6)
                self._feed(wallet=p.get("wallet") or "manual", short=short(p.get("wallet") or "manual"), mint=p["mint"],
                           symbol=p.get("symbol"), kind="sell", action="conta do token fechada", real=True,
                           reason=f"{back:.5f} SOL de aluguel devolvidos para a carteira")
            # 0.32.449: rede = uma taxa por transação (compra + cada venda); vale também para posição aberta antes desta versão
            fp = p.setdefault("fee_parts", {})
            fp["network"] = fr["prio"] * (1 + len(p.get("sells") or []))
            p["fees_sol"] = sum(float(v or 0) for v in fp.values())
            pnl = p["proceeds"] - p["sol_in"]          # diferença REAL de SOL na carteira: já com todas as taxas
            tr = {"opened_at": p["opened_at"], "closed_at": now_iso(), "wallet": p["wallet"], "mint": p["mint"],
                  "symbol": p["symbol"], "sol_in": p["sol_in"], "sol_out": round(p["proceeds"], 6),
                  "pnl_sol": round(pnl, 6), "pnl_pct": round(pnl / p["sol_in"] * 100, 2), "price_in": p["price_in"],
                  "price_out": p.get("price_now"), "fees_sol": round(p["fees_sol"], 6), "reason": why,
                  "fee_parts": {k: round(v, 6) for k, v in (p.get("fee_parts") or {}).items()},
                  "gross_sol": round(pnl + p["fees_sol"], 6), "venue": p.get("venue_in"),
                  "hold_s": round(time.time() - p.get("open_t", time.time())), "sells": p.get("sells", []),
                  "real": True, "signature": p.get("signature"), "mcap_in": p.get("mcap_in"),
                  "mcap_out": (self.tokens.get(p["mint"]) or {}).get("mcap_sol")}
            tr["lag_s"] = p.get("lag_s")
            tr["best_pct"], tr["worst_pct"] = p.get("best_pct"), p.get("worst_pct")
            tr["score"] = p.get("score")
            tr["score_parts"] = p.get("score_parts")       # 0.32.117: cérebro em sombra mede pressão, curva e criador na entrada
            tr["trader_px"] = p.get("trader_px") or p.get("trader_price")
            tr["manual"] = bool(p.get("manual")) or p.get("wallet") == "manual"
            tr["sim_id"] = p.get("sim_id")                 # 0.31.38: par na fictícia (espelho)
            tr["lat"] = p.get("lat")                       # 0.31.51: tempo da compra real (montar, confirmar, total)
            tr["sell_tries"] = p.get("sell_tries")         # 0.32.107: cada tentativa de venda
            tr["fora_do_robo"] = bool(p.get("fora_do_robo"))   # 0.32.182: vendido fora do robô (sem o SOL na conta)
            tr["conta_devolvida_sol"] = p.get("conta_devolvida_sol")   # 0.32.215: aluguel da conta do token devolvido
            if p.get("fora_sigs"):
                tr["fora_sigs"] = p["fora_sigs"]           # 0.32.459: assinaturas das vendas feitas fora do robô
            tr["entrou_porque"] = self.entry_why(p)         # 0.32.60
            if self.sign_out(p):
                tr["sinal"] = self.sign_out(p)              # 0.32.423: tempo no positivo × negativo
            if p.get("origem"):
                tr["origem"] = p["origem"]                 # 0.32.401: o trade REAL guarda a aba (BOOST etc.), como a fictícia
            if p.get("auto") is True and p.get("origem") in AUTO_ORIGINS:
                closed = time.time()
                tr.update(id=p["id"], auto=True, origem=p["origem"], auto_info=copy.deepcopy(p.get("auto_info") or {}),
                          closed_t=closed, closed_at=datetime.fromtimestamp(closed, timezone.utc).isoformat(),
                          exit_price=p.get("price_now"))
            tr["api"] = self.api_used(p)                  # 0.32.220: gasto das APIs com esta moeda
            self._save_trade(tr)
            self._del_pos(p)
            self._after_close(tr)
            self._emit(f"[PUMP REAL] fechou {p['symbol']} ({why}) → {pnl:+.4f} SOL ({tr['pnl_pct']:+.1f}%) líquido")
            self._sim_follow(p, frac, got, sold, why, True)     # 0.32.158/0.32.160: a fictícia par sai junto
        else:
            self._save_pos(p)
            self._emit(f"[PUMP REAL] {p['symbol']}: vendeu {frac * 100:.0f}% ({why}) → {got:.4f} SOL")
            self._sim_follow(p, frac, got, sold, why, False)

    def _sim_follow(self, rp: dict, frac: float, got: float, sold: float, why: str, full: bool) -> None:
        """0.32.160 (cópia exata): depois de cada venda REAL confirmada, a fictícia par vende a mesma parte no preço que a real
        conseguiu (mesmo resultado em SOL). A real decide e executa primeiro; a fictícia só acompanha."""
        if rp.get("sim_id") is None or not (self.exact_on() or (rp.get("origem") == "boostmig" and not rp.get("bm_own"))):
            return                                       # 0.32.400: no BOOST a fictícia sempre acompanha a REAL
        sim = next((x for x in self.positions() if x["id"] == rp["sim_id"] and not x.get("real")), None)
        if not sim or not sim.get("tokens_left"):
            return
        ef = sim.pop("exit_follow", None)
        sfrac = 1.0 if full else frac
        qty = sim["tokens_left"] * sfrac
        fr = self._fee_rates(sim["mint"])
        px = None
        if sold and qty > 0:
            target = got * min(1.0, qty / sold) if not full else got * (qty / sold)
            px = (target + fr["prio"]) / (qty * (1 - fr["slip"]) * max(1e-9, 1 - fr["venue"] - fr["portal"]))
        px = px or (self.tokens.get(sim["mint"]) or {}).get("price") or sim.get("price_now")
        reason = (ef or {}).get("why") or why
        for pre in ("espelho do fictício: ", "junto com a fictícia: "):
            reason = reason[len(pre):] if reason.startswith(pre) else reason
        msg = self._sell(sim, sfrac, px, reason if ef else f"junto com a real: {reason}", time.time(), from_real=True)
        if msg:
            self._emit(msg)
        if not full and ef and float(ef.get("frac") or 0) >= 1.0:
            # a fictícia queria sair toda e a real vendeu só uma parte: pede o resto na real; a fictícia espera de novo
            still = next((x for x in self.positions() if x["id"] == rp["sim_id"] and not x.get("real")), None)
            if still:
                still["exit_follow"] = ef
                self._save_pos(still)
                self._real_sell(rp, 1.0, f"junto com a fictícia: {ef.get('why') or 'saída'}")

    # ------------------------------------------------------------------ painel
    ABA_ORIGEM = {"explorar": "Explorar", "barrado": "Explorar · barrados", "barrado_btn": "Explorar · barrados", "base": "Base da pump.fun",
                  "elite": "Maiores traders", "calls": "Calls quentes", "bruxo": "Aba do Bruxo",
                  "lancamento": "Lançamento sem trader", "jevtrade": "Jev Trade",
                  "boostmig": "BOOST da migração"}

    def entry_why(self, p: dict) -> str:
        """0.32.60 (pedido do dono: "explicar sempre o motivo que levou o robô a entrar e sair de tal moeda, e salvar"): o
        motivo da ENTRADA em texto, a partir do que a posição guardou quando abriu."""
        if p.get("entrou_porque"):
            return str(p["entrou_porque"])
        fo = p.get("follow_of") or {}
        if fo:
            return f"copiou a operação da conta {fo.get('nome') or 'seguida'} (mesmo valor e mesmas regras de saída)"
        bx = p.get("bruxo") or {}
        if p.get("origem") == "bruxo" or bx:
            parts = [f"top trader {', '.join(bx.get('names') or []) or '?'} comprou" + (f" {bx['trader_sol']:.2f} SOL" if bx.get("trader_sol") else "")]
            if bx.get("age_min") is not None:
                parts.append(f"token com {bx['age_min']:.1f} min de vida")
            if bx.get("flow") is not None:
                parts.append(f"ritmo de compra {bx['flow']:.1f} SOL/min" + (f" (média dos novos {bx['flow_base']:.1f})" if bx.get("flow_base") else ""))
            if bx.get("top10") is not None:
                parts.append(f"10 maiores com {bx['top10']:.0f}%")
            if bx.get("dev_pct") is not None:
                parts.append(f"criador com {bx['dev_pct']:.1f}%")
            return "Aba do Bruxo: " + " · ".join(parts)
        ai = p.get("auto_info") or {}
        if p.get("auto") is True and ai:
            txt = f"{self.aba_of(p)}: veredito {ai.get('veredito') or '?'}" + (f" ({ai['chance']}%)" if ai.get("chance") is not None else "")
            why = ai.get("why") or []
            return txt + (" · " + " · ".join(str(w) for w in why[:3]) if why else "")
        if isinstance(p.get("auto"), str) and p["auto"]:
            return str(p["auto"])                          # ex.: barrado que subiu (o texto do motivo da compra)
        if p.get("eq"):
            return f"Copiar igual: a carteira {short(p['wallet'])} comprou e a cópia entra sem filtro"
        if p.get("manual") or p.get("wallet") == "manual":
            return "você clicou em Comprar"
        out = f"copiou {short(p['wallet'])}" + (f": o trader comprou {p['trader_sol']:.2f} SOL" if p.get("trader_sol") else "")
        if p.get("score") is not None:
            out += f" · nota da entrada {float(p['score']):.0f}"
        if p.get("lag_s") is not None:
            out += f" · entrou {float(p['lag_s']):.1f} s depois dele"
        if p.get("mcap_in"):
            out += f" · market cap {float(p['mcap_in']):.0f} SOL"
        return out

    def aba_of(self, x: dict) -> str:
        """0.32.41 (pedido do dono: "no histórico, de qual aba está vindo cada trade"): a tela que originou a operação."""
        if x.get("follow_of"):
            return "Copiar trades de usuário"
        if x.get("origem") in self.ABA_ORIGEM:
            return self.ABA_ORIGEM[x["origem"]]
        if x.get("eq"):
            return "Copiar igual"
        w = x.get("wallet")
        # 0.32.119: a compra automática da Base não grava origem e caía como "Botão Comprar"; só o texto do motivo a separa
        if str(x.get("auto") or x.get("entrou_porque") or "").startswith("automático:"):
            return self.ABA_ORIGEM["base"]
        if x.get("manual") or w == "manual":
            return "Botão Comprar"
        lu = getattr(self, "study_lucro", None) or []
        if lu and w in lu and getattr(getattr(self, "cfg", None), "pump_st_lucro_on", False) and w not in (getattr(self, "manual", None) or []):
            return "Estudo · deram lucro"                # 0.32.211: copiadas pela chave do quadro novo
        if w in (getattr(self, "study", None) or []) or w in (getattr(self, "study_copy", None) or []):
            return "Carteiras em estudo"
        if w in (getattr(self, "elite_follow", None) or []):
            return "Maiores traders (80%+)"
        return "Top traders"

    def snapshot(self) -> dict:
        c = self.cfg
        rk = self.ranking_cache or self.ranking(100)
        fol = set(self.followed)
        man = set(self.manual)
        stats_by_w = {r["wallet"]: r for r in rk}
        lbmap = {r["wallet"]: r for r in self.leaderboard}
        copied = {}
        for t in self.trades(5000):
            d = copied.setdefault(t["wallet"], {"n": 0, "pnl_sol": 0.0, "wins": 0})
            d["n"] += 1
            d["pnl_sol"] += t["pnl_sol"]
            d["wins"] += t["pnl_sol"] > 0
        followed = []
        for w in self.followed:
            r = stats_by_w.get(w) or {"wallet": w, "short": short(w)}
            lbr = lbmap.get(w)
            followed.append({**r, "manual": w in man, "ia_sim": self._sim_only_base(w), "prova": self.needs_proof(w), "copied": copied.get(w), "lb": lbr,
                             "ignored": (self.rpc_status.get("ignored_by") or {}).get(w, 0),
                             "other_copied": (self.rpc_status.get("other_by") or {}).get(w, 0),
                             "act": self.activity_view(w),
                             "source": "manual" if w in man else "leaderboard" if lbr else "ranking"})
        for p in (pos := self.positions()):
            px = (self.tokens.get(p["mint"]) or {}).get("price")
            if px:
                p["price_now"] = px
                left_cost = p["sol_in"] * (p["tokens_left"] / p["tokens"]) if p.get("tokens") else 0
                val = self._exit_value(p, px)
                p["chg_pct"] = round((val / left_cost - 1) * 100, 2) if left_cost else None
                p["value_sol"] = round(val, 6)
                p["price_at"] = (self.tokens.get(p["mint"]) or {}).get("last_t")
                # 0.32.28 (pedido do dono: "o ganho real do momento"): o que já vendeu + o que vale agora − o que investiu
                p["pnl_now_sol"] = round(float(p.get("proceeds") or 0) + val - p["sol_in"], 6)
                p["pnl_now_pct"] = round(p["pnl_now_sol"] / p["sol_in"] * 100, 2) if p["sol_in"] else None
            p["api"] = self.api_used(p)                    # 0.32.220: gasto das APIs com esta moeda até agora
            tkp = self.tokens.get(p["mint"]) or {}
            # 0.31.69 (sugestão do Bruxo): tempo máximo desta posição e de onde ele vem, para a coluna "Tempo de saída"
            own = self._auto_num(p.get("max_hold_s"))
            p["hold_s"] = own if own is not None else float(self._c("pump_max_hold_h", 6)) * 3600
            p["hold_src"] = "posição" if own is not None else "geral"
            p["vol"] = tkp.get("vol")
            p["mcap_now"] = tkp.get("mcap_sol")
            p["liq_usd"] = tkp.get("liq_usd")
            # 0.32.427 (pedido do dono): no card, tempo no positivo × negativo (agora), o stop por tempo e os dados do BOOST
            so = self.sign_out(p)
            if so:
                g = p.get("sinal") or {}
                so["agora"] = "positivo" if g.get("up") else "negativo"
                so["seguidos_s"] = round(time.time() - float(g["neg_since"])) if (g.get("up") is False and g.get("neg_since") is not None) else 0
                p["sinal_now"] = so
            if p.get("origem") == "boostmig" and self.bm_view_hook is not None:
                try:
                    p["bm"] = self.bm_view_hook(p["mint"])
                except Exception:
                    p["bm"] = None
        return {"enabled": getattr(c, "pump_enabled", True), "copy_enabled": getattr(c, "pump_copy_enabled", True),
                "rpc": dict(self.rpc_status), "paid_stream": self._paid(),
                "status": {**self.status, "followed": len(self.followed), "tracked_tokens": len(self.sub_tokens),
                           "wallets_seen": len(self.wallets)},
                "paused": [{"wallet": w, "short": short(w), **v,
                            "act": self.activity_view(w), "lb": lbmap.get(w), "copied": copied.get(w)}
                           for w, v in self.paused().items()],
                "wallet_names": dict(self.market.__dict__.get("trader_names") or {}),
                "leaderboard": [r | {"followed": r["wallet"] in fol, "manual": r["wallet"] in man,
                                     "paused": r["wallet"] in self.paused(),
                                     "act": self.activity_view(r["wallet"]),
                                     "online": self.is_online(r["wallet"]),
                                     "top_active": r["wallet"] in self.top_active} for r in self.leaderboard],
                "lb_status": {**self.lb_status, "key_set": bool(self.lb_key()),
                              "source": "leaderboard" if self.leaderboard else "ranking próprio"},
                "tab_gate": self.tab_gate_view(),      # 0.32.325: trava por tela (o que cada tela já provou na fictícia)
                "followed": followed, "ranking": [r | {"followed": r["wallet"] in fol} for r in rk[:50]],
                "manual": self.manual, "banned": self.banned,
                "positions": [dict(p, aba=self.aba_of(p), entrou_porque=self.entry_why(p)) for p in pos], "trades": [dict(x, aba=self.aba_of(x)) for x in self.trades(300)],
                "feed": list(self.feed)[:150], "recent_closed": [dict(x, aba=self.aba_of(x)) for x in self.recent_closed()],
                "live": [e for e in list(self.live) if e["wallet"] in fol][:200], "trader_pos": self.trader_positions(),
                "wallet": self.wallet(), "real_wallet": self.wallet(real=True), "curve": self.curve(),
                "real_curve": self.curve(real=True), "pending": [{"wallet": k[0], "mint": k[1], "in_s": round(v["due"] - time.time())}
                                                          for k, v in self._pending.items()], "real_pending": {"buying": sorted(self._real_buying),
                                                                     "queue": self._rq.qsize() if self._rq else 0},
                "sol_usd": self.sol_usd,
                "cfg": {**{k: getattr(c, k, None) for k in USER_KEYS},
                        "pump_real_enabled": bool(getattr(c, "pump_real_enabled", False))},
                "real": {"enabled": bool(getattr(c, "pump_real_enabled", False)), "on_at": getattr(self, "real_on_at", None), "off_at": getattr(self, "real_off_at", None),
                         "alertas": list(getattr(self, "wallet_alerts", [])), "vigia_at": getattr(self, "_wg_at", None),
                         "wallet_configured": bool(self.sol_wallet and getattr(self.sol_wallet, "keypair", None)),
                         "api_key_set": bool(self.real and self.real.api_key()),
                         "address": getattr(self.sol_wallet, "address", None) if self.sol_wallet else None}}


class _Buying(set):
    """0.32.162: tokens com compra REAL na fila ou saindo, com a hora em que entraram. Uma compra leva no máximo ~3 min
    (o blockhash vence); uma entrada esquecida aqui contaria para sempre no limite de posições reais e travaria a real."""

    def __init__(self, *a):
        super().__init__(*a)
        self.at: dict = {}

    def add(self, m) -> None:
        super().add(m)
        self.at[m] = time.time()

    def discard(self, m) -> None:
        super().discard(m)
        self.at.pop(m, None)

    def prune(self, max_s: float = 600) -> list:
        old = [m for m, t in list(self.at.items()) if time.time() - t > max_s]
        for m in old:
            self.discard(m)
        return old


class PumpReal:
    """Execução REAL na pump.fun pela API de transação local da PumpPortal (a transação é montada por eles e
    ASSINADA aqui pela carteira do bot — a chave nunca sai do bot). DESLIGADA por padrão."""

    def __init__(self, cfg, http, wallet, keys, jup=None):
        self.cfg, self.http, self.wallet, self.keys = cfg, http, wallet, keys
        self.jup = jup                                   # DexCexReal (_dex_swap pela Jupiter) para tokens fora da pump.fun

    def api_key(self) -> str:
        return self.keys.get("pumpportal_api_key") if self.keys is not None else ""

    def today_loss(self, trades: list[dict]) -> float:
        day = datetime.now(timezone.utc).date().isoformat()
        return -sum(t.get("pnl_sol") or 0 for t in trades if t.get("real") and (t.get("closed_at") or "")[:10] == day)

    async def _rpc(self, method: str, params: list, url: str | None = None):
        r = await self.http.post(url or await self.wallet.safe_rpc_url(),
                                 json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=15)
        try:
            js = r.json()
        except ValueError:
            # 0.32.62: o RPC respondeu sem JSON (limite de pedidos, página de erro): diz o que foi, não "JSONDecodeError"
            raise RuntimeError(f"RPC respondeu HTTP {r.status_code} sem dados"
                               + (" (limite de pedidos)" if r.status_code == 429 else "") + f" em {method}") from None
        if "error" in js:
            raise RuntimeError(str(js["error"])[:160])
        return js["result"]

    async def balances(self, mint: str, zero_ok: bool = False) -> tuple[float, float]:
        """(SOL, tokens do mint) da carteira do bot, direto da blockchain."""
        # 0.32.402 (pedido do dono: "mudar a compra e a venda para não ter erros" — 429 do RPC): uma consulta leve só
        # (getMultipleAccounts da carteira + as 2 contas associadas do token) em vez de getBalance + getTokenAccountsByOwner,
        # que é o pedido que os RPCs mais limitam. Se a resposta vier estranha, ou o token não estiver na conta associada,
        # volta para o jeito antigo.
        try:
            atas = sorted(txguard.token_atas(self.wallet.address, mint))
            r = await self._rpc_retry("getMultipleAccounts", [[self.wallet.address] + atas,
                                                              {"encoding": "jsonParsed", "commitment": "confirmed"}])
            vals = (r or {}).get("value") if isinstance(r, dict) else None
            if isinstance(vals, list) and len(vals) == 1 + len(atas) and isinstance(vals[0], dict):
                sol, tok, found = float(vals[0].get("lamports") or 0) / 1e9, 0.0, False
                for a in vals[1:]:
                    if a:
                        ta = a["data"]["parsed"]["info"]["tokenAmount"]
                        tok += float(ta.get("uiAmountString") or ta.get("uiAmount") or 0)
                        found = True
                if found or zero_ok or getattr(self, "_zero_ok", None) == mint:   # antes de comprar, não ter o token é o normal
                    self.rpc_light["leve"] = self.rpc_light.get("leve", 0) + 1
                    return sol, tok
        except Exception:
            pass
        self.rpc_light["completa"] = self.rpc_light.get("completa", 0) + 1
        # 0.31.51: as duas consultas vão juntas (antes uma esperava a outra)
        b, res = await asyncio.gather(
            self._rpc_retry("getBalance", [self.wallet.address, {"commitment": "confirmed"}]),
            self._rpc_retry("getTokenAccountsByOwner", [self.wallet.address, {"mint": mint},
                                                  {"encoding": "jsonParsed", "commitment": "confirmed"}]))
        sol = b["value"] / 1e9
        tok = 0.0
        for a in (res or {}).get("value") or []:
            ta = a["account"]["data"]["parsed"]["info"]["tokenAmount"]
            tok += float(ta.get("uiAmountString") or ta.get("uiAmount") or 0)
        return sol, tok

    rpc_light: dict = {}                           # 0.32.402: quantas leituras leves × completas (servidor todo)
    pool_hint: dict = {}                           # 0.32.422: mint → "pump-amm" quando já graduou (venda direto na PumpSwap)
    TACC_TTL_S = 60.0                              # 0.32.402: lista das contas de token da carteira guardada por 60 s

    async def _others_full(self, owner: str):
        """Lista completa das contas de token da carteira (2 programas) + o SOL: o jeito antigo, mais pesado no RPC."""
        self.rpc_light["completa"] = self.rpc_light.get("completa", 0) + 1
        return await asyncio.gather(*[self._rpc_retry("getTokenAccountsByOwner", [owner, {"programId": prog},
                                                                                  {"encoding": "jsonParsed", "commitment": "processed"}])
                                      for prog in (txguard.TOKEN, txguard.TOKEN_2022)],
                                    self._rpc_retry("getBalance", [owner, {"commitment": "processed"}]))

    async def _others_cached(self, owner: str, mint: str | None):
        """0.32.402: com a lista das contas de token guardada há menos de 60 s, lê os saldos de agora de todas elas (e o SOL)
        numa consulta leve (getMultipleAccounts, até 100 por vez). Devolve (None, None) para usar o jeito completo."""
        c = getattr(self, "_tacc", None)
        if not c or c.get("owner") != owner or time.time() - float(c.get("t") or 0) > self.TACC_TTL_S:
            return None, None
        keys = [owner] + list(c.get("keys") or [])
        try:
            vals = []
            for i in range(0, len(keys), 100):
                r = await self._rpc_retry("getMultipleAccounts", [keys[i:i + 100], {"encoding": "jsonParsed", "commitment": "processed"}])
                v = (r or {}).get("value") if isinstance(r, dict) else None
                if not isinstance(v, list) or len(v) != len(keys[i:i + 100]):
                    return None, None
                vals += v
            if not isinstance(vals[0], dict):
                return None, None
            pre, others = int(vals[0].get("lamports") or 0), []
            for k, a in zip(keys[1:], vals[1:]):
                if not a:
                    continue                           # conta fechada desde a última lista
                info = a["data"]["parsed"]["info"]
                if info.get("mint") != mint:
                    others.append((k, int(info["tokenAmount"]["amount"])))
            self.rpc_light["leve"] = self.rpc_light.get("leve", 0) + 1
            return others, pre
        except Exception:
            return None, None

    async def _send_raw(self, raw_b64: str, opts: dict) -> str:
        """0.32.98 (dono, 30/10 22:28: "RPC respondeu HTTP 429 sem dados em sendTransaction"): o envio tentava uma vez só no RPC
        da carteira. Agora, se o RPC recusar por limite de pedidos ou sem resposta, tenta de novo em 0,3 s e depois no RPC
        público da Solana. Reenviar a MESMA transação assinada é seguro: a assinatura é a mesma e a rede só executa uma vez.
        Erro da própria transação (saldo, slippage, programa) não é repetido."""
        last: Exception | None = None
        own = await self.wallet.safe_rpc_url()
        urls = [own, own] + ([SOL_HTTP] if own != SOL_HTTP else [])
        for i, url in enumerate(urls):
            try:
                return await self._rpc("sendTransaction", [raw_b64, opts], url=url)
            except Exception as e:
                last = e
                msg = str(e)
                if not ("HTTP" in msg or "429" in msg or "sem dados" in msg or isinstance(e, OSError) or type(e).__module__.startswith("httpx")):
                    raise                              # a rede recusou a transação: não adianta repetir
                if i < len(urls) - 1:
                    await asyncio.sleep(1.0 if ("429" in msg or "Too many" in msg) else 0.3)   # 0.32.402: limite precisa de mais tempo
        raise last if last else RuntimeError("sendTransaction sem resposta")

    async def _send_confirm(self, raw_b64: str, simulated: bool = False) -> tuple[str | None, str, str | None]:
        try:
            # 0.31.51: transação que o servidor já simulou não passa por outra simulação no RPC (economiza uma ida)
            sig = await self._send_raw(raw_b64, {"encoding": "base64", "skipPreflight": bool(simulated),
                                                 "preflightCommitment": "processed", "maxRetries": 3})
        except Exception as e:
            return None, "recusada", str(e)[:160]
        # 0.32.101 (BALLOON/MLC, 30/10 23:08: 172 s para confirmar): conferir a cada 0,25 s e reenviar a cada 1 s no RPC da
        # carteira estourava o limite dele (429) — as conferências falhavam e a compra só aparecia depois do blockhash vencer.
        # Agora confere a cada 0,5 s; se o RPC da carteira recusar, confere no RPC público; reenvia a cada 2 s nos dois.
        own = await self.wallet.safe_rpc_url()
        pub = SOL_HTTP if own != SOL_HTTP else None
        # 0.32.431: confere a cada 0,25 s nos primeiros 8 s (quando quase toda transação confirma) e depois a cada 0,5 s
        t_send = time.monotonic()
        for i in range(150):
            await asyncio.sleep(0.25 if time.monotonic() - t_send < 8 else 0.5)
            if i % 8 == 7:
                for url in [own] + ([pub] if pub else []):
                    try:
                        await self._rpc("sendTransaction", [raw_b64, {"encoding": "base64", "skipPreflight": True, "maxRetries": 0}],
                                        url=url)
                    except Exception:
                        pass
            st = None
            for url in [own] + ([pub] if pub else []):
                try:
                    st = (await self._rpc("getSignatureStatuses", [[sig]], url=url))["value"][0]
                    break
                except Exception:
                    continue
            if st is None:
                continue
            if st and st.get("err"):
                return sig, "falhou", str(st["err"])[:120]
            if st and st.get("confirmationStatus") in ("confirmed", "finalized"):
                return sig, "confirmada", None
        return sig, "pendente", "sem confirmação em 60 s"

    async def _tx(self, body: dict, gate=None) -> dict:
        """gate (0.32.431): conferência que roda EM PARALELO com a montagem na PumpPortal (ex.: o saldo da carteira) e é
        esperada só antes de assinar — economiza uma ida ao RPC em cada compra e venda."""
        if body.get("action") == "buy" and not getattr(self.cfg, "pump_real_enabled", False):
            return {"status": "não executou", "reason": "execução real desligada"}
        if not self.wallet or not self.wallet.keypair:
            return {"status": "não executou", "reason": "carteira Solana do bot não configurada"}
        body = {"publicKey": self.wallet.address, "slippage": float(getattr(self.cfg, "pump_real_slippage_pct", 15)),
                "priorityFee": float(getattr(self.cfg, "pump_priority_sol", 0.0005)), "pool": "auto", **body}
        body = {k: (str(v) if not isinstance(v, str) else v) for k, v in body.items()}
        t0 = time.monotonic()
        try:
            # 0.32.443 (BRUISER, 24/11 19:59: a PumpPortal não respondeu em 15 s e a compra REAL inteira caiu com
            # ReadTimeout, sem tentar outra rota). Sem resposta aqui nenhuma transação foi montada, então é seguro ir
            # para a próxima rota; espera no máx. PP_TIMEOUT_S para não perder o momento.
            r = await self.http.post(TRADE_LOCAL_URL, data=body, timeout=httpx.Timeout(self.PP_TIMEOUT_S, connect=3.0))
        except (httpx.TimeoutException, httpx.TransportError) as e:
            return {"status": "falhou", "pp_down": True,
                    "reason": f"PumpPortal não respondeu em {self.PP_TIMEOUT_S:.0f} s ({type(e).__name__})"}
        if r.status_code != 200:
            return {"status": "falhou", "reason": f"PumpPortal HTTP {r.status_code}: {r.text[:120]}"}
        from solders.transaction import VersionedTransaction
        try:
            tx = VersionedTransaction.from_bytes(r.content)
            # SEC-01 (auditoria 2026-10-25): só assina se a transação fizer o que foi pedido
            summary = txguard.check(tx.message, self.wallet.address, mint=body.get("mint"), **self._limits(body))
        except Exception as e:
            log.warning("PumpPortal: transação recusada antes de assinar (%s)", str(e)[:160])
            return {"status": "recusada", "reason": f"transação recusada pela verificação: {str(e)[:120]}"}
        tb = time.monotonic()
        if gate is not None:
            stop = await gate()
            if stop:
                return {"status": "não executou", "reason": stop, "gate": True}
        tg = time.monotonic()
        signed = VersionedTransaction(tx.message, [self.wallet.keypair])
        raw = base64.b64encode(bytes(signed)).decode()
        if summary.get("needs_simulation"):
            why = await self._sim_guard(raw, body.get("mint"), self._limits(body))
            if why:
                log.warning("PumpPortal: transação recusada na simulação (%s)", why[:160])
                return {"status": "recusada", "reason": f"transação recusada pela simulação: {why}"}
        t1 = time.monotonic()
        sig, st, err = await self._send_confirm(raw, simulated=bool(summary.get("needs_simulation")))
        if st == "pendente":                     # SEC-04: espera confirmar ou vencer antes de qualquer nova tentativa
            st, err = await txguard.reconcile(self._rpc_retry, sig, str(tx.message.recent_blockhash))
        # 0.31.51: quanto tempo levou cada parte; 0.32.431: separado em montar (PumpPortal), saldo, simular e enviar+confirmar
        lat = {"montar_ms": round((t1 - t0) * 1000), "confirmar_ms": round((time.monotonic() - t1) * 1000),
               "pumpportal_ms": round((tb - t0) * 1000), "saldo_ms": round((tg - tb) * 1000), "simular_ms": round((t1 - tg) * 1000)}
        return {"status": st, "signature": sig, "reason": err, "ok": st == "confirmada", "lat": lat}

    async def _rpc_retry(self, method: str, params: list):
        """0.31.55 (PJAM, pfp e CLAVA, 27/10: "não deu para simular (RuntimeError)"): o RPC às vezes recusa um pedido
        (limite de pedidos por segundo, nó atrasado). Tenta de novo em 0,15 s e 0,3 s; na última vez usa o RPC público
        da Solana se a carteira usa outro. Só leitura e simulação passam por aqui; o envio da transação não muda."""
        last = None
        for i in range(3):
            try:
                if i == 2 and (await self.wallet.safe_rpc_url()) != SOL_HTTP:
                    return await self._rpc(method, params, url=SOL_HTTP)
                return await self._rpc(method, params)
            except Exception as e:
                last = e
                if i < 2:
                    # 0.32.402: limite de pedidos (429) não libera em 0,15 s; espera 1 s e 2 s antes de tentar de novo
                    lim = "429" in str(e) or "Too many requests" in str(e) or "limite de pedidos" in str(e)
                    await asyncio.sleep((1.0 if lim else 0.15) * (i + 1))
        raise last

    PP_TIMEOUT_S = 6.0                             # 0.32.443: espera máxima pela PumpPortal montar a transação

    SIM_BATCH = 19                                 # contas de token por simulação (+ a carteira); diminui sozinho se o RPC pedir

    async def _sim_guard(self, raw_b64: str, mint: str | None, lim: dict) -> str | None:
        """0.31.48: para a rota intermediária da PumpPortal (txguard.PUMPPORTAL_ROUTER), simula ANTES de enviar e devolve
        o motivo para não enviar: SOL saindo da carteira acima do pedido + tetos de taxa, ou outro token da carteira mexido.
        Falha fechada: se não der para simular, não envia."""
        owner = self.wallet.address
        try:
            others, pre = await self._others_cached(owner, mint)
            if others is None:
                others = []
                r1, r2, bal = await self._others_full(owner)
                listed = []
                for res in (r1, r2):
                    for a in (res or {}).get("value") or []:
                        info = a["account"]["data"]["parsed"]["info"]
                        listed.append(a["pubkey"])
                        if info.get("mint") != mint:
                            others.append((a["pubkey"], int(info["tokenAmount"]["amount"])))
                pre = bal["value"]
                self._tacc = {"owner": owner, "t": time.time(), "keys": listed}
            # (0.32.402: a lista das contas de token fica guardada 60 s; os saldos são lidos de novo numa consulta leve)
            # 0.31.58 (AI, 27/10 18:00: "Too many accounts provided; max 22"): o RPC aceita no máximo 22 contas por
            # simulação. A carteira do bot tem mais contas de token que isso, então a conferência vai em lotes de 21
            # (+ a carteira), todos ao mesmo tempo. Nenhuma conta deixa de ser conferida.
            # 0.32.100 (LENNY, 30/10 23:00: "Too many accounts provided; max 21"): o limite muda de RPC para RPC (22 em 27/10,
            # 21 agora). Lote padrão = 19 contas + a carteira (20) e, se o RPC disser "max N", refaz os lotes com N − 1 + a carteira.
            others = others[:200]
            size = self.SIM_BATCH
            for _ in range(3):
                chunks = [others[i:i + size] for i in range(0, len(others), size)] or [[]]
                try:
                    sims = await asyncio.gather(*[self._rpc_retry("simulateTransaction", [raw_b64, {
                        "encoding": "base64", "sigVerify": False, "commitment": "processed",
                        "accounts": {"encoding": "base64", "addresses": [owner] + [k for k, _ in ch]}}]) for ch in chunks])
                    break
                except Exception as e:
                    m = re.search(r"Too many accounts provided; max (\d+)", str(e))
                    if not m or int(m.group(1)) - 1 >= size or int(m.group(1)) < 2:
                        raise
                    size = int(m.group(1)) - 1
                    type(self).SIM_BATCH = size          # lembra o limite para as próximas simulações
        except Exception as e:
            return f"não deu para simular ({type(e).__name__}: {str(e)[:120]})"
        for sim, ch in zip(sims, chunks):
            why = self._sim_check(sim, int(pre), ch, lim)
            if why:
                return why
        return None

    @staticmethod
    def _sim_check(sim, pre: int, others: list, lim: dict) -> str | None:
        v = (sim or {}).get("value") or {}
        if v.get("err"):
            return f"a simulação falhou: {str(v['err'])[:100]}"
        logs = v.get("logs") or []
        if not any((txguard.PUMP in str(line) or txguard.PUMP_AMM in str(line)) and "invoke" in str(line) for line in logs):
            return "a simulação não mostra a pump.fun sendo chamada"
        accs = v.get("accounts") or []
        if not accs or not accs[0]:
            return "a simulação não devolveu o saldo da carteira"
        spent = int(pre) - int(accs[0]["lamports"])
        cap = (int(lim["max_spend_lamports"]) + int(lim["max_fee_lamports"]) + int(lim["max_priority_lamports"])
               + txguard.MAX_RENT_LAMPORTS + 100_000)
        if spent > cap:
            return f"tiraria {spent / 1e9:.4f} SOL da carteira (teto {cap / 1e9:.4f} SOL)"
        for (key, amount), acc in zip(others, accs[1:]):
            if not acc:
                return "fecharia outra conta de token da carteira"
            data = base64.b64decode((acc.get("data") or [""])[0])
            if len(data) < 72 or int.from_bytes(data[64:72], "little") != amount:
                return "mexeria em outro token da carteira"
        return None

    def _limits(self, body: dict) -> dict:
        """Tetos da verificação: compra gasta no máximo o valor + slippage (+5%); taxa de terceiros até 2% + 0,001 SOL;
        venda não pode gastar SOL e paga no máximo SELL_FEE_CAP_SOL a terceiros."""
        slip = float(body.get("slippage") or 15)
        prio = int(max(float(body.get("priorityFee") or 0) * 1.5, 0.002) * 1e9)
        if body.get("action") == "buy":
            amt = float(body.get("amount") or 0)
            return {"max_spend_lamports": int(amt * (1 + slip / 100) * 1.05 * 1e9),
                    "max_fee_lamports": int(amt * 0.02 * 1e9) + 1_000_000, "max_priority_lamports": prio}
        return {"max_spend_lamports": 0, "max_fee_lamports": int(SELL_FEE_CAP_SOL * 1e9), "max_priority_lamports": prio}

    async def signature_status(self, sig: str) -> str | None:
        return (await txguard.signature_status(self._rpc, sig))[0]

    # erros do programa da pump.fun (Anchor: 6000 + n)
    PUMP_ERRORS = {"0x1770": "não autorizado", "0x1772": "preço subiu além do slippage (SOL insuficiente)",
                   "0x1773": "preço caiu além do slippage (SOL recebido baixo)", "0x1774": "na pump.fun: token não bate com a curva; na PumpSwap: o pool recusou (provável preço andando além do slippage)",
                   "0x1775": "curva já completou — token graduou para a PumpSwap",
                   "0x1776": "curva ainda não completou", "0x1777": "programa da pump.fun não inicializado",
                   # 0.32.25: o mesmo código muda de sentido conforme o programa. IDL oficial pump.json (13/10/2026, conferido em
                   # 28/10): na pump.fun 6001 = AlreadyInitialized; slippage é 6002 (compra) e 6003 (venda). Na Jupiter, 6001 =
                   # slippage excedido. Por isso continua contando como "tentar de novo" (retryable).
                   "0x1771": "erro 6001: na Jupiter = slippage excedido; na pump.fun = programa já inicializado",
                   # 0.31.83 (Grokbot 28/10 07:55, sugestão do Bruxo): erro 6063 do programa da pump.fun = UnsupportedQuoteMint
                   # (IDL oficial pump.json). A curva é cotada em outra moeda (Grokbot: SPCX) e a PumpPortal manda SOL.
                   # 0.32.27: na PumpSwap (IDL pump_amm.json de 07/10/2026, conferido em 28/10) o mesmo 6063 é
                   # InsufficientRealQuoteReserves — o pool não tem a moeda de cotação suficiente para a venda/compra.
                   # 0.32.98: a simulação devolve o código em decimal ({'Custom': 6005}), não em hex (0x1775)
                   "'Custom': 6002}": "preço subiu além do slippage (SOL insuficiente)",
                   "'Custom': 6003}": "preço caiu além do slippage (SOL recebido baixo)",
                   "'Custom': 6004}": "token não bate com a curva",
                   "'Custom': 6005}": "curva já completou — token graduou para a PumpSwap",
                   "'Custom': 6063": "erro 6063: na curva da pump.fun = cotada em outra moeda (não SOL); na PumpSwap = pool sem reserva suficiente",
                   "0x17af": "erro 6063: na curva da pump.fun = cotada em outra moeda (não SOL); na PumpSwap = pool sem reserva suficiente"}

    @classmethod
    def explain(cls, reason) -> str | None:
        if not reason:
            return None
        r = str(reason)
        for code, txt in cls.PUMP_ERRORS.items():
            if code in r:
                return f"{txt} ({code})"
        if "insufficient" in r.lower():
            return "saldo insuficiente para a transação"
        return r[:140]

    @staticmethod
    def retryable(reason) -> bool:
        """Vale tentar outro caminho? (curva completa, rota errada, slippage, PumpPortal sem resposta)"""
        r = str(reason or "")
        return any(c in r for c in ("PumpPortal não respondeu", "0x1775", "0x1774", "0x1772", "0x1773", "0x1771", "HTTP 400", "HTTP 500",
                                    "'Custom': 6005}", "'Custom': 6004}", "'Custom': 6002}", "'Custom': 6003}"))

    @staticmethod
    def other_quote(reason) -> bool:
        """0.31.83: a PumpPortal recusou porque a curva não é cotada em SOL — só a Jupiter pode tentar (SOL → moeda → token)."""
        r = str(reason or "")
        return "'Custom': 6063" in r or "0x17af" in r or "UnsupportedQuoteMint" in r

    async def _jup(self, inp: str, out: str, amount: int, slip_bps: int) -> dict:
        """Troca pela Jupiter (melhor rota entre as DEXs) — para tokens fora da pump.fun."""
        if self.jup is None:
            return {"status": "não executou", "reason": "Jupiter indisponível"}
        r = await self.jup._dex_swap(inp, out, amount, slip_bps=slip_bps, prio="high")
        return {"status": r.get("status") or ("confirmada" if r.get("ok") else "falhou"), "signature": r.get("signature"),
                "reason": r.get("reason"), "ok": bool(r.get("ok"))}

    TOKEN_PROGRAMS = ("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb")
    CLOSE_FEE_SOL = 0.000005                     # taxa base de uma transação com 1 assinatura

    async def close_empty(self, mint: str) -> float:
        """0.32.215 (dono, 05/11: a compra REAL de 0,001 SOL gastou 0,0073 SOL): cada token novo cria uma conta na carteira
        (~0,002 SOL de aluguel) e o robô não fechava essa conta depois de vender, então o valor ficava preso. Fecha as contas
        deste token com saldo ZERO (a rede recusa fechar conta com saldo) e devolve o SOL para a carteira.
        Devolve o SOL recuperado (já sem a taxa); 0 se não havia conta vazia ou se algo falhou (a venda não é afetada)."""
        if not self.wallet or not getattr(self.wallet, "keypair", None):
            return 0.0
        try:
            res = await self._rpc_retry("getTokenAccountsByOwner", [self.wallet.address, {"mint": mint},
                                                                    {"encoding": "jsonParsed", "commitment": "confirmed"}])
            vazias = []
            for a in (res or {}).get("value") or []:
                acc = a.get("account") or {}
                info = (((acc.get("data") or {}).get("parsed") or {}).get("info") or {})
                amount = int(((info.get("tokenAmount") or {}).get("amount")) or 0)
                if amount == 0 and acc.get("owner") in self.TOKEN_PROGRAMS and info.get("owner") == self.wallet.address:
                    vazias.append((a["pubkey"], acc["owner"], int(acc.get("lamports") or 0)))
            if not vazias:
                return 0.0
            from solders.hash import Hash
            from solders.instruction import AccountMeta, Instruction
            from solders.message import Message
            from solders.pubkey import Pubkey
            from solders.transaction import Transaction
            dono = Pubkey.from_string(self.wallet.address)
            ixs = [Instruction(Pubkey.from_string(prog), bytes([9]),        # 9 = CloseAccount (Token e Token-2022)
                               [AccountMeta(Pubkey.from_string(conta), False, True), AccountMeta(dono, False, True),
                                AccountMeta(dono, True, False)]) for conta, prog, _ in vazias[:8]]
            bh = Hash.from_string((await self._rpc_retry("getLatestBlockhash", [{"commitment": "confirmed"}]))["value"]["blockhash"])
            tx = Transaction([self.wallet.keypair], Message.new_with_blockhash(ixs, dono, bh), bh)
            sig, st, err = await self._send_confirm(base64.b64encode(bytes(tx)).decode())
            if st != "confirmada":
                log.info("conta do token %s não fechou: %s %s", mint[:6], st, err)
                return 0.0
            return max(0.0, sum(lam for _, _, lam in vazias[:8]) / 1e9 - self.CLOSE_FEE_SOL)
        except Exception as e:
            log.info("conta do token %s não fechou: %s", mint[:6], str(e)[:160])
            return 0.0

    async def _raw_tok(self, mint: str) -> tuple[int, int]:
        res = await self._rpc_retry("getTokenAccountsByOwner", [self.wallet.address, {"mint": mint},
                                                          {"encoding": "jsonParsed", "commitment": "confirmed"}])
        raw, dec = 0, 0
        for a in (res or {}).get("value") or []:
            ta = a["account"]["data"]["parsed"]["info"]["tokenAmount"]
            raw += int(ta.get("amount") or 0)
            dec = int(ta.get("decimals") or 0)
        return raw, dec

    async def external_sold(self, mint: str, since_t: float, skip=()) -> tuple[float, float, list, float]:
        """0.32.459 (BAH do dono, 25/11: vendeu no app da carteira e o robô não viu): procura nas últimas transações da carteira
        as vendas deste token feitas fora do robô depois de `since_t` (as do robô, em `skip`, ficam de fora). Devolve o SOL que
        entrou, os tokens que saíram, as assinaturas e o aluguel da conta do token fechada fora do robô. Só leitura; até 25."""
        owner = self.wallet.address
        sol = tok = rent = 0.0
        found = []
        try:
            sigs = await self._rpc_retry("getSignaturesForAddress", [owner, {"limit": 25, "commitment": "confirmed"}]) or []
        except Exception:
            return 0.0, 0.0, [], 0.0
        for x in sigs:
            sig = x.get("signature")
            if not sig or x.get("err") or sig in skip:
                continue
            if x.get("blockTime") and float(x["blockTime"]) < since_t:
                break                                    # a lista vem da mais nova para a mais velha
            try:
                tx = await self._rpc_retry("getTransaction", [sig, {"encoding": "jsonParsed", "commitment": "confirmed",
                                                                    "maxSupportedTransactionVersion": 1}])
            except Exception:
                continue
            meta = (tx or {}).get("meta") or {}
            if not meta or meta.get("err"):
                continue

            def amt(bals):
                return sum(float(((b.get("uiTokenAmount") or {}).get("uiAmountString")) or 0) for b in bals or []
                           if b.get("owner") == owner and b.get("mint") == mint)
            dt = amt(meta.get("postTokenBalances")) - amt(meta.get("preTokenBalances"))
            keys = [(k.get("pubkey") if isinstance(k, dict) else k)
                    for k in ((((tx or {}).get("transaction") or {}).get("message") or {}).get("accountKeys") or [])]
            if owner not in keys:
                continue
            i = keys.index(owner)
            ds = (int(meta["postBalances"][i]) - int(meta["preBalances"][i])) / 1e9

            def has(bals):
                return any(b.get("owner") == owner and b.get("mint") == mint for b in bals or [])
            if dt == 0 and ds > 0 and has(meta.get("preTokenBalances")) and not has(meta.get("postTokenBalances")):
                rent += ds                               # conta do token vazia fechada fora do robô: o aluguel voltou
                found.append(sig)
                continue
            if dt >= 0:
                continue
            if ds <= 0:
                continue                                 # token saiu sem SOL entrar (transferência): não é venda
            sol += ds
            tok += -dt
            found.append(sig)
        return sol, tok, found, rent

    async def _sol_change(self, sig: str | None) -> float | None:
        """Quanto SOL a carteira do bot ganhou (+) ou gastou (−) NESSA transação (meta pré/pós da conta que paga).
        0.31.46: com as ordens em paralelo, a diferença de saldo da carteira misturaria duas ordens."""
        if not sig:
            return None
        try:
            tx = None
            for k in range(4):                         # 0.32.101: a transação recém-confirmada pode demorar a aparecer; RPC
                tx = await self._rpc_retry("getTransaction", [sig, {"encoding": "json", "commitment": "confirmed",   # com
                                                                    "maxSupportedTransactionVersion": 1}])           # reserva
                if tx:
                    break
                await asyncio.sleep(1.0)
            meta = (tx or {}).get("meta") or {}
            keys = (((tx or {}).get("transaction") or {}).get("message") or {}).get("accountKeys") or []
            i = keys.index(self.wallet.address) if self.wallet.address in keys else 0
            return (int(meta["postBalances"][i]) - int(meta["preBalances"][i])) / 1e9
        except Exception:
            return None

    async def buy(self, mint: str, amt: float, other: bool = False) -> dict:
        """Compra REAL de `amt` SOL do token. Mede o que saiu e o que entrou na carteira (valores reais).
        other=True: token fora da pump.fun → compra pela Jupiter."""
        if not getattr(self.cfg, "pump_real_enabled", False):
            return {"ok": False, "reason": "execução real desligada"}
        if not self.wallet or not self.wallet.keypair:
            return {"ok": False, "reason": "carteira Solana do bot não configurada"}
        # 0.32.431 (dono: "qualquer milissegundo de perda prejudica"): o saldo de antes é lido EM PARALELO com a montagem da
        # transação na PumpPortal e conferido antes de assinar (antes era uma ida ao RPC a mais, na frente de tudo)
        self._zero_ok = mint                             # 0.32.402: antes de comprar, não ter o token é o normal (leitura leve)
        bal_task = asyncio.ensure_future(self.balances(mint))
        bal_task.add_done_callback(lambda _t: setattr(self, "_zero_ok", None))

        async def gate() -> str | None:
            s0, _t0 = await bal_task
            return None if s0 >= amt + 0.02 else f"saldo insuficiente: {s0:.4f} SOL (precisa {amt:.3f} + 0,02 de reserva)"
        jslip = int(float(getattr(self.cfg, "pump_other_slip_pct", 1.0)) * 100) + 100
        tried = []
        # pump.fun: curva → se a curva já completou (token graduou), PumpSwap → se ainda falhar, Jupiter
        base = float(getattr(self.cfg, "pump_real_slippage_pct", 15))
        hint = (getattr(self, "pool_hint", None) or {}).pop(mint, None)
        if other:
            routes = [("jupiter", None, None)]
        elif hint == "pump-amm":
            # 0.32.430 (DESPAIR do BOOST, 21/11 18:14): token que já graduou compra direto na PumpSwap — a "auto" tentava a curva
            # (6005) e perdia o momento; PumpSwap e Jupiter recusaram pelo preço andando: tenta de novo com mais slippage
            routes = [("pumpportal", "pump-amm", base), ("pumpportal", "pump-amm", max(30.0, base)),
                      ("jupiter", None, base), ("jupiter", None, max(30.0, base))]
        else:
            routes = [("pumpportal", "auto", None), ("pumpportal", "pump-amm", None), ("jupiter", None, None)]
        r, first, pp_down = {}, True, False
        sol0 = tok0 = sol1 = tok1 = None
        for via, pool, slip in routes:
            if via == "pumpportal" and pp_down:          # 0.32.443: PumpPortal sem resposta → vai direto para a Jupiter
                continue
            if via == "jupiter" and first:
                why = await gate()
                if why:
                    return {"ok": False, "reason": why}
            if via == "jupiter":
                # 0.31.48: token da pump.fun na Jupiter (reserva) usa a slippage da carteira real; com 3% fixo a compra do
                # SPAWN falhou com "slippage excedido (0x1771)" em 27/10/2026
                pslip = int(float(slip if slip is not None else base) * 100)
                r = await self._jup(SOL_MINT, mint, int(amt * 1e9), jslip if other else max(jslip, pslip))
            else:
                body = {"action": "buy", "mint": mint, "amount": amt, "denominatedInSol": "true", "pool": pool}
                if slip is not None:
                    body["slippage"] = slip
                import inspect
                if first and "gate" in inspect.signature(self._tx).parameters:
                    r = await self._tx(body, gate=gate)
                else:
                    if first:
                        why = await gate()
                        if why:
                            return {"ok": False, "reason": why}
                    r = await self._tx(body)
                if r.get("gate"):
                    return {"ok": False, "reason": r.get("reason")}
                pp_down = pp_down or bool(r.get("pp_down"))
            first = False
            if sol0 is None:
                sol0, tok0 = await bal_task
                sol1, tok1 = sol0, tok0
                if sol0 < amt + 0.02:                    # a 1ª rota falhou antes de conferir o saldo: as próximas não saem
                    return {"ok": False, "reason": f"saldo insuficiente: {sol0:.4f} SOL (precisa {amt:.3f} + 0,02 de reserva)"}
            if r.get("status") == "pendente":
                await asyncio.sleep(3)
            (sol1, tok1), dsol = await asyncio.gather(self.balances(mint), self._sol_change(r.get("signature") if r.get("ok") else None))
            tried.append(f"{via if via == 'jupiter' else 'PumpPortal ' + pool}{f' {slip:.0f}%' if slip is not None else ''}: "
                         f"{self.explain(r.get('reason')) or r.get('status')}")
            if tok1 - tok0 > 0:
                break
            if r.get("status") == "pendente":     # SEC-04: ainda pode entrar — outra rota compraria duas vezes
                break
            if via != "jupiter" and self.other_quote(r.get("reason")):
                # 0.31.83: PumpSwap também não serve (a curva nem graduou); vai direto para a Jupiter, que roteia pela moeda
                r2 = await self._jup(SOL_MINT, mint, int(amt * 1e9), max(jslip, int(float(getattr(self.cfg, "pump_real_slippage_pct", 15)) * 100)))
                if r2.get("status") == "pendente":
                    await asyncio.sleep(3)
                (sol1, tok1), dsol = await asyncio.gather(self.balances(mint), self._sol_change(r2.get("signature") if r2.get("ok") else None))
                tried.append("jupiter: " + str(self.explain(r2.get("reason")) or r2.get("status") or "sem rota para essa moeda"))
                r = r2
                break
            if not self.retryable(r.get("reason")):
                break
        self._tacc = None                                # 0.32.402: a compra pode ter criado uma conta de token: lista de novo
        if tok1 - tok0 <= 0:
            return {"ok": False, "status": r.get("status"), "signature": r.get("signature"),
                    "reason": " → ".join(tried)[:300] or "o token não entrou na carteira"}
        d = dsol
        return {"ok": True, "signature": r.get("signature"), "sol_spent": max(0.0, -d if d is not None else sol0 - sol1),
                "tokens": tok1 - tok0, "lat": r.get("lat")}

    async def sell(self, mint: str, frac: float, other: bool = False) -> dict:
        """Venda REAL de `frac` da posição (100% = tudo). Mede o SOL que entrou e quanto token sobrou.
        pump.fun: PumpPortal com slippage crescente (15% → 30% → 50%); se o token graduou, PumpSwap; Jupiter só
        como último recurso (a Jupiter não negocia tokens novos ainda na curva). Guarda o motivo de cada tentativa."""
        if not self.wallet or not self.wallet.keypair:
            return {"ok": False, "reason": "carteira Solana do bot não configurada"}
        # 0.32.431: o saldo de antes é lido em paralelo com a montagem da 1ª venda e conferido antes de assinar
        bal_task = asyncio.ensure_future(self.balances(mint))
        NO_TOKEN = "sem saldo do token"

        async def gate() -> str | None:
            _s0, t0_ = await bal_task
            return None if t0_ > 0 else NO_TOKEN
        if other:
            if await gate():
                return {"ok": True, "sol_received": 0.0, "tokens_left": 0.0, "reason": NO_TOKEN}
        pct = f"{max(1, min(100, round(frac * 100)))}%"
        base_slip = float(getattr(self.cfg, "pump_real_slippage_pct", 15))
        tried, last, tries = [], {}, []                # 0.32.107: cada degrau medido (lote 11: escada parecida terminou em −84%)
        hint = (getattr(self, "pool_hint", None) or {}).pop(mint, None)
        if other:
            plan = [("jupiter", None, s_) for s_ in (3.0, 6.0, 10.0)]
        elif hint == "pump-amm":
            # 0.32.422 (FTL, 21/11): token que já graduou (BOOST etc.) vende direto na PumpSwap; a PumpPortal "auto" tentava a curva
            # (erro 6005, curva já completou) três vezes. Jupiter no fim.
            plan = [("pp", "pump-amm", base_slip), ("pp", "pump-amm", max(30.0, base_slip)), ("jupiter", None, 10.0), ("jupiter", None, 25.0)]
        else:
            plan = [("pp", "auto", base_slip), ("pp", "auto", max(30.0, base_slip)), ("pp", "auto", 50.0)]
        pool_override = None
        k = 0
        while k < len(plan):
            via, pool, slip = plan[k]
            k += 1
            t0 = time.monotonic()
            if via == "jupiter":
                raw, _dec = await self._raw_tok(mint)
                amount = raw if frac >= 0.999 else int(raw * frac)
                last = await self._jup(mint, SOL_MINT, amount, int(slip * 100))
                label = f"Jupiter {slip:.0f}%"
            else:
                pool = pool_override or pool
                body_ = {"action": "sell", "mint": mint, "amount": pct, "denominatedInSol": "false", "slippage": slip, "pool": pool}
                import inspect
                if k == 1 and "gate" in inspect.signature(self._tx).parameters:
                    last = await self._tx(body_, gate=gate)
                else:
                    if k == 1 and await gate():
                        return {"ok": True, "sol_received": 0.0, "tokens_left": 0.0, "reason": NO_TOKEN}
                    last = await self._tx(body_)
                if last.get("gate"):
                    return {"ok": True, "sol_received": 0.0, "tokens_left": 0.0, "reason": NO_TOKEN}
                label = f"PumpPortal {pool} {slip:.0f}%"
            sol0, tok0 = await bal_task
            if last.get("status") == "pendente":
                await asyncio.sleep(3)
            sol1, tok1 = await self.balances(mint)
            tried.append(f"{label}: {self.explain(last.get('reason')) or last.get('status')}")
            res_ = "entrou" if tok1 < tok0 * 0.999 else "pendente" if last.get("status") == "pendente" else "falhou"
            tries.append({"via": label, "res": res_, "ms": round((time.monotonic() - t0) * 1000), "erro": None if res_ == "entrou" else str(self.explain(last.get("reason")) or last.get("status"))[:100]})
            if tok0 <= 0 and tok1 <= 0 and last.get("status") != "pendente":
                # 0.32.459 (BAH do dono, 25/11): o token foi vendido no app da carteira. A PumpPortal respondia 400 e a Jupiter "sem
                # cotação" antes de conferir o saldo, e o robô tentava vender de novo para sempre. Duas leituras com saldo zero
                # (antes e depois da tentativa) = o token já não está na carteira.
                return {"ok": True, "sol_received": 0.0, "tokens_left": 0.0, "reason": NO_TOKEN, "attempts": tried, "tentativas": tries}
            if tok1 < tok0 * 0.999:
                d = await self._sol_change(last.get("signature"))
                return {"ok": True, "signature": last.get("signature"), "sol_received": max(0.0, d if d is not None else sol1 - sol0),
                        "tokens_left": tok1, "attempts": tried, "tentativas": tries}
            if last.get("status") == "pendente":
                # SEC-04 (auditoria 2026-10-25): a venda ainda pode entrar; montar outra venderia duas vezes
                return {"ok": False, "status": "pendente", "signature": last.get("signature"), "attempts": tried, "tentativas": tries,
                        "reason": "venda sem confirmação — não reenvia até conferir a assinatura"}
            why = str(last.get("reason") or "")
            if via == "pp" and self.other_quote(why) and not any(p_[0] == "jupiter" for p_ in plan):
                # 0.32.182 (STARMIND do dono, 04/11: +445% e 19 vendas recusadas com 6063 seguidas): subir o slippage na
                # PumpPortal não resolve esse erro (não é preço). Troca o resto da escada por PumpSwap direto e Jupiter
                # (que acha outra rota para o mesmo token) e não repete PumpPortal "auto".
                plan = plan[:k] + ([("pp", "pump-amm", max(30.0, base_slip))] if (pool or "auto") != "pump-amm" else []) + \
                    [("jupiter", None, 10.0), ("jupiter", None, 25.0)]
                continue
            if via == "pp" and ("0x1775" in why or "'Custom': 6005}" in why) and pool_override is None:
                # graduou: as próximas tentativas vão na PumpSwap (0.32.422: o código também vem em decimal, 6005) e a Jupiter
                # entra no fim
                pool_override = "pump-amm"
                if not any(p_[0] == "jupiter" for p_ in plan):
                    plan.append(("jupiter", None, 10.0))
            if via == "pp" and ("HTTP" in why or "0x1774" in why) and not any(p_[0] == "jupiter" for p_ in plan):
                plan.append(("jupiter", None, 10.0))       # PumpPortal não montou: tenta a Jupiter no fim
        return {"ok": False, "status": last.get("status"), "attempts": tried, "tentativas": tries,
                "reason": " → ".join(tried)[:400] or "o token não saiu da carteira"}
