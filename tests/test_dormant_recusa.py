"""0.32.416 (caso ELON do dono, 21/11, Polygon): compra recusada pela rede com "Too little received" (outra compra entrou antes no mesmo
bloco e o preço passou da folga de 3%). A tela agora explica o motivo e cada compra/venda pode usar folga própria. Sem internet."""
from app import dormant_buy as db_
from tests.test_dormant_compra import FakeNet, Resp, SENHA, UID, good_quote, run, setup

# retorno de verdade da transação 0x29a0c817…e107 (Polygon, 21/11/2026)
ELON_OUT = ("0x08c379a0000000000000000000000000000000000000000000000000000000000000002000000000000000000000000000000000000000000000000000000000000000"
            "13546f6f206c6974746c6520726563656976656400000000000000000000000000")


def test_decode_the_real_elon_revert():
    assert db_.decode_revert(ELON_OUT) == "Too little received"
    assert db_.decode_revert("0x4e487b71" + "0" * 62 + "11") == "panic 0x11"
    assert db_.decode_revert("0xdeadbeef") == "erro 0xdeadbeef"
    assert db_.decode_revert(None) is None and db_.decode_revert("0x") is None


def test_price_revert_explains_and_suggests_bigger_slippage():
    t = db_.revert_text("Too little received", "compra", 3.0)
    assert "subiu" in t and "folga de 3%" in t and "6%" in t and "só o gás" in t
    v = db_.revert_text("execution reverted: UniswapV2Router: INSUFFICIENT_OUTPUT_AMOUNT", "venda", 5.0)
    assert "caiu" in v and "folga de 5%" in v and "10%" in v


def test_other_reverts_have_their_own_text():
    assert "prazo" in db_.revert_text("Transaction too old", "compra", 3)
    assert "contrato do token" in db_.revert_text("STF", "venda", 3)
    assert "sem gás" in db_.revert_text(None, "compra", 3, sem_gas=True)
    assert "abc xyz" in db_.revert_text("abc xyz", "compra", 3)
    assert "não pôde ser lido" in db_.revert_text(None, "compra", 3)


def test_slippage_of_the_screen_stays_inside_the_limits():
    assert db_.clean_slip("6", 3.0) == 6.0
    assert db_.clean_slip(None, 3.0) == 3.0 and db_.clean_slip("", 3.0) == 3.0
    assert db_.clean_slip(99, 3.0) == 3.0 and db_.clean_slip(0, 3.0) == 3.0 and db_.clean_slip("x", 3.0) == 3.0
    assert db_.folga_sugerida(3) == 6 and db_.folga_sugerida(10) == 15


class TraceNet(FakeNet):
    async def post(self, url, json=None, headers=None, timeout=None):
        m = json["method"]
        if m == "debug_traceTransaction":
            return Resp({"result": {"error": "execution reverted", "output": ELON_OUT}})
        if m == "eth_getTransactionByHash":
            return Resp({"result": {"gas": hex(400000), "from": "0x1", "to": "0x2", "input": "0x"}})
        return await super().post(url, json=json, headers=headers, timeout=timeout)


def test_failed_buy_saves_the_reason_with_the_slippage_used():
    b, net, db = setup(TraceNet())
    run(db_.Buyer.save_wallet(b, UID, "ethereum", "0x" + "0" * 63 + "1", SENHA))
    run(b.set_on(UID, True, SENHA, "LIGAR"))
    p = run(b.preview(UID, "tok", "ethereum", 0.01, slip=8))
    assert p["slip"] == 8 and p["folga_padrao"] == 3.0 and p["minimo"] == 920
    net.status = "0x0"
    r = run(b.buy(UID, p["quote_id"], SENHA, "COMPRAR"))
    assert r["status"] == "falhou"
    m = db.tables["dormant_buys"][0]["motivo"]
    assert "proteger o seu preço" in m and "folga de 8%" in m and "15%" in m


def test_failed_buy_without_trace_still_records_failure():
    b, net, db = setup()
    p = good_quote(b)
    net.status = "0x0"
    r = run(b.buy(UID, p["quote_id"], SENHA, "COMPRAR"))
    assert r["status"] == "falhou" and "só o gás" in db.tables["dormant_buys"][0]["motivo"]


def test_limit_info_brings_the_configured_slippage():
    b, net, db = setup()
    run(b.save_wallet(UID, "ethereum", "0x" + "0" * 63 + "1", SENHA))
    assert run(b.limit_info(UID, "ethereum"))["folga"] == 3.0
