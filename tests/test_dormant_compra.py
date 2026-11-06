"""0.32.242 (pedido do dono): comprar na DEX pelo Dormant, com chaves privadas guardadas. Sem internet: rede e banco falsos.
Nada aqui assina com chave de verdade: a chave 1 é o vetor público usado nos testes de secp256k1."""
import asyncio
import base64
import os
import pathlib
import time

from app import dormant, dormant_buy as db_, dormant_vault as vault, evm
from app.crypto import SecretBox
from tests.fakes import FakeREST

UID, OUTRO = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
KEY = "0x" + "0" * 63 + "1"
ADDR = "0x7e5f4552091a69125d5dfcb7b8c2659029395bdf"
TOKEN = "0x" + "ab" * 20
SENHA = "cavalo-azul-77"
ETH = db_.CHAINS["ethereum"]
db_.RECIBO_PASSO = 0


class Resp:
    def __init__(self, js, status=200):
        self._js, self.status_code = js, status

    def json(self):
        return self._js


class FakeNet:
    """Rede EVM + CoinGecko + GoPlus. Guarda o que seria enviado; nada sai daqui."""

    def __init__(self):
        self.sent, self.out, self.bal, self.gp_data, self.chain, self.est_error = [], 1000 * 10 ** 18, 10 ** 18, {"is_honeypot": "0", "buy_tax": "0", "sell_tax": "0"}, 1, None
        self.gas = 10 ** 9
        self.status = "0x1"

    async def get(self, url, params=None, headers=None, timeout=None):
        if "gopluslabs" in url:
            return Resp({"result": {TOKEN: self.gp_data}})
        return Resp({"ethereum": {"usd": 2000.0}})                         # /simple/price

    async def post(self, url, json=None, headers=None, timeout=None):
        m, p = json["method"], json["params"]
        def ok(v):
            return Resp({"result": v})
        if m == "eth_chainId":
            return ok(hex(self.chain))
        if m == "eth_gasPrice":
            return ok(hex(self.gas))
        if m == "eth_getBalance":
            return ok(hex(self.bal))
        if m == "eth_getTransactionCount":
            return ok("0x5")
        if m == "eth_estimateGas":
            return Resp({"error": {"message": self.est_error}}) if self.est_error else ok(hex(200000))
        if m == "eth_sendRawTransaction":
            self.sent.append((url, p[0]))
            return ok("0xhash")
        if m == "eth_getTransactionReceipt":
            return ok({"status": self.status, "gasUsed": hex(200000), "effectiveGasPrice": hex(self.gas), "transactionHash": p[0],
                       "logs": [{"address": TOKEN, "topics": [db_.T_TRANSFER, "0x" + "0" * 64, "0x" + ADDR[2:].rjust(64, "0")], "data": hex(self.out)}]})
        if m == "eth_call":
            data = p[0]["data"]
            if data.startswith(db_.SEL_AMOUNTS) and p[0]["to"] == ETH["router"]:
                n = evm.words("0x" + data[10:])[0]
                path_len = evm.words("0x" + data[10:])[2]
                if path_len != 2:
                    return Resp({"error": {"message": "sem par"}})
                # pool fundo: preço igual para valor pequeno e grande; self.out vale para 0,01 ETH
                got = self.out * n // 10 ** 16
                return ok("0x" + evm.w_int(32) + evm.w_int(2) + evm.w_int(n) + evm.w_int(got))
            if data.startswith(db_.SEL_DECIMALS):
                return ok("0x" + evm.w_int(18))
            return Resp({"error": {"message": "execution reverted"}})
        raise AssertionError(m)


def rlp_list(b: bytes) -> list[bytes]:
    def item(i):
        c = b[i]
        if c < 0x80:
            return b[i:i + 1], i + 1
        if c <= 0xb7:
            n = c - 0x80
            return b[i + 1:i + 1 + n], i + 1 + n
        ll = c - 0xb7
        n = int.from_bytes(b[i + 1:i + 1 + ll], "big")
        return b[i + 1 + ll:i + 1 + ll + n], i + 1 + ll + n
    i = 1 if b[0] < 0xf8 else 1 + b[0] - 0xf7
    out = []
    while i < len(b):
        v, i = item(i)
        out.append(v)
    return out


