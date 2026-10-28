"""0.31.89: log de análise dos robôs (cópia, Base, Maiores traders)."""
from app.pumpfun import PumpFun


class _E:
    RLOG_S = PumpFun.RLOG_S
    rlog = PumpFun.rlog
    rlog_summary = staticmethod(PumpFun.rlog_summary)
    rlog_pending = PumpFun.rlog_pending


def test_rlog_groups_by_5min_and_keeps_last_decision():
    e = _E()
    t = 1_793_000_100.0
    e.rlog("base", "A", "AAA", "veredito lixo", t)
    e.rlog("base", "A", "AAA", "veredito lixo", t + 20)           # mesma decisão: não conta duas vezes
    e.rlog("base", "B", "BBB", None, t + 40)
    e.rlog("base", "C", "CCC", "token velho demais (mais de 45 min)", t + 60)
    out = e.rlog_pending()
    assert len(out) == 1 and out[0]["analisados"] == 3 and out[0]["entrou"] == ["BBB"]
    assert {m["motivo"] for m in out[0]["motivos"]} == {"veredito lixo", "token velho demais (mais de 45 min)"}
    assert e.rlog_pending() == []                                   # nada mudou: nada para gravar
    e.rlog("base", "D", "DDD", "veredito lixo", t + 400)            # outro bloco de 5 min
    assert len(e.rlog_pending()) == 1
