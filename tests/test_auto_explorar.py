"""Entradas do Explorar: só simulado por padrão e todos os filtros são obrigatórios."""
import copy
import time
import unittest

from app.pumpfun import PumpFun
from app.settings import PumpSettings
from app.store import MemStore

A = "AutoA".ljust(40, "1") + "pump"
B = "AutoB".ljust(40, "1") + "pump"
C = "AutoC".ljust(40, "1") + "pump"
CREATOR = "DevA".ljust(40, "1")


def _pf(**settings):
    cfg = PumpSettings()
    # travas da 0.31.0 (idade, carteiras novas, trader bom) têm testes próprios em test_auto_seguranca.py
    settings = {"pump_ar_min_age_min": 0, "pump_ar_fresh_on": False, "pump_ar_smart_on": False, **settings}
    for key, value in settings.items():
        setattr(cfg, key, value)
    pf = PumpFun(cfg, MemStore())
    pf.role = "admin"
    for mint in (A, B, C):
        pf.tokens[mint] = {"price": 1e-6, "symbol": mint[:5], "mcap_sol": 30.0}
    return pf


def _row(mint=A, **changes):
    row = {"mint": mint, "cat": "graduating", "pressure": 60.0, "holders": 100,
           "curve_pct": 80.0, "risk": 6.0, "chg_5m": 15.0, "creator": CREATOR,
           "boost": {"active": False}, "pred": {"verdict": "chance alta", "why": ["pressão boa"]}}
    row.update(changes)
    return row


def _run(pf, row=None, t=None):
    return pf.explore_auto_check({"graduating": [row if row is not None else _row()]}, t=t)


def _reject(**changes):
    pf = _pf(pump_ex_auto_on=True)
    assert _run(pf, _row(**changes)) == []
    assert not pf.positions() and not pf.auto_rows



