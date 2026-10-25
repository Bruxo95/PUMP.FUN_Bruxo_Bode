"""Provas da auditoria de carteiras, exclusivamente offline.

Executar da raiz: .venv/Scripts/python.exe docs/auditoria/2026-10-25/poc-carteiras.py
HTTP usa MockTransport, banco usa FakeREST e chaves são geradas para descarte.
Nenhuma transação é transmitida. A mensagem de teste usa blockhash zero.
Não substituir os mocks por clientes reais.
"""
from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import httpx
import pytest
from solders.hash import Hash
from solders.keypair import Keypair
from solders.message import MessageV0
from solders.null_signer import NullSigner
from solders.system_program import TransferParams, transfer
from solders.transaction import VersionedTransaction

from app.jupiter import JupiterQuoter, JupiterWallet
from app.keystore import KeyRing
from app.pumpfun import PumpReal
from app.settings import PumpSettings
from app.solana_wallet import UserWallet
from tests.test_api import UA, env, tok


def rpc_target_and_userinfo() -> dict:
    """Reproduz pelas rotas reais, mas com banco/HTTP inteiramente falsos."""
    monkeypatch = pytest.MonkeyPatch()
    try:
        local = env.__wrapped__(monkeypatch)
        client = local["c"]
        calls = []

        def fake_rpc(request):
            body = json.loads(request.content)
            calls.append({"url": str(request.url), "method": body["method"]})
            value = 1_000_000_000 if body["method"] == "getBalance" else []
            return httpx.Response(200, json={"result": {"value": value}})

        local["hub"].http._transport = httpx.MockTransport(fake_rpc)
        response = client.post("/api/secrets", headers=tok(UA), json={
            "name": "rpc_url", "value": "https://demo:discardable-pass@127.0.0.1:8443/internal-rpc"})
        view = client.get("/api/secrets", headers=tok(UA)).json()
        client.post("/api/secrets", headers=tok(UA), json={
            "name": "wallet_private_key", "value": str(Keypair())})
        balance = client.get("/api/pump/wallet?force=1", headers=tok(UA))
        assert response.json()["ok"]
        assert "discardable-pass" in json.dumps(view)
        assert len(calls) == 3 and all("127.0.0.1:8443" in c["url"] for c in calls)
        return {"rpc_saved": True, "userinfo_in_api_response": True,
                "balance_status": balance.status_code, "mock_rpc_calls": calls}
    finally:
        monkeypatch.undo()


async def unvalidated_external_transactions() -> dict:
    """Retorno de builder comprometido simulado; assinatura local, sem broadcast."""
    keypair, destination = Keypair(), Keypair().pubkey()
    wallet = UserWallet(str(keypair), "https://rpc.example.test")
    instruction = transfer(TransferParams(
        from_pubkey=keypair.pubkey(), to_pubkey=destination, lamports=9_000_000_000))
    message = MessageV0.try_compile(keypair.pubkey(), [instruction], [], Hash.default())
    raw = bytes(VersionedTransaction(message, [NullSigner(keypair.pubkey())]))
    observed = []

    def fake_builder(request):
        if "pumpportal" in request.url.host:
            return httpx.Response(200, content=raw)
        return httpx.Response(200, json={"swapTransaction": base64.b64encode(raw).decode()})

    async def no_broadcast(encoded):
        transaction = VersionedTransaction.from_bytes(base64.b64decode(encoded))
        amount = int.from_bytes(bytes(transaction.message.instructions[0].data)[4:12], "little")
        valid = all(transaction.verify_with_results())
        assert valid and amount == 9_000_000_000
        observed.append({"signature_valid": valid, "unexpected_lamports": amount})
        return "LOCAL_ONLY", "not_broadcast", None

    async with httpx.AsyncClient(transport=httpx.MockTransport(fake_builder)) as http:
        config = PumpSettings()
        config.pump_real_enabled = True  # somente objeto descartável, nenhum ambiente real
        real = PumpReal(config, http, wallet, KeyRing())
        real._send_confirm = no_broadcast
        await real._tx({"action": "buy", "mint": str(Keypair().pubkey()), "amount": 0.05})
        jupiter = JupiterWallet(http, wallet, JupiterQuoter(http, per_min=100_000))
        await no_broadcast(await jupiter._swap_tx({
            "inputMint": "USDC", "outputMint": "SOL", "inAmount": "1", "outAmount": "1"}))
    return {"requested_buy_sol": 0.05, "signed_mock_transactions": observed, "broadcasts": 0}


async def pending_sell_retry() -> dict:
    """Modelo de confirmação atrasada: saldo continua antigo durante a primeira consulta."""
    wallet = UserWallet(str(Keypair()), "https://rpc.example.test")
    real = PumpReal(PumpSettings(), None, wallet, KeyRing())
    # antes, primeira consulta ainda antiga, depois ambas as vendas confirmadas
    balances = iter([(1, 1000), (1, 1000), (1.75, 250)])
    attempts = []

    async def fake_balances(_mint):
        return next(balances)

    async def fake_transaction(body):
        attempts.append(dict(body))
        if len(attempts) == 1:
            return {"status": "pendente", "signature": "MOCK_A", "reason": "sem confirmação"}
        return {"status": "confirmada", "signature": "MOCK_B", "ok": True}

    async def no_sleep(_seconds):
        return None

    real.balances, real._tx = fake_balances, fake_transaction
    with patch("app.pumpfun.asyncio.sleep", new=no_sleep):
        result = await real.sell("discardable-mint", 0.5)
    assert len(attempts) == 2 and [a["amount"] for a in attempts] == ["50%", "50%"]
    assert result["tokens_left"] == 250
    return {"requested_fraction": 0.5, "attempts": len(attempts),
            "amount_each": [a["amount"] for a in attempts], "modeled_tokens_left": result["tokens_left"]}


async def main():
    print(json.dumps({"rpc": rpc_target_and_userinfo()}, ensure_ascii=True))
    print(json.dumps({"signing": await unvalidated_external_transactions()}, ensure_ascii=True))
    print(json.dumps({"pending_retry": await pending_sell_retry()}, ensure_ascii=True))


if __name__ == "__main__":
    asyncio.run(main())
