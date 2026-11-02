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
