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
