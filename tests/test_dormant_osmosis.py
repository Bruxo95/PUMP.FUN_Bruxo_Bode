"""0.32.274 (pedido do dono, 09/11/2026): carteira da Osmosis (Cosmos) e compra pela DEX da Osmosis no Dormant. Sem internet: nó, roteador
e banco falsos. A frase é o vetor público "abandon … about" (nenhuma carteira de verdade)."""
import base64
import hashlib
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

from app import dormant_buy as db_, osmosis as O
from tests.test_dormant_compra import SENHA, UID, Resp, run, setup

FRASE = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
AKT = "ibc/1480B8FD20AD5FCAE81EA87584D269547DD4D436843C1D20F15E00EB64743EF4"


def test_official_vectors_bip39_bip32_ripemd_and_the_known_cosmos_address():
    assert O.ripemd160(b"abc").hex() == "8eb208f7e05d987a9b044a8e98c6b087f15a0bfc"
    for n in (0, 55, 56, 64, 65, 300):                                   # bordas do preenchimento
        m = os.urandom(n)
        try:
            assert O.ripemd160(m) == hashlib.new("ripemd160", m).digest()
        except ValueError:                                                # hashlib sem RIPEMD-160 (OpenSSL 3): fica só o vetor oficial
            pass
    assert O.seed(FRASE, "TREZOR").hex().startswith("c55257c360c07c72029aebc1b53c05ed0362ada38ead3e3e9efa3708e534955")   # BIP39 (Trezor)
    assert hex(O.bip32(bytes(range(16)), [0x80000000, 1, 0x80000002, 2, 1000000000])) == "0x471b76e389e528d6de6d816857e012c5455051cad6660850e58372a6c3e6e7c8"  # BIP32 vetor 1
    w = O.Wallet(FRASE)
    assert O.address_of_pub(w.pub, "cosmos") == "cosmos19rl4cm2hmr8afy4kldpxz3fka4jguq0auqdal4"
    assert w.address == "osmo19rl4cm2hmr8afy4kldpxz3fka4jguq0a5m7df8"
    assert base64.b64encode(w.pub).decode() == "Ak9OKtmcNNYLm6YoPJQxqEGK+GcyEpYfl6d7Y3f80Fti"   # a chave que a Osmosis guarda para essa conta pública
    assert O.Wallet(hex(w.key)).address == w.address                      # chave privada em hex (Keplr) dá o mesmo endereço


def _pb(b: bytes) -> dict:
    """Leitor de protobuf mínimo: {campo: [valores]}."""
    out, i = {}, 0

    def vi(i):
        n = s = 0
        while True:
            c = b[i]
            n |= (c & 0x7F) << s
            i, s = i + 1, s + 7
            if c < 0x80:
                return n, i
    while i < len(b):
        k, i = vi(i)
        f, t = k >> 3, k & 7
        if t == 0:
            v, i = vi(i)
        else:
            ln, i = vi(i)
            v, i = b[i:i + ln], i + ln
        out.setdefault(f, []).append(v)
    return out


