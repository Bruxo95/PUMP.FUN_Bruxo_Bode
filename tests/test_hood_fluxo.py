"""0.32.294 (pedidos do dono e do Bruxo, 11/11/2026): Robinhood — moedas com mais dinheiro entrando, usuários na Administração, taxas
nas fechadas e na Visão geral, RPC que falha descansa, contrato-robô no ranking e venda travada pelo hook. Sem internet."""
import asyncio
import time

from app import evm, hood, hoodcopy, hoodreal, hoodsafe
from app.dormant_buy import v4_pool_id
from tests.test_api import env  # noqa: F401  (fixture env)

TOK = "0x" + "ab" * 20
TOK2 = "0x" + "cd" * 20
A, B, C = "0x" + "11" * 20, "0x" + "22" * 20, "0x" + "33" * 20


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def tr(i, token, wallet, side, eth, amount=1000.0, t=None):
    return {"id": f"x{i}", "tx": "0x" + "ee" * 32, "token": token, "wallet": wallet, "side": side, "amount": amount, "eth": eth,
            "quote": "ETH", "pool": "0x" + "00" * 32, "t": t or time.time() - 60}


def test_flow_ranks_tokens_by_net_money_in_and_shows_top_traders():
    w = hood.HoodWatch(None, None)
    w.eth_usd = 2000.0
    now = time.time()
    w._add(tr(1, TOK, A, "buy", 1.0, t=now - 300))
    w._add(tr(2, TOK, B, "buy", 0.5, t=now - 200))
    w._add(tr(3, TOK, A, "sell", 0.2, t=now - 100))
    w._add(tr(4, TOK2, C, "buy", 0.1, t=now - 100))
    w._add(tr(5, TOK2, C, "buy", 5.0, t=now - 7200))             # fora da janela de 1 h
    w._rank_cache = (now, {"rows": [{"wallet": A}], "copiaria": [B]})
    f = w.flow(1.0, now=now)
    assert [r["token"] for r in f["rows"]] == [TOK, TOK2]
    r = f["rows"][0]
    assert abs(r["liquido_eth"] - 1.3) < 1e-9 and r["carteiras"] == 2 and r["vendedores"] == 1 and r["liquido_usd"] == 2600.0
    assert {t["wallet"]: t["copiando"] for t in r["top"]} == {A: False, B: True}
    assert f["rows"][1]["liquido_eth"] == 0.1 and f["rows"][1]["top"] == []
    assert len(w.flow(24, now=now)["rows"]) == 2 and abs(w.flow(24, now=now)["rows"][0]["liquido_eth"] - 5.1) < 1e-9


def test_fees_are_kept_per_closed_trade_and_summed():
    b = hoodcopy.Book("u", {"eth_por_compra": 0.1, "slip_pct": 0, "gas_eth": 0.0001})
    key = [hoodcopy.ZERO, TOK, 10000, 200, hoodcopy.ZERO]
    now = time.time()
    p = b.buy(tr(1, TOK, A, "buy", 1.0), 0.001, now, key)
    open_fees = p["fees"]
    w = b.wallet(now)
    assert abs(w["taxas"] - open_fees) < 1e-12 and w["taxas_fechadas"] == 0
    t = b.sell(p, 1.0, 0.0012, now + 10, "teste")
    assert t["taxas_eth"] > open_fees and abs(b.wallet(now)["taxas_fechadas"] - t["taxas_eth"]) < 1e-9
    assert hoodcopy.periods(b.trades, now + 20)[0]["taxas"] > 0
    rb = hoodreal.RealBook("u")
    rp = {"id": "r1", "wallet": A, "token": TOK, "open_t": now, "eth_in": 0.01, "proceeds": 0.012, "fees": 0.00001, "fee": 0.01}
    rb.pos["r1"] = rp
    rt = rb.close(rp, now + 5, "teste", None)
    assert rt["taxas_eth"] > 0.00001 + 0.0001 and abs(rb.wallet(now, 15, hoodcopy.periods)["taxas_fechadas"] - rt["taxas_eth"]) < 1e-6


def test_user_summary_does_not_create_a_book():
    w = hood.HoodWatch(None, None)
    c = w.copier
    assert c.user_summary("ninguem")["ficticia"] is None and "ninguem" not in c.books
    c.book("u1")
    s = c.user_summary("u1")
    assert s["ficticia"]["ligada"] is True and s["real"]["ligada"] is False and s["real"]["chave"] is False


def test_failing_rpc_rests_and_contract_refusal_is_not_an_rpc_failure():
    class R:
        def __init__(self, code, js):
            self.status_code, self._js = code, js

        def json(self):
            return self._js

    class H:
        def __init__(self):
            self.calls = []

        async def post(self, url, json=None, **kw):
            self.calls.append(url)
            if "a.rpc" in url:
                raise TimeoutError("demorou")
            if json["method"] == "eth_call":
                return R(200, {"error": {"message": "execution reverted"}})
            return R(200, {"result": "0x10"})

    async def go():
        h = H()
        w = hood.HoodWatch(h, None, ["https://a.rpc", "https://b.rpc"])
        await w.rpc("eth_blockNumber", [], "https://a.rpc")
        assert w._rpc_off.get("https://a.rpc", 0) <= time.time()          # 1 falha: ainda não descansa
        await w.rpc("eth_blockNumber", [], "https://a.rpc")
        assert w._rpc_off["https://a.rpc"] > time.time() and w.stat["pausas"] == 1
        h.calls.clear()
        try:
            await w.rpc("eth_call", [{"to": TOK, "data": "0x"}, "latest"], "https://b.rpc")
            assert False
        except hood.RpcError as e:
            assert "reverted" in str(e)
        assert h.calls == ["https://b.rpc"] and w._rpc_off.get("https://b.rpc", 0) <= time.time()   # recusa do contrato: não pergunta a outro
    run(go())


