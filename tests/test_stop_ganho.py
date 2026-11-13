"""0.32.332 (pedido do dono, 13/11/2026: "estratégia autônoma de stop de ganho, ganhou 10% saiu fora, com tudo que já temos de
histórico"): cérebro que escolhe o alvo por aba, sombra que mede o "e se" depois da venda, e a regra nas três redes (Solana,
Robinhood e BNB). Este arquivo usa os padrões de verdade (ver conftest)."""
import time

from app import bnbcopy, hoodcopy, settings, stopganho
from app.stopganho import Sombras, decidir, linha

DIA = 86400.0
T0 = time.time() - 3 * DIA


def _rows(specs):
    """specs = [(pct, best, dia)]"""
    return [linha(p, b, T0 + d * DIA - 3600 + i) for i, (p, b, d) in enumerate(specs)]


def test_defaults_fictitious_on_real_and_explorar_off():
    d = settings.server_defaults()
    assert d["pump_sg_on"] is True and d["pump_sg_fixo_pct"] == 0
    assert d["pump_sg_real"] is False and d["pump_sg_explorar"] is False         # REAL nova começa OFF; Explorar não muda sozinho
    assert hoodcopy.CFG_DEFAULT["sg_on"] is True and bnbcopy.CFG_DEFAULT["sg_on"] is True
    from app import bnbreal, hoodreal
    assert hoodreal.REAL_DEFAULT["real_sg_on"] is False and bnbreal.REAL_DEFAULT["real_sg_on"] is False
    assert settings.PumpSettings({}).pump_real_enabled is False
    assert d["pump_runup_max_pct"] == 100                                       # 0.32.332: entrada no topo barrada por padrão


def test_without_base_starts_at_the_owner_10_pct():
    d = decidir(_rows([(-30, 15, 0)] * 5))
    assert d["acao"] == "inicio" and d["nivel"] == 10.0 and "+10%" in d["motivo"]
    assert stopganho.nivel_de(None) == (10.0, "inicio")
    assert stopganho.nivel_de(d, fixo=20) == (20.0, "fixo")


def test_picks_the_level_that_pays_when_trades_give_back_the_gain():
    # 40 operações em 5 dias que passaram por +15% e acabaram no stop de -30%, e 4 que correram até +100%
    rs = _rows([(-30, 15, i % 5) for i in range(40)] + [(100, 120, i) for i in range(4)])
    d = decidir(rs)
    assert d["acao"] == "aplicar" and d["nivel"] == 15.0
    assert d["ganho"] > 30 and d["media_sem"] < 0 < d["tabela"][4]["media"]
    l15 = next(x for x in d["tabela"] if x["nivel"] == 15)
    assert l15["chegou"] == 44 and l15["chance"] is not None


def test_keeps_the_rules_when_no_target_beats_them():
    rs = _rows([(80, 80, i % 5) for i in range(30)])       # os ganhos vêm de quem correu: alvo só cortaria
    d = decidir(rs)
    assert d["acao"] == "manter" and d["nivel"] is None
    assert stopganho.nivel_de(d) == (None, "manter")


def test_hysteresis_keeps_current_level_when_the_new_one_is_almost_equal():
    rs = _rows([(-30, 12.4, i % 5) for i in range(30)])
    assert decidir(rs)["nivel"] == 12.0
    assert decidir(rs, atual=10.0)["nivel"] == 12.0          # 12 rende 2 pontos a mais: troca
    rs2 = _rows([(-30, 10.2, i % 5) for i in range(20)] + [(-30, 12.2, i % 5) for i in range(10)])
    assert decidir(rs2, atual=10.0)["nivel"] == 10.0         # quase igual: fica no atual


def test_capped_trades_use_the_shadow_result():
    sg = {"saiu": True, "nivel": 10, "sem": -30.0, "best_sem": 18.0}
    r = linha(10.5, 11.0, T0, sg)
    assert r["sem"] == -30 and r["bu"] == 18
    assert stopganho.com_alvo(r, 15) == 14 and stopganho.com_alvo(r, 20) == -30
    assert linha(10.5, 11, T0, {"saiu": True, "nivel": 10}) is None           # sombra ainda aberta: fora da conta
    assert linha(2500, 2600, T0) is None                                      # preço lido errado
    rows = stopganho.dedup([("a", "Top", "M", 100.0, linha(5, 6, T0)), ("b", "Top", "M", 300.0, linha(5, 6, T0)),
                            ("a", "Top", "M", 400.0, linha(5, 6, T0))])
    assert len(rows) == 2                                                     # outra conta, mesmo token em 10 min: uma vez


