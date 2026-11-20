"""0.32.325 (pedido do dono, 12/11/2026: "sim, faz a trava"): uma tela só compra na REAL depois de provar lucro na FICTÍCIA
(N operações fechadas no período com a soma positiva depois das taxas). Este arquivo usa o padrão de verdade (trava ligada)."""
from datetime import datetime, timedelta, timezone

from app import settings
from app.pumpfun import PumpFun
from app.settings import PumpSettings
from app.store import MemStore

T = "Trader".ljust(44, "1")


def _pf(**kw):
    cfg = PumpSettings()
    cfg.pump_real_need_win = False            # as outras travas da REAL ficam fora: aqui se mede só a trava por tela
    cfg.pump_edge_on = False
    for k, v in kw.items():
        setattr(cfg, k, v)
    return PumpFun(cfg, MemStore())


def _iso(h=1.0):
    return (datetime.now(timezone.utc) - timedelta(hours=h)).isoformat()


def _fechadas(pf, n, sol, pre="t", **extra):
    for i in range(n):
        pf.store.save_trade({"id": f"{pre}{i}", "wallet": T, "real": False, "pnl_pct": sol * 1000, "pnl_sol": sol,
                             "closed_at": _iso(1 + i / 10), **extra})


def test_default_is_on_and_only_restricts_real():
    d = settings.server_defaults()
    assert d["pump_tab_gate_on"] is True and d["pump_tab_gate_n"] == 20 and d["pump_tab_gate_days"] == 7
    assert PumpSettings({}).pump_real_enabled is False


def test_tab_without_proof_stays_out_of_real_and_enters_after_profit():
    pf = _pf()
    assert "0 de 20" in pf.tab_gate_why("Top traders") and pf.sim_only(T)      # sem histórico: só fictícia
    assert "trava por tela" in pf.sim_only_why(T)
    _fechadas(pf, 19, 0.01)
    pf._tgate_key = None
    assert "19 de 20" in pf.tab_gate_why("Top traders") and pf.sim_only(T)
    _fechadas(pf, 1, 0.01, pre="x")
    pf._tgate_key = None
    assert pf.tab_gate_why("Top traders") is None and not pf.sim_only(T)       # 20 fechadas no positivo: liberada
    v = pf.tab_gate_view()
    assert v[0]["aba"] == "Top traders" and v[0]["liberada"] and v[0]["n"] == 20


def test_tab_in_loss_leaves_real_by_itself():
    pf = _pf()
    _fechadas(pf, 20, 0.01)
    _fechadas(pf, 5, -0.05, pre="p")                                            # 5 perdas grandes: a soma fica negativa
    assert "só compra com a tela no positivo" in pf.tab_gate_why("Top traders") and pf.sim_only(T)
    assert pf.tab_gate_view()[0]["liberada"] is False


def test_each_tab_is_judged_alone_and_real_or_fake_gains_do_not_count():
    pf = _pf()
    _fechadas(pf, 25, 0.01, wallet="manual", manual=True, origem="explorar")   # o Explorar provou
    _fechadas(pf, 30, 0.02, pre="r", real=True)                                 # trades REAL não fazem prova
    _fechadas(pf, 30, 9.0, pre="f")                                             # ganho de +900.000% é preço falso: fora
    assert pf.tab_gate_why("Explorar") is None
    assert "0 de 20" in pf.tab_gate_why("Top traders")
    velho = {"id": "v", "wallet": T, "real": False, "pnl_pct": 5, "pnl_sol": 1.0, "closed_at": _iso(24 * 30)}
    pf.store.save_trade(velho)                                                  # fora dos 7 dias: não conta
    pf._tgate_key = None
    assert "0 de 20" in pf.tab_gate_why("Top traders")


def test_switch_off_changes_nothing():
    pf = _pf(pump_tab_gate_on=False)
    assert pf.tab_gate_why("Top traders") is None and not pf.sim_only(T)
    assert pf._sim_only_base(T) is False


def test_boost_nao_passa_pela_trava_por_tela():
    """0.32.392 (dono, 20/11, ONODA: "essa regra não funciona no BOOST, ela estava no copy trade"): o BOOST vai para a REAL
    sem provar na fictícia; as outras telas continuam com a trava."""
    pf = _pf()
    _fechadas(pf, 3, 0.01, wallet="manual", manual=True, origem="boostmig")
    assert pf.tab_gate_why("BOOST da migração") is None
    assert "0 de 20" in pf.tab_gate_why("Explorar")
    v = {x["aba"]: x for x in pf.tab_gate_view()}
    assert v["BOOST da migração"]["sem_trava"] and v["BOOST da migração"]["liberada"]
    assert "boostmig" not in PumpFun.GATE_ORIGINS
