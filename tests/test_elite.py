"""Maiores traders (0.31.2): sinais quando os maiores traders entram no mesmo token, acompanhamento de 60 min,
estudo, sugestões, compra automática (simulada) e saída junto com o trader."""
import time

from tests.test_api import UA, UB, env, tok  # noqa: F401  (fixture env)
from tests.test_auto_explorar import _pf

T1, T2, T3 = ("Top1".ljust(44, "1"), "Top2".ljust(44, "1"), "Top3".ljust(44, "1"))
MINT = "Elite".ljust(40, "1") + "pump"
CFG = {"min_wallets": 2, "window_min": 10, "big_sol": 5.0}


def _elite():
    from app.elite import Elite
    from app.pumpfun import PumpMarket
    el = Elite(PumpMarket())
    lb = [{"wallet": w, "name": n, "realized_usd": u, "base_flags": []} for w, n, u in ((T1, "Solstice", 287000), (T2, "Moon", 200000), (T3, "J777", 198000))]
    lb.append({"wallet": "Bot".ljust(44, "1"), "realized_usd": 999999, "base_flags": ["robô"]})
    assert el.refresh_names([lb], 15) == [T1, T2, T3]                     # robô fica fora
    return el


def _ev(kind, mint=MINT, sol=1.0, tok=1e6):
    return {"txType": kind, "mint": mint, "solAmount": sol, "tokenAmount": tok}


def test_signal_needs_two_top_traders_or_a_big_buy():
    el = _elite()
    t = time.time()
    assert el.on_trade(T1, _ev("buy"), t, CFG) is None
    s = el.on_trade(T2, _ev("buy", sol=2.0, tok=1.9e6), t + 60, CFG)
    assert s and s["wallets"] == [T1, T2] and s["names"] == ["Solstice", "Moon"] and s["sol"] == 3.0
    assert el.on_trade(T3, _ev("buy"), t + 70, CFG) is None                # já há sinal aberto no token
    big = el.on_trade(T3, _ev("buy", mint="Big".ljust(40, "1") + "pump", sol=6.0), t, CFG)
    assert big and big["reason"].startswith("compra grande")
    el.on_trade(T1, _ev("sell", sol=1.2), t + 200, CFG)
    assert s["sold_by"] == {T1: 140}
    assert el.on_trade("Desconhecido".ljust(44, "1"), _ev("buy"), t, CFG) is None


def test_signal_is_followed_for_60_min_and_studied():
    el = _elite()
    t0 = time.time() - 4000
    s = el.on_trade(T1, _ev("buy", sol=5.5, tok=5.5e6), t0, CFG)          # compra grande: preço 1e-6
    el.market.tokens[MINT]["price"] = 1.5e-6
    el.tick(t0 + 301)
    el.market.tokens[MINT]["price"] = 0.6e-6
    el.tick(t0 + 3601)
    assert s["marks"] == {"5": 50.0, "15": -40.0, "60": -40.0} and s["peak_pct"] == 50.0 and s["closed"]
    st = el.study()
    assert st["signals"] == 1 and st["by_n"]["1"]["n"] == 1 and st["all"]["hit30_pct"] == 100.0
    assert st["traders"][0]["name"] == "Solstice"
    rows = el.take_dirty()
    assert rows and rows[0]["id"] == s["id"] and rows[0]["data"]["closed"] is True
    from app.elite import Elite
    again = Elite(el.market)
    again.load(rows)
    assert again.signals[s["id"]]["peak_pct"] == 50.0
    assert again.suggestions(again.study())[0]["tipo"] == "info"           # base pequena: só informa


def test_suggestions_use_the_numbers():
    el = _elite()
    t0 = time.time() - 4000
    for i in range(10):
        for n, (end, wl) in enumerate(((-30.0, [T1]), (25.0, [T1, T2]))):
            sid = f"s{i}-{n}"
            el.signals[sid] = {"id": sid, "mint": f"M{i}{n}", "t": t0, "created_at": "", "reason": "x", "wallets": wl,
                               "names": [], "sol": 1, "px0": 1.0, "marks": {"60": end}, "peak_pct": max(end, 5.0),
                               "low_pct": min(end, 0.0), "closed": True}
    sug = el.suggestions(el.study())
    assert any(x["tipo"] == "regra" and "exija 2" in x["texto"] for x in sug)


