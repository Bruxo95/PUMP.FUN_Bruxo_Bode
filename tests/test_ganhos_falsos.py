"""0.32.1: revisão dos ganhos de +1.900% ou mais (só leitura e marca; nada sai dos totais)."""
from app.ganhos_falsos import collect, impact, judge, pair_real, report

V = [{"versao": "0.31.40", "inicio": "2026-10-27T10:00:00+00:00"}, {"versao": "0.31.52", "inicio": "2026-10-27T16:00:00+00:00"}]


def _t(i, pct, at, real=False, best=None, **kw):
    return {"id": i, "mint": "M" + i, "symbol": "T" + i, "pnl_pct": pct, "pnl_sol": pct / 100 * 0.05, "best_pct": best,
            "opened_at": at, "closed_at": at, "real": real, **kw}


def test_collect_finds_big_gains_and_alvo_falso_in_all_accounts():
    A = ("ua", "Bruxo", [_t("1", 133475.0, "2026-10-27T12:00:00+00:00"), _t("2", 30.0, "2026-10-27T12:00:00+00:00"),
                         _t("3", -13.0, "2026-10-27T13:00:00+00:00", real=True, best=7612.0)])
    B = ("ub", "Pedro", [_t("4", 2500.0, "2026-10-28T09:00:00+00:00")])
    items = collect([A, B], V)
    assert [i["id"] for i in items] == ["4", "3", "1"]
    by = {i["id"]: i for i in items}
    assert by["3"]["tipo"] == "melhor momento" and by["1"]["versao"] == "0.31.40" and not by["1"]["depois_da_correcao"]
    assert by["4"]["depois_da_correcao"] and by["4"]["conta"] == "Pedro"


def test_judge_marks_other_quote_curve_as_false_and_uses_real_pair():
    sim = _t("1", 182916.0, "2026-10-27T12:00:00+00:00", pos_id="P1")
    real = _t("r", -8.0, "2026-10-27T12:00:00+00:00", real=True, sim_id="P1")
    items = collect([("ua", "Bruxo", [sim, real])], V)
    pair_real(items, {"ua": [sim, real]})
    j = judge(items[0], {"quote": "SPCXxyz111"}, None)
    assert j["falso"] is True and "outra moeda" in j["veredito"] and j["resultado_verdadeiro_pct"] == -8.0
    assert "carteira real" in j["fonte_verdadeiro"]


def test_judge_uses_market_price_when_curve_is_sol():
    it = collect([("ua", "X", [_t("1", 5000.0, "2026-10-27T12:00:00+00:00")])], V)[0]
    assert judge(it, {"quote": "SOL"}, {"in_usd": 1.0, "out_usd": 0.9})["falso"] is True
    ok = judge(it, {"quote": "SOL"}, {"in_usd": 1.0, "out_usd": 52.0})
    assert ok["falso"] is False and ok["resultado_verdadeiro_pct"] is None
    assert judge(it, {"quote": "sem curva"}, None)["falso"] is None


def test_impact_only_informs_totals_with_and_without():
    T = [_t("1", 2000.0, "2026-10-27T12:00:00+00:00"), _t("2", -20.0, "2026-10-27T12:00:00+00:00")]
    acc = [("ua", "Bruxo", T)]
    items = [judge(i, {"quote": "TTWOabc"}, None) for i in collect(acc, V)]
    m = impact(items, acc)[0]
    assert m["falsos_sol"] == 1.0 and m["sem_falsos_sol"] == round(1.0 - 0.01 - 1.0, 4) and m["total_sol"] == 0.99
    r = report(items, acc)
    assert r["falsos"] == 1 and r["depois_da_correcao"] == 0 and r["onde_pesa"]
