"""0.32.465 (pedido do dono, 25/11/2026): recomeçar a carteira FICTÍCIA com outro saldo sem apagar o histórico."""
from datetime import datetime, timezone

from app import boostperiodos
from app.pumpfun import PumpFun


def _iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


class _PF:
    sim_since = None
    sim_counts = PumpFun.sim_counts


def test_sem_recomeco_conta_tudo():
    assert _PF().sim_counts({"opened_at": _iso(1000)})


def test_depois_do_recomeco_conta_so_o_que_abriu_depois():
    pf = _PF()
    pf.sim_since = 1_000_000.0
    assert not pf.sim_counts({"opened_at": _iso(999_000), "closed_at": _iso(1_000_500)})
    assert pf.sim_counts({"opened_at": _iso(1_000_100), "closed_at": _iso(1_000_500)})
    assert pf.sim_counts({"open_t": 1_000_100.0})
    assert not pf.sim_counts({"open_t": 999_999.0})


def test_periodos_do_boost_mantem_o_historico_e_separa_a_carteira():
    base = datetime(2026, 11, 24, 12, tzinfo=timezone.utc).timestamp()
    L = [{"opened_at": _iso(base), "closed_at": _iso(base + 60), "pnl_sol": -1.0, "pnl_pct": -10, "sol_in": 0.1, "aba": boostperiodos.ABA},
         {"opened_at": _iso(base + 86400), "closed_at": _iso(base + 86460), "pnl_sol": 0.5, "pnl_pct": 10, "sol_in": 0.1, "aba": boostperiodos.ABA}]
    since = base + 86000
    pf = _PF()
    pf.sim_since = since
    r = boostperiodos.build(L, lambda t: t["aba"], now=base + 90000, since=since, conta=pf.sim_counts)
    novo, velho = r["periodos"][0], r["periodos"][1]
    assert velho["saldo_sol"] == -1.0 and velho["antes_do_recomeco"] and velho["saldo_carteira_sol"] == 0
    assert novo["antes_sol"] == 0 and novo["saldo_carteira_sol"] == 0.5 and not novo["antes_do_recomeco"]
