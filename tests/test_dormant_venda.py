"""0.32.243 (pedido do dono): vender pelo Dormant. Sem internet: rede e banco falsos; a chave 1 é o vetor público dos testes."""
import asyncio
import pathlib
import time

from app import dormant_buy as db_, evm
from tests.test_dormant_compra import ADDR, ETH, KEY, SENHA, TOKEN, UID, OUTRO, FakeNet, Resp, rlp_list, setup

db_.RECIBO_PASSO = 0
SALDO = 1000 * 10 ** 18


class SellNet(FakeNet):
    """Além da compra: saldo do token, autorização, cotação de venda e recibo com a moeda da rede entrando."""

    def __init__(self):
        super().__init__()
        self.token_bal, self.allow, self.sell_out = SALDO, 0, 10 ** 16        # 1000 tokens valem 0,01 ETH = US$ 20
        self.txs = []

    async def post(self, url, json=None, headers=None, timeout=None):
        m, p = json["method"], json["params"]
        if m == "eth_call":
            data = p[0]["data"]
            if data.startswith(db_.SEL_BALANCE):
                return Resp({"result": "0x" + evm.w_int(self.token_bal)})
            if data.startswith(db_.SEL_ALLOW):
                return Resp({"result": "0x" + evm.w_int(self.allow)})
            if data.startswith(db_.SEL_AMOUNTS) and p[0]["to"] == ETH["router"]:
                w = evm.words("0x" + data[10:])
                if "0x%040x" % w[3] == TOKEN and w[2] == 2:                   # token → moeda da rede
                    got = self.sell_out * w[0] // SALDO
                    return Resp({"result": "0x" + evm.w_int(32) + evm.w_int(2) + evm.w_int(w[0]) + evm.w_int(got)})
        if m == "eth_sendRawTransaction":
            f = rlp_list(bytes.fromhex(p[0][2:]))
            self.txs.append({"url": url, "to": "0x" + f[3].hex(), "value": int.from_bytes(f[4], "big"), "data": f[5].hex()})
            if f[5].hex().startswith(db_.SEL_APPROVE[2:]):
                self.allow = evm.words("0x" + f[5].hex()[8:])[1]
        if m == "eth_getTransactionReceipt":
            return Resp({"result": {"status": self.status, "gasUsed": hex(200000), "effectiveGasPrice": hex(self.gas), "transactionHash": p[0], "logs": [
                {"address": ETH["wrapped"], "topics": [db_.T_WITHDRAW, "0x" + ETH["router"][2:].rjust(64, "0")], "data": hex(self.sell_out)},
                {"address": TOKEN, "topics": [db_.T_TRANSFER, "0x" + ADDR[2:].rjust(64, "0"), "0x" + "0" * 64], "data": hex(self.token_bal)}]}})
        return await super().post(url, json=json, headers=headers, timeout=timeout)


def run(c):
    return asyncio.run(c)


def bought(net=None):
    b, net, db = setup(net or SellNet())
    run(b.save_wallet(UID, "ethereum", KEY, SENHA))
    db.tables["dormant_buys"].append({"id": "c1", "user_id": UID, "em": db_._iso(time.time() - 3600), "rede": "ethereum", "cmc": "tok", "cg": "tok-cg", "nome": "Tok", "simbolo": "TOK",
                                      "token": TOKEN, "endereco": ADDR, "status": "confirmada", "qty": 1000.0, "px_in": 0.01, "usd_in": 10.0, "gas_usd": 0.0})
    return b, net, db


def test_sell_approves_exact_amount_on_fixed_router_then_sends_money_to_own_wallet():
    b, net, db = bought()
    p = run(b.preview_sell(UID, "c1", 50))
    assert p.get("quote_id"), p["bloqueia"]
    assert p["vende"] == 500 and p["aprovar"] is True and any("valor exato" in x for x in p["avisos"])
    r = run(b.sell(UID, p["quote_id"], SENHA, "VENDER"))
    assert r["status"] == "confirmada" and r["usd_out"] == 20.0
    assert len(net.txs) == 2
    ap, sw = net.txs
    assert ap["to"] == TOKEN and ap["url"] == ETH["rpc"] and ap["value"] == 0
    w = evm.words("0x" + ap["data"][8:])
    assert "0x%040x" % w[0] == ETH["router"] and w[1] == SALDO // 2          # valor exato, nunca ilimitado
    assert sw["to"] == ETH["router"] and sw["value"] == 0 and sw["url"] == "https://rpc.flashbots.net/fast" and "0x" + sw["data"][:8] == db_.SEL_SELL_ETH
    w = evm.words("0x" + sw["data"][8:])
    assert w[0] == SALDO // 2 and "0x%040x" % w[3] == ADDR                   # o dinheiro vai para a própria carteira
    assert KEY not in str(db.tables["dormant_sells"])


