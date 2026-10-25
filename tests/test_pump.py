"""Testes da cópia de traders (referência: test_pump_* do hermes-jev-trader). Nenhum usa internet:
toda resposta de rede é falsa (httpx.MockTransport)."""
import asyncio
import json
import time

import httpx


# ---------------------------------------------------------------- PUMP.FUN (cópia de traders)
def _pump(tmp_path, paid=True, **kw):
    from app.pumpfun import PumpFun
    from app.settings import PumpSettings
    from app.store import MemStore
    cfg = PumpSettings()
    cfg.pump_rank_every_s = 0
    cfg.pump_lb_min_trades = 0
    cfg.pump_min_mcap_usd = cfg.pump_min_vol_h1_usd = cfg.pump_max_top10_pct = cfg.pump_min_wallet_usd = 0
    cfg.pump_min_txns_h1 = 0
    cfg.pump_only_online = False          # regra nova (só online) tem testes próprios em test_online.py
    for k, v in kw.items():
        setattr(cfg, k, v)
    pf = PumpFun(cfg, MemStore())
    if paid:
        cfg.pump_paid_stream = True

        class _R:
            def api_key(self):
                return "pp-key-xxxxxxxxxxxxxxxx"
        pf.real = _R()
    return pf


_W = "TraderGood1111111111111111111111111111111"


_SN = "SniperBot11111111111111111111111111111111"


def _ev(kind, who, mint, sol, tok, vs, vt, **x):
    return {"txType": kind, "traderPublicKey": who, "mint": mint, "solAmount": sol, "tokenAmount": tok,
            "vSolInBondingCurve": vs, "vTokensInBondingCurve": vt, "marketCapSol": vs * 30, **x}


def _round_trip(pf, who, mint, t0, hold, buy_px, sell_px, sol=1.0):
    tok = sol / buy_px
    pf.on_message(_ev("create", "Dev" + mint[:30].ljust(38, "1"), mint, 0, 0, 30, 30 / buy_px, symbol=mint[:4]), t0 - 1)
    pf.on_message(_ev("buy", who, mint, sol, tok, 30, 30 / buy_px), t0)
    pf.on_message(_ev("sell", who, mint, tok * sell_px, tok, 30, 30 / sell_px, newTokenBalance=0), t0 + hold)


def test_pump_ranking_filters_snipers_and_ranks_by_realized_pnl(tmp_path):
    import time as _t
    pf = _pump(tmp_path)
    now = _t.time()
    for i in range(4):
        _round_trip(pf, _W, f"MintGood{i}".ljust(40, "1"), now - 3000 + i * 100, 120, 1e-6, 1.5e-6)   # +50% segurando 2 min
        _round_trip(pf, _SN, f"MintSnip{i}".ljust(40, "1"), now - 3000 + i * 100, 3, 1e-6, 2e-6)      # +100% em 3 s
    rk = {r["wallet"]: r for r in pf.ranking()}
    assert rk[_W]["eligible"] and abs(rk[_W]["pnl_sol"] - 2.0) < 1e-6 and rk[_W]["winrate"] == 100
    assert not rk[_SN]["eligible"] and any("sniper" in f for f in rk[_SN]["flags"])
    pf.refresh_followed(force=True)
    assert pf.followed == [_W]
    assert any(m["method"] == "subscribeAccountTrade" and _W in m["keys"] for m in pf._flush_subs())


def test_pump_copy_buy_and_proportional_sell_simulated(tmp_path):
    pf = _pump(tmp_path, pump_copy_sol=0.1, pump_extra_slip_pct=3.0, pump_fee_pct=1.0, pump_portal_fee_pct=0.0,
               pump_priority_sol=0.0005)
    pf.add_manual(_W)
    assert pf.followed == [_W]
    mint = "MintCopy".ljust(40, "1") + "pump"
    msgs = pf.on_message(_ev("buy", _W, mint, 1.0, 1e6, 40, 40 / 1e-6))   # preço 1e-6 SOL
    assert msgs and "copiou" in msgs[0]
    p = pf.positions()[0]
    assert abs(p["price_in"] - 1.03e-6) < 1e-12 and abs(p["tokens"] - 0.1 * 0.99 / 1.03e-6) < 1
    # vende metade: newTokenBalance = metade
    pf.on_message(_ev("sell", _W, mint, 1.0, 5e5, 40, 40 / 2e-6, newTokenBalance=5e5))
    p = pf.positions()[0]
    assert abs(p["tokens_left"] / p["tokens"] - 0.5) < 1e-6 and p["proceeds"] > 0
    pf.on_message(_ev("sell", _W, mint, 1.0, 5e5, 40, 40 / 2e-6, newTokenBalance=0))
    assert not pf.positions()
    tr = pf.trades()[0]
    assert tr["pnl_sol"] > 0 and tr["pnl_pct"] > 50 and not tr["real"]
    w = pf.wallet()
    assert abs(w["equity_sol"] - (5.0 + tr["pnl_sol"])) < 1e-6 and w["count"] == 1 and w["wins"] == 1


def test_pump_stop_loss_limits_and_skips(tmp_path):
    pf = _pump(tmp_path, pump_stop_pct=40.0, pump_max_open=1, pump_min_trader_sol=0.2)
    pf.add_manual(_W)
    m1, m2 = "MintStop".ljust(40, "1"), "MintTwo1".ljust(40, "1")
    assert not pf.on_message(_ev("buy", _W, m1, 0.05, 5e4, 30, 3e7))          # compra pequena: não copia
    assert pf.feed[0]["action"] == "não copiou" and "pequena" in pf.feed[0]["reason"]
    pf.on_message(_ev("buy", _W, m1, 1.0, 1e6, 30, 3e7))
    pf.on_message(_ev("buy", _W, m2, 1.0, 1e6, 30, 3e7))
    assert len(pf.positions()) == 1 and "limite" in pf.feed[0]["reason"]
    # outro trader derruba o preço 60% → stop
    msgs = pf.on_message(_ev("sell", "Other111".ljust(40, "1"), m1, 1.0, 1e6, 12, 3e7))
    assert any("stop" in m for m in msgs) and not pf.positions()
    assert pf.trades()[0]["pnl_sol"] < 0


