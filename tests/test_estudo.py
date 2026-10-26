"""Carteiras em estudo (0.14.0): perfil (ganho por minuto/hora/dia), gravação das operações e rotas por usuário."""
import asyncio
import time
from datetime import datetime, timezone

from tests.test_api import UA, UB, W, env, tok  # noqa: F401  (fixture env)


def test_profile_from_positions_and_from_live_trades():
    from app.study import compact_position, from_positions, from_trades, profile
    now = time.time()
    raw = [{"token": f"T{i}", "meta": {"symbol": f"S{i}", "primaryMarket": "pumpfun"}, "invested": 100.0,
            "pnl": {"realized": 48.0 if i < 3 else -24.0}, "roi": 48.0, "counts": {"buys": 1, "sells": 1},
            "timing": {"firstBuy": (now - 1800) * 1000, "lastSell": (now - 600) * 1000, "holdTimeSecs": 90}}
           for i in range(4)]
    rows = [compact_position(p) for p in raw] + [compact_position({"nada": 1})]
    m = from_positions(rows, now)
    assert m["closed"] == 4 and m["pnl_24h"] == 120.0 and m["pnl_1h"] == 120.0
    assert m["per_hour"] == 5.0 and abs(m["per_min"] - 120 / 1440) < 1e-3 and m["win_rate"] == 0.75
    assert m["hold_med_s"] == 90 and m["best"][0]["realized"] == 48.0
    trades = [{"mint": "A", "side": "buy", "sol": 1.0, "tokens": 100, "at": datetime.fromtimestamp(now - 300, timezone.utc).isoformat()},
              {"mint": "A", "side": "sell", "sol": 1.5, "tokens": 100, "at": datetime.fromtimestamp(now - 60, timezone.utc).isoformat()}]
    lv = from_trades(trades, now)
    assert lv["closed"] == 1 and abs(lv["pnl_24h"] - 0.5) < 1e-9 and lv["win_rate"] == 1.0
    p = profile("W", [{"data": r} for r in rows if r], trades, now)
    assert p["main"]["closed"] == 4 and p["live"]["closed"] == 1 and p["trades_seen"] == 2


def test_study_routes_are_per_user_and_record_trades(env):
    c, hub, db = env["c"], env["hub"], env["db"]
    A, B = tok(UA), tok(UB, "b@x.com")
    env["db"].set_role(UB, "admin")  # telas do menu Usar ou descartar: só admin (0.17.4)
    assert c.post("/api/pump/study", json={"wallet": "x;drop", "action": "add"}, headers=A).json()["error"]
    r = c.post("/api/pump/study", json={"wallet": W, "action": "add", "apelido": "baleia"}, headers=A).json()
    assert r["ok"]
    lst = c.get("/api/pump/study", headers=A).json()
    assert [x["wallet"] for x in lst["wallets"]] == [W] and lst["wallets"][0]["apelido"] == "baleia"
    assert c.get("/api/pump/study", headers=B).json()["wallets"] == []                   # B não vê a lista de A
    assert c.get(f"/api/pump/study/{W}", headers=B).json()["error"]                       # nem o perfil
    hub.record_trade(W, {"signature": "SIG1", "txType": "buy", "mint": "M1", "solAmount": 1.0, "tokenAmount": 10,
                         "marketCapSol": 50.0, "blockTime": int(time.time())})
    hub.record_trade(W, {"signature": "SIG1", "txType": "buy", "mint": "M1", "solAmount": 1.0, "tokenAmount": 10})
    asyncio.run(hub.flush_trades())
    assert len(db.tables["wallet_trades"]) == 1                                            # mesma assinatura: 1 linha
    prof = c.get(f"/api/pump/study/{W}", headers=A).json()
    assert prof["trades_seen"] == 1 and prof["recent"][0]["mint"] == "M1"
    assert c.post("/api/pump/study", json={"wallet": W, "action": "remove"}, headers=A).json()["ok"]
    assert c.get("/api/pump/study", headers=A).json()["wallets"] == []
    assert c.get("/api/pump/study").status_code == 401


def test_study_without_tables_does_not_break(env):
    c, db = env["c"], env["db"]
    for t in ("study_wallets", "wallet_trades", "study_positions"):
        del db.tables[t]
    r = c.get("/api/pump/study", headers=tok(UA))
    assert r.status_code == 200 and "não criadas" in r.json()["error"]


def test_copy_simulation_counts_fees_slippage_and_lag():
    """Etapa 2 (0.15.0): mesmo com a carteira lucrando, taxas + slippage + atraso podem tirar o lucro de quem copia."""
    from app.study import copy_sim
    now = time.time()
    prm = {"amt": 0.1, "fee": 0.0175, "prio": 0.0005, "slip": 0.03, "lag_s": 3.0, "lag_measured": True, "delay_s": 0.0}
    good = [{"realized": 50.0, "invested": 100.0, "last_sell": now - 3600, "hold_s": 120} for _ in range(5)]
    c = copy_sim(good, prm, now)
    keep = (0.97 ** 2) * (0.9825 ** 2)
    assert abs(c["pnl_30d"] - 5 * (0.1 * (1.5 * keep - 1) - 0.001)) < 1e-4 and c["verdict"] == "compensa copiar"
    small = [{"realized": 3.0, "invested": 100.0, "last_sell": now - 3600, "hold_s": 120} for _ in range(5)]
    assert copy_sim(small, prm, now)["pnl_30d"] < 0                     # +3% da carteira vira prejuízo para quem copia
    fast = [{"realized": 80.0, "invested": 100.0, "last_sell": now - 60, "hold_s": 2} for _ in range(5)]
    cf = copy_sim(fast, prm, now)
    assert cf["fast_pct"] == 1.0 and cf["pnl_30d"] < 0 and cf["verdict"] == "não compensa"
    assert copy_sim([], prm, now) is None and copy_sim(good[:2], prm, now)["verdict"] == "poucos dados"


