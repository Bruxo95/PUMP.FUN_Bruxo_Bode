"""Regra dos detentores, ideia do Bruxo (0.32.86, áudio de 30/10): moeda que dá pump de verdade já começa com uns 40
detentores e eles continuam entrando minuto a minuto; moeda em que ninguém entra não sobe.

Só MEDE (nada é comprado): usa as leituras de detentores dos sinais da Aba do Bruxo. Moeda com 40+ detentores é lida a
cada minuto até os 10 min (`Bruxo.holders_due`). A regra liga na 1ª leitura com o mínimo de detentores e duas altas seguidas.
A entrada simulada é no preço DAQUELA leitura, nunca no preço do sinal: entrar antes de saber seria usar o futuro.
"""
from __future__ import annotations

import statistics

from .auto_trades import SUSPECT_PCT
from .jev import FEE_PCT, real_cost_pct, sim_result, with_real_cost

MIN_HOLDERS = 40
MIN_GROW_PCT = 10
MAX_ENTRY_MIN = 10
FAIXAS = ((0, 20, "menos de 20"), (20, 40, "20 a 39"), (40, 80, "40 a 79"), (80, 10 ** 9, "80 ou mais"))
EVOLUCAO = ("caiu ou parou", "subiu até 50%", "subiu mais de 50%")


def readings(s: dict) -> list[tuple[int, int]]:
    return sorted((int(k), int(v)) for k, v in (s.get("holders") or {}).items() if v is not None)


def entry(s: dict, min_h: int = MIN_HOLDERS, grow_pct: float = MIN_GROW_PCT) -> int | None:
    """Minuto em que a regra ligou: mínimo de detentores + duas altas seguidas + crescimento nas 3 últimas leituras."""
    R = readings(s)
    for i in range(2, len(R)):
        m, h = R[i]
        if m > MAX_ENTRY_MIN:
            break
        a, b = R[i - 2][1], R[i - 1][1]
        if h >= min_h and a < b < h and (h - a) * 100 >= grow_pct * max(a, 1):
            return m
    return None


def _points(s: dict) -> dict[int, float]:
    """Preço (% sobre o preço do sinal) em cada minuto conhecido."""
    pts = {int(k): float(v) for src in ("marks", "hpx") for k, v in (s.get(src) or {}).items() if v is not None}
    pts.setdefault(0, 0.0)
    return pts


def result(s: dict, m: int, saida: str, stop_pct: float = 30.0) -> tuple[float | None, bool]:
    """(resultado %, dobrou?) de entrar no minuto `m` e sair em `saida` (aos 25 min, se `saida` não vem depois da entrada)."""
    pts = _points(s)
    ex = int(saida) if int(saida) > m else 25
    if m not in pts or ex not in pts or pts[m] <= -100:
        return None, False
    rel = lambda v: ((1 + v / 100) / (1 + pts[m] / 100) - 1) * 100
    path = [rel(v) for k, v in sorted(pts.items()) if m < k <= ex]
    pk = s.get("peak_pct")
    dob = any(v >= 100 for v in path) or (pk is not None and (s.get("peak_s") or 0) > m * 60 and rel(pk) >= 100)
    if any(v <= -stop_pct for v in path):
        return round(-stop_pct - FEE_PCT, 2), dob
    return round(rel(pts[ex]) - FEE_PCT, 2), dob


def _group(rows: list[tuple[float | None, bool, float | None]], sol: float) -> dict:
    res = [r for r, _, _ in rows if r is not None]
    pk = [p for _, _, p in rows if p is not None]
    return {"n": len(rows), "medidos": len(res), "subiu": sum(r > 0 for r in res), "dobrou": sum(1 for _, d, _ in rows if d),
            "acerto": round(sum(r > 0 for r in res) / len(res) * 100) if res else None,
            "media_pct": round(sum(res) / len(res), 2) if res else None, "sol": round(sum(res) * sol / 100, 5),
            "sol_real": with_real_cost(round(sum(res) * sol / 100, 5), len(res), sol),
            "pico_mediano": round(statistics.median(pk), 1) if pk else None}


def _detail(rows: list[dict], sol: float, max_itens: int = 300) -> dict:
    """A conta de um cartão, token por token. O total sozinho engana: poucos ganhos enormes escondem muitas perdas,
    então mostra também a mediana e o resultado sem os 3 maiores (0.32.88, pedido do dono)."""
    med = sorted((x for x in rows if x["res"] is not None), key=lambda x: -x["res"])
    res = [x["res"] for x in med]
    rest = res[3:]
    return {"n": len(rows), "medidos": len(med), "ganhos_sol": round(sum(r for r in res if r > 0) * sol / 100, 5),
            "perdas_sol": round(sum(r for r in res if r < 0) * sol / 100, 5), "mediana_pct": round(statistics.median(res), 2) if res else None,
            "top3_sol": round(sum(res[:3]) * sol / 100, 5), "sem_top3_sol": round(sum(rest) * sol / 100, 5),
            "sem_top3_media": round(sum(rest) / len(rest), 2) if rest else None, "suspeitos": sum(r >= SUSPECT_PCT for r in res),
            "sol": sol, "itens": (med + [x for x in rows if x["res"] is None])[:max_itens]}


