"""Regressões da auditoria de 2026-10-25 (SEC-01 a SEC-04). Tudo offline: chaves descartáveis, blockhash zero,
RPC e provedores falsos — nenhuma transação sai daqui."""
import asyncio
import json

import httpx
import pytest

from tests.test_api import UA, UB, env, tok  # noqa: F401  (fixture env)

PUMP_MINT = "Tok".ljust(40, "1") + "pump"


def _kp_msg(instructions, kp=None):
    from solders.hash import Hash
    from solders.keypair import Keypair
    from solders.message import MessageV0
    kp = kp or Keypair()
    return kp, MessageV0.try_compile(kp.pubkey(), instructions, [], Hash.default())


def _pump_buy_ix(owner, mint, max_lamports):
    from solders.instruction import AccountMeta, Instruction
    from solders.pubkey import Pubkey
    from app import txguard
    data = txguard.PUMP_BUY + (1000).to_bytes(8, "little") + int(max_lamports).to_bytes(8, "little")
    return Instruction(Pubkey.from_string(txguard.PUMP), data,
                       [AccountMeta(Pubkey.from_string(mint), False, False), AccountMeta(owner, True, True)])


def _transfer(owner, lamports, to=None):
    from solders.keypair import Keypair
    from solders.system_program import TransferParams, transfer
    return transfer(TransferParams(from_pubkey=owner, to_pubkey=to or Keypair().pubkey(), lamports=int(lamports)))


# ---------------------------------------------------------------- SEC-01: conferir antes de assinar
def test_txguard_accepts_pump_buy_within_request_and_rejects_drain():
    from solders.pubkey import Pubkey
    from app import txguard
    kp, _ = _kp_msg([])
    me = kp.pubkey()
    mint = str(Pubkey.new_unique())
    lim = dict(max_spend_lamports=60_000_000, max_fee_lamports=2_000_000, mint=mint)
    _, ok = _kp_msg([_pump_buy_ix(me, mint, 57_500_000), _transfer(me, 250_000)], kp)
    assert txguard.check(ok, str(me), **lim)["spend"] == 57_500_000
    cases = [([_transfer(me, 9e9)], "terceiros"),                             # o caso da auditoria: 9 SOL
             ([_pump_buy_ix(me, mint, 9e9)], "acima do pedido"),               # máximo da compra inflado
             ([_pump_buy_ix(me, str(Pubkey.new_unique()), 5e7)], "token pedido")]
    for bad, why in cases:
        _, msg = _kp_msg(bad, kp)
        with pytest.raises(txguard.TxRejected, match=why):
            txguard.check(msg, str(me), **lim)
    from solders.instruction import Instruction
    _, unknown = _kp_msg([Instruction(Pubkey.new_unique(), b"\x01", [])], kp)
    with pytest.raises(txguard.TxRejected, match="programa não permitido"):
        txguard.check(unknown, str(me), **lim)
    _, other_payer = _kp_msg([])
    with pytest.raises(txguard.TxRejected, match="única assinante"):
        txguard.check(other_payer, str(me), **lim)


def test_pumpportal_malicious_tx_is_never_signed_or_sent():
    """Pedido de compra de 0,05 SOL; o provedor devolve transferência de 9 SOL → recusa, zero envios."""
    from solders.transaction import VersionedTransaction
    from app.pumpfun import TRADE_LOCAL_URL, PumpReal
    from app.settings import PumpSettings
    from app.solana_wallet import UserWallet
    kp, _ = _kp_msg([])
    _, evil = _kp_msg([_transfer(kp.pubkey(), 9e9)], kp)
    sent = []

    def handler(req):
        if str(req.url) == TRADE_LOCAL_URL:
            return httpx.Response(200, content=bytes(VersionedTransaction(evil, [kp])))
        sent.append(json.loads(req.content)["method"])
        return httpx.Response(200, json={"result": "SIG"})
    cfg = PumpSettings()
    cfg.pump_real_enabled = True
    pr = PumpReal(cfg, httpx.AsyncClient(transport=httpx.MockTransport(handler)), UserWallet(str(kp)), None)
    r = asyncio.run(pr._tx({"action": "buy", "mint": PUMP_MINT, "amount": 0.05, "denominatedInSol": "true"}))
    assert r["status"] == "recusada" and "verificação" in r["reason"] and not r.get("ok")
    assert "sendTransaction" not in sent


