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

from . import bnbcopy, bnbhist, bnbpancake, bnbreal, bnbsafe, evm

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
BNB_KEY_NAME = "bnb_private_key"   # 0.32.172: nome no cofre (user_secrets), separado das chaves da Solana

RPCS = [u.strip() for u in os.environ.get("BNB_RPCS", "https://bsc-rpc.publicnode.com,https://bsc.blockrazor.xyz").split(",")
        if u.strip()]
SPAN = {"https://bsc-rpc.publicnode.com": 400, "https://bsc.blockrazor.xyz": 25}   # blocos por consulta (medido)
POLL_S = 3.0
POLL_MAX_S = 25.0         # 0.32.183: uma volta lê no máximo 25 s de blocos; o resto fica para a próxima (o bloco e a gravação andam)
STEP_MAX_S = 90.0         # prazo da leitura numa volta (inclui as consultas que esperam o RPC)
BLOCK_S = 0.45            # medido em 02/11/2026: 5.000 blocos em 2.250 s; corrigido sozinho a cada leitura
KEEP_S = 14 * 86400       # memória do ranking = o que a tabela guarda (0.32.179: era 7 dias)
DB_KEEP_S = 14 * 86400
CATCHUP_S = 6 * 3600      # depois de reiniciar, recupera no máximo 6 h
MAX_MEM = 300_000

# Mesma regra do Top traders (pumpfun.refresh_followed/_lb_judge), com valores próprios desta aba.
# min_trades começa em 20 (não 1.000 como na Solana): a Four.Meme tem cerca de 3 compras por minuto (medido em 02/11).
CFG_DEFAULT = {"days": 7, "min_trades": 20, "min_winrate": 50.0, "min_closed": 3, "min_wallet_usd": 5000.0,
               "online_min": 10.0, "top_n": 10, "bot_per_day": 400}