def test_contract_wallets_are_flagged_in_the_ranking():
    now = time.time()
    trades = [tr(i, TOK, A, "buy" if i % 2 else "sell", 1.0, t=now - 3000 + i) for i in range(40)]
    rk = hood.rank(trades, now, {"min_trades": 1, "min_closed": 1, "min_wallet_usd": 0}, {A: {"usd": 5000, "contrato": True}})
    r = rk["rows"][0]
    assert r["contrato"] and any("contrato" in f for f in r["flags"]) and not r["eligible"]


def test_sell_blocked_by_hook_is_explained():
    hook = "0x" + "1d" * 20
    key = [hoodcopy.ZERO, TOK, 1, 1, hook]

    async def call(to, data, frm=None):
        if data.startswith(evm.selector("decimals()")):
            return "0x" + evm.w_int(18)
        if to == hoodsafe.QUOTER:
            w = evm.words("0x" + data[10:])
            if w[6] == 1:
                return "0x" + evm.w_int(10 ** 20) + evm.w_int(0)
            raise RuntimeError("execution reverted")
        raise AssertionError

    class Http:
        async def get(self, url, **kw):
            class X:
                def json(self):
                    return {"result": {}}
            return X()

    s = hoodsafe.Safety(call, Http())
    v = run(s.check(TOK, key, None))
    assert not v["ok"] and "VENDA" in v["why"] and "contrato extra" in v["why"] and v["venda_travada"]
    assert v4_pool_id(key)


def test_flow_and_users_routes_are_admin_only(env):  # noqa: F811
    from tests.test_api import UA, UB, tok
    c, hub = env["c"], env["hub"]
    hub.hood = hood.HoodWatch(None, None)

    async def nada(tokens):
        return None
    hub.hood.fill_names = nada
    assert c.get("/api/hood/fluxo", headers=tok(UB, "b@x.com")).status_code == 403
    assert c.get("/api/hood/usuarios", headers=tok(UB, "b@x.com")).status_code == 403
    r = c.get("/api/hood/fluxo?h=6", headers=tok(UA)).json()
    assert r["horas"] == 6 and r["rows"] == []
    us = c.get("/api/hood/usuarios", headers=tok(UA)).json()["users"]
    assert us and all("hood" in u for u in us)


def test_danger_traders_are_tagged_blocked_from_copy_and_never_buy_in_real():
    """0.32.295 (pedido do dono): trader PERIGO (contrato-robô ou comprou token que não deixa vender) não entra no Copiando agora,
    o botão Copiar é recusado e a REAL não compra dele mesmo se já estava sendo copiado."""
    w = hood.HoodWatch(None, None)
    now = time.time()
    w._add(tr(1, TOK, A, "buy", 1.0, t=now - 100))
    w._add(tr(2, TOK2, B, "buy", 1.0, t=now - 100))
    w.copier.safe.mark(TOK, False, "a VENDA é recusada pelo pool", venda_travada=True)
    w.balances[B] = {"usd": 5000, "contrato": True, "t": now}
    dz = w.danger(now)
    assert "honeypot" in dz[A][0] and "contrato" in dz[B][0]
    rows = {r["wallet"]: r for r in w.ranking(now)["rows"]}
    assert rows[A]["perigo"] and not rows[A]["eligible"] and not rows[A]["copiaria"]

    async def go():
        c = w.copier
        c.book("u1")
        try:
            await c.follow("u1", A, True, "real")
            assert False
        except ValueError as e:
            assert "PERIGO" in str(e)
        assert await c.follow("u1", A, False) == []                     # parar continua funcionando
        c.books["u1"].cfg["manual"] = [B]
        c.rcfg("u1")["real_on"] = True
        chamou = []

        async def real_buy(*a):
            chamou.append(a)
        c._real_buy = real_buy
        t = tr(9, TOK2, B, "buy", 1.0)
        t["_auto"] = False
        c._buy_all(t, {"ok": True}, [hoodcopy.ZERO, TOK2, 3000, 60, hoodcopy.ZERO], 0.001)
        await asyncio.sleep(0)
        assert not chamou and c.real["u1"].events[0]["acao"] == "REAL não copiou" and "PERIGO" in c.real["u1"].events[0]["motivo"]
    run(go())


def test_block_button_stops_copying_and_danger_is_never_copied():
    """0.32.302 (pedido do dono): Bloquear tira da lista e nunca copia; PERIGO não é copiado nem na FICTÍCIA."""
    w = hood.HoodWatch(None, None)

    async def go():
        c = w.copier
        c.book("u1")
        await c.follow("u1", A, True, "ambas")
        assert await c.block("u1", A, True) == [A]
        b = c.books["u1"]
        assert A not in b.cfg["manual"] and b.mode_of(A, True) is None
        try:
            await c.follow("u1", A, True, "sim")
            assert False
        except ValueError as e:
            assert "bloqueado" in str(e)
        assert await c.block("u1", A, False) == [] and b.mode_of(A, True) == "ambas"
        w.balances[B] = {"usd": 1, "contrato": True, "t": time.time()}
        w._danger = None
        c.on_trade(tr(7, TOK, B, "buy", 1.0, t=time.time()), 0.0, [B])
        assert c.stat.get("perigo_ignorados") == 1 and c.stat["compras_vistas"] == 0
    run(go())
