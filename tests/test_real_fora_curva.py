"""0.32.330: com `pump_real_no_curve`, a REAL não compra token ainda na curva da pump.fun; depois de graduar, compra."""
import asyncio
import time

from tests.test_espelho_real import _pf

A = "Curv".ljust(40, "1") + "pump"


def _item():
    return {"mint": A, "symbol": "CRV", "wallet": "W" * 44, "t": time.time(), "trader_price": 1e-6}


def test_padrao_desligado_compra_na_curva(tmp_path):
    pf = _pf(tmp_path)
    assert pf._c("pump_real_no_curve", None) is False
    pf.tokens[A] = {"price": 1e-6, "pool": "pump"}
    asyncio.run(pf._real_buy(_item()))
    assert pf.real.calls and pf.real.calls[0][0] == "buy"


def test_ligado_fica_fora_da_curva_e_compra_graduado(tmp_path):
    pf = _pf(tmp_path)
    pf.cfg.pump_real_no_curve = True
    pf.tokens[A] = {"price": 1e-6, "pool": "pump"}
    asyncio.run(pf._real_buy(_item()))
    assert pf.real.calls == []
    assert any("curva da pump.fun" in (f.get("reason") or "") for f in pf.feed)
    pf.tokens[A]["pool"] = "pumpswap"
    asyncio.run(pf._real_buy(_item()))
    assert pf.real.calls and pf.real.calls[0][0] == "buy"