def test_pump_track_tokens_rotates_subscriptions(tmp_path):
    pf = _pump(tmp_path, pump_track_tokens=3)
    for i in range(5):
        pf.on_message(_ev("create", "Dev" + str(i).ljust(38, "1"), f"Mint{i}".ljust(40, "1"), 0, 0, 30, 3e7))
    subs = pf._flush_subs()
    sub = [k for m in subs if m["method"] == "subscribeTokenTrade" for k in m["keys"]]
    uns = [k for m in subs if m["method"] == "unsubscribeTokenTrade" for k in m["keys"]]
    assert len(sub) == 5 and len(uns) == 2 and len(pf.sub_tokens) == 3


def test_pump_leaderboard_solanatracker_drives_followed(tmp_path):
    import httpx as _h
    from app.keystore import KeyRing
    pf = _pump(tmp_path)
    seen = {}

    def h(req):
        seen["url"] = str(req.url)
        seen["key"] = req.headers.get("x-api-key")
        tr = [{"wallet": f"Top{i}".ljust(44, "1"), "period": {"realized": 50000 - i * 1000, "roi": 120, "tradingDays": 6},
               "winRate": 0.62, "counts": {"trades": 300, "tokensTraded": 80}, "tokens": {"closed": 70},
               "timing": {"lastTrade": 1792700000000}, "identity": {"name": f"KOL {i}"}} for i in range(12)]
        tr[1]["identity"] = {"bot": {"name": "Axiom bot"}}
        return _h.Response(200, json={"traders": tr, "pagination": {"hasMore": False}})

    pf.http = _h.AsyncClient(transport=_h.MockTransport(h))
    asyncio.run(pf.refresh_leaderboard(force=True))
    assert pf.lb_status["error"] == "sem chave da Solana Tracker" and not pf.leaderboard
    pf.keys = KeyRing()
    pf.keys.set("solanatracker_api_key", "st-" + "x" * 30)
    asyncio.run(pf.refresh_leaderboard(force=True))
    assert "platform=pumpfun-app" in seen["url"] and "days=7" in seen["url"] and seen["key"].startswith("st-")
    assert len(pf.leaderboard) == 12 and pf.leaderboard[0]["winrate"] == 62
    assert not pf.leaderboard[1]["eligible"]
    assert len(pf.followed) == 10 and pf.leaderboard[1]["wallet"] not in pf.followed
    assert pf.followed[0] == pf.leaderboard[0]["wallet"]
    pf.add_manual(_W)
    assert pf.followed[0] == _W and len(pf.followed) == 10
    snap = pf.snapshot()
    assert snap["lb_status"]["source"] == "leaderboard" and snap["followed"][1]["source"] == "leaderboard"
    assert "st-" + "x" * 30 not in json.dumps(snap)


def test_pump_live_monitor_entries_exits_only_followed(tmp_path):
    pf = _pump(tmp_path)
    pf.add_manual(_W)
    m = "MintLive".ljust(40, "1")
    pf.on_message(_ev("buy", _W, m, 1.0, 1e6, 30, 3e7, signature="sig1"))
    pf.on_message(_ev("buy", "Stranger".ljust(40, "1"), m, 1.0, 1e6, 30, 3e7))      # não copiado: fora do monitor
    tp = pf.trader_positions()
    assert len(tp) == 1 and tp[0]["wallet"] == _W and abs(tp[0]["invested_sol"] - 1.0) < 1e-9
    pf.on_message(_ev("sell", _W, m, 0.75, 5e5, 30, 3e7 / 1.5, newTokenBalance=5e5))   # vende metade a 1,5×
    pf.on_message(_ev("sell", _W, m, 0.8, 5e5, 30, 3e7 / 1.6, newTokenBalance=0))
    snap = pf.snapshot()
    acts = [e["action"] for e in snap["live"]]
    assert acts == ["saiu", "vendeu parte", "entrou"]
    assert all(e["wallet"] == _W for e in snap["live"])
    assert abs(snap["live"][1]["pnl_pct"] - 50.0) < 0.5 and snap["live"][1]["sold_pct"] == 50
    assert snap["trader_pos"] == [] and m in pf.sub_tokens


def test_pump_free_rpc_parse_trade_and_copy(tmp_path):
    """Monitor grátis: transação da Solana (getTransaction jsonParsed) → evento de compra/venda do trader."""
    from app.pumpfun import SOL_MINT
    pf = _pump(tmp_path, paid=False)
    assert pf._flush_subs() == []                       # sem chave paga: nada de streams pagos da PumpPortal
    pf.add_manual(_W)
    mint = "MintRpc".ljust(44, "1")

    def tx(sol_pre, sol_post, tok_pre, tok_post, sig, wsol=None):
        pre_t = [{"owner": _W, "mint": mint, "uiTokenAmount": {"uiAmountString": str(tok_pre)}}] if tok_pre is not None else []
        post_t = [{"owner": _W, "mint": mint, "uiTokenAmount": {"uiAmountString": str(tok_post)}}]
        return {"blockTime": 1, "transaction": {"signatures": [sig], "message": {"accountKeys": [{"pubkey": _W}, {"pubkey": "X"}]}},
                "meta": {"err": None, "fee": 5000, "preBalances": [int(sol_pre * 1e9), 0], "postBalances": [int(sol_post * 1e9), 0],
                         "preTokenBalances": pre_t, "postTokenBalances": post_t}}
    ev = pf.parse_trade(tx(10, 8.999995, None, 1_000_000, "s1"), _W)       # comprou 1 SOL de token
    assert ev["txType"] == "buy" and abs(ev["solAmount"] - 1.0) < 1e-6 and ev["tokenAmount"] == 1_000_000
    msgs = pf.on_message(ev)
    assert msgs and "copiou" in msgs[0] and len(pf.positions()) == 1
    ev = pf.parse_trade(tx(9, 10.999995, 1_000_000, 0, "s2"), _W)          # vendeu tudo por 2 SOL
    assert ev["txType"] == "sell" and ev["newTokenBalance"] == 0 and abs(ev["solAmount"] - 2.0) < 1e-6
    pf.on_message(ev)
    assert not pf.positions() and pf.trades()[0]["pnl_sol"] > 0
    assert [e["action"] for e in pf.snapshot()["live"]] == ["saiu", "entrou"]
    assert pf.parse_trade({"meta": {"err": {"x": 1}}, "transaction": {}}, _W) is None


