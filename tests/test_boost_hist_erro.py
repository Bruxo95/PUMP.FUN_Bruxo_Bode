"""0.32.481: Histórico e análise do BOOST — se algo falhar, a tela recebe o motivo em JSON (antes: "resposta inválida do
servidor"). E o histórico continua montando com as linhas do banco."""
import time
from datetime import datetime, timezone

from tests.test_api import UA, env, tok  # noqa: F401  (fixture env)


def test_historico_monta_com_linhas_do_banco(env):
    c, db = env["c"], env["db"]
    A = tok(UA)
    c.get("/api/pump", headers=A)
    now = time.time()
    rows = []
    for i in range(30):
        d = {"p0": 1e-7, "t0": now - i * 600, "mint": f"M{i}", "creator": "c", "classe": "lateral", "marks": {"1": 1.0, "3": 2.0},
             "serie": [[10, 1e-7], [30, 2e-7]], "sinal": None, "sybil": {"nivel": "alto", "bundle_pct": 20}, "top_pct": 5, "fim_pct": 1,
             "dump_pct": -40, "dump_s": 100, "top_s": 50, "symbol": "X"}
        rows.append({"mint": d["mint"], "t0": datetime.fromtimestamp(d["t0"], timezone.utc).isoformat(), "dados": d})
    db.tables.setdefault("boost_history", []).extend(rows)
    r = c.get("/api/pump/boost-migracao/historico?dias=1", headers=A)
    assert r.status_code == 200 and r.json()["n"] == 30 and r.json()["lista"][0]["sinal"]


def test_historico_com_erro_devolve_motivo(env, monkeypatch):
    c, hub = env["c"], env["hub"]
    A = tok(UA)
    c.get("/api/pump", headers=A)

    async def quebra(dias=7):
        raise ValueError("teste")
    monkeypatch.setattr(hub, "bm_hist", quebra)
    r = c.get("/api/pump/boost-migracao/historico?dias=1", headers=A)
    assert r.status_code == 200 and "ValueError: teste" in r.json()["error"]
