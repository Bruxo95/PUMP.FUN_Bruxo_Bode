"""0.32.82: Aba do Bruxo — hora em que o token nasceu (idade de agora × idade na compra) e detentores no sinal e
aos 1/5/10/25 min. Sem internet."""
import asyncio
import json

import httpx

from app.bruxo import Bruxo

M = "Hold".ljust(40, "1") + "pump"
W = "Top1".ljust(44, "1")


def test_signal_keeps_birth_time_and_holder_marks():
    b = Bruxo()
    t = 1_000_000.0
    s, _ = b.on_buy(W, "Top1", M, "HLD", 1.0, 1e-6, {}, 1.5, {}, t)
    assert s["created_t"] == t - 90                          # nasceu 1,5 min antes da compra
    assert [k for _, k in b.holders_due(t)] == ["0"]
    s["holders"]["0"] = 12
    assert b.holders_due(t + 30) == []                       # próxima marca só com 1 min
    assert [k for _, k in b.holders_due(t + 61)] == ["1"]
    due = b.holders_due(t + 400)                             # a foto de 1 min não foi tirada e já passou 3 min
    assert s["holders"]["1"] is None and [k for _, k in due] == ["5"]


def _hub(handler):
    from app.hub import PumpHub

    class H:                                                 # só o que holders_count usa
        system_keys = {"rpc_url": "https://rpc.exemplo.com"}
        TOKEN_PROGRAMS = PumpHub.TOKEN_PROGRAMS

        class cfg:
            solana_rpc_public = "https://api.mainnet-beta.solana.com"
    h = H()
    h.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    h.holders_count = PumpHub.holders_count.__get__(h)
    return h


def test_holders_count_with_das_and_fallback():
    def das(req):
        body = json.loads(req.content)
        assert body["method"] == "getTokenAccounts" and body["params"]["mint"] == M
        acc = [{"owner": f"O{i}", "amount": 5 if i != 3 else 0} for i in range(7)] + [{"owner": "O1", "amount": 2}]
        return httpx.Response(200, json={"result": {"token_accounts": acc}})
    assert asyncio.run(_hub(das).holders_count(M)) == 6      # 7 donos, um zerado, um repetido

    import base64

    def gpa(req):
        body = json.loads(req.content)
        if body["method"] == "getTokenAccounts":
            return httpx.Response(200, json={"error": {"code": -32601, "message": "Method not found"}})
        acc = []
        if body["params"][0].startswith("Tokenkeg"):
            for i, amt in enumerate((10, 0, 3)):
                raw = bytes([i + 1]) * 32 + amt.to_bytes(8, "little")
                acc.append({"account": {"data": [base64.b64encode(raw).decode(), "base64"]}})
        return httpx.Response(200, json={"result": acc})
    assert asyncio.run(_hub(gpa).holders_count(M)) == 2
