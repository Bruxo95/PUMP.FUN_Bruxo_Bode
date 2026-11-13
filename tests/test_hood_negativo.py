"""0.32.322 (pedido do dono, 11/11/2026: "por que estamos sempre no negativo ... faz tudo de 1 a 6, se precisa alterar configuração
também faz"): saídas que não seguram a perda, entrada no preço de agora, atraso máximo, pausa do trader que dá prejuízo, ranking
que conta o token que o trader ainda segura no prejuízo, ida e volta de no máximo 8% e o quadro "Por que perdeu"."""
import time

from app import hood, hoodcopy, hoodreal, hoodsafe
from tests.test_hood_copia import KEY, TOK, TRADER, OTHER, copier, run, settle, trade


def test_new_defaults_cut_the_loss_and_let_the_gain_run():
    d, r = hoodcopy.CFG_DEFAULT, hoodreal.REAL_DEFAULT
    assert d["stop_pct"] == 30 and d["trader_so_lucro"] is False and d["trail_ativa_pct"] == 25 and d["trail_dist_pct"] == 20
    assert r["real_stop_pct"] == 30 and r["real_trader_so_lucro"] is False and r["real_trail_dist_pct"] == 20
    assert r["real_on"] is False                                   # nada liga a REAL
    assert hoodsafe.ROUNDTRIP_MAX == 8
    b = hoodcopy.Book("u", {"slip_pct": 0, "gas_eth": 0})
    t = time.time()
    p = b.buy(trade("buy", 1000.0, 1.0), 0.001, t, KEY)
    assert b.trader_exit(p, 1.0, 0.0009, t, "trader vendeu 100%")["pnl_eth"] < 0      # sai com o trader mesmo no prejuízo
    q = b.buy(trade("buy", 1000.0, 1.0, wallet=OTHER), 0.001, t, KEY)
    out = b.on_price(TOK, 0.00065, t)                              # -35%: o stop de 30% fecha
    assert out and out[0]["motivo"].startswith("stop de 30") and q["id"] not in b.pos


def test_upgrade_changes_only_what_was_still_the_old_default():
    velho = {"stop_pct": 0.0, "trader_so_lucro": True, "trail_ativa_pct": 20.0, "trail_dist_pct": 15.0, "gas_eth": 0.00002,
             "eth_por_compra": 0.0003, "real": {"real_on": True, "real_stop_pct": 12.0, "real_trader_so_lucro": True,
                                                "real_trail_ativa_pct": 20.0, "real_trail_dist_pct": 10.0}}
    novo, rc, mudou = hoodcopy.upgrade_cfg(velho)
    assert mudou and novo["cfg_v"] == hoodcopy.CFG_V
    assert novo["stop_pct"] == 30 and novo["trader_so_lucro"] is False and novo["trail_ativa_pct"] == 25 and novo["gas_eth"] == 0.000008
    assert novo["trail_dist_pct"] == 15.0 and novo["eth_por_compra"] == 0.0003       # o que a pessoa escolheu fica
    assert rc["real_stop_pct"] == 12.0 and rc["real_trader_so_lucro"] is False and rc["real_trail_dist_pct"] == 20
    assert rc["real_on"] is True                                   # ligado continua ligado, desligado continua desligado
    assert velho["stop_pct"] == 0.0 and velho["real"]["real_trader_so_lucro"] is True  # o original não muda (vai para o histórico)
    de_novo, _, mudou2 = hoodcopy.upgrade_cfg({**novo, "stop_pct": 0.0})
    assert not mudou2 and de_novo["stop_pct"] == 0.0               # quem voltou o stop para 0 depois do ajuste fica com 0
    assert hoodcopy.clean_cfg(novo)["cfg_v"] == hoodcopy.CFG_V and "cfg_v" in hoodcopy.HIST_SKIP


