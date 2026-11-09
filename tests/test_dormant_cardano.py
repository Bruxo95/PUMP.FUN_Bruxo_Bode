"""0.32.273 (pedido do dono, 09/11/2026): carteira Cardano e compra pela Minswap no Dormant. Sem internet: Minswap, Koios e banco falsos.
A frase usada é o vetor público do CIP-11 (nenhuma carteira de verdade)."""
import json
import pathlib

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from app import cardano as C, dormant_buy as db_
from tests.test_dormant_compra import SENHA, UID, Resp, run, setup

FRASE = "prevent company field green slot measure chief hero apple task eagle sunset endorse dress seed"
SNEK = "279c909f348e533da5808898f87f9a14bb2c3dfbbacccd631d927a3f534e454b"
SCRIPT = bytes.fromhex("11" + "aa" * 56)                     # endereço do contrato da DEX (script)
TAXA = bytes.fromhex("61" + "bb" * 28)                       # quem recebe a taxa do agregador
# transações reais montadas pela Minswap em 09/11/2026 para carteiras públicas (só montadas: ninguém assinou)
REAIS = json.loads(pathlib.Path(__file__).with_name("dados_ada_minswap.json").read_text())


def test_official_vectors_cip3_cip11_cip19_and_signature():
    m = C.master(C.entropy("eight country switch draw meat scout mystery blade tip drift useless good keep usage title"))
    assert m.hex().startswith("c065afd2832cd8b087c4d9ab7011f481ee1e0721e78ea5dd609f3ab3f156d245")      # CIP-3, sem senha
    s = C.derive(C.master(C.entropy(FRASE)), C.PATH_STAKE)
    assert s.hex().startswith("b8ab42f1aacbcdb3ae858e3a3df88142b3ed27a2d3f432024e0d943fc1e59744")      # CIP-11, m/1852'/1815'/0'/2/0
    assert C.bech32_encode("stake", b"\xe1" + C.h224(C.pub_of(s[:32]))) == "stake1uy8ykk8dzmeqxm05znz65nhr80m0k3gxnjvdngf8azh6sjc6hyh36"
    pv = C.bech32_decode("addr_vk1w0l2sr2zgfm26ztc6nl9xy8ghsk5sh6ldwemlpmp9xylzy4dtf7st80zhd")[1]
    sv = C.bech32_decode("stake_vk1px4j0r2fk7ux5p23shz8f3y5y2qam7s954rgf3lg5merqcj6aetsft99wu")[1]
    assert C.base_address(pv, sv) == ("addr1qx2fxv2umyhttkxyxp8x0dlpdt3k6cwng5pxj3jhsydzer3n0d3vllmyqwsx5wktcd8cc3sq835lu7drv2xwl2wywfgse35a3x")   # CIP-19
    w = C.Wallet(FRASE)
    Ed25519PublicKey.from_public_bytes(w.pub).verify(C.sign(w.kl, w.kr, b"x" * 32), b"x" * 32)


def test_bad_phrase_is_refused_with_a_readable_reason():
    for f, why in (("prevent company field", "12, 15"), (FRASE.replace("seed", "sead"), "lista oficial"), (FRASE.replace("seed", "apple"), "não confere")):
        try:
            C.Wallet(f)
            raise AssertionError("aceitou frase errada")
        except ValueError as e:
            assert why in str(e)


class _Pay:
    def __init__(self, adr):
        self.pay_hash = C.bech32_decode(adr)[1][1:29]


def test_real_minswap_buy_and_sell_pass_only_inside_the_limits():
    buy = REAIS["compra"]
    h, info = C.check_tx(buy["cbor"], _Pay(buy["endereco"]), max_out_lovelace=int((10 + 0.85 + 0.88 + 2 + 0.5) * 1e6))
    assert len(h) == 32 and info["sai_ada"] == 13.54 and info["sai_token"] == 0
    try:
        C.check_tx(buy["cbor"], _Pay(buy["endereco"]), max_out_lovelace=12_000_000)
        raise AssertionError("aceitou sair mais ADA que o previsto")
    except C.TxRejected:
        pass
    sell = REAIS["venda"]
    _, info = C.check_tx(sell["cbor"], _Pay(sell["endereco"]), max_out_lovelace=6_000_000, token_out=SNEK, max_token_out=3000)
    assert info["sai_token"] == 3000
    for kw in ({"token_out": SNEK, "max_token_out": 2999}, {}):                     # vende mais que o pedido / token que não é o da venda
        try:
            C.check_tx(sell["cbor"], _Pay(sell["endereco"]), max_out_lovelace=6_000_000, **kw)
            raise AssertionError("aceitou token a mais")
        except C.TxRejected:
            pass


