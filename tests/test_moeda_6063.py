"""0.31.83: erro 6063 (curva cotada em outra moeda) vai direto para a Jupiter e ganha explicação."""
from app.pumpfun import PumpReal

R = "transação recusada pela simulação: a simulação falhou: {'InstructionError': [3, {'Custom': 6063}]}"


def test_6063_is_other_quote():
    assert PumpReal.other_quote(R)
    assert not PumpReal.other_quote("0x1772")
    assert "outra moeda" in PumpReal.explain(R)
