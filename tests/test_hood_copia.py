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


def test_ranking_trades_go_to_the_vps_archive_and_come_back_on_restart():
    """0.32.282 (pedido do dono): o ranking da Robinhood não zera mais quando o site atualiza."""
    class Rest:
        def __init__(self):
            self.deleted = []

        async def _req(self, method, table, params, body, prefer):
            self.deleted.append(params)

    class Arq:
        def __init__(self):
            self.rows, self.rest = [], Rest()

        async def put(self, spec, rows):
            assert spec["tabela"] == "hood_rede"
            self.rows += rows
            return [r["id"] for r in rows]

        async def pages(self, tabela, since=None, until=None, page=5000):
            yield [r for r in self.rows if r["t"] >= since]

    async def go():
        arq = Arq()
        w = hood.HoodWatch(None, None)
        w.arquivo = arq
        now = time.time()
        for i, tr in enumerate([trade("buy", 1000.0, 1.0, t=now - 600), trade("sell", 1000.0, 1.3, t=now - 300)]):
            tr["id"] = f"x{i}"
            w._add(tr)
            w._arq_pend.append({k: tr.get(k) for k in hood.ARQ_FIELDS})
        await w.save_arquivo()
        assert len(arq.rows) == 2 and not w._arq_pend and w.stat["salvos"] == 2 and arq.rest.deleted   # limpeza dos 2 dias
        w2 = hood.HoodWatch(None, None)                                   # "reiniciou"
        w2.arquivo = arq
        w2.db = None
        await w2.load()
        assert len(w2.trades) == 2 and w2.stat["do_arquivo"] == 2 and w2.hold[(TRADER, TOK)] == 0.0
        assert w2.ranking()["rows"][0]["realized_eth"] > 0
    run(go())


def test_rpc_rotation_rests_only_the_rpc_that_asked_to_wait():
    """0.32.283 (dono: leitura 231 s atrasada): revezamento entre RPC grátis; o 429 pausa só aquele RPC."""
    class R:
        def __init__(self, code, js=None):
            self.status_code, self._js = code, js or {"result": "0x10"}

        def json(self):
            return self._js

    class H:
        def __init__(self):
            self.calls = []

        async def post(self, url, json=None, **kw):
            self.calls.append(url)
            return R(429) if "a.rpc" in url else R(200)

    async def go():
        h = H()
        w = hood.HoodWatch(h, None, ["https://a.rpc", "https://b.rpc", "https://c.rpc"])
        assert await w.rpc("eth_blockNumber", []) == "0x10"
        assert h.calls == ["https://a.rpc", "https://b.rpc"] and w._rpc_off["https://a.rpc"] > time.time()
        assert w._pause_until == 0.0                                   # os outros seguem lendo
        h.calls.clear()
        for _ in range(4):
            await w.rpc("eth_blockNumber", [])
        assert "https://a.rpc" not in h.calls and {"https://b.rpc", "https://c.rpc"} <= set(h.calls)
        assert w.official == hood.OFFICIAL and len(hood.RPCS) >= 3 and hood.OFFICIAL in hood.RPCS
    run(go())


def test_copy_button_follows_a_trader_only_in_that_account():
    """0.32.284 (pedido do dono): botão Copiar no ranking, por conta, mesmo para quem não passou na regra."""
    async def go():
        w, c = copier()
        w.copiaria = []                                           # ninguém apto
        c.book("u2")
        assert await c.follow("u1", OTHER.upper().replace("0X", "0x"), True) == [OTHER]
        c.on_trade(trade("buy", 1000.0, 1.0, wallet=OTHER), 0.0, w.copiaria)
        await settle(c)
        assert len(c.books["u1"].pos) == 1 and not c.books["u2"].pos
        assert next(iter(c.books["u1"].pos.values()))["aba"] == "manual"
        c.books["u2"].cfg["auto_top"] = False                     # u2 não quer o Copiando agora
        w.copiaria = [TRADER]
        c.on_trade(trade("buy", 2000.0, 1.0), 0.0, w.copiaria)
        await settle(c)
        assert len(c.books["u1"].pos) == 2 and not c.books["u2"].pos
        assert await c.follow("u1", OTHER, False) == []
        try:
            await c.follow("u1", "nao-e-carteira", True)
            assert False
        except ValueError:
            pass
    run(go())


