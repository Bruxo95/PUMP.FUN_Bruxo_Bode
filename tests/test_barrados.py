"""0.32.21 (pedido do dono): Comprar escolhe a carteira; barrados do Explorar que subiram entram sozinhos SÓ na fictícia.
Tudo com carteira falsa: nenhuma transação de verdade."""
import time

from tests.test_espelho_real import _pf

M = "Barr".ljust(40, "1") + "pump"


def _row(pf, why, vol=50000, chg=1.0):
    now = time.time()
    pf.tokens[M] = {"price": 1e-6 * chg, "symbol": "BAR", "mcap_sol": 40.0, "last_t": now}
    pf._ex_funnel = {M: {"first_t": now - 600, "symbol": "BAR", "px0": 1e-6, "why": why, "entrou": False, "t": now, "vol": vol}}
    return now


def test_buy_button_target_sim_or_real(tmp_path):
    pf = _pf(tmp_path)                                     # real ligada (carteira falsa)
    pf.tokens[M] = {"price": 1e-6, "symbol": "BAR", "mcap_sol": 40.0}
    r = pf.manual_buy(M, target="sim")
    assert r["sim"].startswith("comprou") and r["real"] is None and (pf._rq is None or pf._rq.qsize() == 0)
    m2 = "Barz".ljust(40, "1") + "pump"
    pf.tokens[m2] = {"price": 1e-6, "symbol": "BAZ", "mcap_sol": 40.0}
    r = pf.manual_buy(m2, target="real")
    assert r["sim"] == "não pedida (só real)" and r["real"].startswith("enviando")
    assert not [p for p in pf.positions() if p["mint"] == m2]
    kind, it = pf._rq.get_nowait()
    assert kind == "buy" and it["sim_id"] is None


def test_barred_that_rose_enters_only_sim(tmp_path):
    pf = _pf(tmp_path)
    pf.role = "admin"
    now = _row(pf, "veredito não é chance alta", chg=2.0)
    assert pf.barred_auto(now) == []                       # desligado por padrão
    pf.cfg.pump_bar_auto_on = True
    out = pf.barred_auto(now)
    assert len(out) == 1 and out[0]["r"]["sim"].startswith("comprou")
    p = [p for p in pf.positions() if p["mint"] == M][0]
    assert p["real"] is False and p["origem"] == "barrado" and "subiu" in p["auto"]
    assert pf._rq is None or pf._rq.qsize() == 0           # nunca na real
    assert pf.barred_auto(now) == []                       # um por token


def test_barred_by_safety_or_low_volume_never_enters(tmp_path):
    pf = _pf(tmp_path)
    pf.role = "admin"
    pf.cfg.pump_bar_auto_on = True
    now = _row(pf, "criador na lista negra", chg=3.0)
    assert pf.barred_auto(now) == []
    now = _row(pf, "veredito não é chance alta", vol=100, chg=3.0)
    assert pf.barred_auto(now) == []


def test_early_entry_simulation_per_trigger(tmp_path):
    """0.32.22: mede o que teria dado entrar quando o barrado subia +10/20/30/50% (só mede, não compra)."""
    pf = _pf(tmp_path)
    now = _row(pf, "veredito não é chance alta", chg=1.15)
    pf.barred_track(now)                                   # +15%: abre os gatilhos de +10%
    v = pf._ex_funnel[M]["v"]
    assert "10" in v and "20" not in v
    pf.tokens[M].update(price=1e-6 * 1.15 * 0.5, last_t=now + 30)    # caiu 50% desde a entrada: stop
    pf.barred_track(now + 30)
    assert v["10"]["why"] == "stop" and v["10"]["out"] < 0
    rows = {r["gatilho"]: r for r in pf.barred_sim()}
    assert rows[10]["entradas"] == 1 and rows[10]["acerto"] == 0 and rows[20]["entradas"] == 0
    assert pf._ex_funnel[M]["hi"] >= 15 and pf._ex_funnel[M]["lo"] <= -40
    assert not pf.positions()                              # nada foi comprado


def test_buy_from_barred_list_keeps_origin_label(tmp_path):
    """0.32.29: Comprar na lista de barrados guarda a origem (rótulo 'Barrado que subiu (você comprou)' em Posições)."""
    pf = _pf(tmp_path)
    pf.tokens[M] = {"price": 1e-6, "symbol": "BAR", "mcap_sol": 40.0}
    pf.manual_buy(M, target="sim", origem="barrado_btn")
    assert [p["origem"] for p in pf.positions() if p["mint"] == M] == ["barrado_btn"]


def test_absurd_rise_is_ignored(tmp_path):
    """0.32.30 (HOUSECOIN +5.505%): alta de 20× ou mais sai da simulação e da entrada automática."""
    pf = _pf(tmp_path)
    pf.role = "admin"
    pf.cfg.pump_bar_auto_on = True
    now = _row(pf, "veredito não é chance alta", chg=56.0)
    pf.barred_track(now)
    assert pf._ex_funnel[M].get("suspeito") and not pf._ex_funnel[M].get("v")
    assert pf.barred_auto(now) == []
