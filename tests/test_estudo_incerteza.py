"""0.32.116: faixa de confiança por dia, detentores aos 5 min, dia frio e vigia da carteira. Sem internet."""
import asyncio
import random

import httpx

from app import jevtrade, marketday, resultstudy, stats


def test_one_lucky_day_does_not_become_a_conclusion():
    rows = [(f"d{i}", -5.0) for i in range(50)] + [("d0", 800.0)]
    ci = stats.ci_days(rows)
    assert ci["media"] > 0 and ci["lo"] < 0 and ci["sem_top3"] == -5.0
    assert "ainda não dá para concluir" in stats.reading(ci, "trades")


def test_few_days_never_give_a_range():
    ci = stats.ci_days([("a", 10.0)] * 1000)
    assert ci["lo"] is None and "poucos dados" in stats.reading(ci, "trades")


def test_clear_difference_is_called_and_range_is_reproducible():
    rng = random.Random(1)
    rows = [(f"d{i}", 20 + rng.random()) for i in range(10)]
    assert stats.ci_days(rows)["lo"] > 0 and stats.reading(stats.ci_days(rows), "trades").startswith("melhor")
    assert stats.ci_days(rows) == stats.ci_days(rows)


def test_wilson_matches_the_known_value():
    assert stats.wilson(8, 10) == (49.0, 94.3) and stats.wilson(0, 0) is None


def _r(mint="M", t0=1000.0, h=50):
    return {"mint": mint, "symbol": "X", "t0": t0, "mcap0": 30.0, "snaps": {"5": 60.0}}


def test_holders_are_saved_also_below_40_and_closed_with_the_base():
    j = jevtrade.JevTrade()
    assert j.on_checked(_r("A"), 12, 1300.0) is None and j.h5["A"]["h"] == 12 and j.on_checked(_r("B"), 50, 1300.0) is not None
    assert j.h5_due(1300.0) == [] and len(j.h5_due(1000.0 + jevtrade.H5_WAIT_S)) == 2
    j.h5_close(j.h5["A"], {"label": "morreu", "snaps": {"15": 70, "60": 40}}, 6000.0)
    j.h5_close(j.h5["B"], {"label": "2x", "snaps": {"15": 130}}, 6000.0)
    assert j.h5["A"]["fim"]["dobrou"] is False and j.h5["B"]["fim"]["dobrou"] is True
    S = jevtrade.h5_study(list(j.h5.values()))
    assert S["medidos"] == 2 and S["grupos"][0]["dobrou"] == 1 and "poucos dados" in S["leitura"]
    x = {"mint": "C", "t0": 0.0, "fim": None}
    j.h5["C"] = x
    j.h5_close(x, None, 100.0)
    assert x["fim"] is None                                            # ainda pode aparecer na Base
    j.h5_close(x, None, jevtrade.H5_GIVE_UP_S + 1)
    assert x["fim"] == {"sem_dado": True}


def test_cold_day_needs_quality_and_history():
    D = {f"2026-10-{i:02d}": {"criacoes": 100, "volume_sol": 100.0, "ok": True} for i in range(1, 15)}
    D["2026-10-15"] = {"criacoes": 50, "volume_sol": 50.0, "ok": True}
    D["2026-10-16"] = {"criacoes": 50, "volume_sol": 500.0, "ok": True}
    D["2026-10-17"] = {"criacoes": 1, "volume_sol": 1.0, "ok": False}
    C = marketday.classify(D)
    assert C["2026-10-15"] == "frio" and C["2026-10-16"] == "normal" and C["2026-10-17"] == "sem dado" and C["2026-10-05"] == "sem dado"
    assert marketday.parse({"totals": {"launched": 5, "volume_sol": 1.5}, "coverage": {"pct": 0.8}, "checks": {"failed": []}})["ok"] is False


def test_results_split_by_market_day():
    rows = [{"dia": "a", "data": {"trades": 2, "ganhos": 1, "saldo_sol": -1, "investido_sol": 2}}, {"dia": "b", "data": {"trades": 2, "ganhos": 2, "saldo_sol": 1, "investido_sol": 2}}]
    M = {x["tipo"]: x for x in resultstudy.by_market(rows, {"a": "frio", "b": "normal"})}
    assert M["frio"]["retorno_pct"] == -50 and M["normal"]["acerto"] == 100


