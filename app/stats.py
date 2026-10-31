"""Contas de incerteza dos estudos (0.32.107+, lote 12 conferido).

Resultado de memecoin tem cauda longa: poucos ganhos enormes decidem a média, e trades do mesmo dia andam juntos. Contar trades como
independentes faz um resultado nulo parecer forte. Por isso a faixa sorteia DIAS inteiros (bootstrap por grupo), não trades.
Sempre 95%. Só mede: nada aqui decide compra ou venda.
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timezone

MIN_GRUPOS = 5
REPS = 1000
SEED = 20261031


def day_of(t: float | str | None) -> str | None:
    try:
        if isinstance(t, str):
            return datetime.fromisoformat(t.replace("Z", "+00:00")).astimezone(timezone.utc).date().isoformat()
        return datetime.fromtimestamp(float(t), timezone.utc).date().isoformat()
    except (TypeError, ValueError, OSError):
        return None


def wilson(k: int, n: int, z: float = 1.95996398454) -> tuple[float, float] | None:
    if not n:
        return None
    p, d = k / n, 1 + z * z / n
    c, h = (p + z * z / (2 * n)) / d, z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round(max(0.0, c - h) * 100, 1), round(min(1.0, c + h) * 100, 1)


def ci_days(rows: list[tuple[str | None, float]], reps: int = REPS, seed: int = SEED) -> dict:
    """rows = [(dia, valor)]. Média, faixa de 95% sorteando dias inteiros, e média sem os 3 maiores valores."""
    rows = [(d, float(v)) for d, v in rows if d is not None and v is not None]
    vals = sorted(v for _, v in rows)
    g: dict[str, list[float]] = {}
    for d, v in rows:
        g.setdefault(d, []).append(v)
    out = {"n": len(rows), "dias": len(g), "media": round(sum(vals) / len(vals), 2) if vals else None, "lo": None, "hi": None,
           "sem_top3": round(sum(vals[:-3]) / len(vals[:-3]), 2) if len(vals) > 3 else None}
    if len(g) < MIN_GRUPOS:
        return out
    L, rng, means = list(g.values()), random.Random(seed), []
    for _ in range(reps):
        tot, n = 0.0, 0
        for _x in L:
            y = L[rng.randrange(len(L))]
            tot += sum(y)
            n += len(y)
        means.append(tot / n)
    means.sort()
    out["lo"], out["hi"] = round(means[int(reps * 0.025)], 2), round(means[int(reps * 0.975) - 1], 2)
    return out


def reading(ci: dict, nome: str, unidade: str = "pontos") -> str:
    """Frase para a tela. Nunca diz "melhor" sem a faixa inteira de um lado do zero."""
    if ci["lo"] is None:
        return f"poucos dados: {ci['n']} {nome} em {ci['dias']} dias; a faixa de confiança precisa de pelo menos {MIN_GRUPOS} dias"
    faixa = f"{ci['media']:+.1f} {unidade} (faixa de {ci['lo']:+.1f} a {ci['hi']:+.1f})"
    fim = f" Sem os 3 maiores: {ci['sem_top3']:+.1f}." if ci["sem_top3"] is not None else ""
    if ci["lo"] > 0:
        return f"melhor nos {ci['n']} {nome}: {faixa}.{fim}"
    if ci["hi"] < 0:
        return f"pior nos {ci['n']} {nome}: {faixa}.{fim}"
    return f"ainda não dá para concluir: {faixa}, em {ci['n']} {nome} e {ci['dias']} dias.{fim}"
