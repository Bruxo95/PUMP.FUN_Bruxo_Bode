"""0.32.446 (pedido do dono): o nome do token do BOOST chega rápido — da memória (criação na PumpPortal, Base da pump.fun) ou da
blockchain numa consulta só (Token-2022 e Metaplex); sem nome em NAME_WAIT_S a entrada não fica presa."""
import asyncio
import base64
import time

from app import boostmig as bmod
from app.boostmig import BoostMig
from tests.test_boostmig import Svc, cfg, pronto

M = "MintNome11111111111111111111111111111111pump"


def _s(x: str) -> bytes:
    b = x.encode()
    return len(b).to_bytes(4, "little") + b


def _metaplex(name, sym):
    return bytes([4]) + b"\1" * 64 + _s(name.ljust(32, "\0")) + _s(sym.ljust(10, "\0")) + _s("https://x")


def _t22(name, sym):
    meta = b"\2" * 64 + _s(name) + _s(sym) + _s("https://x") + (0).to_bytes(4, "little")
    ptr = (18).to_bytes(2, "little") + (64).to_bytes(2, "little") + b"\3" * 64
    return b"\0" * 165 + bytes([1]) + ptr + (19).to_bytes(2, "little") + len(meta).to_bytes(2, "little") + meta


def test_le_o_nome_nas_duas_contas():
    assert bmod.name_from_metaplex(_metaplex("Gato Bravo", "GATO")) == ("GATO", "Gato Bravo")
    assert bmod.name_from_mint(_t22("Gato Bravo", "GATO")) == ("GATO", "Gato Bravo")
    assert bmod.name_from_mint(b"\0" * 82) is None


def test_nome_da_criacao_entra_na_hora_da_migracao():
    now = time.time()
    bm = BoostMig(Svc({}), clock=lambda: now)
    bm.on_create({"mint": M, "symbol": "GATO", "name": "Gato Bravo", "txType": "create"}, now - 600)
    b = bm.on_migration({"mint": M, "pool": "pump-amm"}, now)
    assert b["symbol"] == "GATO" and b["name_src"] == "criação (PumpPortal)"


def test_nome_pela_blockchain_numa_consulta():
    now = time.time()
    pedidos = []

    class S(Svc):
        async def _rpc_multi(self, keys, enc, pf=False):
            pedidos.append(list(keys))
            return [{"data": [base64.b64encode(_t22("Gato Bravo", "GATO")).decode(), "base64"]} if k == M else None for k in keys]

    bm = BoostMig(S({}), clock=lambda: now)
    b = bm.on_migration({"mint": M, "pool": "pump-amm"}, now - 2)
    assert not b.get("symbol")
    asyncio.run(bm._names(now))
    assert b["symbol"] == "GATO" and b["name_src"] == "blockchain" and len(pedidos) == 1 and M in pedidos[0]


def test_sem_nome_nao_prende_a_entrada():
    now = time.time()
    bm = BoostMig(Svc({}), clock=lambda: now)
    b = pronto(bm, M, now - 60, now)
    b["symbol"] = b["name"] = None
    est, why = bm.decide(cfg(), b, now, set(), 0)
    assert "aguardando o nome" not in why
    b["t0"] = now - 5
    est, why = bm.decide(cfg(), b, now, set(), 0)
    assert est == "esperar" and "aguardando o nome" in why
