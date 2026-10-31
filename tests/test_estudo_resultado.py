"""0.32.114: estudo do Resultado por período. Só mede. Sem internet."""
import asyncio
from datetime import datetime, timezone

from app import resultstudy as rs

NOW = 2_000_000_000.0


def _t(h, pnl, pct, aba="Explorar", reason="stop de -30%", hold=600, real=False):
    return {"closed_at": datetime.fromtimestamp(NOW - h * 3600, timezone.utc).isoformat(), "pnl_sol": pnl, "pnl_pct": pct, "sol_in": 0.1, "aba": aba,
            "reason": reason, "hold_s": hold, "real": real, "symbol": "T", "mint": "M"}


def _b(T, h=24, real=False):
    return rs.build(T, NOW - h * 3600, NOW, real, lambda t: t["aba"], h)


def test_reason_groups_without_the_numbers():
    assert rs.motivo("stop móvel (pico +36.6% → saiu em +1.5% líquido)") == "stop móvel"
    assert rs.motivo("Jev Trade · stop de +20%") == rs.motivo("Jev Trade · stop de +0%") == "Jev Trade · stop de"
    assert rs.motivo(None) == "sem motivo"


def test_study_counts_and_splits_by_tab_exit_and_time():
    T = [_t(1, 0.2, 200, "Bruxo", "trader vendeu 100%", 200)] + [_t(2, -0.03, -30) for _ in range(6)] + [_t(30, 9, 900), _t(1, 1, 50, real=True)]
    E = _b(T)
    assert E["trades"] == 7 and E["ganhos"] == 1 and E["perdas"] == 6 and E["saldo_sol"] == 0.02 and E["investido_sol"] == 0.7
    assert E["por_aba"][0]["nome"] == "Explorar" and E["por_aba"][0]["n"] == 6 and E["por_aba"][0]["sol"] == -0.18
    assert {x["nome"] for x in E["por_tempo"]} == {"até 5 min", "5 a 30 min"}
    assert E["acerto_empate"] == 13 and any("para empatar" in x for x in E["licoes"]) and any("Explorar" in x for x in E["licoes"])
    assert E["melhores"][0]["sol"] == 0.2 and E["piores"][0]["sol"] == -0.03


def test_suspect_gain_stays_in_the_total_but_out_of_the_groups():
    E = _b([_t(1, 50, 5000), _t(1, -0.03, -30)])
    assert E["saldo_sol"] == 49.97 and E["suspeitos"] == 1 and sum(x["n"] for x in E["por_aba"]) == 1


def test_learn_needs_several_days_to_call_it_repeated():
    dia = lambda d, sol: {"dia": d, "data": {"trades": 2, "saldo_sol": sol, "por_aba": [{"nome": "Explorar", "n": 2, "ganhos": 0, "sol": sol, "media_pct": -10}]}}
    assert rs.learn([dia("a", -1)])["por_aba"][0]["veredito"] == "poucos dias"
    L = rs.learn([dia(str(i), -0.1) for i in range(5)])
    assert L["dias"] == 5 and L["trades"] == 10 and L["por_aba"][0]["veredito"] == "perda repetida" and L["por_aba"][0]["sol"] == -0.5


class _Db:
    def __init__(self):
        self.rows = []

    async def insert(self, t, row, **kw):
        self.rows.append(row)


class _E:
    user_id = "u1"

    def __init__(self, T):
        self.T = T

    def trades(self, n):
        return self.T

    def aba_of(self, t):
        return t["aba"]


class _DbS:
    ROWS = [{"id": "u1:0:1h:9", "user_id": "u1", "real": False, "origem": "manual", "em": "2026-10-31T23:00:00+00:00", "data": {"horas": 1, "trades": 6, "acerto": 33, "saldo_sol": 0.15}},
            {"id": "u1:0:1h:8", "user_id": "u1", "real": False, "origem": "manual", "em": "2026-10-31T22:00:00+00:00", "data": {"horas": 1, "trades": 2}},
            {"id": "u2:0:6h:9", "user_id": "u2", "real": False, "origem": "manual", "em": "2026-10-31T21:00:00+00:00", "data": {"horas": 6, "trades": 9}}]

    async def select(self, table, filters=None, **kw):
        if table == "profiles":
            return [{"user_id": "u1", "nome": "Dono"}, {"user_id": "u2", "email": "bruxo@x.com"}]
        return [r for r in self.ROWS if all(r.get(k) == v for k, v in (filters or {}).items())]


def test_marks_and_base_section_show_only_what_was_saved():
    from app.hub import PumpHub
    h = PumpHub.__new__(PumpHub)
    h.db = _DbS()
    M = asyncio.run(h.rs_marks(_E([]), False))
    assert M == {"1": "2026-10-31T23:00:00+00:00"}                     # só desta conta, e o mais novo de cada período
    B = asyncio.run(h.rs_base(False))
    assert [x["conta"] for x in B] == ["Dono", "Dono", "bruxo"] and B[0]["saldo_sol"] == 0.15
    assert asyncio.run(h.rs_base(True)) == []                          # real não mistura com fictícia
    assert asyncio.run(h.rs_item("u1:0:1h:9"))["trades"] == 6 and asyncio.run(h.rs_item("x")) is None


def test_closed_days_are_saved_once_and_never_the_empty_ones():
    from app.hub import PumpHub
    h = PumpHub.__new__(PumpHub)
    h.db = _Db()
    h.engines = {"u1": _E([_t(30, 0.1, 10), _t(1, 0.1, 10)])}
    asyncio.run(h.result_tick(NOW))
    n = len(h.db.rows)
    asyncio.run(h.result_tick(NOW))
    assert n >= 1 and len(h.db.rows) == n and all(r["origem"] == "dia" and r["user_id"] == "u1" for r in h.db.rows)
    assert h.rs_learn(False)["trades"] >= 1