def setup(net=None):
    net = net or FakeNet()
    db = FakeREST()
    w = dormant.DormantWatch(net, db)
    w.lista = [{"cmc": "tok", "nome": "Tok"}]
    w.map, w.pick = {"tok": ["tok-cg"]}, {"tok": "tok-cg"}
    w.rows = {"tok-cg": {"id": "tok-cg", "name": "Tok", "symbol": "tok", "current_price": 0.02}}
    w.addr = {"tok-cg": {"ethereum": TOKEN, "tron": "TXYZabc"}}
    w.plat = {"tok-cg": ["ethereum", "tron"]}
    box = SecretBox(base64.b64encode(os.urandom(32)).decode())
    b = db_.Buyer(net, db, box, w, allowed=lambda: True)
    return b, net, db


async def ready(b):
    await b.save_wallet(UID, "ethereum", KEY, SENHA)
    await b.set_on(UID, True, SENHA, "LIGAR")


def run(c):
    return asyncio.run(c)


# ------------------------------------------------------------------ cofre
def test_vault_needs_the_password_and_is_bound_to_user_chain_and_address():
    box = SecretBox(base64.b64encode(os.urandom(32)).decode())
    blob = vault.seal(box, UID, "ethereum", ADDR, KEY, SENHA)
    assert KEY not in blob and SENHA not in blob
    assert vault.unseal(box, UID, "ethereum", ADDR, blob, SENHA) == KEY
    for args in ((UID, "ethereum", ADDR, blob, "senha-errada-1"), (UID, "ethereum", "0xoutro", blob, SENHA)):
        try:
            vault.unseal(box, *args)
            raise AssertionError("abriu sem poder")
        except vault.WrongPassword:
            pass
    from app.crypto import CryptoError
    for args in ((OUTRO, "ethereum", ADDR, blob, SENHA), (UID, "base", ADDR, blob, SENHA)):
        try:
            vault.unseal(box, *args)
            raise AssertionError("abriu noutra conta ou rede")
        except CryptoError:
            pass
    other = SecretBox(base64.b64encode(os.urandom(32)).decode())    # banco vazado sem a chave mestra
    try:
        vault.unseal(other, UID, "ethereum", ADDR, blob, SENHA)
        raise AssertionError("abriu com outra chave mestra")
    except CryptoError:
        pass


def test_weak_password_refused():
    assert vault.check_new_password("curta")
    assert vault.check_new_password("aaaaaaaaaaaa")
    assert vault.check_new_password(SENHA) is None


# ------------------------------------------------------------------ carteiras
def test_key_never_stored_in_clear_nor_returned():
    b, _, db = setup()
    r = run(b.save_wallet(UID, "ethereum", KEY, SENHA))
    assert r == {"endereco": ADDR, "redes": ["ethereum"]}
    assert KEY not in str(db.tables["dormant_wallets"]) and KEY[2:] not in str(db.tables["dormant_wallets"]) and SENHA not in str(db.tables)
    pub = run(b.wallets(UID))
    assert KEY not in str(pub) and "cifra" not in str(pub) and pub["tem_senha"] is True
    assert next(x for x in pub["redes"] if x["rede"] == "ethereum")["endereco"] == ADDR


def test_bad_key_error_does_not_echo_the_value():
    b, _, _ = setup()
    bad = "z" * 64
    try:
        run(b.save_wallet(UID, "ethereum", bad, SENHA))
        raise AssertionError
    except db_.BuyError as e:
        assert bad not in str(e)


def test_second_wallet_needs_same_password_and_all_evm_option():
    b, _, db = setup()
    run(b.save_wallet(UID, "ethereum", KEY, SENHA))
    try:
        run(b.save_wallet(UID, "base", KEY, "outra-senha-99"))
        raise AssertionError
    except db_.BuyError as e:
        assert "errada" in str(e)
    r = run(b.save_wallet(UID, "ethereum", KEY, SENHA, todas_evm=True))
    assert set(r["redes"]) == set(db_.EVM_CHAINS) and len(db.tables["dormant_wallets"]) == 6


def test_wallets_are_per_account():
    b, _, _ = setup()
    run(b.save_wallet(UID, "ethereum", KEY, SENHA))
    assert all(not x["endereco"] for x in run(b.wallets(OUTRO))["redes"])
    assert run(b.wallet_row(OUTRO, "ethereum")) is None


def test_lock_after_five_wrong_passwords_survives_restart_and_right_one_resets():
    b, _, db = setup()
    run(b.save_wallet(UID, "ethereum", KEY, SENHA))
    wal = run(b.wallet_row(UID, "ethereum"))
    for i in range(4):
        try:
            run(b._open(UID, wal, "errada-errada"))
        except db_.BuyError:
            pass
    assert run(b._open(UID, wal, SENHA)) == KEY                     # a certa zera a conta
    assert db.tables["dormant_buy_cfg"][0]["erros"] == 0
    for i in range(5):
        try:
            run(b._open(UID, wal, "errada-errada"))
        except db_.BuyError:
            pass
    b2 = db_.Buyer(b.http, db, b.box, b.watch, allowed=lambda: True)  # "reiniciou o servidor"
    try:
        run(b2._open(UID, wal, SENHA))
        raise AssertionError("abriu travado")
    except db_.BuyError as e:
        assert "travado" in str(e)


