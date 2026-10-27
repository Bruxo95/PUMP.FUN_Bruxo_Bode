"""Medidor de uso das APIs (0.31.76)."""
from app.apiusage import Usage, key_tag
from app.explore import item


def test_usage_counts_month_and_minute():
    u = Usage()
    t = 1_793_000_000.0
    for i in range(5):
        u.count("data.solanatracker.io", "chave-secreta", now=t + i)
    u.count("api.dexscreener.com", None, now=t)
    u.count("vnvfluimpqvxbvdbmwqa.supabase.co", None, now=t)          # banco próprio não conta
    v = {x["api"]: x for x in u.view({key_tag("chave-secreta"): "chave do sistema"}, now=t + 10)}
    st = v["Solana Tracker"]
    assert st["mes"] == 5 and st["limite_mes"] == 10_000 and st["chave"] == "chave do sistema" and st["pico_min"] == 5
    assert "DexScreener" in v and not any("supabase" in k for k in v)
    assert "chave-secreta" not in str(u.dump())                       # a chave nunca é guardada


def test_explore_item_has_24h_volume():
    x = item({"token": {"mint": "M", "symbol": "S"}, "pools": [{"liquidity": {"usd": 1}, "txns": {"buys": 3, "sells": 1, "volume24h": 1234.5}}]}, "graduated")
    assert x["vol24_usd"] == 1234.5


def test_dexscreener_pools_per_token(tmp_path):
    """0.31.77 (caso LILY): cada pool do token com volume e compras × vendas de 24 h."""
    import asyncio
    from tests.test_pump import _pump
    pf = _pump(tmp_path, paid=False)
    m = "Lily".ljust(40, "1") + "pump"

    class R:
        status_code = 200

        def json(self):
            return [{"baseToken": {"address": m, "symbol": "LILY"}, "quoteToken": {"symbol": "SOL"}, "dexId": "pumpswap",
                     "volume": {"h24": 267.69}, "txns": {"h24": {"buys": 548, "sells": 3}}, "liquidity": {"usd": 9000}},
                    {"baseToken": {"address": m, "symbol": "LILY"}, "quoteToken": {"symbol": "SOL"}, "dexId": "meteora",
                     "volume": {"h24": 0.1}, "txns": {"h24": {"buys": 12, "sells": 8}}, "liquidity": {"usd": 50}}]

    class H:
        async def get(self, *a, **k):
            return R()
    pf.http = H()
    asyncio.run(pf._fetch_prices([m], set_price=False))
    P = pf.tokens[m]["pools"]
    assert [p["dex"] for p in P] == ["pumpswap", "meteora"] and P[0]["buys24"] == 548 and P[1]["vol24"] == 0.1
