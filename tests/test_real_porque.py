"""0.32.162 (pedido do dono: "por que só a fictícia está funcionando?"): o que impede a REAL de comprar e por que ela ficou de
fora em cada token. Tudo com carteira falsa: nenhuma transação de verdade."""
from app.pumpfun import _Buying
from tests.test_espelho_real import _pf
from tests.test_pump import _W, _ev


def test_real_why_shows_the_open_limit_and_each_token_left_out(tmp_path):
    pf = _pf(tmp_path)
    pf.cfg.pump_real_max_open = 1
    pf.add_manual(_W)
    m1, m2 = "Why1".ljust(40, "1") + "pump", "Why2".ljust(40, "1") + "pump"
    pf.on_message(_ev("buy", _W, m1, 1.0, 1e6, 30, 3e7))                 # a real de m1 vai para a fila (1 de 1)
    pf.on_message(_ev("buy", _W, m2, 1.0, 1e6, 30, 3e7))                 # m2: a real fica de fora pelo limite
    r = pf.real_why()
    assert not r["pode_comprar"] and any("limite de 1 posições reais" in x for x in r["agora"])
    assert r["compras_ficticia"] == 2 and r["nao_copiou_real"] == 1
    assert "limite de 1" in r["motivos"][0]["motivo"] and r["itens"][0]["acao"] == "REAL não copiou"


def test_study_wallet_says_why_it_copies_only_in_sim(tmp_path):
    pf = _pf(tmp_path)
    pf.add_manual(_W)
    pf.study = [_W]
    m = "Stud".ljust(40, "1") + "pump"
    pf.on_message(_ev("buy", _W, m, 1.0, 1e6, 30, 3e7))
    e = next(f for f in pf.feed if f.get("action") == "REAL não copiou")
    assert "Carteiras em estudo" in e["reason"] and pf._rq.qsize() == 0


def test_forgotten_real_buy_does_not_hold_the_limit_forever():
    b = _Buying()
    b.add("velho")
    b.add("novo")
    b.at["velho"] -= 700                                                 # entrou há mais de 10 min e nunca saiu
    assert b.prune() == ["velho"] and "velho" not in b and "novo" in b and len(b) == 1