def test_pump_rpc_ignores_stablecoin_and_non_pump_trades(tmp_path):
    """Trader que troca SOL↔USDC não vira 'compra de USDC'; só memecoins da pump.fun são copiadas."""
    from app.pumpfun import USDC
    pf = _pump(tmp_path, paid=False)
    pf.add_manual(_W)

    def tx(sol_pre, sol_post, mint, tok_pre, tok_post):
        return {"transaction": {"signatures": ["s"], "message": {"accountKeys": [{"pubkey": _W}]}},
                "meta": {"err": None, "fee": 5000, "preBalances": [int(sol_pre * 1e9)], "postBalances": [int(sol_post * 1e9)],
                         "preTokenBalances": [{"owner": _W, "mint": mint, "uiTokenAmount": {"uiAmountString": str(tok_pre)}}],
                         "postTokenBalances": [{"owner": _W, "mint": mint, "uiTokenAmount": {"uiAmountString": str(tok_post)}}]}}
    assert pf.parse_trade(tx(10, 9.000005, USDC, 0, 150), _W, 150.0) is None     # SOL→USDC: não é trade de token
    meme = "Abc".ljust(40, "1") + "pump"
    ev = pf.parse_trade(tx(10, 9.000005, meme, 0, 1e6), _W, 150.0)
    assert ev["mint"] == meme and pf.is_pump(meme)
    other = "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"
    assert not pf.is_pump(other) and not pf.is_pump(USDC)
    # posição antiga em USDC (bug) é removida e devolvida
    pf._save_pos({"opened_at": "x", "open_t": 0, "wallet": _W, "mint": USDC, "symbol": "USDC", "sol_in": 0.1, "tokens": 1,
                  "tokens_left": 1, "price_in": 0.1, "proceeds": 0.0, "fees_sol": 0, "real": False})
    pf._purge_quote_positions()
    assert not pf.positions() and pf.wallet()["equity_sol"] == 5.0


def test_pump_hyperactive_wallet_is_marked_bot_and_replaced(tmp_path):
    import time as _t
    from collections import deque as _dq
    pf = _pump(tmp_path, paid=False)
    pf.leaderboard = [{"wallet": f"W{i}".ljust(44, "1"), "eligible": True, "rank": i + 1, "winrate": 70.0} for i in range(12)]
    pf.refresh_followed(force=True)
    bot = pf.followed[0]
    now = _t.time()
    pf.activity[bot] = {"n": _dq([now] * 50, maxlen=600), "pn": _dq([now] * 40, maxlen=600), "pump": 40, "other": 0}
    assert pf._is_bot(bot, now) and pf.activity_view(bot)["status"] == "robô"
    pf.refresh_followed()
    assert bot not in pf.followed and len(pf.followed) == 10 and pf.leaderboard[10]["wallet"] in pf.followed


def test_pump_only_copies_traders_with_winrate_above_50(tmp_path):
    pf = _pump(tmp_path, paid=False)
    pf.leaderboard = pf._parse_lb({"traders": [
        {"wallet": "A".ljust(44, "1"), "winRate": 0.72, "period": {"realized": 900}},
        {"wallet": "B".ljust(44, "1"), "winRate": 0.50, "period": {"realized": 800}},     # 50% não é "acima"
        {"wallet": "C".ljust(44, "1"), "winRate": 0.31, "period": {"realized": 700}},
        {"wallet": "D".ljust(44, "1"), "period": {"realized": 600}}]})                    # sem acerto: fora
    pf.refresh_followed(force=True)
    assert pf.followed == ["A".ljust(44, "1")]
    assert "precisa > 50%" in " ".join(pf.leaderboard[1]["flags"])
    pf.cfg.pump_min_winrate = 30.0                                                      # mudou no painel: vale já
    pf.refresh_followed()
    assert set(pf.followed) == {"A".ljust(44, "1"), "B".ljust(44, "1"), "C".ljust(44, "1")}


def test_pump_sim_result_is_net_of_real_fees(tmp_path):
    """Compra e venda no mesmo preço do trader: o líquido é negativo só pelas taxas reais (1,25% + 0,5% por lado
    + rede + slippage); bruto + taxas = líquido."""
    pf = _pump(tmp_path, paid=False, pump_copy_sol=0.1, pump_extra_slip_pct=0.0, pump_priority_sol=0.0005,
               pump_hold_until_profit=False)
    pf.add_manual(_W)
    m = "Fee".ljust(40, "1") + "pump"
    pf.on_message(_ev("buy", _W, m, 1.0, 1e6, 30, 3e7))
    pf.on_message(_ev("sell", _W, m, 1.0, 1e6, 30, 3e7, newTokenBalance=0))
    t = pf.trades()[0]
    fp = t["fee_parts"]
    assert abs(fp["platform"] - (0.1 * 0.0125 + 0.1 * 0.9825 * 0.0125)) < 1e-6
    assert abs(fp["network"] - 0.001) < 1e-9 and fp["portal"] > 0
    assert abs(t["gross_sol"] - t["fees_sol"] - t["pnl_sol"]) < 1e-6
    assert abs(t["gross_sol"]) < 1e-3                    # sem as taxas, empataria
    assert -5.0 < t["pnl_pct"] < -4.0                    # ~4,5% de custo ida e volta com 0,1 SOL


