"""0.32.257 (pedido do dono, 07/11/2026): Dormant compra pela Uniswap V4 na Robinhood (inclusive a Pons) e copia a chave EVM para as
redes sem carteira. Sem internet: rede, GeckoTerminal e banco falsos. Nada é assinado nem enviado."""
import pathlib

from app import dormant_buy as db_, evm
from tests.test_dormant_compra import ADDR, KEY, SENHA, UID, FakeNet, Resp, run, setup

GLC = "0xaf0172ddea4ce60db3ebab05748a00b14fc8e433"
HOOK = "0xe5e702641ea86f4ae6cc3cdaed2b886f976be044"
KEY_GLC = [db_.ZERO, GLC, 0, 200, HOOK]
PID = "0x70028c45e0efeea7c73d9144310f8f5cd76a7e0a0e03f945cf21b59dc55ac955"
# compra real de GLC no site da Pons em 07/11/2026 (tx 0x7d5bf818…): o robô tem que montar exatamente isto
REAL = pathlib.Path(__file__).with_name("dados_v4_glc.txt").read_text().strip()


def init_log(key, pid):
    c0, c1, fee, ts, hooks = key
    return {"topics": [db_.T_V4_INIT, pid, "0x" + c0[2:].rjust(64, "0"), "0x" + c1[2:].rjust(64, "0")],
            "data": "0x" + evm.w_int(fee) + evm.w_int(ts) + evm.w_addr(hooks) + evm.w_int(1) + evm.w_int(0)}


class V4Net(FakeNet):
    def __init__(self, logs=None):
        super().__init__()
        self.chain = 4663
        self.logs = logs if logs is not None else [init_log(KEY_GLC, PID)]
        self.calls = []

    async def get(self, url, params=None, headers=None, timeout=None):
        if "geckoterminal" in url:
            return Resp({"data": [{"attributes": {"address": PID, "pool_created_at": "2026-08-28T01:47:31Z", "reserve_in_usd": "9199.78"},
                                   "relationships": {"base_token": {"data": {"id": "robinhood_" + GLC}},
                                                     "quote_token": {"data": {"id": "robinhood_" + db_.ZERO}},
                                                     "dex": {"data": {"id": "pons-v2-dex"}}}},
                                  {"attributes": {"address": "0x" + "cd" * 20, "reserve_in_usd": "50"},     # par V2 comum: não é V4
                                   "relationships": {"base_token": {"data": {"id": "robinhood_" + GLC}},
                                                     "quote_token": {"data": {"id": "robinhood_" + db_.ZERO}}, "dex": {"data": {"id": "pons-v2"}}}}]})
        return await super().get(url, params, headers, timeout)

    async def post(self, url, json=None, headers=None, timeout=None):
        m, p = json["method"], json["params"]
        self.calls.append(m)
        if m == "eth_blockNumber":
            return Resp({"result": hex(2_000_000_000)})
        if m == "eth_getBlockByNumber":
            return Resp({"result": {"timestamp": p[0]}})                 # bloco N tem hora N: a busca binária acha a data do pool
        if m == "eth_getLogs":
            assert p[0]["address"] == db_.V4["robinhood"]["pm"] and p[0]["topics"] == [db_.T_V4_INIT, PID]
            return Resp({"result": self.logs})
        if m == "eth_call" and p[0]["to"] == db_.V4["robinhood"]["quoter"]:
            assert p[0]["data"].startswith(db_.SEL_V4_QUOTE)
            return Resp({"result": "0x" + evm.w_int(199_701 * 10 ** 18) + evm.w_int(80000)})
        return await super().post(url, json, headers, timeout)


def test_v4_order_is_identical_to_the_real_glc_buy():
    assert db_.v4_data(KEY_GLC, 0x430116bede019, 0x2f64b56b288a02b2587c, 1794053713) == REAL
    assert db_.v4_pool_id(KEY_GLC) == PID
    assert db_.v4_key_from_log(init_log(KEY_GLC, PID)) == KEY_GLC


def test_v4_route_found_quoted_and_sent_only_to_the_official_router():
    b, net, _ = setup(V4Net())
    rt = run(b.evm_best("robinhood", GLC, 10 ** 15))
    assert rt["tipo"] == "v4" and rt["dex"] == "Pons (Uniswap V4)" and rt["hook"] and rt["out"] == 199_701 * 10 ** 18
    q = {"rede": "robinhood", "token": GLC, "value": 10 ** 15, "route": {k: v for k, v in rt.items() if k != "out"}}
    to, data = b._evm_tx(q, 10, ADDR)
    assert to == "0x8876789976decbfcbbbe364623c63652db8c0904" and data.startswith(db_.SEL_UR_EXEC)
    n = net.calls.count("eth_getLogs")
    run(b.evm_best("robinhood", GLC, 10 ** 15))
    assert net.calls.count("eth_getLogs") == n                           # chave do pool guardada: não busca de novo


def test_v4_pool_with_wrong_key_or_unchecked_key_never_builds_an_order():
    errado = [db_.ZERO, GLC, 3000, 60, HOOK]                             # evento que não dá o id do pool
    b, _, _ = setup(V4Net(logs=[init_log(errado, PID)]))
    rt = run(b.evm_best("robinhood", GLC, 10 ** 15))
    assert rt is None or rt["tipo"] != "v4"
    b2, _, _ = setup(V4Net())
    q = {"rede": "robinhood", "token": GLC, "value": 10 ** 15, "route": {"tipo": "v4", "rede": "robinhood", "key": KEY_GLC}}
    try:
        b2._evm_tx(q, 10, ADDR)                                          # nunca passou pela conferência na rede
        raise AssertionError("montou ordem com pool não conferido")
    except db_.BuyError as e:
        assert "não conferido" in str(e)


def test_copy_evm_key_fills_only_the_missing_chains():
    b, _, db = setup()
    run(b.save_wallet(UID, "ethereum", KEY, SENHA))
    run(b.save_wallet(UID, "base", KEY, SENHA))
    try:
        run(b.copy_evm(UID, "errada-errada"))
        raise AssertionError
    except db_.BuyError as e:
        assert "errada" in str(e)
    antes = {r["rede"]: r["cifra"] for r in db.tables["dormant_wallets"]}
    r = run(b.copy_evm(UID, SENHA))
    assert r["endereco"] == ADDR and set(r["redes"]) == set(db_.EVM_CHAINS) - {"ethereum", "base"}
    rows = {x["rede"]: x for x in db.tables["dormant_wallets"]}
    assert set(rows) == set(db_.EVM_CHAINS) and all(x["endereco"] == ADDR for x in rows.values())
    assert rows["ethereum"]["cifra"] == antes["ethereum"]                # quem já tinha não muda
    assert run(b._open(UID, rows["robinhood"], SENHA)) == KEY
    assert run(b.copy_evm(UID, SENHA))["redes"] == []                    # de novo: nada a copiar


def test_copy_evm_needs_an_evm_wallet_first():
    b, _, _ = setup()
    try:
        run(b.copy_evm(UID, SENHA))
        raise AssertionError
    except db_.BuyError as e:
        assert "EVM primeiro" in str(e)
