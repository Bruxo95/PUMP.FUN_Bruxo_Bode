"""0.32.467 (pedido do dono, 26/11/2026): carteira da rede MANTRA no Dormant, SÓ carteira. Sem internet: tudo falso."""
import asyncio

from app import dormant_buy as db_, dormant_gas as g
from tests.test_dormant_compra import ADDR, KEY, SENHA, UID, setup
from tests.test_dormant_gas import ready

WMANTRA = "0xe3047710ef6cb36bcf1e58145529778ea7cb5598"


def run(c):
    return asyncio.run(c)


def test_cosmos_address_is_the_same_account_checked_on_chain():
    # par conferido na rede em 26/11/2026: o saldo EVM deste contrato é igual ao saldo do banco Cosmos neste mantra1
    assert db_.cosmos_address("mantra-evm", WMANTRA) == "mantra1uvz8wy80djekhnc7tq2922th36nuk4vcahezg6"
    assert db_.cosmos_address("base", WMANTRA) is None and db_.cosmos_address("mantra-evm", None) is None


def test_ethereum_key_is_copied_to_mantra_and_shows_both_addresses():
    b, _, _ = setup()
    run(b.save_wallet(UID, "ethereum", KEY, SENHA))
    assert "mantra-evm" in run(b.copy_evm(UID, SENHA))["redes"]
    redes = {x["rede"]: x for x in run(b.wallets(UID))["redes"]}
    m = redes["mantra-evm"]
    assert m["endereco"] == ADDR and m["so_carteira"] is True and m["endereco_cosmos"].startswith("mantra1")
    assert redes["ethereum"]["so_carteira"] is False and redes["ethereum"]["endereco_cosmos"] is None


def test_nothing_can_be_bought_on_a_wallet_only_chain():
    assert db_.valid_token("mantra-evm", "0x" + "11" * 20) is False

    class W:
        addr = {"moeda": {"mantra-evm": "0x" + "11" * 20, "base": "0x" + "22" * 20}}

        def chain_of(self, cid):
            return "mantra-evm"

    assert db_.buyable(W(), "moeda") == ["base"]


def test_bridge_never_sends_gas_to_or_from_mantra():
    assert "mantra-evm" not in g.RELAY_ID and "mantra-evm" not in g.ORIGENS
    f, _, net, _ = ready()
    for chamada in (f.routes(UID, "mantra-evm"), f.preview(UID, "mantra-evm", "base", 5)):
        try:
            run(chamada)
            raise AssertionError("a ponte aceitou a MANTRA")
        except db_.BuyError as e:
            assert "não leva gás" in str(e)
    assert net.quotes == 0 and not net.sent