def test_auto_buy_on_signal_and_sell_with_the_trader():
    pf = _pf(pump_el_auto_on=True)
    s = {"id": "s1", "mint": "AutoA".ljust(40, "1") + "pump", "reason": "2 maiores traders compraram em 10 min",
         "wallets": [T1, T2], "names": ["Solstice", "Moon"], "sol": 3.0}
    r = pf.elite_auto(s, time.time())
    assert r and r.get("auto_id")
    p = pf.positions()[0]
    assert p["origem"] == "elite" and p["auto_info"]["wallets"] == [T1, T2] and p["stop_pct"] == 25.0
    assert pf.elite_sell(T3, s["mint"], "J777") == [] and pf.positions()                  # não era do sinal
    msgs = pf.elite_sell(T2, s["mint"], "Moon")
    assert msgs and not pf.positions() and "trader da elite vendeu (Moon)" in pf.trades()[0]["reason"]
    off = _pf(pump_el_auto_on=False)
    assert off.elite_auto(s) is None
    one = _pf(pump_el_auto_on=True)
    assert one.elite_auto({**s, "wallets": [T1], "reason": "compra grande de 6.0 SOL"}) is None   # compra grande OFF


def test_monitor_and_route(env):
    from app.monitor import SharedMonitor
    c, hub = env["c"], env["hub"]
    c.get("/api/pump", headers=tok(UA))
    pf = hub.engines[UA]
    pf.leaderboard = [{"wallet": T1, "name": "Solstice", "realized_usd": 9e5, "base_flags": []},
                      {"wallet": T2, "name": "Moon", "realized_usd": 8e5, "base_flags": []}]
    mon = SharedMonitor(hub)
    assert mon.elite_names() == [T1, T2] and T1 in mon.watch_set()
    t = time.time()
    assert mon.elite_event(T1, _ev("buy"), t) is None
    s = mon.elite_event(T2, _ev("buy"), t + 5)
    assert s and MINT in mon.held()["trader"]
    r = c.get("/api/pump/elite", headers=tok(UA)).json()
    assert r["open"][0]["mint"] == MINT and len(r["traders"]) == 2 and r["feed"][0]["name"] == "Moon"
    assert r["suggestions"] and "summary" in r["auto"]
    assert c.get("/api/pump/elite", headers=tok(UB, "b@x.com")).status_code == 403


def test_recommended_traders_need_80_percent_and_enough_trades():
    from app.elite import Elite
    from app.pumpfun import PumpMarket
    el = Elite(PumpMarket())
    lb = [{"wallet": T1, "name": "Alta", "realized_usd": 60000, "winrate": 95, "trades": 9626, "base_flags": []},
          {"wallet": T2, "name": "Sorte", "realized_usd": 90000, "winrate": 100, "trades": 12, "base_flags": []},
          {"wallet": T3, "name": "Media", "realized_usd": 500000, "winrate": 50, "trades": 7704, "base_flags": []}]
    el.refresh_names([lb], 15)
    assert [r["wallet"] for r in el.recommended()] == [T1]                 # poucos trades ou acerto baixo ficam fora
    sug = el.suggestions(el.study())
    assert any("Alta tem 95% de acerto em 9626 trades" in s["texto"] for s in sug)


def test_wallet_age_reads_the_oldest_transaction(tmp_path):
    import asyncio
    import json
    import httpx
    from tests.test_pump import _pump
    pf = _pump(tmp_path, paid=False)
    now = time.time()
    calls = []

    def handler(req):
        p = json.loads(req.content)["params"]
        calls.append(p[1].get("before"))
        if p[1].get("before") is None:
            return httpx.Response(200, json={"result": [{"signature": f"s{i}", "blockTime": now - i} for i in range(1000)]})
        return httpx.Response(200, json={"result": [{"signature": "velha", "blockTime": now - 30 * 86400}]})
    pf.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    a = asyncio.run(pf.wallet_age(T1))
    assert a["age_days"] == 30.0 and a["more"] is False and calls == [None, "s999"]

    def busy(req):
        p = json.loads(req.content)["params"]
        return httpx.Response(200, json={"result": [{"signature": f"x{i}", "blockTime": now - 86400} for i in range(1000)]})
    pf.http = httpx.AsyncClient(transport=httpx.MockTransport(busy))
    b = asyncio.run(pf.wallet_age(T1, pages=2))
    assert b["more"] is True and b["age_days"] == 1.0                      # muito ativa: "pelo menos 1 dia"


