"""0.32.468 (pedido do dono, 26/11/2026): compra de MANTRA feita no site da Squid entra em Minhas compras. Sem internet: tudo falso,
no formato visto na compra real (depósito na Base, 11 s depois o SquidMulticall paga a carteira na MANTRA)."""
import asyncio

from app import dormant_buy as db_, dormant_squid as sq, evm
from tests.test_dormant_compra import ADDR, KEY, SENHA, UID, OUTRO, FakeNet, Resp, setup

AGORA = int(__import__("time").time())
ENTREGA = AGORA - 200
TX_M, TX_B = "0x" + "fe" * 32, "0x" + "d8" * 32
BLOCO0 = 1_000_000                       # Base falsa: 0,2 s por bloco
TOPO = BLOCO0 + 100_000
PAGOU = ENTREGA - 11


def ts(n):
    return AGORA - (TOPO - n) // 5


class Net(FakeNet):
    def __init__(self):
        super().__init__()
        self.itens = [item()]
        self.mantra = {"to": sq.ROUTERS[0], "input": "0x58181a80" + "00" * 12 + ADDR[2:], "status": "0x1"}
        self.valor, self.logs, self.status_base = 600000000000000, [], "0x1"
        self.base_fora = False
        self.pagou = True
        self.explorador = 0

    @property
    def bloco_pago(self):
        return TOPO - (AGORA - PAGOU) * 5

    async def get(self, url, params=None, headers=None, timeout=None):
        if "mantrascan" in url:
            self.explorador += 1
            return Resp({"items": self.itens})
        if "simple/price" in url:
            cg = (params or {}).get("ids")
            return Resp({cg: {"usd": {"mantra": 0.0025, "ethereum": 1700.0}.get(cg, 1.0)}})
        return await super().get(url, params=params, headers=headers, timeout=timeout)

    async def post(self, url, json=None, headers=None, timeout=None):
        m, p = json["method"], json["params"]
        if url == db_.CHAINS["mantra-evm"]["rpc"]:
            if m == "eth_getTransactionByHash":
                return Resp({"result": {"to": self.mantra["to"], "input": self.mantra["input"]}})
            return Resp({"result": {"status": self.mantra["status"]}})
        if url == db_.CHAINS["base"]["rpc"]:
            if self.base_fora:
                return Resp({"error": {"message": "fora do ar"}})
            if m == "eth_getBlockByNumber":
                n = TOPO if p[0] == "latest" else int(p[0], 16)
                txs = [{"from": ADDR, "hash": TX_B, "nonce": "0x2", "value": hex(self.valor)}] if p[1] and self.pagou and n == self.bloco_pago else []
                return Resp({"result": {"number": hex(n), "timestamp": hex(ts(n)), "transactions": txs}})
            if m == "eth_getTransactionCount":
                return Resp({"result": hex(3 if self.pagou and int(p[1], 16) >= self.bloco_pago else 2)})
            if m == "eth_getTransactionReceipt":
                return Resp({"result": {"status": self.status_base, "gasUsed": "0x5208", "effectiveGasPrice": "0x5f5e100", "l1Fee": "0x0", "logs": self.logs}})
        return await super().post(url, json=json, headers=headers, timeout=timeout)


def item(**mais):
    from datetime import datetime, timezone
    base = {"from": {"hash": "0x073e81D92bd8B39562106819D12346240606F04A"}, "to": {"hash": ADDR}, "success": True, "value": "392302782766948339848",
            "transaction_hash": TX_M, "timestamp": datetime.fromtimestamp(ENTREGA, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000000Z")}
    return {**base, **mais}


def run(c):
    return asyncio.run(c)


def ready(net=None):
    b, net, db = setup(net or Net())
    b.watch.map["mantra-dao"], b.watch.pick["mantra-dao"] = ["mantra"], "mantra"
    run(b.save_wallet(UID, "mantra-evm", KEY, SENHA))
    return b, net, db


def compras(db):
    return db.tables.get("dormant_buys", [])


def test_purchase_made_on_squid_shows_up_with_what_was_paid():
    b, net, db = ready()
    h = run(b.history(UID))
    assert h["squid"]["erro"] is None and len(h["itens"]) == 1
    x = h["itens"][0]
    assert abs(x["qty"] - 392.30278276694835) < 1e-9 and x["fora"] is True and x["cmc"] == "mantra-dao" and x["status"] == "confirmada"
    assert x["usd_in"] == 1.02 and x["rota"] == "0.0006 ETH na Base → MANTRA" and x["motivo"] == sq.PAGO + TX_B and x["tx"] == TX_M
    assert run(b.spent_today(UID)) == 0 and not net.sent                              # não conta no limite e nada é enviado
    assert "mantra" in b.watch.held


def test_never_recorded_twice_and_asks_the_explorer_at_most_once_a_minute():
    b, net, db = ready()
    run(b.history(UID))
    run(b.history(UID))
    assert net.explorador == 1
    b._squid[UID]["tentou"] = 0
    run(b.history(UID))
    assert net.explorador == 2 and len(compras(db)) == 1


def test_paid_with_usdc():
    net = Net()
    net.valor = 0
    net.logs = [{"address": sq.USDC_BASE, "topics": [sq.T_TRANSFER, "0x" + "00" * 12 + ADDR[2:], "0x" + "00" * 32], "data": "0x" + evm.w_int(2_000_000)}]
    b, _, db = ready(net)
    run(b.history(UID))
    x = compras(db)[0]
    assert x["usd_in"] == 2.0 and x["rota"] == "2 USDC na Base → MANTRA"


def test_without_payment_on_base_the_cost_is_estimated_and_said():
    net = Net()
    net.pagou = False
    b, _, db = ready(net)
    run(b.history(UID))
    x = compras(db)[0]
    assert x["motivo"] == sq.SEM_PAGAMENTO and x["gas_usd"] == 0 and abs(x["usd_in"] - 392.30278276694835 * 0.0025) < 1e-5


def test_base_down_records_nothing_and_tries_again():
    net = Net()
    net.base_fora = True
    b, _, db = ready(net)
    h = run(b.history(UID))
    assert h["squid"]["erro"] and not compras(db)
    net.base_fora = False
    b._squid[UID]["tentou"] = 0
    run(b.history(UID))
    assert len(compras(db)) == 1


def test_only_real_squid_deliveries_to_this_wallet_enter():
    outro = "0x" + "99" * 20
    for mudar in (lambda n: n.itens.__setitem__(0, item(**{"from": {"hash": outro}})),
                  lambda n: n.itens.__setitem__(0, item(**{"to": {"hash": outro}})),
                  lambda n: n.itens.__setitem__(0, item(success=False)),
                  lambda n: n.itens.__setitem__(0, item(value="1000000000000000")),          # poeira
                  lambda n: n.mantra.update(to=outro),
                  lambda n: n.mantra.update(input="0x58181a80"),
                  lambda n: n.mantra.update(status="0x0")):
        net = Net()
        mudar(net)
        b, _, db = ready(net)
        run(b.history(UID))
        assert not compras(db), "entrou o que não devia"


def test_other_account_sees_nothing():
    b, _, db = ready()
    assert run(b.history(OUTRO))["squid"] is None and not compras(db)


def test_it_is_only_for_tracking_no_selling_from_here():
    b, _, db = ready()
    run(b.history(UID))
    cid = compras(db)[0]["id"]
    for chamada in (b.preview_sell(UID, cid, 100), b.save_autosell_coin(UID, cid, 50, SENHA)):
        try:
            run(chamada)
            raise AssertionError("deixou vender")
        except db_.BuyError:
            pass
