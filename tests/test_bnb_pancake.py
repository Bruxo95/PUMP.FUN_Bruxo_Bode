"""0.32.178: compras e vendas na PancakeSwap dos tokens que graduaram da Four.Meme. Sem internet."""
import asyncio
import time

from app import bnb, bnbpancake as pc
from tests.test_bnb import TOK, W1, W2, _Resp, _a, _w

U = "11111111-1111-1111-1111-111111111111"
PAIR = "0x" + "cc" * 20
E18 = 10 ** 18
INFO = pc.pair_info(TOK, bnb.ZERO, PAIR)          # TOK (0xa1…) < WBNB (0xbb…) → o token é o token0


def _tf(frm, to, amount, tx="0xt1", i=1, block=200, token=TOK):
    return {"address": token, "topics": [pc.T_TRANSFER, pc.topic_addr(frm), pc.topic_addr(to)], "data": "0x" + _w(int(amount * E18)),
            "transactionHash": tx, "logIndex": hex(i), "blockNumber": hex(block)}


def _sw(a0i, a1i, a0o, a1o, tx="0xt1", i=3, block=200, pair=PAIR):
    return {"address": pair, "topics": [pc.T_SWAP, pc.topic_addr(pc.NOT_TRADER and "0x" + "10" * 20), pc.topic_addr(W1)],
            "data": "0x" + "".join(_w(int(v * E18)) for v in (a0i, a1i, a0o, a1o)), "transactionHash": tx, "logIndex": hex(i),
            "blockNumber": hex(block)}


def test_topics_match_the_standard_events():
    assert pc.T_TRANSFER == "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
    assert pc.T_SWAP == "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822"
    assert INFO["t0"] and INFO["quote"] == bnb.ZERO


def test_decode_buy_and_sell_with_amounts_in_bnb():
    swaps = [_sw(0, 0.5, 1000, 0, tx="0xb"), _sw(400, 0, 0, 0.3, tx="0xs")]
    tfs = [_tf(PAIR, W1, 1000, tx="0xb"), _tf(W2, PAIR, 400, tx="0xs")]
    out = pc.decode(swaps, tfs, {PAIR: INFO})
    b, s = sorted(out, key=lambda x: x["side"])
    assert b["side"] == "buy" and b["wallet"] == W1 and b["amount"] == 1000 and abs(b["value"] - 0.5) < 1e-12
    assert s["side"] == "sell" and s["wallet"] == W2 and abs(s["value"] - 0.3) < 1e-12 and s["venue"] == "pancake"
    assert abs(b["price"] - 0.0005) < 1e-12 and b["quote"] == bnb.ZERO and b["id"].startswith("p:")


def test_token1_side_and_liquidity_and_router_are_not_trades():
    hi = "0x" + "f0" * 20                                         # token acima do WBNB → token1
    info = pc.pair_info(hi, bnb.ZERO, PAIR)
    assert not info["t0"]
    out = pc.decode([_sw(0.2, 0, 0, 500)], [_tf(PAIR, W1, 500, token=hi)], {PAIR: info})
    assert out and abs(out[0]["value"] - 0.2) < 1e-12
    assert pc.decode([], [_tf(W1, PAIR, 10)], {PAIR: INFO}) == []                         # liquidez: sem Swap
    router = "0x10ed43c718714eb63d5aa57b78b54704e256024e"
    assert pc.decode([_sw(0, 1, 5, 0)], [_tf(PAIR, router, 5)], {PAIR: INFO}) == []        # roteador não é trader
    assert pc.decode([_sw(0, 1, 5, 0)], [_tf(PAIR, W1, 5, token="0x" + "99" * 20)], {PAIR: INFO}) == []


class _Http:
    """RPC falso com um par da PancakeSwap: logs da curva vazios, Swap/Transfer do par e getPair."""

    def __init__(self, swaps, tfs):
        self.swaps, self.tfs, self.calls = swaps, tfs, []

    async def post(self, url, json=None, timeout=None):
        m, p = json["method"], json["params"]
        self.calls.append(m)
        if m == "eth_blockNumber":
            return _Resp({"result": hex(1000)})
        if m == "eth_getBlockByNumber":
            return _Resp({"result": {"timestamp": hex(int(time.time()))}})
        if m == "eth_getLogs":
            f = p[0]
            if f["address"] == bnb.TM2:
                return _Resp({"result": []})
            if f["topics"][0] == pc.T_SWAP:
                return _Resp({"result": self.swaps})
            if len(f["topics"]) == 3:                                 # carteira → par (venda)
                return _Resp({"result": [t for t in self.tfs if t["topics"][2] in f["topics"][2]]})
            return _Resp({"result": [t for t in self.tfs if t["topics"][1] in f["topics"][1]]})
        if m == "eth_call":
            to, data = p[0]["to"], p[0]["data"]
            if to == pc.FACTORY_V2:
                return _Resp({"result": "0x" + _a(PAIR)})
            if to == bnb.HELPER3:
                words = [_w(2), _a(bnb.TM2), _a(bnb.ZERO)] + [_w(0)] * 8 + [_w(1)]       # palavra 11 = graduou
                return _Resp({"result": "0x" + "".join(words)})
        return _Resp({"error": {"message": "método não esperado"}})


def test_grad_tick_finds_the_pair():
    w = bnb.BnbWatch(_Http([], []), None, rpcs=["https://x"])
    w._add({"id": "a:0", "tx": "a", "block": 1, "token": TOK, "wallet": W1, "side": "buy", "price": 0.001, "amount": 10,
            "value": 0.01, "fee": 0, "t": time.time(), "quote": bnb.ZERO})
    asyncio.run(w.grad_tick())
    assert TOK in w.graduated and w.pairs[TOK]["pair"] == PAIR and w._pairs_dirty


def test_poll_reads_pancake_and_follows_trader_sale_and_ranks_graduated_profit():
    now = time.time()
    swaps = [_sw(0, 0.5, 1000, 0, tx="0xb", block=995), _sw(1000, 0, 0, 2.0, tx="0xs", i=7, block=998)]
    tfs = [_tf(PAIR, W1, 1000, tx="0xb", block=995), _tf(W1, PAIR, 1000, tx="0xs", i=5, block=998)]
    w = bnb.BnbWatch(_Http(swaps, tfs), None, rpcs=["https://x"])
    w.bnb_usd = 600
    w.quotes[TOK] = bnb.ZERO
    w.graduated.add(TOK)
    w.pairs[TOK] = {**INFO, "t": now}
    w.safe.mark(TOK, True)
    b = w.book(U)
    w.ranking = lambda now=None: {"copiaria": [W1], "rows": []}       # W1 é copiado
    w.cursor = 990
    asyncio.run(w.poll())
    assert w.pstat["trades"] == 2 and w.hold[(W1, TOK)] == 0
    assert not b.pos and b.trades and b.trades[0]["motivo"] == "trader vendeu 100%"      # comprou e seguiu a venda na Pancake
    r = bnb.rank(w.trades, time.time(), {"min_wallet_usd": 0, "min_trades": 0, "min_closed": 1}, w.quotes, 600, {}, w.graduated)
    g = r["graduados"][0]
    assert g["wallet"] == W1 and abs(g["grad_realized_bnb"] - 1.5) < 1e-9 and g["pancake_trades"] == 2 and g["grad_winrate"] == 100
    st = pc.graduated_list(w.trades, w.pairs, time.time(), bnb.to_bnb, w.quotes, 600)
    assert st[0]["token"] == TOK and st[0]["trades_24h"] == 2 and st[0]["compradores_24h"] == 1 and st[0]["desde_pct"] == 300.0
