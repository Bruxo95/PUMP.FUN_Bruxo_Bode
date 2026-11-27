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


def test_historico_token_que_foi_a_zero_nao_quebra():
    """0.32.485: token que chegou a -100% numa marca derrubava o histórico (divisão por zero)."""
    from app import boostmig
    rows = [{"p0": 1e-7, "t0": 1, "mint": "Z", "creator": "c", "classe": "despejou", "fim_pct": -100,
             "marks": {"1": -100.0, "2": -100.0, "3": -100.0, "5": -100.0, "10": -100.0},
             "serie": [[10, 0.0], [30, 0.0]], "top_pct": 0, "dump_pct": -100, "dump_s": 30, "top_s": 0},
            {"p0": 0, "t0": 2, "mint": "Y", "creator": "c", "classe": "lateral", "marks": {"1": 5.0, "3": 10.0},
             "serie": [], "fim_pct": 0}]
    out = boostmig.hist_study(rows)
    assert out["entra_sai"][0]["sai"].get("3") is None or out["entra_sai"][0]["sai"]["3"]["n"] >= 0
    for r in rows:
        boostmig.sign_time(r.get("serie") or [], r.get("p0"))