def test_pump_real_mode_buys_and_sells_for_real_and_records_real_trades(tmp_path):
    """Com o real LIGADO: a compra do trader vira compra REAL (valores medidos na carteira), a venda dele vira venda
    REAL, e o histórico/carteira real ficam separados da simulação."""
    pf = _pump(tmp_path, paid=False, pump_real_max_sol=0.05)
    pf.cfg.pump_real_enabled = True
    calls = []

    class FakeReal:
        def api_key(self):
            return ""

        def today_loss(self, trades):
            return 0.0

        async def buy(self, mint, amt, other=False):
            calls.append(("buy", amt))
            return {"ok": True, "signature": "BUY1", "sol_spent": 0.0512, "tokens": 1_000_000.0}

        async def sell(self, mint, frac, other=False):
            calls.append(("sell", frac))
            return {"ok": True, "signature": "SELL1", "sol_received": 0.0700, "tokens_left": 0.0}
    pf.real = FakeReal()
    pf.add_manual(_W)
    m = "Real".ljust(40, "1") + "pump"
    pf.on_message(_ev("buy", _W, m, 1.0, 1e6, 30, 3e7))
    assert m in pf._real_buying and pf._rq.qsize() == 1
    kind, it = pf._rq.get_nowait()
    asyncio.run(pf._real_buy(it))
    real = [p for p in pf.positions() if p.get("real")]
    sim = [p for p in pf.positions() if not p.get("real")]
    assert len(real) == 1 and len(sim) == 1 and real[0]["sol_in"] == 0.0512 and calls == [("buy", 0.05)]
    pf.on_message(_ev("sell", _W, m, 1.0, 1e6, 30, 3e7 / 1.4, newTokenBalance=0))
    kind, it = pf._rq.get_nowait()
    assert kind == "sell" and it["frac"] == 1.0
    asyncio.run(pf._real_do_sell(it))
    rt = [t for t in pf.trades() if t["real"]]
    assert len(rt) == 1 and abs(rt[0]["pnl_sol"] - (0.07 - 0.0512)) < 1e-9 and rt[0]["signature"] == "BUY1"
    assert pf.wallet(real=True)["count"] == 1 and pf.wallet()["count"] == 1        # sim e real separados
    assert not [p for p in pf.positions() if p.get("real")]


def test_pump_copy_delay_skips_quick_flips_and_copies_holders(tmp_path):
    import time as _t
    pf = _pump(tmp_path, paid=False, pump_copy_delay_s=30.0)
    pf.add_manual(_W)

    async def no_fetch(m):
        return None
    pf._fetch_prices = no_fetch
    a, b = "Flip".ljust(40, "1") + "pump", "Hold".ljust(40, "1") + "pump"
    now = _t.time()
    pf.on_message(_ev("buy", _W, a, 1.0, 1e6, 30, 3e7), now)
    pf.on_message(_ev("buy", _W, b, 1.0, 1e6, 30, 3e7), now)
    assert not pf.positions() and len(pf._pending) == 2
    pf.on_message(_ev("sell", _W, a, 1.1, 1e6, 30, 3e7, newTokenBalance=0), now + 8)     # saiu em 8 s
    assert (_W, a) not in pf._pending and "saiu em 8 s" in pf.feed[0]["reason"]
    pf.tokens[b]["price"] = 1.2e-6                                                          # preço subiu na espera
    for k in pf._pending:
        pf._pending[k]["due"] = now - 1
    asyncio.run(pf._process_pending())
    pos = pf.positions()
    assert len(pos) == 1 and pos[0]["mint"] == b and pos[0]["price_in"] > 1.2e-6          # entrou no preço de agora


def test_pump_copies_trades_outside_pumpfun(tmp_path):
    """Trader copiado comprou um token fora da pump.fun (Raydium etc.): copia no fictício com taxa de DEX, sem
    PumpPortal; no real só se 'Real fora da pump.fun' estiver ligado."""
    from app.pumpfun import USDC
    pf = _pump(tmp_path, paid=False, pump_extra_slip_pct=0.0, pump_other_slip_pct=0.0)
    pf.add_manual(_W)
    tok = "Ray".ljust(44, "1")                                   # não termina em 'pump'
    pf.tokens[tok] = {"symbol": "RAYX", "liq_usd": 500000.0, "main_dex": "raydium", "price": 1e-3}
    assert not pf.is_pump(tok) and pf._other_block(tok) is None
    assert pf._other_block(USDC)
    pf.tokens["Small".ljust(44, "1")] = {"liq_usd": 1000.0}
    assert "liquidez" in pf._other_block("Small".ljust(44, "1"))
    pf.on_message({"txType": "buy", "traderPublicKey": _W, "mint": tok, "solAmount": 1.0, "tokenAmount": 1000.0,
                   "newTokenBalance": 1000.0, "other": True})
    p = pf.positions()[0]
    assert p["venue_in"] == "DEX raydium" and p["fee_parts"]["portal"] == 0.0
    assert abs(p["fee_parts"]["platform"] - 0.1 * 0.003) < 1e-9
    pf.cfg.pump_copy_other = False
    assert pf._other_block(tok) == "cópia fora da pump.fun desligada"


def test_pump_hold_until_profit_when_trader_exits_at_loss(tmp_path):
    """Trader saiu e a nossa posição está no prejuízo (já com taxas): não vende; vende quando ficar positiva."""
    pf = _pump(tmp_path, paid=False, pump_extra_slip_pct=0.0)
    pf.add_manual(_W)
    m = "Hold".ljust(40, "1") + "pump"
    pf.on_message(_ev("buy", _W, m, 1.0, 1e6, 30, 3e7))                       # entra a 1e-6
    pf.on_message(_ev("sell", _W, m, 0.8, 1e6, 30, 3e7 / 0.8, newTokenBalance=0))   # trader sai a 0,8e-6 (−20%)
    p = pf.positions()[0]
    assert p["hold_profit"] and not pf.trades() and pf.feed[0]["action"] == "segurando"
    pf.tokens[m]["price"] = 1.01e-6                                          # +1%: ainda negativo depois das taxas
    pf._check_stops(m, 0)
    assert pf.positions() and not pf.trades()
    pf.tokens[m]["price"] = 1.08e-6                                          # +8%: positivo líquido
    pf._check_stops(m, 0)
    t = pf.trades()[0]
    assert not pf.positions() and t["pnl_sol"] > 0 and "segurou até ficar positivo" in t["reason"]
    # trader sai no LUCRO: vende junto normalmente
    m2 = "Win".ljust(40, "1") + "pump"
    pf.on_message(_ev("buy", _W, m2, 1.0, 1e6, 30, 3e7))
    pf.on_message(_ev("sell", _W, m2, 1.5, 1e6, 30, 3e7 / 1.5, newTokenBalance=0))
    assert not [p for p in pf.positions() if p["mint"] == m2]


