"""0.32.275 (pedido do dono): média por cópia no laboratório e "Copiar só quem dá resultado"."""
from datetime import datetime, timedelta, timezone

from app import toplab
from tests.test_pump import _pump

T = "Edge".ljust(44, "1")


def _iso(h=1):
    return (datetime.now(timezone.utc) - timedelta(hours=h)).isoformat()


def test_acerto_alto_com_media_negativa():
    """O exemplo do dono: 20 ganhos de 10% e 10 perdas de 40% = 67% de acerto e média negativa."""
    R = [{"pnl_pct": 10, "pnl_sol": 0.01}] * 20 + [{"pnl_pct": -40, "pnl_sol": -0.04}] * 10
    p = toplab.payoff(R)
    assert p["ganho_med_pct"] == 10 and p["perda_med_pct"] == 40
    assert p["por_copia_pct"] == -6.67 and p["acerto_empate"] == 80 and p["fator"] == 0.5


def _copias(pf, pcts):
    for i, x in enumerate(pcts):
        pf.store.save_trade({"id": f"e{i}", "wallet": T, "real": False, "pnl_pct": x, "pnl_sol": x / 1000, "closed_at": _iso(i + 1)})


def test_regra_desligada_nao_muda_nada(tmp_path):
    pf = _pump(tmp_path)
    pf.cfg.pump_real_need_win = False
    assert pf.edge_why(T, True) is None and not pf.sim_only(T)


def test_real_espera_base_e_media_positiva(tmp_path):
    pf = _pump(tmp_path)
    pf.cfg.pump_real_need_win = False
    pf.cfg.pump_edge_on = True
    _copias(pf, [10, 10])
    assert "sem base" in pf.edge_why(T, True) and pf.sim_only(T)        # 2 de 5: a REAL espera
    assert pf.edge_why(T, False) is None                                  # a fictícia copia para aprender
    _copias(pf, [10, 10, 10, 10, -40, -40, -40])                           # média negativa
    pf._edge_key = None
    assert "média de" in pf.edge_why(T, True) and pf.sim_only(T)
    assert pf.edge_why(T, False) is None                                  # "travar só a REAL" ligado (padrão)
    pf.cfg.pump_edge_real_only = False
    assert "média de" in pf.edge_why(T, False)                            # agora sai da fictícia também


def test_media_positiva_libera_a_real(tmp_path):
    pf = _pump(tmp_path)
    pf.cfg.pump_real_need_win = False
    pf.cfg.pump_edge_on = True
    _copias(pf, [30, -10, 25, 5, -8])
    assert pf.edge_why(T, True) is None and not pf.sim_only(T)