def test_elite_route_brings_balance_age_and_recommended(env):
    import asyncio
    from app.monitor import SharedMonitor
    c, hub = env["c"], env["hub"]
    c.get("/api/pump", headers=tok(UA))
    pf = hub.engines[UA]
    pf.leaderboard = [{"wallet": T1, "name": "Alta", "realized_usd": 6e4, "winrate": 95, "trades": 500, "base_flags": []}]
    mon = SharedMonitor(hub)
    mon.elite_names()
    hub.market.sol_usd = 100.0

    async def value(w):
        return {"sol": 10.0, "stable": 50.0, "usd": 1050.0, "t": time.time()}

    async def age(w):
        return {"first_t": time.time() - 90 * 86400, "age_days": 90.0, "more": False, "t": time.time()}
    mon.svc.wallet_value, mon.svc.wallet_age = value, age
    assert asyncio.run(mon.elite_info_once()) == 2
    r = c.get("/api/pump/elite", headers=tok(UA)).json()
    tr = r["traders"][0]
    assert tr["balance"]["usd"] == 1050.0 and tr["age"]["age_days"] == 90.0 and r["recommended"] == [T1]


def test_suggested_traders_are_copied_buy_and_sell(env):
    """0.31.4: sugeridos (80%+) entram na lista de cópia; o robô copia compra e venda; Steps mostra cada passo."""
    from app.monitor import SharedMonitor
    from tests.test_pump import _ev as pev
    c, hub = env["c"], env["hub"]
    c.get("/api/pump", headers=tok(UA))
    pf = hub.engines[UA]
    for k in ("pump_min_mcap_usd", "pump_min_vol_h1_usd", "pump_max_top10_pct", "pump_min_wallet_usd", "pump_min_txns_h1"):
        setattr(pf.cfg, k, 0)
    pf.cfg.pump_risk_check = False
    pf.leaderboard = [{"wallet": T1, "name": "Alta", "realized_usd": 6e4, "winrate": 95, "trades": 500, "base_flags": []},
                      {"wallet": T2, "name": "Baixa", "realized_usd": 9e4, "winrate": 50, "trades": 500, "base_flags": []}]
    mon = SharedMonitor(hub)
    mon.elite_names()
    assert mon.elite_follow_sync() == 1 and pf.elite_follow == [T1] and T1 in pf.followed and T2 not in pf.followed
    t = time.time()
    m = "Passo".ljust(40, "1") + "pump"
    ev = pev("buy", T1, m, 1.0, 1e6, 30, 3e7)
    mon.dispatch(ev, t)
    mon.elite_event(T1, ev, t)
    assert pf.positions() and pf.positions()[0]["wallet"] == T1
    r = c.get("/api/pump/elite/steps", headers=tok(UA)).json()
    st = r["steps"][0]
    assert st["wallet"] == T1 and st["kind"] == "buy" and st["bot_action"] == "copiou compra" and st["position"]["open"]
    assert r["following"] == [T1] and r["copy80"] is True
    sell = pev("sell", T1, m, 1.5, 1e6, 30, 3e7 / 1.5, newTokenBalance=0)
    mon.dispatch(sell, t + 60)
    mon.elite_event(T1, sell, t + 60)
    assert not pf.positions() and pf.trades()[0]["wallet"] == T1                # vendeu junto com ele
    pf.cfg.pump_el_copy80 = False
    mon.elite_follow_sync()
    assert pf.elite_follow == [] and T1 not in pf.followed
    assert c.get("/api/pump/elite/steps", headers=tok(UB, "b@x.com")).status_code == 403
