"""Aprendizado diário (0.9.9): resumo, comportamento dos top traders e sugestões com base mínima."""
import asyncio
import time
from collections import deque
from datetime import datetime, timezone

from tests.test_api import UA, UB, W, env, tok  # noqa: F401  (fixture env)


def _trade(wallet, pnl):
    return {"wallet": wallet, "pnl_sol": pnl, "reason": "stop de perda (−40%)", "real": False, "fees_sol": 0.01,
            "closed_at": datetime.now(timezone.utc).isoformat(), "sol_in": 0.1, "hold_s": 30, "fee_parts": {}}


def test_learning_summarizes_traders_and_suggests_with_minimum_base(env):
    from app.learning import build
    pf = asyncio.run(env["hub"].engine(UA))
    pf.add_manual(W)
    now = time.time()
    closed = deque([{"t": now - 600, "pnl": 0.5, "hold": 120, "mint": f"m{i}", "mcap_in": 30} for i in range(15)]
                   + [{"t": now - 600, "pnl": -0.2, "hold": 40, "mint": f"x{i}", "mcap_in": 200} for i in range(10)])
    pf.wallets[W] = {"pos": {}, "closed": closed, "trades": deque([now - 600] * 50)}
    for _ in range(4):
        pf._save_trade(_trade(W, -0.02))
    r = build(pf)
    tt = r["traders_today"]
    assert tt["tokens_closed"] == 25 and tt["winners"]["n"] == 15 and tt["winners"]["mcap_in_med"] == 30
    assert any("25 tokens fechados" in s for s in r["summary"])
    kinds = {s["kind"] for s in r["suggestions"]}
    assert "pausar" not in kinds                                  # só 4 trades: abaixo da base mínima (5)
    assert "mcap" in kinds                                        # perdedores entram com mcap bem maior
    mc = next(s for s in r["suggestions"] if s["kind"] == "mcap")
    assert mc["action"] == {"type": "settings", "values": {"pump_max_mcap_sol": 30}} and mc["base"] == 25
    pf._save_trade(_trade(W, -0.02))
    sug = build(pf)["suggestions"]
    pz = next(s for s in sug if s["kind"] == "pausar")
    assert pz["action"] == {"type": "pause", "wallet": W, "hours": 24} and pz["base"] == 5


def test_learning_route_requires_login_and_is_per_user(env):
    c = env["c"]
    assert c.get("/api/pump/aprendizado").status_code == 401
    ra = c.get("/api/pump/aprendizado", headers=tok(UA)).json()
    rb = c.get("/api/pump/aprendizado", headers=tok(UB, "b@x.com")).json()
    assert ra["summary"] and rb["mine_24h"]["trades"] == 0 and isinstance(rb["suggestions"], list)
