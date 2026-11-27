"""0.32.483 (pedido do dono: muitos tokens fora por "passou de 25% do BOOST sem confirmar"): preço do pool direto da blockchain
desde o 1º segundo (sem esperar a Jupiter indexar o pool novo) e o motivo do que faltou quando não confirma."""
import asyncio
import base64

from app import boostmig as bmod
from app.boostmig import BoostMig, vault_amount, vaults_from_tx
from tests.test_boostmig import M, Svc

WSOL = bmod.SOL_MINT
POOL, VB, VQ = "Pool".ljust(44, "1"), "VauB".ljust(44, "1"), "VauQ".ljust(44, "1")


def run(c):
    return asyncio.new_event_loop().run_until_complete(c)


def tx_migracao():
    keys = [{"pubkey": "Sig1".ljust(44, "1")}, {"pubkey": VB}, {"pubkey": VQ}, {"pubkey": "Out1".ljust(44, "1")}]
    return {"transaction": {"message": {"accountKeys": keys}}, "meta": {"err": None, "postTokenBalances": [
        {"accountIndex": 1, "mint": M, "owner": POOL, "uiTokenAmount": {"amount": str(206_900_000 * 10 ** 6), "decimals": 6}},
        {"accountIndex": 2, "mint": WSOL, "owner": POOL, "uiTokenAmount": {"amount": str(85 * 10 ** 9), "decimals": 9}},
        {"accountIndex": 3, "mint": M, "owner": "Outro".ljust(44, "1"), "uiTokenAmount": {"amount": "5", "decimals": 6}}]}}


def acc(amount):
    raw = bytes(64) + int(amount).to_bytes(8, "little") + bytes(93)
    return {"data": [base64.b64encode(raw).decode(), "base64"]}


def test_contas_do_pool_pela_transacao_da_migracao():
    v = vaults_from_tx(tx_migracao(), M)
    assert v["pool"] == POOL and v["base"] == VB and v["quote"] == VQ
    assert abs(v["px"] - 85 / 206_900_000) < 1e-15
    assert vaults_from_tx({"meta": {"err": {"x": 1}}}, M) is None and vaults_from_tx(None, M) is None
    assert vault_amount(acc(123)) == 123 and vault_amount(None) is None


def test_preco_do_pool_vira_leitura_da_observacao_sem_jupiter():
    now = 1_000_000.0
    svc = Svc({})

    async def get_tx(sig, *a, **k):
        return tx_migracao()
    svc._get_tx = get_tx
    bm = BoostMig(svc, clock=lambda: now)
    calls = []

    async def multi(keys, enc):
        calls.append(list(keys))
        return [acc(200_000_000 * 10 ** 6), acc(90 * 10 ** 9)]
    bm.rpc_multi = multi
    b = bm.on_migration({"mint": M, "txType": "migrate", "pool": "pump-amm", "signature": "abc"}, now)
    run(bm._pool_find(now))
    assert b["vaults"]["base"] == VB
    run(bm._pool_prices(now + 1))
    assert calls == [[VB, VQ]] and b["px_src"] == "pool (blockchain)"
    assert abs(b["samples"][-1][1] - 90 / 200_000_000) < 1e-15
    run(bm._pool_prices(now + 1.5))                       # antes de 1,5 s não consulta de novo
    assert len(calls) == 1


def test_motivo_do_que_faltou_quando_passa_do_limite():
    import inspect
    from app import hub
    src = inspect.getsource(hub.PumpHub._bm_user)
    assert "faltou: " in src and 'u.get("estado") == "esperar"' in src