# ------------------------------------------------------------------ fluxo completo com a carteira do vetor
def enc(v) -> bytes:
    def hd(mt, n):
        if n < 24:
            return bytes([mt << 5 | n])
        for ai, sz in ((24, 1), (25, 2), (26, 4), (27, 8)):
            if n < 1 << (8 * sz):
                return bytes([mt << 5 | ai]) + n.to_bytes(sz, "big")
    if isinstance(v, bool) or v is None:
        return bytes([0xF5 if v else 0xF4]) if v is not None else b"\xf6"
    if isinstance(v, int):
        return hd(0, v)
    if isinstance(v, bytes):
        return hd(2, len(v)) + v
    if isinstance(v, list):
        return hd(4, len(v)) + b"".join(enc(x) for x in v)
    if isinstance(v, dict):
        return hd(5, len(v)) + b"".join(enc(k) + enc(x) for k, x in v.items())
    raise TypeError(v)


def tx(w, outs, extra=None) -> str:
    body = {0: [[b"\x11" * 32, 0]], 1: outs, 2: 200_000, 3: 99_999_999}
    body.update(extra or {})
    return enc([body, {}, True, None]).hex()


class AdaNet:
    """Minswap + Koios + CoinGecko falsos. Guarda o que seria enviado."""

    def __init__(self, w):
        self.w, self.sent, self.cancel = w, [], []
        self.lov, self.tok = 50_000_000, 0
        self.pending, self.conf = True, 3
        self.build = None
        self.mine = w.addr_bytes

    async def get(self, url, params=None, headers=None, timeout=None):
        if url.endswith("/wallet"):
            return Resp({"ada": str(self.lov), "balance": [{"asset": {"token_id": SNEK}, "amount": str(self.tok)}]})
        if url.endswith("/pending-orders"):
            return Resp({"orders": [{"tx_in": self.sent[-1][2] + "#0"}] if self.pending and self.sent else []})
        if "simple/price" in url:
            return Resp({"cardano": {"usd": 0.6}})
        raise AssertionError(url)

    async def post(self, url, json=None, headers=None, timeout=None):
        if url.endswith("/estimate"):
            sell = json["token_in"] != "lovelace"
            return Resp({"amount_out": "8" if sell else "3689", "min_amount_out": "7.9" if sell else "3652", "aggregator_fee": "0.85", "total_dex_fee": "0.88",
                         "deposits": "2", "avg_price_impact": 1.0, "paths": [[{"protocol": "MinswapV2"}]],
                         "tokens": {SNEK: {"decimals": 0}, "lovelace": {"decimals": 6}}})
        if url.endswith("/build-tx"):
            return Resp({"cbor": self.build or tx(self.w, [[SCRIPT, 12_690_000], [TAXA, 850_000], [self.mine, 30_000_000]])})
        if url.endswith("/finalize-and-submit-tx"):
            body, raw = C.tx_parts(json["cbor"])
            h = C.body_hash(raw)
            wit = bytes.fromhex(json["witness_set"])
            Ed25519PublicKey.from_public_bytes(wit[6:38]).verify(wit[40:104], h)   # {0: [[vkey, assinatura]]} confere com o hash do corpo
            assert wit[6:38] == self.w.pub
            self.sent.append((json["cbor"], json["witness_set"], h.hex()))
            return Resp({"tx_id": h.hex()})
        if url.endswith("/cancel-tx"):
            self.cancel.append(json)
            return Resp({"cbor": tx(self.w, [[self.mine, 12_000_000]])})
        if url.endswith("/tx_status"):
            return Resp([{"tx_hash": json["_tx_hashes"][0], "num_confirmations": self.conf}])
        raise AssertionError(url)


def ada_setup():
    w = C.Wallet(FRASE)
    net = AdaNet(w)
    b, _, db = setup(net)
    b.watch.addr = {"tok-cg": {"cardano": SNEK}}
    b.watch.plat = {"tok-cg": ["cardano"]}
    b.watch.rows["tok-cg"]["current_price"] = 0.0016
    run(b.save_wallet(UID, "cardano", "  " + FRASE.upper().replace(" ", "   ") + " ", SENHA))           # espaços e maiúsculas tanto faz
    run(b.set_on(UID, True, SENHA, "LIGAR"))
    return b, net, db, w


