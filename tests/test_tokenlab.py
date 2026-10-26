"""Base própria da pump.fun (0.21.0): fotos do market cap de cada token novo, rótulo, criadores e mercado."""
import asyncio
import time

from tests.test_api import UA, UB, env, tok  # noqa: F401  (fixture env)

CR = "CreatorGood111111111111111111111111111111"
CR2 = "CreatorRug2222222222222222222222222222222"


def _lab():
    from app.pumpfun import PumpMarket
    from app.tokenlab import TokenLab
    m = PumpMarket()
    return TokenLab(m), m


def _life(lab, m, mint, creator, values, t0, name="", graduate_at=None):
    lab.on_create({"mint": mint, "traderPublicKey": creator, "marketCapSol": 30.0, "symbol": name[:4].upper(),
                   "name": name, "solAmount": 1.0}, t0)
    for i, (mins, mc) in enumerate(zip((1, 5, 15, 60), values)):
        t = t0 + mins * 60 + 1
        assert lab.due(t) == [mint]
        m.tokens.setdefault(mint, {})["mcap_sol"] = mc
        if graduate_at == i:
            m.tokens[mint]["pool"] = "pumpswap"
        lab.observe(t, [mint])
        if graduate_at == i:
            break


def test_labels():
    from app.tokenlab import label
    assert label(30, {"1": 40, "5": 160, "15": 90, "60": 50}, False) == "5x"
    assert label(30, {"1": 40, "5": 70, "15": 90, "60": 50}, False) == "2x"
    assert label(30, {"1": 45, "5": 20, "15": 18, "60": 18}, False) == "despencou"
    assert label(30, {"1": 30, "5": 31, "15": 30, "60": 29}, False) == "morreu"
    assert label(30, {"1": 35, "5": 40, "15": 42, "60": 41}, False) == "subiu pouco"
    assert label(30, {"1": 31}, True) == "graduou" and label(None, {}, False) == "sem dado"


def test_token_life_creators_words_and_blacklist():
    lab, m = _lab()
    t0 = time.time() - 7200
    _life(lab, m, "Doge1".ljust(40, "1") + "pump", CR, (40, 70, 90, 50), t0, "Doge Moon")
    _life(lab, m, "Doge2".ljust(40, "1") + "pump", CR, (40, 30, 31, 70), t0 + 5, "Doge Mars")
    _life(lab, m, "Grad1".ljust(40, "1") + "pump", CR, (60, 0, 0, 0), t0 + 9, "Cat", graduate_at=0)
    assert not lab.live and [r["label"] for r in lab.done] == ["2x", "2x", "graduou"]
    assert lab.creators[CR] == {"tokens": 3, "x2": 3, "rugs": 0}
    for i in range(3):
        _life(lab, m, f"Rug{i}".ljust(40, "1") + "pump", CR2, (45, 20, 18, 18), t0 + 20 + i, "Scam")
    assert lab.creators[CR2] == {"tokens": 3, "x2": 0, "rugs": 3}
    assert CR2 in m.blacklist and m.bl_new == [CR2] and CR not in m.blacklist
    snap = lab.snapshot()
    assert snap["day"]["finished"] == 6 and snap["day"]["up"] == 3 and snap["day"]["labels"]["despencou"] == 3
    assert snap["words"][0]["word"] == "doge" and snap["words"][0]["up"] == 2
    assert snap["bad_creators"][0]["creator"] == CR2 and snap["good_creators"][0]["creator"] == CR
    assert sum(h["created"] for h in snap["hours"]) == 6
    tl, hrs, crs = lab.take_dirty()
    assert {r["label"] for r in tl} == {"2x", "graduou", "despencou"} and len(tl) == 6
    assert hrs and {c["creator"] for c in crs} == {CR, CR2}
    assert lab.take_dirty() == ([], [], [])


def test_new_tokens_per_minute_are_capped():
    from app.tokenlab import MAX_PER_MIN
    lab, _ = _lab()
    t = 1_800_000_000.0
    for i in range(MAX_PER_MIN + 3):
        lab.on_create({"mint": f"Cap{i}".ljust(44, "1"), "marketCapSol": 30}, t)
    assert len(lab.live) == MAX_PER_MIN and lab.dropped == 3


def test_creator_history_enters_the_entry_score(tmp_path):
    from tests.test_pump import _pump
    pf = _pump(tmp_path, paid=False)
    mint = "Score".ljust(40, "1") + "pump"
    pf.tokens[mint] = {"creator": CR2, "price": 1e-6}
    pf.market.creator_stats[CR2] = {"tokens": 4, "x2": 0, "rugs": 4}
    score, parts = pf.entry_score("Someone".ljust(44, "1"), mint, 1e-6, 1e-6)
    assert parts["criador"] == 0
    pf.market.creator_stats[CR2] = {"tokens": 4, "x2": 4, "rugs": 0}
    assert pf.entry_score("Someone".ljust(44, "1"), mint, 1e-6, 1e-6)[1]["criador"] == 100


def test_monitor_takes_the_snapshots_and_hub_persists(env):
    from app.monitor import SharedMonitor
    c, hub, db = env["c"], env["hub"], env["db"]
    mon = SharedMonitor(hub)
    mint = "Live".ljust(40, "1") + "pump"
    t0 = time.time() - 70
    mon.dispatch({"txType": "create", "mint": mint, "traderPublicKey": CR, "marketCapSol": 30.0, "symbol": "LIVE"}, t0)
    assert mint in hub.lab.live
    seen = []

    async def curve(ms, public_first=False):
        seen.append(list(ms))
        for x in ms:
            hub.market.tokens.setdefault(x, {})["mcap_sol"] = 66.0
        return []
    mon.svc._curve_prices = curve
    assert asyncio.run(mon.lab_once()) == 1 and seen == [[mint]]
    assert hub.lab.live[mint]["snaps"] == {"1": 66.0}
    rec = hub.lab.live.pop(mint)
    hub.lab.finalize(rec, True, time.time())
    assert asyncio.run(hub.save_lab()) == 1
    assert db.tables["token_life"][0]["label"] == "graduou" and db.tables["creator_stats"][0]["creator"] == CR
    assert db.tables["market_hourly"]
    hub.lab.creators.clear()
    asyncio.run(hub.load_lab())
    assert hub.lab.creators[CR]["x2"] == 1 and hub.market.creator_stats is hub.lab.creators
    r = c.get("/api/pump/base", headers=tok(UA)).json()
    assert r["day"]["finished"] == 1 and r["good_creators"][0]["creator"] == CR
    assert c.get("/api/pump/base", headers=tok(UB, "b@x.com")).status_code == 403
