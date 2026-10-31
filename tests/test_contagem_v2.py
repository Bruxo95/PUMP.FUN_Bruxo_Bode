"""0.32.106: contagem barata de detentores roda ao lado e só compara; a curva não conta como detentor. Sem internet."""
import asyncio
import base64

import httpx

from app.hub import PumpHub

M = "Hold".ljust(40, "1") + "pump"
URL = "https://rpc.teste/?api-key=SEGREDO"


def _acc(owner: int, amount: int = 5):
    raw = bytes([owner]) * 32 + amount.to_bytes(8, "little")
    return {"pubkey": "x", "account": {"data": [base64.b64encode(raw).decode(), "base64"]}}


def _hub(handler):
    h = PumpHub.__new__(PumpHub)
    h.system_keys = {"rpc_url": URL}
    h.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return h


def test_v2_reads_every_page_and_ignores_empty_balances():
    calls = []

    def net(req):
        import json
        p = json.loads(req.content)["params"]
        calls.append(p[1].get("paginationKey"))
        if p[0] != PumpHub.TOKEN_PROGRAMS[0]:
            return httpx.Response(200, json={"result": {"accounts": [], "paginationKey": None}})
        if not p[1].get("paginationKey"):                # página curta com chave: ainda não acabou
            return httpx.Response(200, json={"result": {"accounts": [_acc(1), _acc(2), _acc(2), _acc(3, 0)], "paginationKey": "k2"}})
        return httpx.Response(200, json={"result": {"accounts": [_acc(4)], "paginationKey": None}})
    n, pages = asyncio.run(_hub(net)._holders_v2(M, URL))
    assert n == 3 and pages == 3 and calls[:2] == [None, "k2"]


def test_sample_only_compares_and_keeps_the_key_out_of_errors():
    def boom(req):
        raise httpx.ConnectError("falhou em " + URL)
    h = _hub(boom)

    async def go():
        for _ in range(PumpHub.HV2_EVERY):
            h._hv2_sample(M, 10)
        await asyncio.sleep(0.05)
    asyncio.run(go())
    assert h.hv2["contagens"] == PumpHub.HV2_EVERY and h.hv2["erros"] == 1 and "SEGREDO" not in str(h.hv2)
    assert not h.hv2["rodando"]


def test_sample_records_equal_and_near():
    def net(req):
        return httpx.Response(200, json={"result": {"accounts": [_acc(1)], "paginationKey": None}})
    h = _hub(net)

    async def go():
        for _ in range(PumpHub.HV2_EVERY):
            h._hv2_sample(M, 1)
        await asyncio.sleep(0.05)
    asyncio.run(go())
    assert h.hv2["n"] == 1 and h.hv2["iguais"] == 1 and h.hv2["paginas"] == 2
