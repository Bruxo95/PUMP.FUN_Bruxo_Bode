"""0.32.41: Aba do Bruxo (top trader em moeda nova, só fictícia), aba de origem de cada trade, relatório de cada aba a
cada 30 min e o preço de token graduado que ficava parado. Tudo com carteira falsa: nenhuma transação de verdade."""
import asyncio
import time

import httpx

from app.bruxo import Bruxo
from app import tabreport
from app.daily import _origin
from tests.test_espelho_real import _pf
from tests.test_pump import _pump

M = "Brux".ljust(40, "1") + "pump"
W = "Top1".ljust(44, "1")
SOL = "So11111111111111111111111111111111111111112"


def _facts(**kw):
    f = {"age_min": 2.0, "flow": 8.0, "flow_base": 3.0, "mcap": 45.0, "dev_pct": 2.0, "top10": 20.0,
         "trader_sol": 1.0, "creator": "Dev1".ljust(44, "1"), "graduated": False}
    f.update(kw)
    return f


def _sig(t):
    b = Bruxo()
    s, new = b.on_buy(W, "Top1", M, "BRX", 1.0, 1e-6, {"mcap_sol": 45.0}, 2.0, {}, t)
    assert new
    return b, s


def test_entry_only_sim_with_bruxo_rules(tmp_path):
    pf = _pf(tmp_path)                                     # execução real ligada (carteira falsa)
    pf.role = "admin"
    t = time.time()
    pf.tokens[M] = {"price": 1e-6, "symbol": "BRX", "mcap_sol": 45.0}
    _, s = _sig(t)
    assert pf.bruxo_entry(s, _facts(), t) == "Aba do Bruxo desligada"
    pf.cfg.pump_bx_on = True
    assert pf.bruxo_entry(s, _facts(), t) is None
    p = [p for p in pf.positions() if p["mint"] == M][0]
    assert p["origem"] == "bruxo" and p["real"] is False
    assert p["tp1_pct"] == 100 and p["tp1_frac"] == 50 and p["trail_start"] == 100 and p["stop_pct"] == 30
    assert p["max_hold_s"] == 25 * 60 and p["bruxo"]["wallets"] == [W]
    assert pf._rq is None or pf._rq.qsize() == 0           # REAL desligada por padrão: nada na fila real
    assert pf.aba_of(p) == "Aba do Bruxo"
    assert pf.bruxo_entry(s, _facts(), t) == "já tem posição fictícia neste token"
    # o top trader vendeu: a posição da aba sai junto
    assert pf.bruxo_sell(W, M, "Top1", t + 60)
    assert not [p for p in pf.positions() if p["mint"] == M]


def test_entry_filters_from_the_prompt(tmp_path):
    pf = _pf(tmp_path)
    pf.role = "admin"
    pf.cfg.pump_bx_on = True
    t = time.time()
    _, s = _sig(t)
    assert "min (máximo 5)" in pf.bruxo_entry(s, _facts(age_min=7), t)
    assert "idade do token desconhecida" in pf.bruxo_entry(s, _facts(age_min=None), t)
    assert "abaixo da média inicial" in pf.bruxo_entry(s, _facts(flow=1.0), t)
    assert "10 maiores detentores" in pf.bruxo_entry(s, _facts(top10=60), t)
    assert "criador com" in pf.bruxo_entry(s, _facts(dev_pct=25), t)
    assert "pouca liquidez" in pf.bruxo_entry(s, _facts(mcap=29), t)
    assert "compra do trader pequena" in pf.bruxo_entry(s, _facts(trader_sol=0.01), t)
    assert pf.bruxo_entry(s, _facts(graduated=True), t) == "token já graduou"
    pf.tokens[M] = {"price": 1e-6, "symbol": "BRX", "mcap_sol": 45.0}
    assert pf.bruxo_entry(s, _facts(top10=None), t) is None             # 0.32.58: sem leitura dos detentores não trava


def test_signal_study_measures_peak_and_doubling():
    t = 1_793_000_000.0
    b = Bruxo()
    px = {"v": 1.0}
    for i in range(16):
        m = f"T{i:02d}".ljust(40, "x") + "pump"
        b.on_buy(W, "Top1", m, "T", 1.0, 1.0, {"mcap_sol": 40.0}, 1.5, {}, t + i)
    px["v"] = 2.2
    b.tick(lambda m: px["v"] if m[:3] in ("T00", "T01", "T02") else 0.6, t + 300)
    b.tick(lambda m: 1.0, t + 31 * 60 + 200)
    st = Bruxo.study(list(b.signals.values()))
    assert st["n"] == 16 and st["dobrou"] == 3 and st["stop_antes"] == 13 and st["dobrou_pct"] == 19
    assert st["tempo_ate_pico_mediano_s"] is not None and "dicas" in st


