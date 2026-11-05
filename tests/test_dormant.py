"""0.32.227 (pedido do dono): Dormant vigia a watchlist da CoinMarketCap pela CoinGecko. Sem internet: respostas falsas."""
import asyncio

import httpx

from app import dormant
from tests.test_api import env  # noqa: F401  (fixture env)


def _row(cid, px=1.0, vol=50_000, h1=0.0, h24=0.0, d30=0.0, spark=None, cap=1_000_000):
    return {"id": cid, "name": cid.title(), "symbol": cid[:3], "current_price": px, "total_volume": vol, "market_cap": cap,
            "price_change_percentage_1h_in_currency": h1, "price_change_percentage_24h_in_currency": h24,
            "price_change_percentage_7d_in_currency": 0, "price_change_percentage_30d_in_currency": d30,
            "sparkline_in_7d": {"price": spark or [px * (1 + (i % 2) * 0.2) for i in range(168)]}}


def test_status_rules():
    c = dormant.CFG_DEFAULT
    assert dormant.classify(_row("a", vol=10), c)[0] == "parada"
    assert dormant.classify(_row("a", h1=9), c)[0] == "pump"
    assert dormant.classify(_row("a", h24=-25), c)[0] == "dump"
    calmo = [1.0 + (i % 5) * 0.005 for i in range(168)]
    assert dormant.classify(_row("a", spark=calmo, d30=3), c)[0] == "dormindo"
    acorda = [1.0 + (i % 5) * 0.005 for i in range(144)] + [1.0 + i * 0.004 for i in range(24)]     # passa o topo da faixa
    st, why = dormant.classify(_row("a", spark=acorda, h24=8), c)
    assert st == "acordando" and "topo" in why[0]
    st, why = dormant.classify(_row("a", spark=[1 + (i % 2) * 0.3 for i in range(168)], h24=6), c, vol_med=10_000)
    assert st == "acordando" and "volume" in why[0]                                                  # volume 5× a mediana


def test_match_by_name_alias_and_same_id():
    lista = [{"cmc": "bnb", "nome": "BNB"}, {"cmc": "sushiswap", "nome": "SushiSwap"}, {"cmc": "terra-luna", "nome": "Terra Classic"},
             {"cmc": "nada", "nome": "Nada Coin"}]
    cg = [{"id": "binancecoin", "name": "BNB"}, {"id": "sushi", "name": "Sushi"}, {"id": "terra-luna", "name": "Terra Luna Classic"}]
    m = dormant.match(lista, cg)
    assert m["bnb"] == ["binancecoin"] and m["sushiswap"] == ["sushi"] and m["terra-luna"] == ["terra-luna"] and m["nada"] == []


def test_watch_reads_coingecko_classifies_and_alerts():
    calls = []

    def handler(req):
        calls.append((req.url.path, req.headers.get("x-cg-demo-api-key")))
        if req.url.path.endswith("/coins/list"):
            return httpx.Response(200, json=[{"id": "bitcoin", "name": "Bitcoin"}, {"id": "doge-x", "name": "Doge X"}, {"id": "doge-y", "name": "Doge X"}])
        ids = req.url.params["ids"].split(",")
        rows = [_row(i, h24=state["h24"], cap=10 if i == "doge-x" else 9_000) for i in ids]
        return httpx.Response(200, json=rows)
    state = {"h24": 1.0}
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    w = dormant.DormantWatch(http, None, key_fn=lambda: "CG-teste")
    w.lista = [{"cmc": "bitcoin", "nome": "Bitcoin"}, {"cmc": "doge-x", "nome": "Doge X"}, {"cmc": "morta", "nome": "Morta", "morta_cmc": True}]
    asyncio.run(w.tick())
    assert calls[0] == ("/api/v3/coins/list", "CG-teste") and w.pick == {"bitcoin": "bitcoin", "doge-x": "doge-y"}   # vale a de maior valor
    st = w.state()
    assert st["contagem"]["normal"] == 2 and st["contagem"]["morta"] == 1 and not st["alertas"]
    state["h24"] = 30.0
    w.refresh_now()
    asyncio.run(w.tick())
    st = w.state()
    assert st["contagem"]["pump"] == 2 and {a["cmc"] for a in st["alertas"]} == {"bitcoin", "doge-x"}
    assert len(st["moedas"][0]["spark"]) <= dormant.SPARK_POINTS


def test_429_pauses_and_does_not_crash():
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(429, json={})))
    w = dormant.DormantWatch(http, None)
    try:
        asyncio.run(w.tick())
    except RuntimeError as e:
        assert "esperar" in str(e)
    assert w._pause_until > 0 and w.stat["limite_429"] == 1


def test_dormant_page_and_admin_only_routes(env):
    from tests.test_api import UA, UB, tok
    c = env["c"]
    page = c.get("/dormant")
    assert page.status_code == 200 and "dormant.js" in page.text and "app.js" not in page.text
    assert 'href="/dormant"' in c.get("/entrar").text
    assert c.get("/api/dormant", headers=tok(UB, "b@x.com")).status_code == 403
    assert "ligado" in c.get("/api/dormant", headers=tok(UA)).json()
    assert c.post("/api/dormant/chave", json={"value": "x"}, headers=tok(UA)).json().get("error")
    assert c.post("/api/dormant/cfg", json={"pump_1h": 5}, headers=tok(UB, "b@x.com")).status_code == 403


def test_seed_list_is_the_owner_watchlist():
    lista = dormant.DormantWatch._lista()
    assert len(lista) == 661 and sum(1 for m in lista if m["morta_cmc"]) == 286 and lista[0]["cmc"] == "bitcoin"
