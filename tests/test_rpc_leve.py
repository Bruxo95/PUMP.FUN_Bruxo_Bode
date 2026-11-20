"""0.32.402 (pedido do dono: "mudar a compra e a venda para não ter erros" — 429 do RPC): cada compra e venda REAL gasta menos
RPC. Saldo numa consulta leve (getMultipleAccounts), lista das contas de token guardada 60 s na simulação, e espera maior
quando o RPC responde 429. Sem internet."""
import asyncio

from solders.pubkey import Pubkey

from app import txguard
from app.pumpfun import PumpReal

ME = str(Pubkey.new_unique())
MINT = str(Pubkey.new_unique())


class W:
    address = ME

    async def safe_rpc_url(self):
        return "https://meu-rpc.exemplo.test"


def _pr(rpc):
    pr = PumpReal.__new__(PumpReal)
    pr.wallet, pr._rpc = W(), rpc
    return pr


def _tok(ui, amount=None):
    return {"data": {"parsed": {"info": {"mint": MINT, "tokenAmount": {"uiAmount": ui, "uiAmountString": str(ui),
                                                                       "amount": str(amount or int(ui * 1e6))}}}}}


def test_saldo_numa_consulta_leve():
    calls = []

    async def rpc(method, params, url=None):
        calls.append(method)
        assert method == "getMultipleAccounts" and params[0][0] == ME and set(params[0][1:]) == txguard.token_atas(ME, MINT)
        return {"value": [{"lamports": 2_500_000_000}, _tok(1234.5), None]}
    assert asyncio.run(_pr(rpc).balances(MINT)) == (2.5, 1234.5)
    assert calls == ["getMultipleAccounts"]                     # antes: getBalance + getTokenAccountsByOwner


def test_sem_o_token_na_conta_associada_confere_do_jeito_completo():
    calls = []

    async def rpc(method, params, url=None):
        calls.append(method)
        if method == "getMultipleAccounts":
            return {"value": [{"lamports": 1_000_000_000}, None, None]}
        if method == "getBalance":
            return {"value": 1_000_000_000}
        return {"value": [{"account": _tok(7.0)}]}               # o token está numa conta que não é a associada
    pr = _pr(rpc)
    assert asyncio.run(pr.balances(MINT)) == (1.0, 7.0)          # venda: não pode achar "sem saldo" por engano
    assert "getTokenAccountsByOwner" in calls
    calls.clear()
    pr._zero_ok = MINT                                            # antes de comprar: não ter o token é o normal
    assert asyncio.run(pr.balances(MINT)) == (1.0, 0.0) and calls == ["getMultipleAccounts"]


def test_simulacao_guarda_a_lista_e_le_os_saldos_numa_consulta():
    other = str(Pubkey.new_unique())
    calls = []

    async def rpc(method, params, url=None):
        calls.append(method)
        if method == "getTokenAccountsByOwner":
            if params[1]["programId"] != txguard.TOKEN:
                return {"value": []}
            return {"value": [{"pubkey": other, "account": {"data": {"parsed": {"info": {"mint": "Outro", "tokenAmount": {"amount": "500"}}}}}}]}
        if method == "getBalance":
            return {"value": 1_000_000_000}
        if method == "getMultipleAccounts":
            return {"value": [{"lamports": 1_000_000_000},
                              {"data": {"parsed": {"info": {"mint": "Outro", "tokenAmount": {"amount": "500"}}}}}]}
        import base64
        data = bytearray(165)
        data[64:72] = (500).to_bytes(8, "little")
        return {"value": {"err": None, "logs": [f"Program {txguard.PUMP} invoke [2]"],
                          "accounts": [{"lamports": 1_000_000_000 - 50_000_000}, {"data": [base64.b64encode(bytes(data)).decode(), "base64"]}]}}
    pr = _pr(rpc)
    caps = {"max_spend_lamports": 60_000_000, "max_fee_lamports": 2_000_000, "max_priority_lamports": 2_000_000}
    assert asyncio.run(pr._sim_guard("x", MINT, caps)) is None
    assert calls.count("getTokenAccountsByOwner") == 2
    calls.clear()
    assert asyncio.run(pr._sim_guard("x", MINT, caps)) is None   # segunda operação em menos de 60 s
    assert "getTokenAccountsByOwner" not in calls and "getBalance" not in calls and calls[0] == "getMultipleAccounts"


def test_429_espera_mais_antes_de_tentar_de_novo(monkeypatch):
    esperas = []
    orig = asyncio.sleep

    async def fake(s):
        esperas.append(s)
        await orig(0)
    monkeypatch.setattr(asyncio, "sleep", fake)
    n = {"i": 0}

    async def rpc(method, params, url=None):
        n["i"] += 1
        if n["i"] < 3:
            raise RuntimeError("{'code': 429, 'message': 'Too many requests for a specific RPC call'}")
        return {"value": 1}
    assert asyncio.run(_pr(rpc)._rpc_retry("getBalance", [ME])) == {"value": 1}
    assert esperas == [1.0, 2.0]                                  # antes: 0,15 s e 0,3 s
