"""0.31.87 (Bruxo): desligar stop de perda, stop móvel e venda em partes de uma posição."""
from tests.test_pump import _W, _ev, _pump


def test_turn_off_stop_keeps_position_open(tmp_path):
    pf = _pump(tmp_path, paid=False)
    pf.add_manual(_W)
    m = "Regr".ljust(40, "1") + "pump"
    pf.on_message(_ev("buy", _W, m, 1.0, 1e6, 30, 3e7))
    p = pf.positions()[0]
    assert pf.position_rule(p["id"], "stop", False)["ok"]
    assert pf.positions()[0]["off_stop"] is True
    pf.tokens[m]["price"] = p["price_in"] * 0.2                     # −80%: com o stop ligado fecharia
    import time
    pf._check_stops(m, time.time())
    assert pf.positions() and pf.positions()[0]["id"] == p["id"]
    assert pf.position_rule(p["id"], "nada", False).get("error")