def test_shadow_follows_stop_trader_and_time_and_survives_restart():
    saved = []
    S = Sombras(salvar=saved.append)
    base = {"token": "M", "wallet": "W", "t": 0.0, "ate": 1000.0, "tokens": 100.0, "mult": 1.0, "fixo": 0.0, "custo": 1.0,
            "inv": 1.0, "realizado": 0.0, "base": "resto", "stop": 30.0, "trail": None, "alvo": 0.0, "segue": True,
            "segura": None, "segurando": False, "pico": None, "best": 12.0, "px": 0.0112}
    t1 = {"id": "1", "best_pct": 12.0, "sg": {"saiu": True, "nivel": 10}}
    S.abrir(t1, base)
    assert S.mints() == {"M"}
    S.preco("M", 0.02, 1.0)                                   # subiu até +100% depois da venda
    S.preco("M", 0.0065, 2.0)                                 # caiu: stop de -30%
    assert t1["sg"]["sem"] == -35.0 and t1["sg"]["best_sem"] == 100.0 and t1["sg"]["sombra_fim"] == "stop de perda"
    assert "sombra" not in t1["sg"] and saved == [t1] and not S.abertas
    t2 = {"id": "2", "sg": {"saiu": True}}
    S.abrir(t2, dict(base, segura=0.0))
    S.trader("W", "M", 1.0, 0.009, 3.0)                       # trader saiu no prejuízo: segura até ficar positivo
    assert S.abertas and t2["sg"]["sombra"]["segurando"]
    S.preco("M", 0.0105, 4.0)
    assert t2["sg"]["sombra_fim"] == "segurou até ficar positivo" and t2["sg"]["sem"] == 5.0
    t3 = {"id": "3", "sg": {"saiu": True}}
    S.abrir(t3, base)
    S2 = Sombras()                                            # reiniciou: volta a seguir pelo estado guardado no trade
    assert S2.restaurar([t3, t1], 10.0) == 1 and S2.abertas == [t3]
    S2.tempo(1001.0, lambda m: 0.011)
    assert t3["sg"]["sem"] == 10.0 and t3["sg"]["sombra_fim"] == "tempo máximo"


def _pf(**kw):
    from app.pumpfun import PumpFun
    from app.settings import PumpSettings
    from app.store import MemStore
    cfg = PumpSettings()
    cfg.pump_rank_every_s = 0
    cfg.pump_lb_min_trades = 0
    cfg.pump_min_mcap_usd = cfg.pump_min_vol_h1_usd = cfg.pump_max_top10_pct = cfg.pump_min_wallet_usd = 0
    cfg.pump_min_txns_h1 = 0
    cfg.pump_only_online = False
    cfg.pump_extra_slip_pct = cfg.pump_fee_pct = cfg.pump_portal_fee_pct = cfg.pump_priority_sol = 0.0
    cfg.pump_paid_stream = True
    for k, v in kw.items():
        setattr(cfg, k, v)
    pf = PumpFun(cfg, MemStore())
    return pf


W = "TraderGood1111111111111111111111111111111"
MINT = "MintSG".ljust(40, "1") + "pump"


def _open(pf):
    pf.add_manual(W)
    ev = {"txType": "buy", "traderPublicKey": W, "mint": MINT, "solAmount": 1.0, "tokenAmount": 1e6,
          "vSolInBondingCurve": 40, "vTokensInBondingCurve": 40 / 1e-6, "marketCapSol": 1200}
    msgs = pf.on_message(ev)
    assert msgs and "copiou" in msgs[0], msgs
    return pf.positions()[0]


def _price(pf, px):
    pf.tokens[MINT]["price"] = px
    return pf._check_stops(MINT, time.time())


def test_solana_copy_sells_at_the_level_and_the_shadow_measures_what_would_happen():
    pf = _pf()
    p = _open(pf)
    pin = p["price_in"]
    assert not _price(pf, pin * 1.05) and pf.positions()[0]["sg_nivel"] == 10.0
    msgs = _price(pf, pin * 1.12)
    assert msgs and not pf.positions()
    tr = pf.trades()[0]
    assert tr["reason"].startswith("stop de ganho autônomo: +10%") and 11 < tr["pnl_pct"] < 13
    assert tr["sg"]["saiu"] and tr["sg"]["nivel"] == 10.0 and "sombra" in tr["sg"] and tr["sg_hits"]["10"][0] >= 0
    assert MINT in pf.sg_sombra.mints()
    _price(pf, pin * 0.6)                                    # sem o stop de ganho teria ido ao stop de perda de 30%
    assert tr["sg"]["sem"] < -25 and tr["sg"]["sombra_fim"] == "stop de perda"
    v = pf.sg_view()
    assert v["ligado"] and v["abas"][0]["aba"] == "Top traders" and v["abas"][0]["nivel"] == 10.0


def test_solana_switches_fixed_level_explorar_and_copiar_igual():
    pf = _pf(pump_sg_on=False)
    p = _open(pf)
    _price(pf, p["price_in"] * 1.12)
    assert pf.positions() and pf.positions()[0]["sg_fonte"] == "desligado"
    pf.cfg.pump_sg_on, pf.cfg.pump_sg_fixo_pct = True, 20.0
    _price(pf, p["price_in"] * 1.15)
    assert pf.positions()                                     # fixo em +20%: ainda não
    q = pf.positions()[0]
    q["origem"], q["auto"] = "explorar", True
    q["trail_on"] = False
    pf._save_pos(q)
    _price(pf, p["price_in"] * 1.30)
    assert pf.positions() and pf.positions()[0]["sg_fonte"] == "Explorar sem stop de ganho"
    pf.cfg.pump_sg_explorar = True
    _price(pf, p["price_in"] * 1.25)
    assert not pf.positions() and pf.trades()[0]["reason"].startswith("stop de ganho autônomo: +20%")
    pf2 = _pf()
    r = _open(pf2)
    r["eq"] = True                                            # Copiar igual sai só quando a carteira vende
    pf2._save_pos(r)
    _price(pf2, r["price_in"] * 1.5)
    assert pf2.positions()


