"""0.32.251 (pedido do dono, caso Fvgs…pTkL): trader novo do Top traders só na fictícia até uma cópia fictícia com lucro."""
from tests.test_pump import _W, _pump

T = "Novo".ljust(44, "1")


def test_trader_novo_fica_so_na_ficticia_ate_dar_lucro(tmp_path):
    pf = _pump(tmp_path)
    assert pf.sim_only(T) and "trader novo" in pf.sim_only_why(T)
    pf.store.save_trade({"wallet": T, "real": False, "pnl_sol": -0.02})           # perdeu: continua só fictícia
    assert pf.sim_only(T)
    pf.store.save_trade({"wallet": T, "real": True, "pnl_sol": 0.05})             # lucro na REAL não conta
    assert pf.sim_only(T)
    pf.store.save_trade({"wallet": T, "real": False, "pnl_sol": 0.01})            # 1ª cópia fictícia com lucro
    assert not pf.sim_only(T)


def test_lista_manual_e_opcao_desligada_nao_passam_pela_prova(tmp_path):
    pf = _pump(tmp_path)
    pf.add_manual(_W)
    assert not pf.sim_only(_W)
    pf.cfg.pump_real_need_win = False
    assert not pf.sim_only(T)
    assert not pf.sim_only("manual")                                              # botão Comprar etc. não são carteiras
