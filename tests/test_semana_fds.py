"""0.32.161 (pedido do dono): dias de semana × fins de semana, por aba e por trader, e os blocos fechados guardados. Sem internet."""
import asyncio
import inspect

from app import weekparts as wk
from tests.test_api import UA, env, tok  # noqa: F401  (fixture env)

ab = lambda x: x["_a"]
W1, W2 = "A" * 44, "B" * 44


def t(closed, pnl, w=W1, aba="Top traders"):
    return {"closed_at": closed, "wallet": w, "pnl_pct": pnl, "pnl_sol": pnl / 1000, "sol_in": 0.1, "symbol": f"S{pnl}", "_a": aba}


def test_saturday_and_sunday_are_weekend_in_berlin_time():
    sab = wk.bloco(1_793_455_200)                      # 2026-10-31 14:00 UTC = sábado em Berlim
    assert sab["tipo"] == "fds" and sab["key"] == "2026-10-31-fds" and sab["rotulo"].startswith("sáb 31/10")
    dom_noite = wk.bloco(1_793_575_800)                 # 2026-11-01 23:30 UTC = segunda 00:30 em Berlim
    assert dom_noite["tipo"] == "semana" and dom_noite["key"] == "2026-11-02-semana"


def test_blocks_split_and_summary_per_day():
    T = [t("2026-10-31T12:00:00+00:00", 20), t("2026-11-01T12:00:00+00:00", -10, W2, "Explorar"),
         t("2026-10-29T10:00:00+00:00", 50), t("2026-10-30T10:00:00+00:00", 5000)]          # o último é ganho falso: fica fora
    B = wk.blocos(T, ab, {W1: "trader um"}, now=1_800_000_000)
    assert [(b["key"], b["trades"]) for b in B] == [("2026-10-31-fds", 2), ("2026-10-26-semana", 1)]
    assert B[0]["fechado"] and {a["aba"] for a in B[0]["abas"]} == {"Top traders", "Explorar"}
    assert B[0]["traders"][0]["nome"] == "trader um" and B[0]["melhor"]["symbol"] == "S20"
    R = wk.resumo(T, ab)
    assert R["fds"]["trades"] == 2 and R["fds"]["dias"] == 2 and R["semana"]["dias"] == 1
    assert abs(R["fds"]["por_dia_sol"] - 0.005) < 1e-9 and R["semana"]["acerto"] == 100
    tr = {x["wallet"]: x for x in R["traders"]}
    assert tr[W1]["semana"]["trades"] == 1 and tr[W1]["fds"]["trades"] == 1 and tr[W2]["semana"] is None
    pa = wk.por_aba(T, ab)
    assert pa["Explorar"]["fds"]["trades"] == 1 and pa["Explorar"]["semana"]["trades"] == 0


def test_module_decides_nothing():
    src = inspect.getsource(wk)
    assert "manual_buy" not in src and "_sell(" not in src and "save_settings" not in src


def test_route_and_closed_blocks_are_saved_once(env):
    c, hub = env["c"], env["hub"]
    A = tok(UA)
    c.get("/api/pump", headers=A)
    pf = hub.engines[UA]
    pf._save_trade({"wallet": W1, "symbol": "X", "mint": "M" * 40, "sol_in": 0.1, "pnl_sol": 0.01, "pnl_pct": 10, "reason": "alvo",
                    "hold_s": 60, "closed_at": "2026-10-31T12:00:00+00:00", "real": False})
    r = c.get("/api/pump/weekparts", headers=A).json()
    assert r["blocos"][0]["key"] == "2026-10-31-fds" and r["resumo"]["fds"]["trades"] == 1
    assert asyncio.run(hub.week_save(pf, now=1_800_000_000)) == 1          # o bloco fechado é guardado
    assert asyncio.run(hub.week_save(pf, now=1_800_000_000)) == 0          # e não duplica
    g = c.get("/api/pump/weekparts", headers=A).json()["guardados"]
    assert g and g[0]["key"] == "2026-10-31-fds"
    assert "semanas" in c.get("/api/pump/result-tabs", headers=A).json()
