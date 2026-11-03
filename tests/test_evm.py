"""0.32.172: assinatura da BNB (app/evm.py) conferida com vetores oficiais — sem isso nenhuma transação real sai certa."""
from app import evm


def test_keccak_known_vectors():
    assert evm.keccak256(b"").hex() == "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
    assert evm.selector("Transfer(address,address,uint256)") == "0xddf252ad"
    assert evm.selector("buyTokenAMAP(address,uint256,uint256)") == "0x87f27655"     # visto em compras reais (03/11)
    assert evm.selector("sellToken(address,uint256,uint256)") == "0x3e11741f"        # visto em vendas reais (03/11)


def test_address_of_key_one():
    assert evm.address_of(1) == "0x7e5f4552091a69125d5dfcb7b8c2659029395bdf"


def test_eip155_example_transaction():
    key = evm.parse_key("0x" + "46" * 32)
    assert evm.address_of(key) == "0x9d8a62f656a8d1615c1294fd71e9cfb3e4855a4f"
    raw, _ = evm.sign_tx(key, 9, 20 * 10 ** 9, 21000, "0x" + "35" * 20, 10 ** 18, "0x", 1)
    assert raw == ("0xf86c098504a817c800825208943535353535353535353535353535353535353535880de0b6b3a76400008025a028ef61340bd939bc2195fe5"
                   "37567866003e1a15d3c71ff63e1590620aa636276a067cbe9d8997f761aecb703304b3800ccf555c9f3dc64214b297fb1966a3b6d83")


def test_parse_key_rejects_garbage():
    import pytest
    for bad in ("", "abc", "0x" + "zz" * 32, "0" * 64):
        with pytest.raises(ValueError):
            evm.parse_key(bad)


def test_call_data_with_address_array():
    d = evm.call_data("0x791ac947", 5, 1, ["0x" + "11" * 20, "0x" + "22" * 20], "0x" + "33" * 20, 99)
    w = [d[10 + 64 * i:10 + 64 * (i + 1)] for i in range((len(d) - 10) // 64)]
    assert int(w[2], 16) == 160 and int(w[5], 16) == 2 and w[6].endswith("11" * 20) and w[7].endswith("22" * 20)
