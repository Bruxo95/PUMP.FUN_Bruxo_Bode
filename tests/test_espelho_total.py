"""0.32.277 (pedido do dono, 10/11/2026): "a fictícia compra com lucro e a REAL não; tem que ser o espelho". Espelho total ignora o
"só fictícia" do estudo; as travas com chave própria (lucro na fictícia, só quem dá resultado) continuam."""
from datetime import datetime, timezone

from app import settings
from tests.test_pump import _pump

W = "Estudo".ljust(44, "1")


def _lucro(pf, w):
    pf.store.save_trade({"wallet": w, "real": False, "pnl_sol": 0.01, "closed_at": datetime.now(timezone.utc).isoformat()})


def test_comeca_desligado():
    assert settings.USER_KEYS["pump_real_full_mirror"][1] is False


def test_so_ficticia_do_estudo_vale_ate_ligar_o_espelho_total(tmp_path):
    pf = _pump(tmp_path)
    pf.cfg.pump_real_need_win = False
    pf.sim_only_list = [W]                                      # escolheu "só fictícia" no Copiar
    pf.study = [W]
    assert pf.sim_only(W) and "só fictícia" in pf.sim_only_why(W)
    pf.cfg.pump_real_full_mirror = True
    assert not pf.sim_only(W)                                   # a REAL também compra


def test_trava_de_lucro_continua_com_a_chave_dela(tmp_path):
    pf = _pump(tmp_path)
    pf.sim_only_list = [W]
    pf.cfg.pump_real_full_mirror = True
    pf.cfg.pump_real_need_win = True
    assert pf.sim_only(W) and "Espelho" in pf.sim_only_why(W)   # sem lucro na fictícia nas 24 h: espera
    _lucro(pf, W)
    assert not pf.sim_only(W)
    pf.cfg.pump_real_need_win = False
    assert not pf.sim_only(W)


def test_copiar_so_quem_da_resultado_continua_valendo(tmp_path):
    pf = _pump(tmp_path)
    pf.cfg.pump_real_need_win = False
    pf.cfg.pump_real_full_mirror = True
    pf.cfg.pump_edge_on = True
    pf.study = [W]
    assert pf.sim_only(W)                                       # sem base de cópias: a REAL espera
    pf.cfg.pump_edge_on = False
    assert not pf.sim_only(W)
