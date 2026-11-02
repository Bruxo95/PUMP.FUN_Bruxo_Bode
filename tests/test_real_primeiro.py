"""0.32.156 (pedido do dono, casos inu e WB de 01/11): com real e fictícia no mesmo token do mesmo trader, a REAL decide junto
com a fictícia e sai primeiro. Tudo com carteira falsa: nenhuma transação de verdade."""
import asyncio

from tests.test_espelho_real import _pf
from tests.test_pump import _W, _ev


def _both(tmp_path, mint, real_tokens):
    pf = _pf(tmp_path, pump_extra_slip_pct=0.0)
    pf.cfg.pump_real_mirror = False                     # como na conta do dono: a real copia o trader direto
    pf.add_manual(_W)
    pf.on_message(_ev("buy", _W, mint, 1.0, 1e6, 30, 3e7))                   # entra a 1e-6
    kind, it = pf._rq.get_nowait()
    assert kind == "buy" and not it.get("sim_id")
    pf.real.buy = lambda m, amt, other=False: asyncio.sleep(0, {"ok": True, "signature": "B", "sol_spent": amt, "tokens": real_tokens})
    asyncio.run(pf._real_buy(it))
    return pf


def test_real_sells_with_sim_when_trader_exits_even_if_real_entry_was_worse(tmp_path):
    m = "Wbwb".ljust(40, "1") + "pump"
    pf = _both(tmp_path, m, 0.02 / 1.5e-6)              # a real entrou 50% mais caro
    pf.on_message(_ev("sell", _W, m, 1.3, 1e6, 30, 3e7 / 1.3, newTokenBalance=0))   # trader sai a 1,3e-6
    kind, it = pf._rq.get_nowait()
    assert kind == "sell" and it["frac"] == 1.0          # antes: a real ficava "segurando" no prejuízo
    assert not [p for p in pf.positions() if not p.get("real")] and pf.trades()[0]["pnl_sol"] > 0
    assert pf._rq.qsize() == 0                           # a fictícia fechou sem pedir a venda real de novo
    assert not any(f.get("action") == "segurando" for f in pf.feed)


def test_real_holds_with_sim_and_leaves_when_sim_leaves(tmp_path):
    m = "Inui".ljust(40, "1") + "pump"
    pf = _both(tmp_path, m, 0.02 / 1e-6)
    pf.on_message(_ev("sell", _W, m, 0.8, 1e6, 30, 3e7 / 0.8, newTokenBalance=0))   # trader sai no prejuízo: as duas seguram
    assert all(p.get("hold_profit") for p in pf.positions()) and pf._rq.qsize() == 0
    pf.tokens[m]["price"] = 1.2e-6
    real = [p for p in pf.positions() if p.get("real")][0]
    real["price_in"] = 2e-6                              # a real continua no prejuízo pelo preço dela
    sim = [p for p in pf.positions() if not p.get("real")][0]
    pf._sell(sim, 1.0, 1.2e-6, "segurou até ficar positivo (+15.0% líquido)", 0.0)
    kind, it = pf._rq.get_nowait()
    assert kind == "sell" and it["id"] == real["id"] and "junto com a fictícia" in it["why"]
