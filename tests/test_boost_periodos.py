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
    assert [x[2:] for x in p1["serie"]] == [[0.03, "X", 30], [-0.01, "X", -10]]      # moeda e valores das dicas da tela
    assert p1["serie"][-1][1] == 0.02
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


def test_horarios_do_periodo_e_geral():
    """0.32.477: melhor, médio e pior horário pela hora da compra; ficar de fora só com base no geral."""
    L = []
    for dia in (22, 23, 24):
        L += [_trade(_t(dia, 10, 5), 0.03, 30), _trade(_t(dia, 14, 5), -0.001, -1)]
        L += [_trade(_t(dia, 2, m), -0.01, -10) for m in (1, 2)]
    L.append(_trade(_t(24, 18), -0.5, -50))                      # um dia só: fica em "observar"
    r = boostperiodos.build(L, lambda t: t["aba"], now=_t(24, 23).timestamp())
    g = r["horarios"]
    assert (g["melhor"]["hora"], g["medio"]["hora"], g["pior"]["hora"]) == (10, 2, 18)
    assert [x["hora"] for x in g["lucro"]] == [10]
    assert [x["hora"] for x in g["sempre_perda"]] == [2, 14]
    assert g["evitar"] == [[2, 3]] and [x["hora"] for x in g["observar"]] == [14, 18]       # 14h: só 3 trades
    assert g["evitar_sol"] == -0.06 and round(g["sem_evitar_sol"] - g["total_sol"], 6) == 0.06
    p = r["periodos"][0]["horarios"]                             # o período de um dia: toda hora no prejuízo
    assert p["evitar"] == [[2, 3], [14, 15], [18, 19]] and p["observar"] == []
    assert [x["hora"] for x in p["sempre_perda"]] == [2, 14, 18]


def test_horarios_usa_a_hora_da_compra_e_junta_horas_seguidas():
    t = _trade(_t(24, 11, 2), 0.01, 10)
    t["opened_at"] = _t(24, 10, 58).isoformat()
    assert boostperiodos.horarios([(_t(24, 11, 2).timestamp(), t)])["melhor"]["hora"] == 10
    assert boostperiodos.faixas({5, 0, 1, 23}) == [[0, 2], [5, 6], [23, 24]]
    assert boostperiodos.horarios([]) is None
