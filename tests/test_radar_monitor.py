"""O estudo alimenta o Radar mesmo sem cópia; filtros da cópia continuam valendo."""
import asyncio
import time

from tests.test_monitor import WA, WB, setup, tx  # noqa: F401 (fixture setup)


PUMP_LOG = "Program 6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P invoke"


def note(mon, sub, signature, logs=(PUMP_LOG,)):
    mon.on_notification({"method": "logsNotification", "params": {"subscription": sub, "result": {"value": {
        "signature": signature, "err": None, "logs": list(logs)}}}})


def live_tx(wallet, mint, signature):
    result = tx(wallet, mint, 10, 8.999995, None, 1_000_000, signature)
    result["blockTime"] = time.time()
    return result


def test_study_without_following_queues_both_wallets_in_the_same_transaction(setup):
    a, b, mon, hub = setup["a"], setup["b"], setup["mon"], setup["hub"]
    a.study = [WA, WB]
    a.cfg.pump_radar_enabled = True
    mon._tx_q = asyncio.Queue()
    mon._subs = {1: WA, 2: WB}
    assert mon.followers(WA) == mon.followers(WB) == [] and mon.watch_set() == {WA, WB}
    note(mon, 1, "same-transaction")
    note(mon, 2, "same-transaction")
    note(mon, 1, "same-transaction")
    assert mon._tx_q.qsize() == 2
    mint = "StudyOnly".ljust(40, "1") + "pump"
    for _ in range(2):
        wallet, signature, at = mon._tx_q.get_nowait()
        asyncio.run(mon.handle_tx(wallet, signature, at, live_tx(wallet, mint, signature)))
    assert len(hub._trade_q) == 2 and {r["wallet"] for r in hub._trade_q} == {WA, WB}
    assert len([e for e in a.events if "radar" in e["msg"].lower()]) == 1
    assert not a.positions() and not b.positions() and not b.events
    assert not a.cfg.pump_real_enabled and (a._rq is None or a._rq.empty())


def test_study_of_other_markets_does_not_bypass_copy_other_filter(setup):
    a, mon, hub = setup["a"], setup["mon"], setup["hub"]
    a.study = [WA]
    a.add_manual(WA)
    a.cfg.pump_copy_other = False
    mon._tx_q = asyncio.Queue()
    mon._subs = {1: WA}
    note(mon, 1, "other-study", logs=("Program JUP6 invoke",))
    assert mon._tx_q.qsize() == 1
    wallet, signature, at = mon._tx_q.get_nowait()
    mint = "OtherMarket".ljust(44, "1")  # sem sufixo pump/estado público de curva
    asyncio.run(mon.handle_tx(wallet, signature, at, live_tx(wallet, mint, signature)))
    assert len(hub._trade_q) == 1 and hub._trade_q[0]["wallet"] == WA
    assert a.positions() == [] and (a._rq is None or a._rq.empty())


def test_studied_bot_is_observed_without_being_copied(setup):
    a, mon, hub = setup["a"], setup["mon"], setup["hub"]
    a.study = [WA]
    a.add_manual(WA)
    mon._tx_q = asyncio.Queue()
    mon._subs = {1: WA}
    mon.market.activity[WA] = {"bot_until": time.time() + 3600, "bot_reason": "teste", "last": None,
                                "n": [], "pump": 0, "pump_last": None, "other": 0, "pn": []}
    note(mon, 1, "bot-study")
    assert mon._tx_q.qsize() == 1
    wallet, signature, at = mon._tx_q.get_nowait()
    mint = "BotStudy".ljust(40, "1") + "pump"
    asyncio.run(mon.handle_tx(wallet, signature, at, live_tx(wallet, mint, signature)))
    assert len(hub._trade_q) == 1
    assert a.positions() == [] and (a._rq is None or a._rq.empty())
