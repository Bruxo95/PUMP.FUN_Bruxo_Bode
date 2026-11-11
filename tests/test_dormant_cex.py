"""0.32.247 (pedido do dono): comprar em exchange pela API. Sem internet e sem chave de verdade."""
import asyncio
import pathlib
import urllib.parse
from decimal import Decimal

from app import dormant_buy as db_, dormant_cex as cx
from tests.test_dormant_compra import SENHA, UID, OUTRO, FakeNet, Resp, setup

cx.ORDEM_PASSO = 0
API, SEC = "fakeApiKey12345678", "fakeSecret12345678"


def run(c):
    return asyncio.run(c)


class Net(FakeNet):
    """Binance falsa, CoinGecko falsa."""

    def __init__(self):
        super().__init__()
        self.perms = {"enableWithdrawals": False, "enableSpotAndMarginTrading": True, "ipRestrict": True}
        self.usdt, self.asks, self.has_pair, self.orders, self.urls, self.filled, self.status_ordem, self.tickers = "100", [["0.02", "100000"]], True, [], [], ("1000", "20"), "EXPIRED", None

    async def get(self, url, params=None, headers=None, timeout=None):
        if "/tickers" in url:
            return Resp({"tickers": self.tickers if self.tickers is not None else [{"base": "TOK", "target": "USDT", "market": {"identifier": "binance", "name": "Binance"}, "converted_last": {"usd": 0.02}, "converted_volume": {"usd": 5000}, "bid_ask_spread_percentage": 0.2, "is_stale": False, "trade_url": "javascript:alert(1)"},
                                                                                 {"base": "TOK", "target": "BRL", "market": {"identifier": "mercado_bitcoin", "name": "MB"}, "trade_url": "https://mb.example/x"}]})
        if "ipify" in url:
            return Resp({"ip": "203.0.113.10"})
        return await super().get(url, params=params, headers=headers, timeout=timeout)

    async def request(self, method, url, headers=None, content=None, timeout=None):
        self.urls.append((method, url))
        u = urllib.parse.urlsplit(url)
        if u.path == "/sapi/v1/account/apiRestrictions":
            return Resp(self.perms)
        if u.path == "/api/v3/account":
            return Resp({"canTrade": True, "balances": [{"asset": "USDT", "free": self.usdt}]})
        if u.path == "/api/v3/exchangeInfo":
            return Resp({"symbols": [{"status": "TRADING", "filters": [{"filterType": "PRICE_FILTER", "tickSize": "0.0001"}, {"filterType": "LOT_SIZE", "stepSize": "1", "minQty": "1"}, {"filterType": "NOTIONAL", "minNotional": "1"}]}] if self.has_pair else []})
        if u.path == "/api/v3/depth":
            return Resp({"asks": self.asks})
        if u.path == "/api/v3/order" and method == "POST":
            q = dict(urllib.parse.parse_qsl(u.query))
            self.orders.append(q)
            return Resp({"orderId": 77})
        if u.path == "/api/v3/order":
            return Resp({"executedQty": self.filled[0], "cummulativeQuoteQty": self.filled[1], "status": self.status_ordem})
        raise AssertionError(url)


def ready(net=None, on=True):
    b, net, db = setup(net or Net())
    c = cx.CexBuyer(b)
    run(c.save_key(UID, "binance", API, SEC, "", SENHA, False))
    if on:
        run(b.set_on(UID, True, SENHA, "LIGAR"))
    return c, b, net, db


# ------------------------------------------------------------------ assinaturas: exemplos oficiais das documentações
def test_binance_signature_matches_official_example():
    s = "NhqPtmdSJYdKjVHjA7PZj4Mge3R5YNiP1e3UZjInClVN65XAbvqqM6A7H5fATj0j"
    q = "symbol=LTCBTC&side=BUY&type=LIMIT&timeInForce=GTC&quantity=1&price=0.1&recvWindow=5000&timestamp=1499827319559"
    assert cx.hmac_hex(s, q) == "c8db56825ae71d6d79447849e617115f4a920fa2acdcab2b053c4b2838bd6b71"


# ------------------------------------------------------------------ chave
def test_key_with_withdrawal_is_refused_and_not_stored():
    net = Net()
    net.perms["enableWithdrawals"] = True
    b, net, db = setup(net)
    try:
        run(cx.CexBuyer(b).save_key(UID, "binance", API, SEC, "", SENHA, True))     # marcar a caixinha não adianta: a API disse que saca
        raise AssertionError
    except db_.BuyError as e:
        assert "SACAR" in str(e)
    assert db.tables["dormant_cex_keys"] == []


