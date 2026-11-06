"""Explorar (0.28.0): listas estilo pump.fun/explore pela Solana Tracker, veredito e aprendizado da curva."""
import asyncio
import time

import httpx

from tests.test_api import UA, UB, env, tok  # noqa: F401  (fixture env)

G = "Grad".ljust(40, "1") + "pump"
N = "Novo".ljust(40, "1") + "pump"


def _sample(curve=85.0, graduated=()):
    def row(mint, sym, **kw):
        return {"token": {"mint": mint, "symbol": sym, "name": sym + " coin", "creator": "Dev".ljust(44, "1")},
                "pools": [{"liquidity": {"usd": 9000}, "marketCap": {"usd": 52000}, "curvePercentage": kw.get("curve"),
                           "txns": {"buys": 10, "sells": 5}}],
                "events": {"5m": {"priceChangePercentage": kw.get("c5", 12.0)}, "1h": {"priceChangePercentage": kw.get("c1", 150.0)}},
                "risk": {"score": kw.get("risk", 3), "rugged": False}, "buys": kw.get("buys", 120), "sells": kw.get("sells", 40),
                "txns": 160, "holders": kw.get("holders", 210)}
    return {"latest": [row(N, "NEW", curve=10.0, buys=5, sells=20)],
            "graduating": [row(G, "GRD", curve=curve)],
            "graduated": [row(m, "OLD") for m in graduated]}


def test_parse_and_verdicts():
    from app.explore import Explore, parse
    d = parse(_sample())
    g = d["graduating"][0]
    assert g["mint"] == G and g["curve_pct"] == 85.0 and g["mcap_usd"] == 52000 and g["pressure"] == 75.0
    assert g["chg_5m"] == 12.0 and g["holders"] == 210 and g["risk"] == 3
    ex = Explore()
    ex.update(d)
    snap = ex.snapshot({}, {}, lambda m: {})
    assert snap["lists"]["graduating"][0]["pred"]["verdict"] == "chance alta"
    assert snap["lists"]["latest"][0]["pred"]["verdict"] == "lixo"                 # 20% compras
    assert snap["movers"][0]["chg_1h"] == 150.0
    assert parse(None) == {"latest": [], "graduating": [], "graduated": []}
    assert parse({"graduating": [{"nada": 1}, "x"]})["graduating"] == []


def test_learns_how_many_graduating_tokens_graduate():
    from app.explore import KEEP_S, Explore, parse
    ex = Explore()
    now = time.time()
    ex.update(parse(_sample(curve=85.0)), now - 100)
    ex.update(parse(_sample(curve=88.0, graduated=[G])), now)
    assert ex.learned(now) == [{"faixa": "80 a 90%", "n": 1, "grad_pct": 100.0}]
    ex.seen["Other".ljust(44, "1")] = {"t": now - KEEP_S - 1, "curve": 45.0, "grad": None}
    assert {"faixa": "40 a 60%", "n": 1, "grad_pct": 0.0} in ex.learned(now)


def test_monitor_reads_solana_tracker_and_route_is_admin_only(env):
    from app.monitor import SharedMonitor
    c, hub = env["c"], env["hub"]
    mon = SharedMonitor(hub)
    assert asyncio.run(mon.explore_once()) is False and not hub.explore.error   # 0.32.238: ninguém usa o Explorar = não busca
    hub.explore_seen = time.time()                                              # alguém abriu a tela
    assert asyncio.run(mon.explore_once()) is False and "sem chave" in hub.explore.error
    seen = []

    def handler(req: httpx.Request):
        seen.append((req.url.path, req.headers.get("x-api-key")))
        return httpx.Response(200, json=_sample())
    mon.svc.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    hub.shared_st_key = "st-sistema-" + "k" * 20
    assert asyncio.run(mon.explore_once()) is True and seen[0] == ("/tokens/multi/all", hub.shared_st_key)
    r = c.get("/api/pump/explore", headers=tok(UA)).json()
    assert r["error"] is None and r["lists"]["graduating"][0]["mint"] == G and r["lists"]["graduating"][0]["boost"] == {}
    assert c.get("/api/pump/explore", headers=tok(UB, "b@x.com")).status_code == 403
