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
        if url.endswith("/coins/categories"):
            return Resp([{"id": "meme-token", "name": "Meme", "market_cap": 9e9},
                         {"id": "solana-ecosystem", "name": "Solana Ecosystem", "market_cap": 5e10, "volume_24h": 1e9, "market_cap_change_24h": 2.0},
                         {"id": "tron-ecosystem", "name": "Tron Ecosystem", "market_cap": 9e10, "volume_24h": 2e9, "market_cap_change_24h": -1.0}])
        if url.endswith("/coins/markets"):
            assert params["category"] == "tron-ecosystem"
            return Resp([_row("sobe", h1=9), _row("cai", h24=-30), _row("quieta", vol=10), _row("tron")])
        return Resp({}, 404)


def run(c):
    return asyncio.run(c)


def test_only_ecosystems_listed_biggest_first_and_name_without_word():
    w = dormant.DormantWatch(Net(), None)
    L = run(w.eco_list())
    assert [e["id"] for e in L] == ["tron-ecosystem", "solana-ecosystem"] and L[0]["nome"] == "Tron"


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
    for bad in ("meme-token", "../x", "nada-ecosystem"):
        try:
            run(w.eco_coins(bad))
            raise AssertionError("aceitou " + bad)
        except ValueError:
            pass