def test_key_without_trade_refused_and_mexc_needs_confirmation():
    net = Net()
    net.perms["enableSpotAndMarginTrading"] = False
    b, net, db = setup(net)
    try:
        run(cx.CexBuyer(b).save_key(UID, "binance", API, SEC, "", SENHA, False))
        raise AssertionError
    except db_.BuyError as e:
        assert "negociar" in str(e)
    try:
        run(cx.CexBuyer(b).save_key(UID, "mexc", API, SEC, "", SENHA, False))
        raise AssertionError
    except db_.BuyError as e:
        assert "sem saque" in str(e)
    assert run(cx.CexBuyer(b).save_key(UID, "mexc", API, SEC, "", SENHA, True))["info"]["saque_conferido"] is False


def test_secret_never_stored_clear_nor_returned_and_needs_password_of_vault():
    c, b, net, db = ready()
    t = str(db.tables["dormant_cex_keys"])
    assert SEC not in t and API not in t and SENHA not in t
    st = run(c.state(UID))
    assert SEC not in str(st) and API not in str(st) and "cifra" not in str(st)
    assert run(c.state(OUTRO))["exchanges"][0]["rotulo"] is None
    try:
        run(c.save_key(UID, "mexc", API, SEC, "", "outra-senha-99", True))
        raise AssertionError
    except db_.BuyError as e:
        assert "errada" in str(e)
    assert run(b.change_password(UID, SENHA, "senha-nova-123")) == 1
    assert run(c._keys(UID, "binance", "senha-nova-123"))["secret"] == SEC


def test_no_withdraw_code_exists():
    src = pathlib.Path("app/dormant_cex.py").read_text(encoding="utf-8").lower()
    for bad in ("/withdraw", "wallet/withdraw", "asset/withdraw", "capital/withdraw", '"type": "market"', '"ordertype": "market"', '"ordtype": "market"'):
        assert bad not in src, bad


# ------------------------------------------------------------------ onde vende
def test_offers_filter_unsafe_link_and_mark_supported():
    c, b, net, _ = ready()
    b.watch.pick["tok"] = "tok-cg"
    r = run(c.offers("tok"))["lista"]
    assert r[0]["ex"] == "binance" and r[0]["url"] is None        # javascript: não vira link
    assert r[1]["ex"] is None and r[1]["url"] == "https://mb.example/x"


# ------------------------------------------------------------------ compra
def test_buy_is_limit_ioc_never_market_and_never_spends_more_than_asked():
    c, b, net, db = ready()
    p = run(c.preview(UID, "tok", "binance", 20, SENHA))
    assert p.get("quote_id"), p["bloqueia"]
    assert p["maximo"] == 0.0206 and p["par"] == "TOK/USDT"
    r = run(c.buy(UID, p["quote_id"], SENHA, "COMPRAR"))
    assert r["status"] == "confirmada" and r["qty"] == 1000 and r["px_in"] == 0.02
    o = net.orders[0]
    assert o["type"] == "LIMIT" and o["timeInForce"] == "IOC" and o["side"] == "BUY" and o["symbol"] == "TOKUSDT"
    assert Decimal(o["price"]) * Decimal(o["quantity"]) <= 20
    assert SEC not in str(db.tables["dormant_buys"])


def test_stale_pair_is_blocked_by_the_exchange_itself():
    net = Net()
    net.has_pair = False
    c, b, net, _ = ready(net)
    p = run(c.preview(UID, "tok", "binance", 20, SENHA))
    assert not p.get("quote_id") and any("não negocia" in x for x in p["bloqueia"])


def test_blocks_limits_balance_off_and_expensive():
    c, b, net, _ = ready()
    p = run(c.preview(UID, "tok", "binance", 50, SENHA))
    assert any("limite por compra em exchange" in x for x in p["bloqueia"])
    net.usdt = "1"
    p = run(c.preview(UID, "tok", "binance", 20, SENHA))
    assert any("saldo insuficiente" in x for x in p["bloqueia"]) and not p.get("quote_id")
    net.usdt = "100"
    net.asks = [["0.03", "100000"]]
    p = run(c.preview(UID, "tok", "binance", 20, SENHA))
    assert any("acima da CoinGecko" in x for x in p["bloqueia"])
    net.asks = [["0.02", "100000"]]
    run(b.set_on(UID, False))
    assert any("desligadas" in x for x in run(c.preview(UID, "tok", "binance", 20, SENHA))["bloqueia"])


