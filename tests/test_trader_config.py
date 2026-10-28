"""0.32.19 (pedido do dono): Configuração do Trader — 2º alvo, stop por tempo e faixa da curva, só nas cópias e desligados
por padrão. Tudo com carteira falsa."""
from tests.test_pump import _W, _ev, _pump

M = "Tcfg".ljust(40, "1") + "pump"


def _pf(tmp_path):
    pf = _pump(tmp_path, paid=False)
    pf.add_manual(_W)
    return pf


def test_new_rules_start_off(tmp_path):
    pf = _pf(tmp_path)
    c = pf.cfg
    assert c.pump_tp2_pct == 0 and c.pump_timestop_on is False and c.pump_entry_curve_on is False


def test_second_target_sells_share_of_original(tmp_path):
    pf = _pf(tmp_path)
    c = pf.cfg
    c.pump_tp1_on, c.pump_tp1_pct, c.pump_tp1_frac_pct = True, 100, 50
    c.pump_tp2_pct, c.pump_tp2_frac_pct = 300, 25
    c.pump_trail_enabled = False
    pf.on_message(_ev("buy", _W, M, 1.0, 1e6, 30, 3e7), 1000.0)
    p = [p for p in pf.positions() if p["mint"] == M][0]
    base = pf.tokens[M]["price"]
    pf.tokens[M]["price"] = base * 2.8               # +100% líquido depois das taxas
    pf._check_stops(M, 1001.0)
    p = [p for p in pf.positions() if p["mint"] == M][0]
    assert p.get("tp1_done") and abs(p["tokens_left"] / p["tokens"] - 0.5) < 0.01
    pf.tokens[M]["price"] = base * 6.0
    pf._check_stops(M, 1002.0)
    p = [p for p in pf.positions() if p["mint"] == M][0]
    assert p.get("tp2_done") and abs(p["tokens_left"] / p["tokens"] - 0.25) < 0.01     # moonbag 25%


def test_time_stop_sells_copy_that_never_went_up(tmp_path):
    pf = _pf(tmp_path)
    pf.cfg.pump_timestop_on, pf.cfg.pump_timestop_s, pf.cfg.pump_timestop_gain_pct = True, 180, 0
    pf.on_message(_ev("buy", _W, M, 1.0, 1e6, 30, 3e7), 1000.0)
    pf._check_stops(M, 1100.0)
    assert [p for p in pf.positions() if p["mint"] == M]                                 # ainda não deu o tempo
    pf._check_stops(M, 1200.0)
    assert not [p for p in pf.positions() if p["mint"] == M]
    assert any("stop por tempo" in (t.get("reason") or "") for t in pf.trades(5))


def test_entry_curve_range_blocks_copy(tmp_path):
    pf = _pf(tmp_path)
    pf.cfg.pump_entry_curve_on, pf.cfg.pump_entry_curve_min, pf.cfg.pump_entry_curve_max = True, 0, 10
    pf.on_message(_ev("buy", _W, M, 1.0, 1e6, 60, 3e7), 1000.0)                         # curva bem cheia
    assert not [p for p in pf.positions() if p["mint"] == M]
