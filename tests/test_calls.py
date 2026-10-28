"""0.31.94: calls quentes pela blockchain."""
from app.calls import COST_PCT, FOLLOW_S, MIN_CALLS, Calls


def _buy(cl, w, mint, t, sol=1.0, tok=1000.0, mc=80):
    return cl.on_trade(w, {"mint": mint, "txType": "buy", "solAmount": sol, "tokenAmount": tok, "marketCapSol": mc}, t, w[:4], "teste", 0.001)


def test_call_measure_dump_and_score():
    cl = Calls()
    t = 1_793_000_000.0
    px = {"value": 1.0}
    for i in range(MIN_CALLS):
        m = f"M{i}"
        c = _buy(cl, "CALLERAAAA", m, t + i)
        cl.tick(lambda _m: px["value"], t + i + FOLLOW_S)                # seguidor entra a 1.0
        px["value"] = 1.2 if i % 2 == 0 else 0.9
        cl.tick(lambda _m: px["value"], t + i + FOLLOW_S + 900)           # 15 min
        px["value"] = 1.0
    d = cl.callers()["CALLERAAAA"]
    assert d["medidas"] == MIN_CALLS and d["ganhou"] == 3 and d["nota"] is not None
    assert cl.result(c) == round(-10.0 - COST_PCT, 2) or cl.result(c) == round(20.0 - COST_PCT, 2)
    # despejo: vende metade em 2 min
    c2 = _buy(cl, "DUMPERBBBB", "X", t)
    cl.on_trade("DUMPERBBBB", {"mint": "X", "txType": "sell", "tokenAmount": 600.0}, t + 120, "D", "teste", None)
    assert c2["despejo_s"] == 120.0
    # veredito: outro caller no mesmo token em 10 min soma
    _buy(cl, "OUTROCCCCC", "X", t + 60)
    v = cl.verdict(c2, cl.callers())
    assert any("mesmo token" in w for w in v["why"]) and any("despeja" in w for w in v["why"])
    assert cl.verdict(c2, cl.callers(), blacklisted=lambda m: True)["verdict"] == "lixo"
