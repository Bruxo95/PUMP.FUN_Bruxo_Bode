"""0.32.177: segurança do token da BNB antes de comprar (honeypot, congelar, taxa alta). Sem internet."""
import asyncio
import time

from app import bnb, bnbsafe
from tests.test_bnb import TOK, W1, _Http

U = "11111111-1111-1111-1111-111111111111"
F = 10 ** 18


class _Get:
    def __init__(self, data=None, fail=False):
        self.data, self.fail, self.n = data, fail, 0

    async def get(self, url, timeout=None):
        self.n += 1
        if self.fail:
            raise OSError("sem rede")
        tok = url.split("=")[-1]
        data = self.data

        class R:
            def json(self_inner):
                return {"code": 1, "result": ({tok: data} if data is not None else {})}
        return R()


def _fees(buy_pct, sell_pct):
    async def tb(token, funds):
        return [0, 0, 1000 * F, funds, int(funds * buy_pct / 100), 0, 0, funds]

    async def ts(token, amount):
        got = 5 * F
        return [0, 0, got, int(got * sell_pct / 100)]
    return tb, ts


def _check(safe, graduated=False, fees=(1, 1)):
    tb, ts = _fees(*fees)
    return asyncio.run(safe.check(TOK, graduated, False, 600.0, tb, ts))


def test_judge_goplus_flags_and_taxes():
    assert bnbsafe.judge_goplus({}) == [] and bnbsafe.judge_goplus(None) == []
    why = bnbsafe.judge_goplus({"is_honeypot": "1", "transfer_pausable": "1", "sell_tax": "0.1", "buy_tax": "0.01"})
    assert "honeypot: não deixa vender" in why and any("congelar" in w for w in why)
    assert any("taxa de venda do token 10%" in w for w in why) and not any("compra do token" in w for w in why)
    assert bnbsafe.judge_goplus({"is_honeypot": "0", "sell_tax": "0.01", "is_open_source": "1"}) == []


def test_curve_token_normal_fee_passes_even_without_goplus_data():
    s = bnbsafe.Safety(None, _Get({}))
    v = _check(s)
    assert v["ok"] and v["taxa_compra"] == 1.0 and v["taxa_venda"] == 1.0 and v["goplus"] == "sem dados"
    assert s.cached(TOK)["ok"]


def test_high_curve_fee_is_barred_anti_sniper_or_tax():
    s = bnbsafe.Safety(None, _Get({}))
    v = _check(s, fees=(1, 10))
    assert not v["ok"] and "anti-sniper" in v["why"] and s.summary()["barrados"][0]["token"] == TOK


def test_goplus_honeypot_is_barred_and_stays_barred():
    g = _Get({"is_honeypot": "1"})
    s = bnbsafe.Safety(None, g)
    assert not _check(s)["ok"]
    assert not _check(s)["ok"] and g.n == 1                     # guardado: não consulta de novo


def test_graduated_token_needs_goplus_data():
    assert not _check(bnbsafe.Safety(None, _Get({})), graduated=True)["ok"]
    v = _check(bnbsafe.Safety(None, _Get(fail=True)), graduated=True)
    assert not v["ok"] and v.get("erro")
    assert _check(bnbsafe.Safety(None, _Get({"is_honeypot": "0", "sell_tax": "0"})), graduated=True)["ok"]


def test_rpc_failure_never_buys_and_retries_soon():
    async def bad(token, funds):
        raise OSError("rpc caiu")
    s = bnbsafe.Safety(None, _Get({}))
    v = asyncio.run(s.check(TOK, False, False, 600.0, bad, bad))
    assert not v["ok"] and v.get("erro")
    v["t"] -= bnbsafe.ERR_S + 1
    assert s.cached(TOK) is None                                 # tenta de novo depois de 1 min


def test_watch_does_not_copy_barred_token():
    w = bnb.BnbWatch(_Http([], {}), None)
    w.bnb_usd = 600
    b = w.book(U)
    w.safe.mark(TOK, False, "honeypot: não deixa vender")
    buy = {"id": "a:0", "tx": "a", "block": 1, "token": TOK, "wallet": W1, "side": "buy", "price": 0.001, "amount": 1000,
           "value": 1.0, "fee": 0.01, "t": time.time(), "quote": bnb.ZERO}
    w._add(buy)
    w._copy(buy, 0.0, {W1})
    assert not b.pos and b.events[0]["motivo"].startswith("token barrado pela segurança: honeypot")
    assert w.painel(U)["seguranca"]["barrados"][0]["why"] == "honeypot: não deixa vender"


def test_watch_checks_unknown_token_before_buying():
    w = bnb.BnbWatch(_Http([], {}), None)
    w.bnb_usd = 600
    b = w.book(U)
    w.safe = bnbsafe.Safety(None, _Get({}))
    tb, ts = _fees(1, 1)
    w._try_buy, w._try_sell = tb, ts
    buy = {"id": "a:0", "tx": "a", "block": 1, "token": TOK, "wallet": W1, "side": "buy", "price": 0.001, "amount": 1000,
           "value": 1.0, "fee": 0.01, "t": time.time(), "quote": bnb.ZERO}
    w._add(buy)

    async def go():
        w._copy(buy, 0.0, {W1})
        assert not b.pos                                          # ainda conferindo
        await asyncio.gather(*list(w._tasks))
    asyncio.run(go())
    assert len(b.pos) == 1 and w.safe.cached(TOK)["ok"]


def test_real_never_buys_without_approved_check():
    from tests.test_bnb_real import _buy, _drain, _watch
    w = _watch()
    w.safe.cache.clear()
    asyncio.run(w._real_buy(U, _buy(), 0.00001))
    rb = w.rbook(U)
    assert not rb.pos and rb.events[0]["acao"] == "REAL não copiou" and "segurança" in rb.events[0]["motivo"]
    w.safe.mark(TOK, False, "honeypot: não deixa vender")

    async def go():
        tr = _buy()
        w._add(tr)
        w._copy(tr, 0.0, {W1})
        await _drain(w)
    asyncio.run(go())
    assert not rb.pos and "honeypot" in rb.events[0]["motivo"]
