"""0.32.484: Caçador de explosões da Robinhood, só em sombra (caso Super Iguana, 27/11/2026)."""
import asyncio
import time

from app import hoodhunt as H
from app.hood import T_INIT, WETH, ZERO

POOL = "0x" + "ab" * 32
TOKEN = "0xba1a2d9783ebe2b76493c5c12eb9813a0e062843"
HOOK = "0x339138b2b4b217753d7453552778865343a82145"


def _w(n):
    return format(n, "064x")


def init_log(c0=ZERO, c1=TOKEN, fee=0, hook=HOOK, sqrt=2 ** 96, block=100):
    t = lambda a: "0x" + "0" * 24 + a[2:]
    return {"topics": [T_INIT, POOL, t(c0), t(c1)], "data": "0x" + _w(fee) + _w(60) + "0" * 24 + hook[2:] + _w(sqrt) + _w(0),
            "blockNumber": hex(block), "transactionHash": "0xcafe"}


class W:
    head, head_t, block_s, eth_usd, arquivo = 100, 1000.0, 0.1, 3000.0, None

    async def fill_names(self, tokens):
        return None

    class copier:
        meta = {}

        @staticmethod
        async def check_token(tk):
            return {"ok": True, "venda_travada": False}


def tr(t, side, eth, amount, wallet, pool=POOL):
    return {"t": t, "side": side, "eth": eth, "amount": amount, "wallet": wallet, "pool": pool, "quote": "ETH", "fee": None, "token": TOKEN}


def test_parse_init_eth_pool_and_hook_flags():
    p = H.parse_init(init_log(), 1000.0)
    assert p["token"] == TOKEN and p["fee"] == 0 and p["px_ini"] == 1.0
    # 0x…2145: afterSwapReturnDelta (bit 2) ligado, como o pool do SI
    assert "depois da troca muda o valor" in p["hook_flags"]
    assert H.parse_init(init_log(c0=WETH), 1.0)["token"] == TOKEN
    usdg = "0x5fc5360d0400a0fd4f2af552add042d716f1d168"
    assert H.parse_init(init_log(c0=TOKEN, c1=usdg), 1.0) is None       # par em dólar: fora


def test_entries_marks_and_results():
    p = H.parse_init(init_log(hook=ZERO), 1000.0)
    p["px_ini"] = 0.000001
    H.on_trade(p, tr(1010, "buy", 0.001, 1000, "0x1"))                  # 1ª compra: entrada A no preço 0,000001
    assert p["a"]["px"] == 0.000001 and p["b"] is None
    for i in range(2, 6):
        H.on_trade(p, tr(1010 + i, "buy", 0.02, 10000, "0x%d" % i))     # preço 0,000002, 5 compradores, 0,081 ETH
    assert p["c"] and p["b"] is None                                    # B espera a conferência das travas
    p["checks"] = {"lp": "contrato", "ruins": []}
    H.on_trade(p, tr(1020, "buy", 0.02, 10000, "0x6"))
    assert p["b"]["px"] == 0.000002
    H.on_trade(p, tr(1030, "buy", 0.1, 1000, "0x7"))                    # pico 0,0001 = 100× a entrada A
    H.on_trade(p, tr(2000, "sell", 0.02, 1000, "0x7"))                  # depois cai para 0,00002
    assert H.marks(p, 1010 + 3601)
    assert p["a"]["m"]["1"] == 0.00002
    r1 = H.result(p["a"], "1", 3000.0)
    assert abs(r1 - (0.10 * 20 - 0.10 - 2 * H.GAS_ETH * 3000)) < 1e-9   # 20× sem taxa de pool (hook zero, fee 0)
    assert H.result(p["a"], "x100", 3000.0) > 9.8                        # o pico passou de 100×: vendeu no alvo (menos o gás)
    assert H.result(p["a"], "x5", 3000.0) > 0.35
    assert H.result(p["b"], "24", 3000.0) is None                        # marca de 24 h ainda aberta


def test_rug_and_honeypot_value_zero():
    hu = H.Hunter(W())
    hu.note_init([init_log(hook=ZERO)])
    p = hu.pools[POOL]
    hu.on_trade(tr(1001, "buy", 0.001, 1000, "0x1"))
    ml = lambda d: {"topics": ["0x", POOL, "0x"], "data": "0x" + _w(0) + _w(0) + (_w(d) if d >= 0 else _w(2 ** 256 + d)) + _w(0), "blockNumber": hex(100)}
    hu.note_liq([ml(1000)])
    hu.note_liq([ml(-600)])
    assert p["rug_t"] and "liquidez tirada" in H.traps(p)
    H.marks(p, p["a"]["t"] + 3601)
    assert p["a"]["m"]["1"] == 0.0
    assert H.result({"px": 1.0, "m": {"1": 5.0}, "fee": 0.01}, "1", 3000.0, hp=True) < -0.099


def test_study_and_state_without_arquivo():
    hu = H.Hunter(W())
    hu.note_init([init_log(hook=ZERO)])
    hu.pools[POOL]["px_ini"] = 0.000001
    hu.on_trade(tr(1001, "buy", 0.001, 1000, "0x1"))
    hu.on_trade(tr(1002, "buy", 1.0, 1000, "0x2"))                      # 1000× do início
    st = hu.state(7, now=1100)
    assert st["sombra"] is True and st["status"]["com_troca"] == 1
    assert st["estudo"]["explosoes"][0]["x_pico"] >= 100
    assert st["agora"][0]["a"]["x_pico"] == 1000.0
    asyncio.run(hu.save())                                              # sem arquivo: não grava e não quebra


def test_pool_without_trade_leaves_and_closed_goes_to_done():
    hu = H.Hunter(W())
    hu.note_init([init_log(hook=ZERO)])
    hu.pools[POOL]["t"] = 0
    asyncio.run(hu.tick())
    assert POOL not in hu.pools
    hu.note_init([init_log(hook=ZERO)])
    hu.on_trade(tr(1001, "buy", 0.001, 1000, "0x1"))
    hu.pools[POOL]["t"] = time.time() - 26 * 3600                       # já passou da janela + 24 h
    asyncio.run(hu.tick())
    assert POOL not in hu.pools and hu.done and hu.done[0]["fechado"]
