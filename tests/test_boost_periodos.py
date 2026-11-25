"""Períodos diários do BOOST (0.32.459)."""
from datetime import datetime

from app import boostperiodos
from app.daily import TZ


def _t(dia, h, m=0):
    return datetime(2026, 11, dia, h, m, tzinfo=TZ)


def _trade(closed, pnl, pct, aba="BOOST da migração", sol_in=0.1):
    return {"closed_at": closed.isoformat(), "opened_at": closed.isoformat(), "pnl_sol": pnl, "pnl_pct": pct, "sol_in": sol_in,
            "symbol": "X", "mint": "m", "aba": aba}


def test_periodos_numerados_por_dia_e_somas():
    L = [_trade(_t(24, 20, 24), 0.03, 30), _trade(_t(24, 21), -0.01, -10),
         _trade(_t(25, 10), 0.02, 20), _trade(_t(25, 11), 0.5, 50, aba="Top traders")]
    r = boostperiodos.build(L, lambda t: t["aba"], now=_t(25, 12).timestamp())
    assert [p["rotulo"] for p in r["periodos"]] == ["02", "01"]
    p1 = r["periodos"][1]
    assert p1["fechado"] and p1["trades"] == 2 and p1["ganhos"] == 1 and p1["perdas"] == 1
    assert p1["pct_ganhos_soma"] == 30 and p1["pct_perdas_soma"] == -10 and p1["acerto"] == 50
    p2 = r["periodos"][0]
    assert not p2["fechado"] and p2["trades"] == 1                       # o trade de outra aba não entra no BOOST
    assert p2["antes_sol"] == 0.02                                      # mas conta na carteira inicial do período
    assert r["atual"] == 2


def test_dia_sem_trade_continua_contando_e_ganho_falso_fica_fora():
    L = [_trade(_t(23, 10), 0.01, 10), _trade(_t(25, 10), 9.0, 99999)]
    r = boostperiodos.build(L, lambda t: t["aba"], now=_t(25, 12).timestamp())
    assert [p["rotulo"] for p in r["periodos"]] == ["03", "02", "01"]
    assert r["periodos"][0]["trades"] == 0 and r["periodos"][1]["trades"] == 0


def test_sem_trades_do_boost():
    assert boostperiodos.build([], lambda t: "x")["periodos"] == []