# ---------------------------------------------------------------- SEC-04: venda pendente
def test_pending_sell_is_not_rebuilt_before_reconciling():
    from app.pumpfun import PumpReal
    from app.settings import PumpSettings

    class W:
        keypair = object()
        address = "Me".ljust(44, "1")
    pr = PumpReal(PumpSettings(), None, W(), None)
    calls = []

    async def bal(mint):
        return 0.3, 1000.0                                  # saldo ainda antigo: a venda não apareceu

    async def tx(body):
        calls.append(body.get("slippage"))
        return {"ok": False, "status": "pendente", "signature": "SIG1", "reason": "sem confirmação"}
    pr.balances, pr._tx = bal, tx
    orig = asyncio.sleep

    async def fast(_s):
        await orig(0)
    asyncio.sleep = fast
    try:
        r = asyncio.run(pr.sell(PUMP_MINT, 0.5))
    finally:
        asyncio.sleep = orig
    assert calls == [15.0] and r["status"] == "pendente" and r["signature"] == "SIG1" and not r["ok"]


def test_reconcile_waits_for_signature_or_blockhash_expiry():
    from app import txguard
    answers = {"status": [None, None], "valid": [True, False]}

    async def rpc(method, params):
        if method == "getSignatureStatuses":
            v = answers["status"].pop(0) if answers["status"] else None
            return {"value": [v]}
        return {"value": answers["valid"].pop(0)}
    assert asyncio.run(txguard.reconcile(rpc, "S", "B", step=0))[0] == "expirada"

    async def rpc_ok(method, params):
        return {"value": [{"confirmationStatus": "confirmed", "err": None}]}
    assert asyncio.run(txguard.reconcile(rpc_ok, "S", "B", step=0)) == ("confirmada", None)

    async def rpc_stuck(method, params):
        return {"value": [None]} if method == "getSignatureStatuses" else {"value": True}
    assert asyncio.run(txguard.reconcile(rpc_stuck, "S", "B", timeout=0, step=0))[0] == "pendente"


def test_engine_holds_new_sell_while_previous_signature_is_unconfirmed(env):
    import time
    hub = env["hub"]
    pf = asyncio.run(hub.engine(UA))
    p = {"id": "p1", "real": True, "mint": PUMP_MINT, "symbol": "TOK", "tokens": 1000, "tokens_left": 1000,
         "sol_in": 0.05, "proceeds": 0.0, "selling": True, "opened_at": "x", "wallet": "w",
         "sell_pending": {"signature": "SIG1", "at": time.time()}}
    pf._save_pos(p)
    sells = []

    class FakeReal:
        async def signature_status(self, sig):
            return None

        async def sell(self, *a, **k):
            sells.append(a)
            return {"ok": False}
    pf.real = FakeReal()
    asyncio.run(pf._real_do_sell({"id": "p1", "frac": 0.5, "why": "teste"}))
    pos = next(x for x in pf.positions() if x["id"] == "p1")
    assert sells == [] and pos["sell_pending"]["signature"] == "SIG1" and not pos["selling"]


# ---------------------------------------------------------------- SEC-03: RPC para destino interno
def test_rpc_internal_destinations_are_refused(env):
    c = env["c"]
    for bad in ("https://127.0.0.1:8443/internal-rpc", "https://localhost/x", "https://10.0.0.5/",
                "https://169.254.169.254/", "https://user:pw@rpc.exemplo.com/", "https://127.1/"):
        r = c.post("/api/secrets", json={"name": "rpc_url", "value": bad}, headers=tok(UA)).json()
        assert r.get("error") and not r.get("ok"), bad