def study(signals: list[dict], saida: str = "10", min_h: int = MIN_HOLDERS, grow_pct: float = MIN_GROW_PCT, sol: float = 0.1,
          show: int = 0) -> dict:
    sigs = sorted(signals, key=lambda s: s["t"])
    with_h = [s for s in sigs if readings(s)]
    regra, combo, todos, linhas, curva = [], [], [], [], []
    det: dict[str, list] = {"regra": [], "todos": [], "regra_jev": []}
    faixas: dict[str, list] = {f[2]: [] for f in FAIXAS}
    evol: dict[str, list] = {k: [] for k in EVOLUCAO}
    acc = 0.0
    for s in with_h:
        R = readings(s)
        base = (sim_result(s, saida), s.get("hit100_s") is not None, s.get("peak_pct"))
        todos.append(base)
        meta = {"t": s["t"], "mint": s.get("mint"), "symbol": s.get("symbol"), "pico": s.get("peak_pct")}
        det["todos"].append({**meta, "res": base[0], "ligou": None})
        next(faixas[nome] for lo, hi, nome in FAIXAS if lo <= R[0][1] < hi).append(base)
        h5 = (s.get("holders") or {}).get("5")
        if R[0][0] <= 1 and h5 is not None:
            d = (h5 / R[0][1] - 1) * 100 if R[0][1] else (100 if h5 else 0)
            r5, d5 = result(s, 5, saida)
            evol[EVOLUCAO[0] if d <= 0 else EVOLUCAO[1] if d <= 50 else EVOLUCAO[2]].append((r5, d5, s.get("peak_pct")))
        m = entry(s, min_h, grow_pct)
        r = None
        if m is not None:
            r, dob = result(s, m, saida)
            regra.append((r, dob, s.get("peak_pct")))
            det["regra"].append({**meta, "res": r, "ligou": m})
            if (s.get("jev") or {}).get("acao") == "entrar":
                combo.append((r, dob, s.get("peak_pct")))
                det["regra_jev"].append({**meta, "res": r, "ligou": m})
            if r is not None:
                acc += sol * r / 100
                curva.append([s["t"] + m * 60, round(acc, 5)])
        if max(h for _, h in R) >= show:               # 0.32.103: o filtro vem antes do corte das 200 linhas
            fl = s.get("flow") or {}
            linhas.append({"t": s["t"], "mint": s.get("mint"), "symbol": s.get("symbol"), "kind": s.get("kind", "trader"), "evol": R,
                           "ligou": m, "res": r, "pico": s.get("peak_pct"), "jev": (s.get("jev") or {}).get("acao"),
                           "h0": R[0][1], "h": R[-1][1], "h_t": s["t"] + R[-1][0] * 60,
                           "cresc_pct": round((R[-1][1] / R[0][1] - 1) * 100, 1) if R[0][1] else None,
                           "mc0": s.get("mcap0") if s.get("mcap0") is not None else fl.get("mcap"), "px0": s.get("px0"),
                           "top10": s.get("top10"), "dev_pct": s.get("dev_pct") if s.get("dev_pct") is not None else fl.get("dev_pct")})
    g_regra, g_todos = _group(regra, sol), _group(todos, sol)
    if g_regra["medidos"] < 20:
        leitura = f"poucos dados: {g_regra['medidos']} entradas medidas; a comparação vale a partir de 20"
    elif g_regra["media_pct"] > (g_todos["media_pct"] or 0):
        leitura = f"a regra está melhor: média {g_regra['media_pct']:+.1f}% por entrada contra {g_todos['media_pct'] or 0:+.1f}% de todos os sinais"
    else:
        leitura = f"a regra não está ajudando: média {g_regra['media_pct']:+.1f}% por entrada contra {g_todos['media_pct'] or 0:+.1f}% de todos os sinais"
    linhas.sort(key=lambda x: (x["ligou"] is None, -x["t"]))
    return {"min_h": min_h, "cresc_pct": grow_pct, "saida_min": saida, "sinais": len(sigs), "medidos": len(with_h),
            "sem_dados": len(sigs) - len(with_h), "custo_real_pct": real_cost_pct(sol), "show": show, "mostrando": len(linhas), "regra": {**g_regra, "curva": curva}, "todos": g_todos, "regra_jev": _group(combo, sol),
            "faixas": [{"faixa": k, **_group(v, sol)} for k, v in faixas.items() if v],
            "evolucao": [{"faixa": k, **_group(v, sol)} for k, v in evol.items() if v], "leitura": leitura, "linhas": linhas[:200],
            "detalhe": {k: _detail(v, sol) for k, v in det.items()}}
