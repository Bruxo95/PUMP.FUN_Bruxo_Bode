"""0.32.459 (BAH do dono, 25/11): metade do token foi vendida no app da carteira (+0,075912037 SOL) e a conta do token fechada
(+0,00151384 SOL). O robô tentava vender para sempre (PumpPortal 400, Jupiter sem cotação) e não via o SOL. Sem internet."""
import asyncio

from app.pumpfun import PumpReal
from tests.test_venda_graduado import M, _pr

OWN = "Me"


def tx(sig, pre_tok, post_tok, pre_sol, post_sol, conta=True):
    def bals(v):
        return [] if v is None else [{"owner": OWN, "mint": M, "uiTokenAmount": {"uiAmountString": str(v)}}]
    return {"meta": {"err": None, "preTokenBalances": bals(pre_tok), "postTokenBalances": bals(post_tok),
                     "preBalances": [pre_sol, 0], "postBalances": [post_sol, 0]},
            "transaction": {"message": {"accountKeys": [{"pubkey": OWN}, {"pubkey": "Pool"}]}}}


def test_sem_saldo_duas_vezes_para_de_tentar():
    pr, calls = _pr([{"ok": False, "reason": "PumpPortal HTTP 400: Bad Request"}])

    async def zero(mint):
        return 1.0, 0.0

    async def tx(body, gate=None):                       # como a PumpPortal real: o 400 vem antes de conferir o saldo
        calls.append(body["pool"])
        return {"ok": False, "reason": "PumpPortal HTTP 400: Bad Request"}

    async def jup(*a):
        calls.append("jupiter")
        return {"ok": False, "reason": "sem cotação em nenhuma DEX"}
    pr.balances, pr._tx, pr._jup = zero, tx, jup
    PumpReal.pool_hint[M] = "pump-amm"
    r = asyncio.run(pr.sell(M, 1.0))
    assert r["ok"] and r["reason"] == "sem saldo do token" and len(calls) == 1


def test_acha_a_venda_e_o_aluguel_feitos_na_carteira():
    pr = PumpReal.__new__(PumpReal)
    pr.wallet = type("W", (), {"address": OWN})()
    txs = {"robo": tx("robo", 269325.97, 134662.99, 0, 82_843_354),
           "fora": tx("fora", 134662.99, 0, 1_000_000_000, 1_075_912_037),
           "conta": tx("conta", 0, None, 1_075_912_037, 1_077_425_877),
           "outro": tx("outro", None, None, 5, 3)}

    async def rpc(method, params):
        if method == "getSignaturesForAddress":
            return [{"signature": s, "blockTime": 2000} for s in ("conta", "fora", "outro", "robo")] + [{"signature": "velha", "blockTime": 10}]
        return txs[params[0]]
    pr._rpc_retry = rpc
    sol, tok, sigs, rent = asyncio.run(pr.external_sold(M, 1000, {"robo"}))
    assert round(sol, 9) == 0.075912037 and round(tok, 2) == 134662.99
    assert round(rent, 8) == 0.00151384 and set(sigs) == {"fora", "conta"}
