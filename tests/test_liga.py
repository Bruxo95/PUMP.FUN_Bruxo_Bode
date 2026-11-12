"""0.32.328 (pedido do dono, 12/11/2026: "faz tudo" — copiar os maiores traders não estava dando certo): liga de candidatos. As vagas
do Top traders vão para quem deu resultado para quem COPIA, não para quem mais lucrou sozinho."""
from datetime import datetime, timedelta, timezone

from app.pumpfun import PumpFun
from app.settings import PumpSettings
from app.store import MemStore


def W(c):
    return (c * 44)[:44]


def _pf(**kw):
    cfg = PumpSettings()
    for k, v in kw.items():
        setattr(cfg, k, v)
    return PumpFun(cfg, MemStore())


def _copias(pf, w, n, pct, hold):
    for i in range(n):
        pf.store.save_trade({"id": f"{w[:4]}{i}", "wallet": w, "real": False, "pnl_pct": pct, "pnl_sol": pct / 1000, "hold_s": hold,
                             "closed_at": (datetime.now(timezone.utc) - timedelta(hours=1 + i)).isoformat()})


def test_default_is_on():
    assert PumpSettings().pump_liga_on is True and PumpSettings().pump_liga_min_hold_s == 60


def test_proven_first_untested_next_losers_and_fast_flippers_out():
    pf = _pf()
    a, b, c, d, e = W("A"), W("B"), W("C"), W("D"), W("E")
    _copias(pf, a, 5, 10.0, 300)          # dá resultado para quem copia
    _copias(pf, e, 6, 25.0, 900)          # dá mais ainda
    _copias(pf, b, 5, -12.0, 300)         # dá prejuízo para quem copia
    _copias(pf, c, 5, 30.0, 20)           # vende em 20 s: não dá para copiar de verdade
    _copias(pf, d, 2, -50.0, 300)         # ainda sem base: fica em teste
    order = pf.liga_order([d, b, c, a, e])
    assert order == [e, a, d]
    assert "por cópia" in pf.liga_out[b] and "rápido demais" in pf.liga_out[c]
    assert pf.liga_count == {"comprovados": 2, "em_teste": 1, "rebaixados": 2}


def test_real_copies_and_old_trades_do_not_count():
    pf = _pf()
    w = W("F")
    _copias(pf, w, 5, -20.0, 300)
    for t in pf.store.trades(100):
        t["real"] = True
    for i in range(5):
        pf.store.save_trade({"id": f"old{i}", "wallet": w, "real": False, "pnl_pct": -30, "pnl_sol": -0.03, "hold_s": 300,
                             "closed_at": (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()})
    assert pf.liga_order([w]) == [w] and not pf.liga_out


def test_minimum_hold_zero_turns_the_speed_rule_off():
    pf = _pf(pump_liga_min_hold_s=0)
    w = W("G")
    _copias(pf, w, 5, 15.0, 5)
    assert pf.liga_order([w]) == [w]
