"""0.32.279 (pedido do dono, 10/11/2026: "faz 1 a 4"): Robinhood Chain, cópia fictícia em ETH, conferência do token, preço das
posições e carteira REAL (desligada). Sem internet: a rede, a GoPlus e o envio são falsos."""
import asyncio
import time

from app import evm, hood, hoodcopy, hoodreal, hoodsafe
from app.dormant_buy import SEL_UR_EXEC, v4_pool_id
from tests.test_api import env  # noqa: F401  (fixture env)

TOK = "0x" + "ab" * 20
TRADER = "0x" + "11" * 20
OTHER = "0x" + "22" * 20
KEY = [hoodcopy.ZERO, TOK, 10000, 200, hoodcopy.ZERO]          # pool ETH / token, taxa de 1%
PID = v4_pool_id(KEY)
SEL_DEC = evm.selector("decimals()")
SEL_TRANSFER = evm.selector("transfer(address,uint256)")


class Resp:
    def __init__(self, js):
        self._js = js

    def json(self):
        return self._js


class Http:
    def __init__(self, goplus=None):
        self.goplus = goplus or {}

    async def get(self, url, **kw):
        if "gopluslabs" in url:
            return Resp({"result": self.goplus})
        return Resp({})


class Watch:
    """O mínimo da HoodWatch que a cópia usa."""

    def __init__(self, loss=0.03, honeypot=False, decimals=18):
        self.px, self.head, self.head_t, self.block_s = {}, 1000, time.time(), 0.1
        self.loss, self.honeypot, self.decimals = loss, honeypot, decimals
        self.copiaria = [TRADER]

    def ranking(self, now=None):
        return {"copiaria": self.copiaria}

    async def rpc(self, method, params):
        if method != "eth_call":
            raise AssertionError("sem rede neste teste: " + method)
        p = params[0]
        data = p["data"]
        if data.startswith(SEL_DEC):
            return "0x" + evm.w_int(self.decimals)
        if data.startswith(SEL_TRANSFER):
            if self.honeypot:
                raise RuntimeError("execution reverted")
            return "0x" + evm.w_int(1)
        if p["to"] == hoodsafe.QUOTER:
            w = evm.words("0x" + data[10:])
            amount, buy = w[7], w[6] == 1               # PoolKey (5), zeroForOne, amount
            if buy:
                return "0x" + evm.w_int(amount * 1000) + evm.w_int(0)        # 1 ETH = 1000 tokens
            return "0x" + evm.w_int(int(amount / 1000 * (1 - self.loss))) + evm.w_int(0)
        raise AssertionError("eth_call inesperado")


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


async def settle(c):
    for _ in range(5):
        if c._tasks:
            await asyncio.gather(*list(c._tasks))
        await asyncio.sleep(0)


def trade(side, amount, eth, t=None, wallet=TRADER):
    return {"id": f"{side}{amount}{eth}", "tx": "0x" + "ee" * 32, "token": TOK, "wallet": wallet, "side": side, "amount": amount,
            "eth": eth, "quote": "ETH", "pool": PID, "t": t or time.time(), "fee": 10000}


def copier(**kw):
    w = Watch(**kw)
    c = hoodcopy.Copier(w, Http())
    c.keys[PID] = KEY
    c.book("u1")
    return w, c


def test_copies_the_buy_and_sells_the_same_fraction():
    async def go():
        w, c = copier()
        c.on_trade(trade("buy", 1000.0, 1.0), 0.0, w.copiaria)
        await settle(c)
        b = c.books["u1"]
        assert len(b.pos) == 1
        p = next(iter(b.pos.values()))
        assert p["key"] == KEY and abs(p["fee"] - 0.01) < 1e-12 and p["eth_in"] > 0
        c.on_trade(trade("sell", 500.0, 0.6), 1000.0, w.copiaria)          # vendeu metade
        assert len(b.pos) == 1 and len(p["vendas"]) == 1 and abs(p["tokens_left"] - p["tokens"] / 2) < 1e-9
        c.on_trade(trade("sell", 500.0, 0.7), 500.0, w.copiaria)           # vendeu o resto
        assert not b.pos and len(b.trades) == 1 and b.trades[0]["pnl_eth"] > 0
        assert c.stat["copiadas"] == 1
    run(go())


