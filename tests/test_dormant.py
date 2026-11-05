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


def _cg_handler(calls):
    def handler(req):
        calls.append(req.url.path)
        p = req.url.path
        if p.endswith("/coins/list"):
            return httpx.Response(200, json=[{"id": "bitcoin", "name": "Bitcoin", "symbol": "btc", "platforms": {}},
                                             {"id": "pepe", "name": "Pepe", "symbol": "pepe", "platforms": {"ethereum": "0x1", "base": "0x2"}},
                                             {"id": "bonk", "name": "Bonk", "symbol": "bonk", "platforms": {"solana": "So1"}}])
        if p.endswith("/coins/markets"):
            ids = req.url.params["ids"].split(",")
            return httpx.Response(200, json=[_row(i, h24=2.0) for i in ids])
        if "/coins/" in p:
            return httpx.Response(200, json={"categories": ["Meme", "Solana Ecosystem"], "asset_platform_id": "solana"})
        return httpx.Response(404)
    return handler


def test_add_search_and_remove_keep_who_added():
    calls = []
    w = dormant.DormantWatch(httpx.AsyncClient(transport=httpx.MockTransport(_cg_handler(calls))), None)
    w.lista = [{"cmc": "bitcoin", "nome": "Bitcoin"}]
    asyncio.run(w.tick())
    res = asyncio.run(w.search("BONK"))
    assert res[0]["id"] == "bonk" and res[0]["blockchains"] == ["Solana"] and not res[0]["ja_tem"]
    assert asyncio.run(w.search("https://www.coingecko.com/en/coins/pepe"))[0]["id"] == "pepe"
    e = asyncio.run(w.add("bonk", "Douglas", "u1"))
    assert e["por"] == "Douglas"
    try:
        asyncio.run(w.add("bonk", "Outro", "u2"))
        raise AssertionError("aceitou repetida")
    except ValueError:
        pass
    w._next = 0
    asyncio.run(w.tick())
    st = w.state()
    bonk = [m for m in st["moedas"] if m["cmc"] == "cg:bonk"][0]
    assert bonk["add_por"] == "Douglas" and bonk["extra"] and bonk["chain_nome"] == "Solana" and bonk["preco"] is not None
    assert [m for m in st["moedas"] if m["cmc"] == "bitcoin"][0]["chain_nome"] == "Blockchain própria"
    assert asyncio.run(w.remove("cg:bonk")) and not asyncio.run(w.remove("bitcoin"))


def test_categories_come_one_coin_at_a_time_and_group():
    calls = []
    w = dormant.DormantWatch(httpx.AsyncClient(transport=httpx.MockTransport(_cg_handler(calls))), None)
    w.lista = [{"cmc": "bitcoin", "nome": "Bitcoin"}, {"cmc": "bonk", "nome": "Bonk"}]
    asyncio.run(w.tick())                      # lista + preços
    asyncio.run(w.info_step(1e10))             # 1 moeda
    asyncio.run(w.info_step(1e10 + 30))        # a outra
    assert len(w.info) == 2 and all(v["cats"] == ["Meme", "Solana Ecosystem"] for v in w.info.values())
    g = w.state()["grupos"]
    assert g["blockchain"][0]["nome"] == "Solana" and g["categoria"][0]["nome"] in ("Meme", "Solana Ecosystem")


def test_last_three_actions_come_from_the_blockchain_and_waking_alerts():
    """0.32.229 (áudio do Bruxo): a CoinGecko só diz a rede e o contrato; as últimas ações vêm da blockchain (GeckoTerminal)."""
    import time as _t
    now = _t.time()
    trades = {"lista": []}

    def iso(ts):
        from datetime import datetime, timezone
        return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def handler(req):
        p = req.url.path
        if req.url.host == "api.geckoterminal.com":
            if p.endswith("/pools"):
                assert "/networks/solana/tokens/So1/" in p
                return httpx.Response(200, json={"data": [{"attributes": {"address": "POOL1", "name": "BONK / SOL"}}]})
            assert p.endswith("/networks/solana/pools/POOL1/trades")
            return httpx.Response(200, json={"data": [{"attributes": {"block_timestamp": iso(t), "kind": k, "volume_in_usd": "120.5",
                                                                      "tx_from_address": "W", "tx_hash": "TX%d" % i}} for i, (t, k) in enumerate(trades["lista"])]})
        if p.endswith("/coins/list"):
            return httpx.Response(200, json=[{"id": "bonk", "name": "Bonk", "symbol": "bonk", "platforms": {"solana": "So1"}},
                                             {"id": "bitcoin", "name": "Bitcoin", "symbol": "btc", "platforms": {}}])
        if p.endswith("/coins/markets"):
            return httpx.Response(200, json=[_row(i) for i in req.url.params["ids"].split(",")])
        return httpx.Response(404)
    w = dormant.DormantWatch(httpx.AsyncClient(transport=httpx.MockTransport(handler)), None)
    w.lista = [{"cmc": "bonk", "nome": "Bonk"}, {"cmc": "bitcoin", "nome": "Bitcoin"}]
    asyncio.run(w.tick())
    assert w.target("bonk") == ("solana", "solana", "So1") and w.target("bitcoin") is None      # rede própria não tem pool para ler
    trades["lista"] = [(now - 90000, "buy")]                                                       # só negócio de mais de 24 h
    import app.dormant as dm
    dm.GT_EVERY_S, old = 0, dm.GT_EVERY_S
    try:
        assert asyncio.run(w.gt_step(now)) == "bonk"
        b = w.chain["bonk"]
        assert b["n24"] == 0 and b["pool"] == "POOL1" and len(b["last3"]) == 1 and not w.alertas
        trades["lista"] = [(now - 60, "buy"), (now - 90000, "buy")]                                  # negociou agora depois de 25 h parada
        assert asyncio.run(w.gt_step(now + dm.GT_AGAIN_S + 1)) == "bonk"
    finally:
        dm.GT_EVERY_S = old
    a = w.alertas[0]
    assert a["para"] == "acordou_chain" and "Solana" in a["por"][0] and w.chain["bonk"]["n24"] == 1
    st = w.state()
    bonk = [m for m in st["moedas"] if m["cmc"] == "bonk"][0]
    assert bonk["bc"]["last3"][0]["kind"] == "compra" and st["blockchain"]["lidas"] == 1
    assert [m for m in st["moedas"] if m["cmc"] == "bitcoin"][0]["rede_propria"]


