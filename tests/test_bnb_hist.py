"""0.32.179: histórico dos traders da BNB pela NodeReal (Four.Meme e PancakeSwap). Sem internet."""
import asyncio
import time

import pytest

from tests.test_api import env  # noqa: F401  (fixture env)

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
        if m == "eth_chainId":
            return _Resp({"result": "0x38"})
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
    with pytest.raises(ValueError):                  # endereço do painel da NodeReal (Greenfield testnet), não o da BNB
        bnbhist.clean_key("https://open-platform.nodereal.io/8a189c1adc9d4f78b/greenfieldbilling-testnet/")


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


def test_nodereal_key_lives_only_in_the_bnb_panel(env):
    from tests.test_api import UA, UB, tok
    c, hub = env["c"], env["hub"]
    hub.bnb = bnb.BnbWatch(_NR([]), None, rpcs=["https://x"])
    assert c.get("/api/pump/bnb/nodereal", headers=tok(UB, "b@x.com")).status_code == 403
    assert c.get("/api/pump/bnb/nodereal", headers=tok(UA)).json()["configurada"] is False
    assert c.post("/api/pump/bnb/nodereal", json={"value": "curta"}, headers=tok(UA)).json()["error"]
    r = c.post("/api/pump/bnb/nodereal", json={"value": "https://bsc-mainnet.nodereal.io/v1/" + KEY}, headers=tok(UA))
    assert r.json()["ok"] and KEY not in r.text
    v = c.get("/api/pump/bnb/nodereal", headers=tok(UA))
    assert v.json()["configurada"] is True and KEY not in v.text and hub.system_keys["nodereal_bnb_key"] == KEY
    assert "nodereal_bnb_key" not in c.get("/api/admin/keys", headers=tok(UA)).json()["keys"]          # fora do painel da Solana
    assert c.post("/api/pump/bnb/nodereal/remover", json={}, headers=tok(UA)).json()["configurada"] is False
    assert not hub.system_keys.get("nodereal_bnb_key")


def test_check_key_needs_bsc_mainnet():
    assert asyncio.run(bnbhist.check_key(_NR([]), KEY)) is None

    class Test(_NR):
        async def post(self, url, json=None, timeout=None):
            return _Resp({"result": "0x61"})                                     # testnet
    assert "não é da BNB Smart Chain" in asyncio.run(bnbhist.check_key(Test([]), KEY))
    bad = asyncio.run(bnbhist.check_key(_NR([], err="invalid api key"), KEY))
    assert "recusou" in bad and KEY not in bad


def test_boot_loads_only_ranking_days_and_more_on_demand():
    """0.32.192: no início só os dias do ranking (padrão 7); pedir 14 traz o resto do banco."""
    seen = []

    class DB:
        async def select(self, table, filters=None, order=None, limit=None, columns="*", offset=0, gte=None, lte=None, **kw):
            seen.append((table, gte, lte))
            return []

        async def insert(self, *a, **k):
            return None
    w = bnb.BnbWatch(_NR([]), DB(), rpcs=["https://x"])
    asyncio.run(w.load())
    t0 = [g for (tb, g, _) in seen if tb == "bnb_fm_trades"][0]["t"]
    assert abs((time.time() - t0) - (7 * 86400 + 3600)) < 60

    async def more():
        await w.save_cfg({"days": 14})
        await asyncio.gather(*list(w._tasks))
    asyncio.run(more())
    g, l_ = [(g, l_) for (tb, g, l_) in seen if tb == "bnb_fm_trades"][-1]
    assert abs((time.time() - g["t"]) - 14 * 86400) < 60 and l_["t"] == t0
