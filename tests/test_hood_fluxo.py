"""0.32.294 (pedidos do dono e do Bruxo, 11/11/2026): Robinhood — moedas com mais dinheiro entrando, usuários na Administração, taxas
nas fechadas e na Visão geral, RPC que falha descansa, contrato-robô no ranking e venda travada pelo hook. Sem internet."""
import asyncio
import time

from app import evm, hood, hoodcopy, hoodreal, hoodsafe
from app.dormant_buy import v4_pool_id
from tests.test_api import env  # noqa: F401  (fixture env)
from tests.test_hood_copia import copier

TOK = "0x" + "ab" * 20
TOK2 = "0x" + "cd" * 20
A, B, C = "0x" + "11" * 20, "0x" + "22" * 20, "0x" + "33" * 20


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def tr(i, token, wallet, side, eth, amount=1000.0, t=None):
    return {"id": f"x{i}", "tx": "0x" + "ee" * 32, "token": token, "wallet": wallet, "side": side, "amount": amount, "eth": eth,
            "quote": "ETH", "pool": "0x" + "00" * 32, "t": t or time.time() - 10}


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


def test_token_block_buy_button_and_check_without_waiting_for_copy():
    """0.32.303 (pedido do dono): moeda bloqueada nunca é comprada; botão Comprar só com a conferência aprovada; moeda sem pool de ETH
    aparece barrada; trader PERIGO marcado na lista Dinheiro entrando."""
    w = hood.HoodWatch(None, None)
    c = w.copier
    now = time.time()
    key = [hoodcopy.ZERO, TOK, 3000, 60, hoodcopy.ZERO]
    pid = v4_pool_id(key)
    t1 = tr(1, TOK, A, "buy", 1.0, t=now - 30)
    t1["pool"] = pid
    w._add(t1)
    c.keys[pid] = key
    w.px[TOK] = (0.001, now)

    async def go():
        c.book("u1")
        v = await c.check_token(TOK2)
        assert not v["ok"] and v.get("sem_pool")
        c.safe.mark(TOK, True, "")
        r = await c.buy_token("u1", TOK, "sim")
        assert r["ficticia"] == "comprou" and r["real"] is None
        p = next(iter(c.books["u1"].pos.values()))
        assert p["wallet"] == "botao" and p["aba"] == "botao"
        r = await c.buy_token("u1", TOK, "real")
        assert "desligada" in r["real"]
        assert await c.block_token("u1", TOK, True) == [TOK]
        try:
            await c.buy_token("u1", TOK, "sim")
            assert False
        except ValueError as e:
            assert "bloqueada" in str(e)
        c.safe.mark(TOK2, False, "a VENDA é recusada pelo pool", venda_travada=True)
        try:
            await c.buy_token("u1", TOK2, "sim")
            assert False
        except ValueError as e:
            assert "barrou" in str(e)
        t2 = tr(2, TOK, B, "buy", 1.0, t=now)
        b = c.books["u1"]
        b.cfg["manual"] = [B]
        n = len(b.pos)
        c._buy_all({**t2, "_auto": False}, {"ok": True}, key, 0.001)
        assert len(b.pos) == n and "bloqueada" in b.events[0]["motivo"]
    run(go())
    w.balances[B] = {"usd": 1, "contrato": True, "t": now}
    w._danger = None
    w._add(tr(3, TOK, B, "buy", 1.0, t=now))
    w._rank_cache = (now, {"rows": [{"wallet": B}], "copiaria": []})
    f = w.flow(1, now=now)
    assert f["rows"][0]["top"][0]["perigo"]