def test_price_moved_up_sends_nothing_and_quote_rules():
    c, b, net, _ = ready()
    p = run(c.preview(UID, "tok", "binance", 20, SENHA))
    for fn, w in ((b.buy, "COMPRAR"), (b.sell, "VENDER")):
        try:
            run(fn(UID, p["quote_id"], SENHA, w))
            raise AssertionError
        except db_.BuyError:
            pass
    net.asks = [["0.05", "100000"]]
    try:
        run(c.buy(UID, p["quote_id"], SENHA, "COMPRAR"))
        raise AssertionError
    except db_.BuyError as e:
        assert "nada foi enviado" in str(e)
    assert not net.orders
    net.asks = [["0.02", "100000"]]
    p = run(c.preview(UID, "tok", "binance", 20, SENHA))
    run(c.buy(UID, p["quote_id"], SENHA, "COMPRAR"))
    try:
        run(c.buy(UID, p["quote_id"], SENHA, "COMPRAR"))
        raise AssertionError
    except db_.BuyError:
        pass
    assert len(net.orders) == 1


def test_no_fill_is_reported_and_exchange_limit_is_separate():
    net = Net()
    net.filled = ("0", "0")
    c, b, net, db = ready(net)
    p = run(c.preview(UID, "tok", "binance", 20, SENHA))
    r = run(c.buy(UID, p["quote_id"], SENHA, "COMPRAR"))
    assert r["status"] == "falhou" and "nada foi comprado" in r["motivo"]
    net.filled = ("1000", "20")
    p = run(c.preview(UID, "tok", "binance", 20, SENHA))
    run(c.buy(UID, p["quote_id"], SENHA, "COMPRAR"))
    assert run(c.spent(UID)) == 20 and run(b.spent_today(UID)) == 0 and run(b.gas_spent_today(UID)) == 0


def test_history_shows_exchange_and_blocks_sell_here():
    c, b, net, db = ready()
    p = run(c.preview(UID, "tok", "binance", 20, SENHA))
    run(c.buy(UID, p["quote_id"], SENHA, "COMPRAR"))
    h = run(b.history(UID))
    it = h["itens"][0]
    assert it["rede_nome"] == "Binance" and it["cex"] is True and it["moeda"] == "USDT" and it["expl"] is None
    try:
        run(b.preview_sell(UID, it["id"], 100))
        raise AssertionError
    except db_.BuyError:
        pass


def test_exchange_names_match_and_migration_closed():
    assert db_.CEX_NOMES == {k: v["nome"] for k, v in cx.EXCHANGES.items()}
    sql = pathlib.Path("supabase/migrations/20261106000004_dormant_cex.sql").read_text(encoding="utf-8")
    assert "enable row level security" in sql and "revoke all on public.dormant_cex_keys from anon, authenticated" in sql and "create policy" not in sql


def test_walk_book_respects_cap():
    asks = [(Decimal("1"), Decimal("5")), (Decimal("2"), Decimal("5")), (Decimal("9"), Decimal("100"))]
    w = cx.walk_book(asks, Decimal("100"), Decimal("2"))
    assert w["qty"] == 10 and w["gasto"] == 15 and w["sobra"] == 85



def test_mexc_guide_marks_only_what_the_panel_uses():
    """0.32.317 (pedido do dono, prints da tela da MEXC de 11/11): botão "Ver o que marcar" com as caixas da MEXC. Só as 3 que o
    painel usa (saldo, ordem, ler a ordem) vêm marcadas; saque, transferência, futuros e P2P ficam desmarcados."""
    import re
    js = open("web/dormant.js", encoding="utf-8").read()
    g = js[js.index("const XGUIDE = {"):js.index("    nonkyc: {")]
    marcadas = re.findall(r'\["([^"]+)", true', g)
    assert marcadas == ["View Account Details", "View Order Details", "Trade"]
    for nome in ("Withdraw", "Transfer", "Order Placing", "Place order", "Advertiser", "Edit Account Info"):
        assert f'["{nome}", false' in g
    assert "data-xguide" in js and "X_IP = r.ip" in js


# ------------------------------------------------------------------ 0.32.318: NonKYC e volume de 24 h
def test_nonkyc_signature_follows_the_documentation_example():
    """https://api.nonkyc.io/openapi.json: hmac.new(secret, f"{apiKey}{url}{json_body}{nonce}", sha256).hexdigest()."""
    import hashlib
    import hmac
    url, body, nonce = "https://api.nonkyc.io/api/v2/cancelorder", '{"id":"5845454765457"}', "1700000000000"
    want = hmac.new(SEC.encode(), (API + url + body + nonce).encode(), hashlib.sha256).hexdigest()
    assert cx.nonkyc_sign(API, url, body, nonce, SEC) == want


