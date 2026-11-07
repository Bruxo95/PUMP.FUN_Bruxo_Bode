"""0.32.254 (pedido do dono): a REAL só compra token com pelo menos N min de vida (padrão 10)."""
import asyncio
import time

import httpx

from tests.test_espelho_real import _pf

A = "Idad".ljust(40, "1") + "pump"


def _item(pf):
    return {"mint": A, "symbol": "IDA", "wallet": "W" * 44, "t": time.time(), "trader_price": 1e-6}


def test_padrao_e_10_min_e_token_novo_fica_fora_da_real(tmp_path):
    pf = _pf(tmp_path)
    assert float(pf._c("pump_real_min_age_min", -1)) == 10
    pf.tokens[A] = {"price": 1e-6, "creator": "C" * 44, "created_t": time.time() - 4 * 60}   # criação vista: 4 min
    asyncio.run(pf._real_buy(_item(pf)))
    assert pf.real.calls == []
    assert any("4.0 min de vida" in (f.get("reason") or "") for f in pf.feed)
    pf.tokens[A]["created_t"] = time.time() - 12 * 60                                         # 12 min: compra
    asyncio.run(pf._real_buy(_item(pf)))
    assert pf.real.calls and pf.real.calls[0][0] == "buy"


def test_idade_pelo_rpc_quando_o_monitor_nao_viu_a_criacao(tmp_path):
    pf = _pf(tmp_path)
    now = time.time()

    def handler(req):
        return httpx.Response(200, json={"result": [{"signature": "s1", "blockTime": now - 60},
                                                     {"signature": "s0", "blockTime": now - 3 * 60}]})
    pf.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert 2.9 < asyncio.run(pf.token_age_min(A, 10)) < 3.1                   # só 2 transações: nasceu há 3 min
    assert pf.tokens[A]["born_t"] == now - 3 * 60
    pf.cfg.pump_real_min_age_min = 2
    asyncio.run(pf._real_buy(_item(pf)))
    assert pf.real.calls                                                      # 3 min ≥ 2 min: compra
