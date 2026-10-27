"""Copiar os trades de outro usuário (0.31.61): a conta que segue abre e fecha os mesmos trades da conta seguida."""
import asyncio

from tests.test_api import UA, UB, env, tok  # noqa: F401  (fixture env)

M = "Foll".ljust(40, "1") + "pump"


def test_follower_opens_and_closes_the_same_trade(env):
    c, hub = env["c"], env["hub"]
    A, B = tok(UA), tok(UB, "b@x.com")
    env["db"].set_role(UB, "admin")
    c.get("/api/pump", headers=A)
    c.get("/api/pump", headers=B)
    lead, fol = hub.engines[UA], hub.engines[UB]
    r = c.post("/api/pump/follow-user", json={"user_id": UA}, headers=B).json()
    assert r.get("ok") and fol.follow_user == UA
    assert c.post("/api/pump/follow-user", json={"user_id": UB}, headers=A).json().get("error")   # sem círculo
    lead.tokens[M] = {"price": 1e-6, "symbol": "FOL", "mcap_sol": 40.0}
    lead.manual_buy(M)
    lp = [p for p in lead.positions() if p["mint"] == M][0]
    fp = [p for p in fol.positions() if p["mint"] == M]
    assert fp and fp[0]["follow_of"]["pos"] == lp["id"] and abs(fp[0]["sol_in"] - lp["sol_in"]) < 0.01
    assert fp[0]["stop_pct"] == lp["stop_pct"]
    lead._sell(lp, 1.0, 1.2e-6, "alvo", 0.0)
    assert not [p for p in fol.positions() if p["mint"] == M]                                   # fechou junto
    assert any("a conta" in (t.get("reason") or "") for t in fol.trades(10))
    c.post("/api/pump/follow-user", json={"user_id": ""}, headers=B)
    assert fol.follow_user == ""
