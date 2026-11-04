"""0.32.170: cópia FICTÍCIA da BNB (bnbcopy.Book) e o painel com menu. Sem internet."""
import asyncio
import time

from app import bnb, bnbcopy
from tests.test_api import env  # noqa: F401  (fixture env)
from tests.test_bnb import TOK, W1, W2, _Http, _log

U = "11111111-1111-1111-1111-111111111111"


def _tr(side, wallet, amount, value, t=None, token=TOK):
    return {"side": side, "wallet": wallet, "token": token, "amount": amount, "value": value, "fee": value * 0.01,
            "t": t or time.time(), "tx": "0xabc"}


def test_buy_sells_same_fraction_and_counts_fees():
    b = bnbcopy.Book(U, {"bnb_por_compra": 0.1, "slip_pct": 0, "gas_bnb": 0})
    p = b.buy(_tr("buy", W1, 1000, 1.0), 0.001, 100.0)
    assert p and abs(b.cash - 0.9) < 1e-9 and abs(p["tokens"] - 0.099 / 0.001) < 1e-6        # 1% de taxa na compra
    assert b.buy(_tr("buy", W1, 10, 0.01), 0.001, 101.0) is None                                 # mesmo trader e token
    assert b.events[0]["motivo"] == "já tem a posição deste trader neste token"
    assert b.sell(p, 0.5, 0.002, 200.0, "trader vendeu 50%") is None and len(p["vendas"]) == 1   # metade
    tr = b.sell(p, 1.0, 0.002, 300.0, "trader vendeu 100%")
    assert tr and not b.pos and b.trades[0] is tr
    assert abs(tr["bnb_out"] - 99 * 0.002 * 0.99) < 1e-9 and tr["pnl_bnb"] > 0                   # 1% na venda também
    w = b.wallet(400.0)
    assert w["fechadas"] == 1 and w["acerto"] == 100.0 and w["resultado"] == round(w["total"] - 1.0, 6)


def test_limits_stop_and_time():
    b = bnbcopy.Book(U, {"bnb_por_compra": 0.1, "max_abertas": 1, "stop_pct": 30, "max_hold_h": 1, "slip_pct": 0})
    p = b.buy(_tr("buy", W1, 1000, 1.0), 0.001, 0.0)
    assert b.buy(_tr("buy", W2, 1000, 1.0), 0.001, 1.0) is None and "limite de 1" in b.events[0]["motivo"]
    assert b.on_price(TOK, 0.0009, 10.0) == []                                                  # −10%: segura
    out = b.on_price(TOK, 0.0006, 20.0)
    assert out and out[0]["motivo"] == "stop de 30%" and p["id"] not in b.pos
    b.buy(_tr("buy", W2, 1000, 1.0), 0.001, 100.0)
    assert b.timeouts(100.0 + 1800) == [] and b.timeouts(100.0 + 3600)[0]["motivo"].startswith("tempo máximo")
    off = bnbcopy.Book(U, {"on": False})
    assert off.buy(_tr("buy", W1, 1, 1), 0.001, 0) is None and off.events[0]["motivo"] == "cópia desligada nesta conta"


def test_week_split_uses_berlin_weekday():
    sat = 1793430000.0          # 2026-10-31 (sábado), 08:00 em Berlim
    mon = sat + 2 * 86400
    trs = [{"close_t": sat, "pnl_bnb": 0.1, "bnb_in": 0.05}, {"close_t": mon, "pnl_bnb": -0.02, "bnb_in": 0.05}]
    w = bnbcopy.week_split(trs)
    assert w["blocos"]["fds"]["n"] == 1 and w["blocos"]["semana"]["pnl"] == -0.02
    assert {d["dia"]: d["n"] for d in w["dias"]}["sábado"] == 1


def test_watch_copies_ranked_trader_and_follows_sale():
    w = bnb.BnbWatch(_Http([], {}), None)
    w.bnb_usd = 600
    b = w.book(U)
    now = time.time()
    buy = {"id": "a:0", "tx": "a", "block": 1, "token": TOK, "wallet": W1, "side": "buy", "price": 0.001, "amount": 1000,
           "value": 1.0, "fee": 0.01, "t": now, "quote": bnb.ZERO}
    w.safe.mark(TOK, True)                       # 0.32.177: token já conferido pela segurança (bnbsafe)
    w._add(buy)
    w._copy(buy, 0.0, {W1})
    assert len(b.pos) == 1
    old = {**buy, "id": "b:0", "wallet": W2, "t": now - 3600}
    w._add(old)
    w._copy(old, 0.0, {W2})                       # compra antiga (recuperação depois de reiniciar): não copia
    assert len(b.pos) == 1
    sell = {**buy, "id": "c:0", "side": "sell", "amount": 500, "price": 0.002, "value": 1.0}
    before = w.hold[(W1, TOK)]
    w._add(sell)
    w._copy(sell, before, {W1})
    p = next(iter(b.pos.values()))
    assert p["vendas"][0]["frac"] == 0.5 and p["px_now"] == 0.002
    pn = w.painel(U)
    assert pn["posicoes"][0]["pnl_bnb"] > 0 and pn["abas"][0]["nome"] == "Top traders BNB" and pn["carteira"]["abertas"] == 1


def test_painel_routes_are_admin_only(env):
    from tests.test_api import UA, UB, tok
    c, hub = env["c"], env["hub"]
    assert c.get("/api/pump/bnb/painel", headers=tok(UB, "b@x.com")).status_code == 403
    assert c.get("/api/pump/bnb/painel", headers=tok(UA)).json()["ligado"] is False
    hub.bnb = bnb.BnbWatch(_Http([], {}), None)
    r = c.get("/api/pump/bnb/painel", headers=tok(UA)).json()
    assert r["ligado"] and r["carteira"]["saldo"] == 1.0 and r["cfg"]["on"] is True
    r = c.post("/api/pump/bnb/conta", json={"bnb_por_compra": 0.2, "saldo_inicial": 2}, headers=tok(UA)).json()
    assert r["ok"] and r["cfg"]["bnb_por_compra"] == 0.2 and hub.bnb.books[UA].cash == 2.0
    assert c.post("/api/pump/bnb/fechar", json={"id": "x"}, headers=tok(UA)).json()["error"].startswith("posição")
    assert c.post("/api/pump/bnb/conta", json={"on": False}, headers=tok(UB, "b@x.com")).status_code == 403


def test_watch_poll_with_book_does_not_break(tmp_path):
    logs = [_log("buy", TOK, W1, 1000, 0.5, block=995, i=0)]
    w = bnb.BnbWatch(_Http(logs, {}), None, rpcs=["https://bsc-rpc.publicnode.com"])
    w.book(U)
    w.cursor = 990
    assert asyncio.run(w.poll()) == 1
