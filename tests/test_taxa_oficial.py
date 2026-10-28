"""0.31.82: tabela oficial da PumpSwap (opção do usuário, desligada por padrão)."""
from app.pumpfun import PumpFun
from tests.test_pump import _pump

M = "Taxa".ljust(40, "1") + "pump"


def test_swap_fee_table():
    assert PumpFun.swap_fee_official(300) == 1.25
    assert PumpFun.swap_fee_official(1000) == 1.20
    assert PumpFun.swap_fee_official(5000) == 1.00
    assert PumpFun.swap_fee_official(200000) == 0.30
    assert PumpFun.swap_fee_official(None) is None


def test_official_fee_only_when_turned_on(tmp_path):
    pf = _pump(tmp_path)
    pf.tokens[M] = {"pool": "pump-amm", "price": 1e-6, "quote": "SOL"}          # 1.000 SOL de valor de mercado
    assert abs(pf._fee_rates(M)["venue"] - 0.003) < 1e-9                       # desligada: campo fixo 0,30%
    pf.cfg.pump_swap_fee_official = True
    assert abs(pf._fee_rates(M)["venue"] - 0.012) < 1e-9                       # ligada: 1,20%
    pf.tokens[M]["quote"] = "outra moeda"
    assert abs(pf._fee_rates(M)["venue"] - 0.003) < 1e-9                       # fora de SOL segue o campo
    pf.tokens[M] = {"price": 1e-6}                                             # ainda na curva: 1,25% como antes
    assert abs(pf._fee_rates(M)["venue"] - 0.0125) < 1e-9
