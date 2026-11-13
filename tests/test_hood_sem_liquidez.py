"""0.32.315 (casos TEXEL e mihao do dono, 11/11/2026): o criador tirou toda a liquidez do pool V4 (TEXEL às 13:00:30, 5 s depois da
compra REAL; mihao às 14:01:22, 2 min depois do botão). A fictícia tinha "fechado" no cálculo e a REAL ficou presa com a venda
recusada (o Quoter devolve NotEnoughLiquidity). Sem internet: a rede é falsa."""
import asyncio
import time

from app import evm, hoodcopy, hoodreal
from app.dormant_buy import v4_pool_id
from tests.test_hood_copia import KEY, TOK, TRADER, Http, Watch, copier, run, settle, trade


def _real_pos(c, sim_id=None, **kw):
    rb = c.rbook("u1")
    p = {"id": "r1", "wallet": TRADER, "token": TOK, "sim_id": sim_id, "open_t": time.time() - 600, "eth_in": 0.002, "proceeds": 0.0,
         "px_in": 0.001, "px_now": 0.0009, "tokens": 2.0, "tokens_left": 2.0, "raw_left": str(2 * 10 ** 18), "fee": 0.0001,
         "fees": 0.00001, "best_pct": 0.0, "worst_pct": -10.0, "key": KEY, **kw}
    rb.pos[p["id"]] = p
    return rb, p


def test_liquidity_slot_is_read_from_the_pool_manager():
    """slot 3 do Pool.State: keccak(id do pool, 6) + 3 (conferido na rede em 11/11: TEXEL e mihao com liquidez 0)."""
    seen = []

    async def rpc(m, p):
        seen.append(p[0])
        return "0x" + evm.w_int((5 << 128) | 0)                 # 128 bits de cima são outro campo: liquidez = 0
    ch = hoodreal.Chain(rpc)
    assert run(ch.liquidity(KEY)) == 0
    base = int.from_bytes(evm.keccak256(bytes.fromhex(v4_pool_id(KEY)[2:]) + (6).to_bytes(32, "big")), "big")
    assert seen[0]["to"] == hoodreal.PM and seen[0]["data"] == hoodreal.SEL_EXTSLOAD + evm.w_int(base + 3)


def test_sell_quote_reports_no_liquidity_when_the_pool_is_empty():
    async def go(liq):
        async def rpc(m, p):
            return "0x" + evm.w_int(liq)
        ch = hoodreal.Chain(rpc)

        async def quote(key, amount, buy):
            raise hoodreal.ChainError("simulação recusada: execution reverted")
        ch.quote = quote
        try:
            await ch.sell_quote(KEY, 8000)
        except hoodreal.SellBlocked as e:
            return e
    e = run(go(0))
    assert isinstance(e, hoodreal.NoLiquidity) and "tirou toda a liquidez" in str(e)
    e = run(go(10 ** 20))
    assert not isinstance(e, hoodreal.NoLiquidity) and "recusou cotar a venda" in str(e)


def test_no_liquidity_writes_off_the_fictitious_and_keeps_the_real_at_zero():
    async def go():
        w, c = copier()
        c.on_trade(trade("buy", 1000.0, 1.0), 0.0, w.copiaria)
        await settle(c)
        b = c.books["u1"]
        assert len(b.pos) == 1
        rb, rp = _real_pos(c)
        c.mark_no_liq(TOK, "TEXEL")
        assert not b.pos and b.trades[0]["px_out"] == 0.0 and b.trades[0]["pnl_pct"] < -95     # o que de verdade aconteceria
        assert "liquidez" in b.trades[0]["motivo"]
        assert rp["id"] in rb.pos and rp["px_now"] == 0.0 and rb.value_now(rp, 15) == 0.0
        assert rp["sell_retry_at"] > time.time() + 500                                        # não fica tentando a cada minuto
        assert c.no_sell_why(TOK, "TEXEL")                                                     # e não compra de novo
        pos = c.painel("u1", real=True)["posicoes"][0]
        assert pos["sem_liquidez"] and pos["pnl_pct"] < -95
        sold = []

        async def chain_sell(*a, **k):
            sold.append(1)
        c.chain.sell = chain_sell
        assert await c._real_sell("u1", rp, 1.0, "stop") is None and not sold                  # espera a próxima conferência
    run(go())


