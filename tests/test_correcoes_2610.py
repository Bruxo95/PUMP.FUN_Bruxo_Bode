"""Correções de 2026-10-26 a partir dos relatórios (0.31.10): robô de volume fora dos sugeridos e explicado no Steps,
saída por estagnação e perdas por tempo máximo no relatório."""
import time

from tests.test_daily import _iso
from tests.test_pump import _W, _ev, _pump

BOT = "Gladey".ljust(44, "1")


def test_volume_bot_leaves_the_suggested_list_and_steps_explain():
    from app.elite import Elite
    from app.pumpfun import PumpMarket
    el = Elite(PumpMarket())
    el.refresh_names([[{"wallet": BOT, "name": "Gladey", "realized_usd": 9e4, "winrate": 95, "trades": 900, "base_flags": []}]], 15)
    assert [r["wallet"] for r in el.recommended()] == [BOT]
    t = time.time()
    m = "Bonk".ljust(40, "1") + "pump"
    for i in range(5):
        el.on_trade(BOT, {"txType": "buy", "mint": m, "solAmount": 0.001, "tokenAmount": 10.0}, t + i, {"min_wallets": 2, "window_min": 10, "big_sol": 5})
        el.on_trade(BOT, {"txType": "sell", "mint": m, "solAmount": 1.5, "tokenAmount": 10.0}, t + i + 0.5, {"min_wallets": 2, "window_min": 10, "big_sol": 5})
    assert el.recommended() == [] and "robô de volume" in el.bot_reason(BOT)
    st = el.steps([], [], [], None)
    buy = next(x for x in st if x["kind"] == "buy")
    assert buy["bot_action"] == "ignorado: robô" and "0,01 SOL" in buy["bot_reason"]


def test_stale_position_exits_only_when_option_is_on(tmp_path):
    pf = _pump(tmp_path, paid=False, pump_extra_slip_pct=0.0, pump_trail_enabled=False, pump_hold_until_profit=False)
    pf.add_manual(_W)
    m = "Parado".ljust(40, "1") + "pump"
    t0 = time.time() - 50 * 60
    pf.on_message(_ev("buy", _W, m, 1.0, 1e6, 30, 3e7), t0)
    pf.tokens[m]["price"] = 1.02e-6                                   # ≈ -1,7% líquido: parado
    pf._check_stops(m, time.time())
    assert pf.positions()                                             # opção desligada: segura
    pf.cfg.pump_exit_stale_on = True
    pf._check_stops(m, time.time())
    assert not pf.positions() and pf.trades()[0]["reason"].startswith("parado há 50 min")


def test_daily_report_flags_time_limit_losses_and_lists_worst_trades(tmp_path):
    from app.daily import build, day_of
    pf = _pump(tmp_path, paid=False)
    now = time.time()
    for i, (pnl, why) in enumerate(((-0.0126, "tempo máximo (6 h)"), (-0.0038, "tempo máximo (6 h)"), (-0.0166, "tempo máximo (6 h)"),
                                    (0.0259, "stop móvel (pico +52.8% → saiu em +25.7% líquido)"))):
        pf._save_trade({"wallet": "W", "symbol": f"T{i}", "mint": "M" * 40, "sol_in": 0.1005, "pnl_sol": pnl, "pnl_pct": pnl * 1000,
                        "reason": why, "opened_at": _iso(now - 3600 * 6), "closed_at": _iso(now - 60 * (i + 1)), "real": False})
    rep = build(pf, day_of(now), [])
    assert any(s["tipo"] == "tempo_maximo" for s in rep["suggestions"])
    assert [x["token"] for x in rep["worst_trades"]] == ["T2", "T0", "T1"]


def test_ghosts_measure_stale_and_one_hour_rules():
    from app.ghosts import VARIANTS
    ids = [v for v, _, _ in VARIANTS]
    assert "parado45" in ids and "max1h" in ids
