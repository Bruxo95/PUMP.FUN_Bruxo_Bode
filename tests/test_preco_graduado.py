"""0.32.28 (print do dono, 28/10): token que já graduou não usa o par antigo da curva ("pumpfun") da DexScreener para o
preço — antes ele ganhava do par da PumpSwap pela liquidez e o preço ficava parado no preço final da curva."""
import asyncio

import httpx

from tests.test_pump import _pump

M = "Grad".ljust(40, "1") + "pump"
SOL = "So11111111111111111111111111111111111111112"


def test_graduated_token_price_comes_from_pumpswap_pair(tmp_path):
    pf = _pump(tmp_path, paid=False)
    pairs = [{"baseToken": {"address": M}, "quoteToken": {"address": SOL}, "dexId": "pumpfun", "priceNative": "0.00000041088",
              "liquidity": {"usd": 90000}, "pairAddress": "CURVA"},
             {"baseToken": {"address": M}, "quoteToken": {"address": SOL}, "dexId": "pumpswap", "priceNative": "0.0000009",
              "liquidity": {"usd": 30000}, "pairAddress": "POOL"}]
    pf.http = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=pairs)))
    pf.tokens[M] = {"pool": "pumpswap", "created_t": 1}
    asyncio.run(pf._fetch_prices([M]))
    assert abs(pf.tokens[M]["price"] - 0.0000009) < 1e-12