def test_old_buys_and_traders_outside_the_list_are_not_copied():
    async def go():
        w, c = copier()
        c.on_trade(trade("buy", 1000.0, 1.0, t=time.time() - 600), 0.0, w.copiaria)     # releitura depois de reiniciar
        c.on_trade(trade("buy", 1000.0, 1.0, wallet=OTHER), 0.0, w.copiaria)           # não está no "Copiaria agora"
        await settle(c)
        assert not c.books["u1"].pos and c.stat["compras_vistas"] == 0
    run(go())


def test_honeypot_roundtrip_loss_and_odd_decimals_are_barred():
    async def go():
        for kw, palavra in (({"honeypot": True}, "honeypot"), ({"loss": 0.30}, "ida e volta"), ({"decimals": 9}, "casas")):
            w, c = copier(**kw)
            c.on_trade(trade("buy", 1000.0, 1.0), 0.0, w.copiaria)
            await settle(c)
            b = c.books["u1"]
            assert not b.pos, kw
            assert palavra in b.events[0]["motivo"], (kw, b.events[0])
    run(go())


def test_goplus_honeypot_blocks_even_when_the_pool_quotes():
    async def go():
        w = Watch()
        c = hoodcopy.Copier(w, Http({TOK: {"is_honeypot": "1"}}))
        c.keys[PID] = KEY
        c.book("u1")
        c.on_trade(trade("buy", 1000.0, 1.0), 0.0, w.copiaria)
        await settle(c)
        assert not c.books["u1"].pos and "GoPlus" in c.books["u1"].events[0]["motivo"]
    run(go())


def test_pool_not_paid_in_eth_is_not_copied():
    async def go():
        w, c = copier()
        c.keys[PID] = None                                     # pool WETH/USDG: a leitura não guarda chave
        c._key_at[PID] = time.time()
        c.on_trade(trade("buy", 1000.0, 1.0), 0.0, w.copiaria)
        await settle(c)
        assert not c.books["u1"].pos and c.stat["sem_pool"] == 1
    run(go())


def test_initialize_logs_keep_only_eth_pools():
    w, c = Watch(), None
    c = hoodcopy.Copier(w, Http())
    def init(key):
        data = "0x" + evm.w_int(key[2]) + evm.w_int(key[3]) + evm.w_addr(key[4]) + evm.w_int(1) + evm.w_int(0)
        return {"topics": [hood.T_INIT, v4_pool_id(key), "0x" + evm.w_addr(key[0]), "0x" + evm.w_addr(key[1])], "data": data}
    weth = [hood.WETH, TOK, 3000, 60, hoodcopy.ZERO]
    c.note_init([init(KEY), init(weth)])
    assert c.keys[PID] == KEY and v4_pool_id(weth) not in c.keys
    assert hood.T_INIT == "0x" + evm.keccak256(b"Initialize(bytes32,address,address,uint24,int24,address,uint160,int24)").hex()


def test_stop_and_max_time_close_the_fictitious_position():
    b = hoodcopy.Book("u", {"stop_pct": 30, "max_hold_h": 1})
    now = time.time()
    p = b.buy(trade("buy", 1000.0, 1.0), 0.001, now, KEY)
    b.on_price(TOK, 0.0006, now + 10)                           # −40%
    assert not b.pos and "stop" in b.trades[0]["motivo"]
    p = b.buy(trade("buy", 1000.0, 1.0), 0.001, now, KEY)
    assert p and not b.timeouts(now + 1800) and b.timeouts(now + 3700)
    assert "tempo máximo" in b.trades[0]["motivo"]


def test_swap_fee_is_read_from_the_event():
    tr = hood.decode({"transactionHash": "0xa", "logIndex": "0x1", "blockNumber": "0x10", "address": hood.PM,
                      "topics": [hood.T_SWAP, PID, "0x" + "0" * 24 + "99" * 20],
                      "data": "0x" + format((-10**17) % (1 << 256), "064x") + format(5 * 10**21, "064x") + "0" * 64 * 3 + format(10000, "064x")},
                     [(TOK, hood.PM, TRADER, 5 * 10**21)], 1, 3000.0)
    assert tr["fee"] == 10000 and tr["pool"] == PID