def test_study_list_has_copy_ranking(env):
    c, db = env["c"], env["db"]
    A = tok(UA)
    c.post("/api/pump/study", json={"wallet": W, "action": "add"}, headers=A)
    now = time.time()
    for i in range(6):
        db.tables["study_positions"].append({"wallet": W, "token": f"T{i}", "data": {
            "token": f"T{i}", "realized": 60.0, "invested": 100.0, "sells": 1, "last_sell": now - 3600, "hold_s": 300, "holding": 0}})
    r = c.get("/api/pump/study", headers=A).json()
    assert r["ranking"][0]["wallet"] == W and r["ranking"][0]["n_30d"] == 6 and r["ranking"][0]["pnl_30d"] > 0
    assert r["params"]["lag_s"] == 3.0 and not r["params"]["lag_measured"]
    prof = c.get(f"/api/pump/study/{W}", headers=A).json()
    assert prof["copy"]["verdict"] == "compensa copiar" and "closed_list" not in (prof["main"] or {})


def test_share_study_wallet_with_another_user(env):
    """0.17.1: Compartilhar coloca a carteira na lista de estudo de outro usuário (pedido do dono em 2026-10-25)."""
    c, hub, db = env["c"], env["hub"], env["db"]
    A, B = tok(UA, "ana@x.com"), tok(UB, "bia@x.com")
    env["db"].set_role(UB, "admin")  # telas do menu Usar ou descartar: só admin (0.17.4)
    c.get("/api/pump/study", headers=B)                                                  # B já tem conta
    assert c.post("/api/pump/study", json={"wallet": W, "action": "add", "apelido": "baleia"}, headers=A).json()["ok"]
    us = c.get("/api/pump/study/share-targets", headers=A).json()["users"]
    assert [u["user_id"] for u in us] == [UB] and us[0]["email"] == "b***@x.com"        # sem A e sem e-mail completo
    assert c.post("/api/pump/study/share", json={"wallet": W, "to": "x"}, headers=A).json()["error"]
    assert c.post("/api/pump/study/share", json={"wallet": W, "to": UA}, headers=A).json()["error"]
    # B não pode "compartilhar" uma carteira que não estuda (não serve para mexer na lista dos outros)
    assert c.post("/api/pump/study/share", json={"wallet": W, "to": UA}, headers=B).json()["error"]
    assert c.post("/api/pump/study/share", json={"wallet": W, "to": UB}, headers=A).json()["ok"]
    lst = c.get("/api/pump/study", headers=B).json()["wallets"]
    assert [x["wallet"] for x in lst] == [W] and lst[0]["apelido"] == "baleia"
    assert c.get(f"/api/pump/study/{W}", headers=B).json().get("error") is None           # B já abre o perfil
    assert c.post("/api/pump/study/share", json={"wallet": W, "to": UB}, headers=A).json()["already"]
    acoes = [r["acao"] for r in db.tables["audit_log"]]
    assert "compartilhar carteira em estudo" in acoes and "recebeu carteira em estudo" in acoes
    assert c.post("/api/pump/study/share", json={"wallet": W, "to": UB}).status_code == 401


def test_study_shows_your_own_result_copying_each_wallet(env):
    """0.29.0: "Seu resultado copiando" = trades e posições do próprio usuário com a carteira (fictício e real)."""
    c, hub = env["c"], env["hub"]
    A = tok(UA)
    assert c.post("/api/pump/study", json={"wallet": W, "action": "add"}, headers=A).json()["ok"]
    pf = hub.engines[UA]
    for pnl in (0.05, -0.02):
        pf._save_trade({"wallet": W, "mint": "M", "pnl_sol": pnl, "sol_in": 0.1, "real": False,
                        "opened_at": "2026-10-26T01:00:00+00:00", "closed_at": "2026-10-26T02:00:00+00:00"})
    pf._save_trade({"wallet": "Outra".ljust(44, "1"), "pnl_sol": 9.0, "sol_in": 0.1, "real": False})
    mine = c.get("/api/pump/study", headers=A).json()["mine"]
    row = mine["rows"][0]
    assert len(mine["rows"]) == 1 and row["wallet"] == W and row["real"] is False and row["trades"] == 2
    assert row["pnl_sol"] == 0.03 and row["win_rate"] == 0.5 and row["roi_pct"] == 15.0 and row["since"].startswith("2026-10-26T01")
    assert mine["total"]["sim"]["pnl_sol"] == 0.03 and mine["total"]["real"]["trades"] == 0


def test_copied_wallet_without_trades_shows_why(env):
    """0.31.2: carteira copiada sem trade fechado aparece com o motivo (o dono via "0" e não sabia por quê)."""
    c, hub = env["c"], env["hub"]
    A = tok(UA)
    assert c.post("/api/pump/study", json={"wallet": W, "action": "add"}, headers=A).json()["ok"]
    pf = hub.engines[UA]
    pf.add_manual(W)
    for _ in range(3):
        pf._feed(wallet=W, short="x", mint="M", symbol="S", kind="buy", sol=0.1, action="não copiou",
                 reason="compra pequena do trader (0.100 SOL < mínimo 0.20)")
    mine = c.get("/api/pump/study", headers=A).json()["mine"]
    row = mine["rows"][0]
    assert row["trades"] == 0 and row["diag"]["buys_seen"] == 3 and row["diag"]["copied"] == 0
    assert row["diag"]["top_skips"][0]["n"] == 3 and "compra pequena" in row["diag"]["top_skips"][0]["reason"]
