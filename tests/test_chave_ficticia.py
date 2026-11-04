"""0.32.198 (pedido do dono): chave geral da carteira FICTÍCIA. Tudo com carteira falsa: nenhuma transação de verdade."""
from tests.test_espelho_real import _pf
from tests.test_pump import _W, _ev

M = "Sim0".ljust(40, "1") + "pump"


def test_sim_off_opens_nothing_in_the_fictitious_wallet(tmp_path):
    pf = _pf(tmp_path)
    pf.add_manual(_W)
    pf.cfg.pump_real_enabled = False
    pf.cfg.pump_sim_on = False
    pf.on_message(_ev("buy", _W, M, 1.0, 1e6, 30, 3e7))
    assert not pf.positions()
    pf.cfg.pump_sim_on = True
    pf.on_message(_ev("buy", _W, M, 1.0, 1e6, 30, 3e7))
    assert [p["real"] for p in pf.positions()] == [False]


def test_sim_off_trader_copy_still_goes_to_real(tmp_path):
    pf = _pf(tmp_path)
    pf.add_manual(_W)
    pf.cfg.pump_real_enabled = True
    pf.cfg.pump_sim_on = False
    pf.on_message(_ev("buy", _W, M, 1.0, 1e6, 30, 3e7))
    kind, it = pf._rq.get_nowait()
    assert kind == "buy" and it["mint"] == M and not it.get("sim_id")
    assert not [p for p in pf.positions() if not p.get("real")]


def test_sim_off_open_position_still_sells(tmp_path):
    pf = _pf(tmp_path)
    pf.add_manual(_W)
    pf.cfg.pump_real_enabled = False
    pf.on_message(_ev("buy", _W, M, 1.0, 1e6, 30, 3e7))
    assert pf.positions()
    pf.cfg.pump_sim_on = False
    pf.cfg.pump_hold_until_profit = False
    pf.on_message(_ev("sell", _W, M, 1.0, 1e6, 30, 3e7))
    assert not pf.positions()
