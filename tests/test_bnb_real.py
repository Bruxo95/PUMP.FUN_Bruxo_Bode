"""0.32.172: carteira REAL da BNB. Sem internet e sem enviar nada: a rede é falsa (fake do RPC ou da Chain)."""
import asyncio
import time

from app import bnb, bnbreal, evm
from tests.test_api import env  # noqa: F401  (fixture env)
from tests.test_bnb import TOK, W1, W2, _Http

U = "11111111-1111-1111-1111-111111111111"
KEY = "0x" + "46" * 32
ADDR = evm.address_of(evm.parse_key(KEY))


class _Vault:
    def __init__(self):
        self.d = {}

    async def load(self, uid):
        return dict(self.d.get(uid, {}))

    async def save(self, uid, name, value):
        self.d.setdefault(uid, {})[name] = value

    async def delete(self, uid, name):
        self.d.get(uid, {}).pop(name, None)


class _Chain:
    """Chain falsa: guarda o que seria enviado."""

    def __init__(self, fail_sell=0):
        self.buys, self.sells, self.fail_sell = [], [], fail_sell

    async def balance(self, addr):
        return int(1e18)

    async def buy(self, key, addr, token, quote, amt, bnb_usd, slip, gwei):
        self.buys.append((token, quote, amt, slip))
        return {"raw": 1000 * 10 ** 18, "bnb": amt + 0.00002, "tx": "0xbuy", "gas": 0.00002}

    async def sell(self, key, addr, token, quote, raw, graduated, slip, gwei):
        if self.fail_sell:
            self.fail_sell -= 1
            raise bnbreal.ChainError("a rede recusou na simulação: Slippage")
        self.sells.append((token, raw, graduated))
        return {"bnb": raw / 1e18 * 0.00002, "tx": "0xsell", "gas": 0.00002}


def _watch(on=True, chain=None):
    w = bnb.BnbWatch(_Http([], {}), None)
    w.bnb_usd, w.real_allowed, w.vault = 600, True, _Vault()
    w.vault.d[U] = {"bnb_private_key": KEY}
    w.chain = chain or _Chain()
    w.book(U)
    w.quotes[TOK] = bnb.ZERO
    w.safe.mark(TOK, True)                       # 0.32.177: token já aprovado pela segurança
    if on:
        w.rcfg(U)["real_on"] = True
    return w


def _buy(wallet=W1, t=None, token=TOK):
    return {"id": "a:%s" % wallet, "tx": "a", "block": 1, "token": token, "wallet": wallet, "side": "buy", "price": 0.00001,
            "amount": 1000, "value": 0.01, "fee": 0.0001, "t": t or time.time(), "quote": bnb.ZERO}


async def _drain(w):
    while w._tasks:
        await asyncio.gather(*list(w._tasks))


def test_real_follows_buy_and_sells_same_fraction():
    async def go():
        w = _watch()
        tr = _buy()
        w._add(tr)
        w._copy(tr, 0.0, {W1})
        await _drain(w)
        rb = w.real[U]
        assert len(rb.pos) == 1 and w.chain.buys[0][2] == 0.01 and rb.events[0]["acao"] == "REAL comprou"
        p = next(iter(rb.pos.values()))
        assert p["real"] and p["raw_left"] == str(1000 * 10 ** 18) and p["tx_in"] == "0xbuy"
        sell = {**tr, "id": "s:0", "side": "sell", "amount": 500, "price": 0.00002}
        before = w.hold[(W1, TOK)]
        w._add(sell)
        w._copy(sell, before, {W1})
        await _drain(w)
        assert w.chain.sells[0][1] == 500 * 10 ** 18 and p["raw_left"] == str(500 * 10 ** 18) and p["vendas"][0]["frac"] == 0.5
        pn = w.painel(U, real=True)
        assert pn["real"] and pn["posicoes"][0]["real"] and pn["carteira"]["endereco"] == ADDR
    asyncio.run(go())


