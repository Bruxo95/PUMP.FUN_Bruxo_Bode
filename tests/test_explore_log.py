"""0.31.88: log de análise do Explorar (ciclo por lista) e estudo dos filtros pelas sombras."""
from app.basegeral import filters_study


class _E:
    from app.pumpfun import PumpFun
    explore_cycle_note = PumpFun.explore_cycle_note


def test_cycle_note_counts_and_changes_only():
    e = _E()
    e._ex_funnel = {"A": {"t": 100.0, "symbol": "AAA", "chance": "chance alta", "why": "pressão abaixo de 60", "entrou": False},
                    "B": {"t": 100.0, "symbol": "BBB", "chance": "fraco", "why": "veredito não é chance alta", "entrou": False},
                    "C": {"t": 100.0, "symbol": "CCC", "chance": "chance alta", "why": None, "entrou": True},
                    "D": {"t": 50.0, "symbol": "DDD", "chance": "fraco", "why": "velho", "entrou": False}}
    r = e.explore_cycle_note(90.0, 10, 3, 100.0)
    assert r["analisados"] == 3 and r["sem_preco"] == 7 and r["chance_alta"] == 2 and r["entrou"] == ["CCC"]
    assert r["chance_alta_barrados"][0]["symbol"] == "AAA" and r["gargalo"]
    assert e.explore_cycle_note(90.0, 10, 3, 100.0) is None              # nada mudou: não grava de novo


def test_filters_study():
    sh = {"a": {"ret": 30.0, "pico": 80.0, "why": "veredito não é chance alta", "veredito": "fraco"},
          "b": {"ret": -20.0, "why": "veredito não é chance alta", "veredito": "lixo"},
          "c": {"ret": 10.0, "why": "pressão abaixo de 60", "veredito": "chance alta"}}
    f = {x["motivo"]: x for x in filters_study(sh, 4.0)}
    v = f["veredito não é chance alta"]
    assert v["n"] == 2 and v["ganhariam"] == 1 and v["pico_50"] == 1 and f["pressão abaixo de 60"]["chance_alta"] == 1
