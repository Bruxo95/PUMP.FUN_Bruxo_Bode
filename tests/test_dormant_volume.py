"""0.32.248 (pedido do dono): volume por período, alerta com o que movimentou e resposta logo depois de enviar. Sem internet."""
import asyncio
import time

import httpx

from app import dormant, dormant_buy as db_, dormant_gas as g
from tests.test_dormant_gas import RelayNet, ready
from tests.test_dormant_compra import SENHA, UID


def _watch(handler):
    w = dormant.DormantWatch(httpx.AsyncClient(transport=httpx.MockTransport(handler)), None)
    w.lista = [{"cmc": "bonk", "nome": "Bonk"}]
    w.pick = {"bonk": "bonk"}
    return w


def test_pool_batch_reads_many_pools_in_one_call():
    calls = []

    def handler(req):
        calls.append(req.url.path)
        return httpx.Response(200, json={"data": [{"attributes": {"address": "pool1", "reserve_in_usd": "5000", "volume_usd": {"h1": "866.4", "h6": "1981.5", "h24": "36695.9"},
                                                                  "transactions": {"h1": {"buys": 3, "sells": 4}, "h24": {"buys": 90, "sells": 80}}}}]})
    w = _watch(handler)
    w.gtpool = {"bonk": {"net": "solana", "pool": "POOL1", "t": 1}, "x": {"net": "solana", "pool": "pool2", "t": 1}, "sem": {"net": "solana", "pool": None}}
    now = time.time()
    assert asyncio.run(w.pool_vol_step(now)) == 2
    assert len(calls) == 1 and calls[0] == "/api/v2/networks/solana/pools/multi/POOL1,pool2"
    v = w.vols("bonk", now)
    assert v["v1"] == 866.4 and v["v6"] == 1981.5 and v["pv24"] == 36695.9 and v["tx24"] == [90, 80] and v["v12"] is None      # 12 h só com foto antiga
    assert asyncio.run(w.pool_vol_step(now + 10)) == 0                      # dentro dos 10 min não lê de novo


def test_12h_is_6h_now_plus_the_6h_of_six_hours_ago_and_never_invented():
    now = 1_000_000.0
    p = {"h6": 100.0, "s6": [[now - 21600, 40.0], [now - 3600, 90.0]]}
    assert dormant.DormantWatch.v12(p, now) == 140.0
    assert dormant.DormantWatch.v12({"h6": 100.0, "s6": [[now - 3600, 90.0]]}, now) is None
    assert dormant.DormantWatch.v12({"s6": []}, now) is None


def test_30_days_come_once_per_coin_and_7d_30d_only_with_enough_days():
    calls = []
    now = time.time()

    def handler(req):
        calls.append(req.url.path)
        pts = [[(now - i * 86400) * 1000, 100.0] for i in range(29, 0, -1)]
        return httpx.Response(200, json={"total_volumes": pts})
    w = _watch(handler)
    assert w.vols("bonk", now)["v7d"] is None and w.vols("bonk", now)["v30d"] is None
    asyncio.run(w.vol_step(now))
    v = w.vols("bonk", now)
    assert v["v7d"] == 700.0 and v["v30d"] == 2900.0 and "bonk" in w.volback
    asyncio.run(w.vol_step(now + 60))
    assert len(calls) == 1                                                  # uma vez só por moeda


def test_429_on_history_does_not_mark_as_done():
    w = _watch(lambda req: httpx.Response(429, json={}))
    try:
        asyncio.run(w.vol_step(time.time()))
    except RuntimeError:
        pass
    assert "bonk" not in w.volback


def test_alert_keeps_how_much_moved():
    w = _watch(lambda req: httpx.Response(404))
    w.rows = {"bonk": {"name": "Bonk", "symbol": "bonk", "current_price": 1, "total_volume": 50000, "market_cap": 1, "price_change_percentage_1h_in_currency": 16.3, "price_change_percentage_24h_in_currency": -4}}
    w.status = {"bonk": ("normal", [])}
    w.pvol = {"bonk": {"h1": 1234.0}}
    w._classify(time.time())
    a = w.alertas[0]
    assert a["para"] == "pump" and a["vol24"] == 50000 and a["v1"] == 1234.0


def test_user_gets_answer_soon_and_the_operation_finishes_behind():
    """0.32.248: o dono via "cotação venceu" com a transação já na rede. A resposta vem logo; a confirmação segue por trás."""
    net = RelayNet()
    f, b, net, db = ready(net)

    async def go():
        antes = db_.RESPOSTA_S, g.ENTREGA_PASSO
        db_.RESPOSTA_S, g.ENTREGA_PASSO = 0.05, 0.2
        try:
            p = await f.preview(UID, "binance-smart-chain", "base", 5)
            r = await f.fill(UID, p["quote_id"], SENHA, "ABASTECER")
            assert r["status"] in ("enviando", "pendente") and r["origem_nome"] == "Base" and r["tx"]    # já diz de onde saiu
            assert len(net.sent) == 1
            p2 = await f.preview(UID, "binance-smart-chain", "base", 5)
            assert any("sem confirmação" in x for x in p2["bloqueia"])      # continua segurando a próxima
            await asyncio.sleep(1.2)
            assert db.tables["dormant_gas"][0]["status"] == "confirmada"    # terminou por trás
        finally:
            db_.RESPOSTA_S, g.ENTREGA_PASSO = antes
    asyncio.run(go())