def test_manual_sell_with_no_liquidity_writes_off_the_real():
    async def go():
        w, c = copier()
        rb, rp = _real_pos(c)

        async def get_key(uid):
            return 1, "0x" + "33" * 20
        c.get_key = get_key

        async def chain_sell(*a, **k):
            raise hoodreal.NoLiquidity("o criador tirou toda a liquidez do pool")
        c.chain.sell = chain_sell
        tr = await c.close_real("u1", "r1")
        assert tr and tr["eth_out"] == 0.0 and tr["pnl_eth"] == -0.002 and "baixa" in tr["motivo"]
        assert not rb.pos and TOK in c.no_liq
    run(go())


def test_real_does_not_buy_when_the_fictitious_already_closed():
    """Caso TEXEL: a fictícia fechou às 13:00:01 e a REAL comprou às 13:00:25. Com o espelho a REAL desiste."""
    async def go():
        w, c = copier()
        c.real_allowed = True
        rc = c.rcfg("u1")
        rc["real_on"] = True
        c.safe.mark(TOK, True, "")

        async def get_key(uid):
            return 1, "0x" + "33" * 20
        c.get_key = get_key
        bought = []

        async def chain_buy(*a, **k):
            bought.append(1)
        c.chain.buy = chain_buy
        rb = c.rbook("u1")
        rb.balance, rb.balance_t = 1.0, time.time()
        await c._real_buy("u1", {**trade("buy", 1000.0, 1.0), "_sim_id": "ja-fechou"}, 0.001, KEY)
        assert not bought and not rb.pos
        assert rb.events[0]["acao"] == "REAL não copiou" and "fictícia já fechou" in rb.events[0]["motivo"]
    run(go())


def test_closing_time_never_comes_before_the_opening():
    """A fictícia mostrava "ficou -15 s": o preço do stop vinha de um trade lido com atraso, de antes da compra."""
    b = hoodcopy.Book("u1")
    p = b.buy(trade("buy", 1000.0, 1.0), 0.001, time.time(), KEY)
    tr = b.sell(p, 1.0, 0.0009, p["open_t"] - 30, "stop de 1%")
    assert tr["close_t"] >= tr["open_t"]


def test_price_tick_marks_no_liquidity_when_the_quoter_refuses():
    async def go():
        w, c = copier()
        rb, rp = _real_pos(c)

        async def call(to, data, frm=None):
            raise RuntimeError("execution reverted")
        c._call = call

        async def liquidity(key):
            return 0
        c.chain.liquidity = liquidity
        await c.price_tick(time.time())
        assert TOK in c.no_liq and rp["px_now"] == 0.0
    run(go())


def test_stop_below_the_round_trip_cost_is_warned_on_screen():
    js = open("web/hood.js", encoding="utf-8").read()
    assert "function stopWarn" in js and "custo de entrar e sair" in js
    assert asyncio  # noqa
    assert Http and Watch


# ------------------------------------------------------------------ 0.32.316: liquidez solta (carteira comum pode tirar)
def _lp_safety(owner_code):
    from app import hoodsafe
    pid = v4_pool_id(KEY)
    dono = "0x" + "44" * 20

    def log(delta, salt=7, snd=hoodsafe.POSM):
        return {"topics": [hoodsafe.T_ML, pid, "0x" + "0" * 24 + snd[2:]],
                "data": "0x" + evm.w_int(0) + evm.w_int(10) + evm.w_int(delta % (1 << 256)) + evm.w_int(salt)}

    async def rpc(m, p):
        if m == "eth_blockNumber":
            return hex(10_000_000)
        if m == "eth_getLogs":
            return [log(1000), log(300, salt=8, snd="0x" + "55" * 20)]      # 1000 do NFT 7 (carteira) + 300 de uma lançadora
        if m == "eth_getCode":
            return owner_code
        raise AssertionError(m)

    async def call(to, data, frm=None):
        assert to == hoodsafe.POSM and data == hoodsafe.SEL_OWNER + evm.w_int(7)
        return "0x" + evm.w_addr(dono)
    s = hoodsafe.Safety(call, None)
    s.rpc = rpc
    return s


