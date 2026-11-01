"""Relatório dos traders de uma aba (0.32.140, pedido do dono): quem se repete, em todo o tempo e nas últimas 24 h.

`tabela` serve à tela do Histórico. `build` monta o relatório guardado para a Base geral, com vereditos e lições. As lições são
contas e comparações, não uma IA. Só mede: nada aqui compra, vende ou pausa trader.
"""
from __future__ import annotations

import time

from . import stats
from .auto_trades import SUSPECT_PCT
from .resultstudy import ts
from .toplab import trader_verdict

JANELA_S = 86400
MIN_REP = 2
MIN_LICAO = 3


def _linha(w: str, L: list[dict], names: dict) -> dict:
    pnl = [float(t.get("pnl_sol") or 0) for t in L]
    saldo, inv = sum(pnl), sum(float(t.get("sol_in") or 0) for t in L)
    ganhos = sum(p > 0 for p in pnl)
    acerto = round(ganhos / len(L) * 100)
    ci = stats.ci_days([(stats.day_of(t.get("closed_at")), t.get("pnl_pct")) for t in L])
    o = sorted(L, key=lambda t: float(t.get("pnl_sol") or 0))
    return {"wallet": w, "nome": names.get(w), "trades": len(L), "ganhos": ganhos, "perdas": len(L) - ganhos, "acerto": acerto, "saldo_sol": round(saldo, 6), "investido_sol": round(inv, 6),
            "pct": round(saldo / inv * 100, 2) if inv else None, "dias": ci["dias"], "lo": ci["lo"], "hi": ci["hi"], "veredito": trader_verdict(ci, len(L), acerto, saldo),
            "melhor": {"symbol": o[-1].get("symbol"), "sol": o[-1].get("pnl_sol")}, "pior": {"symbol": o[0].get("symbol"), "sol": o[0].get("pnl_sol")}}


def linhas(L: list[dict], names: dict) -> list[dict]:
    g: dict[str, list] = {}
    for t in L:
        w = t.get("wallet")
        if w and w != "manual":
            g.setdefault(w, []).append(t)
    return sorted((_linha(w, R, names) for w, R in g.items()), key=lambda x: (-x["trades"], -x["saldo_sol"]))


def tabela(trades: list[dict], aba: str, aba_of, real: bool, names: dict, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    L = [t for t in trades if bool(t.get("real")) == real and aba_of(t) == aba and float(t.get("pnl_pct") or 0) < SUSPECT_PCT]
    return {"todo": linhas(L, names), "h24": linhas([t for t in L if (ts(t) or 0) > now - JANELA_S], names)}


def _nome(x: dict) -> str:
    return x.get("nome") or f"{x['wallet'][:4]}…{x['wallet'][-4:]}"


def licoes(todo: list[dict], h24: list[dict]) -> list[str]:
    L: list[str] = []
    if not todo:
        return ["Nenhum trader com trade fechado nesta aba."]
    lucro = sum(x["saldo_sol"] for x in todo if x["saldo_sol"] > 0)
    top = sorted(todo, key=lambda x: -x["saldo_sol"])
    if lucro > 0 and top[0]["saldo_sol"] > 0:
        pct = top[0]["saldo_sol"] / lucro * 100
        if pct >= 50:
            L.append(f"{_nome(top[0])} responde por {pct:.0f}% do lucro: o resultado depende muito de uma carteira só.")
    for x in todo:
        if x["veredito"] == "provado":
            L.append(f"{_nome(x)} está provado: {x['trades']} trades em {x['dias']} dias, com a faixa de confiança acima de zero.")
        elif x["veredito"] == "ruim":
            L.append(f"{_nome(x)} vai mal: {x['trades']} trades, acerto de {x['acerto']}%, {x['saldo_sol']:+.4f} SOL. Vale avaliar a pausa.")
    d = {x["wallet"]: x for x in h24}
    for x in todo:
        y = d.get(x["wallet"])
        if y and y["trades"] >= MIN_LICAO and x["saldo_sol"] > 0 > y["saldo_sol"]:
            L.append(f"{_nome(x)} é positivo no total, mas perdeu nas últimas 24 h: {y['saldo_sol']:+.4f} SOL em {y['trades']} trades.")
    if sum(1 for x in todo if x["dias"] >= stats.MIN_GRUPOS) == 0:
        L.append(f"Nenhum trader tem {stats.MIN_GRUPOS} dias de trades ainda: use como pista, não como conclusão.")
    return L


def build(trades: list[dict], aba: str, aba_of, real: bool, names: dict, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    T = tabela(trades, aba, aba_of, real, names, now)
    soma = lambda K: {"traders": len(K), "trades": sum(x["trades"] for x in K), "saldo_sol": round(sum(x["saldo_sol"] for x in K), 6), "investido_sol": round(sum(x["investido_sol"] for x in K), 6)}
    return {"aba": aba, "real": real, "em": now, **T, "total": soma(T["todo"]), "total24": soma(T["h24"]), "licoes": licoes(T["todo"], T["h24"])}


def learn(rows: list[dict]) -> list[dict]:
    """Junta o relatório mais recente de cada conta e aba. `rows` vem do mais novo para o mais antigo."""
    vistos, g = set(), {}
    for r in rows:
        chave = (r.get("user_id"), (r.get("data") or {}).get("aba"))
        if chave in vistos:
            continue
        vistos.add(chave)
        for x in (r.get("data") or {}).get("todo") or []:
            d = g.setdefault(x["wallet"], {"wallet": x["wallet"], "nome": None, "contas": 0, "trades": 0, "ganhos": 0, "saldo_sol": 0.0, "vereditos": {}})
            d["nome"] = d["nome"] or x.get("nome")
            d["contas"] += 1
            d["trades"] += x["trades"]
            d["ganhos"] += x["ganhos"]
            d["saldo_sol"] += x["saldo_sol"]
            d["vereditos"][x["veredito"]] = d["vereditos"].get(x["veredito"], 0) + 1
    out = [{**d, "acerto": round(d["ganhos"] / d["trades"] * 100) if d["trades"] else 0, "saldo_sol": round(d["saldo_sol"], 6)} for d in g.values()]
    return sorted(out, key=lambda x: -x["saldo_sol"])
