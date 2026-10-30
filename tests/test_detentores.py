"""0.32.86: regra dos detentores (ideia do Bruxo). Só mede; sem internet."""
from app import detentores
from app.bruxo import Bruxo

M = "Hold".ljust(40, "1") + "pump"


def _sig(hold, marks=None, hpx=None, t=1000.0, **kw):
    return {"t": t, "mint": M, "symbol": "HLD", "holders": {str(k): v for k, v in hold.items()},
            "marks": {str(k): v for k, v in (marks or {}).items()}, "hpx": {str(k): v for k, v in (hpx or {}).items()}, **kw}


def test_rule_needs_minimum_and_two_rises_in_a_row():
    assert detentores.entry(_sig({0: 40, 1: 48, 2: 55})) == 2
    assert detentores.entry(_sig({0: 12, 1: 25, 5: 45})) == 5
    assert detentores.entry(_sig({0: 40, 1: 40, 2: 40, 3: 40})) is None          # parado: "esquece"
    assert detentores.entry(_sig({0: 40, 1: 48, 2: 44, 3: 41})) is None          # caiu
    assert detentores.entry(_sig({0: 30, 1: 32, 2: 34})) is None                 # abaixo do mínimo
    assert detentores.entry(_sig({0: 30, 1: 32, 2: 34}), min_h=30) == 2
    assert detentores.entry(_sig({0: 100, 1: 101, 2: 102})) is None              # alta pequena demais (10%)
    assert detentores.entry(_sig({0: 100, 1: 101, 2: 102}), grow_pct=0) == 2
    assert detentores.entry(_sig({0: 40, 1: None, 2: 44, 3: 50})) == 3           # leitura perdida fica de fora
    assert detentores.entry(_sig({0: 1, 1: 2, 10: 3, 25: 90})) is None           # depois dos 10 min não vale


def test_entry_uses_the_price_of_the_reading_not_the_signal():
    s = _sig({0: 40, 1: 48, 2: 60}, marks={10: 100}, hpx={2: 60})                # sinal +0 → leitura +60% → saída +100%
    r, dob = detentores.result(s, 2, "10")
    assert r == round((200 / 160 - 1) * 100 - detentores.FEE_PCT, 2) and dob is False


def test_stop_comes_before_the_exit_and_late_entry_exits_at_25():
    s = _sig({}, marks={5: 10, 10: 50}, hpx={2: 100})
    assert detentores.result(s, 2, "10")[0] == -30 - detentores.FEE_PCT          # caiu 45% depois da entrada
    s = _sig({}, marks={5: 20, 25: 44})
    assert detentores.result(s, 5, "5")[0] == round(20 - detentores.FEE_PCT, 2)
    assert detentores.result(_sig({}, marks={5: 20}), 5, "10") == (None, False)  # ainda sem a foto da saída


def test_study_groups_and_compares_with_all_signals():
    sobe = _sig({0: 45, 1: 60, 2: 80, 5: 120}, marks={1: 5, 5: 20, 10: 80}, hpx={2: 10}, peak_pct=90, peak_s=500, jev={"acao": "entrar"})
    parado = _sig({0: 8, 1: 8, 5: 8}, marks={5: -10, 10: -20}, t=2000.0, peak_pct=2, peak_s=30)
    sem = {"t": 3000.0, "mint": M, "holders": {"0": None}, "marks": {}}
    D = detentores.study([sobe, parado, sem], "10")
    assert D["sinais"] == 3 and D["medidos"] == 2 and D["sem_dados"] == 1
    assert D["regra"]["n"] == 1 and D["regra"]["medidos"] == 1 and D["regra_jev"]["n"] == 1
    assert D["regra"]["curva"][0][0] == 1000.0 + 120
    assert {f["faixa"]: f["n"] for f in D["faixas"]} == {"40 a 79": 1, "menos de 20": 1}
    assert {f["faixa"]: f["n"] for f in D["evolucao"]} == {"subiu mais de 50%": 1, "caiu ou parou": 1}
    assert D["linhas"][0]["ligou"] == 2 and "poucos dados" in D["leitura"]


def test_detail_shows_the_tokens_and_the_total_without_the_biggest_wins():
    sigs = [_sig({0: 45, 1: 60, 2: 80}, marks={10: v}, hpx={2: 0}, t=1000.0 + i, peak_pct=max(v, 0)) for i, v in enumerate((500, 10, -10, -20, -20))]
    D = detentores.study(sigs, "10")
    G = D["detalhe"]["todos"]
    assert G["medidos"] == 5 and G["itens"][0]["res"] == 496 and G["itens"][-1]["res"] == -24
    assert G["ganhos_sol"] == round((496 + 6) * 0.1 / 100, 5) and G["perdas_sol"] == round(-(14 + 24 + 24) * 0.1 / 100, 5)
    assert G["mediana_pct"] == -14 and G["sem_top3_sol"] == round(-48 * 0.1 / 100, 5) and G["sem_top3_media"] == -24
    assert D["detalhe"]["regra"]["itens"][0]["ligou"] == 2 and D["detalhe"]["regra_jev"]["n"] == 0
    assert detentores.study([_sig({0: 45, 1: 60, 2: 80}, marks={10: 3000}, hpx={2: 0})], "10")["detalhe"]["todos"]["suspeitos"] == 1


def test_only_coins_with_40_holders_are_read_every_minute():
    b = Bruxo()
    t = 1_000_000.0
    s, _ = b.on_buy("W".ljust(44, "1"), "Top", M, "HLD", 1.0, 1e-6, {}, 1.0, {}, t)
    s["holders"].update({"0": 12, "1": 39})
    assert b.holders_due(t + 125) == []                                          # abaixo de 40: fica nas marcas fixas
    s["holders"]["1"] = 40
    assert [k for _, k in b.holders_due(t + 125)] == ["2"]
    s["holders"]["2"] = 44
    assert [k for _, k in b.holders_due(t + 182)] == ["3"]
    assert [k for _, k in b.holders_due(t + 335)] == ["5"]                       # leitura extra atrasada é pulada
    assert "3" not in s["holders"]


def test_fixed_marks_come_first_when_the_queue_fills():
    b = Bruxo()
    t = 1_000_000.0
    a, _ = b.on_buy("W".ljust(44, "1"), "Top", M, "HLD", 1.0, 1e-6, {}, 1.0, {}, t)
    a["holders"].update({"0": 50, "1": 60})
    c, _ = b.on_buy("X".ljust(44, "1"), "Top", "Other".ljust(40, "1") + "pump", "OTH", 1.0, 1e-6, {}, 1.0, {}, t + 120)
    assert [(s is c, k) for s, k in b.holders_due(t + 125)] == [(True, "0"), (False, "2")]
