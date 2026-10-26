"""Botão Comprar da Base da pump.fun (0.23.0) e rótulo "nasceu graduado"."""
import time

from tests.test_api import UA, UB, env, tok  # noqa: F401  (fixture env)
from tests.test_pump import _pump

M = "Compra".ljust(40, "1") + "pump"            # sem "l": endereço Solana não usa essa letra


def test_manual_buy_opens_simulated_position_without_copy_filters(tmp_path):
    pf = _pump(tmp_path, paid=False, pump_score_min_on=True, pump_score_min=99.0, pump_copy_sol=0.2)
    assert pf.manual_buy(M)["error"]                                       # sem preço ainda
    pf.tokens[M] = {"price": 1e-6, "symbol": "MAN", "mcap_sol": 30.0}
    r = pf.manual_buy(M)
    assert r["ok"] and "fictícia" in r["sim"] and r["real"] is None        # real desligado: não envia nada
    p = pf.positions()[0]
    assert p["wallet"] == "manual" and p["manual"] and abs(p["sol_in"] - 0.2005) < 1e-9
    assert pf.manual_buy(M)["sim"] == "já tem posição fictícia neste token" and len(pf.positions()) == 1
    assert pf._rq is None or pf._rq.empty()
    pf.tokens[M]["price"] = 0.4e-6                                         # segue o stop normal
    pf._check_stops(M, time.time())
    assert not pf.positions() and pf.trades()[0]["reason"].startswith("stop de perda")


def test_manual_buy_route_is_admin_only_and_audited(env):
    c, hub, db = env["c"], env["hub"], env["db"]
    assert c.post("/api/pump/manual-buy", json={"mint": M}, headers=tok(UB, "b@x.com")).status_code == 403
    assert c.post("/api/pump/manual-buy", json={"mint": "x;y"}, headers=tok(UA)).json()["error"]
    assert c.post("/api/pump/manual-buy", json={"mint": M}, headers=tok(UA)).json()["error"]   # sem preço
    hub.market.tokens[M] = {"price": 1e-6, "symbol": "MAN", "mcap_sol": 30.0}
    r = c.post("/api/pump/manual-buy", json={"mint": M}, headers=tok(UA)).json()
    assert r["ok"] and hub.engines[UA].positions()[0]["mint"] == M
    assert any(a["acao"] == "compra manual" for a in db.tables["audit_log"])


def test_born_graduated_is_not_counted_as_rising():
    from app.pumpfun import PumpMarket
    from app.tokenlab import TokenLab, label
    assert label(411.0, {"1": 411.0}, True) == "nasceu graduado"
    assert label(30.0, {"1": 30.0}, True) == "graduou"
    lab = TokenLab(PumpMarket())
    t0 = time.time() - 400
    lab.on_create({"mint": "Rise".ljust(44, "1"), "marketCapSol": 30.0, "symbol": "RISE"}, t0)
    lab.on_create({"mint": "Flat".ljust(44, "1"), "marketCapSol": 30.0, "symbol": "FLAT"}, t0)
    lab.live["Rise".ljust(44, "1")]["snaps"] = {"1": 45.0, "5": 75.0}
    lab.live["Flat".ljust(44, "1")]["snaps"] = {"1": 29.0}
    rs = lab.snapshot()["rising"]
    assert [x["symbol"] for x in rs] == ["RISE"] and rs[0]["gain_pct"] == 150.0 and rs[0]["fotos"] == 2
