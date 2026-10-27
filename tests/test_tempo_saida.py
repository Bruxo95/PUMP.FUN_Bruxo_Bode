"""Tempo de saída por posição (0.31.69, sugestão do Bruxo): estender ou tirar o limite, inclusive no par do espelho."""
import time

from tests.test_espelho_real import A, _pf


def test_extend_hold_and_no_limit(tmp_path):
    pf = _pf(tmp_path)
    pf.cfg.pump_real_enabled = False
    pf.tokens[A] = {"price": 1e-6, "symbol": "LEG", "mcap_sol": 40.0}
    pf.manual_buy(A)
    p = [x for x in pf.positions() if x["mint"] == A][0]
    snap = [x for x in pf.snapshot()["positions"] if x["mint"] == A][0]
    assert snap["hold_s"] == 6 * 3600 and snap["hold_src"] == "geral"
    r = pf.extend_hold(p["id"], 30)
    assert r["ok"] and abs(r["max_hold_s"] - (6 * 3600 + 1800)) < 5
    pf.extend_hold(p["id"], None)
    assert [x for x in pf.positions() if x["mint"] == A][0]["max_hold_s"] >= 3e8
    assert not pf.check_timeouts(time.time() + 7 * 3600)                  # sem limite: não sai por tempo
    assert pf.extend_hold("nao-existe", 30).get("error")
