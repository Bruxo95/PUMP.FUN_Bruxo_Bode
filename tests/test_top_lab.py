"""0.32.124: Laboratório do Top traders. Só mede. Sem internet."""
import inspect
from datetime import datetime, timedelta, timezone

from app import toplab
from app.toplab import Barred

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


def tr(dia, pnl, w="W1", **kw):
    fe = T0 + timedelta(days=dia, hours=3)
    return {"closed_at": fe.isoformat(), "wallet": w, "pnl_pct": pnl, "pnl_sol": pnl / 1000, "sol_in": 0.1, **kw}


def aba(t):
    return t.get("_a", toplab.ABA)


def test_one_lucky_day_is_not_called_proven():
    r = toplab.study([tr(0, 100.0), tr(0, 90.0), tr(0, 80.0), tr(1, -5.0)], aba)
    assert r["ci"]["lo"] is None and "poucos dados" in r["leitura"]
    assert r["top3_sol"] == 0.27 and r["sem_top3_sol"] == -0.005
    assert r["traders"][0]["veredito"] == "poucos dados"


def test_other_tabs_real_and_false_gains_stay_out():
    r = toplab.study([tr(0, 10.0), tr(0, 10.0, _a="Explorar"), tr(0, 10.0, real=True), tr(0, 5000.0)], aba)
    assert r["trades"] == 1


def test_trader_verdicts():
    bom = [tr(d, 20.0 + d, "A") for d in range(6)]
    ruim = [tr(d, -20.0 - d, "B") for d in range(6)]
    pouco = [tr(0, 50.0, "C")]
    fraco = [tr(0, -10.0, "D") for _ in range(5)]
    v = {x["wallet"]: x["veredito"] for x in toplab.traders(bom + ruim + pouco + fraco)}
    assert v == {"A": "provado", "B": "ruim", "C": "poucos dados", "D": "ruim"}


def test_late_price_lowers_the_result():
    t = tr(0, 100.0, trader_px=1.0, late={"5": 1.25, "15": None})
    L = {x["segundos"]: x for x in toplab.late([t])}
    assert L[5]["n"] == 1 and L[5]["ficticia_pct"] == 100.0 and L[5]["honesta_pct"] == 60.0 and L[5]["perda_pct"] == -40.0
    assert L[15]["n"] == 0 and L[30]["honesta_pct"] is None


def test_barred_buy_is_followed_for_15_minutes():
    b = Barred()
    b.note("W", "M", "SYM", "filtro X de 30 SOL", 1000.0)
    b.note("W", "M", "SYM", "de novo", 1100.0)
    assert len(b.items) == 1 and b.mints() == ["M"]
    px = {"M": 1.0}
    assert b.tick(px.get, 1002.0) == []                     # antes dos 5 s não vale como entrada
    b.tick(px.get, 1006.0)
    px["M"] = 2.0
    b.tick(px.get, 1500.0)
    px["M"] = 1.5
    done = b.tick(px.get, 1000.0 + toplab.WATCH_S)
    assert done[0]["ret"] == 46.0 and done[0]["pico"] == 100.0 and b.mints() == []


def test_barred_stop_counts_first_and_no_price_is_dropped():
    b = Barred()
    b.note("W", "M", "S", "x", 0.0)
    b.note("W", "N", "S", "x", 0.0)
    px = {"M": 1.0}
    b.tick(px.get, 6.0)
    px["M"] = 0.6
    b.tick(px.get, 100.0)
    px["M"] = 3.0
    done = b.tick(px.get, float(toplab.WATCH_S))
    assert done[0]["ret"] == -34.0 and len(b.items) == 1     # N nunca teve preço e saiu


def test_barred_limit_is_shown():
    b = Barred()
    for i in range(toplab.MAX_OPEN + 3):
        b.note("W", f"M{i}", "S", "x", 0.0)
    assert len(b.items) == toplab.MAX_OPEN and b.study()["fora"] == 3