def test_change_password_reencrypts_all_or_nothing():
    b, _, db = setup()
    run(b.save_wallet(UID, "ethereum", KEY, SENHA, todas_evm=True))
    antes = str(db.tables["dormant_wallets"])
    try:
        run(b.change_password(UID, "errada-errada", "senha-nova-123"))
        raise AssertionError
    except db_.BuyError:
        pass
    assert str(db.tables["dormant_wallets"]) == antes
    assert run(b.change_password(UID, SENHA, "senha-nova-123")) == 6
    assert run(b._open(UID, run(b.wallet_row(UID, "base")), "senha-nova-123")) == KEY


# ------------------------------------------------------------------ travas
def test_starts_off_and_turning_on_needs_password_and_word():
    b, _, _ = setup()
    assert run(b.cfg(UID))["on"] is False
    run(b.save_wallet(UID, "ethereum", KEY, SENHA))
    for senha, word in ((SENHA, ""), ("errada-errada", "LIGAR")):
        try:
            run(b.set_on(UID, True, senha, word))
            raise AssertionError
        except db_.BuyError:
            pass
    assert run(b.cfg(UID))["on"] is False
    assert run(b.set_on(UID, True, SENHA, "LIGAR"))["on"] is True
    assert run(b.set_on(UID, False))["on"] is False                 # desligar não pede nada


def test_limits_cannot_turn_on_and_raising_needs_password():
    b, _, _ = setup()
    run(b.save_wallet(UID, "ethereum", KEY, SENHA))
    assert run(b.save_limits(UID, {"on": True, "max_usd": 10}, ""))["on"] is False     # baixar é livre, "on" é ignorado
    try:
        run(b.save_limits(UID, {"max_usd": 5000}, ""))
        raise AssertionError
    except db_.BuyError:
        pass
    assert run(b.save_limits(UID, {"max_usd": 999999, "slip_pct": 99}, SENHA)) == {**db_.CFG_DEFAULT, "max_usd": 10000.0, "slip_pct": 15.0}


def test_preview_blocks_without_quote_when_anything_is_missing():
    b, _, _ = setup()
    p = run(b.preview(UID, "tok", "ethereum", 0.01))
    assert not p.get("quote_id") and any("desligadas" in x for x in p["bloqueia"]) and any("carteira" in x for x in p["bloqueia"])
    run(ready(b))
    b.allowed = lambda: False
    p = run(b.preview(UID, "tok", "ethereum", 0.01))
    assert not p.get("quote_id") and any("PUMP_REAL_ALLOWED" in x for x in p["bloqueia"])
    b.allowed = lambda: True
    p = run(b.preview(UID, "tok", "ethereum", 0.5))                 # US$ 1.000 > limite de US$ 50
    assert not p.get("quote_id") and any("limite por compra" in x for x in p["bloqueia"])


def test_only_chains_with_safe_dex_are_buyable():
    b, _, _ = setup()
    assert db_.buyable(b.watch, "tok-cg") == ["ethereum"]           # TRON fica de fora
    for bad in ("tron", "../x", "ethereum2"):
        try:
            run(b.preview(UID, "tok", bad, 0.01))
            raise AssertionError
        except db_.BuyError:
            pass
    for v in ("abc", -1, 0, float("nan"), float("inf"), None):
        try:
            run(b.preview(UID, "tok", "ethereum", v))
            raise AssertionError(v)
        except db_.BuyError:
            pass


def test_honeypot_and_bad_price_block():
    net = FakeNet()
    net.gp_data = {"is_honeypot": "1"}
    b, net, _ = setup(net)
    run(ready(b))
    p = run(b.preview(UID, "tok", "ethereum", 0.01))
    assert not p.get("quote_id") and any("honeypot" in x for x in p["bloqueia"])
    net.gp_data = {"sell_tax": "0.5"}
    b._gp.clear()
    assert any("taxa de venda" in x for x in run(b.preview(UID, "tok", "ethereum", 0.01))["bloqueia"])
    net.gp_data = {"is_honeypot": "0"}
    b._gp.clear()
    net.out = 500 * 10 ** 18                                        # paga o dobro da CoinGecko: pool errado ou manipulado
    p = run(b.preview(UID, "tok", "ethereum", 0.01))
    assert not p.get("quote_id") and any("acima da CoinGecko" in x for x in p["bloqueia"])


