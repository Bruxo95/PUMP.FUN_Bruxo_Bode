"""Estudo do resultado por período (0.32.114, pedido do dono): de onde veio o ganho ou a perda das últimas horas.

`build` monta o estudo de uma janela: por aba, por motivo de saída, por tempo de posição, melhores, piores e lições. As lições são
contas e comparações, não uma IA. `learn` soma os estudos diários de todas as contas para a Base geral. Só os dias fechados entram
no aprendizado, porque as janelas de 1/6/12/24 h se sobrepõem e contariam o mesmo trade várias vezes.

Só mede: nada aqui muda filtro, compra ou venda.
"""
from __future__ import annotations

import re
from datetime import datetime

from .auto_trades import SUSPECT_PCT

MIN_LICAO = 5           # trades para uma aba ou um motivo virar lição
MIN_AMOSTRA = 20
MIN_DIAS = 5
TEMPOS = ((300, "até 5 min"), (1800, "5 a 30 min"), (7200, "30 min a 2 h"), (10 ** 12, "mais de 2 h"))


def ts(t: dict) -> float | None:
    try:
        return datetime.fromisoformat(str(t.get("closed_at")).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def motivo(r) -> str:
    """Agrupa "stop móvel (pico +36.6% → saiu em +1.5%)" e "stop de +20%" sem os números de cada trade."""
    txt = str(r or "sem motivo").split("(")[0]
    txt = re.sub(r"[+\-−]?\d+[\d.,]*\s*(%|min|h|s)?", " ", txt)
    return re.sub(r"\s+", " ", txt).strip(" :·-")[:48] or "sem motivo"


def _group(rows: list[tuple[str, dict]]) -> list[dict]:
    g: dict[str, dict] = {}
    for nome, t in rows:
        d = g.setdefault(nome, {"nome": nome, "n": 0, "ganhos": 0, "sol": 0.0, "pct": 0.0})
        d["n"] += 1
        d["ganhos"] += float(t.get("pnl_sol") or 0) > 0
        d["sol"] += float(t.get("pnl_sol") or 0)
        d["pct"] += float(t.get("pnl_pct") or 0)
    out = [{"nome": d["nome"], "n": d["n"], "ganhos": d["ganhos"], "acerto": round(d["ganhos"] / d["n"] * 100), "sol": round(d["sol"], 6),
            "media_pct": round(d["pct"] / d["n"], 2)} for d in g.values()]
    return sorted(out, key=lambda x: x["sol"])


def _item(t: dict, aba: str) -> dict:
    return {"symbol": t.get("symbol"), "mint": t.get("mint"), "aba": aba, "sol": t.get("pnl_sol"), "pct": t.get("pnl_pct"), "motivo": t.get("reason"), "closed_at": t.get("closed_at")}


def _licoes(E: dict) -> list[str]:
    L: list[str] = []
    if E["trades"] < MIN_AMOSTRA:
        L.append(f"Poucos trades ({E['trades']}): use como pista, não como conclusão.")
    if E["trades"] and E["ganhos"] and E["perdas"]:
        g, p = E["ganhos_sol"] / E["ganhos"], -E["perdas_sol"] / E["perdas"]
        if g + p > 0:
            E["acerto_empate"] = round(p / (g + p) * 100)
            falta = "acima" if E["acerto"] >= E["acerto_empate"] else "abaixo"
            L.append(f"Ganho médio de {g:.4f} SOL e perda média de {p:.4f} SOL: para empatar precisa de {E['acerto_empate']}% de acerto. Ficou em {E['acerto']}%, {falta} disso.")
    for chave, nome in (("por_aba", "A aba"), ("por_motivo", "A saída"), ("por_tempo", "Posições de")):
        G = [x for x in E[chave] if x["n"] >= MIN_LICAO]
        if G and G[0]["sol"] < 0:
            L.append(f"{nome} \"{G[0]['nome']}\" foi o que mais perdeu: {G[0]['sol']:+.4f} SOL em {G[0]['n']} trades, acerto de {G[0]['acerto']}%.")
        if G and G[-1]["sol"] > 0 and G[-1] is not G[0]:
            L.append(f"{nome} \"{G[-1]['nome']}\" foi o que mais ganhou: {G[-1]['sol']:+.4f} SOL em {G[-1]['n']} trades.")
    if E["suspeitos"]:
        L.append(f"{E['suspeitos']} ganho(s) acima de 20× ficaram fora dos grupos: confira se o preço era verdadeiro.")
    return L


def build(trades: list[dict], start: float, end: float, real: bool, aba_of, horas: float | None = None) -> dict:
    T = [t for t in trades if bool(t.get("real")) == real and (x := ts(t)) is not None and start < x <= end]
    pnl = [float(t.get("pnl_sol") or 0) for t in T]
    good = [t for t in T if float(t.get("pnl_pct") or 0) < SUSPECT_PCT]
    E = {"inicio": start, "fim": end, "horas": horas, "real": real, "trades": len(T), "ganhos": sum(p > 0 for p in pnl), "perdas": sum(p <= 0 for p in pnl),
         "acerto": round(sum(p > 0 for p in pnl) / len(T) * 100) if T else 0, "ganhos_sol": round(sum(p for p in pnl if p > 0), 6),
         "perdas_sol": round(sum(p for p in pnl if p <= 0), 6), "saldo_sol": round(sum(pnl), 6),
         "investido_sol": round(sum(float(t.get("sol_in") or 0) for t in T), 6), "suspeitos": len(T) - len(good),
         "por_aba": _group([(aba_of(t), t) for t in good]), "por_motivo": _group([(motivo(t.get("reason")), t) for t in good]),
         "por_tempo": _group([(next(n for lim, n in TEMPOS if float(t.get("hold_s") or 0) <= lim), t) for t in good])}
    E["retorno_pct"] = round(E["saldo_sol"] / E["investido_sol"] * 100, 2) if E["investido_sol"] else None
    ord_ = sorted(T, key=lambda t: float(t.get("pnl_sol") or 0))
    E["piores"] = [_item(t, aba_of(t)) for t in ord_[:5] if float(t.get("pnl_sol") or 0) < 0]
    E["melhores"] = [_item(t, aba_of(t)) for t in ord_[::-1][:5] if float(t.get("pnl_sol") or 0) > 0]
    E["licoes"] = _licoes(E)
    return E


def learn(rows: list[dict]) -> dict:
    """Soma os estudos de dias fechados. `rows`: [{"dia", "data"}], uma linha por conta e dia."""
    dias = {r.get("dia") for r in rows}
    out: dict[str, dict] = {}
    for chave in ("por_aba", "por_motivo", "por_tempo"):
        g: dict[str, dict] = {}
        for r in rows:
            for x in (r.get("data") or {}).get(chave) or []:
                d = g.setdefault(x["nome"], {"nome": x["nome"], "n": 0, "ganhos": 0, "sol": 0.0, "pond": 0.0, "dias": {}})
                d["n"] += x["n"]
                d["ganhos"] += x["ganhos"]
                d["sol"] += x["sol"]
                d["pond"] += x["media_pct"] * x["n"]
                d["dias"][r.get("dia")] = d["dias"].get(r.get("dia"), 0.0) + x["sol"]
        L = []
        for d in g.values():
            pos = sum(v > 0 for v in d["dias"].values())
            nd = len(d["dias"])
            vd = "poucos dias" if nd < MIN_DIAS else "lucro repetido" if pos / nd >= 0.6 and d["sol"] > 0 else "perda repetida" if pos / nd <= 0.4 and d["sol"] < 0 else "misto"
            L.append({"nome": d["nome"], "n": d["n"], "acerto": round(d["ganhos"] / d["n"] * 100) if d["n"] else 0, "sol": round(d["sol"], 6),
                      "media_pct": round(d["pond"] / d["n"], 2) if d["n"] else None, "dias": nd, "dias_positivos": pos, "veredito": vd})
        out[chave] = sorted(L, key=lambda x: x["sol"])
    return {"dias": len(dias), "estudos": len(rows), "trades": sum(int((r.get("data") or {}).get("trades") or 0) for r in rows),
            "saldo_sol": round(sum(float((r.get("data") or {}).get("saldo_sol") or 0) for r in rows), 6), **out}
