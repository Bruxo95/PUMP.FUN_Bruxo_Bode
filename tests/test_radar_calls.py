"""0.31.96: Radar com as compras guardadas e ondas calculadas das calls."""
from app.calls import Calls


def test_waves_from_saved_calls():
    cl = Calls()
    t = 1_793_000_000.0
    for i, w in enumerate(("A" * 32, "B" * 32, "C" * 32)):
        cl.on_trade(w, {"mint": "M", "txType": "buy", "solAmount": 1, "tokenAmount": 10}, t + i * 60, w[:1], "carteira em estudo", 0.1)
    cl.on_trade("D" * 32, {"mint": "N", "txType": "buy", "solAmount": 1, "tokenAmount": 10}, t, "D", "estudo", 0.1)
    buys = cl.for_wallets({"A" * 32, "B" * 32, "C" * 32, "D" * 32}, 24, now=t + 300)
    assert len(buys) == 4
    w = Calls.waves(buys, 2, 300)
    assert len(w) == 1 and w[0]["mint"] == "M" and len(w[0]["carteiras"]) == 3
    assert Calls.waves(buys, 4, 300) == []