def test_coin_window_brings_chart_and_trades_once_and_caches():
    """0.32.232 (pedido do dono): clicar na moeda abre gráfico de 30 dias (CoinGecko) e as últimas negociações (blockchain)."""
    calls = []

    def handler(req):
        calls.append(req.url.path)
        p = req.url.path
        if p.endswith("/market_chart"):
            return httpx.Response(200, json={"prices": [[1_700_000_000_000 + i * 3_600_000, 1 + i / 100] for i in range(48)],
                                             "total_volumes": [[1_700_000_000_000 + i * 3_600_000, 1000] for i in range(48)]})
        if req.url.host == "api.geckoterminal.com":
            return httpx.Response(200, json={"data": [{"attributes": {"block_timestamp": "2026-11-05T21:00:00Z", "kind": "sell", "volume_in_usd": "50",
                                                                      "tx_from_address": "W", "tx_hash": "T"}}]})
        return httpx.Response(404)
    w = dormant.DormantWatch(httpx.AsyncClient(transport=httpx.MockTransport(handler)), None)
    w.lista = [{"cmc": "bonk", "nome": "Bonk"}]
    w.pick = {"bonk": "bonk"}
    w.rows = {"bonk": _row("bonk")}
    w.plat, w.addr = {"bonk": ["solana"]}, {"bonk": {"solana": "So1"}}
    w.gtpool = {"bonk": {"net": "solana", "pool": "P1", "t": 1e12}}
    d = asyncio.run(w.detail("bonk"))
    assert len(d["grafico"]["precos"]) == 48 and d["negocios"]["lista"][0]["kind"] == "venda" and d["contratos"][0]["rede"] == "Solana"
    n = len(calls)
    asyncio.run(w.detail("bonk"))                     # segunda vez em seguida: vem do cache, sem consultar de novo
    assert len(calls) == n and asyncio.run(w.detail("nao-existe")) is None


def test_coin_has_ath_and_atl_dates():
    """0.32.233 (pedido do dono): data da máxima e da mínima histórica na janela da moeda."""
    w = dormant.DormantWatch(None, None)
    w.lista = [{"cmc": "bonk", "nome": "Bonk"}]
    w.pick = {"bonk": "bonk"}
    w.rows = {"bonk": {**_row("bonk"), "ath": 2.0, "ath_date": "2024-12-09T00:00:00.000Z", "atl": 0.1, "atl_date": "2023-04-17T00:00:00.000Z",
                       "atl_change_percentage": 900.0}}
    it = w.state()["moedas"][0]
    assert it["ath_t"] and it["atl_t"] and it["ath_t"] > it["atl_t"] and it["atl_pct"] == 900.0


def test_coin_window_uses_the_dex_chart_when_coingecko_asks_to_wait():
    """0.32.234 (pedido do dono): sem a CoinGecko (429), o gráfico vem do pool da DEX; o pool é achado na hora se faltar."""
    def handler(req):
        p = req.url.path
        if p.endswith("/market_chart"):
            return httpx.Response(429, json={})
        if p.endswith("/pools") and "/tokens/" in p:
            return httpx.Response(200, json={"data": [{"attributes": {"address": "P9", "name": "BONK / SOL"}}]})
        if "/ohlcv/hour" in p:
            return httpx.Response(200, json={"data": {"attributes": {"ohlcv_list": [[1_700_003_600, 1, 2, 0.5, 1.5, 900], [1_700_000_000, 1, 1, 1, 1, 100]]}}})
        if p.endswith("/trades"):
            return httpx.Response(200, json={"data": []})
        return httpx.Response(404)
    w = dormant.DormantWatch(httpx.AsyncClient(transport=httpx.MockTransport(handler)), None)
    w.lista = [{"cmc": "bonk", "nome": "Bonk"}]
    w.pick, w.rows = {"bonk": "bonk"}, {"bonk": _row("bonk")}
    w.plat, w.addr = {"bonk": ["solana"]}, {"bonk": {"solana": "So1"}}
    d = asyncio.run(w.detail("bonk"))
    g = d["grafico"]
    assert d["pool"]["pool"] == "P9" and g["fonte"].startswith("DEX") and g["precos"] == [[1_700_000_000, 1], [1_700_003_600, 1.5]]
    assert d["alvo"]["net"] == "solana" and w._pause_until > 0


def test_only_the_dormant_page_can_show_the_dex_chart(env):
    c = env["c"]
    assert "frame-src https://www.geckoterminal.com https://dexscreener.com" in c.get("/dormant").headers["Content-Security-Policy"]
    assert "frame-src" not in c.get("/app").headers["Content-Security-Policy"]
