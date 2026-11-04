"""0.32.179: histórico dos traders da BNB pela NodeReal (Four.Meme e PancakeSwap). Sem internet."""
import asyncio
import time

import pytest

from app import bnb, bnbhist, bnbpancake as pc
from tests.test_bnb import TOK, W1, W2, _Resp, _a, _log, _w

KEY = "abcdef0123456789abcdef0123456789"
PAIR = "0x" + "cc" * 20


class _NR:
    """NodeReal falsa: bloco 10.000, 0,45 s por bloco, logs da curva, getTokenInfo (graduado) e getPair."""

    def __init__(self, logs, err=None):
        self.logs, self.err, self.urls = logs, err, []

    async def post(self, url, json=None, timeout=None):
        self.urls.append(url)
        m, p = json["method"], json["params"]
        if self.err:
            return _Resp({"error": {"message": self.err + " " + url}})
        if m == "eth_blockNumber":
            return _Resp({"result": hex(10_000)})
        if m == "eth_getBlockByNumber":
            return _Resp({"result": {"timestamp": hex(int(1_700_000_000 + int(p[0], 16) * 0.45))}})
        if m == "eth_getLogs":
            f = p[0]
            a, b = int(f["fromBlock"], 16), int(f["toBlock"], 16)
            if f["address"] == bnb.TM2:
                return _Resp({"result": [lg for lg in self.logs if a <= int(lg["blockNumber"], 16) <= b]})
            return _Resp({"result": []})
        if m == "eth_call":
            to = p[0]["to"]
            if to == bnb.HELPER3:
                return _Resp({"result": "0x" + "".join([_w(2), _a(bnb.TM2), _a(bnb.ZERO)] + [_w(0)] * 8 + [_w(1)])})
            if to == pc.FACTORY_V2:
                return _Resp({"result": "0x" + _a(PAIR)})
        return _Resp({"error": {"message": "método não esperado"}})


def test_clean_key_accepts_key_or_url():
    assert bnbhist.clean_key(KEY) == KEY
    assert bnbhist.clean_key("https://bsc-mainnet.nodereal.io/v1/" + KEY + "/") == KEY
    with pytest.raises(ValueError):
        bnbhist.clean_key("curta")


def test_backfill_reads_old_curve_trades_finds_pair_and_never_copies():
    logs = [_log("buy", TOK, W1, 1000, 0.5, block=100, i=0), _log("sell", TOK, W1, 1000, 1.0, block=200, i=1),
            _log("buy", TOK, W2, 10, 0.01, block=9_000, i=2)]
    w = bnb.BnbWatch(_NR(logs), None, rpcs=["https://x"])
    w.key_fn = lambda: KEY
    live = {"id": "live:0", "tx": "l", "block": 9_990, "token": TOK, "wallet": W2, "side": "buy", "price": 0.001, "amount": 5,
            "value": 0.005, "fee": 0, "t": time.time(), "quote": bnb.ZERO}
    w._add(live)
    b = w.book("u")
    h = w.hist
    h.span = 20_000

    async def go():
        await h.setup()
        while await h.step():
            pass
    asyncio.run(go())
    assert h.st["fase"] == "pronto" and h.st["trades_curva"] == 3 and h.st["pct"] == 100.0
    assert [t["id"] for t in w.trades][-1] == "live:0"                                   # em ordem de hora
    assert len(w.trades) == 4 and not b.pos                                              # histórico não copia
    assert w.pairs[TOK]["pair"] == PAIR and TOK in w.graduated
    assert w.hold[(W2, TOK)] == 5                                                        # não mexe no que segura agora
    r = bnb.rank([t for t in w.trades if t["id"] != "live:0"], 1_700_000_000 + 10_000 * 0.45, {"min_wallet_usd": 0, "min_trades": 0, "min_closed": 1, "days": 14},
                 w.quotes, 600, {}, w.graduated)
    w1 = next(x for x in r["rows"] if x["wallet"] == W1)
    assert abs(w1["realized_bnb"] - (0.99 - 0.505)) < 1e-6 and w1["grad_tokens"] == 1          # lucro do passado entra
    assert all(u.startswith(bnbhist.URL) for u in w.http.urls)


def test_key_never_appears_in_errors_or_status():
    w = bnb.BnbWatch(_NR([], err="rate limited"), None, rpcs=["https://x"])
    w.key_fn = lambda: KEY
    with pytest.raises(bnbhist.HistError) as e:
        asyncio.run(w.hist.rpc("eth_blockNumber", []))
    assert KEY not in str(e.value)
    assert KEY not in str(w.state()["historico"]) and w.state()["historico"]["chave"] is True


def test_without_key_waits():
    w = bnb.BnbWatch(_NR([]), None, rpcs=["https://x"])
    assert w.state()["historico"]["chave"] is False and w.state()["historico"]["fase"] == "esperando a chave"
