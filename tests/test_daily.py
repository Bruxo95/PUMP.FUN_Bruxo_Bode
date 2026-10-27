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


def test_past_days_are_rebuilt_saved_and_studied(env):
    """0.31.6: dias que já passaram viram relatório (a partir dos trades) e entram no aprendizado de vários dias."""
    from app.daily import day_of
    c, hub, db = env["c"], env["hub"], env["db"]
    c.get("/api/pump", headers=tok(UA))
    pf = hub.engines[UA]
    now = time.time()
    for d in (1, 2, 3):
        _trades(pf, now - d * 86400)
    assert asyncio.run(hub.backfill_daily(now)) == 3
    assert asyncio.run(hub.backfill_daily(now)) == 0                       # uma vez só
    saved = {r["dia"]: r["data"] for r in db.tables["daily_report"]}
    d1 = day_of(now - 86400)
    assert saved[d1]["closed"] and saved[d1]["backfilled"] and saved[d1]["trades"] == 10
    assert saved[d1]["equity_end"] is not None
    r = c.get("/api/pump/daily", headers=tok(UA)).json()
    st = r["study"]
    assert st["days"] >= 3 and st["positive_days"] == 0
    assert any(x["tipo"] == "muitos_stops" and x["dias"] >= 3 for x in st["recurring"])
    assert any(s["area"] == "repetido" for s in st["suggestions"])


def test_report_lists_each_trade_with_time_and_by_hour(tmp_path):
    """0.31.8: cada trade do dia com horário de entrada e saída, resultado por hora e horário ruim."""
    from app.daily import blocks, build, day_of, hhmm
    from tests.test_pump import _pump
    pf = _pump(tmp_path, paid=False)
    base = (time.time() - 3 * 3600) // 3600 * 3600 + 60                 # começo de hora: 3 horas certinhas
    for i in range(9):
        c = base + (i // 3) * 3600 + i * 60
        pf._save_trade({"wallet": "W", "symbol": f"T{i}", "mint": "M" * 40, "sol_in": 0.1, "hold_s": 125,
                        "pnl_sol": -0.05 if i < 3 else 0.01, "pnl_pct": -50.0 if i < 3 else 10.0, "reason": "stop de perda" if i < 3 else "alvo",
                        "opened_at": _iso(c - 125), "closed_at": _iso(c), "real": False})
    day = day_of(base + 10)
    rep = build(pf, day, [])
    tl = [x for x in rep["trades_list"]]
    assert tl and tl[0]["entrada"] == hhmm(base - 125) and tl[0]["saida"] == hhmm(base) and tl[0]["duracao_s"] == 125
    if all(day_of(base + k * 3600) == day for k in range(3)):
        assert len(rep["by_hour"]) == 3 and any(s["tipo"] == "horario_ruim" for s in rep["suggestions"])
    txt = " ".join(t for _, t in blocks(rep, None, "x"))
    assert "Trades do dia com horário" in txt and tl[0]["entrada"] in txt and "T0" in txt



def test_daily_report_follows_the_real_wallet():
    """0.31.45: com real=True o relatório usa só os trades reais (o fictício fica de fora) e monta a curva do dia."""
    from app.daily import build, day_of
    import time as _t

    class P:
        feed = []
        def trades(self, n):
            from datetime import datetime, timezone
            now, ago = datetime.now(timezone.utc).isoformat(), datetime.fromtimestamp(_t.time() - 60, timezone.utc).isoformat()
            return [{"real": True, "pnl_sol": 0.02, "sol_in": 0.05, "closed_at": now, "opened_at": ago, "symbol": "RL", "mint": "R" * 40},
                    {"pnl_sol": 300.0, "sol_in": 0.05, "closed_at": now, "opened_at": ago, "symbol": "SIM", "mint": "S" * 40}]
        def _c(self, k, d):
            return d
    rep = build(P(), day_of(_t.time()), None, real=True)
    assert rep["real"] is True and rep["trades"] == 1 and rep["pnl_sol"] == 0.02
    assert rep["best_trades"][0]["token"] == "RL" and rep["points"][-1]["resultado"] == 0.02 and rep["equity_end"] is None
    sim = build(P(), day_of(_t.time()), None)
    assert sim["trades"] == 1 and sim["pnl_sol"] == 300.0



def test_real_report_learns_from_failures():
    """0.31.49: falhas da real do dia viram sugestão com a dica (o aprendizado de vários dias junta as repetidas)."""
    from datetime import datetime, timezone
    from app.daily import build, day_of, study
    import time as _t
    now = datetime.now(timezone.utc).isoformat()

    class P:
        feed = [{"at": now, "action": "REAL falhou", "symbol": "NEWMOON", "mint": "N" * 40,
                 "reason": "PumpPortal auto: transação recusada pela verificação: x"},
                {"at": now, "action": "REAL falhou", "symbol": "SPAWN", "mint": "S" * 40, "reason": "jupiter: slippage excedido (0x1771)"}]

        def trades(self, n):
            return []

        def _c(self, k, d):
            return d
    rep = build(P(), day_of(_t.time()), None, real=True)
    assert len(rep["real_misses"]) == 2
    tipos = {s["tipo"] for s in rep["suggestions"]}
    assert "falha_real_verificação" in tipos and "falha_real_slippage" in tipos
    assert study([rep])["recurring"][0]["tipo"].startswith("falha_real_")
