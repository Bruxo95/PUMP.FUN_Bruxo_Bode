"""Botão Comprar com valores prontos (0.26.0): quanto comprar, stop, alvo, stop móvel e venda em +80% com Boost ON."""
import time

from tests.test_pump import _pump

M = "Botao".ljust(40, "1") + "pump"


def _buy(tmp_path, **kw):
    pf = _pump(tmp_path, paid=False, pump_extra_slip_pct=0.0, pump_copy_sol=0.5, **kw)
    pf.tokens[M] = {"price": 1e-6, "symbol": "BTN", "mcap_sol": 30.0}
    assert pf.manual_buy(M)["ok"]
    return pf, pf.positions()[0]


def _px(pf, px):
    pf.tokens[M]["price"] = px
    pf._check_stops(M, time.time())


def test_button_uses_its_own_preset_values(tmp_path):
    pf, p = _buy(tmp_path)
    assert abs(p["sol_in"] - 0.1005) < 1e-9                                # 0,1 SOL do botão, não os 0,5 da cópia
    assert (p["stop_pct"], p["tp_pct"], p["trail_on"], p["trail_start"], p["trail_dist"], p["boost_tp"]) == (30.0, 100.0, True, 30.0, 15.0, 80.0)
    _px(pf, 0.65e-6)                                                       # −36%: o stop geral (40%) não venderia
    assert not pf.positions() and pf.trades()[0]["reason"] == "stop de perda (−30%)"


def test_boost_on_sells_at_80_and_without_boost_waits_for_target(tmp_path):
    pf, _ = _buy(tmp_path)
    pf.market.boosts[M] = {"active": True}
    _px(pf, 1.9e-6)                                                        # ≈ +83% líquido
    assert not pf.positions() and pf.trades()[0]["reason"].startswith("boost ON: alvo +80%")
    pf2, _ = _buy(tmp_path)
    _px(pf2, 1.9e-6)
    assert pf2.positions()                                                 # sem boost: segura
    _px(pf2, 2.15e-6)                                                      # ≈ +107%: alvo do botão
    assert not pf2.positions() and pf2.trades()[0]["reason"] == "alvo (+100%)"


def test_copies_keep_the_general_rules(tmp_path):
    from tests.test_pump import _W, _ev
    pf = _pump(tmp_path, paid=False, pump_extra_slip_pct=0.0, pump_trail_enabled=False)
    pf.add_manual(_W)
    m = "Copia".ljust(40, "1") + "pump"
    pf.on_message(_ev("buy", _W, m, 1.0, 1e6, 30, 3e7), time.time())
    assert "stop_pct" not in pf.positions()[0]
    pf.tokens[m]["price"] = 0.65e-6
    pf._check_stops(m, time.time())
    assert pf.positions()                                                  # cópia segue o stop geral de 40%