def test_follow_route_is_admin_only(env):  # noqa: F811
    from tests.test_api import UA, UB, tok
    c, hub = env["c"], env["hub"]
    hub.hood = hood.HoodWatch(None, None)
    w = "0x" + "5a" * 20
    assert c.post("/api/hood/seguir", json={"wallet": w, "on": True}, headers=tok(UB, "b@x.com")).status_code == 403
    assert c.post("/api/hood/seguir", json={"wallet": w, "on": True}, headers=tok(UA)).json()["manual"] == [w]
    assert c.get("/api/hood/painel", headers=tok(UA)).json()["cfg_sim"]["manual"] == [w]
    assert "error" in c.post("/api/hood/seguir", json={"wallet": "x", "on": True}, headers=tok(UA)).json()


def test_refuel_quotes_only_to_own_robinhood_wallet_and_needs_ligar_lock():
    """0.32.286 (pedido do dono): abastecer a carteira da Robinhood de outra rede pela Relay, com a conferência do Dormant."""
    from app import hoodgas
    from app.dormant_gas import DEPOSITORY, SEL_DEPOSIT
    addr = "0x" + "77" * 20
    sent = {}

    class Http:
        async def post(self, url, json=None, **kw):
            if "relay" in url:
                sent["relay"] = json
                v = int(json["amount"])
                return Resp({"steps": [{"id": "deposit", "kind": "transaction", "requestId": "0x" + "ab" * 32,
                                        "items": [{"data": {"to": DEPOSITORY, "chainId": json["originChainId"], "value": str(v), "from": json["user"],
                                                            "data": SEL_DEPOSIT + evm.w_addr(json["user"]) + "cd" * 32}}]}],
                             "details": {"recipient": json["recipient"], "sender": json["user"], "timeEstimate": 1,
                                         "currencyOut": {"amountFormatted": str(v / 1e18 * 0.99)}}})
            m = json["method"]
            res = {"eth_getBalance": hex(10 ** 18), "eth_gasPrice": hex(10 ** 9), "eth_estimateGas": hex(50000), "eth_chainId": hex(8453),
                   "eth_getTransactionCount": "0x1", "eth_sendRawTransaction": "0x" + "ef" * 32}[m]
            sent.setdefault("rpc", []).append(m)
            return Resp({"result": res})

        async def get(self, url, **kw):
            return Resp({"ethereum": {"usd": 2000.0}})

    async def go():
        w = Watch()
        w.eth_usd = 2000.0
        c = hoodcopy.Copier(w, Http())
        async def gk(uid):
            return 5, addr
        c.get_key = gk
        async def rpc(m, p):
            return hex(10 ** 15)
        c.chain.rpc = rpc
        st = await c.gas.status("u")
        assert st["chave"] and st["precisa"] and st["rotas"][0]["ok"]
        assert sent["relay"]["recipient"] == addr and sent["relay"]["destinationChainId"] == 4663
        q = await c.gas.preview("u", "base", 10)
        assert any("PUMP_REAL_ALLOWED" in b for b in q["bloqueia"]) and "quote_id" not in q        # trava geral fechada
        c.real_allowed = True
        assert "teto" in " ".join((await c.gas.preview("u", "base", 80))["bloqueia"])
        q = await c.gas.preview("u", "base", 10)
        assert q["quote_id"] and not q["bloqueia"] and abs(q["taxa_pct"] - 1.0) < 0.01
        try:
            await c.gas.fill("u", q["quote_id"], "sim")
            assert False
        except hoodgas.FillError as e:
            assert "ABASTECER" in str(e)
        row = await c.gas.fill("u", q["quote_id"], "ABASTECER")
        assert row["status"] == "pendente" and "eth_sendRawTransaction" in sent["rpc"] and c.gas.spent_24h("u") == 10
        try:
            await c.gas.preview("u", "polygon", 10)
            assert False
        except hoodgas.FillError:
            pass
    run(go())


