"""Dia frio ou normal na pump.fun (0.32.116, lote 12 conferido). Fonte: pumpdata.fun, não a pump.fun.

Frio = criações E volume abaixo da mediana dos 14 dias anteriores, com pelo menos 10 dias válidos. Critério do lote 12, definido antes
de olhar os dados. Só existe depois que o dia fecha, então nunca serve de filtro de entrada: só para estudar o resultado depois.
Os termos da fonte pedem citar o nome dela onde o dado aparece, e não copiar a base em volume: aqui ficam só 3 números por dia.
"""
from __future__ import annotations

import statistics
import time

URL = "https://pumpdata.fun/stats/{}.json"
MIN_COB = 0.95
JANELA = 14
MIN_ANT = 10
DIAS = 35


def parse(js: dict) -> dict | None:
    t = (js or {}).get("totals") or {}
    if t.get("launched") is None or t.get("volume_sol") is None:
        return None
    cob = ((js or {}).get("coverage") or {}).get("pct")
    return {"criacoes": int(t["launched"]), "volume_sol": float(t["volume_sol"]), "cobertura": cob,
            "ok": not ((js or {}).get("checks") or {}).get("failed") and (cob is None or float(cob) >= MIN_COB)}


def classify(days: dict[str, dict]) -> dict[str, str]:
    """{dia: "frio" | "normal" | "sem dado"}. Dia sem qualidade ou sem histórico nunca vira frio por chute."""
    out: dict[str, str] = {}
    for d in sorted(days):
        x = days[d]
        base = time.mktime(time.strptime(d, "%Y-%m-%d"))
        prev = [days.get(time.strftime("%Y-%m-%d", time.localtime(base - i * 86400 + 7200))) for i in range(1, JANELA + 1)]
        ant = [p for p in prev if p and p.get("ok")]
        if not x.get("ok") or len(ant) < MIN_ANT:
            out[d] = "sem dado"
            continue
        frio = x["criacoes"] < statistics.median(p["criacoes"] for p in ant) and x["volume_sol"] < statistics.median(p["volume_sol"] for p in ant)
        out[d] = "frio" if frio else "normal"
    return out
