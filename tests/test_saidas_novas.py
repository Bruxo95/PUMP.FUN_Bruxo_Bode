"""0.32.323 (pedido do dono, 11/11/2026: "por que estamos sempre no negativo" → "Sim, aplica"): padrões novos de saída da cópia
na Solana e o ajuste único das contas que ainda estavam nos antigos. Este arquivo usa os padrões de verdade (ver conftest)."""
from app import settings
from app.settings import SAIDAS_OLD, SAIDAS_V, PumpSettings, saidas_upgrade


def test_new_exit_defaults():
    d = settings.server_defaults()
    assert d["pump_stop_pct"] == 30 and d["pump_hold_until_profit"] is False
    assert d["pump_trail_start_pct"] == 25 and d["pump_trail_dist_pct"] == 20
    assert d["pump_edge_on"] is True and d["pump_edge_real_only"] is True      # só trava a REAL; a fictícia segue copiando
    assert PumpSettings({}).pump_real_enabled is False                           # nada liga a REAL
    # as regras próprias do Explorar não mudam (lógica intocável sem OK do dono)
    assert d["pump_ar_stop_pct"] == 25 and d["pump_ar_trail_start"] == 40 and d["pump_ar_trail_dist"] == 15 and d["pump_ex_auto_on"] is True


def test_upgrade_only_touches_what_was_still_the_old_default():
    antiga = dict(PumpSettings(dict(SAIDAS_OLD)).user_dict())                    # conta gravada com os padrões antigos
    ch = saidas_upgrade(antiga, antiga)
    assert ch == {"pump_stop_pct": 30.0, "pump_hold_until_profit": False, "pump_trail_start_pct": 25.0,
                  "pump_trail_dist_pct": 20.0, "pump_edge_on": True}
    assert "pump_real_enabled" not in ch and "pump_sim_on" not in ch and not [k for k in ch if k.startswith(("pump_ex_", "pump_ar_"))]
    escolheu = {**antiga, "pump_stop_pct": 55.0, "pump_trail_dist_pct": 13.0}    # valores que a pessoa escolheu ficam
    ch = saidas_upgrade(escolheu, escolheu)
    assert "pump_stop_pct" not in ch and "pump_trail_dist_pct" not in ch and ch["pump_hold_until_profit"] is False
    ch = saidas_upgrade(antiga, antiga, mexeu={"pump_hold_until_profit", "pump_stop_pct"})   # mexeu pela tela: não muda
    assert "pump_hold_until_profit" not in ch and "pump_stop_pct" not in ch and ch["pump_trail_start_pct"] == 25.0


def test_upgrade_runs_once_and_never_for_a_new_account():
    antiga = dict(PumpSettings(dict(SAIDAS_OLD)).user_dict())
    assert saidas_upgrade({}, antiga) == {} and saidas_upgrade(None, antiga) == {}       # conta nova já nasce no padrão novo
    assert saidas_upgrade({**antiga, "_saidas_v": SAIDAS_V}, antiga) == {}               # já recebeu: quem voltou ao antigo fica
    assert saidas_upgrade({**antiga, "_saidas_v": "x"}, antiga)                          # marca estragada: trata como não feito
