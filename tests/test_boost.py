"""Boost pago na DexScreener (0.24.0): ON/OFF na Base da pump.fun. Nenhum teste usa internet."""
import asyncio
import time

import httpx

from tests.test_api import UA, env, tok  # noqa: F401  (fixture env)

MINT = "Boost".ljust(40, "1") + "pump"


def _orders(now):
    ms = now * 1000
    return {"orders": [{"type": "tokenProfile", "status": "approved", "paymentTimestamp": ms - 3600_000},
                       {"type": "tokenAd", "status": "cancelled", "paymentTimestamp": ms - 3600_000}],
            "boosts": [{"amount": 10, "paymentTimestamp": ms - 7200_000}, {"amount": 50, "paymentTimestamp": ms - 3 * 86400_000}]}


def test_parse_orders_marks_recent_boost_and_paid_items():
    from app.pumpfun import PumpFun
    now = time.time()
    b = PumpFun.parse_orders(_orders(now), now)
    assert b["active"] and b["amount_24h"] == 10 and b["boosts_total"] == 2 and b["paid"] == ["tokenProfile"]
    old = PumpFun.parse_orders({"orders": [], "boosts": [{"amount": 10, "paymentTimestamp": (now - 2 * 86400) * 1000}]}, now)
    assert not old["active"] and old["amount_24h"] == 0
    assert PumpFun.parse_orders(None, now)["active"] is False


def test_monitor_checks_rising_tokens_and_screen_shows_it(env):
    from app.monitor import SharedMonitor
    c, hub = env["c"], env["hub"]
    seen = []

    def handler(req: httpx.Request):
        seen.append(req.url.path)
        return httpx.Response(200, json=_orders(time.time()))
    mon = SharedMonitor(hub)
    mon.svc.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    t0 = time.time() - 400
    hub.lab.on_create({"mint": MINT, "marketCapSol": 30.0, "symbol": "BST"}, t0)
    hub.lab.live[MINT]["snaps"] = {"1": 60.0}
    assert asyncio.run(mon.boost_once()) == 1 and seen == [f"/orders/v1/solana/{MINT}"]
    assert asyncio.run(mon.boost_once()) == 0                          # não repete antes de 2 min
    r = c.get("/api/pump/base", headers=tok(UA)).json()
    b = r["rising"][0]["boost"]
    assert r["rising"][0]["mint"] == MINT and b["active"] and b["paid"] == ["tokenProfile"]
    hub.market.tokens.setdefault("Pair".ljust(44, "1"), {})["boost_active"] = 3
    assert hub.lab.boost("Pair".ljust(44, "1"))["active"] is True