def test_robinhood_book_sells_at_the_level_but_not_the_button_buy():
    key = [hoodcopy.ZERO, "0x" + "ab" * 20, 10000, 200, hoodcopy.ZERO]
    b = hoodcopy.Book("u", {"slip_pct": 0, "gas_eth": 0})
    t = time.time()
    tr = {"id": "x", "tx": "0x" + "ee" * 32, "token": key[1], "wallet": "0x" + "11" * 20, "side": "buy", "amount": 1000.0,
          "eth": 1.0, "t": t, "fee": 10000}
    p = b.buy(tr, 0.001, t, key)
    out = b.on_price(key[1], 0.00113, t)                      # +13% no preço, ~+10,9% depois da taxa do pool
    assert out and out[0]["motivo"].startswith("stop de ganho autônomo: +10%") and out[0]["sg"]["saiu"]
    assert p["id"] not in b.pos
    q = b.buy(dict(tr, wallet="0x" + "22" * 20), 0.001, t, key, origem="botao")
    assert not b.on_price(key[1], 0.0013, t) and q["id"] in b.pos and q["sg_fonte"] == "fora"


def test_bnb_book_now_has_a_take_profit():
    b = bnbcopy.Book("u", {"slip_pct": 0, "gas_bnb": 0})
    t = time.time()
    p = b.buy({"wallet": "w", "token": "tk", "t": t, "bnb": 1.0}, 1e-6, t)
    assert not b.on_price("tk", 1.05e-6, t) and p["sg_nivel"] == 10.0
    out = b.on_price("tk", 1.14e-6, t)
    assert out and out[0]["motivo"].startswith("stop de ganho autônomo") and out[0]["sg"]["saiu"]
    b2 = bnbcopy.Book("u", {"slip_pct": 0, "gas_bnb": 0, "sg_on": False})
    b2.buy({"wallet": "w", "token": "tk", "t": t, "bnb": 1.0}, 1e-6, t)
    assert not b2.on_price("tk", 1.5e-6, t)


def test_entry_bands_only_measure():
    rs = [dict(r, x={"atraso": 40}) for r in _rows([(-30, 3, i % 5) for i in range(20)])]
    rs += [dict(r, x={"atraso": 1}) for r in _rows([(-30, 15, i % 5) for i in range(20)])]
    f = stopganho.faixas(rs, 10.0, {"atraso": stopganho.FAIXAS["atraso"]})
    assert f[0]["faixa"] == "mais de 30 s" and f[0]["ruim"] and not f[-1]["ruim"] and f[-1]["media"] == 9.0


def test_entry_block_uses_bad_bands_and_lets_one_in_five_through():
    """0.32.335: a faixa ruim barra a entrada na fictícia; uma em cada cinco passa para continuar medindo."""
    rs = [dict(r, x={"atraso": 40}) for r in _rows([(-30, 3, i % 5) for i in range(20)])]
    rs += [dict(r, x={"atraso": 1}) for r in _rows([(-30, 15, i % 5) for i in range(30)])]
    rows = [dict(r, grupo="Top traders") for r in rs]
    d = stopganho.decidir_grupos(rows)["Top traders"]
    assert [f["faixa"] for f in d["ruins"]] == ["mais de 30 s"]
    assert stopganho.na_faixa(d["ruins"], {"atraso": 45})["faixa"] == "mais de 30 s"
    assert stopganho.na_faixa(d["ruins"], {"atraso": 2}) is None
    pf = _pf()
    pf.sg_pool = lambda: {"Top traders": d}
    ev = {"blockTime": 1000.0}
    outs = [pf.sg_entry_block(W, {}, ev, 1045.0, 50) for _ in range(5)]
    assert sum(1 for o in outs if o) == 4 and "entrada ruim" in outs[0]
    assert pf.sg_entry_block(W, {}, ev, 1001.0, 50) is None
    pf.cfg.pump_sg_entrada_on = False
    assert pf.sg_entry_block(W, {}, ev, 1045.0, 50) is None


def test_fictitious_slippage_is_lower_but_real_estimate_keeps_3_pct():
    d = settings.server_defaults()
    assert d["pump_extra_slip_pct"] == 1.5 and d["pump_sg_entrada_on"] is True
    pf = _pf(pump_extra_slip_pct=1.5)
    assert pf._fee_rates(MINT)["slip"] == 0.015 and pf._fee_rates(MINT, real=True)["slip"] == 0.03
