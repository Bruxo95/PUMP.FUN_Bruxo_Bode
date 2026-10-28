"""0.31.86: Raio-X do token, veredito medido por sombras e sombras fora de "chance alta" fora do aprender com os erros."""
from app.basegeral import verdict_study
from app.raiox import analyze, parse, study


def _tr(t, typ, w, amt, sol):
    return {"time": 1_793_000_000_000 + t * 1000, "type": typ, "wallet": w, "amount": amt, "volumeSol": sol, "priceUsd": 0.001}


def test_xray_first_buyers_and_dump():
    js = {"trades": [_tr(0, "buy", "A", 100, 1), _tr(0, "buy", "B", 100, 1), _tr(30, "buy", "C", 50, 0.5),
                     _tr(120, "sell", "A", 100, 1.5), _tr(125, "sell", "B", 60, 0.9), _tr(4000, "sell", "C", 4, 0.04)]}
    r = analyze(parse(js))
    assert r["n"] == 6 and r["compradores"] == 3 and r["sinais"]["bloco_n"] == 2
    first = {x["wallet"]: x for x in r["primeiros"]}
    assert first["A"]["perfil"] == "vendeu tudo" and first["C"]["perfil"] == "segurou"
    assert r["sinais"]["vendas_cedo_pct"] == round(2 / 3 * 100, 1)
    assert r["despejo"]["minuto"] == 2 and r["despejo"]["primeiros_no_despejo"] == 2
    st = study({"M": r}, {"M": {"pnl_pct": -30.0, "sombra": True}})
    assert any(x["feature"] == "vendas_cedo_pct" and x["faixa"] == "50 a 75%" and x["n_sombra"] == 1 for x in st)


def test_verdict_study_uses_cost_and_peak():
    sh = {"a": {"ret": 20.0, "pico": 60.0, "veredito": "fraco"}, "b": {"ret": 2.0, "pico": 10.0, "veredito": "fraco"},
          "c": {"ret": None, "veredito": "lixo"}, "d": {"ret": 10.0, "pico": 12.0}}
    v = {x["veredito"]: x for x in verdict_study(sh, 4.0)}
    assert v["fraco"]["n"] == 2 and v["fraco"]["ganharia"] == 1 and v["fraco"]["pico_50"] == 1
    assert v["chance alta"]["n"] == 1 and "lixo" not in v


def test_other_verdict_shadows_stay_out_of_learning():
    from app.hub import PumpHub
    h = object.__new__(PumpHub)
    h.shadows = {"x": {"t0": 1_793_000_000, "ret": 50.0, "veredito": "fraco", "info": {}},
                 "y": {"t0": 1_793_000_000, "ret": 50.0, "veredito": "chance alta", "info": {}}}
    assert [t["mint"] for t in h.shadow_trades()] == ["y"]
