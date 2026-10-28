"""Estudo automático de carteiras (0.31.13): adiciona sozinho, julga pelo "se você tivesse copiado", descarta o que
não compensa, aprova o que compensa e aprende que tipo de carteira compensa."""
import time

from tests.test_api import UA, UB, env, tok  # noqa: F401  (fixture env)

WA, WB, WC, WD = "B" * 44, "C" * 44, "D" * 44, "E" * 44


def _lb(*rows):
    return [{"wallet": w, "winrate": wr, "trades": n, "realized_usd": usd, "base_flags": fl} for w, wr, n, usd, fl in rows]


def _pos(db, w, realized, n=6):
    now = time.time()
    for i in range(n):
        db.tables["study_positions"].append({"wallet": w, "token": f"{w[:3]}{i}", "data": {
            "token": f"{w[:3]}{i}", "realized": realized, "invested": 100.0, "sells": 1, "last_sell": now - 3600,
            "hold_s": 300, "holding": 0}})


def test_rates_and_candidates_order_by_what_was_learned():
    from app.autostudy import candidates, judge, rates
    log = [{"acao": "aprovou", "info": {"features": {"fonte": "ranking", "acerto": "acerto 80% ou mais"}}},
           {"acao": "descartou", "info": {"features": {"fonte": "ranking", "acerto": "acerto abaixo de 60%"}}},
           {"acao": "descartou", "info": {"features": {"fonte": "ranking", "acerto": "acerto abaixo de 60%"}}}]
    rt = rates(log)
    low = next(x for x in rt if x["valor"] == "acerto abaixo de 60%")
    assert low["julgadas"] == 2 and low["aprovadas"] == 0 and low["taxa"] == 0.25
    pool = [{"wallet": WA, "winrate": 50, "trades": 200, "realized_usd": 9000, "fonte": "ranking"},
            {"wallet": WB, "winrate": 85, "trades": 200, "realized_usd": 100, "fonte": "ranking"},
            {"wallet": WC, "winrate": 90, "trades": 200, "realized_usd": 50, "fonte": "ranking", "base_flags": ["robô"]},
            {"wallet": WD, "winrate": 90, "trades": 200, "realized_usd": 50, "fonte": "ranking"}]
    out = candidates(pool, {WD}, rt)
    assert [c["wallet"] for c in out] == [WB, WA]          # aprendeu: acerto alto primeiro; robô e já estudada fora
    now = time.time()
    assert judge(now, {"copy": {"n_30d": 2}, "trades_seen": 0, "closed": 0}, now) is None
    assert judge(now - 4 * 86400, {"copy": None, "trades_seen": 0, "closed": 0}, now)[0] == "descartou"
    assert judge(now - 8 * 86400, {"copy": {"n_30d": 2}, "trades_seen": 5, "closed": 2}, now)[0] == "descartou"


def test_study_auto_adds_judges_and_learns(env):
    c, hub, db = env["c"], env["hub"], env["db"]
    A = tok(UA)
    c.post("/api/pump/study", json={"wallet": WD, "action": "add", "apelido": "minha"}, headers=A)
    pf = hub.engines[UA]
    pf.leaderboard = _lb((WA, 85, 300, 5000, []), (WB, 40, 300, 4000, []), (WC, 90, 300, 3000, ["dev de token"]))
    r = c.post("/api/pump/study/auto/run", json={}, headers=A).json()
    assert r["ok"] and r["adicionou"] == 2
    lst = c.get("/api/pump/study", headers=A).json()
    ap = {x["wallet"]: x["apelido"] for x in lst["wallets"]}
    assert ap[WD] == "minha" and ap[WA].startswith("auto · ") and ap[WB].startswith("auto · ") and WC not in ap
    assert lst["auto"]["counts"]["adicionou"] == 2 and lst["auto"]["on"] is True
    _pos(db, WA, 60.0)                                       # compensa
    _pos(db, WB, -50.0)                                      # não compensa
    _pos(db, WD, -50.0)                                      # a do dono nunca sai sozinha
    r = c.post("/api/pump/study/auto/run", json={}, headers=A).json()
    assert r["aprovou"] == 1 and r["descartou"] == 1
    lst = c.get("/api/pump/study", headers=A).json()
    ws = [x["wallet"] for x in lst["wallets"]]
    assert WB not in ws and WA in ws and WD in ws
    assert any(x["valor"] == "acerto abaixo de 60%" and x["aprovadas"] == 0 for x in lst["auto"]["rates"])
    assert any("Estudo automático: descartou" in e["msg"] for e in pf.events)
    r = c.post("/api/pump/study/auto/run", json={}, headers=A).json()
    assert r["aprovou"] == 0 and r["adicionou"] == 0         # aprovada não repete; descartada não volta por 7 dias


def test_study_auto_off_and_admin_only(env):
    c, hub = env["c"], env["hub"]
    A = tok(UA)
    c.post("/api/pump/settings", json={"pump_st_auto_on": False}, headers=A)
    assert c.post("/api/pump/study/auto/run", json={}, headers=A).json()["ok"] is False
    assert c.post("/api/pump/study/auto/run", json={}, headers=tok(UB, "b@x.com")).status_code == 403


def test_wallet_facts_become_learned_features():
    """0.32.9 (pedido do dono): idade, saldo, transações e tokens criados entram no estudo."""
    from app.autostudy import facts_features
    f = facts_features({"age_days": 12, "age_more": False, "usd": 25000, "txs": 400, "criados": 2})
    assert f == {"idade": "carteira com menos de 30 dias", "saldo": "saldo US$ 10 mil ou mais",
                 "transacoes": "menos de 1.000 transações", "criador": "já criou token"}
    g = facts_features({"age_days": 3, "age_more": True, "usd": None, "txs": 4000, "criados": 0})
    assert g["idade"].startswith("carteira com 180") and g["saldo"] is None and g["criador"] is None
