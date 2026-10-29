"""0.32.80: relatório da Aba do Bruxo (30 min e 1 dia) e o aprendizado de vários dias."""
from datetime import datetime, timezone

from app.bruxoreport import build, learn

NOW = 1_800_000_000.0


def _iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


def _sig(i, peak, entrou, kind="trader", t=NOW - 600):
    return {"id": f"s{i}", "t": t, "mint": f"M{i}", "kind": kind, "done": True, "peak_pct": peak, "peak_s": 120,
            "hit100_s": 100 if peak >= 100 else None, "stop30_s": None, "marks": {"5": peak / 2}, "age_min": 1.0,
            "decisoes": {"u": {"entrou": entrou, "motivo": None if entrou else "curva em 40% (só entra no começo, até 25%)"}}}


def _tr(pnl, origem="bruxo", ago=300):
    return {"origem": origem, "pnl_sol": pnl, "pnl_pct": pnl * 1000, "closed_at": _iso(NOW - ago), "opened_at": _iso(NOW - ago - 60),
            "symbol": "T", "mint": "M", "hold_s": 60, "reason": "stop de perda (−30%)" if pnl < 0 else "alvo"}


def test_report_counts_signals_launches_and_ops():
    sigs = [_sig(i, 150, i < 3) for i in range(6)] + [_sig(10 + i, 20, False, "lancamento") for i in range(4)]
    sigs.append(_sig(99, 500, True, t=NOW - 5000))                      # fora dos 30 min
    trades = [_tr(0.01), _tr(-0.02), _tr(0.005, "lancamento"), _tr(0.5, ago=4000), _tr(0.3, "outra")]
    r = build(sigs, "u", trades, [{"origem": "bruxo"}], NOW - 1800, NOW, "30min")
    assert r["sinais"]["n"] == 6 and r["sinais"]["entrou"] == 3 and r["lancamento"]["n"] == 4
    assert r["sinais"]["nao_entrou"][0]["motivo"].startswith("curva em 40%")
    assert r["operacoes"]["n"] == 3 and {g["origem"] for g in r["operacoes"]["grupos"]} == {"bruxo", "lancamento"}
    assert r["abertas"] == 1 and r["veredito"] == "perdendo" and r["maiores_perdas"][0]["pnl_sol"] == -0.02


def test_learn_repeated_lessons_over_days():
    d = lambda dia, l: {"dia": dia, "licoes": l, "operacoes": {"n": 3, "pnl_sol": 0.01}, "sinais": {"n": 5}, "estudo": {}, "lancamento": {}}
    L = learn([d("2026-10-28", ["Aba do Bruxo: maior causa X"]), d("2026-10-29", ["Aba do Bruxo: maior causa X", "outra"])])
    assert L["licoes_repetidas"][0]["dias"] == 2 and len(L["dias"]) == 2 and L["pnl_sol"] == 0.02
