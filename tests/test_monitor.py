"""Etapa 6: monitor compartilhado + um motor por usuário. Simula 2 usuários seguindo carteiras diferentes (e a
mesma), sem internet."""
import asyncio
import base64
import os
import time

import httpx
import pytest

from tests.fakes import FakeREST

UA = "11111111-1111-1111-1111-111111111111"
UB = "22222222-2222-2222-2222-222222222222"
WA = "TraderGood1111111111111111111111111111111"
WB = "TraderBeta1111111111111111111111111111111"


def tx(wallet, mint, sol_pre, sol_post, tok_pre, tok_post, sig):
    pre = [{"owner": wallet, "mint": mint, "uiTokenAmount": {"uiAmountString": str(tok_pre)}}] if tok_pre is not None else []
    post = [{"owner": wallet, "mint": mint, "uiTokenAmount": {"uiAmountString": str(tok_post)}}]
    return {"blockTime": 1, "transaction": {"signatures": [sig], "message": {"accountKeys": [{"pubkey": wallet}]}},
            "meta": {"err": None, "fee": 5000, "preBalances": [int(sol_pre * 1e9)], "postBalances": [int(sol_post * 1e9)],
                     "preTokenBalances": pre, "postTokenBalances": post}}


class Net:
    """Rede falsa: conta as chamadas por host/caminho."""
    def __init__(self):
        self.calls = []

    def __call__(self, req):
        self.calls.append((req.url.host, req.url.path))
        if "solanatracker" in req.url.host:
            tr = [{"wallet": f"Top{i}".ljust(44, "1"), "period": {"realized": 9000 - i}, "winRate": 0.7,
                   "counts": {"trades": 5000}} for i in range(4)]
            return httpx.Response(200, json={"traders": tr})
        if req.url.path.endswith("/swap/v1/quote"):
            return httpx.Response(200, json={"outAmount": str(int(175.5 * 1e6))})
        return httpx.Response(404)


@pytest.fixture
def setup(monkeypatch):
    from app.crypto import SecretBox
    from app.hub import PumpHub
    from app.monitor import SharedMonitor
    from app.settings import ServerConfig
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("APP_ENCRYPTION_KEY", base64.b64encode(os.urandom(32)).decode())
    cfg = ServerConfig()
    db = FakeREST()
    db.add_user(UA, "a@x.com")
    db.add_user(UB, "b@x.com")
    net = Net()
    http = httpx.AsyncClient(transport=httpx.MockTransport(net))
    hub = PumpHub(cfg, http, db, SecretBox(cfg.encryption_key))

    async def load():
        a, b = await hub.engine(UA), await hub.engine(UB)
        return a, b
    a, b = asyncio.run(load())
    for e in (a, b):
        c = e.cfg
        c.pump_min_mcap_usd = c.pump_min_vol_h1_usd = c.pump_max_top10_pct = c.pump_min_wallet_usd = 0
        c.pump_min_txns_h1 = 0
        c.pump_rank_every_s = 0
    mon = SharedMonitor(hub)

    async def no_fetch(*a, **k):
        return None
    mon.svc._fetch_prices = no_fetch
    mon.svc.holders_check = no_fetch
    return {"hub": hub, "mon": mon, "a": a, "b": b, "net": net}


def _run(coro):
    return asyncio.run(coro)


def test_each_user_copies_only_the_traders_they_follow(setup):
    a, b, mon = setup["a"], setup["b"], setup["mon"]
    a.add_manual(WA)
    b.add_manual(WB)
    assert mon.watch_set() == {WA, WB} and mon.followers(WA) == [a] and mon.followers(WB) == [b]
    ma, mb = "MintA".ljust(40, "1") + "pump", "MintB".ljust(40, "1") + "pump"
    _run(mon.handle_tx(WA, "s1", time.time(), tx(WA, ma, 10, 8.999995, None, 1_000_000, "s1")))
    assert [p["mint"] for p in a.positions()] == [ma] and b.positions() == []
    assert [e["wallet"] for e in a.live] == [WA] and not b.live and not b.feed
    _run(mon.handle_tx(WB, "s2", time.time(), tx(WB, mb, 5, 3.999995, None, 2_000_000, "s2")))
    assert [p["mint"] for p in b.positions()] == [mb] and [p["mint"] for p in a.positions()] == [ma]
    # mercado público é um só: os dois enxergam os mesmos tokens e as carteiras vistas
    assert a.market is b.market is mon.market and ma in a.tokens and mb in b.tokens
    # venda do trader de A fecha só a posição de A
    _run(mon.handle_tx(WA, "s3", time.time(), tx(WA, ma, 9, 10.999995, 1_000_000, 0, "s3")))
    assert not a.positions() and a.trades()[0]["pnl_sol"] > 0 and len(b.positions()) == 1 and not b.trades()