def test_copy_config_from_other_user_only_changes_chosen_and_never_turns_real_on():
    """0.32.313 (pedido do dono): copiar a configuração de outra conta, como na Solana. Só o que foi escolhido, REAL nunca liga,
    saldo não muda, traders bloqueados ficam de fora."""
    w = hood.HoodWatch(None, None)
    c = w.copier
    assert c.share_cfg("ele") is None                      # nunca abriu o /hood
    run(c.save_book_cfg("ele", {"eth_por_compra": 0.0006, "stop_pct": 20, "saldo_inicial": 9, "manual": [A, B], "modo": {A: "real"},
                                "bloqueados": [C], "tokens_bloqueados": [TOK]}))
    run(c.save_real_cfg("ele", {"real_slip_pct": 10, "real_stop_pct": 20}))
    c.real_cfg["ele"]["real_on"] = True
    run(c.save_book_cfg("eu", {"bloqueados": [B]}))
    src = c.share_cfg("ele")
    assert "saldo_inicial" not in src["sim"] and "on" not in src["sim"] and "real_on" not in src["real"]
    r = run(c.copy_cfg("eu", "ele", ["stop_pct", "real_slip_pct"]))
    b = c.book("eu")
    assert r["ficticia"] == 1 and r["real"] == 1
    assert b.cfg["stop_pct"] == 20 and b.cfg["eth_por_compra"] == hoodcopy.CFG_DEFAULT["eth_por_compra"]   # só o escolhido
    assert c.rcfg("eu")["real_slip_pct"] == 10 and not c.rcfg("eu").get("real_on")
    assert b.cfg["saldo_inicial"] == hoodcopy.CFG_DEFAULT["saldo_inicial"]
    run(c.copy_cfg("eu", "ele", [], traders=True))
    assert b.cfg["manual"] == [A] and b.cfg["modo"].get(A) == "real"         # B está bloqueado nesta conta
    run(c.copy_cfg("eu", "ele", [], bloqueios=True))
    assert set(b.cfg["bloqueados"]) == {B, C} and b.cfg["tokens_bloqueados"] == [TOK]
    run(c.copy_cfg("eu", "ele", None))
    assert b.cfg["eth_por_compra"] == 0.0006 and c.rcfg("eu")["real_stop_pct"] == 20 and not c.rcfg("eu").get("real_on")
    for bad in ("eu", "ninguem"):
        try:
            run(c.copy_cfg("eu", bad, None))
            assert False
        except ValueError:
            pass


# ------------------------------------------------------------------ 0.32.319: histórico da configuração e voltar
def test_config_history_keeps_versions_and_goes_back_without_turning_anything_on():
    async def go():
        w, c = copier()
        rc = c.rcfg("u1")
        rc["real_on"] = False
        await c.save_book_cfg("u1", {"stop_pct": 1})
        await c.save_real_cfg("u1", {"real_stop_pct": 20})               # junta com a anterior (tela, menos de 10 min)
        h = await c.cfg_history("u1")
        assert [v["n"] for v in h["versoes"]] == [2, 1] and h["atual_n"] == 2
        assert {m["k"] for m in h["versoes"][0]["mudou"]} == {"stop_pct", "real_stop_pct"}
        await c.follow("u1", "0x" + "77" * 20, True, "sim")
        h = await c.cfg_history("u1")
        assert h["versoes"][0]["n"] == 3 and h["versoes"][0]["mudou"][0]["lista"]
        c.books["u1"].cfg["on"] = False                                   # ligar/desligar nunca entra nem volta
        r = await c.cfg_back("u1", 1)
        assert r["mudou"] >= 3
        b = c.books["u1"]
        assert b.cfg["stop_pct"] == hoodcopy.CFG_DEFAULT["stop_pct"] and b.cfg["manual"] == [] and c.rcfg("u1")["real_stop_pct"] == hoodreal.REAL_DEFAULT["real_stop_pct"]
        assert b.cfg["on"] is False and c.rcfg("u1")["real_on"] is False
        h = await c.cfg_history("u1")
        assert h["versoes"][0]["origem"] == "voltou para a versão 1" and h["atual_n"] == 4
        r = await c.cfg_back("u1", 2, ["stop_pct"])                      # só uma opção
        assert r["mudou"] == 1 and b.cfg["stop_pct"] == 1 and c.rcfg("u1")["real_stop_pct"] == hoodreal.REAL_DEFAULT["real_stop_pct"]
    run(go())


def test_config_history_routes_and_screen():
    import pathlib
    api = pathlib.Path("app/hood_api.py").read_text(encoding="utf-8")
    assert '"/api/hood/config/historico"' in api and '"/api/hood/config/voltar"' in api and "admin_only" in api
    sql = pathlib.Path("supabase/migrations/20261111000001_hood_config_versoes.sql").read_text(encoding="utf-8")
    assert "enable row level security" in sql and "revoke all on public.hood_config_versions from anon, authenticated" in sql
    js = pathlib.Path("web/hood.js").read_text(encoding="utf-8")
    assert "data-hback" in js and 'id="hiBox"' in pathlib.Path("web/hood.html").read_text(encoding="utf-8")


# ------------------------------------------------------------------ 0.32.327: o dono tirando liquidez de um pool aberto
def _ml(pid, delta, snd):
    from app import hoodsafe
    return {"topics": [hoodsafe.T_ML, pid, "0x" + "0" * 24 + snd[2:]],
            "data": "0x" + evm.w_int(0) + evm.w_int(10) + evm.w_int(delta % (1 << 256)) + evm.w_int(7)}

