"""Sugestões do Bruxo + aprendizagem do bot (0.31.38): suspeitos fora da conta, funil do filtro e real × fictícia."""
import asyncio

from app.auto_trades import api_item, summary
from tests.test_espelho_real import A, _pf


def _row(i, pnl, pct):
    return {"id": str(i), "mint": "M", "real": False, "entrada_em": "2026-10-27T10:00:00+00:00",
            "saida_em": "2026-10-27T10:10:00+00:00", "pnl_sol": pnl, "pnl_pct": pct}


def test_big_gain_stays_in_totals_and_is_only_marked():
    rows = [_row(1, 134.14, 133475.5), _row(2, 0.01, 10.0), _row(3, -0.02, -40.0)]
    s = summary(rows)                                                     # 0.31.39: pedido do dono, continua na conta
    assert s["closed"] == 3 and s["suspects"] == 1 and abs(s["pnl_sol"] - 134.13) < 1e-9
    assert abs(s["suspects_sol"] - 134.14) < 1e-9
    assert api_item(rows[0], 0)["suspeito"] and not api_item(rows[1], 0)["suspeito"]


def test_funnel_counts_blocked_and_entered(tmp_path):
    pf = _pf(tmp_path)
    b = "Barr".ljust(40, "1") + "pump"
    pf.tokens[b] = {"price": 1e-6}
    pf._funnel_note({"mint": b, "symbol": "BAR", "pred": {"verdict": "chance alta"}}, "pressão 40% abaixo de 60%", 100.0)
    pf._funnel_note({"mint": A, "symbol": "ESP", "pred": {"verdict": "chance alta"}}, None, 100.0)
    pf.tokens[b]["price"] = 2e-6                                          # o barrado dobrou depois
    f = pf.explore_funnel(now=200.0)
    assert f["vistos"] == 2 and f["entrou"] == 1 and f["barrados"] == 1 and f["chance_alta"] == 2
    assert f["motivos"][0]["motivo"] == "pressão 40% abaixo de 60%" and f["subiram_50"] == 1


def test_mirror_pairs_real_next_to_sim(tmp_path):
    pf = _pf(tmp_path)
    pf.tokens[A] = {"price": 1e-6, "symbol": "ESP", "mcap_sol": 40.0}
    pf.manual_buy(A, auto="automático: x")
    sim = [p for p in pf.positions() if not p.get("real")][0]
    _k, it = pf._rq.get_nowait()
    asyncio.run(pf._real_buy(it))
    pf._sell(sim, 1.0, 1.2e-6, "alvo", 0.0)
    _k, it = pf._rq.get_nowait()
    asyncio.run(pf._real_do_sell(it))
    pairs = pf.mirror_pairs()
    assert len(pairs) == 1 and pairs[0]["sim_pct"] is not None and pairs[0]["real_pct"] is not None