def test_existing_allowance_skips_approve():
    net = SellNet()
    net.allow = SALDO
    b, net, _ = bought(net)
    p = run(b.preview_sell(UID, "c1", 100))
    assert p["aprovar"] is False
    run(b.sell(UID, p["quote_id"], SENHA, "VENDER"))
    assert len(net.txs) == 1 and net.txs[0]["to"] == ETH["router"]


def test_sell_works_with_buying_off_but_not_with_general_lock():
    b, _, _ = bought()
    assert run(b.cfg(UID))["on"] is False
    assert run(b.preview_sell(UID, "c1", 100)).get("quote_id")
    b.allowed = lambda: False
    p = run(b.preview_sell(UID, "c1", 100))
    assert not p.get("quote_id") and any("PUMP_REAL_ALLOWED" in x for x in p["bloqueia"])


def test_word_password_and_quote_rules():
    b, net, _ = bought()
    p = run(b.preview_sell(UID, "c1", 100))
    for senha, word in ((SENHA, "COMPRAR"), ("errada-errada", "VENDER")):
        try:
            run(b.sell(UID, p["quote_id"], senha, word))
            raise AssertionError
        except db_.BuyError:
            pass
    assert not net.txs
    try:                                       # cotação de venda não serve para comprar
        run(b.buy(UID, p["quote_id"], SENHA, "COMPRAR"))
        raise AssertionError
    except db_.BuyError:
        pass
    run(b.set_on(UID, True, SENHA, "LIGAR"))
    q = run(b.preview(UID, "tok", "ethereum", 0.01))
    try:                                       # e a de compra não serve para vender
        run(b.sell(UID, q["quote_id"], SENHA, "VENDER"))
        raise AssertionError
    except db_.BuyError:
        pass
    run(b.sell(UID, p["quote_id"], SENHA, "VENDER"))
    try:                                       # clique dobrado
        run(b.sell(UID, p["quote_id"], SENHA, "VENDER"))
        raise AssertionError
    except db_.BuyError:
        pass


def test_other_account_and_bad_inputs():
    b, _, _ = bought()
    for args in ((OUTRO, "c1", 100), (UID, "nada", 100), (UID, "c1", 0), (UID, "c1", 101), (UID, "c1", "x")):
        try:
            run(b.preview_sell(*args))
            raise AssertionError(args)
        except db_.BuyError:
            pass


def test_blocks_without_balance_changed_wallet_or_bad_price():
    net = SellNet()
    b, net, db = bought(net)
    net.token_bal = 0
    p = run(b.preview_sell(UID, "c1", 100))
    assert not p.get("quote_id") and any("não tem este token" in x for x in p["bloqueia"])
    net.token_bal = SALDO
    net.sell_out = 10 ** 15                    # receberia US$ 2 por US$ 20 na CoinGecko
    p = run(b.preview_sell(UID, "c1", 100))
    assert not p.get("quote_id") and any("abaixo do preço" in x for x in p["bloqueia"])
    net.sell_out = 10 ** 16
    db.tables["dormant_buys"][0]["endereco"] = "0x" + "11" * 20
    p = run(b.preview_sell(UID, "c1", 100))
    assert not p.get("quote_id") and any("trocada" in x for x in p["bloqueia"])


def test_worse_price_or_changed_balance_send_nothing():
    for mexe in (lambda n: setattr(n, "sell_out", 5 * 10 ** 15), lambda n: setattr(n, "token_bal", 1), lambda n: setattr(n, "chain", 56)):
        b, net, _ = bought()
        p = run(b.preview_sell(UID, "c1", 100))
        mexe(net)
        try:
            run(b.sell(UID, p["quote_id"], SENHA, "VENDER"))
            raise AssertionError
        except db_.BuyError as e:
            assert "nada foi enviado" in str(e)
        assert not net.txs


def test_pending_sale_blocks_next_operation_and_row_saved_before_send():
    b, net, db = bought()
    p = run(b.preview_sell(UID, "c1", 100))
    orig = net.post
    seen = []

    async def spy(url, json=None, headers=None, timeout=None):
        if json["method"] == "eth_sendRawTransaction" and not json["params"][0].startswith("0xapprove"):
            seen.append(len(db.tables["dormant_sells"]))
        return await orig(url, json=json, headers=headers, timeout=timeout)
    net.post = spy
    run(b.sell(UID, p["quote_id"], SENHA, "VENDER"))
    assert seen == [0, 1]                      # a autorização não grava; a venda grava antes de enviar
    db.tables["dormant_sells"][0]["status"] = "pendente"
    p2 = run(b.preview_sell(UID, "c1", 100))
    assert not p2.get("quote_id") and any("sem confirmação" in x for x in p2["bloqueia"])