class NkNet(Net):
    def __init__(self):
        super().__init__()
        self.nk_orders, self.cancels, self.nk_active = [], [], True

    async def get(self, url, params=None, headers=None, timeout=None):
        if url.endswith("/exchanges"):
            return Resp([{"id": "nonkyc_io", "trade_volume_24h_btc": 200}, {"id": "binance", "trade_volume_24h_btc": 80000}, {"id": "outra", "trade_volume_24h_btc": 1}])
        if url.endswith("/simple/price") and (params or {}).get("ids") == "bitcoin":
            return Resp({"bitcoin": {"usd": 70000.0}})
        if "/tickers" in url:
            r = await super().get(url, params, headers, timeout)
            r._js["tickers"].append({"base": "TOK", "target": "USDT", "market": {"identifier": "nonkyc_io", "name": "Nonkyc.io"}, "converted_last": {"usd": 0.02}})
            return r
        return await super().get(url, params=params, headers=headers, timeout=timeout)

    async def request(self, method, url, headers=None, content=None, timeout=None):
        u = urllib.parse.urlsplit(url)
        if u.netloc != "api.nonkyc.io":
            return await super().request(method, url, headers, content, timeout)
        self.urls.append((method, url))
        p = u.path[len("/api/v2"):]
        if p == "/market/info":
            return Resp({"symbol": "TOK/USDT", "isActive": True, "isPaused": False, "priceDecimals": 4, "quantityDecimals": 0})
        if p == "/market/orderbook":
            return Resp({"asks": [{"price": "0.02", "quantity": "100000"}]})
        assert headers["X-API-KEY"] == API and headers["X-API-SIGN"] == cx.nonkyc_sign(API, url, content or "", headers["X-API-NONCE"], SEC)
        if p == "/balances":
            return Resp([{"asset": "USDT", "available": self.usdt}, {"asset": "BTC", "available": "1"}])
        if p == "/createorder":
            import json
            self.nk_orders.append(json.loads(content))
            return Resp({"id": "nk1"})
        if p == "/getorder/nk1":
            return Resp({"id": "nk1", "price": "0.0202", "executedQuantity": "400", "isActive": self.nk_active, "status": "Partly Filled" if self.nk_active else "Cancelled", "createdAt": 1})
        if p == "/cancelorder":
            self.cancels.append(content)
            self.nk_active = False
            return Resp({"success": True, "id": "nk1"})
        if p == "/account/trades":
            return Resp([{"orderid": "nk1", "totalWithFee": "8.02"}, {"orderid": "outra", "totalWithFee": "99"}])
        raise AssertionError(url)


def test_nonkyc_buy_is_limit_then_cancels_the_rest_and_reads_the_real_cost():
    cx.NK_CANCEL_S = 0
    b, net, db = setup(NkNet())
    c = cx.CexBuyer(b)
    try:
        run(c.save_key(UID, "nonkyc", API, SEC, "", SENHA, False))
        raise AssertionError("sem a confirmação de saque não pode salvar")
    except db_.BuyError as e:
        assert "não diz pela API" in str(e)
    run(c.save_key(UID, "nonkyc", API, SEC, "", SENHA, True))
    run(b.set_on(UID, True, SENHA, "LIGAR"))
    q = run(c.preview(UID, "tok", "nonkyc", 10, SENHA))
    assert not q["bloqueia"] and q["par"] == "TOK/USDT", q
    r = run(c.buy(UID, q["quote_id"], SENHA, "COMPRAR"))
    o = net.nk_orders[0]
    assert o["type"] == "limit" and o["side"] == "buy" and o["symbol"] == "TOK/USDT" and o["strictValidate"] is True
    assert float(o["price"]) * float(o["quantity"]) <= 10.0001
    assert net.cancels and '"nk1"' in net.cancels[0]                  # o resto da ordem foi cancelado
    assert r["status"] == "confirmada" and r["qty"] == 400 and abs(r["usd_in"] - 8.02) < 1e-9


def test_exchange_volume_in_dollars_is_shown_per_exchange():
    b, net, db = setup(NkNet())
    st = run(cx.CexBuyer(b).state(UID))
    v = {x["id"]: x["vol24_usd"] for x in st["exchanges"]}
    assert v["nonkyc"] == 14_000_000 and v["binance"] == 5_600_000_000 and v["mexc"] is None
    assert next(x for x in st["exchanges"] if x["id"] == "nonkyc")["cg_url"].endswith("/exchanges/nonkyc-io")


def test_nonkyc_guide_picks_read_and_trading_only():
    js = open("web/dormant.js", encoding="utf-8").read()
    g = js[js.index("    nonkyc: {"):js.index("let X_IP")]
    assert '["Read + Trading Access", true' in g and '["Read Only Access", false' in g and '["Read + Trading + Withdraw Access", false' in g
