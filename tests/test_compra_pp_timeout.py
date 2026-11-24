"""0.32.443 (BRUISER, 24/11 19:59): a PumpPortal não respondeu em 15 s e a compra REAL caiu inteira com ReadTimeout.
Agora a falta de resposta vira motivo, espera no máx. 6 s e a compra segue pela Jupiter. Sem internet."""
import asyncio

import httpx

from app.pumpfun import PumpReal

M = "Bru1".ljust(40, "1") + "pump"


def test_tx_sem_resposta_da_pumpportal_vira_motivo():
    pr = PumpReal.__new__(PumpReal)
    pr.wallet = type("W", (), {"keypair": object(), "address": "Me"})()
    pr.cfg = type("C", (), {"pump_real_enabled": True, "pump_real_slippage_pct": 15, "pump_priority_sol": 0.0001})()

    def handler(req):
        raise httpx.ReadTimeout("sem resposta", request=req)

    async def go():
        pr.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        r = await pr._tx({"action": "buy", "mint": M, "amount": 0.05})
        await pr.http.aclose()
        return r
    r = asyncio.run(go())
    assert r["pp_down"] and r["status"] == "falhou" and "PumpPortal não respondeu" in r["reason"]
    assert PumpReal.retryable(r["reason"])


def test_compra_pula_para_a_jupiter_quando_a_pumpportal_nao_responde():
    pr = PumpReal.__new__(PumpReal)
    pr.wallet = type("W", (), {"keypair": object(), "address": "Me"})()
    pr.cfg = type("C", (), {"pump_real_enabled": True, "pump_real_slippage_pct": 15, "pump_other_slip_pct": 1.0})()
    calls, bal = [], {"tok": 0.0}

    async def balances(mint):
        return 1.0, bal["tok"]

    async def tx(body, gate=None):
        calls.append(("pp", body["pool"]))
        if gate:
            await gate()
        return {"status": "falhou", "pp_down": True, "reason": "PumpPortal não respondeu em 6 s (ReadTimeout)"}

    async def jup(a, b, amount, bps):
        calls.append(("jupiter",))
        bal["tok"] = 500.0
        return {"ok": True, "status": "confirmada", "signature": "j"}

    async def solc(sig):
        return -0.05
    pr.balances, pr._tx, pr._jup, pr._sol_change = balances, tx, jup, solc
    PumpReal.pool_hint[M] = "pump-amm"
    r = asyncio.run(pr.buy(M, 0.05))
    assert r["ok"] and calls == [("pp", "pump-amm"), ("jupiter",)]