def test_same_trader_copied_by_both_users_counted_once(setup):
    a, b, mon = setup["a"], setup["b"], setup["mon"]
    a.add_manual(WA)
    b.add_manual(WA)
    b.cfg.pump_copy_sol = 0.5                                  # cada um com a sua configuração
    m = "Both".ljust(40, "1") + "pump"
    _run(mon.handle_tx(WA, "s1", time.time(), tx(WA, m, 10, 8.999995, None, 1_000_000, "s1")))
    pa, pb = a.positions(), b.positions()
    assert len(pa) == 1 and len(pb) == 1 and pa[0]["sol_in"] < pb[0]["sol_in"]
    assert pa[0]["id"] != pb[0]["id"] or a.store is not b.store
    st = mon.market.wallets[WA]
    assert len(st["trades"]) == 1 and abs(st["pos"][m]["cost"] - 1.0) < 1e-6       # lido uma vez só
    assert mon.market.rpc_status["parsed"] == 1


def test_price_drop_stops_only_who_holds_the_token(setup):
    a, b, mon = setup["a"], setup["b"], setup["mon"]
    a.add_manual(WA)
    b.add_manual(WB)
    ma, mb = "StopA".ljust(40, "1") + "pump", "StopB".ljust(40, "1") + "pump"
    _run(mon.handle_tx(WA, "s1", time.time(), tx(WA, ma, 10, 8.999995, None, 1_000_000, "s1")))
    _run(mon.handle_tx(WB, "s2", time.time(), tx(WB, mb, 10, 8.999995, None, 1_000_000, "s2")))
    seen = []

    async def curve(ms, public_first=False):
        seen.append(sorted(ms))
        mon.market.tokens[ma]["price"] = mon.market.tokens[ma]["price"] * 0.4     # A despenca 60%
        return []
    mon.svc._curve_prices = curve
    _run(mon.price_once(False))
    assert seen == [sorted([ma, mb])]                                  # uma consulta para os dois
    assert not a.positions() and "stop de perda" in a.trades()[0]["reason"]
    assert len(b.positions()) == 1 and not b.trades()


def test_trailing_fast_loop_covers_all_users(setup):
    a, b, mon = setup["a"], setup["b"], setup["mon"]
    for e in (a, b):
        e.add_manual(WA)
        e.cfg.pump_extra_slip_pct = 0.0
    b.cfg.pump_trail_fast_s = 0.5
    m = "Trail".ljust(40, "1") + "pump"
    _run(mon.handle_tx(WA, "s1", time.time(), tx(WA, m, 10, 8.999995, None, 1_000_000, "s1")))
    px0 = mon.market.tokens[m]["price"]
    mon.market.tokens[m]["price"] = px0 * 1.6
    mon.check_stops([m])                                               # liga o stop móvel nos dois
    assert all(p["trail_peak"] is not None for p in a.positions() + b.positions())

    async def curve(ms, public_first=False):
        assert public_first and ms == [m]
        mon.market.tokens[m]["price"] = px0 * 1.2                      # caiu do pico
        return []
    mon.svc._curve_prices = curve
    dt = _run(mon.trail_once())
    assert dt == 0.5 and not a.positions() and not b.positions()
    assert "stop móvel" in a.trades()[0]["reason"] and "stop móvel" in b.trades()[0]["reason"]