def test_tab_report_verdicts_causes_and_learning():
    now = time.time()
    iso = lambda s: __import__("datetime").datetime.fromtimestamp(now - s, __import__("datetime").timezone.utc).isoformat()
    tr = [{"origem": "barrado", "pnl_sol": -0.02, "pnl_pct": -40, "best_pct": 1, "reason": "stop de perda (−30%)", "closed_at": iso(600), "symbol": "A", "mint": "a"},
          {"origem": "barrado", "pnl_sol": -0.05, "pnl_pct": -95, "best_pct": -2, "reason": "stop de perda (−30%)", "closed_at": iso(900), "symbol": "B", "mint": "b"},
          {"origem": "barrado", "pnl_sol": -0.01, "pnl_pct": -10, "best_pct": 35, "reason": "stop móvel", "closed_at": iso(5000), "symbol": "C", "mint": "c"},
          {"origem": "barrado", "pnl_sol": 0.03, "pnl_pct": 60, "best_pct": 80, "reason": "stop móvel", "closed_at": iso(7000), "symbol": "D", "mint": "d"}]
    aba = lambda x: "Explorar · barrados" if x.get("origem") == "barrado" else "Top traders"
    rep = tabreport.build(tr, [], aba, now)
    a = rep["abas"][0]
    assert a["aba"] == "Explorar · barrados" and a["veredito"] == "perdendo" and a["h30"]["n"] == 2 and a["h24"]["n"] == 4
    assert {c["causa"] for c in a["causas"]} == {"entrou_no_topo", "stop_escorregou", "devolveu_ganho"}
    assert rep["maiores_perdas"][0]["symbol"] == "B" and rep["maiores_ganhos"][0]["symbol"] == "D"
    L = tabreport.learn([rep, rep, rep])
    assert L["abas"][0]["repetem"] and L["causas"][0]["causa"] == "stop_escorregou"


def test_origin_labels_and_aba(tmp_path):
    pf = _pf(tmp_path)
    assert pf.aba_of({"origem": "barrado"}) == "Explorar · barrados"
    assert pf.aba_of({"wallet": "manual", "manual": True}) == "Botão Comprar"
    assert pf.aba_of({"wallet": W}) == "Top traders"
    assert pf.aba_of({"wallet": W, "eq": True}) == "Copiar igual"
    assert _origin({"origem": "barrado", "manual": True}).startswith("Explorar · barrado")
    assert _origin({"origem": "bruxo", "manual": True}) == "Aba do Bruxo (automática)"


def test_graduated_price_ignores_dead_curve_pair_even_without_pool_flag(tmp_path):
    pf = _pump(tmp_path, paid=False)
    G = "Grad".ljust(40, "2") + "pump"
    pairs = [{"baseToken": {"address": G}, "quoteToken": {"address": SOL}, "dexId": "pumpfun", "priceNative": "0.00000041088",
              "liquidity": {"usd": 90000}, "pairAddress": "CURVA"},
             {"baseToken": {"address": G}, "quoteToken": {"address": SOL}, "dexId": "pumpswap", "priceNative": "0.0000009",
              "liquidity": {"usd": 30000}, "pairAddress": "POOL"}]
    pf.http = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=pairs)))
    pf.tokens[G] = {"created_t": 1}                        # o motor ainda não marcou como graduado
    asyncio.run(pf._fetch_prices([G]))
    assert abs(pf.tokens[G]["price"] - 0.0000009) < 1e-12


def test_copy_dump_filter(tmp_path):
    """0.32.50: filtro contra despejo nas cópias (10 maiores, criador, carteiras novas); desligado não bloqueia."""
    pf = _pf(tmp_path)
    D = "Dump".ljust(40, "1") + "pump"
    cr = "Crea".ljust(44, "1")
    pf.tokens[D] = {"price": 1e-6, "top10_pct": 60.0, "top10_t": time.time(), "creator": cr}
    assert pf.dump_block(D) is None
    pf.cfg.pump_dump_on = True
    assert "10 maiores" in pf.dump_block(D)
    pf.tokens[D]["top10_pct"] = 20.0
    pf.market.wallets[cr] = {"pos": {D: {"tok": 2e8}}}
    assert "criador com 20.0%" in pf.dump_block(D)
    pf.market.wallets[cr]["pos"][D]["tok"] = 1e7
    pf.tokens[D]["fresh"] = {"pct": 55.0}
    assert "carteiras novas" in pf.dump_block(D)
    pf.tokens[D]["fresh"] = {"pct": 10.0}
    assert pf.dump_block(D) is None


