"""0.32.73: relatório do Copiar igual a cada 6 h (por carteira, cada operação, veredito) e o aprendizado da Base geral."""
from datetime import datetime, timezone

from app.eqreport import build, learn

W1, W2 = "A" * 44, "B" * 44
NOW = 1_800_000_000.0


def _iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


def _t(w, pnl, ago, **kw):
    return {"eq": True, "wallet": w, "symbol": "TK", "mint": "M", "pnl_sol": pnl, "pnl_pct": pnl * 1000, "sol_in": 0.05,
            "closed_at": _iso(NOW - ago), "opened_at": _iso(NOW - ago - 60), "hold_s": 60, "reason": "carteira vendeu", **kw}


def test_report_by_wallet_ops_and_verdict():
    trades = [_t(W1, 0.01, 100) for _ in range(4)] + [_t(W1, -0.005, 200)] + [_t(W2, -0.02, 300) for _ in range(5)]
    trades.append(_t(W1, 0.5, 8 * 3600))                       # fora das 6 h
    trades.append(_t(W1, 0.3, 100, eq=False))                  # não é do Copiar igual
    diag = [(NOW - 50, W1, "copiou"), (NOW - 40, W1, "saldo fictício insuficiente"), (NOW - 30, W2, "copiou")]
    r = build(trades, [{"eq": True, "wallet": W1, "symbol": "X", "real": False}], diag, [W1, W2], {W1: "sim"}, NOW)
    by = {c["wallet"]: c for c in r["carteiras"]}
    assert by[W1]["n"] == 5 and by[W1]["veredito"] == "manter" and by[W1]["abertas"] == 1 and by[W1]["vistas"] == 2
    assert by[W1]["nao_copiou"][0]["motivo"] == "saldo fictício insuficiente"
    assert by[W2]["veredito"] == "parar" and by[W2]["modo"] == "off"
    assert len(r["operacoes"]) == 10 and r["vistas"] == 3 and r["copiadas"] == 2 and r["veredito"] == "perdendo"


def test_learn_sums_reports_per_wallet():
    a = build([_t(W1, 0.01, 100) for _ in range(5)], [], [], [W1], {}, NOW)
    b = build([_t(W1, 0.02, 100) for _ in range(5)], [], [], [W1], {}, NOW)
    L = learn([a, b])
    assert L["relatorios"] == 2 and L["carteiras"][0]["periodos"] == 2 and L["carteiras"][0]["veredito"] == "manter"
    assert L["n"] == 10


def test_no_data_says_so():
    r = build([], [], [], [W1], {W1: "sim"}, NOW)
    assert r["veredito"] == "sem dados" and r["carteiras"][0]["veredito"] == "poucos dados"
