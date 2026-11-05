"""0.32.215 (dono, 05/11: compra REAL de 0,001 SOL gastou 0,0073 SOL): depois da venda total, a conta do token com saldo zero
é fechada e o aluguel volta para a carteira e para o trade. Carteira falsa: nenhuma transação de verdade."""
import asyncio
import base64

from app.pumpfun import PumpReal
from tests.test_espelho_real import A, FakeReal, _pf


class FakeRealClose(FakeReal):
    def __init__(self, back=0.00203):
        super().__init__()
        self.back = back

    async def close_empty(self, mint):
        self.calls.append(("close", mint))
        return self.back


def _open_real(pf):
    pf.tokens[A] = {"price": 1e-6, "symbol": "ESP", "mcap_sol": 40.0}
    pf.manual_buy(A, target="real", amt_sol=0.001)
    kind, it = pf._rq.get_nowait()
    asyncio.run(pf._real_buy(it))
    return [p for p in pf.positions() if p.get("real")][0]


def test_full_sell_closes_the_token_account_and_credits_the_trade(tmp_path):
    pf = _pf(tmp_path)
    pf.real = FakeRealClose()
    p = _open_real(pf)
    pf._real_sell(p, 1.0, "teste")
    kind, it = pf._rq.get_nowait()
    asyncio.run(pf._real_do_sell(it))
    tr = [t for t in pf.trades() if t.get("real")][0]
    assert ("close", A) in pf.real.calls
    assert tr["conta_devolvida_sol"] == 0.00203 and abs(tr["sol_out"] - (0.01 + 0.00203)) < 1e-9
    assert any(f["action"] == "conta do token fechada" for f in pf.feed)


def test_no_close_without_the_method_or_when_nothing_comes_back(tmp_path):
    pf = _pf(tmp_path)                                  # FakeReal sem close_empty: segue como antes
    p = _open_real(pf)
    pf._real_sell(p, 1.0, "teste")
    kind, it = pf._rq.get_nowait()
    asyncio.run(pf._real_do_sell(it))
    tr = [t for t in pf.trades() if t.get("real")][0]
    assert not tr.get("conta_devolvida_sol") and abs(tr["sol_out"] - 0.01) < 1e-9


def test_close_empty_only_closes_zero_balance_accounts_of_the_wallet():
    import pytest
    pytest.importorskip("solders")
    from solders.keypair import Keypair
    from solders.transaction import Transaction
    kp = Keypair()
    me = str(kp.pubkey())
    other_owner = str(Keypair().pubkey())
    acc_zero, acc_full, acc_other = str(Keypair().pubkey()), str(Keypair().pubkey()), str(Keypair().pubkey())

    class W:
        keypair = kp
        address = me

    rr = PumpReal.__new__(PumpReal)
    rr.wallet = W()
    sent = []

    def acc(pub, amount, owner):
        return {"pubkey": pub, "account": {"owner": PumpReal.TOKEN_PROGRAMS[0], "lamports": 2039280,
                                           "data": {"parsed": {"info": {"owner": owner, "tokenAmount": {"amount": str(amount)}}}}}}

    async def rpc_retry(method, params):
        if method == "getTokenAccountsByOwner":
            return {"value": [acc(acc_zero, 0, me), acc(acc_full, 5, me), acc(acc_other, 0, other_owner)]}
        return {"value": {"blockhash": "11111111111111111111111111111111"}}

    async def send_confirm(raw, simulated=False):
        sent.append(raw)
        return "SIG", "confirmada", None
    rr._rpc_retry, rr._send_confirm = rpc_retry, send_confirm
    back = asyncio.run(rr.close_empty("M"))
    assert abs(back - (2039280 / 1e9 - PumpReal.CLOSE_FEE_SOL)) < 1e-12
    tx = Transaction.from_bytes(base64.b64decode(sent[0]))
    keys = [str(k) for k in tx.message.account_keys]
    assert acc_zero in keys and acc_full not in keys and acc_other not in keys     # só a conta vazia da própria carteira
    assert len(tx.message.instructions) == 1 and bytes(tx.message.instructions[0].data) == bytes([9])
