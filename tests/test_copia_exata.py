"""0.32.158 (pedido do dono, 02/11): cópia exata — com real e fictícia ligadas, a real manda e a fictícia acompanha.
Tudo com carteira falsa: nenhuma transação de verdade."""
import asyncio

from tests.test_espelho_real import _pf
from tests.test_pump import _W, _ev


def _exact(tmp_path):
    pf = _pf(tmp_path, pump_extra_slip_pct=0.0)
    pf.cfg.pump_real_mirror = True
    pf.cfg.pump_real_exact = True
    pf.add_manual(_W)
    return pf


def test_sim_is_undone_when_real_does_not_buy(tmp_path):
    pf = _exact(tmp_path)
    m = "Exa1".ljust(40, "1") + "pump"
    pf.on_message(_ev("buy", _W, m, 1.0, 1e6, 30, 3e7))
    assert [p["real"] for p in pf.positions()] == [False]
    kind, it = pf._rq.get_nowait()
    assert kind == "buy" and it["sim_id"]

    async def no(mint, amt, other=False):
        return {"ok": False, "reason": "saldo insuficiente"}
    pf.real.buy = no
    asyncio.run(pf._real_buy(it))
    assert not pf.positions() and not pf.trades()                       # a fictícia não fica sozinha
    assert pf.feed[0]["action"] == "FICTÍCIA desfeita"


def test_sim_takes_real_size_and_leaves_with_real(tmp_path):
    pf = _exact(tmp_path)
    m = "Exa2".ljust(40, "1") + "pump"
    pf.on_message(_ev("buy", _W, m, 1.0, 1e6, 30, 3e7))
    kind, it = pf._rq.get_nowait()

    async def buy(mint, amt, other=False):
        return {"ok": True, "signature": "B", "sol_spent": 0.02, "tokens": 0.02 / 1.2e-6}   # a real entrou 20% mais caro
    pf.real.buy = buy
    asyncio.run(pf._real_buy(it))
    real = [p for p in pf.positions() if p.get("real")][0]
    sim = [p for p in pf.positions() if not p.get("real")][0]
    assert abs(sim["sol_in"] - real["sol_in"]) < 1e-9                   # mesmo valor
    assert abs(sim["sol_in"] / sim["tokens"] - real["sol_in"] / real["tokens"]) < 1e-12   # mesmo preço de entrada
    pf.tokens[m]["price"] = 0.7e-6
    pf._real_sell(real, 1.0, "stop de perda (−40%)")                    # a real saiu sozinha (stop dela)
    kind, it = pf._rq.get_nowait()
    asyncio.run(pf._real_do_sell(it))
    assert not pf.positions()                                           # a fictícia saiu junto
    t = [x for x in pf.trades() if not x.get("real")][0]
    assert "junto com a real" in t["reason"]


def test_without_exact_mirror_keeps_old_behavior(tmp_path):
    pf = _exact(tmp_path)
    pf.cfg.pump_real_exact = False
    m = "Exa3".ljust(40, "1") + "pump"
    pf.on_message(_ev("buy", _W, m, 1.0, 1e6, 30, 3e7))
    kind, it = pf._rq.get_nowait()

    async def no(mint, amt, other=False):
        return {"ok": False, "reason": "x"}
    pf.real.buy = no
    asyncio.run(pf._real_buy(it))
    assert [p["real"] for p in pf.positions()] == [False]               # a fictícia continua (como antes)


def test_sim_limits_do_not_block_when_real_decides(tmp_path):
    pf = _exact(tmp_path)
    pf.cfg.pump_max_open = 0                                            # a fictícia "lotada" não barra: quem decide é a real
    m = "Exa4".ljust(40, "1") + "pump"
    pf.on_message(_ev("buy", _W, m, 1.0, 1e6, 30, 3e7))
    kind, it = pf._rq.get_nowait()
    assert kind == "buy" and it["sim_id"] and [p["real"] for p in pf.positions()] == [False]


def _opened(tmp_path, m):
    """Cópia exata com a real comprada: devolve (pf, real, fictícia)."""
    pf = _exact(tmp_path)
    pf.on_message(_ev("buy", _W, m, 1.0, 1e6, 30, 3e7))
    kind, it = pf._rq.get_nowait()

    async def buy(mint, amt, other=False):
        return {"ok": True, "signature": "B", "sol_spent": 0.02, "tokens": 0.02 / 1e-6}
    pf.real.buy = buy
    asyncio.run(pf._real_buy(it))
    real = [p for p in pf.positions() if p.get("real")][0]
    sim = [p for p in pf.positions() if not p.get("real")][0]
    return pf, real, sim


