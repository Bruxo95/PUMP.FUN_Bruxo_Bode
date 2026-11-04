"""BNB · Four.Meme: o que acontece na PancakeSwap depois que o token gradua (0.32.178, pedido do dono em 04/11/2026).

"A compra na Four.Meme fica presa; temos que olhar na PancakeSwap os tokens que vingaram a partir da Four.Meme e
acompanhar os traders que realmente ganham dinheiro com os tokens graduados."

Quando a curva da Four.Meme chega a 100%, a liquidez vai para um par V2 da PancakeSwap (token/WBNB ou token/USDT…) e as
compras e vendas passam a acontecer lá. Aqui:
- `find_pair`: o par V2 do token (PancakeFactory.getPair), guardado com a moeda e a ordem token0/token1;
- `decode`: junta, em cada transação, a transferência do token entre a carteira e o par (quem comprou ou vendeu e quanto)
  com o evento Swap do par (quanto BNB/USDT entrou ou saiu). Vira um trade no mesmo formato dos da curva (`venue` =
  "pancake"), então o ranking, a cópia (seguir a venda do trader) e o preço das posições passam a ver a PancakeSwap.

Compra pela PancakeSwap: o par manda o token direto para quem comprou (Transfer par → carteira). Venda: o roteador
puxa o token da carteira direto para o par (Transfer carteira → par). Transferência para o par sem Swap na mesma
transação (colocar liquidez) não é trade. Carteira que é roteador/agregador aparece como "trader" com muitos trades por
dia e cai no filtro de robô do ranking.
"""
from __future__ import annotations

from . import evm

FACTORY_V2 = "0xca143ce32fe78f1f7019d7d551a6402fc5350c73"   # PancakeSwap V2 (o mesmo do bnbreal)
WBNB = "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c"
ZERO = "0x" + "0" * 40
SEL_PAIR = "0xe6a43905"                                      # getPair(address,address)
T_SWAP = "0x" + evm.keccak256(b"Swap(address,uint256,uint256,uint256,uint256,address)").hex()
T_TRANSFER = "0x" + evm.keccak256(b"Transfer(address,address,uint256)").hex()
PAIRS_MAX = 150              # pares lidos ao mesmo tempo (os que graduaram por último)
# 0.32.183 (monitor da BNB parado em 04/11): o publicnode responde HTTP 403 a eth_getLogs com mais de 10 endereços
# (medido em 04/11: 10 passa, 20 recusa) e o blockrazor responde "exceed max addresses". As consultas vão em lotes.
ADDR_MAX = 10
PAUSE_S = 300                # depois de uma recusa, a PancakeSwap fica de fora 5 min (a curva nunca para)
GRAD_EVERY_S = 180           # confere de novo se um token da curva graduou a cada 3 min
GRAD_PER_MIN = 30            # consultas de "graduou?" por minuto
GRAD_LOOK_S = 3 * 3600       # só tokens que negociaram na curva nas últimas 3 h
NOT_TRADER = {"0x10ed43c718714eb63d5aa57b78b54704e256024e",  # PancakeSwap V2 router
              "0x13f4ea83d0bd40e75c8222255bc855a974568dd4",  # PancakeSwap smart router
              "0x5c952063c7fc8610ffdb798152d69f0b9550762b",  # TokenManager2 da Four.Meme
              "0xf251f83e40a78868fcfa3fa4599dad6494e46034",  # Helper3
              ZERO, "0x000000000000000000000000000000000000dead"}


def topic_addr(a: str) -> str:
    return "0x" + "0" * 24 + a.lower()[2:]


def _t2a(t: str) -> str:
    return "0x" + (t or "")[-40:].lower()


def _words(d: str) -> list[int]:
    d = (d or "0x")[2:]
    return [int(d[i:i + 64], 16) for i in range(0, len(d) - len(d) % 64, 64)]


def pair_info(token: str, quote: str, pair: str) -> dict:
    """quote = moeda da curva (ZERO = BNB → o par é com WBNB)."""
    q = WBNB if quote in ("", ZERO, None) else quote.lower()
    return {"token": token.lower(), "pair": pair.lower(), "quote": ZERO if q == WBNB else q, "t0": token.lower() < q}


async def find_pair(call, token: str, quote: str) -> str | None:
    q = WBNB if quote in ("", ZERO, None) else quote
    w = evm.words(await call(FACTORY_V2, evm.call_data(SEL_PAIR, token, q)))
    return ("0x%040x" % w[0]) if w and w[0] else None


