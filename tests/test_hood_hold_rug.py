"""0.32.505 (pedidos do dono de 28/11 na Robinhood): rug pull antigo entra na lista, hold das duas carteiras, venda de parte do hold
no Histórico, hold não ocupa vaga da REAL e zerar (esconder) o histórico REAL."""
import asyncio
import time

from app import hoodcopy, hoodreal
from tests.test_hood_copia import TOK, copier, run, settle, trade


def _hold(c, real=False):
    p = {"id": "h1", "wallet": "cacador-a", "token": TOK, "open_t": time.time() - 60, "px_in": 0.001, "tokens": 10.0, "tokens_left": 10.0,
         "fee": 0.01, "eth_in": 0.01, "proceeds": 0.0, "fees": 0.0, "px_now": 0.002, "px_t": time.time(), "best_pct": 0.0, "worst_pct": 0.0,
         "lag_s": 0.0, "aba": "hold", "hold": 20.0, "hold_de": {"entrada": "A"}, "simbolo": "BIT"}
    if real:
        p.update(id="r1", real=True, raw_left=str(10 * 10 ** 18))
        c.rbook("u1").pos["r1"] = p
    else:
        c.books["u1"].pos["h1"] = p
    return p


def test_selling_part_of_the_hold_becomes_a_history_trade_and_keeps_the_rest():
    _, c = copier()
    b = c.books["u1"]
    p = _hold(c)
    tr = c.close_manual("u1", "h1", 0.3)
    assert tr and tr["hold_parte"] == 0.3 and tr["aba"] == "hold" and abs(tr["eth_in"] - 0.003) < 1e-9
    assert tr in b.trades and "h1" in b.pos and abs(p["eth_in"] - 0.007) < 1e-9 and abs(p["tokens_left"] - 7.0) < 1e-9
    assert p["proceeds"] == 0.0 and tr["eth_out"] > 0
    tr2 = c.close_manual("u1", "h1", 1.0)
    assert tr2 and "h1" not in b.pos and "hold vendido por você" in tr2["motivo"]


def test_both_wallets_holds_show_in_the_panel():
    _, c = copier()
    _hold(c)
    _hold(c, real=True)
    for real in (False, True):
        h = c.painel("u1", real=real)["holds"]
        assert {x["real"] for x in h} == {False, True}


def test_real_hold_partial_sale_is_recorded():
    _, c = copier()
    _hold(c, real=True)
    rb = c.rbook("u1")

    async def key(uid):
        return 1, "0x" + "cc" * 20

    async def sell(key, addr, token, pkey, raw, slip):
        return {"raw": raw, "eth": 0.005, "gas": 0.00001, "tx": "0x" + "dd" * 32}
    c.get_key = key
    c.chain.sell = sell
    p = rb.pos["r1"]
    p["key"] = []
    tr = run(c.close_real("u1", "r1", 0.5))
    assert tr and tr["real"] and tr["hold_parte"] == 0.5 and "r1" in rb.pos and abs(p["eth_in"] - 0.005) < 1e-9 and tr in rb.trades


def test_hold_does_not_take_a_real_slot():
    _, c = copier()
    rc = c.rcfg("u1")
    rc["real_max_abertas"] = 1
    _hold(c, real=True)
    c.real_allowed = True
    why = c.real_why_not("u1", {"wallet": "0x" + "11" * 20, "token": "0x" + "ef" * 20}, c.rbook("u1"), rc)
    assert not (why or "").startswith("limite")


def test_old_rug_pulls_enter_the_list_with_the_token_itself():
    _, c = copier()
    c.books["u1"].trades.append({"id": "t", "token": TOK, "motivo": "o criador tirou toda a liquidez do pool (rug pull): perda total",
                                 "simbolo": "ETHEREM", "close_t": time.time(), "pnl_eth": -0.01})
    assert c.rug_scan_old() == 1

    async def dev(tk, now):
        return ""

    async def save():
        return None
    c._dev_of, c.rug_save = dev, save
    run(c.rug_tick(time.time()))
    assert TOK.lower() in c.rug and "rug pull" in c.rug_why(None, None, TOK)
    assert c.rug_scan_old() == 0                     # já está na lista: não repete


def test_hide_real_history_keeps_rows_and_can_show_again():
    _, c = copier()
    rb = c.rbook("u1")
    rb.trades.append({"id": "r", "real": True, "close_t": time.time() - 100, "pnl_eth": -0.01, "eth_in": 0.01, "wallet": "w", "token": TOK})
    r = run(c.hide_real_hist("u1", True))
    assert r["escondidas"] == 1 and len(rb.trades) == 1
    pn = c.painel("u1", real=True)
    assert pn["trades"] == [] and pn["hist_escondidas"] == 1 and pn["carteira"]["fechadas"] == 0
    assert rb.lost_today(time.time()) > 0             # a perda do dia continua contando
    run(c.hide_real_hist("u1", False))
    assert len(c.painel("u1", real=True)["trades"]) == 1
    assert "hist_desde" in open("app/hoodcopy.py", encoding="utf-8").read()


def test_trader_sell_never_touches_a_hold():
    w, c = copier()
    p = _hold(c)
    p["wallet"] = w.copiaria[0]
    c.on_trade(trade("sell", 10.0, 0.01), 10.0, w.copiaria)
    run(settle(c))
    assert "h1" in c.books["u1"].pos
    assert asyncio and hoodreal and hoodcopy


def test_real_sale_starts_before_the_fictitious_one():
    """0.32.507 (regra do dono): com a REAL ligada, a venda REAL presa à fictícia é disparada antes de a fictícia registrar a dela."""
    _, c = copier()
    b = c.books["u1"]
    p = _hold(c)
    p.pop("hold")
    visto = []
    b.close_hook = lambda uid, pp, motivo, frac=1.0: visto.append((pp["tokens_left"], pp["id"] in b.pos))
    b.sell(p, 1.0, 0.002, time.time(), "teste")
    assert visto == [(10.0, True)]
    src = open("app/hoodcopy.py", encoding="utf-8").read()
    assert "_sim_after(n0, sim)" in src and src.index("# 0.32.507: as REAL vêm primeiro") > 0
