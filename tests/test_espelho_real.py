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
    pf.cfg.pump_auto_real = True                 # 0.32.61: a compra automática da Base só vai para a real com o botão REAL dela
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
    msg = pf._sell(sim, 1.0, 1e-6, "stop", 0.0)                           # a saída veio antes de a compra real sair
    assert "prioridade" in msg and sim in pf.positions() and sim["exit_wait"]["why"] == "stop"   # 0.31.47: espera a real
    asyncio.run(pf._real_buy(it))
    kind, it2 = pf._rq.get_nowait()
    assert kind == "sell" and it2["frac"] == 1.0 and "espelho" in it2["why"] and "stop" in it2["why"]
    assert not [p for p in pf.positions() if not p.get("real")]           # a fictícia saiu junto com a real


def test_mirror_off_keeps_old_rule(tmp_path):
    pf = _pf(tmp_path)
    pf.cfg.pump_real_mirror = False
    pf.cfg.pump_auto_real = False
    pf.tokens[A] = {"price": 1e-6, "symbol": "ESP", "mcap_sol": 40.0}
    assert pf.manual_buy(A, auto="automático: Boost ON")["real"] in (None, "REAL desligada nesta aba (só fictícia)")
    assert not pf._real_buying


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



def test_real_orders_run_in_parallel_but_same_token_waits(tmp_path):
    """0.31.46: uma compra real esperando confirmar não segura a venda de OUTRO token; o mesmo token vai em ordem."""
    import asyncio
    pf = _pf(tmp_path)
    order, gate = [], None

    async def buy(it):
        order.append(("buy", it["mint"]))
        await gate.wait()
        order.append(("buy-ok", it["mint"]))

    async def sell(it):
        order.append(("sell", it["mint"]))
    pf._real_buy, pf._real_do_sell = buy, sell

    async def run():
        nonlocal gate
        gate = asyncio.Event()
        loop = asyncio.get_running_loop().create_task(pf.real_loop())
        pf._rq_put(("buy", {"mint": "A", "symbol": "A"}))
        pf._rq_put(("sell", {"mint": "A", "id": "x"}))
        pf._rq_put(("sell", {"mint": "B", "id": "y"}))
        for _ in range(20):
            await asyncio.sleep(0)
        assert ("sell", "B") in order and ("sell", "A") not in order   # B não esperou a compra de A
        gate.set()
        for _ in range(20):
            await asyncio.sleep(0)
        assert order.index(("buy-ok", "A")) < order.index(("sell", "A"))
        loop.cancel()
    asyncio.run(run())



def test_sim_takes_the_real_entry(tmp_path):
    """0.31.47: com a real ativa, a fictícia passa a ter a mesma hora e o mesmo preço efetivo de entrada da real."""
    pf = _pf(tmp_path)
    pf.real.buy = lambda mint, amt, other=False: _ok(amt)
    pf.tokens[A] = {"price": 1e-6, "symbol": "ESP", "mcap_sol": 40.0}
    pf.manual_buy(A, auto="automático: x")
    sim = [p for p in pf.positions() if not p.get("real")][0]
    _k, it = pf._rq.get_nowait()
    asyncio.run(pf._real_buy(it))
    real = [p for p in pf.positions() if p.get("real")][0]
    sim = [p for p in pf.positions() if not p.get("real")][0]           # positions() devolve cópias: ler de novo
    assert sim["open_t"] == real["open_t"] and sim["entrou_com_a_real"]
    assert abs(sim["sol_in"] / sim["tokens"] - real["sol_in"] / real["tokens"]) < 1e-15


async def _ok(amt):
    sim_eff = 1.1e-6                                   # a real entrou um pouco mais caro (10%)
    return {"ok": True, "signature": "B", "sol_spent": amt, "tokens": amt / sim_eff}


def test_suspect_price_is_only_noted(tmp_path):
    """0.31.51 (Jewlon): preço 20× a entrada só vira anotação no feed (aprendizado); nada é vendido por causa disso."""
    pf = _pf(tmp_path)
    pf.cfg.pump_real_enabled = False
    pf.tokens[A] = {"price": 1e-6, "symbol": "JEW", "mcap_sol": 40.0}
    pf.manual_buy(A)
    p = [x for x in pf.positions() if not x.get("real")][0]
    pf._note_suspect_price(A, p["price_in"] * 76)
    pf._note_suspect_price(A, p["price_in"] * 80)
    notes = [e for e in pf.feed if e.get("action") == "preço suspeito"]
    assert len(notes) == 1 and "76×" in notes[0]["reason"] and [x for x in pf.positions() if x["mint"] == A]


def test_explore_real_toggle_and_own_amount():
    """0.32.32 (pedido do dono): 'Também na carteira REAL' nas Proteções das automáticas e valor próprio na real."""
    from tests.test_auto_explorar import A as EA, _run
    from tests.test_auto_protecoes import _complete, _zero_fees
    import time
    pf = _zero_fees(pump_ar_max_h=5, pump_ar_max_open=5, pump_real_max_sol=0.05, pump_ar_real_sol=0.02)
    pf.cfg.pump_real_enabled = True
    pf.real = FakeReal()
    assert _run(pf, t=time.time()) == [EA]
    kind, it = pf._rq.get_nowait()
    _complete(pf._real_buy(it))
    assert pf.real.calls[0] == ("buy", EA, 0.02)                     # valor da real das automáticas
    pf2 = _zero_fees(pump_ex_real_on=False)
    pf2.cfg.pump_real_enabled = True
    pf2.real = FakeReal()
    assert _run(pf2, t=time.time()) == [EA]
    assert pf2._rq is None or pf2._rq.qsize() == 0                    # desligado: só a fictícia
