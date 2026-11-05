"""0.31.91: aprendizado dos logs (resumo por dia, sem apagar os registros)."""
import asyncio

from app.robotlog import rollup, trend
from tests.test_api import UA, env, tok  # noqa: F401  (fixture env)


def test_rollup_and_trend():
    d = rollup([{"analisados": 5, "entrou": ["A"], "motivos": [{"motivo": "veredito lixo", "n": 3}]},
                {"analisados": 4, "entrou": ["A", "B"], "motivos": [{"motivo": "veredito lixo", "n": 2}, {"motivo": "pressão 50 abaixo", "n": 1}]}])
    assert d["analisados"] == 9 and d["entradas"] == 2 and d["gargalo"] == "veredito lixo" and d["motivos"][0]["n"] == 5
    t = trend([{"data": d}, {"data": rollup([])}])
    assert t["dias"] == 2 and t["dias_sem_entrada"] == 1 and t["motivo_principal"] == "veredito lixo"


def test_daily_rollup_keeps_raw_logs(env):
    c, hub = env["c"], env["hub"]
    env["db"].set_role(UA, "admin")
    c.get("/api/pump", headers=tok(UA))
    env["db"].tables["robot_log"].append({"id": "x", "user_id": UA, "modulo": "base", "em": "2026-10-20T10:00:00+00:00",
                                          "data": {"analisados": 3, "entrou": ["Z"], "motivos": [{"motivo": "veredito lixo", "n": 2}]}})
    from datetime import datetime, timezone
    n = asyncio.run(hub.rlog_daily(now=datetime(2026, 10, 22, tzinfo=timezone.utc).timestamp(), max_days=5))
    assert n == 1 and len(env["db"].tables["robot_log"]) == 1               # o registro bruto continua lá
    r = c.get("/api/pump/robot-log/dias?modulo=base", headers=tok(UA)).json()
    assert r["dias"][0]["dia"] == "2026-10-20" and r["tendencia"]["entradas_total"] == 1


def test_dia_fechado_vazio_nao_e_consultado_de_novo(env):
    """0.32.229: dia fechado sem registro fica lembrado; antes era consultado toda hora (maior volume do Supabase)."""
    c, hub, db = env["c"], env["hub"], env["db"]
    c.get("/api/pump", headers=tok(UA))
    from datetime import datetime, timezone
    now = datetime(2026, 10, 22, tzinfo=timezone.utc).timestamp()
    calls = []
    orig = db.select

    async def spy(table, *a, **k):
        if table in ("robot_log", "explore_cycles"):
            calls.append(table)
        return await orig(table, *a, **k)
    db.select = spy
    asyncio.run(hub.rlog_daily(now=now, max_days=5))
    first = len(calls)
    calls.clear()
    asyncio.run(hub.rlog_daily(now=now, max_days=5))
    assert first > 0 and len(calls) < first                 # só o dia de ontem (back=1) volta a ser olhado
    db.select = orig


def test_perfil_em_cache_e_limpo_pelo_admin(env):
    """0.32.229: o perfil fica 30 s em memória; bloqueio pelo admin vale na hora."""
    c, hub, db = env["c"], env["hub"], env["db"]
    hub.PROFILE_TTL = 30
    c.get("/api/pump", headers=tok(UA))
    n = []
    orig = db.select

    async def spy(table, *a, **k):
        if table == "profiles":
            n.append(1)
        return await orig(table, *a, **k)
    db.select = spy
    asyncio.run(hub.ensure_profile({"sub": UA}))
    asyncio.run(hub.ensure_profile({"sub": UA}))
    assert len(n) == 0                                      # veio do cache
    db.select = orig
    assert UA in hub._prof_cache
    asyncio.run(hub.admin_update_user("outro", UA, {}))
    assert UA not in hub._prof_cache
