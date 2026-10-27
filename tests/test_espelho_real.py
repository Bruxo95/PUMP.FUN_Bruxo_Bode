"""Carteira real espelha 100% a fictícia, com o valor e os limites da real (0.31.37, sugestão do Bruxo).
Tudo com carteira falsa: nenhuma transação de verdade."""
import asyncio

from tests.test_pump import _W, _ev, _pump

A = "Espe".ljust(40, "1") + "pump"


class FakeReal:
    def __init__(self):
        self.calls = []

    def api_key(self):
        return ""

    def today_loss(self, trades):
        return 0.0

    async def buy(self, mint, amt, other=False):
        self.calls.append(("buy", mint, amt))
        return {"ok": True, "signature": "B", "sol_spent": amt, "tokens": 1_000_000.0}

    async def sell(self, mint, frac, other=False):
        self.calls.append(("sell", mint, frac))
        return {"ok": True, "signature": "S", "sol_received": 0.01, "tokens_left": 0.0}


def _pf(tmp_path, **kw):
    pf = _pump(tmp_path, paid=False, pump_real_max_sol=0.02, pump_manual_sol=0.3, **kw)
    pf.cfg.pump_real_enabled = True
    pf.real = FakeReal()
    return pf


def test_automatic_buy_is_mirrored_with_real_size(tmp_path):
    pf = _pf(tmp_path)
    pf.tokens[A] = {"price": 1e-6, "symbol": "ESP", "mcap_sol": 40.0}
    r = pf.manual_buy(A, auto="automático: Boost ON")                  # antes: só com "Também na carteira real"
    assert r["sim"] and r["real"].startswith("enviando")
    sim = [p for p in pf.positions() if not p.get("real")][0]
    kind, it = pf._rq.get_nowait()
    assert kind == "buy" and it["sim_id"] == sim["id"]
    asyncio.run(pf._real_buy(it))
    real = [p for p in pf.positions() if p.get("real")][0]
    assert pf.real.calls == [("buy", A, 0.02)]                            # valor da REAL, não os 0,3 do fictício
    assert real["sim_id"] == sim["id"]
    pf._sell(sim, 1.0, 1e-6, "teste", 0.0)                                # o fictício fechou → a real sai junto
    kind, it = pf._rq.get_nowait()
    assert kind == "sell" and it["id"] == real["id"] and it["frac"] == 1.0 and "espelho" in it["why"]


def test_trader_copy_is_mirrored_only_after_sim_opens(tmp_path):
    pf = _pf(tmp_path)
    pf.add_manual(_W)
    pf.cfg.pump_max_open = 1
    m1, m2 = "Mir1".ljust(40, "1") + "pump", "Mir2".ljust(40, "1") + "pump"
    pf.on_message(_ev("buy", _W, m1, 1.0, 1e6, 30, 3e7))
    assert pf._rq.qsize() == 1 and m1 in pf._real_buying
    pf.on_message(_ev("buy", _W, m2, 1.0, 1e6, 30, 3e7))                 # fictício bateu o limite: a real também não entra
    assert pf._rq.qsize() == 1 and m2 not in pf._real_buying


def test_real_limits_still_apply(tmp_path):
    pf = _pf(tmp_path, pump_real_max_open=1)
    pf.tokens[A] = {"price": 1e-6, "symbol": "ESP", "mcap_sol": 40.0}
    b = "Lim2".ljust(40, "1") + "pump"
    pf.tokens[b] = {"price": 1e-6, "symbol": "LIM", "mcap_sol": 40.0}
    pf.manual_buy(A, auto="automático: x")
    r = pf.manual_buy(b, auto="automático: y")
    assert r["sim"] and "limite de 1 posições reais" in r["real"]


def test_real_closes_at_once_when_sim_closed_while_queued(tmp_path):
    pf = _pf(tmp_path)
    pf.tokens[A] = {"price": 1e-6, "symbol": "ESP", "mcap_sol": 40.0}
    pf.manual_buy(A, auto="automático: Boost ON")
    sim = [p for p in pf.positions() if not p.get("real")][0]
    _k, it = pf._rq.get_nowait()
    pf._sell(sim, 1.0, 1e-6, "stop", 0.0)                                 # fechou antes de a compra real sair
    asyncio.run(pf._real_buy(it))
    kind, it2 = pf._rq.get_nowait()
    assert kind == "sell" and it2["frac"] == 1.0 and "já fechou" in it2["why"]


def test_mirror_off_keeps_old_rule(tmp_path):
    pf = _pf(tmp_path)
    pf.cfg.pump_real_mirror = False
    pf.tokens[A] = {"price": 1e-6, "symbol": "ESP", "mcap_sol": 40.0}
    assert pf.manual_buy(A, auto="automático: Boost ON")["real"] is None


def test_explore_last_slot_of_the_hour_still_goes_real():
    """R1R2L1R2 (27/10): a fictícia recém-aberta não pode bloquear a real, e a real não ocupa vaga da fictícia."""
    from tests.test_auto_explorar import A as EA, B as EB, _row, _run
    from tests.test_auto_protecoes import _complete, _zero_fees
    pf = _zero_fees(pump_ar_max_h=1, pump_ar_max_open=1)
    pf.cfg.pump_real_enabled = True
    pf.real = FakeReal()
    import time
    t = time.time()
    assert _run(pf, t=t) == [EA]
    kind, it = pf._rq.get_nowait()
    assert kind == "buy" and it["mint"] == EA and it["sim_id"] is not None   # última vaga da hora: a real vai junto
    _complete(pf._real_buy(it))
    assert pf.real.calls and pf.real.calls[0][0] == "buy"
    assert pf.auto_guard(EB, t) == "limite de 1 posições automáticas abertas"  # só a fictícia ocupa a vaga


def test_mirror_buys_even_if_price_ran_and_misses_are_explained(tmp_path):
    """0.31.43: no espelho a real não desiste porque o preço subiu (chase); e o que não foi para a real tem motivo."""
    pf = _pf(tmp_path, pump_max_chase_pct=30.0, pump_chase_on=True)
    pf.tokens[A] = {"price": 1e-6, "symbol": "ESP", "mcap_sol": 40.0}
    pf.manual_buy(A, auto="automático: x")
    _k, it = pf._rq.get_nowait()
    pf.tokens[A]["price"] = 3e-6                                          # subiu 200% antes de a real sair
    asyncio.run(pf._real_buy(it))
    assert pf.real.calls and pf.real.calls[0][0] == "buy"
    b = "Miss".ljust(40, "1") + "pump"
    pf.tokens[b] = {"price": 1e-6, "symbol": "MIS", "mcap_sol": 40.0}
    pf.cfg.pump_real_daily_loss_sol = 0.01
    pf.real.today_loss = lambda trades: 1.0
    pf.manual_buy(b, auto="automático: y")
    sim_b = [p for p in pf.positions() if p["mint"] == b and not p.get("real")][0]
    _k, it2 = pf._rq.get_nowait()
    asyncio.run(pf._real_buy(it2))
    pf._sell(sim_b, 1.0, 1.1e-6, "alvo", 0.0)
    m = pf.mirror_misses()
    assert m["total"] == 1 and "perda do dia" in m["lista"][0]["motivo"] and m["lista"][0]["dica"]
