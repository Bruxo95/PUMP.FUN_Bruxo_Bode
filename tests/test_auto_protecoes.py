"""Proteções independentes das novas automáticas; não pausam nem mudam as cópias."""
import asyncio
import copy
import time
import unittest
from datetime import datetime, timezone

from tests.test_auto_explorar import A, B, C, _pf, _row, _run


def _iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


def _history(pf, ident, mint, entered, closed=None, pnl=None, origem="explorar"):
    pf.auto_rows[str(ident)] = {"id": str(ident), "mint": mint, "origem": origem, "real": False,
                               "entrada_em": _iso(entered), "saida_em": _iso(closed) if closed is not None else None,
                               "pnl_sol": pnl}


def _zero_fees(**settings):
    return _pf(pump_ex_auto_on=True, pump_extra_slip_pct=0, pump_fee_pct=0, pump_portal_fee_pct=0,
               pump_priority_sol=0, **settings)


def _buy(pf, t):
    assert _run(pf, t=t) == [A]
    return pf.positions()[0]


def _price(pf, price, t):
    pf.tokens[A]["price"] = price
    return pf._check_stops(A, t)


def _copy_same_token(pf):
    p = copy.deepcopy(pf.positions()[0])
    for field in ("id", "auto", "origem", "auto_info", "stop_pct", "tp_pct", "trail_on", "trail_start",
                  "trail_dist", "boost_tp", "tp1_pct", "tp1_frac", "max_hold_s", "smart"):
        p.pop(field, None)
    p.update(wallet="TraderA".ljust(40, "1"), manual=False)
    pf._save_pos(p)
    return p



def _complete(coroutine):
    """Avança só corrotinas falsas sem I/O; não abre o socket local do event loop no Windows."""
    try:
        for _ in range(10):
            try:
                yielded = coroutine.send(None)
            except StopIteration as done:
                return done.value
            assert yielded is None, "o teste não deve aguardar I/O real"
        raise AssertionError("a corrotina falsa não terminou")
    finally:
        coroutine.close()


