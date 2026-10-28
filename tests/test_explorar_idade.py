"""0.32.36 (Bruxo): idade máxima do token no Explorar e idade no aprender com os erros."""
import time

from app.autolearn import FEATURES, bucket
from tests.test_pump import _pump


def _row(age_min):
    return {"mint": "Idad".ljust(40, "1") + "pump", "cat": "graduating", "pred": {"verdict": "chance alta"},
            "pressure": 70, "holders": 150, "curve_pct": 70, "chg_5m": 10, "risk": 3, "buys": 70, "sells": 30,
            "created": (time.time() - age_min * 60) * 1000}


def test_max_age_off_by_default_and_blocks_when_on(tmp_path):
    pf = _pump(tmp_path)
    assert pf.cfg.pump_ex_max_age_min == 0
    assert "máximo" not in str(pf.explore_entry_reason(_row(40)))
    pf.cfg.pump_ex_max_age_min = 10
    assert "máximo 10" in pf.explore_entry_reason(_row(40))
    assert "máximo" not in str(pf.explore_entry_reason(_row(5)))


def test_explore_min_age_own_setting(tmp_path):
    pf = _pump(tmp_path)
    m = "Idad".ljust(40, "1") + "pump"
    assert "mínimo 20" in str(pf.auto_safety(m, 5, "explorar"))
    pf.cfg.pump_ex_min_age_min = 0
    assert "mínimo" not in str(pf.auto_safety(m, 5, "explorar"))
    assert "mínimo 20" in str(pf.auto_safety(m, 5, "base"))          # a Base continua esperando 20 min


def test_age_is_a_learning_feature():
    assert "age_min" in FEATURES and bucket("age_min", 7) == "até 10 min" and bucket("age_min", 45) == "30 a 60 min"