class AutoExplorarTests(unittest.TestCase):
    def test_explore_auto_starts_on_but_only_simulated(self):
        # 0.31.11: o dono pediu o Explorar comprando "chance alta" sozinho; continua só no fictício
        pf = _pf()
        assert pf.cfg.pump_ex_auto_on is True and pf.cfg.pump_auto_real is False
        off = _pf(pump_ex_auto_on=False)
        assert _run(off) == [] and not off.positions()


    def test_explore_auto_uses_own_rules_and_keeps_entry_snapshot(self):
        pf = _pf(pump_ex_auto_on=True, pump_ar_sol=0.07, pump_manual_sol=0.9)
        row, t = _row(), time.time()
        assert _run(pf, row, t) == [A]
        p = pf.positions()[0]
        assert p["auto"] is True and p["origem"] == "explorar"
        assert abs(p["sol_in"] - 0.0705) < 1e-9
        assert (p["stop_pct"], p["tp1_pct"], p["tp1_frac"], p["max_hold_s"]) == (25, 40, 50, 1800)
        assert (p["trail_start"], p["trail_dist"], p["tp_pct"], p["smart"], p["boost_tp"]) == (40, 15, 150, True, 80)
        assert p["auto_info"]["veredito"] == "chance alta" and p["auto_info"]["chance"] is None
        assert p["auto_info"]["source"] == "explorar" and p["auto_info"]["score"] == p["score"]
        record = pf.auto_rows[str(p["id"])]
        assert record["entrada_em"] == p["opened_at"] and record["info"]["pressure"] == 60
        row["boost"]["active"] = True
        row["pred"]["why"].append("mudou depois")
        assert not pf.positions()[0]["auto_info"]["boost"]["active"]
        assert pf.positions()[0]["auto_info"]["why"] == ["pressão boa"]


    def test_explore_auto_rejects_other_verdicts(self):
        for verdict in ("lixo", "suspeito", "possível", "fraco", None):
            _reject(pred={"verdict": verdict})


    def test_explore_auto_rejects_low_pressure(self):
        _reject(pressure=59.9)


    def test_explore_auto_rejects_few_holders(self):
        _reject(holders=99)


    def test_explore_auto_rejects_excess_risk(self):
        _reject(risk=6.01)


    def test_explore_auto_accepts_unknown_risk(self):
        pf = _pf(pump_ex_auto_on=True)
        assert _run(pf, _row(risk=None)) == [A]


    def test_explore_auto_rejects_curve_outside_range(self):
        for curve in (59.99, 95.01):
            _reject(curve_pct=curve)


    def test_explore_auto_rejects_falling_or_overheated_price(self):
        for change in (-0.01, 150.01):
            _reject(chg_5m=change)


    def test_explore_auto_accepts_inclusive_filter_boundaries(self):
        for curve, change in ((60, 0), (95, 150)):
            pf = _pf(pump_ex_auto_on=True)
            assert _run(pf, _row(curve_pct=curve, chg_5m=change)) == [A]


    def test_explore_auto_rejects_rug_or_blacklisted_creator(self):
        _reject(rugged=True)
        pf = _pf(pump_ex_auto_on=True)
        pf.market.blacklist[CREATOR] = {"motivo": "histórico ruim"}
        assert _run(pf) == [] and not pf.positions()


    def test_explore_auto_rejects_creator_with_two_rugs_even_with_wins(self):
        pf = _pf(pump_ex_auto_on=True)
        pf.market.creator_stats[CREATOR] = {"rugs": 2, "x2": 10, "tokens": 12}
        assert _run(pf) == [] and not pf.positions()


    def test_explore_auto_checks_creator_known_in_market_too(self):
        pf = _pf(pump_ex_auto_on=True)
        pf.tokens[A]["creator"] = CREATOR
        pf.market.blacklist[CREATOR] = {"motivo": "histórico ruim"}
        assert _run(pf, _row(creator=None)) == []


    def test_explore_auto_rejects_missing_or_nonfinite_required_data(self):
        for field in ("pressure", "holders", "curve_pct", "chg_5m"):
            for value in (None, float("nan"), float("inf"), float("-inf"), True):
                _reject(**{field: value})
        for value in (float("nan"), float("inf"), -1):
            _reject(risk=value)


    def test_explore_auto_only_buys_from_graduating_list(self):
        pf = _pf(pump_ex_auto_on=True)
        assert pf.explore_auto_check({"latest": [_row(A)], "graduated": [_row(B)]}) == []
        _reject(cat="latest")
        _reject(cat="graduated")

    def test_explore_auto_rechecks_migration_after_cached_list(self):
        pf = _pf(pump_ex_auto_on=True)
        pf.tokens[A]["pool"] = "pump-amm"
        assert _run(pf) == [] and not pf.positions()
        result = pf.manual_buy(A, auto="automático", origem="explorar")
        assert "graduou" in result["error"] and not pf.positions()


    def test_explore_auto_requires_valid_mint_and_positive_finite_price(self):
        _reject(mint="invalid")
        for price in (None, 0, -1, float("nan"), float("inf")):
            pf = _pf(pump_ex_auto_on=True)
            pf.tokens[A]["price"] = price
            assert _run(pf) == [] and not pf.positions()


    def test_explore_auto_is_limited_to_admin(self):
        pf = _pf(pump_ex_auto_on=True)
        pf.role = "user"
        assert _run(pf) == [] and not pf.positions()


    def test_explore_auto_does_not_repeat_token_after_close_for_24h(self):
        pf = _pf(pump_ex_auto_on=True, pump_ar_daily_loss=0, pump_ar_streak_n=0)
        t = int(time.time())
        assert _run(pf, t=t) == [A]
        p = pf.positions()[0]
        pf._sell(p, 1, pf.tokens[A]["price"], "fechou teste", t + 1)
        tr = pf.trades()[0]
        assert tr["id"] == p["id"] and tr["auto"] is True and tr["origem"] == "explorar"
        assert tr["auto_info"] == p["auto_info"] and tr["closed_t"] == t + 1
        assert _run(pf, t=t + 86399) == []
        assert _run(pf, t=t + 86400) == [A]


    def test_explore_auto_never_enqueues_real_when_auto_real_is_off(self):
        pf = _pf(pump_ex_auto_on=True)
        pf.cfg.pump_real_enabled = True
        pf.real = object()   # qualquer chamada de execução real seria erro; nem a fila deve ser criada
        assert _run(pf) == [A]
        assert pf._rq is None and not pf._real_buying and not pf._auto_pending
        assert len(pf.positions()) == 1 and not pf.positions()[0]["real"]


    def test_explore_auto_rechecks_history_gate_inside_purchase(self):
        pf = _pf(pump_ex_auto_on=True)
        pf.auto_ready = False
        before = copy.deepcopy(pf.wallet())
        result = pf.manual_buy(A, auto="automático: chance alta", origem="explorar")
        assert "histórico" in result["error"] and pf.wallet() == before
        assert not pf.positions() and not pf.auto_rows


    def test_manual_and_legacy_base_keep_their_own_existing_rules(self):
        pf = _pf(pump_manual_sol=0.2, pump_ar_sol=0.9)
        assert pf.manual_buy(A)["ok"]
        assert pf.manual_buy(B, auto="automático: Boost ON")["ok"]
        for p in pf.positions():
            assert abs(p["sol_in"] - 0.2005) < 1e-9 and p["stop_pct"] == 30
            assert "origem" not in p and "tp1_pct" not in p
        assert not pf.auto_rows