def test_rpc_hostname_resolving_to_internal_ip_gets_no_request():
    from app.jupiter import JupiterQuoter, JupiterWallet
    from app.solana_wallet import UserWallet
    from solders.keypair import Keypair
    seen = []
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: seen.append(req) or httpx.Response(200)))
    w = UserWallet(str(Keypair()), "https://rpc.parece-publico.com/x")

    async def internal(host):
        return ["10.20.30.40"]
    w.resolver = internal
    out = asyncio.run(JupiterWallet(client, w, JupiterQuoter(client)).sol_balances(force=True))
    assert "público" in out["error"] and seen == []


# ---------------------------------------------------------------- SEC-02: bloqueio durante a carga do motor
def test_block_during_engine_load_does_not_put_account_back(env):
    from app.hub import AccountBlocked
    hub = env["hub"]

    async def go():
        gate, orig = asyncio.Event(), hub._load

        async def slow(uid):
            await gate.wait()
            return await orig(uid)
        hub._load = slow
        loading = asyncio.create_task(hub.engine(UB))
        await asyncio.sleep(0)
        blocking = asyncio.create_task(hub.admin_update_user(UA, UB, {"bloqueado": True}))
        await asyncio.sleep(0.01)
        gate.set()
        with pytest.raises(AccountBlocked):
            await loading
        assert (await blocking)["ok"] and UB not in hub.engines
        with pytest.raises(AccountBlocked):
            await hub.engine(UB)
    asyncio.run(go())
    assert env["c"].get("/api/pump", headers=tok(UB, "b@x.com")).status_code == 403


# ---------------------------------------------------------------- SEC-05: ranking forçado com a chave do sistema
def test_leaderboard_refresh_from_panel_has_cooldown_and_shared_limit(env):
    from app.pumpfun import PumpFun
    c, hub = env["c"], env["hub"]
    PumpFun._lb_shared_calls.clear()
    assert c.post("/api/admin/keys", json={"name": "solanatracker_api_key", "value": "st-SIS-" + "s" * 30},
                  headers=tok(UA)).json()["ok"]
    eb = asyncio.run(hub.engine(UB))
    hits = []

    def h(req):
        hits.append(req.url.host)
        return httpx.Response(200, json={"traders": []})
    eb.http = httpx.AsyncClient(transport=httpx.MockTransport(h))
    B = tok(UB, "b@x.com")
    c.post("/api/pump/leaderboard", json={"days": 7}, headers=B)
    r = c.post("/api/pump/leaderboard", json={"days": 7}, headers=B).json()
    assert len(hits) == 1 and "tente de novo" in r["error"]                     # 2º clique: nada consultado
    eb._lb_at = 0                                                               # passou o intervalo da conta…
    PumpFun._lb_shared_calls.extend([__import__("time").time()] * PumpFun.LB_SHARED_PER_MIN)
    msg = asyncio.run(eb.refresh_leaderboard_user())                            # …mas o limite geral segura
    assert "chave do sistema" in msg and len(hits) == 1
    PumpFun._lb_shared_calls.clear()