def test_entry_guard_for_button_barrados_and_bruxo(tmp_path):
    """0.32.53 (BabyNuts −92% com stop de −30%): token graduado só com preço da PumpSwap recente, liquidez e sem despejo."""
    pf = _pf(tmp_path)
    G = "Babn".ljust(40, "1") + "pump"
    now = time.time()
    pf.tokens[G] = {"price": 5.8e-7, "symbol": "BABY", "pool": "pumpswap", "main_dex": "pumpfun", "last_t": now, "liq_usd": 50000}
    assert pf.manual_buy(G, target="sim").get("sim", "").startswith("comprou")          # trava desligada: igual antes
    for p in list(pf.positions()):
        pf._sell(p, 1.0, p["price_now"], "teste", now)
    pf.cfg.pump_guard_on = True
    assert "sem preço confirmado" in pf.manual_buy(G, target="sim")["error"]
    pf.tokens[G].update(main_dex="pumpswap", last_t=now - 120)
    assert "preço do token graduado velho" in pf.manual_buy(G, target="sim")["error"]
    pf.tokens[G].update(last_t=now, liq_usd=4000)
    assert "liquidez baixa" in pf.manual_buy(G, target="sim", origem="barrado")["error"]
    pf.tokens[G].update(liq_usd=50000, top10_pct=70.0, top10_t=now)
    assert "despejo" in pf.manual_buy(G, target="sim", origem="bruxo")["error"]
    pf.tokens[G].update(top10_pct=20.0)
    assert pf.manual_buy(G, target="sim").get("sim", "").startswith("comprou")


def test_uncopiable_launcher_hft_and_flipper(tmp_path):
    """0.32.57 (análise das 26 carteiras): lançador de token, alta frequência e quem segura < 30 s não são copiados."""
    pf = _pf(tmp_path)
    now = time.time()
    L, H, F, OK = ("Lanc".ljust(44, "1"), "Hfts".ljust(44, "1"), "Flip".ljust(44, "1"), "Good".ljust(44, "1"))
    pf.market.creator_stats[L] = {"tokens": 25}
    pf.market.wallets[H] = {"trades": [now - i * 60 for i in range(200)], "closed": []}
    pf.market.wallets[F] = {"trades": [], "closed": [{"t": now - 100, "hold": 4, "pnl": 1} for _ in range(10)]}
    pf.market.wallets[OK] = {"trades": [now - 60] * 20, "closed": [{"t": now - 100, "hold": 600, "pnl": 1} for _ in range(10)]}
    assert "lançador" in pf.uncopiable(L, now)
    assert "alta frequência" in pf.uncopiable(H, now)
    assert "mediana" in pf.uncopiable(F, now)
    assert pf.uncopiable(OK, now) is None


def test_start_of_curve_rules(tmp_path):
    """0.32.59 (pedido do dono: "pegar do início e sair antes de graduar")."""
    pf = _pf(tmp_path)
    pf.role = "admin"
    t = time.time()
    G = "Grdx".ljust(40, "1") + "pump"
    pf.tokens[G] = {"pool": "pumpswap", "price": 1e-6}
    pf.cfg.pump_entry_curve_on = True
    assert "já graduou" in pf.curve_block(G)                        # token graduado não é copiado com a faixa ligada
    # Aba do Bruxo: só no começo da curva e regra de saída antes de graduar na própria posição
    pf.cfg.pump_bx_on, pf.cfg.pump_bx_curve_max, pf.cfg.pump_bx_grad_exit = True, 25, 85
    _, s = _sig(t)
    assert "só entra no começo" in pf.bruxo_entry(s, _facts(mcap=300), t)
    assert pf.bruxo_rules()["cx_pct"] == 85
    # saída antes da graduação só nas cópias: posição do botão Comprar não sai
    pf.cfg.pump_curve_exit_on, pf.cfg.pump_curve_exit_pct, pf.cfg.pump_cx_copies_only = True, 50, True
    B = "Btnx".ljust(40, "1") + "pump"
    pf.tokens[B] = {"price": 1e-6, "symbol": "BTN", "mcap_sol": 40.0}
    assert pf.manual_buy(B, target="sim")["sim"].startswith("comprou")
    pf.tokens[B]["mcap_sol"] = 350.0                                # curva bem cheia
    pf._check_stops(B, t + 5)
    assert [p for p in pf.positions() if p["mint"] == B]


def test_launch_signals_are_separate_from_trader_signals():
    b = Bruxo()
    t = 1_793_000_000.0
    s1, n1 = b.on_buy("lancamento", "lançamento", M, "X", 0.0, 1.0, {}, 1.0, {}, t, kind="lancamento")
    s2, n2 = b.on_buy(W, "Top1", M, "X", 1.0, 1.0, {}, 1.5, {}, t + 30)
    assert n1 and n2 and s1["id"] != s2["id"] and s1["kind"] == "lancamento" and s2["kind"] == "trader"
