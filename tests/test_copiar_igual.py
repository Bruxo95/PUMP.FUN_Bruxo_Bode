"""0.32.4 — "Copiar igual" (pedido do dono, 28/10): carteiras do leaderboard da pump.fun copiadas sem filtros e sem
espera. Tudo com carteira falsa: nenhuma transação de verdade."""
from app.pumpfun import EQ_SEED
from tests.test_espelho_real import _pf
from tests.test_pump import _W, _ev

M = "Igua".ljust(40, "1") + "pump"


def _eq(tmp_path, **kw):
    pf = _pf(tmp_path, **kw)
    pf.cfg.pump_real_enabled = False
    pf.copy_equal = [_W]
    pf.cfg.pump_eq_on = True
    pf.cfg.pump_min_trader_sol = 5.0          # filtro normal que barraria a compra pequena
    pf.cfg.pump_copy_delay_s = 30.0           # espera normal que atrasaria a cópia
    pf.refresh_followed(force=True)
    return pf


def test_off_by_default_and_seeded_with_leaderboard(tmp_path):
    pf = _pf(tmp_path)
    assert pf.cfg.pump_eq_on is False and pf.eq_wallets() == []
    assert list(pf.copy_equal) == list(EQ_SEED) and len(EQ_SEED) == 20


def test_copies_buy_without_filters_and_delay_then_sells_same_fraction(tmp_path):
    pf = _eq(tmp_path)
    assert _W in pf.followed
    pf.on_message(_ev("buy", _W, M, 0.1, 1e5, 30, 3e7), 1000.0)
    ps = [p for p in pf.positions() if p["mint"] == M]
    assert len(ps) == 1 and ps[0]["eq"] is True and ps[0]["off_stop"] is True
    assert abs(ps[0]["sol_in"] - (pf.cfg.pump_eq_sol + pf.cfg.pump_priority_sol)) < 1e-9
    assert not pf._pending                                     # sem espera
    pf.on_message(_ev("sell", _W, M, 0.05, 5e4, 30, 3e7, newTokenBalance=5e4), 1010.0)
    p = [p for p in pf.positions() if p["mint"] == M][0]
    assert abs(p["tokens_left"] / p["tokens"] - 0.5) < 0.01   # vendeu a metade, como a carteira
    pf.on_message(_ev("sell", _W, M, 0.05, 5e4, 30, 3e7, newTokenBalance=0), 1020.0)
    assert not [p for p in pf.positions() if p["mint"] == M]
    assert any(t.get("eq") for t in pf.trades(10))


def test_no_stop_loss_unless_mode_stop(tmp_path):
    pf = _eq(tmp_path)
    pf.on_message(_ev("buy", _W, M, 0.1, 1e5, 30, 3e7), 1000.0)
    pf.tokens[M]["price"] = pf.tokens[M]["price"] * 0.3      # caiu 70%: o stop normal (40%) venderia
    pf._check_stops(M, 1001.0)
    assert [p for p in pf.positions() if p["mint"] == M]
    pf.cfg.pump_eq_stop_pct = 50.0
    pf._check_stops(M, 1002.0)
    assert not [p for p in pf.positions() if p["mint"] == M]


def test_real_only_with_eq_real(tmp_path):
    pf = _eq(tmp_path)
    pf.cfg.pump_real_enabled = True
    pf.on_message(_ev("buy", _W, M, 0.1, 1e5, 30, 3e7), 1000.0)
    assert pf._rq is None or pf._rq.qsize() == 0               # real desligada neste modo
    m2 = "Igub".ljust(40, "1") + "pump"
    pf.cfg.pump_eq_real = True
    pf.on_message(_ev("buy", _W, m2, 0.1, 1e5, 30, 3e7), 1001.0)
    kind, it = pf._rq.get_nowait()
    assert kind == "buy" and it["mint"] == m2 and it["sim_id"] and it["pos_cfg"]["eq"] is True


def test_normal_copy_unchanged_for_other_wallets(tmp_path):
    pf = _eq(tmp_path)
    other = "OtherTrader1111111111111111111111111111111"[:44]
    pf.add_manual(other)
    pf.on_message(_ev("buy", other, M, 0.1, 1e5, 30, 3e7), 1000.0)   # 0,1 SOL < mínimo 5: a cópia normal barra
    assert not [p for p in pf.positions() if p["wallet"] == other]


def test_study_approved_wallets_copy_only_in_sim(tmp_path):
    """0.32.11 (pedido do dono): aprovadas pelo estudo automático são copiadas sozinhas, só na fictícia."""
    pf = _pf(tmp_path)                                  # real ligada, espelho ligado (carteira falsa)
    pf.study_copy = [_W]
    pf.refresh_followed(force=True)
    assert _W not in pf.followed                        # opção desligada: não copia
    pf.cfg.pump_st_auto_copy = True
    pf.refresh_followed(force=True)
    assert _W in pf.followed
    pf.on_message(_ev("buy", _W, M, 1.0, 1e6, 30, 3e7), 1000.0)
    assert [p["real"] for p in pf.positions() if p["mint"] == M] == [False]
    assert pf._rq is None or pf._rq.qsize() == 0        # nada foi para a real
