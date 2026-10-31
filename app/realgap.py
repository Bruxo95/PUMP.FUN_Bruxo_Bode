"""Real × fictícia (0.32.107, lote 11 conferido): ninguém publica essa diferença medida nos mesmos sinais, e o espelho já tem os pares.

`summary` junta os pares de `PumpFun.mirror_pairs` e as tentativas de venda real (`sell_tries`, gravadas desde a 0.32.107).
Só mede: nada aqui decide compra ou venda.
"""
from __future__ import annotations

import statistics

MIN_PARES = 20


def _med(v: list) -> float | None:
    v = [x for x in v if x is not None]
    return round(statistics.median(v), 2) if v else None


def sells(trades: list[dict]) -> list[dict]:
    """Cada degrau da escada de venda: quantas vezes foi tentado, quantas entrou e quanto demorou."""
    g: dict[str, dict] = {}
    for t in trades:
        for x in t.get("sell_tries") or []:
            d = g.setdefault(str(x.get("via")), {"degrau": str(x.get("via")), "tentativas": 0, "entrou": 0, "pendente": 0, "ms": []})
            d["tentativas"] += 1
            d["entrou"] += x.get("res") == "entrou"
            d["pendente"] += x.get("res") == "pendente"
            d["ms"].append(x.get("ms"))
    out = []
    for d in g.values():
        ms = d.pop("ms")
        out.append({**d, "ms_mediano": _med(ms), "entrou_pct": round(d["entrou"] / d["tentativas"] * 100)})
    return sorted(out, key=lambda d: -d["tentativas"])


def summary(pairs: list[dict], real_trades: list[dict], sem_par: int = 0) -> dict:
    P = [x for x in pairs if x.get("sim_pct") is not None]
    dif = [x.get("dif_pct") for x in P]
    pior = sum(1 for x in P if (x.get("sim_sol") or 0) > 0 and (x.get("real_sol") or 0) <= 0)
    base = {"pares": len(P), "sem_par_48h": sem_par, "real_sol": round(sum(x.get("real_sol") or 0 for x in P), 6),
            "fict_sol": round(sum(x.get("sim_sol") or 0 for x in P), 6), "dif_mediana": _med(dif),
            "entrada_mediana": _med([x.get("entrada_pct") for x in P]), "saida_mediana": _med([x.get("saida_pct") for x in P]),
            "atraso_mediano_s": _med([x.get("atraso_s") for x in P]), "ganhou_fict_perdeu_real": pior, "vendas": sells(real_trades)}
    if len(P) < MIN_PARES:
        base["leitura"] = f"poucos dados: {len(P)} pares; a diferença vale a partir de {MIN_PARES}"
    else:
        base["leitura"] = f"a cada trade, a real ficou {base['dif_mediana']:+.1f} pontos da fictícia (mediana)"
    return base
