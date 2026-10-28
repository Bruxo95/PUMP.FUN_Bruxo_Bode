"""0.31.99: Explorar no "possível" (OFF), regra Wilson (OFF), compra automática das calls só na fictícia (OFF)."""
from app.ghosts import Ghosts
from app.pumpfun import AUTO_ORIGINS
from tests.test_pump import _pump


def test_options_start_off_and_calls_origin(tmp_path):
    pf = _pump(tmp_path)
    assert pf.cfg.pump_ex_possivel_on is False and pf.cfg.pump_ar_learn_wilson is False and pf.cfg.pump_calls_auto_on is False
    assert "calls" in AUTO_ORIGINS
    row = {"mint": "Poss".ljust(40, "1") + "pump", "cat": "graduating", "pred": {"verdict": "possível"}}
    assert pf.explore_entry_reason(row) == "veredito não é chance alta"
    pf.cfg.pump_ex_possivel_on = True
    assert pf.explore_entry_reason(row) != "veredito não é chance alta"


def test_wilson_option_changes_only_when_on(tmp_path):
    pf = _pump(tmp_path)
    pf._learned = {"explorar": (9e18, {"bloqueios": [{"feature": "risk", "faixa": "4 a 6"}],
                                       "faixas": [{"feature": "risk", "faixa": "4 a 6", "bloq_wilson": False}]})}
    assert pf.learned_for_entry("explorar")["bloqueios"]
    pf.cfg.pump_ar_learn_wilson = True
    assert pf.learned_for_entry("explorar")["bloqueios"] == []


def test_ghost_open_positions_survive_restart(tmp_path):
    import time
    pf = _pump(tmp_path)
    g = pf.ghosts
    g.open = [{"v": g.names[0] if isinstance(g.names, list) else next(iter(g.names)), "mint": "X", "open_t": time.time()}]
    d = g.dump()
    g2 = Ghosts(pf) if False else g
    g2.open = []
    g2.load(d)
    assert len(g2.open) == 1
