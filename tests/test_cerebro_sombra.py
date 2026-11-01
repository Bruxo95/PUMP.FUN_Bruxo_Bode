"""0.32.117: o cérebro em sombra julga cada trade só com o passado e nunca bloqueia nada. Sem internet."""
import inspect
from datetime import datetime, timedelta, timezone

from app import brainshadow as bs


def tr(dia, h, pnl, mcap=20.0, mint=None, **kw):
    ab = datetime(2026, 10, dia, h, 0, tzinfo=timezone.utc)
    fe = ab + timedelta(minutes=20)
    return {"opened_at": ab.isoformat(), "closed_at": fe.isoformat(), "mint": mint or f"m{dia}{h}", "pnl_pct": pnl, "pnl_sol": pnl / 1000, "mcap_in": mcap, **kw}


def rows(L, aba="Aba do Bruxo", conta="a"):
    return [(conta, aba, t) for t in L]


def linha(r, nome="Aba do Bruxo"):
    return next(x for x in r["abas"] if x["aba"] == nome)


def test_first_trades_are_never_barred_because_there_is_no_past():
    r = bs.run(rows([tr(1, h, -30.0) for h in range(0, 6)]))
    assert linha(r)["fechadas"] == 6 and linha(r)["atual"]["n"] == 0


def test_rule_only_bars_after_the_band_went_bad_and_counts_the_saved_loss():
    r = bs.run(rows([tr(1, h, -30.0) for h in range(0, 6)] + [tr(2, 10, -30.0), tr(2, 12, 50.0)]))
    x = linha(r)["atual"]
    assert x["n"] == 2 and x["ganhos"] == 1
    assert x["poupado_sol"] == 0.03 and x["perderia_sol"] == 0.05 and x["efeito_sol"] == -0.02


def test_trade_still_open_when_the_next_one_starts_is_not_known_yet():
    ab = tr(1, 0, -30.0)
    ab["closed_at"] = datetime(2026, 10, 9, tzinfo=timezone.utc).isoformat()   # só fechou dias depois
    r = bs.run(rows([ab] + [tr(1, h, -30.0) for h in range(1, 6)] + [tr(2, 10, -30.0)]))
    assert linha(r)["atual"]["n"] == 0                 # só 5 fechadas antes do último: abaixo do mínimo de 6


def test_same_token_in_two_accounts_counts_once():
    t = [tr(1, 1, -30.0, mint="X")]
    r = bs.run(rows(t, conta="a") + rows(t, conta="b"))
    assert linha(r)["fechadas"] == 1


def test_only_entry_time_numbers_are_used():
    t = tr(1, 3, 10.0, score=50.0, score_parts={"pressão": 0.8}, hold_s=9, best_pct=900, reason="x")
    nomes = dict(bs.features(t, datetime.fromisoformat(t["opened_at"]).timestamp()))
    assert nomes["Valor de mercado na entrada"] == "abaixo de 30 SOL" and nomes["Nota da entrada"] == "40 a 55"
    assert nomes["Pressão de compra (parte da nota)"] == "forte" and len(nomes) == 4


def test_real_copies_and_explorar_stay_out():
    of = lambda t: t.get("_a", "Aba do Bruxo")
    assert bs.aba({"pnl_pct": 1, "real": True}, of) is None and bs.aba({"pnl_pct": 1, "follow_of": {}}, of) == "Aba do Bruxo"
    assert bs.aba({"pnl_pct": 1, "follow_of": {"user": "x"}}, of) is None
    assert bs.aba({"pnl_pct": 1, "_a": "Explorar"}, of) is None and bs.aba({"pnl_pct": 5000}, of) is None
    assert bs.aba({"pnl_pct": 1, "_a": "Botão Comprar"}, of) is None


def test_reading_never_claims_gain_without_the_range():
    assert bs._leitura({"n": 0, "dias": 0, "lo": None}).startswith("não teria barrado")
    assert bs._leitura({"n": 9, "dias": 2, "lo": None, "hi": None, "media": -20}).startswith("poucos dados")
    assert bs._leitura({"n": 9, "dias": 6, "lo": -30.0, "hi": 4.0, "media": -9}).startswith("ainda não dá")
    assert bs._leitura({"n": 9, "dias": 6, "lo": -30.0, "hi": -4.0, "media": -9}).startswith("ajudaria")
    assert bs._leitura({"n": 9, "dias": 6, "lo": 4.0, "hi": 30.0, "media": 9}).startswith("atrapalharia")


def test_module_decides_nothing():
    src = inspect.getsource(bs)
    for proibido in ("manual_buy", "learned_for_entry", "save_settings", "_sell("):
        assert proibido not in src


def test_every_automatic_tab_gets_its_own_label():
    import types
    from app.pumpfun import PumpFun
    o = types.SimpleNamespace(ABA_ORIGEM=PumpFun.ABA_ORIGEM, study=[], study_copy=[], elite_follow=[])
    assert PumpFun.aba_of(o, {"origem": "jevtrade", "wallet": "manual"}) == "Jev Trade"
    assert PumpFun.aba_of(o, {"origem": "explorar", "wallet": "manual"}) == "Explorar"
    assert PumpFun.aba_of(o, {"wallet": "manual", "manual": True, "auto": "automático: Boost ON"}) == "Base da pump.fun"
    assert PumpFun.aba_of(o, {"wallet": "manual", "manual": True, "entrou_porque": "automático: chance alta (70%)"}) == "Base da pump.fun"
    assert PumpFun.aba_of(o, {"wallet": "manual", "manual": True}) == "Botão Comprar"