def test_liquidity_owned_by_a_plain_wallet_is_flagged():
    r = run(_lp_safety("0x").lp_control(KEY))
    assert r["pct_carteira"] == 76.9 and "pode tirar tudo" in r["livre"]
    r = run(_lp_safety("0x6080604052").lp_control(KEY))          # dono é contrato (trava de liquidez)
    assert r["pct_carteira"] == 0.0 and r["livre"] is None


def test_loose_liquidity_blocks_fictitious_and_real_unless_the_option_is_off():
    async def go():
        w, c = copier()
        c.safe.mark(TOK, True, "", lp_livre="100% da liquidez é de uma carteira comum")
        c._buy_all(trade("buy", 1000.0, 1.0), c.safe.cached(TOK), KEY, 0.001)
        b = c.books["u1"]
        assert not b.pos and "liquidez solta" in b.events[0]["motivo"]
        b.cfg["so_lp_presa"] = False
        c._buy_all(trade("buy", 1000.0, 1.0), c.safe.cached(TOK), KEY, 0.001)
        assert len(b.pos) == 1
        c.real_allowed = True
        c.rcfg("u1")["real_on"] = True

        async def get_key(uid):
            return 1, "0x" + "33" * 20
        c.get_key = get_key
        rb = c.rbook("u1")
        await c._real_buy("u1", {**trade("buy", 1000.0, 1.0), "wallet": "0x" + "66" * 20}, 0.001, KEY)
        assert "liquidez solta" in rb.events[0]["motivo"]
    run(go())


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


def test_owner_pulling_liquidity_closes_open_positions():
    from app import hoodsafe
    async def go():
        w, c = copier()
        c.on_trade(trade("buy", 1000.0, 1.0), 0.0, w.copiaria)
        await settle(c)
        b = c.books["u1"]
        assert len(b.pos) == 1

        async def liquidity(key):
            return 600                                      # sobrou 600 de 1000: saiu 40%
        c.chain.liquidity = liquidity
        c.note_liq([_ml(v4_pool_id(KEY), -400, hoodsafe.POSM)])
        await settle(c)
        assert not b.pos and "tirou 40% da liquidez" in b.trades[0]["motivo"]
    run(go())


def test_small_pull_or_option_off_keeps_the_position():
    from app import hoodsafe
    async def go():
        w, c = copier()
        c.on_trade(trade("buy", 1000.0, 1.0), 0.0, w.copiaria)
        await settle(c)
        b = c.books["u1"]

        async def liquidity(key):
            return 900
        c.chain.liquidity = liquidity
        c.note_liq([_ml(v4_pool_id(KEY), -100, hoodsafe.POSM)])     # 10%: fica
        await settle(c)
        assert len(b.pos) == 1
        b.cfg["sair_liquidez"] = False
        c._liq_seen.clear()
        c.note_liq([_ml(v4_pool_id(KEY), -900, hoodsafe.POSM)])
        await settle(c)
        assert len(b.pos) == 1
    run(go())


def test_launchpad_contract_that_pulled_liquidity_counts_as_loose():
    from app import hoodsafe
    w, c = copier()
    pad = "0x" + "0a" * 20
    c.note_liq([_ml("0x" + "12" * 32, -5, pad), _ml("0x" + "13" * 32, -5, pad)])
    assert c.lp_pullers[pad] == 2 and c.safe.pullers is c.lp_pullers
    pid = v4_pool_id(KEY)

    async def rpc(m, p):
        if m == "eth_blockNumber":
            return hex(10_000_000)
        if m == "eth_getLogs":
            return [{"topics": [hoodsafe.T_ML, pid, "0x" + "0" * 24 + pad[2:]],
                     "data": "0x" + evm.w_int(0) + evm.w_int(10) + evm.w_int(1000) + evm.w_int(1)}]
        raise AssertionError(m)
    c.safe.rpc = rpc
    r = run(c.safe.lp_control(KEY))
    assert r["pct_carteira"] == 100.0 and r["livre"]
