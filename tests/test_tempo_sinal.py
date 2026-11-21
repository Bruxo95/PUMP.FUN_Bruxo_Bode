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
