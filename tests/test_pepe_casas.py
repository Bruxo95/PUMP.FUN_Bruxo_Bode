"""0.32.65 — caso PEPE do Bruxo (29/10): token fora da pump.fun com 4 casas decimais era cotado como se tivesse 6
(preço 100× acima, stop móvel em "+9547%" falso) e o RPC da carteira sem JSON matava a venda com "Expecting value".
Sem internet."""
import asyncio
import json

import httpx

from tests.test_pump import _pump

PEPE = "PEPEqnuuCDbBC89p1u9vpnP1KQ2oj1xTcQBsjt9X55m"


def _net(dec=4, seen=None):
    def h(req):
        if req.url.host == "lite-api.jup.ag":
            amt = int(req.url.params["amount"])
            if seen is not None:
                seen.append(amt)
            # preço de verdade: 5e-8 SOL por token (4 casas → 1 token = 10^4 unidades)
            return httpx.Response(200, json={"outAmount": str(int(amt / 10 ** dec * 5e-8 * 1e9)), "inAmount": str(amt)})
        body = json.loads(req.content)
        if body["method"] == "getTokenSupply":
            return httpx.Response(200, json={"result": {"value": {"decimals": dec, "uiAmountString": "1"}}})
        return httpx.Response(404)
    return httpx.AsyncClient(transport=httpx.MockTransport(h))


def test_quote_uses_the_token_real_decimals(tmp_path):
    from app.jupiter import JupiterQuoter
    pf = _pump(tmp_path, paid=False)
    pf.http = _net(seen=(seen := []))
    pf.market.jup = JupiterQuoter(pf.http, per_min=10_000)
    asyncio.run(pf._pumpswap_prices([PEPE], qty={PEPE: 1_975_000}))
    assert seen == [1_975_000 * 10 ** 4]                  # antes: × 10^6 (100× os tokens da posição)
    px = pf.tokens[PEPE]["price"]
    assert 4.9e-8 < px < 5.3e-8 and pf.tokens[PEPE]["decimals"] == 4


def test_fake_peak_is_cleared_when_decimals_are_fixed(tmp_path):
    pf = _pump(tmp_path, paid=False, pump_trail_enabled=True)
    p = {"id": "p1", "mint": PEPE, "symbol": "PEPE", "wallet": "W", "sol_in": 0.1, "tokens": 2e6, "tokens_left": 2e6,
         "price_in": 5e-8, "open_t": 0, "trail_peak": 10014.6, "trail_exit": 10004.6, "best_pct": 10014.6}
    pf._save_pos(p)
    tk = pf.tokens.setdefault(PEPE, {})
    tk.update(price=5.1e-8, last_t=1e12, decimals=4, dec_fix_t=1.0)
    pf._check_stops(PEPE, 1e9)
    open_p = [x for x in pf.positions() if x["mint"] == PEPE]
    assert open_p and open_p[0].get("trail_peak") is None and float(open_p[0].get("best_pct") or 0) < 100
    assert any(f.get("action") == "preço corrigido" for f in pf.store.feed_items())


def test_wallet_rpc_without_json_explains_and_uses_public_rpc():
    from app.jupiter import PUBLIC_RPC, JupiterQuoter, JupiterWallet
    hosts = []

    def h(req):
        hosts.append(str(req.url).rstrip("/"))
        if str(req.url).rstrip("/") == PUBLIC_RPC:
            return httpx.Response(200, json={"result": "assinatura"})
        return httpx.Response(429, text="<html>Too Many Requests</html>")

    http = httpx.AsyncClient(transport=httpx.MockTransport(h))

    class W:
        address = "Bot1111111111111111111111111111111111111111"

        async def safe_rpc_url(self):
            return "https://meu-rpc.exemplo.com"

    jw = JupiterWallet(http, W(), JupiterQuoter(http))
    assert asyncio.run(jw._rpc("sendTransaction", ["x"])) == "assinatura"
    assert hosts == ["https://meu-rpc.exemplo.com", PUBLIC_RPC]

    http2 = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(429, text="")))
    jw2 = JupiterWallet(http2, W(), JupiterQuoter(http2))
    try:
        asyncio.run(jw2._rpc("sendTransaction", ["x"]))
        raise AssertionError("devia falhar")
    except RuntimeError as e:
        assert "HTTP 429" in str(e) and "Expecting value" not in str(e)
