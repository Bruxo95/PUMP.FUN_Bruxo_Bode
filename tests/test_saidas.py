"""Saídas inteligentes, nota da entrada e gestão de banca (0.19.0). Tudo começa desligado; cada teste liga só o
que testa."""
import time
from datetime import datetime, timezone

from tests.test_pump import _W, _ev, _pump

_W2 = "TraderTwo2222222222222222222222222222222"
_W3 = "TraderThree33333333333333333333333333333"
_DEV = "DevOfToken11111111111111111111111111111"


def _buy(pf, m, t, who=_W, px=1e-6):
    pf.on_message(_ev("buy", who, m, 1.0, 1e6, 30, 30 / px), t)


def test_new_options_start_off_and_do_not_change_old_behavior(tmp_path):
    pf = _pump(tmp_path, paid=False)
    for k in ("pump_exit_dev_sell", "pump_exit_migrate", "pump_exit_pressure_on", "pump_exit_kol_on",
              "pump_score_min_on", "pump_size_by_score", "pump_streak_on", "pump_cold_on"):
        assert getattr(pf.cfg, k) is False
    pf.add_manual(_W)
    m = "Off".ljust(40, "1") + "pump"
    t = time.time()
    pf.on_message(_ev("create", _DEV, m, 0, 0, 30, 3e7, symbol="OFF"), t - 5)
    _buy(pf, m, t)
    pf.on_message(_ev("sell", _DEV, m, 0.1, 1e5, 30, 3e7), t + 1)            # dev vende, mas a opção está OFF
    p = pf.positions()[0]
    assert p["score"] is not None and 0 <= p["score"] <= 100 and abs(p["sol_in"] - 0.1005) < 1e-9


def test_exit_when_dev_sells(tmp_path):
    pf = _pump(tmp_path, paid=False, pump_exit_dev_sell=True)
    pf.add_manual(_W)
    m = "DevExit".ljust(40, "1") + "pump"
    t = time.time()
    pf.on_message(_ev("create", _DEV, m, 0, 0, 30, 3e7, symbol="DEVX"), t - 5)
    _buy(pf, m, t)
    assert pf.positions()
    pf.on_message(_ev("sell", _DEV, m, 0.1, 1e5, 30, 3e7), t + 2)
    assert not pf.positions() and pf.trades()[0]["reason"].startswith("dev vendeu")


def test_exit_when_token_graduates(tmp_path):
    pf = _pump(tmp_path, paid=False, pump_exit_migrate=True)
    pf.add_manual(_W)
    m = "Migra".ljust(40, "1") + "pump"
    _buy(pf, m, time.time())
    assert pf.positions()[0]["grad_in"] is False
    pf.tokens[m]["pool"] = "pump-amm"
    pf._check_stops(m, time.time())
    assert not pf.positions() and pf.trades()[0]["reason"].startswith("token graduou")


def test_exit_when_other_followed_wallets_sell(tmp_path):
    pf = _pump(tmp_path, paid=False, pump_exit_kol_on=True, pump_exit_kol_n=2)
    for w in (_W, _W2, _W3):
        pf.add_manual(w)
    m = "Kols".ljust(40, "1") + "pump"
    t = time.time()
    for i, w in enumerate((_W, _W2, _W3)):
        _buy(pf, m, t + i, who=w)
    assert len(pf.positions()) == 1 and pf.positions()[0]["wallet"] == _W
    pf.on_message(_ev("sell", _W2, m, 1.0, 1e6, 30, 3e7, newTokenBalance=0), t + 5)
    assert pf.positions() and pf.positions()[0]["kol_sellers"] == [_W2]
    pf.on_message(_ev("sell", _W3, m, 1.0, 1e6, 30, 3e7, newTokenBalance=0), t + 6)
    assert not pf.positions() and "2 carteiras" in pf.trades()[0]["reason"]


def test_exit_when_buy_pressure_turns(tmp_path):
    pf = _pump(tmp_path, paid=False, pump_exit_pressure_on=True, pump_exit_pressure_pct=40.0)
    pf.add_manual(_W)
    m = "Press".ljust(40, "1") + "pump"
    t0 = time.time() - 120
    _buy(pf, m, t0)
    pf.tokens[m]["vol"] = {"buys_m5": 3, "sells_m5": 17}                   # 15% de compras
    pf._check_stops(m, t0 + 30)                                             # antes de 1 min: segura
    assert pf.positions()
    pf._check_stops(m, t0 + 90)
    assert not pf.positions() and "pressão de compra virou" in pf.trades()[0]["reason"]


def test_min_score_blocks_and_size_follows_score(tmp_path):
    pf = _pump(tmp_path, paid=False, pump_score_min_on=True, pump_score_min=99.0)
    pf.add_manual(_W)
    m = "Score".ljust(40, "1") + "pump"
    _buy(pf, m, time.time())
    assert not pf.positions()
    assert any("nota da entrada" in str(e.get("reason")) for e in pf.feed)
    pf2 = _pump(tmp_path, paid=False, pump_size_by_score=True, pump_extra_slip_pct=0.0)
    pf2.add_manual(_W)
    _buy(pf2, m, time.time())
    p = pf2.positions()[0]
    assert abs((p["sol_in"] - 0.0005) - 0.1 * (0.5 + p["score"] / 100)) < 1e-6


def test_loss_streak_pauses_new_copies(tmp_path):
    pf = _pump(tmp_path, paid=False, pump_streak_on=True, pump_streak_n=2, pump_streak_h=1.0, pump_trail_enabled=False,
                pump_autopause_stops=0)
    pf.add_manual(_W)
    t = time.time()
    for i in range(2):
        m = f"Loss{i}".ljust(40, "1") + "pump"
        _buy(pf, m, t + i)
        pf.tokens[m]["price"] = 0.4e-6                                      # −60%: stop de perda
        pf._check_stops(m, t + i)
    assert len(pf.trades()) == 2 and all(x["pnl_sol"] < 0 for x in pf.trades())
    assert pf._halt_until > time.time()
    _buy(pf, "Loss9".ljust(40, "1") + "pump", t + 5)
    assert not pf.positions() and any("sequência de perdas" in str(e.get("reason")) for e in pf.feed)


def test_cold_market_halves_the_copy(tmp_path):
    pf = _pump(tmp_path, paid=False, pump_cold_on=True, pump_cold_wr=30.0, pump_extra_slip_pct=0.0)
    now = datetime.now(timezone.utc).isoformat()
    for i in range(6):
        pf._save_trade({"wallet": "X", "mint": f"C{i}", "pnl_sol": -0.01, "closed_at": now, "real": False})
    assert pf.cold_market().startswith("×0,5")
    pf.add_manual(_W)
    _buy(pf, "Cold".ljust(40, "1") + "pump", time.time())
    p = pf.positions()[0]
    assert abs((p["sol_in"] - 0.0005) - 0.05) < 1e-9


def test_reports_group_results_by_score():
    from app.reports import build
    now = datetime.now(timezone.utc).isoformat()
    T = [{"score": 85, "pnl_sol": 0.02, "closed_at": now}, {"score": 82, "pnl_sol": 0.01, "closed_at": now},
         {"score": 35, "pnl_sol": -0.03, "closed_at": now}, {"pnl_sol": 0.5, "closed_at": now}]
    r = build(T, [], None, False)
    by = {x["faixa"]: x for x in r["by_score"]}
    assert by["80–100"]["trades"] == 2 and by["80–100"]["win_rate"] == 1.0 and by["0–39"]["pnl_sol"] == -0.03
    assert by["40–59"]["trades"] == 0
