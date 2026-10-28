"""0.32.3 — sugestão do Bruxo (áudio de 28/10, SPCX): a fictícia já ter o token não impede a real de comprar.
Tudo com carteira falsa: nenhuma transação de verdade."""
from tests.test_espelho_real import A, _pf
from tests.test_pump import _W, _ev


def test_trader_buy_goes_to_real_when_only_sim_holds_token(tmp_path):
    pf = _pf(tmp_path)
    pf.add_manual(_W)
    m = "Spcx".ljust(40, "1") + "pump"
    pf.cfg.pump_real_enabled = False
    pf.on_message(_ev("buy", _W, m, 1.0, 1e6, 30, 3e7))                  # só a fictícia entra (real desligada)
    assert [p["real"] for p in pf.positions() if p["mint"] == m] == [False]
    pf.cfg.pump_real_enabled = True
    pf.on_message(_ev("buy", _W, m, 1.0, 1e6, 30, 3e7))                  # trader compra de novo: a real entra separada
    kind, it = pf._rq.get_nowait()
    assert kind == "buy" and it["mint"] == m and not it.get("sim_id")
    assert len([p for p in pf.positions() if p["mint"] == m and not p.get("real")]) == 1   # a fictícia não duplica
    pf.on_message(_ev("buy", _W, m, 1.0, 1e6, 30, 3e7))                  # com a real já comprando, não repete
    assert pf._rq.qsize() == 0


def test_buy_button_goes_to_real_when_only_sim_holds_token(tmp_path):
    pf = _pf(tmp_path)
    pf.tokens[A] = {"price": 1e-6, "symbol": "ESP", "mcap_sol": 40.0}
    pf.cfg.pump_real_enabled = False
    pf.manual_buy(A)
    pf.cfg.pump_real_enabled = True
    r = pf.manual_buy(A)
    assert r["sim"] == "já tem posição fictícia neste token" and r["real"].startswith("enviando")
    kind, it = pf._rq.get_nowait()
    assert kind == "buy" and not it.get("sim_id") and it["pos_cfg"]["manual"] is True
