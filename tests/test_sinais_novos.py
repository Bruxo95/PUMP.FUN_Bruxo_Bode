"""Item A (0.31.81): sinais novos anotados e estudados, sem bloquear nada."""
from app.autolearn import FEATURES, study, study_extra
from app.explore import extra_info, item


def test_extra_info_and_study_never_block():
    raw = {"token": {"mint": "M", "symbol": "S", "createdAt": 1_793_000_000_000},
           "risk": {"score": 5, "top10": 55.5, "dev": {"percentage": 3}, "snipers": {"totalPercentage": 20},
                    "insiders": {"totalPercentage": 0}, "bundlers": {"totalPercentage": 7}},
           "pools": [{"liquidity": {"usd": 1}, "txns": {"buys": 90, "sells": 10, "volume24h": 50.0}}]}
    row = item(raw, "graduating")
    assert row["top10"] == 55.5 and row["dev_pct"] == 3 and row["snipers_pct"] == 20 and row["bundlers_pct"] == 7
    info = extra_info(row, {"mayhem": True, "quote": "outra moeda"}, 1_793_000_600)
    assert info["mayhem"] is True and info["avg_trade_usd"] == 0.5 and info["age_min"] == 10.0
    trades = [{"origem": "explorar", "pnl_sol": -0.03, "pnl_pct": -60.0, "auto_info": dict(info)} for _ in range(10)]
    ex = {(x["feature"], x["faixa"]) for x in study_extra(trades)}
    assert ("mayhem", "Mayhem") in ex and ("top10", "40 a 60%") in ex and ("avg_trade_usd", "menos de $1") in ex
    assert not any(f in FEATURES for f in ("mayhem", "top10", "avg_trade_usd", "age_min"))      # nunca bloqueiam
    assert study(trades, "explorar")["bloqueios"] == []
