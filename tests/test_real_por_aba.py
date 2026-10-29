"""0.32.61 (pedido do dono): cada compra automática só vai para a REAL com o botão REAL da própria aba, e o stop que passou
do limite explica no motivo de onde o preço pulou. Tudo com carteira falsa: nenhuma transação de verdade."""
from tests.test_espelho_real import A, _pf


def test_auto_without_its_real_button_stays_fictitious(tmp_path):
    pf = _pf(tmp_path)
    pf.tokens[A] = {"price": 1e-6, "symbol": "ESP", "mcap_sol": 40.0}
    pf.cfg.pump_auto_real = False
    r = pf.manual_buy(A, auto="automático: Boost ON")
    assert r["sim"] and r["real"] == "REAL desligada nesta aba (só fictícia)" and not pf._real_buying


def test_calls_go_real_only_with_button(tmp_path):
    pf = _pf(tmp_path)
    m1, m2 = "Cax1".ljust(40, "1") + "pump", "Cax2".ljust(40, "1") + "pump"
    for m in (m1, m2):
        pf.tokens[m] = {"price": 1e-6, "symbol": "CAL", "mcap_sol": 40.0}
    r = pf.manual_buy(m1, auto="call de X (80%)", origem="calls")
    assert r["real"] == "REAL desligada nesta aba (só fictícia)"
    pf.cfg.pump_calls_real = True
    r = pf.manual_buy(m2, auto="call de X (80%)", origem="calls")
    assert str(r["real"]).startswith("enviando") and m2 in pf._real_buying


def test_stop_gap_explains_jump(tmp_path):
    pf = _pf(tmp_path)
    assert pf._stop_gap((100.0, -10.0, 99.0), -31.0, 30, 101.0, A) == ""          # passou pouco do limite: nada a explicar
    s = pf._stop_gap((100.0, -12.0, 99.0), -65.0, 30, 101.0, A)
    assert "pulou de -12% para -65% em 1 s" in s and "despejo" in s
    s = pf._stop_gap((100.0, -12.0, 60.0), -65.0, 30, 101.0, A)
    assert "preço parado" in s
    assert "1ª leitura" in pf._stop_gap(None, -90.0, 30, 101.0, A)