def test_history_nets_sales_oldest_purchase_first():
    b, _, _ = setup()
    now = time.time()
    b.watch.rows["tok-cg"].update(current_price=2.0, sparkline_in_7d={"price": [1.0] * 168})
    base = {"rede": "ethereum", "cg": "tok-cg", "token": TOKEN, "status": "confirmada", "gas_usd": 0.0}
    rows = [{**base, "id": "nova", "em": db_._iso(now - 100), "qty": 10.0, "px_in": 1.0, "usd_in": 10.0},
            {**base, "id": "velha", "em": db_._iso(now - 86400), "qty": 10.0, "px_in": 1.0, "usd_in": 10.0}]
    sells = [{"rede": "ethereum", "token": TOKEN, "status": "confirmada", "em": db_._iso(now - 50), "qty": 15.0, "usd_out": 30.0, "gas_usd": 0.0},
             {"rede": "ethereum", "token": TOKEN, "status": "falhou", "em": db_._iso(now - 40), "qty": 5.0, "usd_out": 99.0}]
    h = db_.holdings(rows, b.watch, now, sells=sells)
    nova, velha = h["itens"]
    assert velha["vendido"] == 10.0 and velha["resto"] == 0 and velha["recebido"] == 20.0 and velha["h1"] is None and velha["total"] == 100.0
    assert nova["vendido"] == 5.0 and nova["resto"] == 5.0 and nova["recebido"] == 10.0 and nova["valor"] == 10.0 and nova["ganho"] == 10.0
    assert h["resumo"] == {**h["resumo"], "investido": 20.0, "valor": 10.0, "recebido": 30.0, "ganho": 20.0, "total": 100.0}


def test_v3_sale_unwraps_to_own_wallet():
    data = db_.v3_sell_data(TOKEN, ETH["wrapped"], 3000, ADDR, 123, 1000, 900)
    assert data.startswith(db_.SEL_MULTI)
    h = data[10:]
    assert (len(h) // 2) % 32 == 0
    w = evm.words("0x" + h)
    assert w[0] == 32 and w[1] == 2 and w[2] == 64
    assert ADDR[2:] in h and db_.V3_ROUTER[2:] in h and db_.SEL_UNWRAP[2:] in h


def test_migration_keeps_sales_closed():
    sql = pathlib.Path("supabase/migrations/20261106000002_dormant_vendas.sql").read_text(encoding="utf-8")
    assert "enable row level security" in sql and "revoke all on public.dormant_sells from anon, authenticated" in sql and "create policy" not in sql


# 0.32.411 (pedido do dono): vender só o valor investido desta compra, em moeda da rede
def test_sell_only_the_invested_value():
    b, net, db = bought()
    db.tables["dormant_buys"][-1]["nativo"] = 0.0025                  # o saldo todo vale 0,01 ETH: vende 1/4
    p = run(b.preview_sell(UID, "c1", "investido"))
    assert p.get("quote_id"), p["bloqueia"]
    assert p["investido"] is True and p["pct"] == 25 and p["vende"] == 250 and p["investido_nativo"] == 0.0025
    db.tables.setdefault("dormant_sells", []).append({"id": "v1", "user_id": UID, "compra": "c1", "status": "confirmada", "nativo_out": 0.002, "token": TOKEN, "rede": "ethereum"})
    p = run(b.preview_sell(UID, "c1", "investido"))                    # já voltaram 0,002: falta 0,0005 = 5%
    assert p["pct"] == 5 and p["vende"] == 50
    db.tables["dormant_sells"][-1]["nativo_out"] = 0.003
    p = run(b.preview_sell(UID, "c1", "investido"))
    assert not p.get("quote_id") and any("já voltou" in x for x in p["bloqueia"])
    db.tables["dormant_sells"].clear()
    db.tables["dormant_buys"][-1]["nativo"] = 0.05                    # vale menos que o investido: vende tudo e avisa
    p = run(b.preview_sell(UID, "c1", "investido"))
    assert p["pct"] == 100 and p["vende"] == 1000 and any("menos que o investido" in x for x in p["avisos"])


def test_sell_amount_uses_bps_and_falls_back_to_pct():
    assert db_.sell_amount(10_000, {"pct": 50}) == 5_000
    assert db_.sell_amount(10_000, {"bps": 1234, "pct": 12.34}) == 1_234
    assert db_.sell_amount(10_000, {"bps": 10_000}) == 10_000
