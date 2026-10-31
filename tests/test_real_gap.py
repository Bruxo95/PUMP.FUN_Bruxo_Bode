"""0.32.107: resumo Real × fictícia e tentativas de venda real. Só mede. Sem internet."""
from app import realgap


def _p(sim, real, **kw):
    return {"sim_pct": sim, "real_pct": real, "dif_pct": real - sim, "sim_sol": sim / 100, "real_sol": real / 100, **kw}


def test_summary_compares_only_real_pairs():
    P = [_p(10, -5, entrada_pct=2.0, saida_pct=-3.0, atraso_s=1.0), _p(-10, -12, entrada_pct=4.0, saida_pct=-1.0, atraso_s=3.0), {"sim_pct": None, "real_sol": 9}]
    S = realgap.summary(P, [], 2)
    assert S["pares"] == 2 and S["sem_par_48h"] == 2 and S["ganhou_fict_perdeu_real"] == 1
    assert S["dif_mediana"] == -8.5 and S["entrada_mediana"] == 3.0 and S["atraso_mediano_s"] == 2.0
    assert S["real_sol"] == -0.17 and "poucos dados" in S["leitura"]


def test_verdict_only_with_enough_pairs():
    S = realgap.summary([_p(10, 5, fechou=f"2026-10-{20 + i}T10:00:00+00:00") for i in range(6)], [])
    assert S["ci"]["dias"] == 6 and S["leitura"].startswith("pior") and "-5.0" in S["leitura"]


def test_sell_ladder_is_counted_step_by_step():
    T = [{"sell_tries": [{"via": "PumpPortal auto 15%", "res": "falhou", "ms": 900}, {"via": "PumpPortal auto 30%", "res": "entrou", "ms": 1100}]},
         {"sell_tries": [{"via": "PumpPortal auto 15%", "res": "entrou", "ms": 700}]}, {}]
    V = {x["degrau"]: x for x in realgap.sells(T)}
    assert V["PumpPortal auto 15%"]["tentativas"] == 2 and V["PumpPortal auto 15%"]["entrou_pct"] == 50
    assert V["PumpPortal auto 30%"]["entrou"] == 1 and V["PumpPortal auto 15%"]["ms_mediano"] == 800