def test_failed_network_simulation_blocks():
    net = FakeNet()
    net.est_error = "execution reverted: TRANSFER_FAILED"
    b, net, _ = setup(net)
    run(ready(b))
    p = run(b.preview(UID, "tok", "ethereum", 0.01))
    assert not p.get("quote_id") and any("simulação" in x for x in p["bloqueia"]) and not net.sent


# ------------------------------------------------------------------ compra
def good_quote(b):
    run(ready(b))
    p = run(b.preview(UID, "tok", "ethereum", 0.01))
    assert p.get("quote_id"), p["bloqueia"]
    return p


def test_buy_sends_only_to_the_fixed_router_with_own_wallet_as_receiver():
    b, net, db = setup()
    p = good_quote(b)
    assert p["minimo"] == 970                                       # folga padrão de 3%
    r = run(b.buy(UID, p["quote_id"], SENHA, "COMPRAR"))
    assert r["status"] == "confirmada" and r["qty"] == 1000 and abs(r["px_in"] - 0.02) < 1e-9
    assert len(net.sent) == 1 and net.sent[0][0] == "https://rpc.flashbots.net"
    f = rlp_list(bytes.fromhex(net.sent[0][1][2:]))
    assert "0x" + f[3].hex() == ETH["router"] and int.from_bytes(f[4], "big") == 10 ** 16
    assert (int.from_bytes(f[6], "big") - 35) // 2 == 1             # chain id da Ethereum assinado
    data = f[5].hex()
    assert "0x" + data[:8] == db_.SEL_SWAP_ETH and "095ea7b3" not in data     # nada de approve
    w = evm.words("0x" + data[8:])
    assert w[0] == 970 * 10 ** 18 and "0x%040x" % w[2] == ADDR      # mínimo e recebedor = a própria carteira
    assert "0x%040x" % w[-1] == TOKEN
    linha = db.tables["dormant_buys"][0]
    assert linha["status"] == "confirmada" and linha["user_id"] == UID and KEY not in str(linha)


def test_row_is_saved_before_sending():
    b, net, db = setup()
    p = good_quote(b)
    orig = net.post
    seen = []

    async def spy(url, json=None, headers=None, timeout=None):
        if json["method"] == "eth_sendRawTransaction":
            seen.append([r["status"] for r in db.tables["dormant_buys"]])
        return await orig(url, json=json, headers=headers, timeout=timeout)
    net.post = spy
    run(b.buy(UID, p["quote_id"], SENHA, "COMPRAR"))
    assert seen == [["enviando"]]


def test_needs_word_and_password_and_wrong_ones_send_nothing():
    b, net, _ = setup()
    p = good_quote(b)
    for senha, word in ((SENHA, "comprar"), ("errada-errada", "COMPRAR"), ("", "COMPRAR"), (None, "COMPRAR")):
        try:
            run(b.buy(UID, p["quote_id"], senha, word))
            raise AssertionError
        except db_.BuyError:
            pass
    assert not net.sent


def test_quote_is_single_use_personal_and_expires():
    b, net, _ = setup()
    p = good_quote(b)
    run(b.save_wallet(OUTRO, "ethereum", KEY, SENHA))
    run(b.set_on(OUTRO, True, SENHA, "LIGAR"))
    try:
        run(b.buy(OUTRO, p["quote_id"], SENHA, "COMPRAR"))          # cotação de outra conta
        raise AssertionError
    except db_.BuyError as e:
        assert "venceu" in str(e)
    run(b.buy(UID, p["quote_id"], SENHA, "COMPRAR"))
    try:
        run(b.buy(UID, p["quote_id"], SENHA, "COMPRAR"))            # clique dobrado
        raise AssertionError
    except db_.BuyError:
        pass
    assert len(net.sent) == 1
    q = run(b.preview(OUTRO, "tok", "ethereum", 0.01))
    b.quotes[q["quote_id"]]["t"] = time.time() - db_.QUOTE_TTL_S - 1
    try:
        run(b.buy(OUTRO, q["quote_id"], SENHA, "COMPRAR"))
        raise AssertionError
    except db_.BuyError as e:
        assert "venceu" in str(e)


def test_worse_price_wrong_chain_or_gas_spike_send_nothing():
    for mexe in (lambda n: setattr(n, "out", 900 * 10 ** 18), lambda n: setattr(n, "chain", 56), lambda n: setattr(n, "gas", 10 ** 11)):
        b, net, _ = setup()
        p = good_quote(b)
        mexe(net)
        try:
            run(b.buy(UID, p["quote_id"], SENHA, "COMPRAR"))
            raise AssertionError
        except db_.BuyError as e:
            assert "nada foi enviado" in str(e)
        assert not net.sent