ADDR = "Wa11et"


def _tx(pre, post, logs=(), err=None, tok=None):
    return {"meta": {"err": err, "preBalances": pre, "postBalances": post, "logMessages": list(logs), "preTokenBalances": tok or [], "postTokenBalances": []},
            "transaction": {"message": {"accountKeys": [{"pubkey": ADDR}, {"pubkey": "Outro"}]}}}


def test_only_plain_transfers_raise_the_alert():
    from app.hub import PumpHub
    assert PumpHub.wallet_leak(_tx([10 ** 9, 0], [0, 10 ** 9]), ADDR)["sol"] == 1.0
    assert PumpHub.wallet_leak(_tx([10 ** 9, 0], [0, 10 ** 9], ["Program 6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P invoke"]), ADDR) is None
    assert PumpHub.wallet_leak(_tx([0, 10 ** 9], [10 ** 9, 0]), ADDR) is None                     # depósito
    assert PumpHub.wallet_leak(_tx([10 ** 9, 0], [0, 10 ** 9], err={"x": 1}), ADDR) is None       # falhou
    assert PumpHub.wallet_leak(_tx([5000, 0], [0, 0]), ADDR) is None                              # só taxa de rede
    t = [{"owner": ADDR, "mint": "T", "uiTokenAmount": {"uiAmount": 5}}]
    assert PumpHub.wallet_leak(_tx([5000, 0], [0, 0], tok=t), ADDR)["tokens"] == 1


class _W:
    keypair = 1
    address = ADDR

    async def safe_rpc_url(self):
        return "https://rpc.teste/?api-key=SEGREDO"


class _E:
    user_id = "u1"
    sol_wallet = _W()

    def __init__(self):
        self.msgs = []

    def _emit(self, m):
        self.msgs.append(m)


class _Db:
    async def insert(self, *a, **k):
        pass


def test_first_round_is_a_baseline_and_a_new_transfer_alerts_once():
    from app.hub import PumpHub
    sigs = [{"signature": "velha"}]

    def net(req):
        import json
        m = json.loads(req.content)["method"]
        return httpx.Response(200, json={"result": sigs if m == "getSignaturesForAddress" else _tx([10 ** 9, 0], [0, 10 ** 9])})
    h = PumpHub.__new__(PumpHub)
    h.http, h.db = httpx.AsyncClient(transport=httpx.MockTransport(net)), _Db()
    e = _E()
    assert asyncio.run(h.wallet_guard_once(e, 1.0)) == 0 and e.msgs == []
    sigs.insert(0, {"signature": "nova"})
    assert asyncio.run(h.wallet_guard_once(e, 2.0)) == 1 and "ALERTA" in e.msgs[0] and e.wallet_alerts[0]["sig"] == "nova"
    assert asyncio.run(h.wallet_guard_once(e, 3.0)) == 0


def test_rpc_sem_json_usa_o_publico_e_explica():
    """0.32.389: log de 20/11 — 'vigia da carteira: JSONDecodeError' a cada minuto. O RPC da carteira respondeu sem JSON:
    agora explica (HTTP e site, sem a chave) e lê pelo RPC público."""
    from app.hub import PumpHub
    hosts = []

    def net(req):
        import json
        hosts.append(req.url.host)
        if req.url.host != "api.mainnet-beta.solana.com":
            return httpx.Response(429, text="<html>limite</html>")
        return httpx.Response(200, json={"result": [{"signature": "velha"}]})
    h = PumpHub.__new__(PumpHub)
    h.http, h.db = httpx.AsyncClient(transport=httpx.MockTransport(net)), _Db()
    e = _E()
    e._wg_err = None
    assert asyncio.run(h.wallet_guard_once(e, 1.0)) == 0
    assert "HTTP 429 sem JSON" in e._wg_err and "api.mainnet-beta.solana.com" in hosts and "chave" not in e._wg_err
