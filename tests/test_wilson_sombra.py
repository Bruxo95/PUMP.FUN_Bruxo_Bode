"""0.31.84: regra Wilson só como sombra (não muda o bloqueio atual)."""
from app.autolearn import study, wilson


def _t(win, pressure=65):
    return {"origem": "explorar", "pnl_sol": 0.01 if win else -0.02, "pnl_pct": 20.0 if win else -40.0,
            "auto_info": {"pressure": pressure}}


def test_wilson_matches_nist_example():
    lo, hi = wilson(6, 20)
    assert round(lo * 100, 2) == 16.39 and round(hi * 100, 2) == 48.38


def test_shadow_rule_never_changes_blocking():
    trades = [_t(True), _t(True)] + [_t(False) for _ in range(5)]          # 2 em 7: bloqueada pela regra atual
    st = study(trades, "explorar")
    fx = [x for x in st["faixas"] if x["feature"] == "pressure"][0]
    assert fx["bloqueada"] is True and fx["bloq_wilson"] is False and fx["wilson"] == "liberaria"
    assert st["bloqueios"] and st["wilson"]["liberaria"] == 1