def test_real_off_does_not_buy_and_old_fictitious_positions_are_not_copied():
    async def go():
        w = _watch(on=False)
        tr = _buy()
        w._add(tr)
        w._copy(tr, 0.0, {W1})                     # a fictícia compra; a REAL está desligada
        await _drain(w)
        assert len(w.books[U].pos) == 1 and not w.chain.buys
        await w.set_real(U, True)                  # ligou depois: a posição que a fictícia já tinha NÃO vai para a REAL
        await w.real_tick()
        await _drain(w)
        assert not w.chain.buys and not w.rbook(U).pos
        old = _buy(W2, t=time.time() - 3600)       # compra antiga (recuperação após reinício) também não
        w._add(old)
        w._copy(old, 0.0, {W2})
        await _drain(w)
        assert not w.chain.buys
    asyncio.run(go())


def test_real_limits_and_lock():
    async def go():
        w = _watch()
        w.real_allowed = False
        tr = _buy()
        w._add(tr)
        w._copy(tr, 0.0, {W1})
        await _drain(w)
        assert not w.chain.buys and "trava geral" in w.real[U].events[0]["motivo"]
        w.real_allowed = True
        w.quotes[TOK] = "0x" + "12" * 20           # moeda desconhecida: não compra
        w._copy({**tr, "id": "b:0"}, 0.0, {W1})
        await _drain(w)
        assert not w.chain.buys and "moeda" in w.real[U].events[0]["motivo"]
    asyncio.run(go())


def test_real_sell_failure_waits_and_retries():
    async def go():
        w = _watch(chain=_Chain(fail_sell=1))
        tr = _buy()
        w._add(tr)
        w._copy(tr, 0.0, {W1})
        await _drain(w)
        p = next(iter(w.real[U].pos.values()))
        r = await w._real_sell(U, p, 1.0, "trader vendeu 100%")
        assert r is None and p["sell_error"] and p["sell_retry_at"] > time.time()
        assert await w._real_sell(U, p, 1.0, "de novo") is None and not w.chain.sells      # ainda esperando
        p["sell_retry_at"] = 0
        await w.real_tick()
        await _drain(w)
        assert w.chain.sells and not w.real[U].pos and w.real[U].trades[0]["real"]
    asyncio.run(go())


def test_set_real_needs_key_and_lock():
    async def go():
        w = _watch(on=False)
        w.vault.d[U] = {}
        try:
            await w.set_real(U, True)
            assert False
        except ValueError as e:
            assert "chave" in str(e)
        await w.set_key(U, KEY)
        st = await w.set_real(U, True)
        assert st["ligada"] and st["endereco"] == ADDR
        w.real_allowed = False
        try:
            await w.set_real(U, True)
            assert False
        except ValueError as e:
            assert "trava geral" in str(e)
        await w.remove_key(U)
        assert not w.rcfg(U)["real_on"]
    asyncio.run(go())


def test_chain_buy_builds_four_meme_call():
    calls = []

    async def rpc(method, params):
        calls.append((method, params))
        if method == "eth_call" and params[0]["data"].startswith(bnbreal.SEL["try_buy"]):
            w = [int(bnbreal.TM2, 16), 0, 5000 * 10 ** 18, 0, 0, 10 ** 16, 0, 10 ** 16]
            return "0x" + "".join(evm.w_int(x) for x in w)
        if method == "eth_estimateGas":
            return hex(430000)
        if method == "eth_gasPrice":
            return hex(50_000_000)
        if method == "eth_getTransactionCount":
            return "0x3"
        if method == "eth_sendRawTransaction":
            return "0x00"
        if method == "eth_getTransactionReceipt":
            log = {"address": TOK, "topics": [bnbreal.T_TRANSFER, "0x" + "0" * 64, "0x" + ADDR[2:].rjust(64, "0")],
                   "data": hex(4900 * 10 ** 18)}
            return {"status": "0x1", "gasUsed": hex(400000), "effectiveGasPrice": hex(100_000_000), "logs": [log], "transactionHash": "0xh"}
        raise AssertionError(method)

    async def go():
        orig = asyncio.sleep

        async def fast(_):
            await orig(0)
        asyncio.sleep = fast
        try:
            res = await bnbreal.Chain(rpc).buy(evm.parse_key(KEY), ADDR, TOK, bnb.ZERO, 0.01, 600, 10, 0.1)
        finally:
            asyncio.sleep = orig
        est = [c for c in calls if c[0] == "eth_estimateGas"][0][1][0]
        assert est["to"] == bnbreal.TM2 and est["data"].startswith(bnbreal.SEL["buy"]) and int(est["value"], 16) == 10 ** 16
        assert int(est["data"][10 + 128:10 + 192], 16) == 4500 * 10 ** 18            # mínimo = estimativa − 10%
        assert res["raw"] == 4900 * 10 ** 18 and abs(res["bnb"] - (0.01 + 0.00004)) < 1e-12
    asyncio.run(go())