CFG_LIMITS = {"days": (1, 14), "min_trades": (0, 100000), "min_winrate": (0, 100), "min_closed": (1, 1000),
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
        w = W.setdefault(t["wallet"], {"n": 0, "tk": {}, "first": t["t"], "last": t["t"], "days": set(), "vol": 0.0, "pc": 0})
        w["n"] += 1
        w["pc"] += 1 if t.get("venue") == "pancake" else 0
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
        g_real, g_tok, g_win, g_closed = 0.0, 0, 0, 0
        for tok, k in w["tk"].items():
            if k["got"] <= 0:
                continue                                   # vendeu o que comprou antes da janela: sem custo conhecido
            frac = min(1.0, k["out"] / k["got"])
            if frac > 0:
                realized += k["sell"] - k["buy"] * frac
            if tok in graduated:                           # 0.32.178: o que ganhou nos tokens que foram para a PancakeSwap
                g_tok += 1
                if frac > 0:
                    g_real += k["sell"] - k["buy"] * frac
                if frac >= 0.9:
                    g_closed += 1
                    g_win += 1 if k["sell"] > k["buy"] * frac else 0
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
                     "days_active": len(w["days"]), "per_day": round(w["n"] / span_d, 1),
                     "grad_realized_bnb": round(g_real, 6), "grad_tokens": g_tok, "grad_closed": g_closed,
                     "grad_winrate": round(100 * g_win / g_closed, 1) if g_closed else None, "pancake_trades": w["pc"]})
    rows.sort(key=lambda r: r["realized_bnb"], reverse=True)
    grad_rows = sorted([r for r in rows if r["grad_realized_bnb"] > 0], key=lambda r: r["grad_realized_bnb"], reverse=True)[:30]
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
    for r in grad_rows:
        r["no_top"] = r in top
        r["copiaria"] = r["wallet"] in chosen
        r.setdefault("bot", r["per_day"] > cfg["bot_per_day"])
    return {"rows": top, "copiaria": chosen, "carteiras": len(rows), "fora_moeda": fora, "graduados": grad_rows,
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
        # 0.32.172: carteira REAL (bnbreal). Começa desligada; a chave vem do cofre (user_secrets, criptografada) e só fica
        # na memória. real_allowed = trava geral PUMP_REAL_ALLOWED do servidor (main.py liga as duas).
        self.real: dict[str, bnbreal.RealBook] = {}
        self.real_cfg: dict[str, dict] = {}
        self.vault = None
        self.real_allowed = False
        self.chain = bnbreal.Chain(self.rpc)
        self._keys: dict[str, tuple] = {}
        self._tasks: set = set()
        self._rbal_at = 0.0
        # 0.32.177: segurança do token antes de toda compra (fictícia e REAL): honeypot, congelar, taxa alta… (bnbsafe)
        self.safe = bnbsafe.Safety(self._call, http)
        # 0.32.178: tokens que foram para a PancakeSwap (par V2) e as compras/vendas lá (bnbpancake)
        self.pairs: dict[str, dict] = {}          # token → pair_info (+ t = quando achamos o par)
        self._gchk: dict[str, float] = {}         # token → última conferência de "graduou?" / "qual o par?"
        self._gq: deque = deque()
        self._pairs_dirty = False
        self.pstat = {"trades": 0, "erros": 0, "ultimo_erro": None, "graduados_achados": 0}
        self._pk_off_until = 0.0
        self.etapa, self.volta_t = None, None            # 0.32.183: onde o laço está e quando terminou a última volta
        # 0.32.179: histórico dos últimos dias pela NodeReal (chave do sistema; main.py liga key_fn)
        self.key_fn = lambda: ""
        self.hist = bnbhist.Backfill(self, lambda: self.key_fn())

    # ------------------------------------------------------------------ RPC
    async def rpc(self, method: str, params: list, side: bool = False):
        """side=True: consulta extra (PancakeSwap). Não encolhe o trecho de leitura da curva nem troca o RPC principal
        (0.32.183: as recusas dela encolhiam o trecho da curva e o monitor parou em 04/11)."""
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
                    if not side and method == "eth_getLogs" and ("range" in msg or "limit" in msg or "exceed" in msg):
                        self.span[url] = max(5, self.span.get(url, 25) // 2)
                    raise RpcError(msg)
                if not side:
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

    async def token_info(self, token: str, call=None) -> None:
        h = await (call or self._call)(HELPER3, SEL_TOKEN_INFO + token[2:].rjust(64, "0"))
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
        t0 = time.monotonic()
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
            for tr in await self._pancake_logs(a, b):
                if tr["id"] not in self.seen:
                    tr["t"] = round(ht - (head - tr["block"]) * self.block_s, 1)
                    new.append(tr)
            new.sort(key=lambda x: (x["block"], x["id"]))
            cop = set(self.ranking()["copiaria"]) if new and self.books else set()
            for tr in new:
                if tr["token"] not in self.quotes and tr.get("venue") != "pancake":
                    try:
                        await self.token_info(tr["token"])
                    except RpcError:
                        pass                                   # tenta de novo na próxima vez que o token negociar
                tr["quote"] = self.quotes.get(tr["token"]) or tr.get("quote")
                before = self.hold.get((tr["wallet"], tr["token"]), 0.0)
                self._add(tr, save=True)
                self._copy(tr, before, cop)
                n += 1
            self.stat["logs"] += len(logs)
            self.cursor = b
            if n > 2000 or time.monotonic() - t0 > POLL_MAX_S:
                break                                          # recuperação longa: continua na próxima volta
        self.stat["polls"] += 1
        return n

    # ------------------------------------------------------------------ PancakeSwap (0.32.178)
    def _active_pairs(self) -> dict[str, dict]:
        top = sorted(self.pairs.values(), key=lambda x: x.get("t") or 0, reverse=True)[:bnbpancake.PAIRS_MAX]
        return {p["pair"]: p for p in top}

    async def _pancake_logs(self, a: int, b: int) -> list[dict]:
        """Compras e vendas nos pares da PancakeSwap dos tokens graduados, no mesmo trecho de blocos da curva."""
        pairs = self._active_pairs()
        if not pairs or time.time() < self._pk_off_until:
            return []
        try:
            rng = {"fromBlock": hex(a), "toBlock": hex(b)}
            B = bnbpancake.ADDR_MAX
            plist = list(pairs)
            swaps: list[dict] = []
            for i in range(0, len(plist), B):
                swaps += await self.rpc("eth_getLogs", [{**rng, "address": plist[i:i + B], "topics": [bnbpancake.T_SWAP]}],
                                        side=True) or []
            if not swaps:
                return []
            hit = {(s.get("address") or "").lower() for s in swaps}
            hp = [x for x in plist if x.lower() in hit]               # transferências só dos pares que tiveram troca
            tr: list[dict] = []
            for i in range(0, len(hp), B):
                part = hp[i:i + B]
                pt = [bnbpancake.topic_addr(x) for x in part]
                toks = list({pairs[x]["token"] for x in part})
                tr += await self.rpc("eth_getLogs", [{**rng, "address": toks, "topics": [bnbpancake.T_TRANSFER, None, pt]}], side=True) or []
                tr += await self.rpc("eth_getLogs", [{**rng, "address": toks, "topics": [bnbpancake.T_TRANSFER, pt]}], side=True) or []
            out = bnbpancake.decode(swaps, tr, pairs)
            self.pstat["trades"] += len(out)
            return out
        except Exception as e:                                  # a PancakeSwap nunca para a leitura da curva
            self.pstat["erros"] += 1
            self.pstat["ultimo_erro"] = str(e)[:160]
            self._pk_off_until = time.time() + bnbpancake.PAUSE_S
            return []

    async def grad_tick(self) -> None:
        """Descobre os tokens da curva que graduaram e o par V2 de cada um (limite de consultas por minuto)."""
        now = time.time()
        while self._gq and now - self._gq[0] > 60:
            self._gq.popleft()
        recent: dict[str, float] = {}
        for t in reversed(self.trades):
            if now - t["t"] > bnbpancake.GRAD_LOOK_S:
                break
            if t.get("venue") != "pancake":
                recent.setdefault(t["token"], t["t"])
        want = [tk for tk in self.graduated if tk not in self.pairs and now - self._gchk.get(tk, 0) > 300]
        want += [tk for tk, _ in sorted(recent.items(), key=lambda x: -x[1])
                 if tk not in self.graduated and now - self._gchk.get(tk, 0) > bnbpancake.GRAD_EVERY_S]
        for tk in want:
            if len(self._gq) >= bnbpancake.GRAD_PER_MIN:
                break
            self._gq.append(now)
            self._gchk[tk] = now
            try:
                if tk not in self.graduated:
                    await self.token_info(tk)
                if tk in self.graduated and tk not in self.pairs:
                    self._gq.append(now)
                    pair = await bnbpancake.find_pair(self._call, tk, self.quotes.get(tk) or ZERO)
                    if pair:
                        self.pairs[tk] = {**bnbpancake.pair_info(tk, self.quotes.get(tk) or ZERO, pair), "t": now}
                        self._pairs_dirty = True
                        self.pstat["graduados_achados"] += 1
                        log.info("BNB: %s… graduou, par PancakeSwap %s…", tk[:10], pair[:10])
            except Exception:
                pass

    def add_old(self, trs: list[dict]) -> None:
        """Trades antigos (histórico): entram na memória em ordem de hora e vão para o banco, sem cópia e sem mexer no
        que cada trader segura agora."""
        new = [t for t in trs if t["id"] not in self.seen]
        if not new:
            return
        allt = sorted(list(self.trades) + new, key=lambda x: x["t"])[-MAX_MEM:]
        self.trades = deque(allt, maxlen=MAX_MEM)
        self.seen = {t["id"] for t in self.trades}
        for t in new:
            if t.get("quote") and t["token"] not in self.quotes:
                self.quotes[t["token"]] = t["quote"]
            px = price_bnb(t, t.get("quote"), self.bnb_usd)
            if px and (t["token"] not in self.px or t["t"] >= self.px[t["token"]][1]):
                self.px[t["token"]] = (px, t["t"])
        self.pending.extend(new)
        self._rank_cache = None

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
        """Trade novo lido: o trader do ranking comprou → confere a segurança do token e a fictícia (e a REAL ligada)
        compra; quem tem posição copiada vendeu → vende a mesma parte. Também atualiza o preço das posições abertas."""
        px = self.px.get(tr["token"], (None,))[0]
        for b in self.books.values():
            if px:
                b.on_price(tr["token"], px, tr["t"])
            if tr["side"] == "sell":
                frac = min(1.0, (tr["amount"] or 0) / before) if before > 0 else 1.0
                for p in [p for p in b.pos.values() if p["wallet"] == tr["wallet"] and p["token"] == tr["token"]]:
                    b.sell(p, frac, px, time.time(), f"trader vendeu {frac * 100:.0f}%")
        # 0.32.172: a REAL segue a mesma decisão, com valor e limites próprios; só compras novas (até 60 s) entram
        for uid, rb in self.real.items():
            if px:
                self._real_price(uid, rb, tr["token"], px, tr["t"])
            if tr["side"] == "sell":
                frac = min(1.0, (tr["amount"] or 0) / before) if before > 0 else 1.0
                for p in [p for p in rb.pos.values() if p["wallet"] == tr["wallet"] and p["token"] == tr["token"]]:
                    p["retry_frac"] = frac
                    self._spawn(self._real_sell(uid, p, frac, f"trader vendeu {frac * 100:.0f}%"))
        if tr["side"] == "buy" and tr["wallet"] in cop and time.time() - tr["t"] <= 60:   # recuperação após reinício não copia
            tr["bnb"] = to_bnb(tr, tr.get("quote"), self.bnb_usd)
            v = self.safe.cached(tr["token"])
            if v is not None:
                self._buy_all(tr, v)
            else:
                self._spawn(self._safe_buy(tr))

    async def _try_buy(self, token: str, funds: int) -> list[int]:
        return evm.words(await self._call(bnbreal.HELPER3, evm.call_data(bnbreal.SEL["try_buy"], token, 0, funds)))

    async def _try_sell(self, token: str, amount: int) -> list[int]:
        return evm.words(await self._call(bnbreal.HELPER3, evm.call_data(bnbreal.SEL["try_sell"], token, amount)))

    async def _safe_buy(self, tr: dict) -> None:
        tk = tr["token"]
        try:
            v = await self.safe.check(tk, tk in self.graduated, (self.quotes.get(tk) or ZERO) not in ("", ZERO, "?"),
                                      self.bnb_usd, self._try_buy, self._try_sell)
        except Exception as e:                                     # nunca compra sem conferir
            v = self.safe.mark(tk, False, "falha na conferência (" + type(e).__name__ + ")", erro=True)
        self._buy_all(tr, v)

    def _buy_all(self, tr: dict, v: dict) -> None:
        """Compra (ou registra por que não comprou) em toda carteira fictícia e REAL ligada, depois da conferência."""
        now = time.time()
        px = self.px.get(tr["token"], (None,))[0]
        if not v["ok"]:
            why = "token barrado pela segurança: " + v["why"]
            for b in self.books.values():
                if b.cfg.get("on"):
                    b._ev(now, tr["wallet"], tr["token"], "não copiou", why)
            for uid, rc in list(self.real_cfg.items()):
                if rc.get("real_on"):
                    self.rbook(uid).ev(now, tr["wallet"], tr["token"], "REAL não copiou", why)
            log.info("BNB: não copiou %s… (%s)", tr["token"][:10], v["why"][:120])
            return
        for b in self.books.values():
            b.buy(tr, px, now)
        for uid, rc in list(self.real_cfg.items()):
            if rc.get("real_on"):
                self._spawn(self._real_buy(uid, tr, px))

    # ------------------------------------------------------------------ carteira REAL (0.32.172)
    def rbook(self, uid: str) -> bnbreal.RealBook:
        rb = self.real.get(uid)
        if rb is None:
            rb = self.real[uid] = bnbreal.RealBook(uid)
        return rb

    def rcfg(self, uid: str) -> dict:
        if uid not in self.real_cfg:
            self.real_cfg[uid] = bnbreal.clean(None)
        return self.real_cfg[uid]

    def _spawn(self, coro) -> None:
        t = asyncio.ensure_future(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    async def get_key(self, uid: str):
        """(chave, endereço) da carteira BNB da conta, ou (None, None). A chave nunca sai da memória do servidor."""
        k = self._keys.get(uid)
        if k and time.time() - k[2] < 300:
            return k[0], k[1]
        if self.vault is None:
            return None, None
        try:
            v = (await self.vault.load(uid)).get(BNB_KEY_NAME)
            key = evm.parse_key(v) if v else None
        except Exception:
            key = None
        addr = evm.address_of(key) if key else None
        self._keys[uid] = (key, addr, time.time())
        if addr:
            self.rbook(uid).address = addr
        return key, addr

    def real_status(self, uid: str) -> dict:
        rc, rb = self.rcfg(uid), self.real.get(uid)
        k = self._keys.get(uid)
        return {"permitido": self.real_allowed, "chave": bool(k and k[0]),
                "endereco": (k[1] if k else None) or (rb.address if rb else None),
                "ligada": bool(rc.get("real_on")), "desde": rc.get("on_since"), "saldo": rb.balance if rb else None}

    def _real_price(self, uid: str, rb, token: str, px: float, t: float) -> None:
        rc, cf = self.rcfg(uid), self.book(uid).cfg
        for p in list(rb.pos.values()):
            if p["token"] != token or px <= 0:
                continue
            p["px_now"], p["px_t"] = px, t
            _, pct = rb.pnl_now(p, rc["real_slip_pct"])
            p["best_pct"], p["worst_pct"] = max(p.get("best_pct", 0), pct), min(p.get("worst_pct", 0), pct)
            rb.dirty_pos.add(p["id"])
            if cf["stop_pct"] and pct <= -cf["stop_pct"] and (p.get("sell_retry_at") or 0) <= time.time():
                p["retry_frac"] = 1.0
                self._spawn(self._real_sell(uid, p, 1.0, f"stop de {cf['stop_pct']:.0f}%"))

    def real_why_not(self, uid: str, tr: dict, rb, rc: dict) -> str | None:
        q = self.quotes.get(tr["token"])
        if not self.real_allowed:
            return "trava geral do servidor fechada (PUMP_REAL_ALLOWED)"
        if q is None or q == "?":
            return "moeda do token ainda desconhecida"
        if q != ZERO and q not in STABLES:
            return "token cotado em moeda que não é BNB nem dólar"
        if q in STABLES and not self.bnb_usd:
            return "sem a cotação BNB/dólar"
        if tr["token"] in self.graduated:
            return "o token já foi para a PancakeSwap"
        if any(p["wallet"] == tr["wallet"] and p["token"] == tr["token"] for p in rb.pos.values()) or (tr["wallet"], tr["token"]) in rb.busy:
            return "já tem a posição REAL deste trader neste token"
        if len(rb.pos) + len(rb.busy) >= rc["real_max_abertas"]:
            return f"limite de {rc['real_max_abertas']} posições REAL abertas"
        lost = rb.lost_today(time.time())
        if lost >= rc["real_perda_dia"]:
            return f"perda do dia ({lost:.4f} BNB) chegou ao limite de {rc['real_perda_dia']:g} BNB: volta amanhã (00:00 UTC)"
        if rb.balance is not None and rb.balance < rc["real_bnb_por_compra"] + bnbreal.GAS_RESERVE:
            return f"saldo da carteira ({rb.balance:.4f} BNB) menor que a compra + {bnbreal.GAS_RESERVE} BNB de gás"
        return None

    async def _real_buy(self, uid: str, tr: dict, px: float | None) -> None:
        rb, rc = self.rbook(uid), self.rcfg(uid)
        now = time.time()
        key, addr = await self.get_key(uid)
        why = "sem a chave da carteira BNB" if not key else self.real_why_not(uid, tr, rb, rc)
        sv = self.safe.cached(tr["token"])
        if not why and not (sv and sv["ok"]):                       # 0.32.177: a REAL nunca compra token sem conferência boa
            why = "token sem conferência de segurança aprovada" + (": " + sv["why"] if sv and sv.get("why") else "")
        if why:
            rb.ev(now, tr["wallet"], tr["token"], "REAL não copiou", why)
            return
        k = (tr["wallet"], tr["token"])
        rb.busy.add(k)
        try:
            async with rb.lock:
                if rb.balance is None or time.time() - rb.balance_t > 30:
                    rb.balance, rb.balance_t = await self.chain.balance(addr) / 1e18, time.time()
                if rb.balance < rc["real_bnb_por_compra"] + bnbreal.GAS_RESERVE:
                    rb.ev(now, tr["wallet"], tr["token"], "REAL não copiou",
                          f"saldo da carteira ({rb.balance:.4f} BNB) menor que a compra + gás")
                    return
                res = await self.chain.buy(key, addr, tr["token"], self.quotes.get(tr["token"]) or ZERO, rc["real_bnb_por_compra"],
                                           self.bnb_usd, rc["real_slip_pct"], rc["real_gwei"])
            t = time.time()
            p = bnbreal.new_position(tr, res, t, px, self.quotes.get(tr["token"]) or ZERO)
            rb.pos[p["id"]] = p
            rb.dirty_pos.add(p["id"])
            rb.balance_t = 0
            rb.ev(t, tr["wallet"], tr["token"], "REAL comprou", f"{rc['real_bnb_por_compra']:g} BNB, {t - tr['t']:.0f} s depois do trader", res["tx"])
            log.info("BNB REAL: comprou %s… %.4f BNB (conta %s…)", tr["token"][:10], res["bnb"], uid[:8])
        except Exception as e:
            rb.ev(time.time(), tr["wallet"], tr["token"], "REAL falhou", str(e)[:200])
            log.warning("BNB REAL: compra falhou (%s…): %s", tr["token"][:10], str(e)[:160])
        finally:
            rb.busy.discard(k)
            await self.flush_books()

    async def _real_sell(self, uid: str, p: dict, frac: float, motivo: str, manual: bool = False) -> dict | None:
        rb, rc = self.rbook(uid), self.rcfg(uid)
        if p.get("selling") or p["id"] not in rb.pos:
            return None
        if not manual and (p.get("sell_retry_at") or 0) > time.time():
            return None
        p["selling"] = True
        frac = 1.0 if frac >= 0.95 else max(0.0, frac)
        try:
            key, addr = await self.get_key(uid)
            if not key:
                raise bnbreal.ChainError("sem a chave da carteira BNB: cole a chave em Configurações para vender")
            left = int(p["raw_left"])
            raw = left if frac >= 1 else int(left * frac)
            async with rb.lock:
                try:
                    res = await self.chain.sell(key, addr, p["token"], p.get("quote") or ZERO, raw, p["token"] in self.graduated,
                                                rc["real_slip_pct"], rc["real_gwei"])
                except bnbreal.ChainError as e:
                    if "não tem mais" in str(e):
                        p["tokens_left"], p["raw_left"] = 0.0, "0"
                        tr = rb.close(p, time.time(), "a carteira não tem mais o token (vendido fora do sistema?)", p.get("px_now"))
                        rb.ev(time.time(), p["wallet"], p["token"], "REAL fechou", tr["motivo"])
                        return tr
                    raise
            t = time.time()
            p["raw_left"] = str(max(0, left - raw))
            p["tokens_left"] = max(0.0, p["tokens_left"] - raw / 1e18)
            p["proceeds"] += res["bnb"]
            p["fees"] = p.get("fees", 0) + res.get("gas", 0)
            p["tx_last"] = res["tx"]
            for k in ("sell_error", "sell_retry_at", "retry_frac"):
                p.pop(k, None)
            rb.balance_t = 0
            if int(p["raw_left"]) > 0 and frac < 1:
                p.setdefault("vendas", []).append({"t": t, "frac": round(frac, 4), "bnb": round(res["bnb"], 6), "motivo": motivo, "tx": res["tx"]})
                rb.dirty_pos.add(p["id"])
                rb.ev(t, p["wallet"], p["token"], "REAL vendeu parte", f"{frac * 100:.0f}% · {motivo}", res["tx"])
                return None
            tr = rb.close(p, t, motivo, p.get("px_now"))
            rb.ev(t, p["wallet"], p["token"], "REAL fechou", f"{motivo} · {tr['pnl_bnb']:+.4f} BNB", res["tx"])
            return tr
        except Exception as e:
            p["sell_error"] = str(e)[:200]
            p["sell_retry_at"] = time.time() + bnbreal.RETRY_S
            p.setdefault("retry_frac", frac)
            rb.dirty_pos.add(p["id"])
            rb.ev(time.time(), p["wallet"], p["token"], "REAL falhou ao vender", str(e)[:200])
            log.warning("BNB REAL: venda falhou (%s…): %s", p["token"][:10], str(e)[:160])
            if manual:
                raise
            return None
        finally:
            p["selling"] = False
            await self.flush_books()

    async def real_tick(self) -> None:
        """Tempo máximo das posições REAL, nova tentativa das vendas que falharam e saldo da carteira (a cada 30 s)."""
        now = time.time()
        bal = now - self._rbal_at > 30
        if bal:
            self._rbal_at = now
        for uid, rb in list(self.real.items()):
            cf = self.book(uid).cfg
            for p in list(rb.pos.values()):
                if now - p["open_t"] >= cf["max_hold_h"] * 3600:
                    p["retry_frac"] = 1.0
                    self._spawn(self._real_sell(uid, p, 1.0, f"tempo máximo de {cf['max_hold_h']:g} h"))
                elif p.get("sell_error") and (p.get("sell_retry_at") or 0) <= now and p.get("retry_frac"):
                    self._spawn(self._real_sell(uid, p, p["retry_frac"], "nova tentativa de venda"))
            if bal and (rb.address or self.rcfg(uid).get("real_on")):
                _, addr = await self.get_key(uid)
                if addr:
                    try:
                        rb.balance, rb.balance_t = await self.chain.balance(addr) / 1e18, now
                    except Exception:
                        pass

    async def set_key(self, uid: str, value: str) -> str:
        key = evm.parse_key(value)
        await self.vault.save(uid, BNB_KEY_NAME, value.strip())
        self._keys.pop(uid, None)
        _, addr = await self.get_key(uid)
        return addr or evm.address_of(key)

    async def remove_key(self, uid: str) -> None:
        self.rcfg(uid)["real_on"] = False
        await self.vault.delete(uid, BNB_KEY_NAME)
        self._keys.pop(uid, None)
        rb = self.real.get(uid)
        if rb:
            rb.address, rb.balance = None, None
        self.book(uid).dirty_book = True
        await self.flush_books()

    async def set_real(self, uid: str, on: bool) -> dict:
        rc = self.rcfg(uid)
        if on:
            if not self.real_allowed:
                raise ValueError("a trava geral do servidor está fechada (PUMP_REAL_ALLOWED=false): nada é enviado")
            key, _ = await self.get_key(uid)
            if not key:
                raise ValueError("cole antes a chave privada da carteira BNB em Configurações")
            rc["real_on"], rc["on_since"] = True, time.time()
        else:
            rc["real_on"] = False
        self.book(uid).dirty_book = True
        await self.flush_books()
        return self.real_status(uid)

    async def save_real_cfg(self, uid: str, raw: dict) -> dict:
        rc = self.rcfg(uid)
        keep = {k: rc[k] for k in ("real_on", "on_since") if k in rc}
        self.real_cfg[uid] = {**bnbreal.clean(raw, rc), **keep}
        self.book(uid).dirty_book = True
        await self.flush_books()
        return self.real_cfg[uid]

    async def close_all(self, uid: str, real: bool) -> dict:
        if not real:
            b = self.book(uid)
            out = [b.sell(p, 1.0, None, time.time(), "vendido por você (vender todas)") for p in list(b.pos.values())]
            await self.flush_books()
            return {"vendidas": len([x for x in out if x]), "falhas": 0}
        rb = self.rbook(uid)
        ok = bad = 0
        for p in list(rb.pos.values()):
            try:
                if await self._real_sell(uid, p, 1.0, "vendido por você (vender todas)", manual=True):
                    ok += 1
            except Exception:
                bad += 1
        return {"vendidas": ok, "falhas": bad}

    async def positions_tick(self) -> None:
        """Tempo máximo das posições e preço dos tokens que já foram para a PancakeSwap (a Four.Meme não negocia mais)."""
        now = time.time()
        for b in self.books.values():
            b.timeouts(now)
        toks = {p["token"] for b in self.books.values() for p in b.pos.values()} | \
            {p["token"] for rb in self.real.values() for p in rb.pos.values()}
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
                    for uid, rb in list(self.real.items()):
                        self._real_price(uid, rb, tk, px, now)

    async def dex_price(self, token: str) -> float | None:
        try:
            r = await self.http.get(DEX_URL + token, timeout=10)
            pairs = [x for x in (r.json().get("pairs") or []) if x.get("chainId") == "bsc"
                     and ((x.get("quoteToken") or {}).get("address") or "").lower() == WBNB and x.get("priceNative")]
            pairs.sort(key=lambda x: float((x.get("liquidity") or {}).get("usd") or 0), reverse=True)
            return float(pairs[0]["priceNative"]) if pairs else None
        except Exception:
            return None

    def _bk(self, uid: str, peek: bool = False) -> bnbcopy.Book:
        """Carteira fictícia da conta. peek = visualização do admin: não cria nem grava nada para quem é visto."""
        if peek:
            return self.books.get(uid) or bnbcopy.Book(uid)
        return self.book(uid)

    def user_summary(self, uid: str, now: float | None = None) -> dict:
        """Resumo de uma conta para a Administração da BNB (0.32.173)."""
        now = now or time.time()
        b, rb, rc = self.books.get(uid), self.real.get(uid), self.real_cfg.get(uid) or {}
        f = None
        if b is not None:
            w = b.wallet(now)
            f = {"ligada": b.cfg["on"], "resultado": w["resultado"], "abertas": w["abertas"], "fechadas": w["fechadas"], "acerto": w["acerto"]}
        r = {"ligada": bool(rc.get("real_on")), "endereco": rb.address if rb else None, "abertas": len(rb.pos) if rb else 0,
             "fechadas": len(rb.trades) if rb else 0, "resultado": round(sum(x["pnl_bnb"] for x in rb.trades), 6) if rb else 0.0}
        return {"ficticia": f, "real": r}

    def painel(self, uid: str, now: float | None = None, real: bool = False, peek: bool = False) -> dict:
        now = now or time.time()
        if real:
            return self.painel_real(uid, now, peek)
        b = self._bk(uid, peek)
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
                "copiaria": self.ranking(now)["copiaria"], "real_cfg": self.real_cfg.get(uid) or bnbreal.clean(None), "cfg_sim": b.cfg, "real_padrao": bnbreal.REAL_DEFAULT,
                "real_status": self.real_status(uid), "leitura_ok": self.reading_ok(now),
                "seguranca": self.safe.summary(now)}

    def reading_ok(self, now: float | None = None) -> bool:
        now = now or time.time()
        return bool(self.trades) and not (self.stat["ultimo_erro_t"] and now - self.stat["ultimo_erro_t"] < 120)

    def painel_real(self, uid: str, now: float, peek: bool = False) -> dict:
        """Mesmo formato do painel fictício, com as posições e trades da carteira REAL."""
        b = self._bk(uid, peek)
        rb = (self.real.get(uid) or bnbreal.RealBook(uid)) if peek else self.rbook(uid)
        rc = (self.real_cfg.get(uid) or bnbreal.clean(None)) if peek else self.rcfg(uid)
        pos = []
        for p in sorted(rb.pos.values(), key=lambda x: x["open_t"], reverse=True):
            v, pct = rb.pnl_now(p, rc["real_slip_pct"])
            pos.append({**{k: p.get(k) for k in ("id", "wallet", "token", "open_t", "px_in", "px_now", "px_t", "bnb_in", "proceeds",
                                                  "best_pct", "worst_pct", "lag_s", "tx_in", "vendas", "aba", "sell_error", "selling")},
                        "pnl_bnb": round(v, 6), "pnl_pct": round(pct, 2), "graduou": p["token"] in self.graduated,
                        "fecha_em": p["open_t"] + b.cfg["max_hold_h"] * 3600, "real": True})
        cfg = {**b.cfg, "on": bool(rc.get("real_on")), "bnb_por_compra": rc["real_bnb_por_compra"],
               "max_abertas": rc["real_max_abertas"], "slip_pct": rc["real_slip_pct"]}
        return {"real": True, "cfg": cfg, "padrao": bnbcopy.CFG_DEFAULT, "carteira": rb.wallet(now, rc["real_slip_pct"], bnbcopy.periods),
                "posicoes": pos, "trades": rb.trades[:500], "eventos": rb.events[:100], "semana": bnbcopy.week_split(rb.trades),
                "abas": [{"aba": "top", "nome": "Top traders BNB", "ligada": bool(rc.get("real_on")), "abertas": len(rb.pos),
                          "fechadas": len(rb.trades), "periodos": bnbcopy.periods(rb.trades, now),
                          "resultado": round(sum(x["pnl_bnb"] for x in rb.trades), 6)}],
                "copiaria": self.ranking(now)["copiaria"], "real_cfg": rc, "cfg_sim": b.cfg, "real_padrao": bnbreal.REAL_DEFAULT,
                "real_status": self.real_status(uid), "leitura_ok": self.reading_ok(now),
                "seguranca": self.safe.summary(now)}

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

    async def close_real(self, uid: str, pid: str) -> dict | None:
        p = self.rbook(uid).pos.get(pid)
        return await self._real_sell(uid, p, 1.0, "vendido por você", manual=True) if p else None

    async def flush_books(self) -> None:
        if self.db is None:
            for b in list(self.books.values()) + list(self.real.values()):
                b.dirty_pos.clear()
                b.closed_pos.clear()
                b.new_trades.clear()
                if hasattr(b, "dirty_book"):
                    b.dirty_book = False
            return
        for b in list(self.books.values()):
            try:
                if b.dirty_book:
                    await self.db.insert("bnb_books", {"user_id": b.user_id, "cfg": {**b.cfg, "real": self.rcfg(b.user_id)},
                                                       "cash": b.cash}, upsert=True, on_conflict="user_id")
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
        for rb in list(self.real.values()):
            try:
                if rb.new_trades:
                    rows = [{"id": x["id"], "user_id": rb.user_id, "t": x["close_t"], "data": x} for x in rb.new_trades]
                    await self.db.insert("bnb_trades", rows, upsert=True, on_conflict="id")
                    rb.new_trades.clear()
                for pid in list(rb.closed_pos):
                    await self.db.delete("bnb_positions", {"id": pid, "user_id": rb.user_id})
                    rb.closed_pos.discard(pid)
                ids = set(rb.dirty_pos)                    # compra que chega durante a gravação fica para a próxima
                rows = [{"id": pid, "user_id": rb.user_id, "data": {k: v for k, v in rb.pos[pid].items() if k != "selling"}}
                        for pid in ids if pid in rb.pos]
                if rows:
                    await self.db.insert("bnb_positions", rows, upsert=True, on_conflict="id")
                rb.dirty_pos -= ids
            except Exception as e:
                log.warning("BNB: carteira REAL não gravou: %s", str(e)[:160])

    async def load_books(self) -> None:
        for r in await self.db.select("bnb_books", None) or []:
            b = self.books[r["user_id"]] = bnbcopy.Book(r["user_id"], r.get("cfg"), r.get("cash"))
            b.dirty_book = False
            rc = (r.get("cfg") or {}).get("real")
            if isinstance(rc, dict):
                self.real_cfg[r["user_id"]] = {**bnbreal.clean(rc, rc), **{k: rc[k] for k in ("real_on", "on_since") if k in rc}}
        for r in await self.db.select("bnb_positions", None) or []:
            d = r.get("data")
            if not isinstance(d, dict) or not r.get("user_id"):
                continue
            if d.get("real"):
                self.rbook(r["user_id"]).pos[r["id"]] = d
            elif r["user_id"] in self.books:
                self.books[r["user_id"]].pos[r["id"]] = d
        for r in await self.db.select("bnb_trades", None, order="t.desc", limit=20000) or []:
            d = r.get("data")
            if not isinstance(d, dict):
                continue
            b = self.rbook(r["user_id"]) if d.get("real") and r.get("user_id") else self.books.get(r.get("user_id"))
            if b is not None and len(b.trades) < bnbcopy.KEEP_TRADES:
                b.trades.append(d)

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
                elif r.get("k") == "hist":
                    self.hist.restore(r.get("v"))
                elif r.get("k") == "pairs" and isinstance(r.get("v"), dict):
                    self.pairs = {k: v for k, v in r["v"].items() if isinstance(v, dict) and v.get("pair")}
                    self.graduated.update(self.pairs)
            since = time.time() - KEEP_S
            off = 0
            while True:
                rows = await self.db.select("bnb_fm_trades", None, order="t.asc", limit=5000, offset=off,
                                            gte={"t": since}) or []
                for r in rows:
                    self._add({k: r.get(k) for k in ("id", "tx", "block", "token", "wallet", "side", "price", "amount",
                                                     "value", "fee", "t", "quote", "venue")})
                off += len(rows)
                if len(rows) < 5000 or off >= MAX_MEM:
                    break
            self.stat["carregados"] = off
            await self.load_books()
        except Exception as e:
            log.warning("BNB: dados guardados não carregaram: %s", str(e)[:160])
        self.loaded = True

    async def _flush_rows(self, rows: list[dict]) -> bool:
        try:
            await self.db.insert("bnb_fm_trades", [{**{k: r.get(k) for k in ("id", "tx", "block", "token", "wallet", "side",
                                                                            "price", "amount", "value", "fee", "t", "quote")},
                                                   "venue": r.get("venue") or "fourmeme"} for r in rows], upsert=True, on_conflict="id")
            return True
        except Exception as e:
            self.pending = rows + self.pending                 # não perde: tenta de novo na próxima
            log.warning("BNB: não gravou %d trades: %s", len(rows), str(e)[:160])
            return False

    async def flush(self) -> None:
        if self.db is None:
            self.pending.clear()
            return
        for _ in range(20 if len(self.pending) > 1000 else 1):   # 0.32.179: o histórico grava em lotes
            rows, self.pending = self.pending[:1000], self.pending[1000:]
            if not rows or not await self._flush_rows(rows):
                break
        try:
            if self._pairs_dirty:
                self._pairs_dirty = False
                await self.db.insert("bnb_state", {"k": "pairs", "v": self.pairs}, upsert=True, on_conflict="k")
            if self.cursor:
                await self.db.insert("bnb_state", {"k": "cursor", "v": {"block": self.cursor, "t": time.time()}},
                                     upsert=True, on_conflict="k")
        except Exception as e:
            log.warning("BNB: não gravou o estado: %s", str(e)[:160])
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
        self._spawn(self.hist.run())                       # 0.32.179: histórico pela NodeReal (espera a chave)
        while True:
            # 0.32.183 (monitor parado em 04/11, sem erro): cada etapa tem prazo; se uma travar, vira erro e a volta segue
            steps = [("leitura", self.poll, STEP_MAX_S), ("preço do BNB", self.refresh_bnb_usd, 60),
                     ("saldos", lambda: self.balances_tick([r["wallet"] for r in self.ranking()["rows"][:30]]), 60),
                     ("posições", self.positions_tick, 60), ("graduados", self.grad_tick, 60), ("carteira REAL", self.real_tick, 60)]
            if time.time() - self._flush_at > 30:
                self._flush_at = time.time()
                steps += [("gravação", self.flush, 120), ("gravação das carteiras", self.flush_books, 120)]
            for nome, fn, lim in steps:
                self.etapa = nome
                try:
                    await asyncio.wait_for(fn(), lim)
                except asyncio.TimeoutError:
                    self._erro(f"{nome}: passou de {lim:.0f} s e foi interrompida")
                except Exception as e:
                    self._erro(f"{nome}: {str(e)[:180]}")
            self.etapa, self.volta_t = None, time.time()
            await asyncio.sleep(POLL_S)

    def _erro(self, msg: str) -> None:
        self.stat["erros"] += 1
        self.stat["ultimo_erro"], self.stat["ultimo_erro_t"] = msg[:200], time.time()
        log.warning("BNB: %s", msg[:200])

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
            recent.append({**{k: t.get(k) for k in ("t", "tx", "token", "wallet", "side", "amount", "venue")},
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
                           "bloco_s": self.block_s, "volta_t": self.volta_t, "etapa": self.etapa,
                           "pancake_pausa_s": max(0, round(self._pk_off_until - now)) or None},
                "ranking": rk, "recentes": recent,
                "historico": self.hist.status(),
                "pancake": {**self.pstat, "pares": len(self.pairs), "lendo": len(self._active_pairs()),
                            "tokens": bnbpancake.graduated_list(self.trades, self.pairs, now, to_bnb, self.quotes, self.bnb_usd)[:60]}}
