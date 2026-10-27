"""Resultado por versão (0.31.50): ajudou ou piorou, fictícia e real separadas."""
from app.versions_report import build, compact, load


def _t(at, pnl, real=False):
    return {"closed_at": at, "pnl_sol": pnl, "real": real}


def test_versions_report_says_which_version_helped():
    V = [{"versao": "1", "inicio": "2026-10-27T00:00:00+00:00", "titulo": "a"},
         {"versao": "2", "inicio": "2026-10-27T10:00:00+00:00", "titulo": "b"},
         {"versao": "3", "inicio": "2026-10-27T20:00:00+00:00", "titulo": "c"}]
    T = [_t("2026-10-27T01:00:00+00:00", -0.01) for _ in range(5)] + [_t("2026-10-27T11:00:00+00:00", 0.05) for _ in range(5)] \
        + [_t("2026-10-27T21:00:00+00:00", 0.1)] + [_t("2026-10-27T11:00:00+00:00", 0.3, real=True)]
    r = build(T, V, now=1.9e9)
    v = {x["versao"]: x for x in r["versoes"]}
    assert v["1"]["veredito"] == "primeira medida" and v["2"]["veredito"] == "ajudou" and v["3"]["veredito"] == "pouca base"
    assert v["2"]["real"]["pnl_sol"] == 0.3 and r["total_real"] == 0.3 and r["melhor"] == "2"
    assert compact(r)[-1]["versao"] == "3"
    assert build(T, V, now=1.9e9, real=True)["versoes"][1]["real"]["trades"] == 1


def test_versions_file_is_in_order_and_has_the_current_version():
    from app.version import VERSION
    L = load()
    assert L and L[-1]["versao"] == VERSION.split("·")[0].strip()
