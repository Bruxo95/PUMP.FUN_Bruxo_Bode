"""0.32.405 (pedido do dono): gráfico de 3 meses, 1 ano e tudo na janela da moeda. Sem internet."""
import asyncio

from tests.test_dormant_compra import setup


def run(c):
    return asyncio.run(c)


def watch():
    b, net, db = setup()
    return b.watch


def test_long_chart_uses_coingecko_and_keeps_it_for_an_hour():
    w, chamadas = watch(), []

    async def get(path, params=None):
        chamadas.append((path, params["days"]))
        return {"prices": [[1700000000000, 1.0], [1700086400000, 2.0]], "total_volumes": [[1700000000000, 10.0], [1700086400000, 20.0]]}
    w.get = get
    g = run(w.chart_long("tok", "365"))
    assert g["fonte"] == "CoinGecko" and g["precos"] == [[1700000000, 1.0], [1700086400, 2.0]] and g["volumes"][1] == [1700086400, 20.0]
    assert run(w.chart_long("tok", "365")) == g and chamadas == [("/coins/tok-cg/market_chart", "365")]     # segunda vez vem da memória


def test_all_time_falls_back_to_the_dex_pool_when_coingecko_refuses():
    w = watch()

    async def get(path, params=None):
        raise RuntimeError("CoinGecko respondeu HTTP 401")

    async def gt_get(path):
        assert "/ohlcv/day?limit=1000" in path
        return {"data": {"attributes": {"ohlcv_list": [[1700086400, 0, 0, 0, 2.0, 20.0], [1700000000, 0, 0, 0, 1.0, 10.0]]}}}
    w.get, w.gt_get = get, gt_get
    w.target = lambda cid: ("ethereum", "eth", "0xabc")
    w.gtpool["tok-cg"] = {"pool": "0xpool", "net": "eth"}
    g = run(w.chart_long("tok", "max"))
    assert g["fonte"] == "DEX (GeckoTerminal)" and g["precos"] == [[1700000000, 1.0], [1700086400, 2.0]] and "401" in g["aviso"]


def test_bad_period_and_no_history_are_plain_errors():
    w = watch()
    assert run(w.chart_long("tok", "999"))["erro"] == "período inválido"
    assert "erro" in run(w.chart_long("nao-existe", "90"))

    async def get(path, params=None):
        raise RuntimeError("a CoinGecko pediu para esperar (limite de consultas)")
    w.get = get
    w.target = lambda cid: None
    assert "esperar" in run(w.chart_long("tok", "90"))["erro"]
