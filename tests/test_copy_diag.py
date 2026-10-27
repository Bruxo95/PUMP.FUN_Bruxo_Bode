"""Por que não copiou (0.31.78): compras vistas dos traders seguidos, copiadas e motivos."""
from tests.test_pump import _W, _ev, _pump


def test_copy_diag_counts_small_buys(tmp_path):
    pf = _pump(tmp_path, paid=False, pump_min_trader_sol=0.2)
    pf.add_manual(_W)
    m1, m2 = "Dia1".ljust(40, "1") + "pump", "Dia2".ljust(40, "1") + "pump"
    pf.on_message(_ev("buy", _W, m1, 0.05, 1e6, 30, 3e7))                # compra pequena: não copia
    pf.on_message(_ev("buy", _W, m2, 1.0, 1e6, 30, 3e7))                 # copia
    d = pf.copy_diag()
    assert d["vistas"] == 2 and d["copiadas"] == 1
    assert any("compra pequena" in x["motivo"] for x in d["motivos"])
    assert d["traders"][0]["wallet"] == _W and d["traders"][0]["copiadas"] == 1