def test_real_starts_off_and_needs_the_general_lock_and_the_key():
    async def go():
        w, c = copier()
        assert hoodreal.REAL_DEFAULT["real_on"] is False and c.rcfg("u1")["real_on"] is False
        c.on_trade(trade("buy", 1000.0, 1.0), 0.0, w.copiaria)
        await settle(c)
        assert not c.real.get("u1") or not c.real["u1"].pos             # REAL desligada: nada
        try:
            await c.set_real("u1", True)
            assert False, "ligou sem a trava geral"
        except ValueError as e:
            assert "PUMP_REAL_ALLOWED" in str(e)
        c.real_allowed = True
        try:
            await c.set_real("u1", True)
            assert False, "ligou sem chave"
        except ValueError as e:
            assert "chave" in str(e)
        assert hoodreal.clean({"real_on": True})["real_on"] is False          # ligar só pela rota com LIGAR
        assert hoodreal.clean({"real_eth_por_compra": 99})["real_eth_por_compra"] == 0.5
    run(go())


def test_real_buy_and_sell_go_only_to_the_official_router_with_exact_approvals():
    async def go():
        w, c = copier()
        c.real_allowed = True
        addr = "0x" + "33" * 20
        sent = []
        allow = {"tok": 0, "p2": (0, 0)}

        async def send(key, frm, to, data, value):
            sent.append((to, data[:10], value, data))
            logs = []
            if to == hoodreal.UR and value:
                logs = [{"address": TOK, "topics": [hoodreal.T_TRANSFER, "0x" + evm.w_addr(hoodreal.PM), "0x" + evm.w_addr(addr)],
                         "data": "0x" + evm.w_int(2 * 10**18)}]
            if to == TOK:
                allow["tok"] = evm.words("0x" + data[10:])[1]
            if to == hoodreal.PERMIT2:
                ww = evm.words("0x" + data[10:])
                allow["p2"] = (ww[2], ww[3])
            if to == hoodreal.UR and not value:
                logs = [{"address": hoodreal.PM, "topics": [hoodreal.T_V4_SWAP, PID, "0x" + evm.w_addr(hoodreal.UR)],
                         "data": "0x" + evm.w_int(10**15) + evm.w_int((-10**18) % (1 << 256)) + evm.w_int(0) * 4}]
            return {"transactionHash": "0x" + "aa" * 32, "logs": logs, "_gas_eth": 0.00001}

        async def call(to, data, frm=None):
            if data.startswith(hoodreal.SEL_BALANCE):
                return "0x" + evm.w_int(2 * 10**18)
            if data.startswith(hoodreal.SEL_ALLOW):
                return "0x" + evm.w_int(allow["tok"])
            if data.startswith(hoodreal.SEL_P2_ALLOW):
                return "0x" + evm.w_int(allow["p2"][0]) + evm.w_int(allow["p2"][1]) + evm.w_int(0)
            if to == hoodreal.QUOTER:
                return "0x" + evm.w_int(10**18) + evm.w_int(0)
            raise AssertionError("call inesperado")

        c.chain.send, c.chain.call = send, call
        res = await c.chain.buy(1, addr, TOK, KEY, 0.002, 15, time.time() + 3600)
        assert res["raw"] == 2 * 10**18
        assert sent[0][0] == hoodreal.UR and sent[0][1] == SEL_UR_EXEC and sent[0][2] == int(0.002 * 1e18)
        assert sent[1][0] == TOK and evm.words("0x" + sent[1][3][10:]) == [int(hoodreal.PERMIT2, 16), 2 * 10**18]   # só o comprado
        assert sent[2][0] == hoodreal.PERMIT2 and len(sent) == 3
        sent.clear()
        r = await c.chain.sell(1, addr, TOK, KEY, 10**18, 15)
        assert [x[0] for x in sent] == [hoodreal.UR] and sent[0][2] == 0                 # autorização já pronta: uma transação só
        assert abs(r["eth"] - (0.001 - 0.00001)) < 1e-12
        try:
            await c.chain.buy(1, addr, TOK, [hood.WETH, TOK, 3000, 60, hoodcopy.ZERO], 0.002, 15, 0)
            assert False
        except hoodreal.ChainError as e:
            assert "nada foi enviado" in str(e)
    run(go())