def test_pump_real_buy_falls_back_to_pumpswap_then_jupiter_when_curve_complete(tmp_path):
    from app.settings import PumpSettings
    from app.pumpfun import PumpReal
    cfg = PumpSettings()
    cfg.pump_real_enabled = True

    class W:
        keypair = object()
        address = "Me".ljust(44, "1")
        rpc_url = "x"
    pr = PumpReal(cfg, None, W(), None)
    st = {"tok": 0.0, "sol": 1.0, "calls": []}

    async def bal(mint):
        return st["sol"], st["tok"]

    async def tx(body):
        st["calls"].append(body.get("pool"))
        if body.get("pool") == "auto":
            return {"ok": False, "status": "recusada", "reason": "Transaction simulation failed: custom program error: 0x1775"}
        st["tok"], st["sol"] = 1000.0, st["sol"] - 0.0506            # PumpSwap funcionou
        return {"ok": True, "status": "confirmada", "signature": "S"}
    pr.balances, pr._tx = bal, tx
    r = asyncio.run(pr.buy("Tok".ljust(40, "1") + "pump", 0.05))
    assert r["ok"] and st["calls"] == ["auto", "pump-amm"] and abs(r["sol_spent"] - 0.0506) < 1e-9
    assert "graduou" in PumpReal.explain("custom program error: 0x1775")


def test_pump_real_sell_retries_pumpportal_with_more_slippage_before_jupiter(tmp_path):
    from app.settings import PumpSettings
    from app.pumpfun import PumpReal
    cfg = PumpSettings()

    class W:
        keypair = object()
        address = "Me".ljust(44, "1")
        rpc_url = "x"
    pr = PumpReal(cfg, None, W(), None)
    st = {"tok": 1000.0, "sol": 0.3, "calls": []}

    async def bal(mint):
        return st["sol"], st["tok"]

    async def tx(body):
        st["calls"].append((body.get("pool"), body.get("slippage")))
        if body.get("slippage") < 30:
            return {"ok": False, "status": "recusada", "reason": "custom program error: 0x1773"}
        st["tok"], st["sol"] = 0.0, st["sol"] + 0.04
        return {"ok": True, "status": "confirmada", "signature": "S"}

    async def jup(*a, **k):
        st["calls"].append(("jupiter", None))
        return {"ok": False, "status": "falhou", "reason": "sem cotação"}
    pr.balances, pr._tx, pr._jup = bal, tx, jup
    r = asyncio.run(pr.sell("Tok".ljust(40, "1") + "pump", 1.0))
    assert r["ok"] and st["calls"] == [("auto", 15.0), ("auto", 30.0)] and abs(r["sol_received"] - 0.04) < 1e-9


def test_pump_live_price_from_bonding_curve_onchain(tmp_path):
    import base64 as _b64
    import httpx as _h
    pf = _pump(tmp_path, paid=False)
    m = "Hvc15QpFBGRsB4hcbfMaaJZk9b5UCM97PcX5tLWVk5q6"
    data = bytes(8) + (1_000_000_000_000_000).to_bytes(8, "little") + (36_000_000_000).to_bytes(8, "little") \
        + bytes(24) + b"\x00" + bytes(117)

    def h(req):
        js = json.loads(req.content)
        assert js["method"] == "getMultipleAccounts" and js["params"][0] == [pf.curve_pda(m)]
        return _h.Response(200, json={"result": {"value": [{"data": [_b64.b64encode(data).decode(), "base64"]}]}})
    pf.http = _h.AsyncClient(transport=_h.MockTransport(h))
    assert pf.curve_pda(m) == "8JPhxFVkgtGKDQAgsNZD1MC3QGcnFV2HadMkUuLAkmk3"
    rest = asyncio.run(pf._curve_prices([m]))
    assert rest == [] and abs(pf.tokens[m]["price"] - 3.6e-8) < 1e-15
    assert not pf._paid()                                   # ter chave da PumpPortal não liga stream pago


def test_pump_min_trades_filter_is_configurable(tmp_path):
    pf = _pump(tmp_path, paid=False, pump_lb_min_trades=1000)
    pf.leaderboard = pf._parse_lb({"traders": [
        {"wallet": "A".ljust(44, "1"), "winRate": 0.7, "counts": {"trades": 1500}},
        {"wallet": "B".ljust(44, "1"), "winRate": 0.8, "counts": {"trades": 400}}]})
    pf.refresh_followed(force=True)
    assert pf.followed == ["A".ljust(44, "1")] and "precisa ≥ 1000" in " ".join(pf.leaderboard[1]["flags"])
    pf.cfg.pump_lb_min_trades = 300
    pf.refresh_followed()
    assert len(pf.followed) == 2


def test_pump_position_shows_token_volume(tmp_path):
    import httpx as _h
    pf = _pump(tmp_path, paid=False)
    pf.add_manual(_W)
    m = "Vol".ljust(40, "1") + "pump"
    pf.on_message(_ev("buy", _W, m, 1.0, 1e6, 30, 3e7))

    def h(req):
        return _h.Response(200, json=[
            {"baseToken": {"address": m, "symbol": "VOL"}, "quoteToken": {"address": "So11111111111111111111111111111111111111112"},
             "dexId": "pumpfun", "priceNative": "0.000002", "liquidity": {"usd": 0},
             "volume": {"m5": 1200, "h1": 15000, "h6": 40000, "h24": 90000}, "txns": {"h1": {"buys": 120, "sells": 80}}}])
    pf.http = _h.AsyncClient(transport=_h.MockTransport(h))
    pf.tokens[m]["price"], pf.tokens[m]["last_t"] = 1e-6, __import__("time").time()
    asyncio.run(pf._fetch_prices([m], set_price=False))
    assert pf.tokens[m]["price"] == 1e-6                          # preço da curva não é trocado
    p = pf.snapshot()["positions"][0]
    assert p["vol"]["h1"] == 15000 and p["vol"]["buys_h1"] == 120