# ---------------------------------------------------------------- SEC-06: token falso repetido
def test_rejected_token_is_remembered_and_jwks_reload_is_limited():
    import time as _t
    import jwt as _jwt
    from app.auth import Auth, AuthError
    from tests.test_api import SB
    calls = []

    def h(req):
        calls.append(req.url.path)
        if req.url.path.endswith("jwks.json"):
            return httpx.Response(200, json={"keys": []})
        return httpx.Response(401, json={"msg": "invalid"})
    a = Auth(SB, "anon", httpx.AsyncClient(transport=httpx.MockTransport(h)))
    fake = _jwt.encode({"sub": UA, "exp": int(_t.time()) + 60}, "x" * 32, algorithm="HS256")
    for _ in range(3):
        with pytest.raises(AuthError):
            asyncio.run(a.verify(fake))
    assert calls == ["/auth/v1/user"]                                           # antes: 1 consulta por tentativa
    calls.clear()
    for i in range(3):                                                          # tokens diferentes, kid desconhecido
        t = "eyJhbGciOiJFUzI1NiIsImtpZCI6Im5vdm8ifQ." + f"e30{i}" + ".c2ln"
        with pytest.raises(AuthError):
            asyncio.run(a.verify(t))
    assert calls.count("/auth/v1/.well-known/jwks.json") <= 2                  # 1 normal + no máx. 1 forçada


# ---------------------------------------------------------------- SEC-09 e SEC-11
def test_rpc_host_never_shows_credentials_and_huge_numbers_are_validation_errors(env):
    from app.solana_wallet import UserWallet
    assert UserWallet("", "https://rpc.exemplo.com/?api-key=segredo").public()["rpc_host"] == "rpc.exemplo.com"
    c = env["c"]
    r = c.post("/api/pump/settings", json={"pump_max_open": "1e1000", "pump_stop_pct": "nan"}, headers=tok(UA))
    assert r.status_code == 200 and set(r.json()["errors"]) == {"pump_max_open", "pump_stop_pct"}
    r = c.post("/api/pump/swap", json={"confirm": True, "usdc": "abc"}, headers=tok(UA))
    assert r.status_code == 200 and r.json()["error"] == "valor inválido"


def test_txguard_program_ids_match_the_rest_of_the_engine():
    """O ID da PumpSwap no txguard estava digitado errado (achado em 2026-10-25): toda venda/compra na PumpSwap
    seria recusada. Os IDs e discriminadores precisam bater com o motor e com o IDL oficial."""
    from app import txguard
    from app.pumpfun import PUMP_PROGRAMS
    assert (txguard.PUMP, txguard.PUMP_AMM) == PUMP_PROGRAMS
    assert txguard.PUMP_BUY.hex() == "66063d1201daebea" and txguard.PUMP_SELL.hex() == "33e685a4017f83ad"
    assert txguard.PUMP_BUY_SOL_IN.hex() == "38fc74089edfcd5f"


# ---------------------------------------------------------------- risco do token antes de copiar (0.9.3)
def test_token_risk_from_solana_tracker_blocks_dangerous_tokens(env):
    pf = asyncio.run(env["hub"].engine(UA))
    mint = "Risk".ljust(40, "1") + "pump"
    seen = []

    def h(req):
        seen.append((req.url.path, req.headers.get("x-api-key")))
        return httpx.Response(200, json={"risk": {"score": 9, "rugged": False, "risks": [
            {"name": "Freeze Authority Enabled", "level": "danger", "score": 7500},
            {"name": "Top 10 Holders", "level": "warn", "score": 1000}]}})
    pf.http = httpx.AsyncClient(transport=httpx.MockTransport(h))
    asyncio.run(pf.risk_check(mint, "chave-st"))
    asyncio.run(pf.risk_check(mint, "chave-st"))                                # cache: 1 consulta só
    assert seen == [("/tokens/" + mint, "chave-st")]
    tk = pf.tokens[mint]
    assert "Freeze Authority" in pf.risk_block(tk)
    tk["risk"] = {"score": 8, "rugged": False, "danger": [], "warn": ["Top 10 Holders"]}
    assert "8/10" in pf.risk_block(tk)                                          # nota acima do máximo (7)
    tk["risk"]["score"] = 5
    assert pf.risk_block(tk) is None
    pf.cfg.pump_risk_check = False
    tk["risk"] = {"score": 10, "rugged": True, "danger": ["x"], "warn": []}
    assert pf.risk_block(tk) is None                                            # desligado: não bloqueia
    assert pf.risk_block({}) is None                                            # sem dados: não bloqueia