def test_modes_per_trader_and_real_goes_first():
    """0.32.287 (pedido do dono): 3 botões (FICTÍCIA, REAL, as 2); com as duas ligadas a REAL sai primeiro e a FICTÍCIA usa o preço dela."""
    async def go():
        w, c = copier()
        w.copiaria = []
        order = []

        async def real_buy(uid, tr, px, key):
            order.append(("real", tr["wallet"]))
        c._real_buy = real_buy
        orig_buy = hoodcopy.Book.buy

        def fake_buy(self, tr, px, t, key, origem="top"):
            order.append(("sim", tr["wallet"]))
            return orig_buy(self, tr, px, t, key, origem)
        hoodcopy.Book.buy = fake_buy
        try:
            c.rcfg("u1")["real_on"] = True
            await c.follow("u1", OTHER, True, "real")
            await c.follow("u1", TRADER, True, "sim")
            c.on_trade(trade("buy", 1000.0, 1.0, wallet=OTHER), 0.0, w.copiaria)
            c.on_trade(trade("buy", 1000.0, 1.0, wallet=TRADER), 0.0, w.copiaria)
            await settle(c)
            assert ("real", OTHER) in order and ("sim", OTHER) not in order
            assert ("sim", TRADER) in order and ("real", TRADER) not in order
            order.clear()
            await c.follow("u1", OTHER, True, "ambas")
            c.on_trade(trade("buy", 500.0, 1.0, wallet=OTHER), 0.0, w.copiaria)
            await settle(c)
            assert order == [("real", OTHER), ("sim", OTHER)]                 # a REAL sai primeiro
        finally:
            hoodcopy.Book.buy = orig_buy
        b = c.books["u1"]
        p = next(x for x in b.pos.values() if x["wallet"] == OTHER)
        c._align("u1", {"wallet": OTHER, "token": TOK, "open_t": p["open_t"], "px_in": p["px_in"] * 2})
        assert p["alinhado_real"] and abs(p["px_in"] - p["px_in_ficticio"] * 2) < 1e-15
        rc = hoodreal.clean({"real_stop_pct": 30, "real_max_hold_h": 2})
        assert rc["real_stop_pct"] == 30 and rc["real_max_hold_h"] == 2
        try:
            await c.follow("u1", OTHER, True, "tudo")
            assert False
        except ValueError:
            pass
    run(go())


# ---------------------------------------------------------------- 0.32.290: stop móvel, sair com o trader / dev, preço reserva
DEV = "0x" + "33" * 20


