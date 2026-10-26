"""Travas das entradas automáticas pedidas em áudio pelo dono (0.31.0): idade mínima do token, carteiras novas
entre os maiores detentores e trader bom já no token ("triangulação")."""
import asyncio
import json
import time

import httpx

from tests.test_api import UA, env, tok  # noqa: F401  (fixture env)
from tests.test_pump import _pump

M = "Seguro".ljust(40, "1") + "pump"
GOOD = "TraderBom".ljust(44, "1")


def test_safety_rules(tmp_path):
    pf = _pump(tmp_path, paid=False)
    assert pf.auto_safety(M, 5.0).startswith("token com 5 min")
    assert pf.auto_safety(M, 25.0).startswith("esperando checar")
    pf.tokens[M] = {"fresh": {"n": 8, "of": 20, "pct": 40.0, "t": time.time()}}
    assert "8 de 20" in pf.auto_safety(M, 25.0)
    pf.tokens[M]["fresh"] = {"n": 2, "of": 20, "pct": 10.0, "t": time.time()}
    assert pf.auto_safety(M, 25.0).startswith("nenhum trader bom")
    pf.add_manual(GOOD)
    pf.wallets[GOOD] = {"pos": {M: {"tok": 1000.0}}}
    assert pf.smart_in(M) == [GOOD] and pf.auto_safety(M, 25.0) is None
    assert pf.auto_safety(M, None) is None                                 # idade desconhecida não trava


def test_fresh_check_counts_new_wallets_among_top_holders(tmp_path):
    pf = _pump(tmp_path, paid=False)
    now = time.time()
    owners = [f"Dono{i}".ljust(44, "1") for i in range(5)]

    def handler(req: httpx.Request):
        body = json.loads(req.content)
        m, p = body["method"], body["params"]
        if m == "getTokenSupply":
            return httpx.Response(200, json={"result": {"value": {"uiAmountString": "1000000000"}}})
        if m == "getTokenLargestAccounts":
            return httpx.Response(200, json={"result": {"value": [{"address": f"Conta{i}".ljust(44, "1"), "uiAmountString": "1000000"} for i in range(5)]}})
        if m == "getMultipleAccounts":
            return httpx.Response(200, json={"result": {"value": [{"data": {"parsed": {"info": {"owner": o}}}} for o in owners]}})
        if m == "getSignaturesForAddress":
            i = owners.index(p[0])
            n, first = (3, now - 3600) if i < 2 else (25, now - 90 * 86400)        # 2 novas, 3 antigas
            return httpx.Response(200, json={"result": [{"blockTime": first}] * n})
        return httpx.Response(404)
    pf.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    fr = asyncio.run(pf.fresh_check(M, now))
    assert fr == {"n": 2, "of": 5, "pct": 40.0, "t": now} and pf.tokens[M]["holder_owners"] == owners
    assert asyncio.run(pf.fresh_check(M, now + 60)) is fr                  # cache de 3 min


def test_screens_show_fresh_and_smart_and_mark_bots_as_trash(env):
    from app.explore import parse
    from tests.test_explore import G, _sample
    c, hub = env["c"], env["hub"]
    hub.explore.update(parse(_sample()))
    c.get("/api/pump/explore", headers=tok(UA))
    hub.market.tokens.setdefault(G, {})["fresh"] = {"n": 9, "of": 20, "pct": 45.0, "t": time.time()}
    row = c.get("/api/pump/explore", headers=tok(UA)).json()["lists"]["graduating"][0]
    assert row["fresh"]["n"] == 9 and row["smart"] == 0
    assert row["pred"]["verdict"] == "lixo" and "carteiras novas" in row["pred"]["why"][0]
    pf = hub.engines[UA]
    assert pf.explore_entry_reason({**row, "pred": {"verdict": "chance alta"}, "created": (time.time() - 3600) * 1000}) is not None
