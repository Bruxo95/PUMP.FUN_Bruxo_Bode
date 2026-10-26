"""Previsão na Base da pump.fun (0.25.0): lixo, fraco, possível, chance alta e suspeito; acerto medido aos 5 min."""
import time
from datetime import datetime, timezone

from tests.test_api import UA, env, tok  # noqa: F401  (fixture env)


def _lab():
    from app.pumpfun import PumpMarket
    from app.tokenlab import TokenLab
    m = PumpMarket()
    return TokenLab(m), m


def _teach(lab, now):
    when = datetime.fromtimestamp(now - 3600, timezone.utc).isoformat(timespec="seconds")
    for i in range(40):
        lab.done.append({"mint": f"A{i}", "label": "2x" if i < 30 else "morreu", "mcap0": 30.0, "snaps": {"1": 50.0},
                         "dev_buy": 2.0, "created_at": when, "boost": i < 10})
    for i in range(60):
        lab.done.append({"mint": f"B{i}", "label": "2x" if i < 3 else "morreu", "mcap0": 30.0, "snaps": {"1": 31.0},
                         "dev_buy": 0.0, "created_at": when})


def test_learned_signals_drive_the_verdict():
    lab, _ = _lab()
    now = time.time()
    _teach(lab, now)
    hi = lab.predict({"mint": "X1", "symbol": "AAA", "mcap0": 30.0, "snaps": {"1": 50.0}, "dev_buy": 2.0, "t0": now}, now)
    lo = lab.predict({"mint": "X2", "symbol": "BBB", "mcap0": 30.0, "snaps": {"1": 31.0}, "dev_buy": 0.0, "t0": now}, now)
    assert hi["verdict"] == "chance alta" and hi["chance"] > 80 and any("1 min" in w for w in hi["why"])
    assert lo["verdict"] == "fraco" and lo["chance"] < 5


def test_hard_rules_mark_trash_and_suspicious():
    lab, m = _lab()
    now = time.time()
    assert lab.predict({"mint": "S", "symbol": "S", "mcap0": 28.0, "snaps": {"1": 721.0}}, now)["verdict"] == "suspeito"
    for i in range(3):
        lab.on_create({"mint": f"Clone{i}".ljust(44, "1"), "marketCapSol": 28.0, "symbol": "SIMUL"}, now - 60)
    p = lab.predict({"mint": "C", "symbol": "simul", "mcap0": 28.0, "snaps": {"1": 40.0}}, now)
    assert p["verdict"] == "lixo" and "clones" in p["why"][0]
    lab.creators["Dev"] = {"tokens": 3, "x2": 0, "rugs": 2}
    assert lab.predict({"mint": "D", "symbol": "D", "creator": "Dev", "mcap0": 28.0, "snaps": {"1": 40.0}}, now)["verdict"] == "lixo"
    assert lab.predict({"mint": "E", "symbol": "E", "mcap0": 28.0, "snaps": {"1": 40.0, "5": 20.0}}, now)["verdict"] == "lixo"


def test_prediction_at_5_min_is_saved_and_its_hit_rate_learned():
    lab, m = _lab()
    t0 = time.time() - 4000
    mint = "Pred".ljust(40, "1") + "pump"
    lab.on_create({"mint": mint, "marketCapSol": 30.0, "symbol": "PRD"}, t0)
    for mins, mc in zip((1, 5, 15, 60), (40.0, 70.0, 90.0, 80.0)):
        m.tokens.setdefault(mint, {})["mcap_sol"] = mc
        lab.observe(t0 + mins * 60 + 1, [mint])
    row = lab.done[-1]
    assert row["label"] == "2x" and row["pred5"] in ("fraco", "possível", "chance alta") and row["chance5"] is not None
    tab = next(tb for tb in lab.lessons(time.time() + 120)["tables"] if tb["nome"].startswith("Previsão"))
    assert tab["linhas"][0]["n"] == 1 and tab["linhas"][0]["up_pct"] == 100.0


def test_base_route_has_predictions_and_trash_switch(env):
    c, hub = env["c"], env["hub"]
    t0 = time.time() - 120
    mint = "Rota".ljust(40, "1") + "pump"
    hub.lab.on_create({"mint": mint, "marketCapSol": 30.0, "symbol": "ROTA"}, t0)
    hub.lab.live[mint]["snaps"] = {"1": 45.0}
    r = c.get("/api/pump/base", headers=tok(UA)).json()
    assert r["hide_trash"] is False and r["rising"][0]["pred"]["verdict"] in ("fraco", "possível", "chance alta")
    assert c.post("/api/pump/settings", json={"pump_base_hide_trash": True}, headers=tok(UA)).json()["applied"]
    assert c.get("/api/pump/base", headers=tok(UA)).json()["hide_trash"] is True
