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