def test_isolated_key_name_tables_and_migration():
    from app.keystore import BNB_SECRET_NAMES, SECRET_NAMES
    assert hoodcopy.HOOD_KEY_NAME in BNB_SECRET_NAMES and hoodcopy.HOOD_KEY_NAME not in SECRET_NAMES   # fora das Chaves pessoais da Solana
    sql = open("supabase/migrations/20261110000001_robinhood_copia.sql", encoding="utf-8").read()
    for name in ("hood_books", "hood_positions", "hood_trades", "'hood_private_key'", "'bnb_private_key'", "enable row level security"):
        assert name in sql, name
    js = open("web/hood.js", encoding="utf-8").read()
    for rota in ("/api/hood/painel", "/api/hood/real", "/api/hood/chave", "LIGAR"):
        assert rota in js or rota in open("web/hood.html", encoding="utf-8").read(), rota


def test_copy_routes_are_admin_only_and_real_needs_ligar(env):  # noqa: F811
    from tests.test_api import UA, UB, tok
    c, hub = env["c"], env["hub"]
    hub.hood = hood.HoodWatch(None, None)
    hub.hood.copier.vault = hub.vault
    assert c.get("/api/hood/painel", headers=tok(UB, "b@x.com")).status_code == 403
    assert c.post("/api/hood/real", json={"on": True, "confirm": "LIGAR"}, headers=tok(UB, "b@x.com")).status_code == 403
    p = c.get("/api/hood/painel", headers=tok(UA)).json()
    assert p["ligado"] and p["real"] is False and p["real_status"]["ligada"] is False and p["cfg_sim"]["on"] is True
    assert "LIGAR" in c.post("/api/hood/real", json={"on": True}, headers=tok(UA)).json()["error"]
    assert "PUMP_REAL_ALLOWED" in c.post("/api/hood/real", json={"on": True, "confirm": "LIGAR"}, headers=tok(UA)).json()["error"]
    r = c.post("/api/hood/conta", json={"eth_por_compra": 0.02, "on": False}, headers=tok(UA)).json()
    assert r["cfg"]["eth_por_compra"] == 0.02 and r["cfg"]["on"] is False
    assert c.get("/api/hood/painel?real=1", headers=tok(UA)).json()["real"] is True
    assert "VENDER" in c.post("/api/hood/fechar-todas", json={"real": True}, headers=tok(UA)).json()["error"]


def test_dynamic_fee_pool_does_not_invent_profit():
    """Caso PONS (10/11/2026): pool V4 de taxa dinâmica (fee = 0x800000) virou +543.649% de mentira."""
    dyn = [hoodcopy.ZERO, TOK, 0x800000, 200, "0x" + "44" * 20]
    assert hoodcopy.pool_fee(dyn, 10130) == 0.01013 and hoodcopy.pool_fee(dyn) == 0.01 and hoodcopy.pool_fee(KEY) == 0.01
    b = hoodcopy.Book("u", {"eth_por_compra": 0.1, "slip_pct": 2})
    now = time.time()
    t = trade("buy", 1000.0, 1.0)
    t["fee"] = 10130
    p = b.buy(t, 0.001, now, dyn)
    assert p["tokens"] > 0 and abs(p["fee"] - 0.01013) < 1e-9
    b.on_price(TOK, 0.001, now + 5)
    assert -6 < b.pnl_now(p)[1] < 0                      # mesmo preço: só taxa e folga
    bad = dict(p, fee=8.388608, tokens=-700.0, tokens_left=-700.0, best_pct=543649.4)
    assert hoodcopy.repair(bad) and bad["tokens"] > 0 and bad["best_pct"] == 0 and bad["fee"] == 0.01
    assert not hoodcopy.repair(p)