def test_barred_study_needs_days_and_keeps_motives_apart():
    b = Barred()
    base = T0.timestamp()
    for d in range(6):
        b.items[f"a{d}"] = {"t0": base + d * 86400, "why": f"market cap {d} SOL acima", "ret": 30.0 + d}
    b.items["z"] = {"t0": base, "why": "outro motivo", "ret": -10.0}
    M = {x["motivo"]: x for x in b.study()["motivos"]}
    assert M["market cap # SOL acima"]["veredito"] == "pode estar barrando ganhos" and M["outro motivo"]["veredito"] == "poucos dados"


def test_module_decides_nothing():
    src = inspect.getsource(toplab)
    for proibido in ("manual_buy", "save_settings", ".pause(", "_sell("):
        assert proibido not in src


def test_repeat_buy_keeps_the_finished_result():
    b = Barred()
    b.note("W", "M", "S", "x", 0.0)
    px = {"M": 1.0}
    b.tick(px.get, 6.0)
    b.tick(px.get, float(toplab.WATCH_S))
    b.note("W", "M", "S", "x", 4000.0)
    assert len(b.items) == 2 and b.study()["prontas"] == 1 and b.study()["abertas"] == 1


def _late(p, marks):
    import types
    from app.pumpfun import PumpFun
    salvou = []
    o = types.SimpleNamespace(_save_pos=salvou.append)
    for t, px in marks:
        PumpFun._late_note(o, p, px, t)
    return salvou


def test_late_price_only_records_and_skips_stale_or_manual_positions():
    p = {"open_t": 100.0, "wallet": "W", "price_in": 1.0, "stop_pct": 30}
    salvou = _late(p, [(102.0, 1.0), (106.0, 1.1), (117.0, 1.2), (160.0, 1.5)])
    assert p["late"] == {"5": 1.1, "15": 1.2, "30": None} and len(salvou) == 3
    assert p["price_in"] == 1.0 and p["stop_pct"] == 30
    for outra in ({"open_t": 1.0, "wallet": "W", "real": True}, {"open_t": 1.0, "wallet": "manual"}, {"open_t": 1.0, "wallet": "W", "manual": True}):
        assert _late(outra, [(50.0, 1.0)]) == [] and "late" not in outra


def test_position_already_held_is_not_a_barred_buy():
    import types
    from app.pumpfun import PumpFun
    notas = []
    o = types.SimpleNamespace(top_hook=lambda *a: notas.append(a), tokens={"M": {"symbol": "S"}})
    PumpFun._top_barred(o, "W", "M", "já tem posição copiada neste token (fictícia)", 1.0)
    PumpFun._top_barred(o, "W", "M", "market cap alto", 1.0)
    assert [n[3] for n in notas] == ["market cap alto"]


def _tab(**cfg):
    import types
    from app.pumpfun import PumpFun
    o = types.SimpleNamespace(cfg=types.SimpleNamespace(**cfg), ABA_ORIGEM=PumpFun.ABA_ORIGEM, TAB_SWITCH=PumpFun.TAB_SWITCH, study=["S"], study_copy=[], elite_follow=["E"])
    o.aba_of = lambda x: PumpFun.aba_of(o, x)
    return lambda who: PumpFun.tab_off(o, who)


def test_tab_switch_only_stops_its_own_tab_and_defaults_to_on():
    assert _tab()("W") is None and _tab()("S") is None
    off = _tab(pump_top_on=False)
    assert off("W") == "aba Top traders desligada" and off("S") is None and off("E") is None
    assert _tab(pump_st_copy_on=False)("S") == "aba Carteiras em estudo desligada" and _tab(pump_st_copy_on=False)("W") is None


def test_switched_off_tab_is_not_a_barred_buy():
    import types
    from app.pumpfun import PumpFun
    notas = []
    o = types.SimpleNamespace(top_hook=lambda *a: notas.append(a), tokens={})
    PumpFun._top_barred(o, "W", "M", "aba Top traders desligada", 1.0)
    PumpFun._top_barred(o, "W", "M", "cópia desligada", 1.0)
    assert notas == []


def test_new_switches_exist_and_start_on():
    from app.settings import USER_KEYS
    assert USER_KEYS["pump_top_on"][1] is True and USER_KEYS["pump_st_copy_on"][1] is True
