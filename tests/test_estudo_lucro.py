"""0.32.211 (pedido do dono): quadro "Estudo · deram lucro" — com a chave ligada, as carteiras do estudo que deram lucro
são copiadas só na FICTÍCIA, numa aba própria. Sem internet."""
from tests.test_pump import _pump

W1 = "L1".ljust(44, "1")
W2 = "L2".ljust(44, "1")


def test_profit_wallets_are_copied_only_with_the_switch_and_only_in_the_sim(tmp_path):
    pf = _pump(tmp_path, paid=False, pump_only_online=False)
    pf.study = [W1, W2]
    pf.study_lucro = [W1]
    pf.refresh_followed(force=True)
    assert W1 not in pf.followed and pf.study_lucro_wallets() == []          # chave desligada (padrão): nada muda
    pf.cfg.pump_st_lucro_on = True
    pf.refresh_followed(force=True)
    assert W1 in pf.followed and W2 not in pf.followed
    assert pf.sim_only(W1) and "deu lucro" in pf.sim_only_why(W1)            # nunca vai para a REAL
    assert pf.aba_of({"wallet": W1}) == "Estudo · deram lucro" and pf.aba_of({"wallet": W2}) == "Carteiras em estudo"
    assert pf.tab_off(W1) is None
    pf.cfg.pump_st_lucro_on = False
    assert pf.tab_off(W1) is None or "desligada" in pf.tab_off(W1)
    pf.refresh_followed(force=True)
    assert W1 not in pf.followed


def test_profit_wallets_go_to_the_real_only_with_their_own_real_switch(tmp_path):
    """0.32.213 (pedido do dono): chave "Estudo · deram lucro na REAL" (começa desligada)."""
    from app.settings import USER_KEYS
    assert USER_KEYS["pump_st_lucro_real"][1] is False
    pf = _pump(tmp_path, paid=False, pump_only_online=False)
    pf.study = [W1]
    pf.study_lucro = [W1]
    pf.cfg.pump_st_lucro_on = True
    assert pf.sim_only(W1)
    pf.cfg.pump_st_lucro_real = True
    assert not pf.sim_only(W1)
