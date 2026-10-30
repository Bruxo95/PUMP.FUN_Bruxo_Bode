"""0.32.98 (dono, 30/10 22:28): sendTransaction com HTTP 429 no RPC da carteira tenta de novo e cai para o RPC público."""
import asyncio

import pytest

from app.pumpfun import PumpReal, SOL_HTTP


class _W:
    async def safe_rpc_url(self):
        return "https://meu-rpc.exemplo"


def _real(answers):
    r = PumpReal.__new__(PumpReal)
    r.wallet = _W()
    calls = []

    async def rpc(method, params, url=None):
        calls.append(url)
        a = answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a
    r._rpc = rpc
    return r, calls


def test_send_retries_429_then_uses_public_rpc():
    r, calls = _real([RuntimeError("RPC respondeu HTTP 429 sem dados (limite de pedidos) em sendTransaction"),
                      RuntimeError("RPC respondeu HTTP 429 sem dados (limite de pedidos) em sendTransaction"), "SIG"])
    assert asyncio.run(r._send_raw("tx", {})) == "SIG"
    assert calls == ["https://meu-rpc.exemplo", "https://meu-rpc.exemplo", SOL_HTTP]


def test_send_does_not_repeat_when_the_network_rejects_the_transaction():
    r, calls = _real([RuntimeError("{'code': -32002, 'message': 'insufficient funds'}")])
    with pytest.raises(RuntimeError):
        asyncio.run(r._send_raw("tx", {}))
    assert len(calls) == 1


def test_simulation_6005_in_decimal_tries_pumpswap_and_jupiter():
    """PIO (30/10 22:47): {'Custom': 6005} = curva completou; antes a compra parava na 1ª rota por o código vir em decimal."""
    why = "transação recusada pela simulação: a simulação falhou: {'InstructionError': [3, {'Custom': 6005}]}"
    assert PumpReal.retryable(why)
    assert "graduou" in PumpReal.explain(why)
    assert not PumpReal.retryable("{'InstructionError': [3, {'Custom': 6063}]}")


def test_confirm_uses_public_rpc_when_wallet_rpc_is_rate_limited(monkeypatch):
    """BALLOON/MLC (30/10): 172 s para confirmar porque toda conferência no RPC da carteira dava 429."""
    import app.pumpfun as pfm
    r = PumpReal.__new__(PumpReal)
    r.wallet = _W()
    calls = []

    async def rpc(method, params, url=None):
        calls.append((method, url))
        if url != SOL_HTTP and method != "sendTransaction":
            raise RuntimeError("RPC respondeu HTTP 429 sem dados (limite de pedidos) em " + method)
        if method == "sendTransaction":
            return "SIG"
        return {"value": [{"confirmationStatus": "confirmed", "err": None}]}
    r._rpc = rpc

    async def fast(_):
        return None
    monkeypatch.setattr(pfm.asyncio, "sleep", fast)
    sig, st, err = asyncio.run(r._send_confirm("tx"))
    assert (sig, st) == ("SIG", "confirmada")
    assert ("getSignatureStatuses", SOL_HTTP) in calls
    assert sum(1 for m, _ in calls if m == "getSignatureStatuses") <= 2