def test_trader_sell_real_first_and_sim_closes_at_real_price(tmp_path):
    m = "Exa5".ljust(40, "1") + "pump"
    pf, real, sim = _opened(tmp_path, m)
    pf.on_message(_ev("sell", _W, m, 1.5, 1e6, 30, 3e7 / 1.5, newTokenBalance=0))
    kind, it = pf._rq.get_nowait()
    assert kind == "sell" and it["id"] == real["id"] and it["frac"] == 1.0
    sims = [p for p in pf.positions() if not p.get("real")]
    assert sims and sims[0].get("exit_follow") and not pf.trades()      # a fictícia espera a venda real

    async def sell(mint, frac, other=False):
        return {"ok": True, "signature": "S", "sol_received": 0.028, "tokens_left": 0.0}
    pf.real.sell = sell
    asyncio.run(pf._real_do_sell(it))
    assert not pf.positions()
    rt = [t for t in pf.trades() if t.get("real")][0]
    st = [t for t in pf.trades() if not t.get("real")][0]
    assert abs(rt["pnl_sol"] - st["pnl_sol"]) < 1e-6 and abs(rt["pnl_pct"] - st["pnl_pct"]) < 0.05   # mesmo resultado


def test_sim_own_stop_asks_real_first_and_waits(tmp_path):
    m = "Exa6".ljust(40, "1") + "pump"
    pf, real, sim = _opened(tmp_path, m)
    pf.tokens[m]["price"] = 0.5e-6                                      # −50%: as duas batem o stop de 40%
    pf._check_stops(m, 0)
    kind, it = pf._rq.get_nowait()
    assert kind == "sell" and it["id"] == real["id"] and pf._rq.qsize() == 0
    sims = [p for p in pf.positions() if not p.get("real")]
    assert sims and sims[0].get("exit_follow") and not pf.trades()


def test_sim_waiting_without_real_closes_at_market(tmp_path):
    m = "Exa7".ljust(40, "1") + "pump"
    pf, real, sim = _opened(tmp_path, m)
    sim["exit_follow"] = {"frac": 1.0, "why": "trader vendeu 100%", "t": 0}
    pf._save_pos(sim)
    pf._del_pos(real)                                                   # a real sumiu (vendida por fora)
    pf._check_stops(m, 0)
    assert not pf.positions() and pf.trades()[0]["reason"] == "trader vendeu 100%"


def test_button_buy_sim_limit_does_not_block_and_sim_is_undone_when_real_is_blocked(tmp_path):
    from tests.test_espelho_real import A
    pf = _exact(tmp_path)
    pf.tokens[A] = {"price": 1e-6, "symbol": "ESP", "mcap_sol": 40.0}
    pf.cfg.pump_max_open = 0                                            # fictícia "lotada": a real decide
    r = pf.manual_buy(A)
    assert r["sim"].startswith("comprou") and r["real"].startswith("enviando")
    B = "Btn2".ljust(40, "1") + "pump"
    pf.tokens[B] = {"price": 1e-6, "symbol": "BB", "mcap_sol": 40.0}
    pf.cfg.pump_real_max_open = 1                                       # a real está no limite (a compra de A na fila)
    r = pf.manual_buy(B)
    assert r["sim"].startswith("desfeita") and not [p for p in pf.positions() if p["mint"] == B]


def test_exact_fixes_sim_price_even_when_far_from_real(tmp_path):
    """0.32.214 (MEOWTH): a fictícia entrou num preço 300× errado; na cópia exata vale o preço que a REAL pagou."""
    pf = _exact(tmp_path)
    m = "Exa9".ljust(40, "1") + "pump"
    pf.on_message(_ev("buy", _W, m, 1.0, 1e6, 30, 3e7))
    kind, it = pf._rq.get_nowait()
    sim = [p for p in pf.positions() if not p.get("real")][0]
    sim["best_pct"] = 7000.0
    px_real = sim["sol_in"] / sim["tokens"] * 300

    async def buy(mint, amt, other=False):
        return {"ok": True, "signature": "B", "sol_spent": 0.02, "tokens": 0.02 / px_real}
    pf.real.buy = buy
    asyncio.run(pf._real_buy(it))
    real = [p for p in pf.positions() if p.get("real")][0]
    sim = [p for p in pf.positions() if not p.get("real")][0]
    assert abs(sim["sol_in"] / sim["tokens"] - real["sol_in"] / real["tokens"]) < 1e-12
    assert "best_pct" not in sim and any(f["action"] == "preço corrigido" for f in pf.feed)


def test_exact_real_does_not_open_a_separate_position_when_sim_already_holds(tmp_path):
    """0.32.214 (clippy): a fictícia tinha o token de antes (REAL desligada); depois de ligar, a REAL não entra separada."""
    pf = _exact(tmp_path)
    m = "ExaA".ljust(40, "1") + "pump"
    pf.cfg.pump_real_enabled = False
    pf.on_message(_ev("buy", _W, m, 1.0, 1e6, 30, 3e7))
    assert [p["real"] for p in pf.positions()] == [False]
    pf.cfg.pump_real_enabled = True
    while pf._rq is not None and not pf._rq.empty():
        pf._rq.get_nowait()
    pf.on_message(_ev("buy", _W, m, 0.5, 4e5, 31, 3e7))
    assert pf._rq is None or pf._rq.empty()
    assert any(f["action"] == "REAL não copiou" and "cópia exata" in f["reason"] for f in pf.feed)
