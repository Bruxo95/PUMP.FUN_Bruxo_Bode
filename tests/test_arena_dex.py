"""0.32.397 (pedido do dono): Arena DEX como segundo DEX V2 da Avalanche. Sem internet."""
from app import dormant_buy as d

ARENA = "0xf56d524d651b90e4b84dc2fffd83079698b9066e"
C = d.CHAINS["avalanche"]


def test_arena_is_a_fixed_extra_router_and_foreign_addresses_are_ignored():
    assert C["extra"] == [{"dex": "Arena DEX", "router": ARENA}]
    assert d.router_of(C, ARENA) == ARENA
    assert d.router_of(C, None) == C["router"]
    assert d.router_of(C, "0x" + "ab" * 20) == C["router"]            # endereço que não é daqui nunca vira destino
    assert d.router_of(d.CHAINS["ethereum"], ARENA) == d.CHAINS["ethereum"]["router"]


def test_extra_routes_buy_and_sell_with_the_arena_router():
    tok = "0x5ddc8d968a94cf95cfeb7379f8372d858b9c797d"
    buy = d.extra_v2(C, [C["wrapped"], tok], C["ponte"])
    assert [r["rota"] for r in buy] == ["direta", "passando por dólar"] and {r["router"] for r in buy} == {ARENA}
    assert buy[1]["path"] == [C["wrapped"], C["ponte"], tok]
    sell = d.extra_v2(C, [tok, C["wrapped"]], C["ponte"], sell=True)
    assert sell[1]["path"] == [tok, C["ponte"], C["wrapped"]]
    assert d.extra_v2(d.CHAINS["base"], [C["wrapped"], tok], None) == []      # rede sem extra não muda


def test_arena_router_uses_the_same_avax_functions_as_trader_joe():
    q = {"rede": "avalanche", "token": "0x5ddc8d968a94cf95cfeb7379f8372d858b9c797d", "value": 10**17, "amount": 10**18,
         "route": {"tipo": "v2", "path": [C["wrapped"], "0x5ddc8d968a94cf95cfeb7379f8372d858b9c797d"], "router": ARENA, "dex": "Arena DEX"}}
    b = d.Buyer.__new__(d.Buyer)
    to, data = b._evm_tx(q, 1, "0x" + "11" * 20)
    assert to == ARENA and data.startswith("0x" + d.SEL_SWAP_AVAX.replace("0x", ""))
    q["route"]["path"] = [q["token"], C["wrapped"]]
    to, data = b._sell_tx(q, 1, "0x" + "11" * 20)
    assert to == ARENA and data.startswith("0x" + d.SEL_SELL_AVAX.replace("0x", ""))
    assert d.Buyer._spender(q) == ARENA
