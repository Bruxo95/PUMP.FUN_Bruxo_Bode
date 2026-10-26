"""Relatório de cada menu dentro do relatório do dia (0.31.9)."""
import time

from tests.test_api import UA, W, env, tok  # noqa: F401  (fixture env)
from tests.test_daily import _iso, _trades


def test_each_menu_reports_and_suggests(env):
    from app.daily import day_of
    from app.modules_report import build
    c, hub = env["c"], env["hub"]
    c.get("/api/pump", headers=tok(UA))
    pf = hub.engines[UA]
    now = time.time()
    _trades(pf, now)
    for i in range(5):
        pf._save_trade({"wallet": "manual", "origem": "explorar", "auto": True, "mint": f"E{i}", "sol_in": 0.05, "pnl_sol": -0.02,
                        "pnl_pct": -40.0, "reason": "stop de perda (−25%)", "closed_at": _iso(now - 30), "real": False})
    c.post("/api/pump/study", json={"wallet": W, "action": "add"}, headers=tok(UA))
    menus = build(hub, pf, day_of(now), True)
    names = [m["menu"] for m in menus]
    for want in ("Top traders (cópias)", "Carteiras em estudo", "Explorar", "Relatórios (E se…)", "Opções novas de cópia",
                 "Base da pump.fun", "Radar de KOLs", "Lista negra"):
        assert want in names, (want, names)
    ex = next(m for m in menus if m["menu"] == "Explorar")
    assert any(s["tipo"] == "menu:Explorar:automatica_no_prejuizo" for s in ex["sugestoes"])
    op = next(m for m in menus if m["menu"] == "Opções novas de cópia")
    assert any("venda em partes" in s["texto"].lower() for s in op["sugestoes"])
    past = build(hub, pf, day_of(now - 86400), False)
    assert "Base da pump.fun" not in [m["menu"] for m in past]               # dado ao vivo só no dia de hoje


def test_menus_go_into_daily_pdf_ai_and_study(env):
    c, hub = env["c"], env["hub"]
    c.get("/api/pump", headers=tok(UA))
    _trades(hub.engines[UA], time.time())
    r = c.get("/api/pump/daily", headers=tok(UA)).json()
    assert r["report"]["modules"] and any(m["menu"] == "Top traders (cópias)" for m in r["report"]["modules"])
    t = c.get("/api/pump/daily/ai", headers=tok(UA)).text
    assert "Relatório de cada menu" in t and "Top traders (cópias)" in t
    from app.daily import study
    rep = {"dia": "2026-10-20", "pnl_sol": -0.1, "suggestions": [],
           "modules": [{"menu": "Explorar", "sugestoes": [{"area": "lógica", "tipo": "menu:Explorar:x", "titulo": "Explorar: x", "texto": "t", "base": 5}]}]}
    st = study([rep, {**rep, "dia": "2026-10-21"}])
    assert st["recurring"][0]["tipo"] == "menu:Explorar:x" and st["recurring"][0]["dias"] == 2 and st["recurring"][0]["titulo"] == "Explorar: x"
