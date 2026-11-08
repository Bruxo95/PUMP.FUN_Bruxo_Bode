"""0.32.251/0.32.265 (pedido do dono): só na fictícia até uma cópia fictícia com lucro nas últimas 24 h; vale também para a
lista manual."""
from datetime import datetime, timedelta, timezone

from tests.test_pump import _W, _pump

T = "Novo".ljust(44, "1")


def _iso(h_atras):
    return (datetime.now(timezone.utc) - timedelta(hours=h_atras)).isoformat()


def test_trader_novo_fica_so_na_ficticia_ate_dar_lucro(tmp_path):
    pf = _pump(tmp_path)
    assert pf.sim_only(T) and "últimas 24 h" in pf.sim_only_why(T)
    pf.store.save_trade({"wallet": T, "real": False, "pnl_sol": -0.02, "closed_at": _iso(1)})     # perdeu: só fictícia
    assert pf.sim_only(T)
    pf.store.save_trade({"wallet": T, "real": True, "pnl_sol": 0.05, "closed_at": _iso(1)})       # lucro na REAL não conta
    assert pf.sim_only(T)
    pf.store.save_trade({"wallet": T, "real": False, "pnl_sol": 0.01, "closed_at": _iso(2)})      # lucro na fictícia: REAL
    assert not pf.sim_only(T)


def test_lucro_com_mais_de_24h_nao_vale(tmp_path):
    pf = _pump(tmp_path)
    pf.store.save_trade({"wallet": T, "real": False, "pnl_sol": 0.07, "closed_at": _iso(25)})
    assert pf.sim_only(T)


def test_lista_manual_tambem_passa_pela_prova(tmp_path):
    pf = _pump(tmp_path)
    pf.add_manual(_W)
    assert pf.sim_only(_W)
    pf.store.save_trade({"wallet": _W, "real": False, "pnl_sol": 0.01, "closed_at": _iso(3)})
    assert not pf.sim_only(_W)


def test_opcao_desligada_e_compras_sem_carteira(tmp_path):
    pf = _pump(tmp_path)
    pf.cfg.pump_real_need_win = False
    assert not pf.sim_only(T)
    pf.cfg.pump_real_need_win = True
    assert not pf.sim_only("manual")                                                             # botão Comprar etc.
