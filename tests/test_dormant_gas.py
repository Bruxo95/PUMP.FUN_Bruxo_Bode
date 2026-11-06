"""0.32.244 (pedido do dono): abastecer de gás uma carteira a partir de outra rede, pela Relay. Sem internet: tudo falso."""
import asyncio
import pathlib

from app import dormant_buy as db_, dormant_gas as g, evm
from tests.test_dormant_compra import ADDR, KEY, SENHA, UID, OUTRO, FakeNet, Resp, rlp_list, setup

g.ENTREGA_PASSO = 0
g.ENTREGA_S = 1
db_.RECIBO_PASSO = 0
SOLA = "vines1vzrYbzLMRdu58ou5XTby4qAqVRLmqo36NKPTg"
# Solana exige solders para a chave; aqui o destino é outra rede EVM (mesmo endereço) ou uma linha direta no banco
PRECOS = {"ethereum": {"usd": 2000.0}, "binancecoin": {"usd": 500.0}, "solana": {"usd": 100.0}}


class RelayNet(FakeNet):
    def __init__(self):
        super().__init__()
        self.mexe = lambda js: js
        self.saida = 0.0099                    # 0,0099 BNB = US$ 4,95 por US$ 5
        self.estado = "success"
        self.quotes = 0

    async def get(self, url, params=None, headers=None, timeout=None):
        if "simple/price" in url:
            return Resp({k: v for k, v in PRECOS.items() if k == (params or {}).get("ids")})
        if "intents/status" in url:
            return Resp({"status": self.estado})
        return await super().get(url, params=params, headers=headers, timeout=timeout)

    async def post(self, url, json=None, headers=None, timeout=None):
        if "relay.link" in url:
            self.quotes += 1
            b = json
            data = g.SEL_DEPOSIT + evm.w_addr(b["user"]) + evm.w_int(self.quotes + 7)
            js = {"requestId": "0x" + "ab" * 32, "steps": [{"id": "deposit", "kind": "transaction", "requestId": "0x" + "ab" * 32, "items": [
                {"data": {"to": g.DEPOSITORY, "from": b["user"], "value": b["amount"], "chainId": b["originChainId"], "data": data}}]}],
                  "details": {"recipient": b["recipient"], "sender": b["user"], "currencyOut": {"amountFormatted": str(self.saida)}, "timeEstimate": 1}}
            return Resp(self.mexe(js))
        if json["method"] == "eth_chainId":                  # cada RPC responde a própria rede
            return Resp({"result": hex(next(c["id"] for c in db_.CHAINS.values() if c.get("rpc") == url))})
        return await super().post(url, json=json, headers=headers, timeout=timeout)


def run(c):
    return asyncio.run(c)


def ready(net=None):
    b, net, db = setup(net or RelayNet())
    run(b.save_wallet(UID, "ethereum", KEY, SENHA, todas_evm=True))
    run(b.set_on(UID, True, SENHA, "LIGAR"))
    return g.GasFiller(b), b, net, db


def test_deposit_is_exactly_the_fixed_contract_with_own_wallet():
    f, b, net, db = ready()
    p = run(f.preview(UID, "binance-smart-chain", "base", 5))
    assert p.get("quote_id"), p["bloqueia"]
    assert p["taxa_pct"] == 1.0 and p["recebedor"] == ADDR
    r = run(f.fill(UID, p["quote_id"], SENHA, "ABASTECER"))
    assert r["status"] == "confirmada"
    assert len(net.sent) == 1
    t = rlp_list(bytes.fromhex(net.sent[0][1][2:]))
    assert "0x" + t[3].hex() == g.DEPOSITORY and int.from_bytes(t[4], "big") == int(5 / 2000 * 1e18)
    assert (int.from_bytes(t[6], "big") - 35) // 2 == 8453              # assinada para a rede de origem
    assert t[5].hex()[:8] == g.SEL_DEPOSIT[2:] and "095ea7b3" not in t[5].hex()
    assert KEY not in str(db.tables["dormant_gas"]) and SENHA not in str(db.tables["dormant_gas"])
    assert run(b.spent_today(UID)) == 5.0                                # conta no limite do dia


def test_any_tampering_by_the_api_is_refused_and_nothing_is_signed():
    ruins = [lambda j: j["steps"][0]["items"][0]["data"].update(to="0x" + "99" * 20),
             lambda j: j["steps"][0]["items"][0]["data"].update(value="999999999999999999"),
             lambda j: j["steps"][0]["items"][0]["data"].update(chainId=1),
             lambda j: j["steps"][0]["items"][0]["data"].update(data=db_.SEL_APPROVE + evm.w_addr(g.DEPOSITORY) + evm.w_int(1)),
             lambda j: j["steps"][0]["items"][0]["data"].update(data=g.SEL_DEPOSIT + evm.w_addr("0x" + "99" * 20) + evm.w_int(1)),
             lambda j: j["steps"].insert(0, {"id": "approve", "kind": "transaction", "items": []}),
             lambda j: j["steps"][0].update(id="swap"),
             lambda j: j["details"].update(recipient="0x" + "99" * 20),
             lambda j: j["details"].update(currencyOut={}),
             lambda j: j.update(requestId="x") or j["steps"][0].update(requestId="x")]
    for ruim in ruins:
        net = RelayNet()

        def mexe(js, r=ruim):
            r(js)
            return js
        net.mexe = mexe
        f, b, net, _ = ready(net)
        try:
            run(f.preview(UID, "binance-smart-chain", "base", 5))
            raise AssertionError("passou")
        except db_.BuyError as e:
            assert "recusado" in str(e)
        assert not net.sent


