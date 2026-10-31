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