def test_cardano_wallet_is_saved_from_the_phrase_and_shows_its_address():
    b, net, db, w = ada_setup()
    rows = {r["rede"]: r for r in db.tables["dormant_wallets"]}
    assert rows["cardano"]["endereco"] == w.address and w.address.startswith("addr1q")
    assert FRASE not in json.dumps(db.tables)                      # a frase só fica cifrada
    assert db_.buyable(b.watch, "tok-cg") == ["cardano"]


def test_buy_signs_only_the_checked_transaction_and_waits_for_the_token():
    b, net, db, w = ada_setup()
    p = run(b.preview(UID, "tok", "cardano", 10))
    assert p.get("quote_id"), p["bloqueia"]
    assert p["dex"] == "Minswap" and p["recebe"] == 3689 and any("0.85 ADA do agregador" in a for a in p["avisos"])
    r = run(b.buy(UID, p["quote_id"], SENHA, "COMPRAR"))
    assert len(net.sent) == 1 and r["status"] == "pendente"         # ordem na DEX: o token ainda não chegou
    net.pending, net.tok = False, 3680                               # a Minswap executou: o token chegou na carteira
    row = db.tables["dormant_buys"][0]
    row["status"] = "pendente"
    out = run(b._apply_ada(row, venda=False))
    assert out["status"] == "confirmada" and out["qty"] == 3680 and out["px_in"] > 0


def test_buy_that_would_send_extra_ada_or_a_certificate_is_never_signed():
    b, net, db, w = ada_setup()
    for bad in (tx(w, [[SCRIPT, 12_690_000], [TAXA, 850_000], [TAXA, 5_000_000], [w.addr_bytes, 25_000_000]]),   # leva 5 ADA a mais
                tx(w, [[SCRIPT, 12_690_000], [w.addr_bytes, 30_000_000]], {4: [[0, [0, w.pay_hash]]]})):         # delegação escondida
        net.build = bad
        p = run(b.preview(UID, "tok", "cardano", 10))
        try:
            run(b.buy(UID, p["quote_id"], SENHA, "COMPRAR"))
            raise AssertionError("assinou transação errada")
        except db_.BuyError as e:
            assert "conferência" in str(e)
    assert net.sent == [] and not db.tables.get("dormant_buys")


def test_stuck_order_is_cancelled_and_only_returns_money():
    b, net, db, w = ada_setup()
    p = run(b.preview(UID, "tok", "cardano", 10))
    run(b.buy(UID, p["quote_id"], SENHA, "COMPRAR"))
    row = db.tables["dormant_buys"][0]
    r = run(b.cancel_ada(UID, "compra", row["id"], SENHA))
    assert r["ok"] and net.cancel[0]["orders"] == [{"tx_in": net.sent[0][2] + "#0"}]
    assert db.tables["dormant_buys"][0]["status"] == "cancelada"
    assert run(b.spent_today(UID)) == 0                              # cancelada não conta no limite do dia


def test_sell_sends_only_the_token_being_sold():
    b, net, db, w = ada_setup()
    p = run(b.preview(UID, "tok", "cardano", 10))
    run(b.buy(UID, p["quote_id"], SENHA, "COMPRAR"))
    net.pending, net.tok = False, 3680
    row = db.tables["dormant_buys"][0]
    run(b._apply_ada(row, venda=False))
    net.pending = True
    net.build = tx(w, [[SCRIPT, [2_690_000, {bytes.fromhex(SNEK[:56]): {bytes.fromhex(SNEK[56:]): 1840}}]], [TAXA, 850_000], [w.addr_bytes, 40_000_000]])
    q = run(b.preview_sell(UID, row["id"], 50))
    assert q.get("quote_id"), q["bloqueia"]
    assert q["vende"] == 1840
    run(b.sell(UID, q["quote_id"], SENHA, "VENDER"))
    assert len(net.sent) == 2
    db.tables["dormant_sells"][0]["status"] = "confirmada"           # a 1ª venda terminou (com uma pendente a rede fica travada)
    net.build = tx(w, [[SCRIPT, [2_690_000, {bytes.fromhex(SNEK[:56]): {bytes.fromhex(SNEK[56:]): 3000}}]], [w.addr_bytes, 40_000_000]])
    q = run(b.preview_sell(UID, row["id"], 50))
    try:
        run(b.sell(UID, q["quote_id"], SENHA, "VENDER"))              # a montagem tenta levar mais token que o vendido
        raise AssertionError("vendeu a mais")
    except db_.BuyError as e:
        assert "conferência" in str(e)