def test_pump_trailing_stop_locks_profit(tmp_path):
    pf = _pump(tmp_path, paid=False, pump_extra_slip_pct=0.0, pump_trail_start_pct=20.0, pump_trail_dist_pct=10.0)
    pf.add_manual(_W)
    m = "Trail".ljust(40, "1") + "pump"
    pf.on_message(_ev("buy", _W, m, 1.0, 1e6, 30, 3e7))              # 1e-6
    for px in (1.15e-6, 1.30e-6, 1.60e-6):                           # sobe: liga o stop móvel e acompanha o pico
        pf.tokens[m]["price"] = px
        pf._check_stops(m, 0)
    p = pf.positions()[0]
    assert p["trail_peak"] > 40 and p["trail_exit"] == round(p["trail_peak"] - 10, 2)
    pf.tokens[m]["price"] = 1.50e-6                                  # caiu pouco: segura
    pf._check_stops(m, 0)
    assert pf.positions()
    pf.tokens[m]["price"] = 1.42e-6                                  # caiu mais de 10 pontos do pico: sai no lucro
    pf._check_stops(m, 0)
    t = pf.trades()[0]
    assert not pf.positions() and "stop móvel" in t["reason"] and t["pnl_sol"] > 0


def test_pump_token_and_trader_filters(tmp_path):
    """Não entra em token sem volume/mcap baixo/concentrado; só copia trader com saldo mínimo."""
    pf = _pump(tmp_path, paid=False, pump_min_mcap_usd=10000, pump_min_vol_h1_usd=5000, pump_min_txns_h1=30,
               pump_max_top10_pct=35, pump_min_wallet_usd=5000)
    pf.sol_usd = 150.0
    m = "Dev".ljust(40, "1") + "pump"
    pf.tokens[m] = {"mcap_sol": 28.0, "vol": {"h1": 0, "buys_h1": 0, "sells_h1": 0}}
    assert "market cap" in pf.token_block(m)                     # 28 SOL ≈ $4.200 — token recém-criado
    pf.tokens[m]["mcap_sol"] = 300.0
    assert "volume 1 h" in pf.token_block(m)
    pf.tokens[m]["vol"] = {"h1": 20000, "buys_h1": 10, "sells_h1": 5}
    assert "negociações" in pf.token_block(m)
    pf.tokens[m]["vol"] = {"h1": 20000, "buys_h1": 100, "sells_h1": 60}
    pf.tokens[m]["top10_pct"] = 62.0
    assert "10 maiores" in pf.token_block(m)
    pf.tokens[m]["top10_pct"] = 20.0
    assert pf.token_block(m) is None
    pf.tokens["New".ljust(40, "1") + "pump"] = {"mcap_sol": 300.0}
    assert "sem volume" in pf.token_block("New".ljust(40, "1") + "pump")
    # trader: saldo
    pf.leaderboard = pf._parse_lb({"traders": [{"wallet": "Rich".ljust(44, "1"), "winRate": 0.7},
                                               {"wallet": "Poor".ljust(44, "1"), "winRate": 0.7}]})
    pf.wallet_usd = {"Rich".ljust(44, "1"): {"usd": 12000, "t": 9e18}, "Poor".ljust(44, "1"): {"usd": 300, "t": 9e18}}
    pf.refresh_followed(force=True)
    assert pf.followed == ["Rich".ljust(44, "1")]


def test_pump_trailing_positions_get_fast_price_checks(tmp_path):
    """Só as posições com stop móvel ligado entram no laço rápido; o stop é checado logo após o preço novo."""
    pf = _pump(tmp_path, paid=False, pump_extra_slip_pct=0.0, pump_trail_start_pct=20.0, pump_trail_dist_pct=10.0)
    pf.add_manual(_W)
    a, b = "Fast".ljust(40, "1") + "pump", "Slow".ljust(40, "1") + "pump"
    pf.on_message(_ev("buy", _W, a, 1.0, 1e6, 30, 3e7))
    pf.on_message(_ev("buy", _W, b, 1.0, 1e6, 30, 3e7))
    pf.tokens[a]["price"] = 1.5e-6
    pf._check_stops(a, 0)                                         # liga o stop móvel só em A
    seen = []

    async def curve(ms, public_first=False):
        seen.append((list(ms), public_first))
        pf.tokens[a]["price"] = 1.2e-6                            # despencou entre as leituras
        return []
    pf._curve_prices = curve
    pf.cfg.pump_trail_fast_s = 0.3

    async def run_once():
        t = asyncio.create_task(pf.trail_fast_loop())
        await asyncio.sleep(0.2)
        t.cancel()
    asyncio.run(run_once())
    assert seen and seen[0] == ([a], True)
    assert [p["mint"] for p in pf.positions()] == [b] and "stop móvel" in pf.trades()[0]["reason"]


def test_pump_pause_trader_manual_and_auto_after_two_stops(tmp_path):
    pf = _pump(tmp_path, paid=False, pump_extra_slip_pct=0.0, pump_stop_pct=40.0, pump_hold_until_profit=False,
               pump_trail_enabled=False)
    pf.leaderboard = [{"wallet": f"T{i}".ljust(44, "1"), "eligible": True, "rank": i + 1, "winrate": 70.0}
                      for i in range(12)]
    pf.refresh_followed(force=True)
    w = pf.followed[0]
    # pausa manual: sai dos copiados, entra o próximo; compras dele não são copiadas
    pf.pause(w)
    assert w not in pf.followed and len(pf.followed) == 10 and pf.is_paused(w)
    assert pf.on_message(_ev("buy", w, "Px".ljust(40, "1") + "pump", 1.0, 1e6, 30, 3e7)) == []
    pf.resume(w)
    assert w in pf.followed and not pf.is_paused(w)
    # automática: 2 stops de perda em 24 h → pausa 24 h
    for k in range(2):
        m = f"Stop{k}".ljust(40, "1") + "pump"
        pf.on_message(_ev("buy", w, m, 1.0, 1e6, 30, 3e7))
        pf.tokens[m]["price"] = 0.5e-6
        pf._check_stops(m, 0)
    p = pf.paused().get(w)
    assert p and p["until"] and "2 stops" in p["reason"] and w not in pf.followed
    assert pf.snapshot()["paused"][0]["wallet"] == w


