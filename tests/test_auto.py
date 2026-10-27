"""Compra automática da Base da pump.fun (0.27.0): roda no servidor, começa desligada."""
import time

from tests.test_api import UA, env, tok  # noqa: F401  (fixture env)
from tests.test_pump import _pump

A = "AutoA".ljust(40, "1") + "pump"
B = "AutoB".ljust(40, "1") + "pump"


def _row(mint, boost=True, verdict="possível", age=3.0, chance=15.0):
    return {"mint": mint, "symbol": mint[:5], "age_min": age, "boost": {"active": boost},
            "pred": {"verdict": verdict, "chance": chance}}


def _pf(tmp_path, **kw):
    kw = {"pump_ar_min_age_min": 0, "pump_ar_fresh_on": False, "pump_ar_smart_on": False, **kw}   # travas 0.31.0
    pf = _pump(tmp_path, paid=False, **kw)
    for m in (A, B):
        pf.tokens[m] = {"price": 1e-6, "symbol": m[:5], "mcap_sol": 40.0}
    return pf


def test_auto_buy_is_off_by_default(tmp_path):
    pf = _pf(tmp_path)
    assert pf.cfg.pump_auto_on is False and pf.cfg.pump_auto_real is False
    assert pf.auto_check([_row(A)]) == [] and not pf.positions()


def test_auto_buys_boosted_tokens_once_and_skips_trash(tmp_path):
    pf = _pf(tmp_path, pump_auto_on=True)
    assert pf.auto_check([_row(A, verdict="lixo"), _row(B, age=50.0)]) == []          # lixo e velho demais (máx. 45 min desde a 0.31.0)
    assert pf.auto_check([_row(A, boost=False, verdict="chance alta")]) == []          # chance alta está OFF
    assert pf.auto_check([_row(A)]) == [A]
    p = pf.positions()[0]
    assert p["auto"].startswith("automático: Boost ON") and p["stop_pct"] == 30.0 and p["boost_tp"] == 80.0
    assert pf.auto_check([_row(A)]) == [] and len(pf.positions()) == 1                 # não repete o token
    assert any(e.get("action") == "comprou (automático)" for e in pf.feed)


def test_auto_respects_hourly_limit_and_chance_rule(tmp_path):
    pf = _pf(tmp_path, pump_auto_on=True, pump_auto_boost=False, pump_auto_chance=True, pump_auto_max_h=1)
    assert pf.auto_check([_row(A, boost=False, verdict="chance alta"), _row(B, boost=False, verdict="chance alta")]) == [A]


def test_auto_never_buys_real_unless_allowed(tmp_path):
    pf = _pump(tmp_path, paid=True)
    pf.cfg.pump_real_enabled = True
    pf.cfg.pump_real_mirror = False                      # 0.31.37: com o espelho ligado a real copia (test_espelho_real)
    pf.tokens[A] = {"price": 1e-6, "symbol": "AUT", "mcap_sol": 40.0}
    r = pf.manual_buy(A, auto="automático: Boost ON")
    assert r["real"] is None and not pf._real_buying


def test_monitor_runs_auto_buy_for_who_turned_it_on(env):
    from app.monitor import SharedMonitor
    c, hub = env["c"], env["hub"]
    assert c.post("/api/pump/settings", json={"pump_auto_on": True, "pump_ar_min_age_min": 0, "pump_ar_fresh_on": False,
                                                 "pump_ar_smart_on": False}, headers=tok(UA)).json()["applied"]
    mon = SharedMonitor(hub)
    t0 = time.time() - 180
    hub.lab.on_create({"mint": A, "marketCapSol": 30.0, "symbol": "AUT"}, t0)
    hub.lab.live[A]["snaps"] = {"1": 45.0}
    hub.market.tokens[A] = {"price": 1.5e-6, "symbol": "AUT", "mcap_sol": 45.0}
    hub.market.boosts[A] = {"active": True, "t": time.time()}
    assert mon.auto_once() == 1 and hub.engines[UA].positions()[0]["mint"] == A
    assert mon.auto_once() == 0
