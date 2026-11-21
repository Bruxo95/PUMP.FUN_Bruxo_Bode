"""0.32.425 (pedido do dono): Alertas da blockchain — categorias "Ecosystem" da CoinGecko e as moedas de cada uma, com a mesma conta
dos Alertas. Sem internet: respostas falsas."""
import asyncio

from app import dormant


class Resp:
    def __init__(self, js, status=200):
        self._js, self.status_code = js, status

    def json(self):
        return self._js


def _row(cid, h1=0.0, h24=0.0, vol=50_000, cap=1_000_000):
    return {"id": cid, "name": cid.title(), "symbol": cid[:3], "image": "", "current_price": 1.0, "total_volume": vol, "market_cap": cap,
            "market_cap_rank": 10, "price_change_percentage_1h_in_currency": h1, "price_change_percentage_24h_in_currency": h24,
            "price_change_percentage_7d_in_currency": 0, "price_change_percentage_30d_in_currency": 0,
            "sparkline_in_7d": {"price": [1.0 + (i % 2) * 0.2 for i in range(168)]}}


class Net:
    def __init__(self):
        self.calls = []

    async def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        if url.endswith("/coins/categories/list"):
            return Resp([{"category_id": "meme-token", "name": "Meme"}, {"category_id": "x402-ecosystem", "name": "x402 Ecosystem"},
                         {"category_id": "solana-ecosystem", "name": "Solana Ecosystem"}, {"category_id": "tron-ecosystem", "name": "Tron Ecosystem"},
                         {"category_id": "binance-smart-chain", "name": "BNB Chain Ecosystem"}, {"category_id": "polygon-ecosystem", "name": "Polygon Ecosystem"}])
        if url.endswith("/asset_platforms"):
            return Resp([{"id": "solana", "name": "Solana"}, {"id": "tron", "name": "TRON"}, {"id": "binance-smart-chain", "name": "BNB Smart Chain"},
                         {"id": "polygon-pos", "name": "Polygon", "shortname": "MATIC"}])
        if url.endswith("/coins/list"):
            return Resp([{"id": "a", "name": "A", "symbol": "a", "platforms": {"solana": "x", "tron": "y"}}, {"id": "b", "name": "B", "symbol": "b", "platforms": {"solana": "z"}}])
        if url.endswith("/coins/markets"):
            assert params["category"] == "tron-ecosystem"
            return Resp([_row("sobe", h1=9), _row("cai", h24=-30), _row("quieta", vol=10), _row("tron")])
        return Resp({}, 404)


def run(c):
    return asyncio.run(c)


def test_only_real_networks_most_tokens_first():
    # 0.32.426: só categorias que são rede (batem com /asset_platforms); x402 e Meme ficam fora; mais tokens primeiro
    w = dormant.DormantWatch(Net(), None)
    L = run(w.eco_list())
    ids = [e["id"] for e in L]
    assert "x402-ecosystem" not in ids and "meme-token" not in ids
    # 0.32.429: as 30 maiores em ordem fixa (BNB antes de Solana, Tron, Polygon), sem precisar da lista inteira de moedas
    assert ids == ["binance-smart-chain", "solana-ecosystem", "tron-ecosystem", "polygon-ecosystem"] and all(e["top"] for e in L)
    assert L[1]["nome"] == "Solana"


def test_coins_of_a_chain_use_the_same_rules_and_are_cached():
    net = Net()
    w = dormant.DormantWatch(net, None)
    w.pick = {"tron": "tron"}
    r = run(w.eco_coins("tron-ecosystem"))
    st = {x["id"]: x["status"] for x in r["itens"]}
    assert st["sobe"] == "pump" and st["cai"] == "dump" and st["quieta"] == "parada"
    assert r["contagem"]["pump"] == 1 and r["nome"] == "Tron"
    tron = next(x for x in r["itens"] if x["id"] == "tron")
    assert tron["ja_tem"] and tron["key"] == "tron" and not next(x for x in r["itens"] if x["id"] == "sobe")["ja_tem"]
    n = len(net.calls)
    run(w.eco_coins("tron-ecosystem"))
    assert len(net.calls) == n                                     # 10 min guardado: não pergunta de novo


def test_unknown_or_bad_category_is_refused():
    w = dormant.DormantWatch(Net(), None)
    for bad in ("meme-token", "../x", "nada-ecosystem", "x402-ecosystem"):
        try:
            run(w.eco_coins(bad))
            raise AssertionError("aceitou " + bad)
        except ValueError:
            pass
