"""Relatório do dia (0.31.5): fotos da Visão geral a cada 30 min no banco, diagnóstico, sugestões e fechamento do dia."""
import asyncio
import json
import time
from datetime import datetime, timezone

import httpx

from tests.test_api import UA, UB, env, tok  # noqa: F401  (fixture env)

LOSER = "Perdedor".ljust(44, "1")


def _iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


def _trades(pf, now):
    for i in range(10):
        stop = i < 6
        pf._save_trade({"wallet": LOSER if i < 4 else "Outro".ljust(44, "1"), "mint": f"M{i}", "sol_in": 0.1,
                        "pnl_sol": -0.03 if stop else 0.01, "pnl_pct": -30.0 if stop else 10.0, "fees_sol": 0.006,
                        "best_pct": 40.0 if i < 3 else 5.0, "reason": "stop de perda (−30%)" if stop else "trader vendeu 100%",
                        "closed_at": _iso(now - 60), "real": False, "lag_s": 7.0})


def test_report_diagnoses_and_suggests(tmp_path):
    from app.daily import build, day_of
    from tests.test_pump import _pump
    pf = _pump(tmp_path, paid=False)
    now = time.time()
    _trades(pf, now)
    rep = build(pf, day_of(now), [{"t": now - 3600, "saldo": 5.0}, {"t": now, "saldo": 4.7}])
    assert rep["trades"] == 10 and rep["acerto"] == 0.4 and rep["stops"] == 6 and rep["gave_back"] == 3
    areas = " ".join(s["texto"] for s in rep["suggestions"])
    assert "Acerto do dia 40%" in areas and "stop de perda" in areas and "+30% ou mais" in areas
    assert "Perd…1111" in areas and "Atraso médio" in areas and "caiu -6.0%" in areas
    assert rep["by_exit"][0]["nome"] == "stop de perda"


def test_hub_saves_points_and_closes_previous_day_with_telegram(env):
    from app.daily import day_of
    c, hub, db = env["c"], env["hub"], env["db"]
    c.get("/api/pump", headers=tok(UA))
    pf = hub.engines[UA]
    now = time.time()
    prev = day_of(now - 86400)
    db.tables["daily_report"].append({"user_id": UA, "dia": prev, "data": {"points": [{"t": now - 90000, "saldo": 5.0}]}})
    sent = []
    hub.http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: (sent.append(json.loads(r.content)), httpx.Response(200, json={"ok": True}))[1]))
    pf.keys.set("telegram_bot_token", "123456789:" + "A" * 35)
    pf.keys.set("telegram_chat_id", "987654321")
    pf.cfg.pump_tg_on = True
    assert asyncio.run(hub.save_daily(now)) == 1
    assert asyncio.run(hub.save_daily(now + 60)) == 1
    rows = {r["dia"]: r["data"] for r in db.tables["daily_report"]}
    assert len(rows[day_of(now)]["points"]) == 2 and rows[prev]["closed"] is True
    assert len(sent) == 1 and sent[0]["text"].startswith("PUMP FUN COPY · relatório de " + prev)
    r = c.get("/api/pump/daily", headers=tok(UA)).json()
    assert r["today"] == day_of(time.time()) and len(r["report"]["points"]) >= 2 and r["report"]["suggestions"]
    assert any(d["dia"] == prev and d["closed"] for d in r["days"])
    old = c.get("/api/pump/daily?dia=" + prev, headers=tok(UA)).json()
    assert old["report"]["closed"] is True
    assert c.get("/api/pump/daily", headers=tok(UB, "b@x.com")).status_code == 403
