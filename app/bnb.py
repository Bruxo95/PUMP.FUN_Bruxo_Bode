"""BNB Chain · Four.Meme (etapa 1, 0.32.168): só LÊ a rede e monta o ranking próprio dos traders. Não copia nada.

Pedido do dono em 02/11/2026: copiar traders da BNB seguindo a regra do Top traders, de graça e ISOLADO do que já
funciona. Este módulo não usa nada do motor da Solana: tem RPC, memória, tabelas (bnb_*) e configuração próprios.

Como lê (conferido na rede em 02/11/2026, RPC grátis bsc-rpc.publicnode.com):
- Todo trade da curva da Four.Meme passa pelo contrato TokenManager2 (0x5c95…762b): conferido em dois tokens, 100% das
  transferências passaram por ele. Uma consulta eth_getLogs nesse endereço traz todas as compras e vendas.
- Eventos TokenPurchase/TokenSale(token, conta, preço, quantidade, valor, taxa, ofertas, fundos): nenhum campo indexado,
  8 palavras de 32 bytes. "valor" está na moeda da curva; a taxa é 1% do valor (conferido em 6 eventos).
- Alguns tokens são cotados em USDT, não em BNB (o mesmo problema da curva em outra moeda da Solana). A moeda de cada
  token vem de TokenManagerHelper3.getTokenInfo (posição 2 = moeda; zero = BNB; posição 11 = já foi para a PancakeSwap).
- O RPC oficial (bsc-dataseed) recusa eth_getLogs ("limit exceeded"); o blockrazor aceita no máximo 25 blocos.

Limites desta etapa: venda feita na PancakeSwap depois da graduação não é vista (o token conta como "aberto"); tokens
cotados em moeda que não é BNB nem dólar ficam fora das contas; o ranking começa vazio e enche com os dias.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque

from . import bnbcopy

log = logging.getLogger("bnb")

TM2 = "0x5c952063c7fc8610ffdb798152d69f0b9550762b"            # TokenManager2 da Four.Meme
HELPER3 = "0xf251f83e40a78868fcfa3fa4599dad6494e46034"         # TokenManagerHelper3 (getTokenInfo)
T_BUY = "0x7db52723a3b2cdd6164364b3b766e65e540d7be48ffa89582956d8eaebe62942"   # TokenPurchase(address,address,uint256×6)
T_SELL = "0x0a5575b3648bae2210cee56bf33254cc1ddfbc7bf637c0af2ac18b14fb1bae19"  # TokenSale(address,address,uint256×6)
SEL_TOKEN_INFO = "0x1f69565f"                                  # getTokenInfo(address)
SEL_BALANCE = "0x70a08231"                                     # balanceOf(address)
SEL_RESERVES = "0x0902f1ac"                                    # getReserves()
PAIR_USDT_WBNB = "0x16b9a82891338f9ba80e2d6970fdda79d1eb0dae"  # PancakeSwap V2: token0 = USDT, token1 = WBNB
STABLES = {"0x55d398326f99059ff775485246999027b3197955": "USDT",   # símbolo e 18 casas conferidos na rede
           "0x8d0d000ee44948fc98c9b98a4fa4921476f08b0d": "USD1",
           "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d": "USDC"}
ZERO = "0x" + "0" * 40
WBNB = "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c"
DEX_URL = "https://api.dexscreener.com/latest/dex/tokens/"   # preço depois da graduação (grátis, 300/min)

RPCS = [u.strip() for u in os.environ.get("BNB_RPCS", "https://bsc-rpc.publicnode.com,https://bsc.blockrazor.xyz").split(",")
        if u.strip()]
SPAN = {"https://bsc-rpc.publicnode.com": 400, "https://bsc.blockrazor.xyz": 25}   # blocos por consulta (medido)
POLL_S = 3.0
BLOCK_S = 0.45            # medido em 02/11/2026: 5.000 blocos em 2.250 s; corrigido sozinho a cada leitura
KEEP_S = 7 * 86400        # memória do ranking (a tabela guarda 14 dias)
DB_KEEP_S = 14 * 86400
CATCHUP_S = 6 * 3600      # depois de reiniciar, recupera no máximo 6 h
MAX_MEM = 200_000

# Mesma regra do Top traders (pumpfun.refresh_followed/_lb_judge), com valores próprios desta aba.
# min_trades começa em 20 (não 1.000 como na Solana): a Four.Meme tem cerca de 3 compras por minuto (medido em 02/11).
CFG_DEFAULT = {"days": 7, "min_trades": 20, "min_winrate": 50.0, "min_closed": 3, "min_wallet_usd": 5000.0,
               "online_min": 10.0, "top_n": 10, "bot_per_day": 400}
CFG_LIMITS = {"days": (1, 7), "min_trades": (0, 100000), "min_winrate": (0, 100), "min_closed": (1, 1000),
              "min_wallet_usd": (0, 10_000_000), "online_min": (1, 1440), "top_n": (1, 50), "bot_per_day": (10, 100000)}


def clean_cfg(raw: dict | None) -> dict:
    out = dict(CFG_DEFAULT)
    for k, v in (raw or {}).items():
        if k not in CFG_DEFAULT:
            continue
        try:
            lo, hi = CFG_LIMITS[k]
            val = float(v)
            if val != val:
                continue
            val = min(hi, max(lo, val))
            out[k] = int(val) if isinstance(CFG_DEFAULT[k], int) else round(val, 4)
        except (TypeError, ValueError):
            continue
    return out


def _word(data: str, i: int) -> int:
    return int(data[2 + 64 * i: 2 + 64 * (i + 1)] or "0", 16)


def _addr(data: str, i: int) -> str:
    return "0x" + data[2 + 64 * i + 24: 2 + 64 * (i + 1)].lower()


def decode(lg: dict) -> dict | None:
    """Um log da Four.Meme vira um trade (valores na moeda da curva, 18 casas). Outro evento devolve None."""
    tp = (lg.get("topics") or [""])[0].lower()
    if tp not in (T_BUY, T_SELL):
        return None
    d = lg.get("data") or ""
    if len(d) < 2 + 64 * 8:
        return None
    return {"id": f"{lg.get('transactionHash')}:{int(lg.get('logIndex') or '0x0', 16)}",
            "tx": lg.get("transactionHash"), "block": int(lg.get("blockNumber") or "0x0", 16),
            "token": _addr(d, 0), "wallet": _addr(d, 1), "side": "buy" if tp == T_BUY else "sell",
            "price": _word(d, 2) / 1e18, "amount": _word(d, 3) / 1e18, "value": _word(d, 4) / 1e18,
            "fee": _word(d, 5) / 1e18}


def to_bnb(tr: dict, quote: str | None, bnb_usd: float | None) -> float | None:
    """Quanto o trade mexeu na carteira, em BNB: compra = valor + taxa saindo; venda = valor − taxa entrando."""
    q = (quote or "").lower()
    v = tr["value"] + tr["fee"] if tr["side"] == "buy" else tr["value"] - tr["fee"]
    if q in ("", ZERO):
        return v
    if q in STABLES and bnb_usd:
        return v / bnb_usd
    return None


def price_bnb(tr: dict, quote: str | None, bnb_usd: float | None) -> float | None:
    """Preço do token em BNB pelo trade (o evento traz o preço na moeda da curva)."""
    q = (quote or "").lower()
    if not tr.get("price"):
        return None
    if q in ("", ZERO):
        return tr["price"]
    if q in STABLES and bnb_usd:
        return tr["price"] / bnb_usd
    return None


def rank(trades, now: float, cfg: dict, quotes: dict, bnb_usd: float | None, balances: dict,
         graduated: set | None = None) -> dict:
    """Ranking próprio pela regra do Top traders: os que mais lucraram nos últimos N dias; apto = trades mínimos, acerto
    acima do mínimo (tokens fechados com lucro), carteira com saldo mínimo, sem robô; copiaria os N melhores aptos que
    negociaram nos últimos X minutos. Lucro só do que foi realizado (vendido) e visto pela Four.Meme."""
    cfg = clean_cfg(cfg)
    since = now - cfg["days"] * 86400
    graduated = graduated or set()
    W: dict[str, dict] = {}
    fora = 0
    for t in trades:
        if t["t"] < since:
            continue
        b = to_bnb(t, quotes.get(t["token"]), bnb_usd)
        if b is None:
            fora += 1
            continue
        w = W.setdefault(t["wallet"], {"n": 0, "tk": {}, "first": t["t"], "last": t["t"], "days": set(), "vol": 0.0})
        w["n"] += 1
        w["first"], w["last"] = min(w["first"], t["t"]), max(w["last"], t["t"])
        w["days"].add(int(t["t"] // 86400))
        w["vol"] += b
        k = w["tk"].setdefault(t["token"], {"buy": 0.0, "sell": 0.0, "got": 0.0, "out": 0.0})
        if t["side"] == "buy":
            k["buy"] += b
            k["got"] += t["amount"]
        else:
            k["sell"] += b
            k["out"] += t["amount"]
    rows = []
    for wal, w in W.items():
        realized, win, closed, opened, grad_open = 0.0, 0, 0, 0, 0
        for tok, k in w["tk"].items():
            if k["got"] <= 0:
                continue                                   # vendeu o que comprou antes da janela: sem custo conhecido
            frac = min(1.0, k["out"] / k["got"])
            if frac > 0:
                realized += k["sell"] - k["buy"] * frac
            if frac >= 0.9:
                closed += 1
                win += 1 if k["sell"] > k["buy"] * frac else 0
            else:
                opened += 1
                grad_open += 1 if tok in graduated else 0
        span_d = max(1.0, (w["last"] - w["first"]) / 86400)
        rows.append({"wallet": wal, "trades": w["n"], "realized_bnb": round(realized, 6), "vol_bnb": round(w["vol"], 4),
                     "tokens": len(w["tk"]), "closed": closed, "open": opened, "grad_open": grad_open,
                     "winrate": round(100 * win / closed, 1) if closed else None, "last_t": w["last"],
                     "days_active": len(w["days"]), "per_day": round(w["n"] / span_d, 1)})
    rows.sort(key=lambda r: r["realized_bnb"], reverse=True)
    top = rows[:50]
    win_s = cfg["online_min"] * 60
    for r in top:
        flags = []
        if r["trades"] < cfg["min_trades"]:
            flags.append(f"{r['trades']} trades (precisa ≥ {cfg['min_trades']})")
        if r["winrate"] is None or r["closed"] < cfg["min_closed"]:
            flags.append(f"acerto desconhecido ({r['closed']} tokens fechados, precisa ≥ {cfg['min_closed']})")
        elif r["winrate"] <= cfg["min_winrate"]:
            flags.append(f"acerto {r['winrate']:.0f}% (precisa > {cfg['min_winrate']:.0f}%)")
        if r["per_day"] > cfg["bot_per_day"]:
            flags.append(f"robô: {r['per_day']:.0f} trades por dia")
        bal = balances.get(r["wallet"])
        r["wallet_usd"] = bal.get("usd") if bal else None
        if cfg["min_wallet_usd"]:
            if bal is None or bal.get("usd") is None:
                flags.append("conferindo saldo da carteira…")
            elif bal["usd"] < cfg["min_wallet_usd"]:
                flags.append(f"carteira ${bal['usd']:,.0f} < ${cfg['min_wallet_usd']:,.0f}".replace(",", "."))
        r["flags"], r["eligible"] = flags, not flags
        r["online"] = now - r["last_t"] <= win_s
    chosen = [r["wallet"] for r in top if r["eligible"] and r["online"]][:cfg["top_n"]]
    for r in top:
        r["copiaria"] = r["wallet"] in chosen
    return {"rows": top, "copiaria": chosen, "carteiras": len(rows), "fora_moeda": fora,
            "aptos": sum(1 for r in top if r["eligible"]), "aptos_online": sum(1 for r in top if r["eligible"] and r["online"])}


class RpcError(Exception):
    pass


class BnbWatch:
    """Leitura da Four.Meme num laço próprio. db pode ser None (sem guardar)."""

    def __init__(self, http, db=None, rpcs: list[str] | None = None):
        self.http, self.db = http, db
        self.rpcs = list(rpcs or RPCS)
        self.rpc_i = 0
        self.span = {u: SPAN.get(u, 25) for u in self.rpcs}
        self.trades: deque = deque(maxlen=MAX_MEM)
        self.seen: set = set()
        self.quotes: dict[str, str] = {}
        self.graduated: set = set()
        self.balances: dict[str, dict] = {}
        self.bnb_usd: float | None = None
        self._bnb_at = 0.0
        self.cfg = dict(CFG_DEFAULT)
        self.cursor: int | None = None
        self.head: int | None = None
        self.head_t: float | None = None
        self.block_s = BLOCK_S
        self._ts_at = 0.0
        self.pending: list[dict] = []
        self.stat = {"polls": 0, "logs": 0, "erros": 0, "ultimo_erro": None, "ultimo_erro_t": None, "rpc": None,
                     "carregados": 0, "desde": time.time(), "chamadas": 0}
        self._flush_at = time.time()
        self._trim_at = 0.0
        self._bal_q: deque = deque()
        self._rank_cache: tuple[float, dict] | None = None
        self.loaded = False
        # 0.32.170: cópia fictícia por conta de admin (bnbcopy.Book); o que cada trader tem em cada token (para vender a
        # mesma parte) e o último preço em BNB de cada token
        self.books: dict[str, bnbcopy.Book] = {}
        self.hold: dict[tuple, float] = {}
        self.px: dict[str, tuple] = {}
        self._dex_at: dict[str, float] = {}
        self._grad_at: dict[str, float] = {}

    # ------------------------------------------------------------------ RPC
    async def rpc(self, method: str, params: list):
        last = None
        for k in range(len(self.rpcs)):
            url = self.rpcs[(self.rpc_i + k) % len(self.rpcs)]
            try:
                self.stat["chamadas"] += 1
                r = await self.http.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                                         timeout=15)
                js = r.json()
                if js.get("error"):
                    msg = str(js["error"].get("message") or js["error"])[:160]
                    if method == "eth_getLogs" and ("range" in msg or "limit" in msg or "exceed" in msg):
                        self.span[url] = max(5, self.span.get(url, 25) // 2)
                    raise RpcError(msg)
                self.rpc_i = (self.rpc_i + k) % len(self.rpcs)
                self.stat["rpc"] = url
                return js.get("result")
            except Exception as e:
                last = f"{url.split('//')[-1]}: {type(e).__name__} {str(e)[:120]}"
        raise RpcError(last or "sem RPC")

    async def _call(self, to: str, data: str) -> str:
        return await self.rpc("eth_call", [{"to": to, "data": data}, "latest"]) or "0x"

    async def refresh_bnb_usd(self) -> None:
        if self.bnb_usd and time.time() - self._bnb_at < 300:
            return
        h = await self._call(PAIR_USDT_WBNB, SEL_RESERVES)
        r0, r1 = _word(h, 0), _word(h, 1)                      # USDT, WBNB (as duas com 18 casas)
        if r0 and r1:
            self.bnb_usd, self._bnb_at = r0 / r1, time.time()

    async def token_info(self, token: str) -> None:
        h = await self._call(HELPER3, SEL_TOKEN_INFO + token[2:].rjust(64, "0"))
        if len(h) < 2 + 64 * 12:
            self.quotes[token] = "?"
            return
        self.quotes[token] = _addr(h, 2)
        if _word(h, 11):
            self.graduated.add(token)

    # ------------------------------------------------------------------ leitura
    async def poll(self) -> int:
        """Uma volta: blocos novos → trades. Devolve quantos trades entraram."""
        head = int(await self.rpc("eth_blockNumber", []), 16)
        if self.head and self.head_t and time.time() - self._ts_at < 30:
            ht = self.head_t + (head - self.head) * self.block_s    # economiza uma consulta: hora do bloco a cada 30 s
        else:
            blk = await self.rpc("eth_getBlockByNumber", [hex(head), False])
            ht = int(blk["timestamp"], 16) if blk else time.time()
            if self.head and self.head_t and head > self.head:
                bs = (ht - self.head_t) / (head - self.head)
                if 0.1 < bs < 3:
                    self.block_s = round(self.block_s * 0.9 + bs * 0.1, 4)
            self._ts_at = time.time()
        self.head, self.head_t = head, ht
        if self.cursor is None or head - self.cursor > CATCHUP_S / self.block_s:
            self.cursor = head - int(60 / self.block_s)        # sem cursor (ou muito velho): começa 1 min atrás
        n = 0
        url = self.rpcs[self.rpc_i]
        while self.cursor < head:
            a = self.cursor + 1
            b = min(head, a + self.span.get(url, 25) - 1)
            logs = await self.rpc("eth_getLogs", [{"address": TM2, "topics": [[T_BUY, T_SELL]],
                                                   "fromBlock": hex(a), "toBlock": hex(b)}]) or []
            new = []
            for lg in logs:
                tr = decode(lg)
                if not tr or tr["id"] in self.seen:
                    continue
                tr["t"] = round(ht - (head - tr["block"]) * self.block_s, 1)
                new.append(tr)
            cop = set(self.ranking()["copiaria"]) if new and self.books else set()
            for tr in new:
                if tr["token"] not in self.quotes:
                    try:
                        await self.token_info(tr["token"])
                    except RpcError:
                        pass                                   # tenta de novo na próxima vez que o token negociar
                tr["quote"] = self.quotes.get(tr["token"])
                before = self.hold.get((tr["wallet"], tr["token"]), 0.0)
                self._add(tr, save=True)
                self._copy(tr, before, cop)
                n += 1
            self.stat["logs"] += len(logs)
            self.cursor = b
            if n > 2000:
                break                                          # recuperação longa: continua na próxima volta
        self.stat["polls"] += 1
        return n

    def _add(self, tr: dict, save: bool = False) -> None:
        if tr["id"] in self.seen:
            return
        if len(self.trades) == self.trades.maxlen:
            self.seen.discard(self.trades[0]["id"])
        self.trades.append(tr)
        self.seen.add(tr["id"])
        if tr.get("quote") and tr["token"] not in self.quotes:
            self.quotes[tr["token"]] = tr["quote"]
        k = (tr["wallet"], tr["token"])
        self.hold[k] = max(0.0, self.hold.get(k, 0.0) + (tr["amount"] or 0) * (1 if tr["side"] == "buy" else -1))
        px = price_bnb(tr, tr.get("quote"), self.bnb_usd)
        if px and (tr["token"] not in self.px or tr["t"] >= self.px[tr["token"]][1]):
            self.px[tr["token"]] = (px, tr["t"])
        if save:
            self.pending.append(tr)
        self._rank_cache = None

    # ------------------------------------------------------------------ cópia fictícia (0.32.170)
    def book(self, uid: str) -> bnbcopy.Book:
        b = self.books.get(uid)
        if b is None:
            b = self.books[uid] = bnbcopy.Book(uid)
            b.dirty_book = True
        return b

    def _copy(self, tr: dict, before: float, cop: set) -> None:
        """Trade novo lido: o trader do ranking comprou → a fictícia compra; quem tem posição copiada vendeu → vende a
        mesma parte. Também atualiza o preço das posições abertas do token."""
        px = self.px.get(tr["token"], (None,))[0]
        for b in self.books.values():
            if px:
                b.on_price(tr["token"], px, tr["t"])
            if tr["side"] == "buy" and tr["wallet"] in cop and time.time() - tr["t"] <= 60:   # recuperação após reinício não copia
                tr["bnb"] = to_bnb(tr, tr.get("quote"), self.bnb_usd)
                b.buy(tr, px, time.time())
            elif tr["side"] == "sell":
                frac = min(1.0, (tr["amount"] or 0) / before) if before > 0 else 1.0
                for p in [p for p in b.pos.values() if p["wallet"] == tr["wallet"] and p["token"] == tr["token"]]:
                    b.sell(p, frac, px, time.time(), f"trader vendeu {frac * 100:.0f}%")

    async def positions_tick(self) -> None:
        """Tempo máximo das posições e preço dos tokens que já foram para a PancakeSwap (a Four.Meme não negocia mais)."""
        now = time.time()
        for b in self.books.values():
            b.timeouts(now)
        toks = {p["token"] for b in self.books.values() for p in b.pos.values()}
        for tk in list(toks)[:20]:
            if tk not in self.graduated and now - self._grad_at.get(tk, 0) > 300:
                self._grad_at[tk] = now
                try:
                    await self.token_info(tk)
                except RpcError:
                    pass
            if tk in self.graduated and now - self._dex_at.get(tk, 0) > 60:
                self._dex_at[tk] = now
                px = await self.dex_price(tk)
                if px:
                    self.px[tk] = (px, now)
                    for b in self.books.values():
                        b.on_price(tk, px, now)

    async def dex_price(self, token: str) -> float | None:
        try:
            r = await self.http.get(DEX_URL + token, timeout=10)
            pairs = [x for x in (r.json().get("pairs") or []) if x.get("chainId") == "bsc"
                     and ((x.get("quoteToken") or {}).get("address") or "").lower() == WBNB and x.get("priceNative")]
            pairs.sort(key=lambda x: float((x.get("liquidity") or {}).get("usd") or 0), reverse=True)
            return float(pairs[0]["priceNative"]) if pairs else None
        except Exception:
            return None

    def painel(self, uid: str, now: float | None = None) -> dict:
        now = now or time.time()
        b = self.book(uid)
        pos = []
        for p in sorted(b.pos.values(), key=lambda x: x["open_t"], reverse=True):
            sol, pct = b.pnl_now(p)
            pos.append({**{k: p.get(k) for k in ("id", "wallet", "token", "open_t", "px_in", "px_now", "px_t", "bnb_in",
                                                  "proceeds", "best_pct", "worst_pct", "lag_s", "tx_in", "vendas", "aba")},
                        "pnl_bnb": round(sol, 6), "pnl_pct": round(pct, 2), "graduou": p["token"] in self.graduated,
                        "fecha_em": p["open_t"] + b.cfg["max_hold_h"] * 3600})
        return {"cfg": b.cfg, "padrao": bnbcopy.CFG_DEFAULT, "carteira": b.wallet(now), "posicoes": pos,
                "trades": b.trades[:500], "eventos": b.events[:100], "semana": bnbcopy.week_split(b.trades),
                "abas": [{"aba": "top", "nome": "Top traders BNB", "ligada": b.cfg["on"], "abertas": len(b.pos),
                          "fechadas": len(b.trades), "periodos": bnbcopy.periods(b.trades, now),
                          "resultado": round(sum(x["pnl_bnb"] for x in b.trades), 6)}],
                "copiaria": self.ranking(now)["copiaria"],
                "leitura_ok": bool(self.trades) and not (self.stat["ultimo_erro_t"] and now - self.stat["ultimo_erro_t"] < 120)}

    async def save_book_cfg(self, uid: str, raw: dict) -> dict:
        b = self.book(uid)
        old = b.cfg["saldo_inicial"]
        b.cfg = bnbcopy.clean_cfg(raw, b.cfg)
        b.cash += b.cfg["saldo_inicial"] - old             # mudar o saldo inicial soma/tira a diferença do saldo
        b.dirty_book = True
        await self.flush_books()
        return b.cfg

    def close_manual(self, uid: str, pid: str) -> dict | None:
        b = self.book(uid)
        p = b.pos.get(pid)
        return b.sell(p, 1.0, None, time.time(), "vendido por você") if p else None

    async def flush_books(self) -> None:
        if self.db is None:
            for b in self.books.values():
                b.dirty_pos.clear()
                b.closed_pos.clear()
                b.new_trades.clear()
                b.dirty_book = False
            return
        for b in list(self.books.values()):
            try:
                if b.dirty_book:
                    await self.db.insert("bnb_books", {"user_id": b.user_id, "cfg": b.cfg, "cash": b.cash},
                                         upsert=True, on_conflict="user_id")
                    b.dirty_book = False
                if b.new_trades:
                    rows = [{"id": x["id"], "user_id": b.user_id, "t": x["close_t"], "data": x} for x in b.new_trades]
                    await self.db.insert("bnb_trades", rows, upsert=True, on_conflict="id")
                    b.new_trades.clear()
                for pid in list(b.closed_pos):
                    await self.db.delete("bnb_positions", {"id": pid, "user_id": b.user_id})
                    b.closed_pos.discard(pid)
                rows = [{"id": pid, "user_id": b.user_id, "data": b.pos[pid]} for pid in b.dirty_pos if pid in b.pos]
                if rows:
                    await self.db.insert("bnb_positions", rows, upsert=True, on_conflict="id")
                b.dirty_pos.clear()
            except Exception as e:
                log.warning("BNB: carteira fictícia não gravou: %s", str(e)[:160])

    async def load_books(self) -> None:
        for r in await self.db.select("bnb_books", None) or []:
            b = self.books[r["user_id"]] = bnbcopy.Book(r["user_id"], r.get("cfg"), r.get("cash"))
            b.dirty_book = False
        for r in await self.db.select("bnb_positions", None) or []:
            if r.get("user_id") in self.books and isinstance(r.get("data"), dict):
                self.books[r["user_id"]].pos[r["id"]] = r["data"]
        for r in await self.db.select("bnb_trades", None, order="t.desc", limit=20000) or []:
            b = self.books.get(r.get("user_id"))
            if b is not None and isinstance(r.get("data"), dict) and len(b.trades) < bnbcopy.KEEP_TRADES:
                b.trades.append(r["data"])

    async def balances_tick(self, wallets: list[str]) -> None:
        """Saldo das carteiras do topo (BNB + USDT + USD1 + USDC), no máximo 6 por volta; vale 30 min."""
        now = time.time()
        for w in wallets:
            b = self.balances.get(w)
            if (not b or now - b["t"] > 1800) and w not in self._bal_q:
                self._bal_q.append(w)
        if not self.bnb_usd:
            return
        for _ in range(min(6, len(self._bal_q))):
            w = self._bal_q.popleft()
            try:
                bnb = int(await self.rpc("eth_getBalance", [w, "latest"]) or "0x0", 16) / 1e18
                usd = bnb * self.bnb_usd
                for s in STABLES:
                    usd += _word(await self._call(s, SEL_BALANCE + w[2:].rjust(64, "0")), 0) / 1e18
                self.balances[w] = {"bnb": round(bnb, 4), "usd": round(usd, 2), "t": now}
            except RpcError:
                self.balances.setdefault(w, {"bnb": None, "usd": None, "t": now - 1500})   # tenta de novo em 5 min

    def ranking(self, now: float | None = None) -> dict:
        now = now or time.time()
        if self._rank_cache and now - self._rank_cache[0] < 10:
            return self._rank_cache[1]
        r = rank(self.trades, now, self.cfg, self.quotes, self.bnb_usd, self.balances, self.graduated)
        self._rank_cache = (now, r)
        return r

    # ------------------------------------------------------------------ banco
    async def load(self) -> None:
        if self.db is None:
            self.loaded = True
            return
        try:
            for r in await self.db.select("bnb_state", None) or []:
                if r.get("k") == "cfg" and isinstance(r.get("v"), dict):
                    self.cfg = clean_cfg(r["v"])
                elif r.get("k") == "cursor" and isinstance(r.get("v"), dict):
                    self.cursor = int(r["v"].get("block") or 0) or None
            since = time.time() - KEEP_S
            off = 0
            while True:
                rows = await self.db.select("bnb_fm_trades", None, order="t.asc", limit=5000, offset=off,
                                            gte={"t": since}) or []
                for r in rows:
                    self._add({k: r.get(k) for k in ("id", "tx", "block", "token", "wallet", "side", "price", "amount",
                                                     "value", "fee", "t", "quote")})
                off += len(rows)
                if len(rows) < 5000 or off >= MAX_MEM:
                    break
            self.stat["carregados"] = off
            await self.load_books()
        except Exception as e:
            log.warning("BNB: dados guardados não carregaram: %s", str(e)[:160])
        self.loaded = True

    async def flush(self) -> None:
        if self.db is None:
            self.pending.clear()
            return
        rows, self.pending = self.pending[:1000], self.pending[1000:]
        try:
            if rows:
                await self.db.insert("bnb_fm_trades", [{k: r.get(k) for k in ("id", "tx", "block", "token", "wallet", "side",
                                                                             "price", "amount", "value", "fee", "t", "quote")}
                                                      for r in rows], upsert=True, on_conflict="id")
            if self.cursor:
                await self.db.insert("bnb_state", {"k": "cursor", "v": {"block": self.cursor, "t": time.time()}},
                                     upsert=True, on_conflict="k")
        except Exception as e:
            self.pending = rows + self.pending                 # não perde: tenta de novo na próxima
            log.warning("BNB: não gravou %d trades: %s", len(rows), str(e)[:160])
        if time.time() - self._trim_at > 86400:
            self._trim_at = time.time()
            try:
                await self.db.rpc("bnb_trim", {"antes": time.time() - DB_KEEP_S})
            except Exception as e:
                log.warning("BNB: limpeza dos trades antigos: %s", str(e)[:120])

    async def save_cfg(self, raw: dict) -> dict:
        self.cfg = clean_cfg({**self.cfg, **(raw or {})})
        self._rank_cache = None
        if self.db is not None:
            await self.db.insert("bnb_state", {"k": "cfg", "v": self.cfg}, upsert=True, on_conflict="k")
        return self.cfg

    # ------------------------------------------------------------------ laço
    async def run(self) -> None:
        await self.load()
        while True:
            try:
                await self.poll()
                await self.refresh_bnb_usd()
                await self.balances_tick([r["wallet"] for r in self.ranking()["rows"][:30]])
                await self.positions_tick()
            except Exception as e:
                self.stat["erros"] += 1
                self.stat["ultimo_erro"], self.stat["ultimo_erro_t"] = str(e)[:200], time.time()
            if time.time() - self._flush_at > 30:
                self._flush_at = time.time()
                await self.flush()
                await self.flush_books()
            await asyncio.sleep(POLL_S)

    def state(self, now: float | None = None) -> dict:
        now = now or time.time()
        rk = self.ranking(now)
        last = self.trades[-1]["t"] if self.trades else None
        day = [t for t in self.trades if t["t"] >= now - 86400]
        q = {}
        for t in day:
            nm = "BNB" if (t.get("quote") or ZERO) == ZERO else STABLES.get(t.get("quote") or "", "outra")
            q[nm] = q.get(nm, 0) + 1
        recent = []
        for t in list(self.trades)[-60:][::-1]:
            recent.append({**{k: t.get(k) for k in ("t", "tx", "token", "wallet", "side", "amount")},
                           "bnb": (lambda b: round(b, 5) if b is not None else None)(to_bnb(t, t.get("quote"), self.bnb_usd)),
                           "moeda": "BNB" if (t.get("quote") or ZERO) == ZERO else STABLES.get(t.get("quote") or "", "outra")})
        return {"ligado": True, "carregado": self.loaded, "cfg": self.cfg, "padrao": CFG_DEFAULT,
                "status": {"bloco": self.head, "lido_ate": self.cursor,
                           "atraso_s": round((self.head - self.cursor) * self.block_s, 1) if self.head and self.cursor else None,
                           "ultimo_trade_t": last, "trades_memoria": len(self.trades), "trades_24h": len(day),
                           "compras_24h": sum(1 for t in day if t["side"] == "buy"),
                           "carteiras_24h": len({t["wallet"] for t in day}), "tokens_24h": len({t["token"] for t in day}),
                           "moedas_24h": q, "bnb_usd": round(self.bnb_usd, 2) if self.bnb_usd else None,
                           "graduados": len(self.graduated), "rpc": (self.stat["rpc"] or "").split("//")[-1],
                           "erros": self.stat["erros"], "ultimo_erro": self.stat["ultimo_erro"],
                           "ultimo_erro_t": self.stat["ultimo_erro_t"], "chamadas": self.stat["chamadas"],
                           "desde": self.stat["desde"], "a_gravar": len(self.pending), "carregados": self.stat["carregados"],
                           "bloco_s": self.block_s},
                "ranking": rk, "recentes": recent}