def test_upgrade_runs_once_on_load_and_goes_to_the_config_history():
    class DB:
        def __init__(self):
            self.rows = {"hood_books": [{"user_id": "u1", "cash": 0.4, "cfg": {"stop_pct": 0.0, "trader_so_lucro": True, "max_hold_h": 3.0,
                                                                              "real": {"real_stop_pct": 0.0}}}]}
            self.ins = []

        async def select(self, table, flt=None, **kw):
            return list(self.rows.get(table, []))

        async def insert(self, table, row, **kw):
            self.ins.append((table, row))

        async def delete(self, *a, **kw):
            pass

    async def go():
        w, c = copier()
        c.books.clear()
        c.db = db = DB()
        await c.load()
        b = c.books["u1"]
        assert b.cfg["stop_pct"] == 30 and b.cfg["trader_so_lucro"] is False and b.cfg["max_hold_h"] == 3.0 and b.cash == 0.4
        assert c.rcfg("u1")["real_stop_pct"] == 30 and not c.rcfg("u1").get("real_on")
        vers = [r for t, r in db.ins if t == "hood_config_versions"]
        assert vers[0]["cfg"]["stop_pct"] == 0.0 and vers[0]["cfg"]["real_stop_pct"] == 0.0        # como estava: dá para voltar
        assert vers[-1]["origem"] == hoodcopy.AJUSTE and vers[-1]["cfg"]["stop_pct"] == 30
        assert b.dirty_book                                           # grava o cfg_v para não ajustar de novo
    run(go())


def test_entry_block_late_stretched_price_and_losing_trader():
    c = hoodcopy.clean_cfg({})
    t = 1000.0
    tr = {"wallet": TRADER, "token": TOK, "t": t - 60}
    assert "60 s depois" in hoodcopy.entry_block(c, tr, t, None, "top", [])
    tr["t"] = t - 5
    assert hoodcopy.entry_block(c, tr, t, 14.0, "top", []) is None
    assert "acima do que o trader pagou" in hoodcopy.entry_block(c, tr, t, 40.0, "top", [])
    assert hoodcopy.entry_block({**c, "max_acima_pct": 0}, tr, t, 40.0, "top", []) is None       # 0 = desligado
    ruins = [{"wallet": TRADER, "close_t": t - 60, "pnl_eth": -0.001}] * 3
    assert "trader em pausa" in hoodcopy.entry_block(c, tr, t, None, "top", ruins)
    assert hoodcopy.entry_block(c, tr, t, None, "manual", ruins) is None      # escolhido à mão: você manda
    assert hoodcopy.entry_block(c, tr, t, None, "top", ruins[:2]) is None     # menos de 3 cópias: ainda não julga
    assert hoodcopy.entry_block(c, tr, t, None, "top", ruins + [{"wallet": TRADER, "close_t": t - 10, "pnl_eth": 0.01}]) is None
    assert hoodcopy.entry_block(c, {**tr, "t": t - 500}, t, 900.0, "botao", ruins) is None        # o botão Comprar não passa por aqui


def test_copy_enters_at_the_price_of_now_not_at_the_trader_price():
    async def go():
        w, c = copier()                                    # o pool do teste cota 1 ETH = 1000 tokens (0,001 por token)
        c.on_trade(trade("buy", 2000.0, 1.0), 0.0, w.copiaria)        # o trader pagou 0,0005: o preço de agora está ~98% acima
        await settle(c)
        b = c.books["u1"]
        assert not b.pos and "acima do que o trader pagou" in b.events[0]["motivo"]
        b.cfg["max_acima_pct"] = 0
        c.on_trade(trade("buy", 2000.0, 1.0), 0.0, w.copiaria)
        await settle(c)
        p = next(iter(b.pos.values()))
        assert abs(p["trader_px"] - 0.0005) < 1e-12 and p["acima_pct"] > 90
        assert abs(p["px_in"] - 0.001 * 0.99 * 1.02) < 1e-9          # preço do pool agora (sem a taxa de 1%) + a folga de 2%
    run(go())


def test_real_without_mirror_also_refuses_the_late_buy():
    async def go():
        w, c = copier()
        b = c.book("u1")
        b.cfg.update(on=False)
        c.rcfg("u1").update(real_on=True, real_espelho=False)
        chamou = []

        async def real_buy(*a):
            chamou.append(a)
        c._real_buy = real_buy
        c._buy_all(trade("buy", 1000.0, 1.0, t=time.time() - 70), {"ok": True}, KEY, 0.001)
        await settle(c)
        assert not chamou and "70 s depois" in c.real["u1"].events[0]["motivo"]
        c._buy_all(trade("buy", 1000.0, 1.0), {"ok": True}, KEY, 0.001)
        await settle(c)
        assert len(chamou) == 1
    run(go())