class AutoProtecoesTests(unittest.TestCase):
    def test_auto_reset_requires_closing_sim_position_and_keeps_ledger_after_close(self):
        pf = _zero_fees()
        t = time.time()
        p = _buy(pf, t)
        before = copy.deepcopy(pf.positions())
        feed_before = copy.deepcopy(list(pf.feed))
        assert "feche as posições automáticas simuladas" in pf.reset_sim()["error"]
        assert pf.positions() == before and list(pf.feed) == feed_before
        pf._sell(p, 1, 1e-6, "fechada para zerar", t + 1)
        ledger = copy.deepcopy(pf.auto_rows)
        assert pf.reset_sim() == {"ok": True}
        assert not pf.positions() and not pf.trades() and not pf.feed
        assert pf.auto_rows == ledger and ledger[str(p["id"])]["saida_em"]
        assert "24 h" in pf.auto_guard(A, t + 2)

    def test_auto_reset_blocks_persisted_open_sim_even_without_position_cache(self):
        pf = _pf()
        t = time.time()
        _history(pf, "orphan", A, t)
        assert "feche as posições automáticas simuladas" in pf.reset_sim()["error"]
        pf.auto_rows["orphan"]["real"] = True
        assert pf.reset_sim() == {"ok": True}  # o reset é só da carteira fictícia
        assert pf.auto_rows["orphan"]["saida_em"] is None

    def test_auto_fake_real_reservation_survives_await_and_keeps_trade_id(self):
        pf = _zero_fees(pump_auto_real=True, pump_ar_max_open=3)
        pf.cfg.pump_real_enabled = True
        pf.cfg.pump_real_mirror = False   # regra antiga (reserva de vaga da real); o espelho está em test_espelho_real
        t = time.time()

        class FakeReal:
            @staticmethod
            def today_loss(trades):
                return 0

            async def buy(self, mint, amount, other=False):
                assert mint == A and A in pf._auto_pending
                assert "abertas" in pf.auto_guard(C)
                await asyncio.sleep(0)  # outras rotinas ainda enxergam a vaga reservada durante a confirmação
                assert A in pf._auto_pending and "abertas" in pf.auto_guard(C)
                return {"ok": True, "sol_spent": amount, "tokens": amount / 1e-6, "signature": "fake-buy"}

            async def sell(self, mint, frac, other=False):
                return {"ok": True, "sol_received": 0.06, "tokens_left": 0, "signature": "fake-sell"}

        pf.real = FakeReal()
        _buy(pf, t)
        assert _run(pf, _row(B), t) == [B]  # duas SIM + uma reserva atingem o teto de três
        assert pf._auto_pending == {A: t}
        kind, queued = pf._rq.get_nowait()
        assert kind == "buy" and pf._rq.empty()
        _complete(pf._real_buy(queued))
        real = next(p for p in pf.positions() if p.get("real"))
        assert len(pf.positions()) == 3 and not pf._auto_pending
        assert real["auto"] is True and real["origem"] == "explorar" and real["tp1_pct"] == 40
        assert pf.auto_rows[str(real["id"])]["entrada_em"] == real["opened_at"]
        _complete(pf._real_do_sell({"id": real["id"], "frac": 1, "why": "fechamento falso"}))
        trade = pf.trades()[0]
        assert trade["id"] == real["id"] and trade["auto_info"] == real["auto_info"]
        assert trade["auto"] is True and trade["origem"] == "explorar"
        assert pf.auto_rows[str(real["id"])]["saida_em"] == trade["closed_at"]

    def test_auto_fake_real_queue_rechecks_switch_before_execution(self):
        pf = _zero_fees(pump_auto_real=True)
        pf.cfg.pump_real_enabled = True
        pf.cfg.pump_real_mirror = False   # 0.31.37: com o espelho ligado a automática vai para a real sem pump_auto_real
        pf.real = object()  # não pode chegar a today_loss/buy depois de desligar a opção
        _buy(pf, time.time())
        _kind, queued = pf._rq.get_nowait()
        pf.cfg.pump_auto_real = False
        _complete(pf._real_buy(queued))
        assert not pf._auto_pending and not pf._real_buying
        assert all(not p.get("real") for p in pf.positions())

    def test_auto_fake_real_queue_rechecks_explore_switch_before_execution(self):
        pf = _zero_fees(pump_auto_real=True)
        pf.cfg.pump_real_enabled = True
        pf.real = object()
        _buy(pf, time.time())
        _kind, queued = pf._rq.get_nowait()
        pf.cfg.pump_ex_auto_on = False
        _complete(pf._real_buy(queued))
        assert not pf._auto_pending and not pf._real_buying
        assert all(not p.get("real") for p in pf.positions())

    def test_auto_fake_real_queue_rechecks_admin_role_before_execution(self):
        pf = _zero_fees(pump_auto_real=True)
        pf.cfg.pump_real_enabled = True
        pf.real = object()
        _buy(pf, time.time())
        _kind, queued = pf._rq.get_nowait()
        pf.role = "user"
        _complete(pf._real_buy(queued))
        assert not pf._auto_pending and not pf._real_buying
        assert all(not p.get("real") for p in pf.positions())

    def test_auto_max_open_counts_positions_once_and_separate_origins(self):
        pf = _pf(pump_ex_auto_on=True, pump_ar_max_open=2)
        t = time.time()
        assert _run(pf, t=t) == [A]
        assert pf.auto_guard(B, t) is None  # posição e auto_rows têm o mesmo id, não contam duas vezes
        assert pf.manual_buy(B, t, auto="automático", origem="base")["auto_id"]
        assert "abertas" in pf.auto_guard(C, t)
        assert _run(pf, _row(C), t) == [] and len(pf.positions()) == 2


    def test_auto_max_open_includes_persisted_orphan_real_and_pending_positions(self):
        pf = _pf(pump_ar_max_open=3)
        pf.cfg.pump_real_mirror = False   # regra antiga: real e reserva contam; com o espelho só a fictícia conta
        t = time.time()
        _history(pf, "orphan", A, t)
        pf.store.save_pos({"id": "real", "mint": B, "auto": True, "origem": "explorar", "real": True})
        pf._auto_pending[C] = t
        assert "abertas" in pf.auto_guard(t=t)


    def test_auto_hourly_limit_sums_base_explore_and_legacy_without_duplicates(self):
        pf = _pf(pump_ar_max_h=3, pump_ar_max_open=10)
        t = time.time()
        _history(pf, "1", A, t - 1800, t - 1700, 0.01, "base")
        _history(pf, "2", B, t - 900, t - 800, 0.01)
        pf.store.save_trade({"id": "2", "mint": B, "auto": True, "origem": "explorar", "opened_at": _iso(t - 900),
                             "closed_at": _iso(t - 800), "pnl_sol": 0.01})
        pf._auto_done = {C: t - 100}
        assert "por hora" in pf.auto_guard(t=t)
        assert pf.auto_guard(t=t + 1801) is None


    def test_auto_daily_loss_uses_net_result_and_resets_at_utc_midnight(self):
        pf = _pf(pump_ar_daily_loss=0.25, pump_ar_streak_n=0)
        t = datetime(2026, 10, 26, 23, 50, tzinfo=timezone.utc).timestamp()
        _history(pf, "loss", A, t - 8000, t - 4000, -0.31)
        _history(pf, "win", B, t - 7000, t - 3900, 0.05, "base")
        _history(pf, "yesterday", C, t - 100000, t - 86400, -9)
        assert "perda do dia" in pf.auto_guard(t=t)
        assert "00:00 UTC" in pf.auto_guard(t=t)
        assert pf.auto_guard(t=t + 600) is None
        pf.auto_rows["win"]["pnl_sol"] = 0.07
        assert "perda do dia" in pf.auto_guard(t=t)  # recuperou para −0,24, mas já disparou a pausa até meia-noite
        assert pf._auto_pause_until == t + 600
        assert pf.auto_guard(t=t + 600) is None and pf._auto_pause_until is None


    def test_auto_daily_limit_nets_gains_before_losses_and_survives_reload(self):
        pf = _pf(pump_ar_daily_loss=0.25, pump_ar_streak_n=0)
        t = datetime(2026, 10, 26, 12, tzinfo=timezone.utc).timestamp()
        _history(pf, "win", A, t - 8000, t - 4000, 0.07)
        _history(pf, "loss", B, t - 7000, t - 3900, -0.31)
        assert pf.auto_guard(t=t) is None  # houve perda de 0,31, mas o líquido nunca passou de −0,24
        _history(pf, "more-loss", C, t - 6000, t - 3000, -0.02)
        _history(pf, "recovered", "OtherMint", t - 5000, t - 2000, 0.4)
        reloaded = _pf(pump_ar_daily_loss=0.25, pump_ar_streak_n=0)
        reloaded.auto_rows = copy.deepcopy(pf.auto_rows)
        assert "perda do dia" in reloaded.auto_guard(t=t)
        assert reloaded._auto_pause_until == t + 12 * 3600


    def test_auto_loss_streak_pause_uses_last_loss_time_without_extending_on_reads(self):
        pf = _pf(pump_ar_daily_loss=0, pump_ar_streak_n=3, pump_ar_streak_h=1)
        t = int(time.time())
        for i, mint in enumerate((A, B, C)):
            _history(pf, str(i), mint, t - 10000 + i * 100, t - 2000 + i * 100, -0.01)
        reason = pf.auto_guard(t=t)
        assert "3 perdas seguidas" in reason
        assert pf.auto_guard(t=t + 10) == reason
        assert pf.auto_guard(t=t + 1800) is None
        _history(pf, "win", "OtherMint", t - 5000, t - 100, 0.01)
        assert pf.auto_guard(t=t) == reason  # lucro de posição que já estava aberta não cancela uma pausa ativada
        assert pf._auto_pause_until == t + 1800
        assert pf.auto_guard(t=t + 1800) is None and pf._auto_pause_until is None


    def test_auto_loss_streak_pause_survives_reload_and_later_profit(self):
        pf = _pf(pump_ar_daily_loss=0, pump_ar_streak_n=3, pump_ar_streak_h=1)
        t = int(time.time())
        for i, mint in enumerate((A, B, C)):
            _history(pf, str(i), mint, t - 10000 + i * 100, t - 2000 + i * 100, -0.01)
        _history(pf, "profit", "OtherMint", t - 5000, t - 100, 0.5)
        reloaded = _pf(pump_ar_daily_loss=0, pump_ar_streak_n=3, pump_ar_streak_h=1)
        reloaded.auto_rows = copy.deepcopy(pf.auto_rows)
        assert "3 perdas seguidas" in reloaded.auto_guard(t=t)
        assert reloaded._auto_pause_until == t + 1800
        assert reloaded.auto_guard(t=t + 1800) is None


    def test_auto_same_mint_cooldown_survives_reloaded_history(self):
        pf = _pf()
        t = int(time.time())
        _history(pf, "persisted", A, t - 86399, t - 86000, 0.01)
        assert "24 h" in pf.auto_guard(A, t)
        assert pf.auto_guard(A, t + 1) is None


    def test_auto_history_failure_blocks_new_entries_but_not_manual(self):
        pf = _pf(pump_ex_auto_on=True)
        pf.auto_ready = False
        assert _run(pf) == [] and not pf.positions()
        assert "histórico" in pf.auto_guard()
        assert pf.manual_buy(A)["ok"] and len(pf.positions()) == 1


    def test_auto_partial_at_40_then_trailing_stop_closes_remaining_half(self):
        pf = _zero_fees()
        t = time.time()
        p = _buy(pf, t)
        _price(pf, 1.41e-6, t + 10)
        rest = pf.positions()[0]
        assert rest["tp1_done"] and abs(rest["tokens_left"] / p["tokens"] - 0.5) < 1e-9
        assert rest["trail_peak"] == 41 and rest["trail_exit"] == 26
        assert not pf.trades() and not pf.auto_rows[str(p["id"])]["saida_em"]
        _price(pf, 1.25e-6, t + 20)
        assert not pf.positions()
        tr = pf.trades()[0]
        assert tr["id"] == p["id"] and tr["reason"].startswith("stop móvel") and len(tr["sells"]) == 2
        assert tr["pnl_sol"] > 0 and pf.auto_rows[str(p["id"])]["motivo_saida"].startswith("stop móvel")


    def test_auto_partial_uses_per_position_fraction_and_can_be_disabled(self):
        pf = _zero_fees(pump_ar_tp1_pct=30, pump_ar_tp1_frac=25)
        t = time.time()
        p = _buy(pf, t)
        _price(pf, 1.31e-6, t + 1)
        assert abs(pf.positions()[0]["tokens_left"] / p["tokens"] - 0.75) < 1e-9
        pf = _zero_fees(pump_ar_tp1_pct=0, pump_tp1_on=True, pump_tp1_pct=10)
        p = _buy(pf, t)
        _price(pf, 1.41e-6, t + 1)
        assert pf.positions()[0]["tokens_left"] == p["tokens"]


    def test_auto_stop_loss_is_25_percent_even_if_copy_stop_is_different(self):
        pf = _zero_fees(pump_stop_pct=80)
        t = time.time()
        _buy(pf, t)
        _price(pf, 0.74e-6, t + 1)
        assert not pf.positions() and pf.trades()[0]["reason"] == "stop de perda (−25%)"


    def test_auto_price_jump_to_boost_or_final_target_sells_all_before_partial(self):
        for boost, price, reason in ((True, 1.81e-6, "boost ON"), (False, 2.51e-6, "alvo (+150%)")):
            pf = _zero_fees()
            t = time.time()
            _buy(pf, t)
            pf.market.boosts[A] = {"active": boost}
            _price(pf, price, t + 1)
            assert not pf.positions() and pf.trades()[0]["reason"].startswith(reason)
            assert len(pf.trades()[0]["sells"]) == 1 and pf.trades()[0]["sells"][0]["frac"] == 1


    def test_auto_max_hold_is_30_minutes_in_both_stop_paths(self):
        for via_prices in (False, True):
            pf = _zero_fees(pump_max_hold_h=12)
            t = time.time()
            _buy(pf, t)
            assert not pf.check_timeouts(t + 1799) and pf.positions()
            if via_prices:
                pf._check_stops(A, t + 1800)
            else:
                pf.check_timeouts(t + 1800)
            assert not pf.positions() and pf.trades()[0]["reason"] == "tempo máximo (30 min)"


    def test_auto_dev_sale_exit_does_not_change_copy_options(self):
        pf = _zero_fees(pump_exit_dev_sell=False, pump_exit_migrate=False, pump_exit_pressure_on=False)
        t = time.time()
        _buy(pf, t)
        copied = _copy_same_token(pf)
        pf.tokens[A]["dev_sold_t"] = t + 1
        pf._check_stops(A, t + 2)
        assert [p["id"] for p in pf.positions()] == [copied["id"]]
        assert pf.trades()[0]["reason"].startswith("dev vendeu")
        assert not pf.cfg.pump_exit_dev_sell


    def test_auto_pressure_exit_waits_60_seconds_and_does_not_exit_copy(self):
        pf = _zero_fees(pump_exit_pressure_on=False)
        t = time.time()
        _buy(pf, t)
        copied = _copy_same_token(pf)
        pf.tokens[A]["vol"] = {"buys_m5": 3, "sells_m5": 7}
        assert not pf._check_stops(A, t + 59) and len(pf.positions()) == 2
        pf._check_stops(A, t + 60)
        assert [p["id"] for p in pf.positions()] == [copied["id"]]
        assert pf.trades()[0]["reason"].startswith("pressão de compra virou")


    def test_auto_migration_exit_does_not_exit_copy_or_retrigger_after_graduated_entry(self):
        pf = _zero_fees(pump_exit_migrate=False)
        t = time.time()
        _buy(pf, t)
        copied = _copy_same_token(pf)
        pf.tokens[A]["pool"] = "pump-amm"
        pf._check_stops(A, t + 1)
        assert [p["id"] for p in pf.positions()] == [copied["id"]]
        assert pf.trades()[0]["reason"].startswith("token graduou")


    def test_auto_smart_exits_can_be_disabled_per_position(self):
        pf = _zero_fees(pump_ar_smart=False, pump_exit_dev_sell=False)
        t = time.time()
        _buy(pf, t)
        pf.tokens[A]["dev_sold_t"] = t + 1
        assert not pf._check_stops(A, t + 2) and pf.positions()


    def test_auto_losses_do_not_pause_copy_streak_or_reduce_copy_size(self):
        pf = _pf(pump_streak_on=True, pump_streak_n=3, pump_cold_on=True, pump_cold_wr=90)
        t = time.time()
        for i in range(5):
            tr = {"id": str(i), "wallet": "manual", "mint": A, "auto": True, "origem": "explorar",
                  "real": False, "closed_at": _iso(t - i), "pnl_sol": -0.01, "reason": "stop de perda (−25%)"}
            pf.store.save_trade(tr)
            pf._after_close(tr)
        assert pf._halt_until == 0 and not pf.paused() and pf.cold_market() == ""
        copy_loss = {"id": "copy", "wallet": "TraderA", "mint": B, "real": False,
                     "closed_at": _iso(t + 1), "pnl_sol": -0.01, "reason": "stop de perda (−40%)"}
        pf.store.save_trade(copy_loss)
        pf._after_close(copy_loss)
        assert pf._halt_until == 0 and pf.cold_market() == ""


def test_auto_stop_zero_means_no_stop_loss():
    """0.32.35 (pedido do dono): stop de perda 0 nas automáticas = sem stop de perda (antes o mínimo era 1%)."""
    pf = _zero_fees(pump_ar_stop_pct=0, pump_ar_trail_start=10000, pump_ar_tp1_pct=0, pump_ar_tp_pct=0,
                    pump_ar_press_min=0, pump_ar_exit_grad=False)
    t = time.time()
    p = _buy(pf, t)
    assert p["stop_pct"] == 0
    _price(pf, p["price_in"] * 0.2, t + 5)                  # −80%: com stop normal sairia
    assert pf.positions()                                    # sem stop: continua aberta
