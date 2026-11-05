"""0.32.220 (pedido do dono): quantas requisições de cada API cada posição gasta, ao vivo e guardado no trade fechado."""
import asyncio

from app import apiusage
from app.apiusage import Usage


def _reset():
    apiusage.MINT_USE.clear()


def test_a_shared_request_is_split_between_the_coins():
    _reset()
    u = Usage()

    async def go():
        u.count("mainnet.helius-rpc.com", body=b'{"method":"getMultipleAccounts"}')
    asyncio.run(apiusage.for_mints(["A", "B"], go()))
    a = apiusage.mint_used("A", {}, apiusage.BOOT)
    assert a["apis"][0]["api"] == "Helius (RPC da Solana)" and a["apis"][0]["requisicoes"] == 0.5
    assert not apiusage.mint_used("C", {}, apiusage.BOOT)["apis"]


def test_usage_counts_only_since_the_position_opened_and_restart_is_partial():
    _reset()
    u = Usage()

    async def one(host):
        u.count(host)
    asyncio.run(apiusage.for_mints(["A"], one("api.dexscreener.com")))
    base = apiusage.mint_snapshot("A")
    asyncio.run(apiusage.for_mints(["A"], one("api.dexscreener.com")))
    asyncio.run(apiusage.for_mints(["A"], one("data.solanatracker.io")))
    r = apiusage.mint_used("A", base, apiusage.BOOT)
    got = {x["api"]: x["requisicoes"] for x in r["apis"]}
    assert got == {"DexScreener": 1.0, "Solana Tracker": 1.0} and not r["parcial"]
    assert apiusage.mint_used("A", base, apiusage.BOOT - 1)["parcial"]       # servidor reiniciou depois que abriu


def test_request_outside_a_coin_context_counts_for_no_coin():
    _reset()
    Usage().count("api.dexscreener.com")
    assert apiusage.MINT_USE == {}
