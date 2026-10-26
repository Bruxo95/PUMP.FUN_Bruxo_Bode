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
