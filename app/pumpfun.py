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

from . import txguard
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


AUTO_ORIGINS = ("explorar", "base", "elite")   # origens das compras automáticas com proteções e registro (0.31.2: elite)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def short(addr: str) -> str:
    return (addr[:4] + "…" + addr[-4:]) if addr and len(addr) > 10 else (addr or "")


class PumpMarket:
    """Dados PÚBLICOS da rede, compartilhados por todos os usuários (um conjunto só no servidor)."""

    def __init__(self, jup=None):
        self.tokens: dict[str, dict] = {}          # mint -> {symbol, name, creator, price, mcap_sol, created_t, last_t}
        self.wallets: dict[str, dict] = {}         # carteira -> {"pos": {mint: {...}}, "closed": deque, "trades": deque}
        self.creators: dict[str, float] = {}       # carteira que criou token -> quando
        self.activity: dict = {}                   # carteira -> atividade na rede (online/offline)
        self.wallet_usd: dict = {}                 # carteira do trader -> {"usd", "sol", "stable", "t"}
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
        self._real_buying: set = set()
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
        if px:
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
                            "held_s": round(now - p.get("first_t", now)), "last_t": tk.get("last_t")})
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
        man = [w for w in self.manual if w not in banned]
        # sugeridos dos Maiores traders (80%+ de acerto, 0.31.4): entram como se fossem manuais enquanto estiverem lá
        man += [w for w in (getattr(self, "elite_follow", None) or []) if w not in banned and w not in man]
        now = time.time()
        bots = {w for w, a in self.activity.items() if a.get("bot_until", 0) > now}
        bots |= set(self.paused())                       # pausados também ficam fora (entra o próximo do top)
        man = [w for w in man if w not in bots]
        self.leaderboard = [self._lb_judge(r) for r in self.leaderboard]
        lb = [r["wallet"] for r in self.leaderboard if r["eligible"] and r["wallet"] not in man
              and r["wallet"] not in banned and r["wallet"] not in bots]
        own = [r["wallet"] for r in self.ranking_cache if r["eligible"] and r["wallet"] not in man and r["wallet"] not in lb]
        # fonte: leaderboard da pump.fun (Solana Tracker); sem chave/sem dados → ranking próprio
        auto = lb + own if self.leaderboard else own
        off: dict[str, float | None] = {}
        if self._c("pump_only_online", True):
            # só entra quem está ONLINE (negociou nos últimos X min); o melhor do top que estiver online ocupa a vaga
            win = float(self._c("pump_online_min", 10)) * 60
            keep = []
            for w in auto:
                ls = self.last_seen(w)
                (keep.append(w) if ls and now - ls <= win else off.__setitem__(w, ls))
            auto = keep
        new = (man + auto)[:max(n, len(man))]
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

    def lb_key(self) -> str:
        own = self.keys.get("solanatracker_api_key") if self.keys is not None else ""
        if not own and self.lb_key_fallback is not None:
            try:
                return self.lb_key_fallback() or ""
            except Exception:
                return ""
        return own

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
                self.lb_status.update(error=msg + " · " + r.text[:120].replace(key, "***"))
                return
            lb = self._parse_lb(r.json())
            self.leaderboard = lb
            self.lb_status.update(at=now_iso(), error=None, count=len(lb), days=days)
            log.info("Pump.fun: leaderboard Solana Tracker com %d traders (%d dias)", len(lb), days)
            self.refresh_followed(force=True)
        except Exception as e:
            self.lb_status.update(error=f"{type(e).__name__}: {str(e)[:120].replace(key, '***')}")

    async def wallet_value(self, w: str) -> dict | None:
        """Saldo da carteira do trader: SOL + USDC + USDT (RPC grátis), em US$."""
        urls = []
        own = getattr(self.sol_wallet, "rpc_url", None) if self.sol_wallet is not None else None
        if own:
            urls.append(own)
        urls.append(str(self._c("pump_rpc_http", SOL_HTTP) or SOL_HTTP))
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
        RPC grátis. Carteira muito ativa passa disso: aí a idade é "pelo menos" (more=True)."""
        url = str(self._c("pump_rpc_http", SOL_HTTP) or SOL_HTTP)
        before, oldest = None, None
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
            bt = [float(x["blockTime"]) for x in res if x.get("blockTime")]
            if bt:
                oldest = min(bt + ([oldest] if oldest else []))
            before = res[-1].get("signature")
            if len(res) < 1000:
                return {"first_t": oldest, "age_days": round((time.time() - oldest) / 86400, 1) if oldest else None,
                        "more": False, "t": time.time()}
        return {"first_t": oldest, "age_days": round((time.time() - oldest) / 86400, 1) if oldest else None,
                "more": True, "t": time.time()}

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
        self.store.save_pos(p)
        self._auto_record(p, closed=False)

    def _del_pos(self, p: dict) -> None:
        self.store.del_pos(p)

    def trades(self, limit: int = 1000) -> list[dict]:
        return self.store.trades(limit)

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

    def wallet(self, real: bool = False) -> dict:
        start = 0.0 if real else float(self._c("pump_sim_balance_sol", 5.0))
        closed = [t for t in self.trades(100000) if bool(t.get("real")) == real]
        pos = [p for p in self.positions() if bool(p.get("real")) == real]
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
                "sol_usd": self.sol_usd}

    def curve(self, real: bool = False) -> list[list]:
        bal, pts = (0.0 if real else float(self._c("pump_sim_balance_sol", 5.0))), []
        for t in reversed([t for t in self.trades(5000) if bool(t.get("real")) == real]):
            bal += t["pnl_sol"]
            pts.append([t["closed_at"], round(bal, 6)])
        return pts

    # ------------------------------------------------------------------ cópia
    def _feed(self, **kw) -> None:
        kw.setdefault("at", now_iso())
        self.store.feed_add(kw)

    def _copy(self, who: str, mint: str, kind: str, sol: float, tok: float, ev: dict, before: float, t: float) -> list[str]:
        c = self.cfg
        tk = self.tokens.get(mint) or {}
        sym = tk.get("symbol") or ev.get("symbol") or short(mint)
        px = (tk.get("price") if ev.get("_delayed") and tk.get("price") else None) or self.price_of(ev) or tk.get("price")
        allpos = self.positions()
        mine = [p for p in allpos if p["mint"] == mint]
        base = {"wallet": who, "short": short(who), "mint": mint, "symbol": sym, "kind": kind, "sol": round(sol, 4),
                "mcap_sol": tk.get("mcap_sol"), "signature": ev.get("signature")}
        delay = float(self._c("pump_copy_delay_s", 0) or 0)
        if kind == "buy" and self.is_paused(who):
            pz = self.paused().get(who) or {}
            self._feed(**base, action="não copiou", reason="trader pausado" + (f" ({pz.get('reason')})" if pz.get("reason") else ""))
            return []
        if kind == "buy" and delay > 0 and not ev.get("_delayed"):
            key = (who, mint)
            if key not in self._pending:
                self._pending[key] = {"due": t + delay, "t": t, "who": who, "mint": mint, "sol": sol, "tok": tok,
                                      "ev": dict(ev), "before": before}
                self._feed(**base, action="aguardando", reason=f"copia em {delay:.0f} s se o trader continuar no token")
            return []
        if kind == "buy":
            why = None
            score, sparts = self.entry_score(who, mint, self.price_of(ev), px)
            if not getattr(c, "pump_copy_enabled", True):
                why = "cópia desligada"
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
                    why = self.chase_block(self.price_of(ev), px)
                if not why:
                    why = self.curve_block(mint)
                if not why:
                    why = self.flow_block(mint)
                if not why:
                    why = self.blacklist_block(who, mint)
                mn = self._onv("pump_score_min_on", "pump_score_min")
                if not why and mn and score < mn:
                    why = f"nota da entrada {score:.0f} abaixo do mínimo {mn:.0f}"
            if why:
                self._feed(**base, action="não copiou", reason=why)
                return []
            msgs = []
            # REAL (se ligado): compra de verdade, com o valor de "SOL por compra". Com o espelho (0.31.37) o real só
            # entra DEPOIS que o fictício abriu a posição (ver _mirror_real, no fim deste bloco)
            if self.real is not None and getattr(c, "pump_real_enabled", False) and not getattr(c, "pump_real_mirror", True):
                rwhy = None
                if not self.is_pump(mint) and not getattr(c, "pump_copy_other_real", False):
                    rwhy = "fora da pump.fun: real desligado para outras DEXs (só fictício)"
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
                    self._feed(**base, action="REAL: comprando", reason=f"enviando compra de {float(self._c('pump_real_max_sol', 0.05)):.3f} SOL")
            # FICTÍCIO (sempre roda, para comparar)
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
            if smine:
                swhy = "já tem posição copiada neste token"
            elif len([p for p in allpos if not p.get("real")]) >= int(self._c("pump_max_open", 10)):
                swhy = f"limite de {int(self._c('pump_max_open', 10))} posições abertas"
            elif self.wallet()["cash_sol"] < amt + float(self._c("pump_priority_sol", 0.0005)):
                swhy = "saldo fictício insuficiente"
            if swhy:
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
            msgs.append(f"[PUMP SIM] copiou {short(who)}: compra {sym} {amt:.3f} SOL (trader comprou {sol:.3f} SOL)")
            self._mirror_real(p, trader_sol=sol, block_t=ev.get("blockTime"))
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
        mine = [p for p in mine if p["wallet"] == who]
        if not mine:
            return []
        if frac < 0.01:                                  # venda irrelevante (<1% do que ele tinha): não mexe
            return []
        out = []
        for p in mine:
            if p.get("hold_profit"):
                continue                                  # já está segurando até ficar positivo
            if getattr(self.cfg, "pump_hold_until_profit", True):
                pxn = px or p.get("price_now") or p["price_in"]
                left_cost = p["sol_in"] * (p["tokens_left"] / p["tokens"])
                val = self._exit_value(p, pxn)
                chg = (val / left_cost - 1) * 100 if left_cost else 0.0
                if chg < float(self._c("pump_hold_min_profit_pct", 0.0)):
                    # trader saiu e NÓS estamos no prejuízo (já contando as taxas de saída): segura até ficar positivo
                    p["hold_profit"] = True
                    p["hold_since"] = now_iso()
                    p["hold_chg_in"] = round(chg, 2)
                    p["chg_pct"] = round(chg, 2)
                    self._save_pos(p)
                    self._feed(**base, action="segurando",
                               reason=f"trader saiu, mas a posição está {chg:+.1f}% depois das taxas — vende quando ficar positiva")
                    out.append(f"[PUMP {'REAL' if p.get('real') else 'SIM'}] {p['symbol']}: trader saiu no prejuízo "
                               f"({chg:+.1f}%) — segurando até ficar positivo")
                    continue
            if p.get("real"):
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

    def _fee_rates(self, mint: str) -> dict:
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
        return {"venue": venue, "venue_name": "PumpSwap" if graduated else "pump.fun (curva)",
                "portal": float(self._c("pump_portal_fee_pct", 0.5)) / 100,
                "prio": float(self._c("pump_priority_sol", 0.0005)),
                "slip": float(self._c("pump_extra_slip_pct", 3.0)) / 100}

    def _exit_value(self, p: dict, px: float) -> float:
        """Quanto entraria vendendo agora, já com TODAS as taxas de saída (plataforma, PumpPortal, rede, slippage)."""
        fr = self._fee_rates(p["mint"])
        return max(0.0, p["tokens_left"] * px * (1 - fr["slip"]) * (1 - fr["venue"] - fr["portal"]) - fr["prio"])

    @staticmethod
    def _addfee(p: dict, **kw) -> None:
        fp = p.setdefault("fee_parts", {"platform": 0.0, "portal": 0.0, "network": 0.0, "slippage": 0.0})
        for k, v in kw.items():
            fp[k] = fp.get(k, 0.0) + v

    def _sell(self, p: dict, frac: float, px: float | None, why: str, t: float) -> str | None:
        if p.get("real"):
            self._real_sell(p, frac, why)
            return f"[PUMP REAL] {p['symbol']}: vendendo {frac * 100:.0f}% ({why})"
        if not px:
            return None
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
                  "price_out": price_out, "fees_sol": round(p["fees_sol"], 6), "reason": why,
                  "fee_parts": {k: round(v, 6) for k, v in (p.get("fee_parts") or {}).items()},
                  "gross_sol": round(pnl + p["fees_sol"], 6),       # resultado antes das taxas (já com slippage)
                  "venue": p.get("venue_in"),
                  "hold_s": round(t - p.get("open_t", t)), "sells": p.get("sells", []), "real": bool(p.get("real")),
                  "mcap_in": p.get("mcap_in"), "mcap_out": (self.tokens.get(p["mint"]) or {}).get("mcap_sol")}
            tr["lag_s"] = p.get("lag_s")
            tr["best_pct"], tr["worst_pct"] = p.get("best_pct"), p.get("worst_pct")
            tr["score"] = p.get("score")
            tr["trader_px"] = p.get("trader_px") or p.get("trader_price")
            tr["manual"] = bool(p.get("manual")) or p.get("wallet") == "manual"
            if p.get("auto") is True and p.get("origem") in AUTO_ORIGINS:
                tr.update(id=p["id"], auto=True, origem=p["origem"], auto_info=copy.deepcopy(p.get("auto_info") or {}),
                          closed_t=t, closed_at=datetime.fromtimestamp(t, timezone.utc).isoformat(), exit_price=px)
            tr["pos_id"] = p["id"]                         # 0.31.38: par real × fictícia (espelho)
            self._save_trade(tr)
            self._del_pos(p)
            self._after_close(tr)
            if getattr(self.cfg, "pump_real_mirror", True):          # 0.31.37: espelho — a real sai junto
                for rp in self.positions():
                    if rp.get("real") and rp.get("sim_id") == p["id"] and not rp.get("selling"):
                        self._real_sell(rp, 1.0, f"espelho do fictício: {why}")
            return (f"[PUMP SIM] fechou {p['symbol']} copiado de {short(p['wallet'])} ({why}) → "
                    f"{pnl:+.4f} SOL ({tr['pnl_pct']:+.1f}%)")
        self._save_pos(p)
        return f"[PUMP SIM] {p['symbol']}: vendeu {frac * 100:.0f}% ({why}) → {got:.4f} SOL"

    def _check_stops(self, mint: str, t: float) -> list[str]:
        out = []
        px = (self.tokens.get(mint) or {}).get("price")
        stop, tp = float(self._c("pump_stop_pct", 40)), float(self._c("pump_tp_pct", 0))
        if px and self.ghosts.open:
            self.ghosts.on_price(mint, px, t)
        if px and self.ghosts_auto.open:
            self.ghosts_auto.on_price(mint, px, t)
        for p in [p for p in self.positions() if p["mint"] == mint]:
            if not px or p.get("selling"):
                continue
            p["price_now"] = px
            left_cost = p["sol_in"] * (p["tokens_left"] / p["tokens"])
            val = self._exit_value(p, px)
            chg = (val / left_cost - 1) * 100 if left_cost else 0
            p["chg_pct"] = round(chg, 2)
            # pós-trade (0.18.0): melhor e pior momento da posição, para ver quanto ficou na mesa
            p["best_pct"] = round(max(chg, p.get("best_pct", chg)), 2)
            p["worst_pct"] = round(min(chg, p.get("worst_pct", chg)), 2)
            own_auto = p.get("auto") is True and p.get("origem") in AUTO_ORIGINS
            max_hold = self._auto_num(p.get("max_hold_s"))
            if max_hold is not None and t - p.get("open_t", t) >= max_hold:
                out.append(self._sell(p, 1.0, px, f"tempo máximo ({max_hold / 60:g} min)", t))
                continue
            # STOP MÓVEL: liga quando o líquido (após taxas) passa de X%; depois sai se cair Y pontos do pico
            trail_on = p["trail_on"] if "trail_on" in p else getattr(self.cfg, "pump_trail_enabled", True)
            t_start = float(p.get("trail_start") or self._c("pump_trail_start_pct", 20))
            t_dist = float(p.get("trail_dist") or self._c("pump_trail_dist_pct", 10))
            stop = float(p.get("stop_pct") or self._c("pump_stop_pct", 40))      # 0.26.0: compra do botão tem as suas
            tp = float(p["tp_pct"]) if p.get("tp_pct") is not None else float(self._c("pump_tp_pct", 0))
            if trail_on and (p.get("trail_peak") is not None or chg >= t_start):
                if p.get("trail_peak") is None:
                    p["trail_since"] = now_iso()
                p["trail_peak"] = round(max(chg, p.get("trail_peak") or chg), 2)
                p["trail_exit"] = round(max(p["trail_peak"] - t_dist, float(self._c("pump_trail_min_lock_pct", 2))), 2)
            tp1 = float(p["tp1_pct"]) if p.get("tp1_pct") is not None else self._onv("pump_tp1_on", "pump_tp1_pct")
            prog = None
            cx = self._onv("pump_curve_exit_on", "pump_curve_exit_pct")
            if cx and self.is_pump(mint) and not self.graduated(mint):
                prog = self.curve_progress((self.tokens.get(mint) or {}).get("mcap_sol"))
            if cx and prog is not None and prog >= cx:
                out.append(self._sell(p, 1.0, px, f"saiu antes da graduação (curva em {prog:.0f}%, {chg:+.1f}% líquido)", t))
                continue
            smart = self.smart_exit(p, t, force=p.get("smart") is True)
            if smart:
                out.append(self._sell(p, 1.0, px, f"{smart} ({chg:+.1f}% líquido)", t))
                continue
            # Saltos diretos ao alvo/Boost encerram a automática inteira, sem começar por uma parcial.
            if own_auto and p.get("boost_tp") and chg >= float(p["boost_tp"]) and self.boost_info(mint).get("active"):
                out.append(self._sell(p, 1.0, px, f"boost ON: alvo +{float(p['boost_tp']):.0f}% ({chg:+.1f}% líquido)", t))
                continue
            if own_auto and tp and chg >= tp:
                out.append(self._sell(p, 1.0, px, f"alvo (+{tp:.0f}%)", t))
                continue
            if tp1 and not p.get("tp1_done") and chg >= tp1 and p["tokens_left"] > p["tokens"] * 0.05:
                p["tp1_done"] = True
                frac = float(p["tp1_frac"]) if p.get("tp1_frac") is not None else float(self._c("pump_tp1_frac_pct", 50))
                frac /= 100
                out.append(self._sell(p, frac, px, f"venda em partes: realizou {frac * 100:.0f}% em {chg:+.1f}% líquido", t))
                continue
            if trail_on and p.get("trail_peak") is not None and chg <= p["trail_exit"]:
                out.append(self._sell(p, 1.0, px, f"stop móvel (pico {p['trail_peak']:+.1f}% → saiu em {chg:+.1f}% líquido)", t))
            elif p.get("hold_profit") and chg > float(self._c("pump_hold_min_profit_pct", 0.0)):
                out.append(self._sell(p, 1.0, px, f"segurou até ficar positivo ({chg:+.1f}% líquido)", t))
            elif chg <= -stop:
                out.append(self._sell(p, 1.0, px, f"stop de perda (−{stop:.0f}%)", t))
            elif p.get("boost_tp") and chg >= float(p["boost_tp"]) and self.boost_info(mint).get("active"):
                out.append(self._sell(p, 1.0, px, f"boost ON: alvo +{float(p['boost_tp']):.0f}% ({chg:+.1f}% líquido)", t))
            elif tp and chg >= tp:
                out.append(self._sell(p, 1.0, px, f"alvo (+{tp:.0f}%)", t))
            else:
                self._save_pos(p)
        return [m for m in out if m]

    def check_timeouts(self, t: float | None = None) -> list[str]:
        t = t or time.time()
        mx = float(self._c("pump_max_hold_h", 6)) * 3600
        out = []
        if self.ghosts.open:
            self.ghosts.on_time(t)
        if self.ghosts_auto.open:
            self.ghosts_auto.on_time(t)
        for p in self.positions():
            hold = self._auto_num(p.get("max_hold_s"))
            hold = hold if hold is not None else mx
            if t - p.get("open_t", t) >= hold and not p.get("selling"):
                out.append(self._sell(p, 1.0, (self.tokens.get(p["mint"]) or {}).get("price") or p.get("price_now"),
                                      f"tempo máximo ({hold / 60:g} min)" if p.get("max_hold_s") is not None else f"tempo máximo ({hold / 3600:.0f} h)", t))
        return [m for m in out if m]

    def close_position(self, pid) -> dict:
        for p in self.positions():
            if str(p["id"]) == str(pid):
                px = (self.tokens.get(p["mint"]) or {}).get("price") or p.get("price_now")
                msg = self._sell(p, 1.0, px, "fechada por você", time.time())
                return {"ok": True, "msg": msg}
        return {"error": "posição não encontrada"}

    def reset_sim(self) -> dict:
        if (any(not p.get("real") and p.get("auto") is True and p.get("origem") in AUTO_ORIGINS
                for p in self.positions())
                or any(not row.get("real") and not row.get("saida_em") for row in self.auto_rows.values())):
            return {"error": "feche as posições automáticas simuladas antes de zerar a carteira fictícia"}
        self.store.reset_sim()
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

    async def _get_tx(self, sig: str) -> dict | None:
        urls = []
        own = getattr(self.sol_wallet, "rpc_url", None) if self.sol_wallet is not None else None
        if own and "api.mainnet-beta.solana.com" not in own:
            urls.append(own)                       # RPC da carteira (ex.: Helius) primeiro: o público dá 429 rápido
        urls.append(str(self._c("pump_rpc_http", SOL_HTTP) or SOL_HTTP))
        body = {"jsonrpc": "2.0", "id": 1, "method": "getTransaction",
                "params": [sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0, "commitment": "confirmed"}]}
        for attempt in range(4):
            for u in urls:
                try:
                    r = await self.http.post(u, json=body, timeout=10)
                    if r.status_code == 429:
                        continue
                    res = (r.json() or {}).get("result")
                    if res:
                        return res
                except Exception:
                    continue
            await asyncio.sleep(1.0 + attempt)
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
        mn = self._onv("pump_curve_speed_on", "pump_min_curve_speed")
        tk = self.tokens.get(mint) or {}
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
        tk = self.tokens.get(p["mint"]) or {}
        opened = float(p.get("open_t") or 0)
        if (force or getattr(self.cfg, "pump_exit_dev_sell", False)) and tk.get("dev_sold_t") and tk["dev_sold_t"] >= opened:
            return "dev vendeu"
        sm = float(self._c("pump_exit_stale_min", 45)) if getattr(self.cfg, "pump_exit_stale_on", False) else 0
        if sm and t and t - opened >= sm * 60 and p.get("chg_pct") is not None \
                and abs(float(p["chg_pct"])) <= float(self._c("pump_exit_stale_band", 5)):
            return f"parado há {(t - opened) / 60:.0f} min"
        if ((p.get("grad_exit", True) if force else getattr(self.cfg, "pump_exit_migrate", False))
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
        return list(rows.values())

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
        notices = self.__dict__.setdefault("_auto_notices", {})
        key = (origem, reason)
        if t - notices.get(key, -1e30) < 60:
            return
        notices[key] = t
        self._auto_notices = {k: at for k, at in notices.items() if t - at < 3600}
        msg = "compra automática pausada: " + reason
        self._feed(wallet="manual", short="automático", mint=mint, symbol=(self.tokens.get(mint) or {}).get("symbol"),
                   kind="buy", action="compra automática pausada", reason=reason, origem=origem)
        self._emit("[PUMP SIM] " + msg)

    def learned(self, origem: str, t: float | None = None) -> dict:
        """Aprender com os erros (0.31.12, app/autolearn.py): faixas das compras automáticas fechadas; avisa quando uma
        faixa nova passa a ser bloqueada. Recalculado do histórico a cada 60 s."""
        from .autolearn import study
        t = time.time() if t is None else t
        cache = self.__dict__.setdefault("_learned", {})
        hit = cache.get(origem)
        if hit and t - hit[0] < 60:
            return hit[1]
        st = study(self.trades(100000), origem)
        before = {(x["feature"], x["faixa"]) for x in (hit[1]["bloqueios"] if hit else [])}
        for x in st["bloqueios"]:
            if hit and (x["feature"], x["faixa"]) not in before:
                self._emit(f"Aprendi com os erros ({origem}): não entro mais com {x['nome']} {x['faixa']} — perdeu em {x['n']} "
                           f"operações (acerto {x['acerto'] * 100:.0f}%, média {x['media_pct']:+.0f}%)")
        cache[origem] = (t, st)
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
        if pred.get("verdict") != "chance alta":
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
        if getattr(self.cfg, "pump_ar_learn", True):
            from .autolearn import blocked_reason
            why = blocked_reason(self.learned("explorar"), row)
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
            result = self.manual_buy(mint, t, auto="automático: chance alta", origem="explorar", info=info)
            self._funnel_note(row, None if result.get("auto_id") else (result.get("error") or result.get("sim") or "não entrou"), t)
            if result.get("auto_id"):
                out.append(mint)
        return out

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
        if g.get("px0") is None:
            g["px0"] = (self.tokens.get(mint) or {}).get("price")
        if g.get("why") is None and g.get("t") and why is not None and g.get("entrou"):
            pass                                           # já entrou: não volta a contar como barrado
        else:
            g["why"], g["entrou"] = why, (why is None) or g.get("entrou", False)
        g["t"] = t
        fn[mint] = g
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
        motivos, barr = {}, []
        for mint, g in fn.items():
            if g.get("entrou"):
                continue
            key = re.sub(r"[-+]?\d+(?:[.,]\d+)?", "#", str(g.get("why") or "outro"))[:90]
            motivos[key] = motivos.get(key, 0) + 1
            px, px0 = (self.tokens.get(mint) or {}).get("price"), g.get("px0")
            if px and px0:
                barr.append({"mint": mint, "symbol": g.get("symbol"), "chg_pct": round((px / px0 - 1) * 100, 1), "motivo": g.get("why")})
        barr.sort(key=lambda b: -b["chg_pct"])
        alta = [b for b in barr if b["chg_pct"] >= 50]
        return {"vistos": len(fn), "chance_alta": sum(1 for g in fn.values() if g.get("chance") == "chance alta"),
                "entrou": sum(1 for g in fn.values() if g.get("entrou")), "barrados": len(fn) - sum(1 for g in fn.values() if g.get("entrou")),
                "motivos": sorted(({"motivo": k, "n": v} for k, v in motivos.items()), key=lambda m: -m["n"])[:12],
                "barrados_com_preco": len(barr), "subiram_50": len(alta), "cairam_30": sum(1 for b in barr if b["chg_pct"] <= -30),
                "top_subiram": alta[:8]}

    def manual_buy(self, mint: str, t: float | None = None, auto: str = "", origem: str = "", info: dict | None = None) -> dict:
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
        rules = self.auto_rules() if own_auto else self.manual_rules()
        fr = self._fee_rates(mint)
        sim_pos = None
        if any(p["mint"] == mint and not p.get("real") for p in allpos):
            out["sim"] = "já tem posição fictícia neste token"
        elif len([p for p in allpos if not p.get("real")]) >= int(self._c("pump_max_open", 10)):
            out["sim"] = f"limite de {int(self._c('pump_max_open', 10))} posições abertas"
        elif self.wallet()["cash_sol"] < amt + fr["prio"]:
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
        if own_auto and not out.get("auto_id"):
            return out                              # uma falha fictícia não dispara compra real automática
        mirror = getattr(self.cfg, "pump_real_mirror", True)
        if self.real is not None and getattr(self.cfg, "pump_real_enabled", False) and (not auto or mirror or getattr(self.cfg, "pump_auto_real", False)):
            if any(p["mint"] == mint and p.get("real") for p in allpos) or mint in self._real_buying:
                out["real"] = "já tem posição REAL neste token"
            elif len([p for p in allpos if p.get("real")]) + len(self._real_buying) >= int(self._c("pump_real_max_open", 5)):
                out["real"] = f"limite de {int(self._c('pump_real_max_open', 5))} posições reais"
            elif own_auto and not mirror and (guard := self.auto_guard(t=t)):
                out["real"] = guard
                self._auto_blocked(guard, mint, origem, t)
            else:
                self._real_buying.add(mint)
                if own_auto:
                    self._auto_pending[mint] = t
                self._rq_put(("buy", {"wallet": "manual", "mint": mint, "symbol": sym, "trader_sol": 0.0,
                                      "trader_price": px, "mcap_in": tk.get("mcap_sol"), "t": t, "block_t": t,
                                      "sim_id": (sim_pos or {}).get("id") if mirror else None,
                                      "pos_cfg": {**rules, "manual": True,
                                                  **({"auto": True, "origem": origem, "auto_info": copy.deepcopy(p["auto_info"])} if own_auto else {})}}))
                self._feed(**base, action="REAL: comprando", reason="compra manual enviada para a fila real")
                out["real"] = f"enviando compra real de até {float(self._c('pump_real_max_sol', 0.05)):.3f} SOL"
        return out

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
            if len(recent) >= int(self._c("pump_auto_max_h", 5)):
                break
            mint, pred = x["mint"], x.get("pred") or {}
            if mint in done or pred.get("verdict") in ("lixo", "suspeito") or x.get("age_min", 99) > float(self._c("pump_auto_max_age", 45)):
                continue
            if self.auto_safety(mint, x.get("age_min")):
                continue                                    # 0.31.0: idade mínima, carteiras novas, trader bom
            why = []
            if getattr(self.cfg, "pump_auto_boost", True) and (x.get("boost") or {}).get("active"):
                why.append("Boost ON")
            if getattr(self.cfg, "pump_auto_chance", False) and pred.get("verdict") == "chance alta":
                why.append(f"chance alta ({pred.get('chance') or 0:.0f}%)")
            if not why:
                continue
            done[mint] = t
            r = self.manual_buy(mint, t, auto="automático: " + " + ".join(why))
            if r.get("error") or (r.get("sim") or "").startswith(("já tem", "limite", "saldo")):
                if r.get("error"):
                    done.pop(mint, None)                    # sem preço ainda: tenta de novo na próxima volta
                continue
            recent.append(t)
            out.append(mint)
        return out

    def elite_auto(self, s: dict, t: float | None = None) -> dict | None:
        """Maiores traders (0.31.2): compra sozinho no sinal, com as proteções das automáticas (pump_ar_*)."""
        if not getattr(self.cfg, "pump_el_auto_on", False) or getattr(self, "role", "admin") != "admin":
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

    def manual_rules(self) -> dict:
        """Stop, alvo e stop móvel que o botão Comprar grava na posição (configurados na Base da pump.fun)."""
        return {"stop_pct": float(self._c("pump_manual_stop_pct", 30)),
                "tp_pct": float(self._c("pump_manual_tp_pct", 100)),
                "trail_on": bool(getattr(self.cfg, "pump_manual_trail_on", True)),
                "trail_start": float(self._c("pump_manual_trail_start", 30)),
                "trail_dist": float(self._c("pump_manual_trail_dist", 15)),
                "boost_tp": float(self._c("pump_manual_boost_tp", 80)) if getattr(self.cfg, "pump_manual_boost_on", True) else None}

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
        urls = []
        own = getattr(self.sol_wallet, "rpc_url", None) if self.sol_wallet is not None else None
        if own:
            urls.append(own)
        urls.append(str(self._c("pump_rpc_http", SOL_HTTP) or SOL_HTTP))
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
            for p in js if isinstance(js, list) else []:
                base = (p.get("baseToken") or {}).get("address")
                if base not in chunk:
                    continue
                v = vols.setdefault(base, {"m5": 0.0, "h1": 0.0, "h6": 0.0, "h24": 0.0, "buys_h1": 0, "sells_h1": 0,
                                           "buys_m5": 0, "sells_m5": 0, "buys_h24": 0, "sells_h24": 0})
                for k_ in ("m5", "h1", "h6", "h24"):
                    v[k_] += float((p.get("volume") or {}).get(k_) or 0)
                for w_ in ("m5", "h1", "h24"):                 # compras × vendas por janela (ficha e pressão)
                    tx_ = (p.get("txns") or {}).get(w_) or {}
                    v["buys_" + w_] += int(tx_.get("buys") or 0)
                    v["sells_" + w_] += int(tx_.get("sells") or 0)
                dx = self.tokens.setdefault(base, {"created_t": time.time()}).setdefault("dexes", [])
                if p.get("dexId") and p["dexId"] not in dx:
                    dx.append(p["dexId"])
                if p.get("dexId") == "pumpswap" and p.get("pairAddress"):
                    self.tokens[base]["pumpswap_pool"] = p["pairAddress"]
                ba = int(((p.get("boosts") or {}).get("active")) or 0)     # 0.24.0: boost ativo no par
                if ba:
                    self.tokens[base]["boost_active"] = max(ba, int(self.tokens[base].get("boost_active") or 0))
                liq = float((p.get("liquidity") or {}).get("usd") or 0)
                if base in best and best[base][0] >= liq:
                    continue
                best[base] = (liq, p)
            now = time.time()
            for m, (liq, p) in best.items():
                q = (p.get("quoteToken") or {}).get("address")
                pn, pu = float(p.get("priceNative") or 0), float(p.get("priceUsd") or 0)
                px = pn if q == SOL_MINT and pn > 0 else (pu / sol_usd if sol_usd and pu else None)
                tk = self.tokens.setdefault(m, {"created_t": now})
                tk["liq_usd"] = liq
                tk["main_dex"] = p.get("dexId")
                tk["chg"] = {k_: float(v_) for k_, v_ in (p.get("priceChange") or {}).items()
                             if k_ in ("m5", "h1", "h6", "h24") and isinstance(v_, (int, float))}
                if m in vols:
                    tk["vol"] = {k_: round(v_, 2) if isinstance(v_, float) else v_ for k_, v_ in vols[m].items()}
                    tk["vol_t"] = now
                if px and (set_price or not tk.get("price") or now - (tk.get("last_t") or 0) > 30):
                    tk["price"] = px
                    tk["last_t"] = now
                sym = (p.get("baseToken") or {}).get("symbol")
                if sym:
                    tk["symbol"] = sym
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

    async def _pumpswap_prices(self, mints: list[str], public_first: bool = False, qty: dict | None = None) -> list[str]:
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
            dec = (self.tokens.get(m) or {}).get("decimals") or 6
            if q_tok <= 0:
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
            tk["price"] = out / q_tok / max(1e-9, 1 - fee)        # tira a taxa da pool (o cálculo de saída aplica de novo)
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
                        "atraso_s": r.get("lag_s"), "motivo_real": r.get("reason"), "motivo_sim": s.get("reason") if s else None})
        out.sort(key=lambda x: str(x.get("fechou") or ""), reverse=True)
        return out[:limit]

    MISS_TIPS = (("limite de", "Aumente \"Posições reais ao mesmo tempo\" na Execução real, ou confira se há posição real antiga presa aberta."),
                 ("perda do dia", "A real parou no limite \"Parar no dia se perder\"; volta sozinha no dia seguinte (UTC)."),
                 ("já tem posição real", "A real já estava nesse token (de outra cópia); normal."),
                 ("desligad", "A execução real ou a entrada automática estava desligada nessa hora."),
                 ("saldo", "Falta SOL na carteira do bot para o \"SOL por compra\" + taxas."),
                 ("subiu", "O preço fugiu antes de a real comprar (corrigido na 0.31.43 para o espelho)."),
                 ("erro", "Falha ao enviar: confira o RPC e o saldo; veja Administração → Logs."),
                 ("falh", "A rede recusou ou não confirmou; confira saldo e slippage da real."),
                 ("recusad", "A rede recusou ou não confirmou; confira saldo e slippage da real."))

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
            g = por.setdefault(k, {"motivo": k, "n": 0, "sim_sol": 0.0, "dica": tip})
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
        mint, allpos = p["mint"], self.positions()
        base = {"wallet": p["wallet"], "short": short(p["wallet"]), "mint": mint, "symbol": p.get("symbol"), "kind": "buy"}
        why = None
        if any(x["mint"] == mint and x.get("real") for x in allpos) or mint in self._real_buying:
            why = "já tem posição REAL neste token"
        elif len([x for x in allpos if x.get("real")]) + len(self._real_buying) >= int(self._c("pump_real_max_open", 5)):
            why = f"limite de {int(self._c('pump_real_max_open', 5))} posições reais (regra da carteira real)"
        if why:
            self._feed(**base, action="REAL não copiou", reason=why, sim_id=p["id"])
            return why
        self._real_buying.add(mint)
        self._rq_put(("buy", {"wallet": p["wallet"], "mint": mint, "symbol": p.get("symbol"), "trader_sol": trader_sol,
                              "trader_price": p.get("trader_price") or p.get("price_now"), "mcap_in": p.get("mcap_in"),
                              "t": p.get("open_t") or time.time(), "block_t": block_t or p.get("open_t"), "sim_id": p["id"],
                              **({"pos_cfg": pos_cfg} if pos_cfg else {})}))
        self._feed(**base, action="REAL: comprando",
                   reason=f"espelho do fictício · até {float(self._c('pump_real_max_sol', 0.05)):.3f} SOL (regra da carteira real)")
        return None

    def _rq_put(self, item) -> None:
        if self._rq is None:
            self._rq = asyncio.Queue()
        self._rq.put_nowait(item)

    def _real_sell(self, p: dict, frac: float, why: str) -> None:
        if p.get("selling"):
            return
        p["selling"] = True
        self._save_pos(p)
        self._rq_put(("sell", {"id": p["id"], "frac": frac, "why": why}))

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
        async with lock, sem:
            try:
                if kind == "buy":
                    await self._real_buy(it)
                else:
                    await self._real_do_sell(it)
            except Exception as e:
                self._emit(f"[PUMP REAL] {kind} {it.get('symbol') or it.get('id')}: erro {type(e).__name__}: {str(e)[:120]}")
                if kind == "buy":
                    self._real_buying.discard(it.get("mint"))
                    self._auto_pending.pop(it.get("mint"), None)
                else:
                    self._unmark_selling(it.get("id"))

    def _unmark_selling(self, pid) -> None:
        for p in self.positions():
            if p["id"] == pid and p.get("selling"):
                p["selling"] = False
                self._save_pos(p)

    async def _real_buy(self, it: dict) -> None:
        mint, sym = it["mint"], it["symbol"]
        # 0.31.43 (sugestão do Bruxo + aprendizagem do bot: "a real não replica a fictícia"): toda desistência da compra
        # real fica no feed com o motivo e o par fictício (sim_id). A tela Real × fictícia junta isso e diz o que ajustar.
        mirrored = getattr(self.cfg, "pump_real_mirror", True) and it.get("sim_id") is not None

        def miss(why: str, action: str = "REAL não copiou") -> None:
            self._feed(wallet=it["wallet"], short=short(it["wallet"]), mint=mint, symbol=sym, kind="buy",
                       action=action, reason=why, sim_id=it.get("sim_id"))
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
            if lim and self.real.today_loss(self.trades(2000)) >= lim:
                miss(f"perda do dia chegou a {lim} SOL")
                return
            mult, mwhy = self.trust_mult(it["wallet"])
            amt = float(self._c("pump_real_max_sol", 0.05)) * min(1.0, mult)
            # a compra real sai da fila depois: confere de novo se o preço já não fugiu da entrada do trader.
            # 0.31.43: no ESPELHO não — a fictícia já passou pelos filtros e os tokens que mais sobem (ex.: R1R2L1R2,
            # +150% em 12 s) eram justamente os barrados aqui; a proteção da real é a slippage da carteira real.
            chase = None if mirrored else self.chase_block(it.get("trader_price"), (self.tokens.get(mint) or {}).get("price"))
            if chase:
                miss(chase)
                return
            try:
                res = await self.real.buy(mint, amt, other=not self.is_pump(mint))
            except Exception as e:
                miss(f"erro ao enviar a compra: {type(e).__name__}: {str(e)[:120]}", "REAL falhou")
                raise
            if not res.get("ok"):
                miss(res.get("reason") or res.get("status") or "a compra não confirmou", "REAL falhou")
                self._emit(f"[PUMP REAL] compra {sym} NÃO feita: {res.get('reason') or res.get('status')}")
                return
            fr = self._fee_rates(mint)
            spent, toks = res["sol_spent"], res["tokens"]
            p = {"opened_at": now_iso(), "open_t": time.time(), "wallet": it["wallet"], "mint": mint, "symbol": sym,
                 "sol_in": round(spent, 9), "tokens": toks, "tokens_left": toks, "price_in": spent / toks,
                 "price_now": it.get("trader_price"), "trader_price": it.get("trader_price"),
                 "trader_sol": it.get("trader_sol"), "proceeds": 0.0, "mcap_in": it.get("mcap_in"), "real": True,
                 "venue_in": fr["venue_name"], "signature": res.get("signature"), "fees_sol": 0.0,
                 "lag_s": round(max(0.0, time.time() - float(it.get("block_t") or it.get("t") or time.time())), 1)}
            self._addfee(p, platform=amt * fr["venue"], portal=amt * fr["portal"],
                         network=max(0.0, spent - amt * (1 + fr["venue"] + fr["portal"])))
            p["fees_sol"] = sum((p.get("fee_parts") or {}).values())
            p.update(it.get("pos_cfg") or {})              # compra do botão: stop/alvo próprios (0.26.0)
            if own_auto:
                p["opened_at"] = datetime.fromtimestamp(p["open_t"], timezone.utc).isoformat()
            if it.get("sim_id") is not None:
                p["sim_id"] = it["sim_id"]                 # 0.31.37: par na carteira fictícia (espelho)
            self._save_pos(p)
            if it.get("sim_id") is not None and not any(x["id"] == it["sim_id"] for x in self.positions()):
                self._real_sell(p, 1.0, "espelho: o fictício já fechou enquanto a compra real saía")
            self._feed(wallet=it["wallet"], short=short(it["wallet"]), mint=mint, symbol=sym, kind="buy",
                       action="REAL comprou", reason=f"gastou {spent:.4f} SOL · recebeu {toks:,.0f} tokens",
                       signature=res.get("signature"))
            self._emit(f"[PUMP REAL] comprou {sym}: {spent:.4f} SOL (copiando {short(it['wallet'])})")
        finally:
            self._real_buying.discard(mint)
            self._auto_pending.pop(mint, None)

    async def _real_do_sell(self, it: dict) -> None:
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
                self._save_pos(p)
                self._emit(f"[PUMP REAL] venda {p['symbol']} adiada: a anterior ainda não confirmou ({why})")
                return
            p.pop("sell_pending", None)
            if st == "confirmada":
                self._emit(f"[PUMP REAL] a venda pendente de {p['symbol']} confirmou depois; o saldo já reflete isso")
        res = await self.real.sell(p["mint"], frac, other=not self.is_pump(p["mint"]))
        if res.get("status") == "pendente" and res.get("signature"):
            p["sell_pending"] = {"signature": res["signature"], "at": time.time()}
        if not res.get("ok"):
            p["selling"] = False
            p["sell_error"] = res.get("reason") or res.get("status")
            self._save_pos(p)
            self._emit(f"[PUMP REAL] venda {p['symbol']} NÃO feita ({why}): {p['sell_error']} — tenta de novo no próximo sinal")
            return
        got, left = res["sol_received"], res["tokens_left"]
        fr = self._fee_rates(p["mint"])
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
            tr["trader_px"] = p.get("trader_px") or p.get("trader_price")
            tr["manual"] = bool(p.get("manual")) or p.get("wallet") == "manual"
            tr["sim_id"] = p.get("sim_id")                 # 0.31.38: par na fictícia (espelho)
            if p.get("auto") is True and p.get("origem") in AUTO_ORIGINS:
                closed = time.time()
                tr.update(id=p["id"], auto=True, origem=p["origem"], auto_info=copy.deepcopy(p.get("auto_info") or {}),
                          closed_t=closed, closed_at=datetime.fromtimestamp(closed, timezone.utc).isoformat(),
                          exit_price=p.get("price_now"))
            self._save_trade(tr)
            self._del_pos(p)
            self._after_close(tr)
            self._emit(f"[PUMP REAL] fechou {p['symbol']} ({why}) → {pnl:+.4f} SOL ({tr['pnl_pct']:+.1f}%) líquido")
        else:
            self._save_pos(p)
            self._emit(f"[PUMP REAL] {p['symbol']}: vendeu {frac * 100:.0f}% ({why}) → {got:.4f} SOL")

    # ------------------------------------------------------------------ painel
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
            followed.append({**r, "manual": w in man, "copied": copied.get(w), "lb": lbr,
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
            tkp = self.tokens.get(p["mint"]) or {}
            p["vol"] = tkp.get("vol")
            p["mcap_now"] = tkp.get("mcap_sol")
            p["liq_usd"] = tkp.get("liq_usd")
        return {"enabled": getattr(c, "pump_enabled", True), "copy_enabled": getattr(c, "pump_copy_enabled", True),
                "rpc": dict(self.rpc_status), "paid_stream": self._paid(),
                "status": {**self.status, "followed": len(self.followed), "tracked_tokens": len(self.sub_tokens),
                           "wallets_seen": len(self.wallets)},
                "paused": [{"wallet": w, "short": short(w), **v,
                            "act": self.activity_view(w), "lb": lbmap.get(w), "copied": copied.get(w)}
                           for w, v in self.paused().items()],
                "leaderboard": [r | {"followed": r["wallet"] in fol, "manual": r["wallet"] in man,
                                     "paused": r["wallet"] in self.paused(),
                                     "act": self.activity_view(r["wallet"]),
                                     "online": self.is_online(r["wallet"])} for r in self.leaderboard],
                "lb_status": {**self.lb_status, "key_set": bool(self.lb_key()),
                              "source": "leaderboard" if self.leaderboard else "ranking próprio"},
                "followed": followed, "ranking": [r | {"followed": r["wallet"] in fol} for r in rk[:50]],
                "manual": self.manual, "banned": self.banned,
                "positions": pos, "trades": self.trades(300), "feed": list(self.feed)[:150],
                "live": [e for e in list(self.live) if e["wallet"] in fol][:200], "trader_pos": self.trader_positions(),
                "wallet": self.wallet(), "real_wallet": self.wallet(real=True), "curve": self.curve(),
                "real_curve": self.curve(real=True), "pending": [{"wallet": k[0], "mint": k[1], "in_s": round(v["due"] - time.time())}
                                                          for k, v in self._pending.items()], "real_pending": {"buying": sorted(self._real_buying),
                                                                     "queue": self._rq.qsize() if self._rq else 0},
                "sol_usd": self.sol_usd,
                "cfg": {**{k: getattr(c, k, None) for k in USER_KEYS},
                        "pump_real_enabled": bool(getattr(c, "pump_real_enabled", False))},
                "real": {"enabled": bool(getattr(c, "pump_real_enabled", False)),
                         "wallet_configured": bool(self.sol_wallet and getattr(self.sol_wallet, "keypair", None)),
                         "api_key_set": bool(self.real and self.real.api_key()),
                         "address": getattr(self.sol_wallet, "address", None) if self.sol_wallet else None}}


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

    async def _rpc(self, method: str, params: list):
        r = await self.http.post(await self.wallet.safe_rpc_url(),
                                 json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=15)
        js = r.json()
        if "error" in js:
            raise RuntimeError(str(js["error"])[:160])
        return js["result"]

    async def balances(self, mint: str) -> tuple[float, float]:
        """(SOL, tokens do mint) da carteira do bot, direto da blockchain."""
        sol = (await self._rpc("getBalance", [self.wallet.address, {"commitment": "confirmed"}]))["value"] / 1e9
        tok = 0.0
        res = await self._rpc("getTokenAccountsByOwner", [self.wallet.address, {"mint": mint},
                                                          {"encoding": "jsonParsed", "commitment": "confirmed"}])
        for a in (res or {}).get("value") or []:
            ta = a["account"]["data"]["parsed"]["info"]["tokenAmount"]
            tok += float(ta.get("uiAmountString") or ta.get("uiAmount") or 0)
        return sol, tok

    async def _send_confirm(self, raw_b64: str) -> tuple[str | None, str, str | None]:
        try:
            sig = await self._rpc("sendTransaction", [raw_b64, {"encoding": "base64", "skipPreflight": False,
                                                                "preflightCommitment": "processed", "maxRetries": 3}])
        except Exception as e:
            return None, "recusada", str(e)[:160]
        for i in range(240):                     # 0.31.46: confere a cada 0,25 s (antes 0,75 s); reenvia a cada ~1 s
            await asyncio.sleep(0.25)
            if i % 4 == 3:
                try:
                    await self._rpc("sendTransaction", [raw_b64, {"encoding": "base64", "skipPreflight": True, "maxRetries": 0}])
                except Exception:
                    pass
            try:
                st = (await self._rpc("getSignatureStatuses", [[sig]]))["value"][0]
            except Exception:
                continue
            if st and st.get("err"):
                return sig, "falhou", str(st["err"])[:120]
            if st and st.get("confirmationStatus") in ("confirmed", "finalized"):
                return sig, "confirmada", None
        return sig, "pendente", "sem confirmação em 60 s"

    async def _tx(self, body: dict) -> dict:
        if body.get("action") == "buy" and not getattr(self.cfg, "pump_real_enabled", False):
            return {"status": "não executou", "reason": "execução real desligada"}
        if not self.wallet or not self.wallet.keypair:
            return {"status": "não executou", "reason": "carteira Solana do bot não configurada"}
        body = {"publicKey": self.wallet.address, "slippage": float(getattr(self.cfg, "pump_real_slippage_pct", 15)),
                "priorityFee": float(getattr(self.cfg, "pump_priority_sol", 0.0005)), "pool": "auto", **body}
        body = {k: (str(v) if not isinstance(v, str) else v) for k, v in body.items()}
        r = await self.http.post(TRADE_LOCAL_URL, data=body, timeout=15)
        if r.status_code != 200:
            return {"status": "falhou", "reason": f"PumpPortal HTTP {r.status_code}: {r.text[:120]}"}
        from solders.transaction import VersionedTransaction
        try:
            tx = VersionedTransaction.from_bytes(r.content)
            # SEC-01 (auditoria 2026-10-25): só assina se a transação fizer o que foi pedido
            txguard.check(tx.message, self.wallet.address, mint=body.get("mint"), **self._limits(body))
        except Exception as e:
            log.warning("PumpPortal: transação recusada antes de assinar (%s)", str(e)[:160])
            return {"status": "recusada", "reason": f"transação recusada pela verificação: {str(e)[:120]}"}
        signed = VersionedTransaction(tx.message, [self.wallet.keypair])
        sig, st, err = await self._send_confirm(base64.b64encode(bytes(signed)).decode())
        if st == "pendente":                     # SEC-04: espera confirmar ou vencer antes de qualquer nova tentativa
            st, err = await txguard.reconcile(self._rpc, sig, str(tx.message.recent_blockhash))
        return {"status": st, "signature": sig, "reason": err, "ok": st == "confirmada"}

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
                   "0x1773": "preço caiu além do slippage (SOL recebido baixo)", "0x1774": "token não bate com a curva",
                   "0x1775": "curva já completou — token graduou para a PumpSwap",
                   "0x1776": "curva ainda não completou", "0x1777": "curva não inicializada",
                   "0x1771": "slippage excedido"}

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
        """Vale tentar outro caminho? (curva completa, rota errada, slippage)"""
        r = str(reason or "")
        return any(c in r for c in ("0x1775", "0x1774", "0x1772", "0x1773", "0x1771", "HTTP 400", "HTTP 500"))

    async def _jup(self, inp: str, out: str, amount: int, slip_bps: int) -> dict:
        """Troca pela Jupiter (melhor rota entre as DEXs) — para tokens fora da pump.fun."""
        if self.jup is None:
            return {"status": "não executou", "reason": "Jupiter indisponível"}
        r = await self.jup._dex_swap(inp, out, amount, slip_bps=slip_bps, prio="high")
        return {"status": r.get("status") or ("confirmada" if r.get("ok") else "falhou"), "signature": r.get("signature"),
                "reason": r.get("reason"), "ok": bool(r.get("ok"))}

    async def _raw_tok(self, mint: str) -> tuple[int, int]:
        res = await self._rpc("getTokenAccountsByOwner", [self.wallet.address, {"mint": mint},
                                                          {"encoding": "jsonParsed", "commitment": "confirmed"}])
        raw, dec = 0, 0
        for a in (res or {}).get("value") or []:
            ta = a["account"]["data"]["parsed"]["info"]["tokenAmount"]
            raw += int(ta.get("amount") or 0)
            dec = int(ta.get("decimals") or 0)
        return raw, dec

    async def _sol_change(self, sig: str | None) -> float | None:
        """Quanto SOL a carteira do bot ganhou (+) ou gastou (−) NESSA transação (meta pré/pós da conta que paga).
        0.31.46: com as ordens em paralelo, a diferença de saldo da carteira misturaria duas ordens."""
        if not sig:
            return None
        try:
            tx = await self._rpc("getTransaction", [sig, {"encoding": "json", "commitment": "confirmed",
                                                          "maxSupportedTransactionVersion": 0}])
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
        sol0, tok0 = await self.balances(mint)
        if sol0 < amt + 0.02:
            return {"ok": False, "reason": f"saldo insuficiente: {sol0:.4f} SOL (precisa {amt:.3f} + 0,02 de reserva)"}
        jslip = int(float(getattr(self.cfg, "pump_other_slip_pct", 1.0)) * 100) + 100
        tried = []
        # pump.fun: curva → se a curva já completou (token graduou), PumpSwap → se ainda falhar, Jupiter
        routes = [("jupiter", None)] if other else [("pumpportal", "auto"), ("pumpportal", "pump-amm"), ("jupiter", None)]
        r, sol1, tok1 = {}, sol0, tok0
        for via, pool in routes:
            if via == "jupiter":
                r = await self._jup(SOL_MINT, mint, int(amt * 1e9), max(jslip, 300 if not other else jslip))
            else:
                r = await self._tx({"action": "buy", "mint": mint, "amount": amt, "denominatedInSol": "true", "pool": pool})
            if r.get("status") == "pendente":
                await asyncio.sleep(3)
            sol1, tok1 = await self.balances(mint)
            tried.append(f"{via if via == 'jupiter' else 'PumpPortal ' + pool}: {self.explain(r.get('reason')) or r.get('status')}")
            if tok1 - tok0 > 0:
                break
            if r.get("status") == "pendente":     # SEC-04: ainda pode entrar — outra rota compraria duas vezes
                break
            if not self.retryable(r.get("reason")):
                break
        if tok1 - tok0 <= 0:
            return {"ok": False, "status": r.get("status"), "signature": r.get("signature"),
                    "reason": " → ".join(tried)[:300] or "o token não entrou na carteira"}
        d = await self._sol_change(r.get("signature"))
        return {"ok": True, "signature": r.get("signature"), "sol_spent": max(0.0, -d if d is not None else sol0 - sol1),
                "tokens": tok1 - tok0}

    async def sell(self, mint: str, frac: float, other: bool = False) -> dict:
        """Venda REAL de `frac` da posição (100% = tudo). Mede o SOL que entrou e quanto token sobrou.
        pump.fun: PumpPortal com slippage crescente (15% → 30% → 50%); se o token graduou, PumpSwap; Jupiter só
        como último recurso (a Jupiter não negocia tokens novos ainda na curva). Guarda o motivo de cada tentativa."""
        if not self.wallet or not self.wallet.keypair:
            return {"ok": False, "reason": "carteira Solana do bot não configurada"}
        sol0, tok0 = await self.balances(mint)
        if tok0 <= 0:
            return {"ok": True, "sol_received": 0.0, "tokens_left": 0.0, "reason": "sem saldo do token"}
        pct = f"{max(1, min(100, round(frac * 100)))}%"
        base_slip = float(getattr(self.cfg, "pump_real_slippage_pct", 15))
        tried, last = [], {}
        if other:
            plan = [("jupiter", None, s_) for s_ in (3.0, 6.0, 10.0)]
        else:
            plan = [("pp", "auto", base_slip), ("pp", "auto", max(30.0, base_slip)), ("pp", "auto", 50.0)]
        pool_override = None
        k = 0
        while k < len(plan):
            via, pool, slip = plan[k]
            k += 1
            if via == "jupiter":
                raw, _dec = await self._raw_tok(mint)
                amount = raw if frac >= 0.999 else int(raw * frac)
                last = await self._jup(mint, SOL_MINT, amount, int(slip * 100))
                label = f"Jupiter {slip:.0f}%"
            else:
                pool = pool_override or pool
                last = await self._tx({"action": "sell", "mint": mint, "amount": pct, "denominatedInSol": "false",
                                       "slippage": slip, "pool": pool})
                label = f"PumpPortal {pool} {slip:.0f}%"
            if last.get("status") == "pendente":
                await asyncio.sleep(3)
            sol1, tok1 = await self.balances(mint)
            tried.append(f"{label}: {self.explain(last.get('reason')) or last.get('status')}")
            if tok1 < tok0 * 0.999:
                d = await self._sol_change(last.get("signature"))
                return {"ok": True, "signature": last.get("signature"), "sol_received": max(0.0, d if d is not None else sol1 - sol0),
                        "tokens_left": tok1, "attempts": tried}
            if last.get("status") == "pendente":
                # SEC-04 (auditoria 2026-10-25): a venda ainda pode entrar; montar outra venderia duas vezes
                return {"ok": False, "status": "pendente", "signature": last.get("signature"), "attempts": tried,
                        "reason": "venda sem confirmação — não reenvia até conferir a assinatura"}
            why = str(last.get("reason") or "")
            if via == "pp" and "0x1775" in why and pool_override is None:
                pool_override = "pump-amm"                 # graduou: as próximas tentativas vão na PumpSwap
            if via == "pp" and ("HTTP" in why or "0x1774" in why) and not any(p_[0] == "jupiter" for p_ in plan):
                plan.append(("jupiter", None, 10.0))       # PumpPortal não montou: tenta a Jupiter no fim
        return {"ok": False, "status": last.get("status"), "attempts": tried,
                "reason": " → ".join(tried)[:400] or "o token não saiu da carteira"}