def _idx(lg: dict) -> int:
    return int(lg.get("logIndex") or "0x0", 16)


def decode(swaps: list[dict], transfers: list[dict], pairs: dict[str, dict]) -> list[dict]:
    """Logs de um trecho de blocos → trades da PancakeSwap. pairs = {endereço do par: pair_info}. Sem hora (o chamador
    preenche `t`). Valores em unidades (18 casas: tokens da Four.Meme, WBNB e USDT da BSC)."""
    by_tx: dict[tuple, list] = {}
    for s in swaps:
        a = (s.get("address") or "").lower()
        if a in pairs:
            by_tx.setdefault((s.get("transactionHash"), a), []).append(s)
    for v in by_tx.values():
        v.sort(key=_idx)
    out, used = [], set()
    for tf in sorted(transfers, key=lambda x: (int(x.get("blockNumber") or "0x0", 16), _idx(x))):
        tp = tf.get("topics") or []
        if len(tp) < 3 or tp[0].lower() != T_TRANSFER:
            continue
        frm, to = _t2a(tp[1]), _t2a(tp[2])
        if frm in pairs and to not in pairs:
            pair, wallet, side = frm, to, "buy"
        elif to in pairs and frm not in pairs:
            pair, wallet, side = to, frm, "sell"
        else:
            continue
        info = pairs[pair]
        if (tf.get("address") or "").lower() != info["token"] or wallet in NOT_TRADER:
            continue
        sw = next((s for s in by_tx.get((tf.get("transactionHash"), pair), [])
                   if _idx(s) > _idx(tf) and (s.get("transactionHash"), _idx(s)) not in used), None)
        if sw is None:
            continue                                            # colocar/tirar liquidez: não é trade
        w = _words(sw.get("data"))
        if len(w) < 4:
            continue
        a0i, a1i, a0o, a1o = w[:4]
        q_in, q_out = (a1i, a1o) if info["t0"] else (a0i, a0o)
        amount = int(tf.get("data") or "0x0", 16) / 1e18
        value = (q_in if side == "buy" else q_out) / 1e18
        if amount <= 0 or value <= 0:
            continue
        used.add((sw.get("transactionHash"), _idx(sw)))
        out.append({"id": f"p:{tf.get('transactionHash')}:{_idx(tf)}", "tx": tf.get("transactionHash"),
                    "block": int(tf.get("blockNumber") or "0x0", 16), "token": info["token"], "wallet": wallet,
                    "side": side, "price": value / amount, "amount": amount, "value": value, "fee": 0.0,
                    "quote": info["quote"], "venue": "pancake"})
    return out


def graduated_list(trades, pairs: dict[str, dict], now: float, to_bnb, quotes: dict, bnb_usd) -> list[dict]:
    """Tokens que foram para a PancakeSwap: quando, quantos trades e compradores lá, volume e o preço desde a graduação."""
    per: dict[str, dict] = {}
    for t in trades:
        if t.get("venue") != "pancake" or t["token"] not in pairs:
            continue
        g = per.setdefault(t["token"], {"n": 0, "n24": 0, "buyers": set(), "sellers": set(), "vol24": 0.0, "first": None, "last": None})
        g["n"] += 1
        if g["first"] is None or t["t"] < g["first"][0]:
            g["first"] = (t["t"], t["price"])
        if g["last"] is None or t["t"] >= g["last"][0]:
            g["last"] = (t["t"], t["price"])
        if t["t"] >= now - 86400:
            g["n24"] += 1
            (g["buyers"] if t["side"] == "buy" else g["sellers"]).add(t["wallet"])
            b = to_bnb(t, quotes.get(t["token"]) or t.get("quote"), bnb_usd)
            g["vol24"] += b or 0.0
    rows = []
    for tk, info in pairs.items():
        g = per.get(tk) or {}
        f, la = g.get("first"), g.get("last")
        rows.append({"token": tk, "pair": info["pair"], "quote": info["quote"], "graduou_t": info.get("t"),
                     "trades": g.get("n", 0), "trades_24h": g.get("n24", 0), "compradores_24h": len(g.get("buyers", ())),
                     "vendedores_24h": len(g.get("sellers", ())), "vol_24h_bnb": round(g.get("vol24", 0.0), 4),
                     "ultimo_t": la[0] if la else None,
                     "desde_pct": round((la[1] / f[1] - 1) * 100, 1) if f and la and f[1] else None})
    rows.sort(key=lambda r: (r["vol_24h_bnb"], r["graduou_t"] or 0), reverse=True)
    return rows
