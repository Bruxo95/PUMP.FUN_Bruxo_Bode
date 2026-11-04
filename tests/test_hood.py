"""0.32.208 (pedido do dono): Robinhood Chain, etapa 1 só leitura, isolada. Sem internet: logs montados à mão."""
from app import hood
from tests.test_api import env  # noqa: F401  (fixture env)

TOK = "0x" + "ab" * 20
USER = "0x" + "11" * 20
USER2 = "0x" + "22" * 20
ROUTER = "0x" + "99" * 20


def _t(a: str) -> str:
    return "0x" + "0" * 24 + a[2:]


def _i(v: int) -> str:
    return format(v % (1 << 256), "064x")


def swap(tx: str, a0: int, a1: int, sender: str = ROUTER, idx: int = 1) -> dict:
    return {"transactionHash": tx, "logIndex": hex(idx), "blockNumber": "0x10", "address": hood.PM,
            "topics": [hood.T_SWAP, "0x" + "cd" * 32, _t(sender)], "data": "0x" + _i(a0) + _i(a1) + "0" * 64 * 6}


def transfer(tx: str, token: str, frm: str, to: str, amount: int) -> dict:
    return {"transactionHash": tx, "address": token, "topics": [hood.T_TRANSFER, _t(frm), _t(to)], "data": "0x" + _i(amount)}


def _dec(sw, trs, n=1, eth_usd=3000.0):
    return hood.decode(sw, list(hood.legs_of(trs).get(sw["transactionHash"], [])), n, eth_usd)


def test_buy_with_native_eth_goes_straight_to_the_wallet():
    s = swap("0xa", -int(0.1e18), 5_000 * 10**18)
    tr = _dec(s, [transfer("0xa", TOK, hood.PM, USER, 5_000 * 10**18)])
    assert tr["side"] == "buy" and tr["wallet"] == USER and tr["token"] == TOK and tr["quote"] == "ETH" and abs(tr["eth"] - 0.1) < 1e-9


def test_sell_through_the_router_finds_the_real_wallet():
    s = swap("0xb", int(0.2e18), -1_000 * 10**18)
    trs = [transfer("0xb", TOK, USER2, ROUTER, 1_000 * 10**18), transfer("0xb", TOK, ROUTER, hood.PM, 1_000 * 10**18)]
    tr = _dec(s, trs)
    assert tr["side"] == "sell" and tr["wallet"] == USER2 and abs(tr["eth"] - 0.2) < 1e-9


def test_weth_and_usdg_pairs_are_valued_in_eth():
    s = swap("0xc", -int(0.5e18), 10**21)
    tr = _dec(s, [transfer("0xc", hood.WETH, ROUTER, hood.PM, int(0.5e18)), transfer("0xc", TOK, hood.PM, USER, 10**21)])
    assert tr["quote"] == "ETH" and abs(tr["eth"] - 0.5) < 1e-9
    s = swap("0xd", -300 * 10**6, 10**21)
    tr = _dec(s, [transfer("0xd", hood.USDG, ROUTER, hood.PM, 300 * 10**6), transfer("0xd", TOK, hood.PM, USER, 10**21)])
    assert tr["quote"] == "USD" and abs(tr["eth"] - 0.1) < 1e-9          # 300 USDG ÷ 3.000 por ETH
    assert _dec(s, [transfer("0xd", hood.USDG, ROUTER, hood.PM, 300 * 10**6), transfer("0xd", TOK, hood.PM, USER, 10**21)], eth_usd=None) is None


def test_multi_pool_routes_and_unclear_trades_stay_out():
    s = swap("0xe", -int(0.1e18), 10**21)
    assert _dec(s, [transfer("0xe", TOK, hood.PM, USER, 10**21)], n=2) is None          # rota com 2 trocas
    assert _dec(s, []) is None                                                         # sem transferência do memecoin
    assert _dec(s, [transfer("0xe", TOK, hood.PM, ROUTER, 10**21)]) is None            # parou no roteador, sem carteira


def test_rank_follows_the_top_traders_rule():
    now = 1_000_000.0
    trades = []
    for i in range(25):
        tk = f"0x{i:040x}"
        trades.append({"t": now - 3000 + i, "wallet": USER, "token": tk, "side": "buy", "eth": 0.1, "amount": 100.0})
        trades.append({"t": now - 2000 + i, "wallet": USER, "token": tk, "side": "sell", "eth": 0.15, "amount": 100.0})
    trades.append({"t": now - 100, "wallet": USER2, "token": TOK, "side": "buy", "eth": 1.0, "amount": 1.0})
    r = hood.rank(trades, now, {"min_wallet_usd": 0, "online_min": 60}, {})
    top = r["rows"][0]
    assert top["wallet"] == USER and abs(top["realized_eth"] - 1.25) < 1e-6 and top["winrate"] == 100.0 and top["eligible"]
    assert r["copiaria"] == [USER]                     # o último trade dele foi há 33 min: online em 60 min
    r2 = hood.rank(trades, now, {"min_wallet_usd": 0, "online_min": 10}, {})
    assert r2["copiaria"] == [] and r2["aptos"] == 1
    other = next(x for x in r["rows"] if x["wallet"] == USER2)
    assert not other["eligible"] and any("trades" in f for f in other["flags"])


def test_clean_cfg_keeps_limits():
    c = hood.clean_cfg({"days": 7, "top_n": 999, "min_winrate": "x", "outra": 1})
    assert c["days"] == 1 and c["top_n"] == 50 and c["min_winrate"] == hood.CFG_DEFAULT["min_winrate"] and "outra" not in c


def test_usage_of_robinhood_is_not_counted_in_this_project():
    import asyncio
    from app import apiusage
    us = apiusage.Usage()

    async def go():
        tok = apiusage.ORIGIN.set(apiusage.HOOD_ORIGEM)
        try:
            us.count("api.dexscreener.com")
        finally:
            apiusage.ORIGIN.reset(tok)
    asyncio.run(go())
    assert not any(v for k, v in us.total.items() if k[0] == "DexScreener")


def test_hood_has_own_page_and_admin_only_routes(env):
    """Página própria (/hood), fora do painel da pump.fun e da BNB; rotas só do admin; na escolha da rede."""
    from tests.test_api import UA, UB, tok
    c = env["c"]
    page = c.get("/hood")
    assert page.status_code == 200 and "hood.js" in page.text and "app.js" not in page.text and "bnb.js" not in page.text
    assert page.headers.get("Cache-Control") == "no-cache"
    assert 'href="/hood"' in c.get("/entrar").text
    assert "hood.js" not in c.get("/app").text and "hood.js" not in c.get("/bnb").text
    assert c.get("/api/hood", headers=tok(UB, "b@x.com")).status_code == 403
    r = c.get("/api/hood", headers=tok(UA)).json()
    assert "ligado" in r
    assert c.post("/api/hood/cfg", json={"min_trades": 5}, headers=tok(UB, "b@x.com")).status_code == 403