def test_real_routes(env):
    from tests.test_api import UA, UB, tok
    c, hub = env["c"], env["hub"]
    w = hub.bnb = bnb.BnbWatch(_Http([], {}), None)
    w.vault = _Vault()
    assert c.post("/api/pump/bnb/chave", json={"value": "abc"}, headers=tok(UA)).json()["error"].startswith("chave privada inválida")
    r = c.post("/api/pump/bnb/chave", json={"value": KEY}, headers=tok(UA)).json()
    assert r["ok"] and r["endereco"] == ADDR
    assert c.post("/api/pump/bnb/real", json={"on": True}, headers=tok(UA)).json()["error"].startswith("para ligar")
    assert "trava geral" in c.post("/api/pump/bnb/real", json={"on": True, "confirm": "LIGAR"}, headers=tok(UA)).json()["error"]
    w.real_allowed = True
    assert c.post("/api/pump/bnb/real", json={"on": True, "confirm": "LIGAR"}, headers=tok(UA)).json()["status"]["ligada"]
    r = c.post("/api/pump/bnb/real/cfg", json={"real_bnb_por_compra": 50, "real_on": False}, headers=tok(UA)).json()
    assert r["cfg"]["real_bnb_por_compra"] == 1 and r["cfg"]["real_on"] is True               # limite de 1 BNB; ligar só pela rota
    pn = c.get("/api/pump/bnb/painel?real=1", headers=tok(UA)).json()
    assert pn["real"] and pn["real_status"]["endereco"] == ADDR and "bnb_private_key" not in str(pn) and KEY[2:] not in str(pn)
    assert c.post("/api/pump/bnb/fechar-todas", json={"real": True}, headers=tok(UA)).json()["error"].startswith("para vender")
    assert c.post("/api/pump/bnb/fechar-todas", json={"real": False}, headers=tok(UA)).json()["ok"]
    for path in ("/api/pump/bnb/chave", "/api/pump/bnb/real", "/api/pump/bnb/fechar-todas"):
        assert c.post(path, json={}, headers=tok(UB, "b@x.com")).status_code == 403


def test_bnb_admin_users_and_view_screen(env):
    """0.32.173 (pedido do dono): Administração da BNB lista os usuários e o admin vê a tela da BNB de cada um, só leitura."""
    from tests.test_api import UA, UB, tok
    c, hub = env["c"], env["hub"]
    w = hub.bnb = bnb.BnbWatch(_Http([], {}), None)
    A, B = tok(UA), tok(UB, "b@x.com")
    c.get("/api/me", headers=B)                                          # cria o perfil do usuário B
    us = c.get("/api/pump/bnb/usuarios", headers=A).json()
    assert us["me"] == UA and any(x["user_id"] == UB and x["bnb"]["ficticia"] is None for x in us["users"])
    assert c.get("/api/pump/bnb/usuarios", headers=B).status_code == 403
    assert c.get("/api/pump/bnb/painel", headers=B).status_code == 403   # usuário comum não abre a BNB sozinho
    V = {**A, "X-View-As": UB}
    r = c.get("/api/pump/bnb/painel", headers=V).json()
    assert r["ligado"] and r["carteira"]["saldo"] == 1.0 and UB not in w.books   # visualizar não cria carteira para ele
    assert c.get("/api/pump/bnb/painel?real=1", headers=V).json()["real"] and UB not in w.real
    assert c.get("/api/pump/bnb", headers=V).json()["ligado"]
    assert c.post("/api/pump/bnb/conta", json={"on": False}, headers=V).status_code == 403   # só leitura