# ---------------------------------------------------------------- Jupiter: troca USDC → SOL
def _jup_setup(wallet_usdc=500.0):
    """Carteira do bot com RPC da Solana falso e Jupiter (/quote e /swap) falsa."""
    import base64 as b64
    from solders.hash import Hash
    from solders.keypair import Keypair
    from solders.message import MessageV0
    from solders.transaction import VersionedTransaction
    from app.jupiter import USDC, SOL, JupiterQuoter, JupiterWallet
    from app.solana_wallet import UserWallet
    kp = Keypair()
    st = {"sol": 1.0, "tok": {USDC: wallet_usdc}, "sent": []}

    def handler(req: httpx.Request):
        u = req.url
        if u.path.endswith("/swap/v1/quote"):
            q = dict(u.params)
            amt = int(q["amount"])
            out = int(amt / 1e6 / 150.0 * 1e9 * 0.997) if q["inputMint"] == USDC else int(amt / 1e9 * 150 * 1e6)
            return httpx.Response(200, json={"inputMint": q["inputMint"], "outputMint": q["outputMint"],
                                             "inAmount": q["amount"], "outAmount": str(out), "slippageBps": 50,
                                             "priceImpactPct": "0.0001"})
        if u.path.endswith("/swap/v1/swap"):
            q = st["last_quote"] = json.loads(req.content)["quoteResponse"]
            # rota Jupiter "route" v1: dados terminam com in_amount, quoted_out, slippage_bps, platform_fee_bps
            from solders.instruction import Instruction
            from solders.pubkey import Pubkey
            from app import txguard
            data = (txguard.anchor("route") + (0).to_bytes(4, "little") + int(q["inAmount"]).to_bytes(8, "little")
                    + int(q["outAmount"]).to_bytes(8, "little") + int(q["slippageBps"]).to_bytes(2, "little") + b"\x00")
            msg = MessageV0.try_compile(kp.pubkey(), [Instruction(Pubkey.from_string(txguard.JUPITER), data, [])],
                                        [], Hash.default())
            return httpx.Response(200, json={"swapTransaction": b64.b64encode(bytes(VersionedTransaction(msg, [kp]))).decode()})
        js = json.loads(req.content)
        m, p = js["method"], js["params"]
        if m == "getBalance":
            return httpx.Response(200, json={"result": {"value": int(st["sol"] * 1e9)}})
        if m == "getTokenAccountsByOwner":
            vals = [{"account": {"data": {"parsed": {"info": {"mint": k, "tokenAmount": {
                "uiAmount": v, "amount": str(int(round(v * 1e6)))}}}}}} for k, v in st["tok"].items()] \
                if p[1]["programId"].startswith("Tokenkeg") else []
            return httpx.Response(200, json={"result": {"value": vals}})
        if m == "sendTransaction":
            q = st["last_quote"]
            if q not in st["sent"]:
                st["tok"][USDC] -= int(q["inAmount"]) / 1e6
                st["sol"] += int(q["outAmount"]) / 1e9 - 0.00001
                st["sent"].append(q)
            return httpx.Response(200, json={"result": "SIG123"})
        if m == "getSignatureStatuses":
            return httpx.Response(200, json={"result": {"value": [{"confirmationStatus": "confirmed", "err": None}]}})
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    w = UserWallet(private_key=str(kp), rpc_url="https://rpc.exemplo.test")

    async def public_dns(host):                    # sem internet nos testes: o RPC "resolve" para IP público
        return ["93.184.216.34"]
    w.resolver = public_dns
    jw = JupiterWallet(client, w, JupiterQuoter(client, per_min=100000))
    return jw, st


def test_wallet_usdc_to_sol_swap(tmp_path):
    jw, st = _jup_setup()
    q = asyncio.run(jw.usdc_to_sol(10.0, preview=True))
    assert q.get("sol_out", 0) > 0 and q.get("venue"), q
    n = len(st["sent"])
    r = asyncio.run(jw.usdc_to_sol(10.0))
    assert r["ok"] and len(st["sent"]) == n + 1 and st["sent"][-1]["inputMint"].startswith("EPj")
    assert r["sol_received"] > 0.06
    assert "saldo insuficiente" in asyncio.run(jw.usdc_to_sol(1e9))["error"]


def test_pump_does_not_chase_price_after_trader_entry(tmp_path):
    """0.9.4: quem copia entra depois; se o preço já fugiu mais que pump_max_chase_pct da entrada do trader, não
    copia — nem na cópia com espera, nem na compra real (conferida de novo na hora de enviar)."""
    import time as _t
    pf = _pump(tmp_path, paid=False, pump_copy_delay_s=30.0, pump_max_chase_pct=30.0)
    pf.add_manual(_W)

    async def no_fetch(m):
        return None
    pf._fetch_prices = no_fetch
    m = "Chase".ljust(40, "1") + "pump"
    now = _t.time()
    pf.on_message(_ev("buy", _W, m, 1.0, 1e6, 30, 3e7), now)                # trader entra a 1e-6
    pf.tokens[m]["price"] = 1.5e-6                                          # +50% durante a espera
    for k in pf._pending:
        pf._pending[k]["due"] = now - 1
    asyncio.run(pf._process_pending())
    assert not pf.positions() and "subiu 50%" in pf.feed[0]["reason"]
    assert pf.chase_block(1e-6, 1.29e-6) is None and pf.chase_block(1e-6, 1.31e-6)
    pf.cfg.pump_max_chase_pct = 0
    assert pf.chase_block(1e-6, 9e-6) is None                               # 0 desliga
    pf.cfg.pump_max_chase_pct, pf.cfg.pump_chase_on = 30.0, False
    assert pf.chase_block(1e-6, 9e-6) is None                               # OFF desliga
    pf.cfg.pump_chase_on = True

    pf.cfg.pump_max_chase_pct, pf.cfg.pump_real_enabled = 30.0, True
    bought = []

    class FakeReal:
        def today_loss(self, trades):
            return 0.0

        async def buy(self, *a, **k):
            bought.append(a)
            return {"ok": False}
    pf.real = FakeReal()
    pf.tokens[m]["price"] = 2e-6
    asyncio.run(pf._real_buy({"wallet": _W, "mint": m, "symbol": "CH", "trader_price": 1e-6}))
    assert bought == [] and "subiu 100%" in pf.feed[0]["reason"] and pf.feed[0]["action"] == "REAL não copiou"