def test_tampering_at_confirm_time_also_refused():
    f, b, net, _ = ready()
    p = run(f.preview(UID, "binance-smart-chain", "base", 5))

    def mexe(js):
        js["steps"][0]["items"][0]["data"]["to"] = "0x" + "99" * 20
        return js
    net.mexe = mexe
    try:
        run(f.fill(UID, p["quote_id"], SENHA, "ABASTECER"))
        raise AssertionError
    except db_.BuyError:
        pass
    assert not net.sent


def test_only_own_registered_wallets_and_allowed_origins():
    f, b, net, db = ready()
    for dest, orig in (("solana", "base"), ("base", "base"), ("base", "polygon-pos"), ("base", "avalanche"), ("tron", "base"), ("base", "solana")):
        try:
            run(f.preview(UID, dest, orig, 5))
            raise AssertionError((dest, orig))
        except db_.BuyError:
            pass
    try:
        run(f.preview(OUTRO, "binance-smart-chain", "base", 5))
        raise AssertionError
    except db_.BuyError as e:
        assert "carteira" in str(e)
    assert not net.sent


def test_polygon_and_avalanche_can_receive():
    f, _, _, _ = ready()
    assert "polygon-pos" not in g.ORIGENS and "avalanche" not in g.ORIGENS and "polygon-pos" in g.RELAY_ID and "avalanche" in g.RELAY_ID and g.RELAY_ID["solana"] == 792703809


def test_limits_and_expensive_fee_block():
    net = RelayNet()
    f, b, net, _ = ready(net)
    p = run(f.preview(UID, "binance-smart-chain", "base", 30))
    assert not p.get("quote_id") and any("teto" in x for x in p["bloqueia"])
    net.saida = 0.008                          # US$ 4 por US$ 5 = 20%
    p = run(f.preview(UID, "binance-smart-chain", "base", 5))
    assert not p.get("quote_id") and any("cara demais" in x for x in p["bloqueia"])
    net.saida = 0.0096                         # 4%
    p = run(f.preview(UID, "binance-smart-chain", "base", 5))
    assert p.get("quote_id") and any("taxa está" in x for x in p["avisos"])
    run(b.set_on(UID, False))
    assert any("desligadas" in x for x in run(f.preview(UID, "binance-smart-chain", "base", 5))["bloqueia"])


def test_needs_word_password_single_use_and_not_usable_as_buy_or_sell():
    f, b, net, _ = ready()
    p = run(f.preview(UID, "binance-smart-chain", "base", 5))
    for senha, w in ((SENHA, "COMPRAR"), ("errada-errada", "ABASTECER")):
        try:
            run(f.fill(UID, p["quote_id"], senha, w))
            raise AssertionError
        except db_.BuyError:
            pass
    for fn, w in ((b.buy, "COMPRAR"), (b.sell, "VENDER")):
        try:
            run(fn(UID, p["quote_id"], SENHA, w))
            raise AssertionError
        except db_.BuyError:
            pass
    assert not net.sent
    run(f.fill(UID, p["quote_id"], SENHA, "ABASTECER"))
    try:
        run(f.fill(UID, p["quote_id"], SENHA, "ABASTECER"))
        raise AssertionError
    except db_.BuyError:
        pass
    assert len(net.sent) == 1


def test_refund_and_pending_are_reported_and_pending_blocks_next():
    net = RelayNet()
    net.estado = "refund"
    f, b, net, _ = ready(net)
    p = run(f.preview(UID, "binance-smart-chain", "base", 5))
    assert run(f.fill(UID, p["quote_id"], SENHA, "ABASTECER"))["status"] == "devolvida"
    net.estado = "pending"
    p = run(f.preview(UID, "binance-smart-chain", "arbitrum-one", 5))
    assert run(f.fill(UID, p["quote_id"], SENHA, "ABASTECER"))["status"] == "pendente"
    p = run(f.preview(UID, "binance-smart-chain", "arbitrum-one", 5))
    assert not p.get("quote_id") and any("sem confirmação" in x for x in p["bloqueia"])


def test_status_tells_which_wallet_has_no_gas():
    net = RelayNet()
    net.bal = 0
    f, _, _, _ = ready(net)
    s = run(f.status(UID))["redes"]
    assert s["ethereum"]["estado"] == "sem" and s["ethereum"]["pode_origem"] is False
    net.bal = 10 ** 18
    s = run(f.status(UID))["redes"]
    assert s["ethereum"]["estado"] == "ok" and s["ethereum"]["pode_origem"] is True and s["polygon-pos"]["pode_origem"] is False
    assert s["ethereum"]["sugestao_usd"] <= g.GAS_MAX_USD


def test_buy_message_points_to_refuel_and_migration_is_closed():
    assert "Abastecer" in pathlib.Path("app/dormant_buy.py").read_text(encoding="utf-8")
    sql = pathlib.Path("supabase/migrations/20261106000003_dormant_gas.sql").read_text(encoding="utf-8")
    assert "enable row level security" in sql and "revoke all on public.dormant_gas from anon, authenticated" in sql and "create policy" not in sql
