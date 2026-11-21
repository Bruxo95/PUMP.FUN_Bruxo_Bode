"""0.32.423 (pedido do dono, 21/11): quanto tempo o token ficou no POSITIVO e no NEGATIVO, somando todas as trocas de estado,
e quantas trocas houve — por posição (de segundo em segundo, vai para o trade) e no histórico do BOOST (pela série). Sem internet."""
from app.boostmig import sign_time
from app.pumpfun import PumpFun


def test_soma_todas_as_trocas():
    # 3 s negativo, 5 s positivo, 2 s negativo, 4 s positivo (referência 1,0)
    pts = [[0, 0.9], [3, 1.1], [8, 0.95], [10, 1.2], [14, 1.3]]
    r = sign_time(pts, 1.0)
    assert r == {"pos_s": 9, "neg_s": 5, "trocas": 3, "neg_pct": 36}


def test_janela_e_sem_dados():
    pts = [[0, 0.9], [10, 1.1], [20, 0.8], [30, 0.7]]
    assert sign_time(pts, 1.0, t_from=10, t_to=30) == {"pos_s": 10, "neg_s": 10, "trocas": 1, "neg_pct": 50}
    assert sign_time(pts, None) is None and sign_time([[0, 1.0]], 1.0) is None


def test_posicao_conta_de_segundo_em_segundo_e_vai_para_o_trade():
    p = {"price_in": 1.0}
    for t, px in [(100, 0.9), (103, 1.1), (108, 0.95), (110, 1.2), (114, 1.25)]:
        PumpFun._sign_note(p, px, t)
    assert PumpFun.sign_out(p) == {"pos_s": 9, "neg_s": 5, "trocas": 3, "neg_pct": 36}
    assert PumpFun.sign_out({"price_in": 1.0}) is None


def test_referencia_e_o_preco_de_mercado_na_entrada():
    """0.32.424: a referência é o preço de mercado da entrada (trader_px), não o price_in com a taxa embutida."""
    p = {"price_in": 1.03, "trader_px": 1.0}
    for t, px in [(0, 1.01), (10, 1.02), (20, 1.02)]:
        PumpFun._sign_note(p, px, t)
    assert PumpFun.sign_out(p)["neg_s"] == 0 and PumpFun.sign_out(p)["pos_s"] == 20


def _pos(**kw):
    p = {"id": "p1", "mint": "M", "symbol": "TK", "price_in": 1.0, "trader_px": 1.0, "stop_pct": 0.0,
         "bm_tneg": {"sum_s": 60.0, "streak_s": 30.0, "stop": 25.0}}
    p.update(kw)
    return p


def _pf():
    pf = PumpFun.__new__(PumpFun)
    feed = []
    pf._save_pos = lambda p: None
    pf._feed = lambda **k: feed.append(k)
    return pf, feed


def test_stop_por_tempo_sem_trocar_liga_o_stop_de_25():
    """0.32.426 (pedido do dono): 30 s seguidos no negativo, sem voltar ao positivo → liga o stop de perda de 25%."""
    pf, feed = _pf()
    p = _pos()
    for t in range(0, 31, 2):
        PumpFun._sign_note(p, 0.95, t)
        pf._tneg_check(p, t)
        if t < 30:
            assert not p.get("bm_tneg_why")
    assert p["stop_pct"] == 25.0 and "seguidos" in p["bm_tneg_why"] and feed[-1]["action"] == "stop por tempo armado"


def test_stop_por_tempo_somado_conta_as_trocas():
    """Negativo 20 s, positivo 5 s, negativo 20 s, positivo 5 s, negativo 20 s = 60 s somados → liga (nenhum trecho chega a 30 s)."""
    pf, _ = _pf()
    p = _pos()
    t = 0
    for dur, px in [(20, 0.9), (5, 1.1), (20, 0.9), (5, 1.1), (21, 0.9)]:
        for _ in range(dur):
            PumpFun._sign_note(p, px, t)
            pf._tneg_check(p, t)
            t += 1
    assert p.get("bm_tneg_why") and "somando" in p["bm_tneg_why"] and p["stop_pct"] == 25.0


def test_no_positivo_nao_liga_e_stop_mais_apertado_fica():
    pf, _ = _pf()
    p = _pos()
    for t in range(0, 200, 5):
        PumpFun._sign_note(p, 1.2, t)
        pf._tneg_check(p, t)
    assert not p.get("bm_tneg_why") and p["stop_pct"] == 0.0
    q = _pos(stop_pct=15.0)
    for t in range(0, 40, 2):
        PumpFun._sign_note(q, 0.9, t)
        pf._tneg_check(q, t)
    assert q["bm_tneg_why"] and q["stop_pct"] == 15.0                 # já tinha stop de 15%: não afrouxa para 25%


def test_regras_do_boost_gravam_o_stop_por_tempo():
    import types
    from app.boostmig import BoostMig
    c = types.SimpleNamespace(pump_bm_tneg_on=True, pump_bm_tneg_sum_s=45, pump_bm_tneg_streak_on=False, pump_bm_tneg_stop_pct=20)
    r = BoostMig.rules(c, {"t0": 0.0}, 10.0)
    assert r["bm_tneg"] == {"sum_s": 45.0, "streak_s": None, "stop": 20.0}