def test_rank_counts_the_bag_the_trader_still_holds_at_a_loss():
    now = 1_000_000.0
    A, B = "0x" + "a1" * 20, "0x" + "b2" * 20
    trades, px = [], {}
    for i in range(12):                                    # A: 12 tokens vendidos com lucro pequeno e 12 que despencaram e ele não vendeu
        g, r = f"0x{i:040x}", f"0x{i + 100:040x}"
        trades += [{"t": now - 900 + i, "wallet": A, "token": g, "side": "buy", "eth": 0.1, "amount": 100.0},
                   {"t": now - 600 + i, "wallet": A, "token": g, "side": "sell", "eth": 0.12, "amount": 100.0},
                   {"t": now - 500 + i, "wallet": A, "token": r, "side": "buy", "eth": 0.1, "amount": 100.0}]
        px[r] = (0.0001, now)                              # vale 10% do que custou
    for i in range(12):                                    # B: ganha menos por token, mas fecha tudo
        g = f"0x{i + 200:040x}"
        trades += [{"t": now - 900 + i, "wallet": B, "token": g, "side": "buy", "eth": 0.1, "amount": 100.0},
                   {"t": now - 600 + i, "wallet": B, "token": g, "side": "sell", "eth": 0.11, "amount": 100.0}]
    cfg = {"min_wallet_usd": 0, "online_min": 60, "min_trades": 1}
    antes = hood.rank(trades, now, cfg, {})                # sem preço: A parece o melhor
    assert antes["rows"][0]["wallet"] == A and antes["rows"][0]["winrate"] == 100.0
    r = hood.rank(trades, now, cfg, {}, px)
    a = next(x for x in r["rows"] if x["wallet"] == A)
    assert r["rows"][0]["wallet"] == B and r["copiaria"] == [B]
    assert a["bags"] == 12 and a["winrate"] == 50.0 and a["realized_eth"] < 0 and abs(a["vendido_eth"] - 0.24) < 1e-9
    assert not a["eligible"]
    d = hood.clean_cfg({})
    assert d["min_closed"] == 5 and d["bot_per_day"] == 150 and d["v"] == 2


def test_why_lost_groups_by_reason_trader_and_delay():
    now = 1_000_000.0
    def x(pnl, motivo, lag, wallet=TRADER, best=0.0):
        return {"close_t": now - 100, "open_t": now - 500, "eth_in": 0.01, "pnl_eth": pnl, "pnl_pct": 100 * pnl / 0.01, "motivo": motivo,
                "lag_s": lag, "wallet": wallet, "taxas_eth": 0.0004, "best_pct": best}
    ts = [x(-0.008, "tempo máximo de 6 h", 40), x(-0.006, "tempo máximo de 6 h", 35, best=18.0), x(0.0005, "stop móvel: pico +22%, saiu em +5%", 4),
          x(0.0001, "trader saiu da moeda · vendeu ao ficar positivo (+1.0%)", 8, OTHER), x(-0.003, "stop de 30%", 12),
          {**x(-0.5, "velho", 1), "close_t": now - 30 * 86400}]
    w = hoodcopy.why_lost(ts, now)
    assert w["n"] == 5 and abs(w["pnl"] - (-0.0164)) < 1e-9 and w["taxas_pct"] == 4.0 and w["acerto"] == 40.0
    assert w["motivos"][0]["k"] == "Tempo máximo" and w["motivos"][0]["n"] == 2 and abs(w["motivos"][0]["pnl"] + 0.014) < 1e-9
    assert {m["k"] for m in w["motivos"]} == {"Tempo máximo", "Stop móvel", "Esperou ficar positivo", "Stop de perda"}
    assert w["traders"][0]["k"] == TRADER and w["atraso"][0]["k"] == "mais de 30 s"
    assert w["devolveu"] == 1 and w["ganho_medio_pct"] == 3.0 and w["perda_media_pct"] < -50
    assert 90 < w["acerto_empate"] < 100                   # ganhando 3% e perdendo 57% em média, só empata acertando quase tudo
    vazio = hoodcopy.why_lost([], now)
    assert vazio["n"] == 0 and vazio["acerto"] is None and vazio["motivos"] == []


def test_panel_brings_the_why_lost_board():
    async def go():
        w, c = copier()
        pa = c.painel("u1")
        assert pa["porque"]["n"] == 0 and pa["padrao"]["max_atraso_s"] == 45
        assert c.painel("u1", real=True)["porque"]["n"] == 0
    run(go())


def test_round_trip_above_8_pct_is_barred():
    async def go():
        w, c = copier(loss=0.10)
        c.on_trade(trade("buy", 1000.0, 1.0), 0.0, w.copiaria)
        await settle(c)
        b = c.books["u1"]
        assert not b.pos and "ida e volta perde" in b.events[0]["motivo"]
    run(go())
