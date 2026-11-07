"""0.32.255 (dono: "por que limita em 20 se configurei 40?"): o motivo diz de qual carteira é o limite."""
from tests.test_pump import _W, _ev, _pump


def test_limite_da_ficticia_diz_que_e_da_ficticia(tmp_path):
    pf = _pump(tmp_path)
    pf.add_manual(_W)
    pf.cfg.pump_max_open, pf.cfg.pump_real_max_open = 1, 40
    pf.on_message(_ev("buy", _W, "Lim1".ljust(40, "1") + "pump", 1.0, 1e6, 30, 3e7))
    pf.on_message(_ev("buy", _W, "Lim2".ljust(40, "1") + "pump", 1.0, 1e6, 30, 3e7))
    r = [f.get("reason") or "" for f in pf.feed if (f.get("action") == "não copiou")]
    assert any("na FICTÍCIA" in x and "REAL tem o limite próprio: 40" in x for x in r)