class FollowWatch(Watch):
    """Watch que também responde balanceOf(token, carteira)."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.bal = {}

    async def rpc(self, method, params):
        p = params[0]
        if method == "eth_call" and p["data"].startswith(hoodcopy.SEL_BAL):
            who = "0x" + p["data"][-40:]
            return "0x" + evm.w_int(self.bal.get(who, 0))
        return await super().rpc(method, params)


class FollowHttp(Http):
    def __init__(self, dex=None):
        super().__init__()
        self.dex = dex or []

    async def get(self, url, **kw):
        if "dexscreener" in url:
            return Resp(self.dex)
        if "/api/v2/addresses/" in url:
            return Resp({"creation_transaction_hash": "0x" + "cd" * 32})
        if "/api/v2/transactions/" in url:
            return Resp({"from": {"hash": DEV}})
        return await super().get(url, **kw)


def fcopier(dex=None):
    w = FollowWatch()
    c = hoodcopy.Copier(w, FollowHttp(dex))
    c.keys[PID] = KEY
    c.book("u1")
    return w, c


def test_trailing_stop_follows_the_solana_rule():
    b = hoodcopy.Book("u1", {"slip_pct": 0, "gas_eth": 0})
    p = b.buy(trade("buy", 1000.0, 1.0), 0.001, time.time(), KEY)
    t = time.time()
    b.on_price(TOK, 0.0015, t)                       # ~+48%: liga o stop móvel (passou de 20%)
    assert p["id"] in b.pos and p["best_pct"] > 40
    b.on_price(TOK, 0.00142, t)                      # caiu ~8 pontos: segura
    assert p["id"] in b.pos
    r = b.on_price(TOK, 0.0013, t)                   # caiu mais de 10 pontos do pico: sai
    assert r and r[0]["motivo"].startswith("stop móvel")
    off = hoodcopy.Book("u2", {"slip_pct": 0, "gas_eth": 0, "trail_on": False})
    q = off.buy(trade("buy", 1000.0, 1.0), 0.001, t, KEY)
    off.on_price(TOK, 0.0015, t)
    off.on_price(TOK, 0.0011, t)
    assert q["id"] in off.pos                        # desligado: não sai


def test_new_switches_are_saved_as_booleans():
    c = hoodcopy.clean_cfg({"sair_dev": 0, "trail_on": "", "trail_ativa_pct": 50, "trail_dist_pct": 0})
    assert c["sair_dev"] is False and c["trail_on"] is False and c["sair_trader"] is True
    assert c["trail_ativa_pct"] == 50 and c["trail_dist_pct"] == 1
    rc = hoodreal.clean({"real_sair_trader": False, "real_trail_dist_pct": 25, "real_on": True})
    assert rc["real_sair_trader"] is False and rc["real_sair_dev"] is True and rc["real_trail_dist_pct"] == 25
    assert rc["real_on"] is False                    # ligar a REAL continua só pela rota com confirmação


def test_sells_when_the_trader_leaves_the_coin():
    async def go():
        w, c = fcopier()
        c.on_trade(trade("buy", 1000.0, 1.0), 0.0, w.copiaria)
        await settle(c)
        b = c.books["u1"]
        b.cfg["trader_so_lucro"] = False
        p = next(iter(b.pos.values()))
        w.bal = {TRADER: 1000 * 10 ** 18, DEV: 0}
        await c.follow_tick(time.time())
        assert p["id"] in b.pos and int(p["trader_max"]) == 1000 * 10 ** 18
        w.bal[TRADER] = 10 ** 18                     # vendeu por outra rota: sobrou 0,1%
        await c.follow_tick(time.time())
        assert p["id"] not in b.pos and b.trades[0]["motivo"] == "trader saiu da moeda"
    run(go())


def test_old_position_with_trader_at_zero_is_closed_and_switch_off_keeps_it():
    async def go():
        w, c = fcopier()
        c.on_trade(trade("buy", 1000.0, 1.0), 0.0, w.copiaria)
        await settle(c)
        b = c.books["u1"]
        p = next(iter(b.pos.values()))
        p["open_t"] -= 3600                          # posição de antes da regra
        b.cfg["sair_trader"] = False
        await c.follow_tick(time.time())
        assert p["id"] in b.pos                      # opção desligada: fica
        p.pop("trader_max")
        b.cfg["sair_trader"], b.cfg["trader_so_lucro"] = True, False
        await c.follow_tick(time.time())
        assert p["id"] not in b.pos and "saldo zero" in b.trades[0]["motivo"]
    run(go())


def test_sells_when_the_dev_dumps():
    async def go():
        w, c = fcopier()
        c.on_trade(trade("buy", 1000.0, 1.0), 0.0, w.copiaria)
        await settle(c)
        b = c.books["u1"]
        p = next(iter(b.pos.values()))
        w.bal = {TRADER: 5 * 10 ** 18, DEV: 100 * 10 ** 18}
        await c.follow_tick(time.time())
        assert c.dev[TOK] == DEV and p["id"] in b.pos
        w.bal[DEV] = 30 * 10 ** 18                   # dev vendeu 70%
        await c.follow_tick(time.time())
        assert p["id"] not in b.pos and b.trades[0]["motivo"] == "dev vendeu 70% da moeda"
    run(go())


def test_dexscreener_price_when_the_quote_is_stale_and_token_name():
    dex = [{"baseToken": {"address": TOK, "name": "Mihao Coin", "symbol": "MIHAO"},
            "quoteToken": {"address": hoodcopy.WETH}, "priceNative": "0.0003", "liquidity": {"usd": 900}}]

    async def go():
        w, c = fcopier(dex)
        c.on_trade(trade("buy", 1000.0, 1.0), 0.0, w.copiaria)
        await settle(c)
        b = c.books["u1"]
        p = next(iter(b.pos.values()))
        w.px[TOK] = (0.001, time.time() - 3600)      # último preço de 1 h atrás (o pool parou de cotar)
        await c.dex_tick(time.time())
        assert p["px_now"] == 0.0003 and p["px_src"] == "dexscreener"
        assert p["nome"] == "Mihao Coin" and p["simbolo"] == "MIHAO"
        pa = c.painel("u1")
        assert pa["posicoes"][0]["simbolo"] == "MIHAO" and pa["posicoes"][0]["pnl_pct"] < -60
    run(go())


def test_trader_exit_waits_for_profit_after_fees():
    """0.32.292 (pedido do dono): trader saiu e a posição está no prejuízo → segura; vende quando ficar positiva."""
    b = hoodcopy.Book("u1", {"slip_pct": 2, "gas_eth": 0.00002})
    t = time.time()
    p = b.buy(trade("buy", 1000.0, 1.0), 0.001, t, KEY)
    assert b.trader_exit(p, 0.5, 0.00101, t, "trader vendeu 50%") is None
    assert p["id"] in b.pos and p["espera"]["frac"] == 0.5 and abs(p["tokens_left"] - p["tokens"]) < 1e-9
    b.trader_exit(p, 1.0, 0.00099, t, "trader saiu da moeda")
    assert p["espera"]["frac"] == 1.0
    b.on_price(TOK, 0.00102, t)                      # +2% no preço ainda é prejuízo depois de taxa, folga e gás
    assert p["id"] in b.pos
    r = b.on_price(TOK, 0.0011, t)                   # +10%: positivo → vende tudo
    assert r and "ficar positivo" in r[0]["motivo"] and r[0]["pnl_eth"] > 0
    off = hoodcopy.Book("u2", {"trader_so_lucro": False})
    q = off.buy(trade("buy", 1000.0, 1.0), 0.001, t, KEY)
    assert off.trader_exit(q, 1.0, 0.0009, t, "trader saiu da moeda") and q["id"] not in off.pos