def test_day_limit_counts_pending_and_blocks_second_buy_while_one_is_pending():
    net = FakeNet()
    b, net, db = setup(net)
    p = good_quote(b)
    db.tables["dormant_buys"].append({"id": "x", "user_id": UID, "rede": "ethereum", "em": db_._iso(time.time()), "usd_in": 190.0, "status": "pendente"})
    assert run(b.spent_today(UID)) == 190.0
    try:
        run(b.buy(UID, p["quote_id"], SENHA, "COMPRAR"))
        raise AssertionError
    except db_.BuyError as e:
        assert "limites" in str(e)
    assert not net.sent
    p2 = run(b.preview(UID, "tok", "ethereum", 0.001))
    assert not p2.get("quote_id") and any("sem confirmação" in x for x in p2["bloqueia"])
    db.tables["dormant_buys"][0]["status"] = "falhou"               # falha não conta no dia
    assert run(b.spent_today(UID)) == 0


def test_failed_tx_is_recorded_as_failed():
    net = FakeNet()
    b, net, db = setup(net)
    p = good_quote(b)
    net.status = "0x0"
    r = run(b.buy(UID, p["quote_id"], SENHA, "COMPRAR"))
    assert r["status"] == "falhou" and db.tables["dormant_buys"][0]["status"] == "falhou"


# ------------------------------------------------------------------ histórico
def test_history_windows_and_total():
    b, _, _ = setup()
    now = time.time()
    spk = [1.0] * 168
    spk[155] = 1.6                                                  # 12 h atrás
    b.watch.rows["tok-cg"].update(current_price=2.0, sparkline_in_7d={"price": spk})
    rows = [{"id": "a", "em": db_._iso(now - 8 * 86400), "rede": "ethereum", "cg": "tok-cg", "nome": "Tok", "status": "confirmada", "qty": 10.0, "px_in": 0.5, "usd_in": 5.0, "gas_usd": 1.0, "nativo": 0.01},
            {"id": "b", "em": db_._iso(now - 1800), "rede": "ethereum", "cg": "tok-cg", "nome": "Tok", "status": "confirmada", "qty": 1.0, "px_in": 1.6, "usd_in": 1.6, "gas_usd": 0.0},
            {"id": "c", "em": db_._iso(now), "rede": "ethereum", "cg": "tok-cg", "status": "falhou", "usd_in": 99.0}]
    h = db_.holdings(rows, b.watch, now)
    a, nova = h["itens"][0], h["itens"][1]
    assert a["h1"] == 100.0 and a["h168"] == 100.0 and a["h12"] == 25.0        # 1 h atrás = 1,00; 12 h atrás = 1,60
    assert a["total"] == round((20 / 6 - 1) * 100, 2) and a["ganho"] == 14.0
    assert nova["h1"] == 25.0 and nova["h24"] == 25.0                          # comprada há 30 min: conta desde a compra
    assert h["resumo"]["investido"] == 7.6 and h["resumo"]["valor"] == 22.0      # a falha não entra
    assert h["itens"][2].get("total") is None


def test_history_of_another_account_stays_out():
    b, _, db = setup()
    db.tables["dormant_buys"].append({"id": "x", "user_id": OUTRO, "rede": "ethereum", "em": db_._iso(time.time()), "status": "confirmada", "qty": 1.0, "cg": "tok-cg", "usd_in": 1.0, "px_in": 1.0})
    assert run(b.history(UID))["itens"] == []


# ------------------------------------------------------------------ o que está no repositório
def test_migration_keeps_tables_closed():
    sql = pathlib.Path("supabase/migrations/20261106000001_dormant_compras.sql").read_text(encoding="utf-8")
    for t in ("dormant_wallets", "dormant_buy_cfg", "dormant_buys"):
        assert f"alter table public.{t} enable row level security" in sql
        assert f"revoke all on public.{t} from anon, authenticated" in sql
    assert "create policy" not in sql and "grant select" not in sql


def test_no_log_call_receives_secret_or_password():
    src = pathlib.Path("app/dormant_buy.py").read_text(encoding="utf-8") + pathlib.Path("app/dormant_api.py").read_text(encoding="utf-8")
    for line in src.splitlines():
        if "log." in line or "audit(" in line:
            for bad in ("secret", 'get("senha"', 'get("chave"', "{senha", "{chave"):
                assert bad not in line, line
