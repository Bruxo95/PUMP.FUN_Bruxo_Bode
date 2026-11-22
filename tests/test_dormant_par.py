"""0.32.430 (pedido do dono, caso ASTEROID 22/11): dar o par na mão a uma moeda "sem par" colando o link da CoinGecko, da DEX ou o contrato.
Sem internet: respostas falsas."""
import asyncio

import httpx

from app import dormant


def _row(cid, px=0.00022):
    return {"id": cid, "name": cid.title(), "symbol": cid[:3], "current_price": px, "total_volume": 5_000, "market_cap": 220_000,
            "price_change_percentage_1h_in_currency": 0, "price_change_percentage_24h_in_currency": 0,
            "price_change_percentage_7d_in_currency": 0, "price_change_percentage_30d_in_currency": 0,
            "sparkline_in_7d": {"price": [px * (1 + (i % 2) * 0.2) for i in range(168)]}}

MINT = "4UeLCRqARmfb6e6KQijtiktqqXUxbfk6jZng7DhuBAGS"
POOL = "A9aWUTdyVV1RrCWWg4mWBMFmAsaPPpR8c5pJEnpxovBj"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SOL = "So11111111111111111111111111111111111111112"


def _watch(calls):
    def handler(req):
        calls.append(str(req.url))
        if req.url.path.endswith("/coins/list"):
            return httpx.Response(200, json=[{"id": "asteroid-the-space-shiba-inu", "name": "Asteroid The Space Shiba Inu", "symbol": "asteroid",
                                              "platforms": {"solana": MINT}},
                                             {"id": "outra", "name": "Outra", "symbol": "out", "platforms": {}}])
        if req.url.host == "api.dexscreener.com":
            return httpx.Response(200, json={"pairs": [{"chainId": "solana", "dexId": "meteora", "pairAddress": POOL, "liquidity": {"usd": 9000},
                                                        "baseToken": {"address": MINT, "symbol": "ASTEROID"}, "quoteToken": {"address": SOL, "symbol": "SOL"}}]})
        if req.url.path.endswith("/coins/markets"):
            return httpx.Response(200, json=[_row(i) for i in req.url.params["ids"].split(",")])
        return httpx.Response(404)
    w = dormant.DormantWatch(httpx.AsyncClient(transport=httpx.MockTransport(handler)), None)
    w.lista = [{"cmc": "asteroid", "nome": "Asteroid Shiba"}]
    w.stat["leitura_t"] = 1.0
    return w


def test_link_addrs_skip_sol_and_usdc():
    url = f"https://jup.ag/swap?buy={MINT}&sell={USDC}"
    assert dormant.link_addrs(url) == [MINT]
    assert dormant.link_addrs(f"https://dexscreener.com/solana/{POOL}") == [POOL]
    assert dormant.link_addrs(f"https://dexscreener.com/solana/{POOL.lower()}")[0] == POOL.lower()


def test_jupiter_link_finds_coin_by_contract_without_dexscreener():
    calls = []
    w = _watch(calls)
    out = asyncio.run(w.search(f"https://jup.ag/swap?buy={MINT}&sell={USDC}"))
    assert [x["id"] for x in out] == ["asteroid-the-space-shiba-inu"] and out[0]["achado_por_contrato"] is not None
    assert not any("dexscreener" in c for c in calls)


def test_pool_link_uses_dexscreener_and_saves_manual_pool():
    calls = []
    w = _watch(calls)
    assert w.item(w.todas()[0])["status"] == "sem_cg"
    out = asyncio.run(w.search(f"https://dexscreener.com/solana/{POOL.lower()}"))
    assert out[0]["id"] == "asteroid-the-space-shiba-inu" and out[0]["pool"]["rede"] == "Solana"
    r = asyncio.run(w.set_link("asteroid", "asteroid-the-space-shiba-inu", usar_pool=True))
    assert r["pool"]["pool"] == POOL and w.links == {"asteroid": "asteroid-the-space-shiba-inu"}
    assert w.pick["asteroid"] == "asteroid-the-space-shiba-inu"          # preço buscado na hora
    it = w.item(w.todas()[0])
    assert it["status"] != "sem_cg" and it["par_manual"] and it["pool_manual"]
    assert w.target("asteroid-the-space-shiba-inu") == ("solana", "solana", MINT)
    asyncio.run(w.refresh_map())                                          # a leitura semanal não desfaz o par escolhido
    assert w.map["asteroid"] == ["asteroid-the-space-shiba-inu"]
    assert asyncio.run(w.clear_link("asteroid")) and "asteroid" not in w.links and not w.gtpool


def test_pool_hint_only_from_server_search():
    w = _watch([])
    r = asyncio.run(w.set_link("asteroid", "asteroid-the-space-shiba-inu", usar_pool=True))
    assert r["pool"] is None                                              # sem busca antes, o navegador não consegue impor um pool


def test_set_link_refuses_unknown_coin_and_key():
    w = _watch([])
    for key, cid in (("nao-existe", "outra"), ("asteroid", "nao-tem")):
        try:
            asyncio.run(w.set_link(key, cid))
            assert False
        except ValueError:
            pass
