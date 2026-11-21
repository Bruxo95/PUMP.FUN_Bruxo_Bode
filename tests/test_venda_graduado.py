"""0.32.422 (FTL, 21/11 14:41): venda REAL de token que já graduou tentava a curva da pump.fun (erro 6005, em decimal) 3 vezes
e repetia a cada 2 s. Agora: token graduado vende direto na PumpSwap (Jupiter no fim), o 6005 em decimal também troca para a
PumpSwap, e a REAL que acompanha a fictícia respeita a espera entre tentativas. Sem internet."""
import asyncio
import time

from app.pumpfun import PumpFun, PumpReal

M = "Ftl1".ljust(40, "1") + "pump"
G6005 = "simulação recusou: {'InstructionError': [3, {'Custom': 6005}]}"


def _pr(results):
    pr = PumpReal.__new__(PumpReal)
    pr.wallet = type("W", (), {"keypair": object(), "address": "Me"})()
    pr.cfg = type("C", (), {"pump_real_slippage_pct": 15})()
    calls, bal = [], {"tok": 100.0}

    async def balances(mint):
        return 1.0, bal["tok"]

    async def tx(body):
        calls.append(("pp", body["pool"], body["slippage"]))
        r = results.pop(0) if results else {"ok": False, "reason": G6005}
        if r.get("ok"):
            bal["tok"] = 0.0
        return r

    async def jup(a, b, amount, bps):
        calls.append(("jupiter", None, bps / 100))
        bal["tok"] = 0.0
        return {"ok": True, "signature": "j"}

    async def raw(mint):
        return 100_000_000, 6

    async def solc(sig):
        return 0.03
    pr.balances, pr._tx, pr._jup, pr._raw_tok, pr._sol_change = balances, tx, jup, raw, solc
    return pr, calls


def test_graduado_vende_direto_na_pumpswap():
    pr, calls = _pr([{"ok": True, "signature": "s"}])
    PumpReal.pool_hint[M] = "pump-amm"
    r = asyncio.run(pr.sell(M, 1.0))
    assert r["ok"] and calls == [("pp", "pump-amm", 15)]


def test_6005_em_decimal_troca_para_pumpswap_e_jupiter():
    pr, calls = _pr([{"ok": False, "reason": G6005}, {"ok": False, "reason": "HTTP 400 qualquer"}, {"ok": False, "reason": "x"}])
    PumpReal.pool_hint.pop(M, None)
    r = asyncio.run(pr.sell(M, 1.0))
    assert r["ok"]
    assert calls[0] == ("pp", "auto", 15) and calls[1][1] == "pump-amm" and calls[-1][0] == "jupiter"


def test_real_junto_com_a_ficticia_respeita_a_espera():
    pf = PumpFun.__new__(PumpFun)
    put = []
    pf._save_pos = lambda p: None
    pf._rq_put = put.append
    p = {"id": "r1", "sell_retry_at": time.time() + 300}
    assert pf._real_sell(p, 1.0, "junto com a fictícia: fechada por você") is False and not put
    assert pf._real_sell(p, 1.0, "fechada por você") is True and put        # pedido direto na tela não espera


def _prb(results, real_on=True):
    pr, calls = _pr([])
    pr.cfg = type("C", (), {"pump_real_slippage_pct": 15, "pump_real_enabled": real_on, "pump_other_slip_pct": 1.0})()
    bal = {"sol": 1.0, "tok": 0.0}

    async def balances(mint):
        return bal["sol"], bal["tok"]

    async def tx(body):
        calls.append(("pp", body["pool"], body.get("slippage")))
        r = results.pop(0) if results else {"ok": False, "reason": "x"}
        if r.get("ok"):
            bal["tok"] = 100.0
        return r

    async def jup(a, b, amount, bps):
        calls.append(("jupiter", None, bps / 100))
        r = results.pop(0) if results else {"ok": False, "reason": "x"}
        if r.get("ok"):
            bal["tok"] = 100.0
        return r

    async def solc(sig):
        return -0.05
    pr.balances, pr._tx, pr._jup, pr._sol_change = balances, tx, jup, solc
    return pr, calls


def test_compra_de_graduado_vai_na_pumpswap_e_sobe_o_slippage():
    """0.32.430 (DESPAIR do BOOST, 21/11 18:14): compra de token graduado não tenta a curva; PumpSwap 15% → 30%, depois Jupiter."""
    pr, calls = _prb([{"ok": False, "reason": "{'Custom': 6004}"}, {"ok": False, "reason": "0x1774"},
                      {"ok": False, "reason": "0x1771"}, {"ok": True, "signature": "j"}])
    PumpReal.pool_hint[M] = "pump-amm"
    r = asyncio.run(pr.buy(M, 0.05))
    assert r["ok"] and calls == [("pp", "pump-amm", 15.0), ("pp", "pump-amm", 30.0), ("jupiter", None, 15.0), ("jupiter", None, 30.0)]


def test_saldo_lido_em_paralelo_com_a_montagem():
    """0.32.431 (dono: "qualquer milissegundo de perda prejudica"): o saldo de antes da compra é lido enquanto a PumpPortal monta
    a transação, e conferido só antes de assinar; saldo baixo não envia."""
    order = []
    pr, calls = _prb([])

    async def balances(mint):
        order.append("saldo:começou")
        await asyncio.sleep(0.05)
        order.append("saldo:terminou")
        return pr._sol, 0.0 if not order.count("enviou") else 100.0

    async def tx(body, gate=None):
        order.append("montou")                            # a montagem não espera o saldo
        why = await gate() if gate else None
        if why:
            return {"status": "não executou", "reason": why, "gate": True}
        order.append("enviou")
        return {"ok": True, "signature": "s", "status": "confirmada"}
    pr.balances, pr._tx = balances, tx
    pr._sol = 1.0
    PumpReal.pool_hint[M] = "pump-amm"
    r = asyncio.run(pr.buy(M, 0.05))
    assert r["ok"] and order.index("montou") < order.index("saldo:terminou") < order.index("enviou")
    order.clear()
    pr._sol = 0.03
    PumpReal.pool_hint[M] = "pump-amm"
    r = asyncio.run(pr.buy(M, 0.05))
    assert not r["ok"] and "saldo insuficiente" in r["reason"] and "enviou" not in order