def test_notifications_only_queue_followed_wallets_and_bots_are_dropped(setup):
    a, b, mon = setup["a"], setup["b"], setup["mon"]
    a.add_manual(WA)
    mon._tx_q = asyncio.Queue()
    mon._subs = {1: WA, 2: WB}

    def note(sub, sig, logs=("Program 6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P invoke",)):
        mon.on_notification({"method": "logsNotification", "params": {"subscription": sub, "result": {"value": {
            "signature": sig, "err": None, "logs": list(logs)}}}})
    note(1, "x1")
    note(2, "x2")                                                      # ninguém copia WB: só status
    note(1, "x1")                                                      # repetida: ignora
    assert mon._tx_q.qsize() == 1 and mon.market.activity[WB]["pump"] == 1
    a.cfg.pump_copy_other = False
    note(1, "x3", logs=("Program JUP6 invoke",))                       # fora da pump.fun e A não copia "fora"
    assert mon._tx_q.qsize() == 1
    for i in range(30):                                                # robô: dezenas de trades por minuto
        note(1, f"bot{i}")
    assert mon.market.activity[WA].get("bot_until", 0) > time.time()
    a.refresh_followed(force=True)
    assert WA not in a.followed and any("parece robô" in e["msg"] for e in a.events)
    assert not any("robô" in e["msg"] for e in b.events)


def test_leaderboard_cached_per_settings_and_key_is_personal(setup):
    hub, a, b, mon, net = setup["hub"], setup["a"], setup["b"], setup["mon"], setup["net"]
    a.keys.set("solanatracker_api_key", "st-chave-do-A-" + "x" * 20)
    _run(mon.lb_once())
    assert len(a.leaderboard) == 4 and b.leaderboard == [] and b.lb_status["error"] == "sem chave da Solana Tracker"
    n = sum(1 for h, _ in net.calls if "solanatracker" in h)
    assert n == 1
    hub.shared_st_key = "st-chave-do-A-" + "x" * 20                    # admin emprestou a chave
    _run(mon.lb_once())
    assert len(b.leaderboard) == 4 and sum(1 for h, _ in net.calls if "solanatracker" in h) == 1   # veio do cache
    assert len(b.followed) == 4 and b.leaderboard[0] is not a.leaderboard[0]                     # cópias separadas
    b.ban(b.leaderboard[0]["wallet"])                                  # banir em B não mexe em A
    assert a.leaderboard[0]["wallet"] in a.followed
    b.cfg.pump_lb_min_trades = 300                                     # filtro diferente → consulta própria
    _run(mon.lb_once())
    assert sum(1 for h, _ in net.calls if "solanatracker" in h) == 2


def test_real_queues_are_separate_per_user(setup):
    a, b, mon = setup["a"], setup["b"], setup["mon"]
    a.add_manual(WA)
    b.add_manual(WA)
    a.cfg.pump_real_enabled = True                                     # (só em teste; real falso)

    class FakeReal:
        jup = None

        def api_key(self):
            return ""
    a.real = FakeReal()
    m = "Real".ljust(40, "1") + "pump"
    _run(mon.handle_tx(WA, "s1", time.time(), tx(WA, m, 10, 8.999995, None, 1_000_000, "s1")))
    assert a._rq is not None and a._rq.qsize() == 1 and m in a._real_buying
    assert (b._rq is None or b._rq.qsize() == 0) and not b._real_buying and b.cfg.pump_real_enabled is False


def test_tick_updates_sol_price_and_prunes_without_touching_followed(setup):
    a, mon = setup["a"], setup["mon"]
    a.add_manual(WA)
    mon.market.wallets[WA] = {"pos": {}, "closed": [], "trades": [], "last_t": 0}
    mon.market.wallets["Old".ljust(44, "1")] = {"pos": {}, "closed": [], "trades": [], "last_t": 0}
    _run(mon.tick_once())
    assert abs(mon.market.sol_usd - 175.5) < 1e-9
    mon.prune()
    assert WA in mon.market.wallets and "Old".ljust(44, "1") not in mon.market.wallets
