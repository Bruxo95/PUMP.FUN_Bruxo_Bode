"""0.32.78: Comprar / Comprar todas do Lançamento sem trader — vagas próprias e aba na operação. Carteira falsa."""
from tests.test_espelho_real import _pf


def test_launch_buys_have_own_slots_and_tab(tmp_path):
    pf = _pf(tmp_path)
    pf.cfg.pump_real_enabled = False
    pf.cfg.pump_max_open = 1
    pf.cfg.pump_manual_sol = 0.01
    ms = [f"Lan{i}".ljust(40, "1") + "pump" for i in range(3)]
    for m in ms:
        pf.tokens[m] = {"price": 1e-6, "symbol": "L", "mcap_sol": 30.0}
        r = pf.manual_buy(m, target="sim", origem="lancamento")
        assert str(r["sim"]).startswith("comprou"), r
    ps = [p for p in pf.positions() if p["mint"] in ms]
    assert len(ps) == 3 and all(pf.aba_of(p) == "Lançamento sem trader" for p in ps)
