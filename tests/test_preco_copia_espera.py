"""0.32.262 (dono, caso yarl): na cópia com espera a fictícia não entra mais barato que o trader pagou."""
from tests.test_pump import _W, _ev, _pump

M = "Yarl".ljust(40, "1") + "pump"


def test_copia_com_espera_nao_usa_preco_velho_abaixo_do_trader(tmp_path):
    pf = _pump(tmp_path)
    pf.add_manual(_W)
    pf.on_message(_ev("buy", "Out".ljust(44, "1"), M, 0.1, 0.1 / 1e-6, 30, 30 / 1e-6))   # preço guardado: 1e-6
    ev = _ev("buy", _W, M, 0.5, 0.5 / 1.8e-6, 0, 0, _delayed=True)                         # o trader pagou 1,8e-6
    pf.tokens[M]["price"] = 1.28e-6                                                        # preço velho (antes dele)
    pf._copy(_W, M, "buy", 0.5, 0.5 / 1.8e-6, ev, 0, __import__("time").time())
    p = [x for x in pf.store.positions() if x["mint"] == M and not x.get("real")]
    assert p and p[0]["price_in"] >= 1.8e-6