def test_pump_partial_take_profit_and_exit_before_graduation(tmp_path):
    """0.12.0: venda em partes realiza uma fração uma vez; saída antes da graduação vende tudo com a curva alta."""
    pf = _pump(tmp_path, paid=False, pump_tp1_on=True, pump_tp1_pct=20.0, pump_tp1_frac_pct=50.0, pump_extra_slip_pct=0.0)
    pf.add_manual(_W)
    m = "Part".ljust(40, "1") + "pump"
    pf.on_message(_ev("buy", _W, m, 1.0, 1e6, 30, 3e7))
    p = pf.positions()[0]
    full = p["tokens"]
    pf.tokens[m]["price"] = 3e-6
    pf._check_stops(m, 0)
    p = pf.positions()[0]
    assert p["tp1_done"] and abs(p["tokens_left"] - full * 0.5) < full * 1e-6
    assert "venda em partes" in pf.feed[0]["reason"] or any("venda em partes" in str(s.get("why")) for s in p.get("sells", []))
    pf._check_stops(m, 0)                                                     # não repete a venda parcial
    assert abs(pf.positions()[0]["tokens_left"] - full * 0.5) < full * 1e-6
    pf.cfg.pump_curve_exit_on, pf.cfg.pump_curve_exit_pct = True, 50.0
    pf.tokens[m]["mcap_sol"] = 300.0                                          # curva ~76%
    pf._check_stops(m, 0)
    assert not pf.positions() and "antes da graduação" in pf.trades()[0]["reason"]
    assert abs(pf.curve_progress(28.0)) < 0.5 and pf.curve_progress(410.0) > 99 and pf.curve_progress(None) is None


def test_pump_curve_filters_trust_size_and_lag(tmp_path):
    import time as _t
    pf = _pump(tmp_path, paid=False)
    m = "Grad".ljust(40, "1") + "pump"
    pf.tokens[m] = {"created_t": _t.time() - 600, "creator": "Dev", "mcap_sol": 60.0, "pool": "pumpswap"}
    assert pf.curve_block(m) is None                                          # tudo desligado por padrão
    pf.cfg.pump_skip_graduated = True
    assert "graduou" in pf.curve_block(m)
    pf.cfg.pump_skip_graduated, pf.tokens[m]["pool"] = False, "pump"
    pf.cfg.pump_curve_speed_on, pf.cfg.pump_min_curve_speed = True, 5.0     # ~16% em 10 min = 1,6%/min
    assert "devagar" in pf.curve_block(m)
    pf.tokens[m]["created_t"] = _t.time() - 60
    assert pf.curve_block(m) is None                                          # ~16% em 1 min: rápido
    pf.cfg.pump_size_by_trader = True
    for _ in range(5):
        pf._save_trade({"wallet": _W, "pnl_sol": 0.02, "real": False, "closed_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat()})
    assert pf.trust_mult(_W)[0] == 1.5 and pf.trust_mult("Outro".ljust(44, "1"))[0] == 1.0
    pf.cfg.pump_min_curve_speed, pf.cfg.pump_size_by_trader = 0.0, False
    pf.add_manual(_W)
    n = "Lag".ljust(41, "1") + "pump"
    now = float(int(_t.time()))                                               # blockTime é inteiro: atraso exato
    pf.on_message(_ev("buy", _W, n, 1.0, 1e6, 30, 3e7, blockTime=int(now) - 4), now)
    assert "atraso 4 s" in pf.feed[0]["reason"] and pf.positions()[-1]["lag_s"] >= 3.5


def test_pump_buy_pressure_filter_flow_parse_and_token_card(tmp_path):
    """0.13.0: pressão de compra (volume da Solana Tracker ou compras × vendas da DexScreener) e ficha do token."""
    pf = _pump(tmp_path, paid=False)
    m = "Flow".ljust(40, "1") + "pump"
    pf.tokens[m] = {"created_t": 0, "creator": "Dev".ljust(44, "1"), "mcap_sol": 100.0, "symbol": "FLW",
                    "vol": {"buys_m5": 3, "sells_m5": 2, "buys_h1": 40, "sells_h1": 60},
                    "holders_top": [{"owner": "Dev".ljust(44, "1"), "pct": 12.5}, {"owner": _W, "pct": 4.0}]}
    assert pf.flow_block(m) is None                                         # desligado por padrão
    pf.cfg.pump_buy_pressure_on, pf.cfg.pump_min_buy_pressure_pct = True, 55.0
    pr, src = pf.pressure(m)
    assert pr == 40.0 and "1 h" in src                                       # 5 min com < 10 negociações: usa 1 h
    assert "40%" in pf.flow_block(m)
    pf.tokens[m]["flow"] = pf.parse_flow({"5m": {"buyers": 30, "sellers": 10, "volume": {"buys": 900, "sells": 100}}})
    assert pf.pressure(m)[0] == 90.0 and pf.flow_block(m) is None           # volume de compra 90%
    assert pf.parse_flow("x") is None and pf.parse_flow({"outro": 1}) is None
    pf.add_manual(_W)
    card = pf.token_card(m)
    assert card["symbol"] == "FLW" and card["pressure"] == 90.0 and card["curve_pct"] > 0
    assert card["holders"][0]["creator"] and card["holders"][1]["followed"]
    assert pf.token_card("Nada".ljust(40, "1"))["seen"] is False