class OsmoNet:
    def __init__(self, w):
        self.w, self.sent, self.sims = w, [], 0
        self.uosmo, self.tok, self.out, self.code = 50_000_000, 0, 57_601_000, 0
        self.route = None

    async def get(self, url, params=None, headers=None, timeout=None):
        if "/router/quote" in url:
            sell = "tokenOutDenom=uosmo" in url
            amt = int(url.split("tokenIn=")[1].split("u")[0].split("ibc")[0])
            r = self.route or [{"pools": [{"id": 3, "token_out_denom": "uosmo" if sell else AKT}], "in_amount": str(amt)}]
            return Resp({"amount_out": "5040000" if sell else str(self.out), "route": r, "price_impact": "-0.002", "effective_fee": "0.008"})
        if "/tokens/metadata" in url:
            return Resp({AKT: {"decimals": 6}})
        if "/by_denom" in url:
            return Resp({"balance": {"amount": str(self.uosmo if "uosmo" in url else self.tok)}})
        if "/auth/v1beta1/accounts/" in url:
            return Resp({"account": {"address": self.w.address, "account_number": "3474754", "sequence": "3"}})
        if "/txfees/" in url:
            return Resp({"base_fee": "0.03"})
        if "/cosmos/tx/v1beta1/txs/" in url:
            raw = self.sent[-1]
            denom_in = _pb(_pb(_pb(_pb(raw)[1][0])[1][0])[2][0])[3][0]                 # a moeda que a mensagem paga
            got = f"{self.out}{AKT}" if denom_in == b"uosmo" else "5040000uosmo"
            return Resp({"tx_response": {"code": self.code, "raw_log": "", "tx": {"auth_info": {"fee": {"amount": [{"denom": "uosmo", "amount": "4000"}]}}},
                                         "events": [{"type": "transfer", "attributes": [{"key": "recipient", "value": self.w.address}, {"key": "amount", "value": got}]},
                                                    {"type": "transfer", "attributes": [{"key": "recipient", "value": "osmo1feecollector"}, {"key": "amount", "value": "4000uosmo"}]}]}})
        if "simple/price" in url:
            return Resp({"osmosis": {"usd": 0.2}})
        raise AssertionError(url)

    async def post(self, url, json=None, headers=None, timeout=None):
        raw = base64.b64decode(json["tx_bytes"])
        t = _pb(raw)
        body, auth, sig = t[1][0], t[2][0], t[3][0]
        doc = O.sign_doc(body, auth, 3474754)
        pk = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256K1(), self.w.pub)
        pk.verify(utils.encode_dss_signature(int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big")),
                  hashlib.sha256(doc).digest(), ec.ECDSA(utils.Prehashed(hashes.SHA256())))         # assinado pela carteira certa, para esta conta
        msgs = _pb(body)[1]
        assert len(msgs) == 1 and _pb(msgs[0])[1][0] == O.MSG_SWAP.encode()                         # uma mensagem só: a troca
        m = _pb(_pb(msgs[0])[2][0])
        assert m[1][0] == self.w.address.encode()                                                    # quem paga e recebe é a própria carteira
        if url.endswith("/simulate"):
            self.sims += 1
            return Resp({"gas_info": {"gas_used": "180000"}})
        self.sent.append(raw)
        return Resp({"tx_response": {"code": 0, "txhash": O.tx_hash(raw)}})


def osmo_setup():
    w = O.Wallet(FRASE)
    net = OsmoNet(w)
    b, _, db = setup(net)
    b.watch.addr = {"tok-cg": {"osmosis": AKT}}
    b.watch.plat = {"tok-cg": ["osmosis"]}
    b.watch.rows["tok-cg"]["current_price"] = 0.035
    run(b.save_wallet(UID, "osmosis", FRASE.upper(), SENHA))
    run(b.set_on(UID, True, SENHA, "LIGAR"))
    return b, net, db, w


def test_osmosis_wallet_from_phrase_and_denoms_keep_their_case():
    b, net, db, w = osmo_setup()
    rows = {r["rede"]: r for r in db.tables["dormant_wallets"]}
    assert rows["osmosis"]["endereco"] == w.address
    assert db_.buyable(b.watch, "tok-cg") == ["osmosis"]
    assert db_.valid_token("osmosis", AKT) and not db_.valid_token("osmosis", AKT.lower()) and not db_.valid_token("osmosis", "uosmo")


def test_buy_builds_signs_and_reads_what_arrived():
    b, net, db, w = osmo_setup()
    p = run(b.preview(UID, "tok", "osmosis", 10))
    assert p.get("quote_id"), p["bloqueia"]
    assert p["dex"] == "Osmosis" and p["recebe"] == 57.601 and p["minimo"] == round(57.601 * 0.97, 6)
    r = run(b.buy(UID, p["quote_id"], SENHA, "COMPRAR"))
    assert net.sims == 1 and len(net.sent) == 1
    m = _pb(_pb(_pb(_pb(net.sent[0])[1][0])[1][0])[2][0])
    assert m[3][0] == b"uosmo" and int(m[4][0]) == int(57_601_000 * 0.97)                          # mínimo a receber dentro da transação
    assert r["status"] == "confirmada" and r["qty"] == 57.601 and r["tx"] == O.tx_hash(net.sent[0])


def test_route_that_does_not_end_in_the_token_or_misses_value_is_refused():
    b, net, db, w = osmo_setup()
    for bad in ([{"pools": [{"id": 3, "token_out_denom": "ibc/" + "0" * 64}], "in_amount": "10000000"}],
                [{"pools": [{"id": 3, "token_out_denom": AKT}], "in_amount": "9000000"}]):
        net.route = bad
        p = run(b.preview(UID, "tok", "osmosis", 10))
        assert not p.get("quote_id") and p["bloqueia"]
    assert net.sent == []


def test_price_worse_than_the_slippage_sends_nothing():
    b, net, db, w = osmo_setup()
    p = run(b.preview(UID, "tok", "osmosis", 10))
    net.out = 50_000_000
    try:
        run(b.buy(UID, p["quote_id"], SENHA, "COMPRAR"))
        raise AssertionError("comprou com preço pior")
    except db_.BuyError as e:
        assert "folga" in str(e)
    assert net.sent == []


def test_sell_sends_the_token_and_reads_the_osmo_received():
    b, net, db, w = osmo_setup()
    p = run(b.preview(UID, "tok", "osmosis", 10))
    run(b.buy(UID, p["quote_id"], SENHA, "COMPRAR"))
    net.tok = 57_601_000
    row = db.tables["dormant_buys"][0]
    q = run(b.preview_sell(UID, row["id"], 50))
    assert q.get("quote_id"), q["bloqueia"]
    assert q["vende"] == 28.8005
    r = run(b.sell(UID, q["quote_id"], SENHA, "VENDER"))
    m = _pb(_pb(_pb(_pb(net.sent[1])[1][0])[1][0])[2][0])
    assert m[3][0] == AKT.encode() and int(_pb(m[2][0])[2][0]) == 28_800_500
    assert r["status"] == "confirmada" and r["nativo_out"] == 5.04, r
