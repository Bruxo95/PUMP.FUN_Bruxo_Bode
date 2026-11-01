"""0.32.113: janela Resultado por período. Sem internet."""
from datetime import datetime, timezone

from app.pumpfun import PumpFun

NOW = 2_000_000_000.0


def _t(h_atras, pnl, sol=0.1):
    return {"closed_at": datetime.fromtimestamp(NOW - h_atras * 3600, timezone.utc).isoformat(), "pnl_sol": pnl, "sol_in": sol}


def test_each_window_counts_only_its_own_trades():
    T = [_t(0.5, 0.2), _t(3, -0.05), _t(10, -0.01), _t(20, 0.1), _t(30, 5.0), {"closed_at": None, "pnl_sol": 9}]
    P = {p["horas"]: p for p in PumpFun.periods(T, 10.0, NOW)}
    assert P[1]["trades"] == 1 and P[1]["ganhos_sol"] == 0.2 and P[1]["perdas_sol"] == 0
    assert P[6]["trades"] == 2 and P[6]["saldo_sol"] == 0.15 and P[6]["perdas"] == 1
    assert P[12]["trades"] == 3 and P[12]["investido_sol"] == 0.3
    assert P[24]["trades"] == 4 and P[24]["saldo_sol"] == 0.24 and P[24]["saldo_antes"] == 9.76


def test_each_tab_gets_its_own_percent_and_windows():
    T = [dict(_t(0.5, 0.02), aba="A", reason="stop de perda (-20%)"), dict(_t(3, -0.05), aba="A", reason="stop de perda (-30%)"), dict(_t(30, 0.3, 1.0), aba="B", reason="alvo")]
    L = {x["aba"]: x for x in PumpFun.tabs(T, lambda t: t["aba"], NOW)}
    assert L["A"]["trades"] == 2 and L["A"]["pct"] == -15.0 and L["A"]["acerto"] == 50
    assert L["B"]["pct"] == 30.0 and L["B"]["saldo_sol"] == 0.3
    P = {p["horas"]: p for p in L["A"]["periodos"]}
    assert P[1]["pct"] == 20.0 and P[6]["pct"] == -15.0 and "saldo_antes" not in P[1]
    assert {p["horas"]: p["pct"] for p in L["B"]["periodos"]}[24] is None      # fora da janela de 24 h
    assert L["A"]["motivos"][0]["nome"] == "stop de perda" and L["A"]["motivos"][0]["n"] == 2
    assert [x["aba"] for x in PumpFun.tabs(T, lambda t: t["aba"], NOW)] == ["B", "A"]


def test_each_exit_reason_lists_its_own_coins_newest_first():
    T = [dict(_t(5, -0.03), symbol="AAA", reason="stop de perda (-30%)"), dict(_t(1, -0.02), symbol="BBB", reason="stop de perda (-20%)"), dict(_t(2, 0.5), symbol="CCC", reason="alvo")]
    M = {m["nome"]: m for m in PumpFun.tabs(T, lambda t: "A", NOW)[0]["motivos"]}
    assert [x["symbol"] for x in M["stop de perda"]["itens"]] == ["BBB", "AAA"] and [x["symbol"] for x in M["alvo"]["itens"]] == ["CCC"]
    assert len(PumpFun.tabs([dict(_t(1, -0.01), reason="x") for _ in range(PumpFun.TAB_ITENS + 5)], lambda t: "A", NOW)[0]["motivos"][0]["itens"]) == PumpFun.TAB_ITENS


def test_pepe_fix_only_touches_the_false_fictitious_trade_and_keeps_the_original():
    import pathlib
    sql = pathlib.Path("supabase/migrations/20261101000003_anula_ganho_falso_pepe.sql").read_text(encoding="utf-8")
    onde = sql[sql.index("where real = false"):]
    assert "data->>'symbol' = 'PEPE'" in onde and ">= 1900" in onde and "fechada_em <" in onde
    assert "'corrigido'" in sql and "delete" not in sql.split("update public.pump_trades")[1].lower()


def test_traders_counts_distinct_copied_wallets_in_each_window():
    T = [dict(_t(1, 0.1), wallet="A"), dict(_t(2, 0.1), wallet="A"), dict(_t(3, 0.1), wallet="B"), dict(_t(2, 0.1), wallet="manual"), dict(_t(30, 0.1), wallet="C")]
    P = {p["horas"]: p for p in PumpFun.periods(T, 10.0, NOW)}
    assert P[24]["traders"] == 2 and P[1]["traders"] == 1 and "_w" not in P[24]


def test_history_shows_trader_name_only_from_the_ranking():
    import pathlib
    s = pathlib.Path("app/pumpfun.py").read_text(encoding="utf-8")
    assert '"wallet_names": dict(self.market.__dict__.get("trader_names") or {})' in s
