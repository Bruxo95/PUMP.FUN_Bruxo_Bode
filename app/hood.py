"""Robinhood Chain (etapa 1, 0.32.208): só LÊ a rede e monta o ranking próprio dos traders de memecoin. Não copia nada.

Pedido do dono em 04/11/2026: mais um projeto como o da BNB, para a Robinhood Chain, TUDO ISOLADO (módulo, rota, página,
tabelas hood_* e configuração próprios; nada do motor da Solana nem da BNB é usado ou alterado).

Como lê (conferido na rede em 04/11/2026, RPC grátis oficial rpc.mainnet.chain.robinhood.com, chain id 4663 = 0x1237):
- A Robinhood Chain é uma camada 2 do Ethereum (Arbitrum Orbit), gás em ETH, ~10 blocos por segundo (600 blocos = 60 s).
- Os memecoins negociam quase todos em pools da Uniswap V4 (DexScreener: JOHN, CASHCAT, HOOKR, STONKBROKER, BONER…).
  Os launchpads (hood.fun, Clanker e outros; os nomes não foram confirmados na rede) criam o pool direto na V4, então
  não existe um contrato de curva só, como o TokenManager2 da Four.Meme. Toda troca V4 passa pelo PoolManager
  (0x8366…0951): ~470 trocas por minuto e ~3 pools novos por minuto (medido).
- O evento Swap da V4 só traz o id do pool e o roteador que chamou (não o trader). Procurar a criação de cada pool custa
  caro (o RPC aceita no máximo 10 milhões de blocos por consulta e a rede já tem mais de 100 milhões). Por isso a moeda e
  o trader saem das TRANSFERÊNCIAS de token na mesma transação: o memecoin é o token que entra ou sai do PoolManager e
  não é WETH nem USDG; o outro lado é WETH (18 casas), USDG (dólar, 6 casas) ou ETH nativo (sem transferência; o valor
  vem do Swap). O trader é quem recebe ou envia o memecoin; quando é o roteador, segue a transferência roteador ↔ carteira.
- O RPC grátis devolve "429 Too Many Requests" com muitas consultas seguidas: aqui são 3 eth_getLogs por volta (trocas,
  transferências saindo e entrando no PoolManager/roteadores), nunca uma consulta por transação.

Etapa 2 (0.32.279, pedido do dono em 10/11/2026: "faz 1 a 4"): a cópia (hoodcopy) recebe cada trade novo, a leitura das trocas
também traz o evento Initialize dos pools novos (mesma consulta, filtro OU) para a cópia ter a chave do pool, e cada trade guarda a
taxa do pool (último campo do Swap) e o preço do token (ETH ÷ quantidade).

Limites desta etapa: transações com mais de uma troca (rotas com vários pools) ficam de fora; o ranking guarda só as
últimas 24 h na memória (a rede tem ~100× o volume da Four.Meme e o banco não aguentaria cada trade); depois de reiniciar,
relê no máximo 30 min da rede. O banco guarda só o ponto da leitura e a regra do ranking (tabela hood_state).
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import Counter, deque

log = logging.getLogger("hood")

CHAIN_ID = 4663
PM = "0x8366a39cc670b4001a1121b8f6a443a643e40951"                                  # Uniswap V4 PoolManager
T_SWAP = "0x40e9cecb9f5f1f1c5b9c97dec2917b7ee92e57ba5563708daca94dd84ad7112f"   # Swap(bytes32,address,int128,int128,uint160,uint128,int24,uint24)
T_INIT = "0xdd466e674ea557f56295e2d0218a125ea4b4f0f6f3307b95f85e6110838d6438"
# 0.32.327: ModifyLiquidity(bytes32,address,int24,int24,int256,bytes32), lido na mesma consulta das trocas (sem consulta a mais)
T_ML = "0xf208f4912782fd25c7f114ca3723a2d5dd6f3bcc3ac8db5af63baa85f711d5ec"    # Initialize(bytes32,address,address,uint24,int24,address,uint160,int24)
T_TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"  # Transfer(address,address,uint256)
WETH = "0x0bd7d308f8e1639fab988df18a8011f41eacad73"                                # 18 casas (conferido na rede)
USDG = "0x5fc5360d0400a0fd4f2af552add042d716f1d168"                                # dólar, 6 casas (conferido na rede)
MAJORS = {WETH: ("ETH", 18), USDG: ("USD", 6)}
ZERO = "0x" + "0" * 40
DEX_URL = "https://api.dexscreener.com/tokens/v1/robinhood/"
EXPLORER = "https://robinhoodchain.blockscout.com"

# 0.32.283 (dono, 10/11/2026: leitura 231 s atrasada com um RPC só): revezamento entre os RPC grátis que aceitam eth_getLogs.
# Testados em 10/11 com a consulta do robô (trocas da V4 em 300 blocos, 9 seguidas): daybreak 0,14 s, oficial 0,25 s, blockreq
# 0,38 s, todos 9/9. publicnode (403), dRPC (400), blockvectra (máx. 100 blocos) e ordofi (fora do ar) recusaram.
# O 429 de um RPC agora pausa só ele por 1 min; a leitura para só se todos pedirem para esperar.
OFFICIAL = "https://rpc.mainnet.chain.robinhood.com"
RPCS = [u.strip() for u in os.environ.get("HOOD_RPCS", "https://robinhood.daybreak-rpc.network," + OFFICIAL +
                                          ",https://robinhood-mainnet-rpc.blockreq.com/v1/rpc/public").split(",") if u.strip()]
HEAD_MARGIN = 30          # blocos (~3 s): cada RPC pode estar um pouco atrás; nunca pede um bloco que ele talvez ainda não tenha
RPC_PAUSE_S = 60
# 0.32.290 (dono, 11/11: "erro na leitura · sem trade há mais de 10 min · leitura atrasada; resolver de uma vez"): RPC que demora ou falha
# também descansa (antes só o 429 pausava). Com 20 s de espera e sem pausa, um RPC travado comia o tempo da volta inteira, que caía no
# limite de 90 s, e a leitura ficava para trás. Cada consulta espera no máximo RPC_TIMEOUT_S; 2 falhas seguidas = 1 min de descanso.
RPC_TIMEOUT_S = 8
RPC_FAILS = 2
SPAN = 300                # blocos por consulta (~30 s). O RPC aceita 10 milhões, mas o 429 vem pelo tamanho das respostas
POLL_S = 10.0             # 3 consultas por volta: ~18 por minuto (o RPC grátis devolve 429 com rajadas)
BLOCK_S = 0.1             # medido em 04/11/2026: 600 blocos em 59–60 s; corrigido sozinho a cada leitura
KEEP_S = 24 * 3600        # memória do ranking (etapa 1)
CATCHUP_S = 1800          # depois de reiniciar, relê no máximo 30 min (mais que isso pula para 10 min atrás)
MAX_MEM = 400_000
# 0.32.282 (pedido do dono, 10/11/2026: o ranking zerava a cada atualização do site): os trades lidos vão para o Postgres da VPS
# (arquivo, tabela genérica; são dados públicos da rede) e voltam para a memória quando o servidor sobe. Lá ficam ARQ_KEEP_S.
ARQ = {"tabela": "hood_rede", "pk": "id", "t": "t", "tipo": "epoch"}
ARQ_FIELDS = ("id", "tx", "block", "token", "wallet", "side", "amount", "eth", "quote", "pool", "fee", "t")
ARQ_KEEP_S = 2 * 86400
ARQ_PEND_MAX = 50_000
ROUTERS_MAX = 25          # roteadores (quem chama o PoolManager) seguidos para achar a carteira de verdade

# Mesma regra do Top traders (pumpfun.refresh_followed/_lb_judge), com valores próprios desta rede.
# 0.32.322 (revisão "por que estamos sempre no negativo", 11/11/2026): o ranking premiava quem vende os ganhadores e fica com os
# perdedores na carteira (só o que foi vendido contava) e aceitava 3 tokens fechados e até 400 trades por dia. Agora o token
# que o trader ainda segura valendo menos da metade do que custou (BAG_LOSS) conta como perda fechada e desconta do lucro; padrão
# de 5 tokens fechados e robô acima de 150 trades por dia. "v" marca a regra já ajustada (quem estava no padrão antigo muda uma vez).
CFG_DEFAULT = {"days": 1, "min_trades": 20, "min_winrate": 50.0, "min_closed": 5, "min_wallet_usd": 1000.0,
               "online_min": 10.0, "top_n": 10, "bot_per_day": 150, "v": 2}
CFG_LIMITS = {"days": (1, 1), "min_trades": (0, 100000), "min_winrate": (0, 100), "min_closed": (1, 1000),
              "min_wallet_usd": (0, 10_000_000), "online_min": (1, 1440), "top_n": (1, 50), "bot_per_day": (10, 100000), "v": (2, 2)}
CFG_OLD = {"min_closed": 3, "bot_per_day": 400}
BAG_LOSS = 0.5


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


def _hex(h) -> int:
    """Número hexa da rede; vazio ("0x", None) ou lixo vale 0. 0.32.291: um Transfer de NFT (ERC-721, data "0x") no bloco
    111.488.593 derrubava a janela inteira com "invalid literal for int() with base 16: '0x'" e a leitura parou ali."""
    try:
        return int(h, 16) if isinstance(h, str) and len(h) > 2 else 0
    except ValueError:
        return 0


def _s(h: str) -> int:
    v = _hex(h if (h or "").startswith("0x") else "0x" + (h or ""))
    return v - (1 << 256) if v >= 1 << 255 else v


def _topic_addr(t: str) -> str:
    return "0x" + (t or "")[-40:].lower()


def legs_of(transfers: list[dict]) -> dict[str, list[tuple]]:
    """Transferências agrupadas por transação: (token, de, para, quantidade)."""
    by: dict[str, list[tuple]] = {}
    for x in transfers:
        tp = x.get("topics") or []
        if len(tp) != 3 or (tp[0] or "").lower() != T_TRANSFER:      # 4 tópicos = NFT (ERC-721): não é moeda
            continue
        by.setdefault(x.get("transactionHash"), []).append(
            ((x.get("address") or "").lower(), _topic_addr(tp[1]), _topic_addr(tp[2]), _hex(x.get("data"))))
    return by


def decode(swap: dict, legs: list[tuple], n_swaps: int, eth_usd: float | None) -> dict | None:
    """Uma troca da V4 + as transferências da mesma transação → trade do memecoin (ETH gasto/recebido). None = fora."""
    if n_swaps != 1:
        return None                                       # rota com várias trocas: fora nesta etapa
    d = swap.get("data") or ""
    if len(d) < 2 + 64 * 2:
        return None
    a0, a1 = abs(_s(d[2:66])), abs(_s(d[66:130]))
    router = _topic_addr((swap.get("topics") or ["", "", ""])[2])
    pm_legs = [lg for lg in legs if PM in (lg[1], lg[2])]
    memes = {lg[0] for lg in pm_legs if lg[0] not in MAJORS}
    if len(memes) != 1:
        return None
    meme = memes.pop()
    mine = [lg for lg in pm_legs if lg[0] == meme]
    out = [lg for lg in mine if lg[1] == PM]              # o pool entregou o memecoin = compra
    inn = [lg for lg in mine if lg[2] == PM]              # o memecoin entrou no pool = venda
    if out and not inn:
        side, main = "buy", max(out, key=lambda x: x[3])
        amount, who = sum(x[3] for x in out), main[2]
    elif inn and not out:
        side, main = "sell", max(inn, key=lambda x: x[3])
        amount, who = sum(x[3] for x in inn), main[1]
    else:
        return None
    # o outro lado: WETH ou USDG passando pelo pool; sem eles, ETH nativo (valor do Swap que não é o do memecoin)
    q = [lg for lg in pm_legs if lg[0] in MAJORS]
    if q:
        tok = max(q, key=lambda x: x[3])
        nm, dec = MAJORS[tok[0]]
        v = tok[3] / 10 ** dec
        if nm == "USD":
            if not eth_usd:
                return None
            v /= eth_usd
        quote = nm
    else:
        other = a1 if abs(a0 - amount) <= abs(a1 - amount) else a0
        v, quote = other / 1e18, "ETH"
    if v <= 0 or amount <= 0:
        return None
    # o trader de verdade: se quem recebeu/enviou é o roteador, segue a transferência roteador ↔ carteira
    if who == router or who == PM:
        hop = [lg for lg in legs if lg[0] == meme and (lg[1] == who if side == "buy" else lg[2] == who) and PM not in (lg[1], lg[2])]
        if not hop:
            return None
        h = max(hop, key=lambda x: x[3])
        who = h[2] if side == "buy" else h[1]
    if who in (ZERO, PM, router):
        return None
    return {"id": f"{swap.get('transactionHash')}:{_hex(swap.get('logIndex'))}", "tx": swap.get("transactionHash"),
            "block": _hex(swap.get("blockNumber")), "token": meme, "wallet": who, "side": side,
            "amount": amount / 1e18, "eth": round(v, 9), "quote": quote, "pool": (swap.get("topics") or ["", ""])[1],
            "fee": int(d[2 + 64 * 5:2 + 64 * 6], 16) if len(d) >= 2 + 64 * 6 else None}


def rank(trades, now: float, cfg: dict, balances: dict, px: dict | None = None) -> dict:
    """Ranking próprio pela regra do Top traders: os que mais lucraram no período (lucro realizado, em ETH); apto = trades
    mínimos, acerto acima do mínimo (tokens fechados com lucro), carteira com saldo mínimo, sem robô; copiaria os N
    melhores aptos que negociaram nos últimos X minutos. A proporção vendida usa a quantidade de token (as casas se cancelam).
    px = token → (preço em ETH, hora): com ele, o que o trader ainda segura no prejuízo fundo entra na conta (0.32.322)."""
    cfg = clean_cfg(cfg)
    since = now - cfg["days"] * 86400
    W: dict[str, dict] = {}
    for t in trades:
        if t["t"] < since:
            continue
        w = W.setdefault(t["wallet"], {"n": 0, "tk": {}, "first": t["t"], "last": t["t"], "vol": 0.0})
        w["n"] += 1
        w["first"], w["last"] = min(w["first"], t["t"]), max(w["last"], t["t"])
        w["vol"] += t["eth"]
        k = w["tk"].setdefault(t["token"], {"buy": 0.0, "sell": 0.0, "got": 0.0, "out": 0.0})
        if t["side"] == "buy":
            k["buy"] += t["eth"]
            k["got"] += t["amount"]
        else:
            k["sell"] += t["eth"]
            k["out"] += t["amount"]
    rows = []
    for wal, w in W.items():
        realized, win, closed, opened, bag, bags = 0.0, 0, 0, 0, 0.0, 0
        for tk, k in w["tk"].items():
            if k["got"] <= 0:
                continue                                   # vendeu o que comprou antes da janela: sem custo conhecido
            frac = min(1.0, k["out"] / k["got"])
            if frac > 0:
                realized += k["sell"] - k["buy"] * frac
            if frac >= 0.9:
                closed += 1
                win += 1 if k["sell"] > k["buy"] * frac else 0
                continue
            custo = k["buy"] * (1 - frac)
            p = (px or {}).get(tk)
            vale = (k["got"] - k["out"]) * p[0] if p and p[0] is not None else None
            if vale is not None and custo > 0 and vale < custo * BAG_LOSS:
                closed += 1                                # segura um token que já perdeu mais da metade: perda, mesmo sem vender
                bags += 1
                bag += vale - custo
            else:
                opened += 1
        span_d = max(1.0, (w["last"] - w["first"]) / 86400)
        rows.append({"wallet": wal, "trades": w["n"], "realized_eth": round(realized + bag, 6), "vendido_eth": round(realized, 6),
                     "bag_eth": round(bag, 6), "bags": bags, "vol_eth": round(w["vol"], 4),
                     "tokens": len(w["tk"]), "closed": closed, "open": opened,
                     "winrate": round(100 * win / closed, 1) if closed else None, "last_t": w["last"],
                     "per_day": round(w["n"] / span_d, 1)})
    rows.sort(key=lambda r: r["realized_eth"], reverse=True)
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
        if bal and bal.get("contrato"):
            flags.append("é um contrato (robô), não uma pessoa: costuma negociar em pools que só ele consegue vender")
        r["contrato"] = bool(bal and bal.get("contrato"))
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
    return {"rows": top, "copiaria": chosen, "carteiras": len(rows),
            "aptos": sum(1 for r in top if r["eligible"]), "aptos_online": sum(1 for r in top if r["eligible"] and r["online"])}


class RpcError(Exception):
    pass


class _RpcBad(RpcError):
    """Erro do próprio RPC (não do contrato chamado)."""


class HoodWatch:
    """Leitura da Robinhood Chain num laço próprio. db pode ser None (sem guardar)."""

    def __init__(self, http, db=None, rpcs: list[str] | None = None):
        self.http, self.db = http, db
        self.rpcs = list(rpcs or RPCS)
        self.rpc_i = 0
        self.official = OFFICIAL
        self._rpc_off: dict[str, float] = {}
        self._rpc_fail: dict[str, int] = {}
        self.span = SPAN
        self.trades: deque = deque(maxlen=MAX_MEM)
        self.seen: set = set()
        self.routers: Counter = Counter()
        self.balances: dict[str, dict] = {}
        self.eth_usd: float | None = None
        self._eth_at = 0.0
        self.cfg = dict(CFG_DEFAULT)
        self.cursor: int | None = None
        self.head: int | None = None
        self.head_t: float | None = None
        self.block_s = BLOCK_S
        self._ts_at = 0.0
        self.stat = {"polls": 0, "trocas": 0, "trades": 0, "fora_rota": 0, "fora_outro": 0, "erros": 0, "ultimo_erro": None,
                     "ultimo_erro_t": None, "rpc": None, "desde": time.time(), "chamadas": 0, "limite_429": 0,
                     "volta_t": None, "por_rpc": {}}
        self._save_at = 0.0
        self._pause_until = 0.0
        self._bal_q: deque = deque()
        self._rank_cache: tuple[float, dict] | None = None
        self.loaded = False
        self.px: dict[str, tuple[float, float]] = {}      # token → (preço em ETH, hora): última troca vista ou cotação da cópia
        self.hold: dict[tuple, float] = {}                # (carteira, token) → quantidade vista (para vender a mesma parte)
        self.arquivo = None                               # main.py liga (hub.arquivo); sem ele, o ranking volta a zerar no reinício
        self._arq_pend: list[dict] = []
        self._arq_trim_at = 0.0
        self._name_try: dict[str, float] = {}
        self._danger: tuple[float, dict] | None = None
        self._flow_scanning = False
        self._scan_at: dict[str, float] = {}
        self.stat.update(salvos=0, do_arquivo=0, arquivo_erro=None)
        from .hoodcopy import Copier
        self.copier = Copier(self, http, db)

    # ------------------------------------------------------------------ RPC
    def next_rpc(self) -> str | None:
        """Próximo RPC do revezamento que não está pausado."""
        now = time.time()
        for k in range(len(self.rpcs)):
            url = self.rpcs[(self.rpc_i + k) % len(self.rpcs)]
            if self._rpc_off.get(url, 0) <= now:
                self.rpc_i = (self.rpc_i + k + 1) % len(self.rpcs)
                return url
        return None

    async def rpc(self, method: str, params: list, url: str | None = None):
        """Consulta no RPC pedido (url) ou no próximo do revezamento; se falhar, tenta os outros que não estão pausados."""
        last = None
        now = time.time()
        order = ([url] if url else []) + [u for u in self.rpcs[self.rpc_i:] + self.rpcs[:self.rpc_i] if u != url]
        if not url:
            self.rpc_i = (self.rpc_i + 1) % len(self.rpcs)
        for url in order:
            if self._rpc_off.get(url, 0) > now:
                continue
            try:
                self.stat["chamadas"] += 1
                self.stat["por_rpc"][url.split("//")[-1].split("/")[0]] = self.stat["por_rpc"].get(url.split("//")[-1].split("/")[0], 0) + 1
                r = await self.http.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                                         headers={"User-Agent": "pump-fun-copy/1.0"}, timeout=RPC_TIMEOUT_S)
                if r.status_code == 429:
                    self.stat["limite_429"] += 1
                    self._rpc_off[url] = time.time() + RPC_PAUSE_S    # só este RPC descansa 1 min; os outros seguem
                    if all(self._rpc_off.get(u, 0) > time.time() for u in self.rpcs):
                        self._pause_until = min(self._rpc_off[u] for u in self.rpcs)
                    raise _RpcBad("429 Too Many Requests (o RPC grátis pediu para esperar)")
                if r.status_code >= 400:
                    raise _RpcBad(f"HTTP {r.status_code}")
                js = r.json()
                if js.get("error"):
                    msg = str(js["error"].get("message") or js["error"])[:160]
                    if method == "eth_getLogs" and ("range" in msg or "limit" in msg or "exceed" in msg or "too many" in msg.lower()):
                        self.span = max(100, self.span // 2)
                    if method == "eth_call":                  # a rede respondeu (o contrato recusou): não é falha do RPC
                        self._rpc_fail[url] = 0
                        raise RpcError(msg)
                    raise _RpcBad(msg)
                self.stat["rpc"] = url
                self._rpc_fail[url] = 0
                return js.get("result")
            except RpcError as e:
                last = f"{url.split('//')[-1]}: {str(e)[:140]}"
                if method == "eth_call" and not isinstance(e, _RpcBad) and "429" not in str(e):
                    raise RpcError(last) from None          # recusa do contrato: perguntar a outro RPC não muda a resposta
                self._rpc_bad(url)
            except Exception as e:
                last = f"{url.split('//')[-1]}: {type(e).__name__} {str(e)[:120]}"
                self._rpc_bad(url)
        raise RpcError(last or "sem RPC")

    def _rpc_bad(self, url: str) -> None:
        """Falha, demora ou resposta estranha: 2 seguidas e o RPC descansa 1 min (os outros seguem lendo)."""
        self._rpc_fail[url] = self._rpc_fail.get(url, 0) + 1
        if self._rpc_fail[url] >= RPC_FAILS and self._rpc_off.get(url, 0) <= time.time():
            self._rpc_off[url] = time.time() + RPC_PAUSE_S
            self._rpc_fail[url] = 0
            self.stat["pausas"] = self.stat.get("pausas", 0) + 1

    async def refresh_eth_usd(self) -> None:
        if self.eth_usd and time.time() - self._eth_at < 300:
            return
        try:
            r = await self.http.get(DEX_URL + WETH, timeout=10)
            px = [float(p.get("priceUsd") or 0) for p in (r.json() or []) if (p.get("baseToken") or {}).get("address", "").lower() == WETH]
            px = [p for p in px if p > 0]
            if px:
                self.eth_usd, self._eth_at = sorted(px)[len(px) // 2], time.time()
        except Exception as e:
            log.info("Robinhood: preço do ETH não veio da DexScreener: %s", str(e)[:120])

    # ------------------------------------------------------------------ leitura
    def _router_topics(self) -> list[str]:
        rs = [PM] + [a for a, _ in self.routers.most_common(ROUTERS_MAX)]
        return ["0x" + "0" * 24 + a[2:] for a in rs]

    async def window(self, a: int, b: int) -> list[dict]:
        """Lê os blocos a..b: 3 consultas (trocas, transferências saindo e entrando no PoolManager e nos roteadores)."""
        url = self.next_rpc()
        logs = await self.rpc("eth_getLogs", [{"address": PM, "topics": [[T_SWAP, T_INIT, T_ML]], "fromBlock": hex(a), "toBlock": hex(b)}], url) or []
        swaps = [x for x in logs if ((x.get("topics") or [""])[0] or "").lower() == T_SWAP]
        inits = [x for x in logs if ((x.get("topics") or [""])[0] or "").lower() == T_INIT]
        mls = [x for x in logs if ((x.get("topics") or [""])[0] or "").lower() == T_ML]
        if inits:
            self.copier.note_init(inits)
        if mls:
            self.copier.note_liq(mls)
        for s in swaps:
            self.routers[_topic_addr((s.get("topics") or ["", "", ""])[2])] += 1
        if not swaps:
            return []
        tps = self._router_topics()
        await asyncio.sleep(0.2)
        t_from = await self.rpc("eth_getLogs", [{"topics": [T_TRANSFER, tps], "fromBlock": hex(a), "toBlock": hex(b)}], url) or []
        await asyncio.sleep(0.2)
        t_to = await self.rpc("eth_getLogs", [{"topics": [T_TRANSFER, None, tps], "fromBlock": hex(a), "toBlock": hex(b)}], url) or []
        legs = legs_of(t_from + t_to)
        per_tx = Counter(s.get("transactionHash") for s in swaps)
        out = []
        for s in swaps:
            self.stat["trocas"] += 1
            if per_tx[s.get("transactionHash")] != 1:
                self.stat["fora_rota"] += 1
                continue
            tr = decode(s, list(dict.fromkeys(legs.get(s.get("transactionHash")) or [])), 1, self.eth_usd)
            if tr is None:
                self.stat["fora_outro"] += 1
                continue
            out.append(tr)
        return out

    async def poll(self) -> int:
        """Uma volta: blocos novos → trades. Devolve quantos trades entraram."""
        head = int(await self.rpc("eth_blockNumber", []), 16) - HEAD_MARGIN
        if self.head and self.head_t and time.time() - self._ts_at < 60:
            ht = self.head_t + (head - self.head) * self.block_s
        else:
            blk = await self.rpc("eth_getBlockByNumber", [hex(head), False])
            ht = int(blk["timestamp"], 16) if blk else time.time()
            if self.head and self.head_t and head > self.head:
                bs = (ht - self.head_t) / (head - self.head)
                if 0.02 < bs < 2:
                    self.block_s = round(self.block_s * 0.8 + bs * 0.2, 4)
            self._ts_at = time.time()
        self.head, self.head_t = head, ht
        if self.cursor is None or head - self.cursor > CATCHUP_S / self.block_s:
            self.cursor = head - int(600 / self.block_s)          # sem ponto guardado (ou muito velho): começa 10 min atrás
        n, t0 = 0, time.time()
        cop = set(self.ranking()["copiaria"])             # uma vez por volta: cada trade novo invalida o ranking guardado
        while self.cursor < head and time.time() - t0 < 25:
            a = self.cursor + 1
            b = min(head, a + self.span - 1)
            for tr in await self.window(a, b):
                if tr["id"] in self.seen:
                    continue
                tr["t"] = round(ht - (head - tr["block"]) * self.block_s, 1)
                before = self.hold.get((tr["wallet"], tr["token"]), 0.0)
                self._add(tr)
                if self.arquivo is not None and len(self._arq_pend) < ARQ_PEND_MAX:
                    self._arq_pend.append({k: tr.get(k) for k in ARQ_FIELDS})
                try:
                    self.copier.on_trade(tr, before, cop)
                except Exception as e:                     # a cópia nunca para a leitura
                    log.warning("Robinhood: cópia falhou num trade: %s", str(e)[:160])
                n += 1
            self.cursor = b
            await asyncio.sleep(0.3)                       # espaça um pouco (com 3 RPC no revezamento, cada um descansa ~1 s)
        self.stat["polls"] += 1
        self.stat["trades"] += n
        self.stat["volta_t"] = time.time()
        return n

    def _add(self, tr: dict) -> None:
        if tr["id"] in self.seen:
            return
        if len(self.trades) == self.trades.maxlen:
            self.seen.discard(self.trades[0]["id"])
        self.trades.append(tr)
        self.seen.add(tr["id"])
        k = (tr["wallet"], tr["token"])
        self.hold[k] = max(0.0, self.hold.get(k, 0.0) + tr["amount"] * (1 if tr["side"] == "buy" else -1))
        if tr.get("amount") and tr.get("quote") == "ETH" and (tr["token"] not in self.px or tr.get("t", 0) >= self.px[tr["token"]][1]):
            self.px[tr["token"]] = (tr["eth"] / tr["amount"], tr.get("t", 0))
        self._rank_cache = None

    def trim(self, now: float | None = None) -> None:
        lim = (now or time.time()) - KEEP_S
        while self.trades and self.trades[0]["t"] < lim:
            self.seen.discard(self.trades.popleft()["id"])
        if len(self.hold) > 200_000:                       # quem não aparece mais nas últimas 24 h sai da conta do que segura
            live = {(t["wallet"], t["token"]) for t in self.trades}
            self.hold = {k: v for k, v in self.hold.items() if k in live}
        if len(self.px) > 50_000:
            keep = self.copier.held()
            self.px = {k: v for k, v in self.px.items() if k in keep or v[1] >= lim}

    async def balances_tick(self, wallets: list[str]) -> None:
        """Saldo das carteiras do topo (ETH + WETH + USDG), no máximo 3 por volta; vale 30 min."""
        now = time.time()
        for w in wallets:
            b = self.balances.get(w)
            if (not b or now - b["t"] > 1800 or "contrato" not in b) and w not in self._bal_q:
                self._bal_q.append(w)
        if not self.eth_usd:
            return
        for _ in range(min(3, len(self._bal_q))):
            w = self._bal_q.popleft()
            try:
                eth = _hex(await self.rpc("eth_getBalance", [w, "latest"])) / 1e18
                arg = "0x70a08231" + w[2:].rjust(64, "0")
                weth = _hex(await self.rpc("eth_call", [{"to": WETH, "data": arg}, "latest"])) / 1e18
                usdg = _hex(await self.rpc("eth_call", [{"to": USDG, "data": arg}, "latest"])) / 1e6
                code = str(await self.rpc("eth_getCode", [w, "latest"]) or "0x").lower()
                # 0.32.290: carteira que tem código é um contrato (robô), não uma pessoa; 0xef0100… é carteira comum com delegação (EIP-7702)
                contrato = len(code) > 2 and not code.startswith("0xef0100")
                self.balances[w] = {"eth": round(eth + weth, 5), "usd": round((eth + weth) * self.eth_usd + usdg, 2), "t": now, "contrato": contrato}
            except RpcError:
                self.balances.setdefault(w, {"eth": None, "usd": None, "t": now - 1500})   # tenta de novo em 5 min
            await asyncio.sleep(0.5)

    def ranking(self, now: float | None = None) -> dict:
        now = now or time.time()
        if self._rank_cache and now - self._rank_cache[0] < 15:
            return self._rank_cache[1]
        r = rank(self.trades, now, self.cfg, self.balances, self.px)
        # 0.32.295 (pedido do dono, 11/11: "tag e o botão de comprar cinza, não quero perder dinheiro"): trader PERIGO não entra no Copiando agora
        dz = self.danger(now)
        for row in r["rows"]:
            row["perigo"] = dz.get(row["wallet"], [])
            if row["perigo"]:
                row["eligible"], row["copiaria"] = False, False
        r["copiaria"] = [w for w in r["copiaria"] if w not in dz]
        self._rank_cache = (now, r)
        return r

    def danger(self, now: float | None = None) -> dict[str, list[str]]:
        """Traders PERIGO (0.32.295): carteira que é um contrato-robô, ou que comprou token cuja VENDA o pool recusa (honeypot para quem
        copia). Vem do saldo (eth_getCode) e das conferências do hoodsafe; guardado 30 s."""
        now = now or time.time()
        if self._danger and now - self._danger[0] < 30:
            return self._danger[1]
        hp = {tk for tk, v in self.copier.safe.cache.items() if v.get("venda_travada")}
        by: dict[str, set] = {}
        if hp:
            for t in self.trades:
                if t["side"] == "buy" and t["token"] in hp:
                    by.setdefault(t["wallet"], set()).add(t["token"])
        out: dict[str, list[str]] = {}
        for w, b in self.balances.items():
            if b.get("contrato"):
                out.setdefault(w, []).append("é um contrato (robô), não uma pessoa")
        for w, tks in by.items():
            out.setdefault(w, []).append(f"comprou {len(tks)} token(s) que não deixam vender (honeypot)")
        self._danger = (now, out)
        return out

    def danger_reason(self, wallet: str) -> str | None:
        r = self.danger().get((wallet or "").lower())
        return "; ".join(r) if r else None

    async def danger_scan(self) -> None:
        """Confere antes, sem esperar a cópia tentar: os tokens que os 30 primeiros do ranking compraram nas últimas 2 h (até 2 por volta)."""
        now = time.time()
        top = {r["wallet"] for r in self.ranking(now)["rows"][:30]}
        seen, n = set(), 0
        for t in reversed(self.trades):
            if t["t"] < now - 7200 or n >= 2:
                break
            if t["side"] != "buy" or t["wallet"] not in top or t["token"] in seen or t.get("quote") != "ETH":
                continue
            seen.add(t["token"])
            if self.copier.safe.cached(t["token"], now) is not None or now - self._scan_at.get(t["token"], 0) < 3600:
                continue
            self._scan_at[t["token"]] = now
            n += 1
            key = await self.copier.pool_key(t.get("pool") or "", t["token"])
            if key:
                await self.copier.safe.check(t["token"], key, t["wallet"], int(t["amount"] * 1e18))
                self._danger = None
                self._rank_cache = None

    # ------------------------------------------------------------------ banco (só o estado: cursor e regra)
    async def load(self) -> None:
        if self.db is not None:
            try:
                for r in await self.db.select("hood_state", None) or []:
                    if r.get("k") == "cfg" and isinstance(r.get("v"), dict):
                        raw = dict(r["v"])
                        if raw.get("v") != CFG_DEFAULT["v"]:        # 0.32.322: regra ainda no padrão antigo → padrão novo, uma vez
                            raw.update({k: CFG_DEFAULT[k] for k, old in CFG_OLD.items() if raw.get(k, old) == old})
                            raw["v"] = CFG_DEFAULT["v"]
                            await self.db.insert("hood_state", {"k": "cfg", "v": clean_cfg(raw)}, upsert=True, on_conflict="k")
                        self.cfg = clean_cfg(raw)
                    elif r.get("k") == "cursor" and isinstance(r.get("v"), dict):
                        self.cursor = int(r["v"].get("block") or 0) or None
            except Exception as e:
                log.warning("Robinhood: estado guardado não carregou: %s", str(e)[:160])
            try:
                await self.copier.load()
            except Exception as e:
                log.warning("Robinhood: carteiras da cópia não carregaram: %s", str(e)[:160])
        if self.arquivo is not None:                    # 0.32.282: as últimas 24 h voltam do arquivo
            try:
                n = 0
                async for rows in self.arquivo.pages(ARQ["tabela"], time.time() - KEEP_S):
                    for r in rows:
                        if r.get("id") and r.get("t") and r.get("wallet") and r.get("token") and r.get("amount") is not None:
                            self._add(r)
                            n += 1
                    if n >= MAX_MEM:
                        break
                self.stat["do_arquivo"] = n
            except Exception as e:
                self.stat["arquivo_erro"] = f"leitura: {type(e).__name__} {str(e)[:120]}"
                log.warning("Robinhood: trades do arquivo não carregaram: %s", str(e)[:160])
        self.loaded = True

    async def save_state(self) -> None:
        if self.db is None or not self.cursor:
            return
        try:
            await self.db.insert("hood_state", {"k": "cursor", "v": {"block": self.cursor, "t": time.time()}},
                                 upsert=True, on_conflict="k")
        except Exception as e:
            log.warning("Robinhood: não gravou o ponto da leitura: %s", str(e)[:160])

    async def save_arquivo(self) -> None:
        """Trades novos para o arquivo (lotes de 500) e, uma vez por dia, apaga de lá o que passou de ARQ_KEEP_S."""
        arq = self.arquivo
        if arq is None:
            return
        try:
            while self._arq_pend:
                part = self._arq_pend[:500]
                await arq.put(ARQ, part)
                del self._arq_pend[:500]
                self.stat["salvos"] += len(part)
            if time.time() - self._arq_trim_at > 86400:
                self._arq_trim_at = time.time()
                await arq.rest._req("DELETE", "arquivo", {"tabela": f"eq.{ARQ['tabela']}", "t": f"lt.{time.time() - ARQ_KEEP_S}"},
                                    None, "return=minimal")
            self.stat["arquivo_erro"] = None
        except Exception as e:
            self.stat["arquivo_erro"] = f"gravação: {type(e).__name__} {str(e)[:120]}"
            log.warning("Robinhood: trades não foram para o arquivo: %s", str(e)[:160])

    async def save_cfg(self, raw: dict) -> dict:
        self.cfg = clean_cfg({**self.cfg, **(raw or {})})
        self._rank_cache = None
        if self.db is not None:
            await self.db.insert("hood_state", {"k": "cfg", "v": self.cfg}, upsert=True, on_conflict="k")
        return self.cfg

    # ------------------------------------------------------------------ laço
    async def run(self) -> None:
        await self.load()
        while True:
            if time.time() >= self._pause_until:
                try:
                    await asyncio.wait_for(self.poll(), 90)
                    self.stat["leitura_ok_t"] = time.time()
                except Exception as e:                     # só erro da LEITURA dos trades acende "erro na leitura" no Monitor
                    self.stat["erros"] += 1
                    self.stat["ultimo_erro"], self.stat["ultimo_erro_t"] = ("leitura: " + (str(e) or type(e).__name__))[:200], time.time()
                try:                                       # saldo das carteiras e preço do ETH: erro aqui não para a leitura
                    await self.refresh_eth_usd()
                    self.trim()
                    await asyncio.wait_for(self.balances_tick([r["wallet"] for r in self.ranking()["rows"][:30]]), 30)
                    await asyncio.wait_for(self.danger_scan(), 30)
                except Exception as e:
                    self.stat["outro_erro"], self.stat["outro_erro_t"] = ("saldo das carteiras: " + (str(e) or type(e).__name__))[:200], time.time()
            try:                                           # tempo máximo, preço e vendas da cópia seguem mesmo com o RPC pedindo calma
                await asyncio.wait_for(self.copier.tick(), 40)
            except Exception as e:
                log.warning("Robinhood: volta da cópia falhou: %s", str(e)[:160])
            if time.time() - self._save_at > 60:           # 0.32.282: estava dentro do except acima e só gravava quando a cópia falhava
                self._save_at = time.time()
                await self.save_state()
                await self.save_arquivo()
            await asyncio.sleep(POLL_S)

    def flow(self, hours: float = 1.0, limit: int = 30, now: float | None = None) -> dict:
        """0.32.294 (pedido do dono, 11/11): as moedas que mais estão recebendo dinheiro. Por token, no período: ETH que entrou nas compras,
        que saiu nas vendas e o saldo (entrou − saiu), carteiras que compraram, quantos do ranking (top 50) e do Copiando agora compraram,
        primeira vez que o token apareceu na leitura (idade aproximada: a memória guarda 24 h) e a variação do preço no período.
        Só trades lidos pela rede (pools V4 com ETH, WETH ou USDG); rota com vários pools fica de fora, como no ranking."""
        now = now or time.time()
        since = now - hours * 3600
        rk = self.ranking(now)
        top = {r["wallet"]: i + 1 for i, r in enumerate(rk["rows"])}
        cop = set(rk["copiaria"])
        first: dict[str, float] = {}
        T: dict[str, dict] = {}
        for t in self.trades:
            tk = t["token"]
            if tk not in first:
                first[tk] = t["t"]
            if t["t"] < since:
                continue
            x = T.setdefault(tk, {"token": tk, "compras_eth": 0.0, "vendas_eth": 0.0, "compras": 0, "vendas": 0, "buyers": set(),
                                  "sellers": set(), "top": {}, "px0": None, "px1": None, "ultimo_t": 0.0})
            px = t["eth"] / t["amount"] if t.get("amount") else None
            if px:
                x["px0"] = x["px0"] or px
                x["px1"] = px
            x["ultimo_t"] = max(x["ultimo_t"], t["t"])
            if t["side"] == "buy":
                x["compras_eth"] += t["eth"]
                x["compras"] += 1
                x["buyers"].add(t["wallet"])
                if t["wallet"] in top or t["wallet"] in cop:
                    x["top"][t["wallet"]] = {"wallet": t["wallet"], "pos": top.get(t["wallet"]), "copiando": t["wallet"] in cop,
                                             "perigo": self.danger_reason(t["wallet"])}
            else:
                x["vendas_eth"] += t["eth"]
                x["vendas"] += 1
                x["sellers"].add(t["wallet"])
        mem0 = self.trades[0]["t"] if self.trades else now
        rows = []
        for x in T.values():
            liq = x["compras_eth"] - x["vendas_eth"]
            rows.append({"token": x["token"], "entrou_eth": round(x["compras_eth"], 5), "saiu_eth": round(x["vendas_eth"], 5),
                         "liquido_eth": round(liq, 5), "liquido_usd": round(liq * self.eth_usd, 2) if self.eth_usd else None,
                         "compras": x["compras"], "vendas": x["vendas"], "carteiras": len(x["buyers"]), "vendedores": len(x["sellers"]),
                         "top": sorted(x["top"].values(), key=lambda v: v["pos"] or 99), "primeiro_t": first.get(x["token"]),
                         "idade_conhecida": first.get(x["token"], now) - mem0 > 300, "ultimo_t": x["ultimo_t"],
                         "preco_pct": round(100 * (x["px1"] / x["px0"] - 1), 1) if x["px0"] and x["px1"] else None,
                         "nome": (self.copier.meta.get(x["token"]) or {}).get("nome"),
                         "simbolo": (self.copier.meta.get(x["token"]) or {}).get("simbolo"),
                         "seguranca": {k: v for k, v in (self.copier.safe.cache.get(x["token"]) or {}).items()
                                       if k in ("ok", "why", "t", "erro", "venda_travada", "sem_pool", "ida_volta_pct", "lp_livre")} or None})
        rows.sort(key=lambda r: r["liquido_eth"], reverse=True)
        return {"horas": hours, "tokens": len(rows), "rows": rows[:limit], "eth_usd": self.eth_usd, "memoria_desde": mem0}

    async def flow_scan(self, tokens: list[str], limit: int = 8) -> None:
        """0.32.303 (pedido do dono): confere sozinho as moedas da lista Dinheiro entrando (até `limit` por vez, uma de cada vez)."""
        if self._flow_scanning:
            return
        self._flow_scanning = True
        try:
            n = 0
            for tk in tokens:
                if n >= limit:
                    break
                if self.copier.safe.cached(tk) is not None:
                    continue
                n += 1
                try:
                    await asyncio.wait_for(self.copier.check_token(tk), 30)
                except Exception:
                    pass
            if n:
                self._danger = None
                self._rank_cache = None
        finally:
            self._flow_scanning = False

    async def fill_names(self, tokens: list[str]) -> None:
        """Nome e símbolo dos tokens pela DexScreener (até 30 por consulta; quem não veio só tenta de novo em 10 min)."""
        now = time.time()
        miss = [t for t in tokens if t not in self.copier.meta and now - self._name_try.get(t, 0) > 600][:30]
        if not miss:
            return
        for t in miss:
            self._name_try[t] = now
        try:
            r = await self.http.get(DEX_URL + ",".join(miss), timeout=10)
            for p in r.json() or []:
                b = p.get("baseToken") or {}
                a = str(b.get("address") or "").lower()
                if a in miss and a not in self.copier.meta:
                    self.copier.meta[a] = {"nome": str(b.get("name") or "")[:40], "simbolo": str(b.get("symbol") or "")[:20]}
        except Exception:
            pass

    def state(self, now: float | None = None) -> dict:
        now = now or time.time()
        rk = self.ranking(now)
        last = self.trades[-1]["t"] if self.trades else None
        hour = [t for t in self.trades if t["t"] >= now - 3600]
        day = [t for t in self.trades if t["t"] >= now - 86400]
        q = Counter(t["quote"] for t in day)
        tok = Counter(t["token"] for t in hour)
        recent = [{k: t.get(k) for k in ("t", "tx", "token", "wallet", "side", "eth", "quote")} for t in list(self.trades)[-60:][::-1]]
        st = self.stat
        return {"ligado": True, "carregado": self.loaded, "cfg": self.cfg, "padrao": CFG_DEFAULT, "explorer": EXPLORER,
                "status": {"bloco": self.head, "lido_ate": self.cursor,
                           "atraso_s": round((self.head - self.cursor) * self.block_s, 1) if self.head and self.cursor else None,
                           "ultimo_trade_t": last, "trades_memoria": len(self.trades), "trades_1h": len(hour), "trades_24h": len(day),
                           "compras_24h": sum(1 for t in day if t["side"] == "buy"), "carteiras_24h": len({t["wallet"] for t in day}),
                           "tokens_24h": len({t["token"] for t in day}), "moedas_24h": dict(q),
                           "eth_24h": round(sum(t["eth"] for t in day), 3), "eth_usd": round(self.eth_usd, 2) if self.eth_usd else None,
                           "rpc": (st["rpc"] or "").split("//")[-1], "por_rpc": st["por_rpc"],
                           "rpcs": [{"rpc": u.split("//")[-1].split("/")[0], "pausa_s": max(0, round(self._rpc_off.get(u, 0) - now))} for u in self.rpcs], "erros": st["erros"], "ultimo_erro": st["ultimo_erro"],
                           "ultimo_erro_t": st["ultimo_erro_t"], "chamadas": st["chamadas"], "limite_429": st["limite_429"],
                           "leitura_ok_t": st.get("leitura_ok_t"), "outro_erro": st.get("outro_erro"), "outro_erro_t": st.get("outro_erro_t"),
                           "pausas": st.get("pausas", 0),
                           "pausa_s": max(0, round(self._pause_until - now)), "desde": st["desde"], "bloco_s": self.block_s,
                           "trocas": st["trocas"], "fora_rota": st["fora_rota"], "fora_outro": st["fora_outro"],
                           "roteadores": len(self.routers), "volta_t": st["volta_t"],
                           "arquivo": self.arquivo is not None, "salvos": st["salvos"], "do_arquivo": st["do_arquivo"],
                           "arquivo_fila": len(self._arq_pend), "arquivo_erro": st["arquivo_erro"]},
                "tokens_1h": [{"token": k, "trades": v} for k, v in tok.most_common(15)],
                "ranking": rk, "recentes": recent}
