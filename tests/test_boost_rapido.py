"""0.32.447 (pedido do dono, caso PAPU): perto do limite de entrada as compras e vendas são lidas a cada 1 s e a decisão roda a cada 1 s."""
import asyncio
import time

from app import boostmig as bmod
from app.boostmig import BoostMig
from tests.test_boostmig import Svc

M = "MintRapido111111111111111111111111111111pump"


class S(Svc):
    def __init__(self, tokens):
        super().__init__(tokens)
        self.n = 0

    async def _fetch_prices(self, mints, set_price=True):
        self.n += 1
        for m in mints:
            self.tokens.setdefault(m, {})["vol"] = {"buys_m5": 120 + self.n, "sells_m5": 50}


def test_janela_quente_le_a_cada_segundo():
    now = time.time()
    svc = S({})
    bm = BoostMig(svc, clock=lambda: now)
    b = bm.on_migration({"mint": M, "pool": "pump-amm"}, now - bmod.JANELA_S * 0.22)   # 22% do BOOST
    bm.enter_max = [25.0]
    assert not bm.hot(b, now)                                            # 0.32.448: ninguém analisou ainda
    b["users"] = {"u1": {"estado": "esperar"}}
    assert bm.hot(b, now) and bm.any_hot(now)
    asyncio.run(bm._track(now))
    asyncio.run(bm._track(now + 1))
    assert svc.n == 1                                                    # 1 s depois: ainda não
    asyncio.run(bm._track(now + 5))
    assert svc.n == 2                                                    # a cada 5 s (fora da janela: 15 s)
    b["users"] = {"u1": {"estado": "entrou"}}
    assert not bm.hot(b, now)
    b["users"] = {"u1": {"estado": "fora"}}
    assert not bm.hot(b, now)                                            # todo mundo já decidiu
    b["users"] = {"u1": {"estado": "esperar"}}
    assert not bm.hot(b, now - bmod.JANELA_S * 0.1)                      # 12%: ainda longe do limite


def test_fora_da_janela_continua_15_s():
    now = time.time()
    svc = S({})
    bm = BoostMig(svc, clock=lambda: now)
    b = bm.on_migration({"mint": M, "pool": "pump-amm"}, now - bmod.JANELA_S * 0.05)
    b["users"] = {"u1": {"estado": "esperar"}}
    bm.enter_max = [25.0]
    asyncio.run(bm._track(now))
    asyncio.run(bm._track(now + 6))
    assert svc.n == 1
