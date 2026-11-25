"""Períodos do BOOST (0.32.459, pedido do dono em 2026-11-25): cada dia é um período numerado (01, 02, 03…), contado a partir do
primeiro trade fechado do BOOST. O período fecha à meia-noite (horário de Berlim, o mesmo dos outros relatórios) e fica no histórico.
Nada é guardado à parte: os períodos saem dos trades fechados da conta, que já ficam no banco, então o histórico não se perde.
Só mede: nada aqui compra, vende ou muda configuração.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

from .auto_trades import SUSPECT_PCT
from .daily import TZ
from .resultstudy import ts

ABA = "BOOST da migração"
MAX_PERIODOS = 120


def _dia(t: float):
    return datetime.fromtimestamp(t, TZ).date()


def _t0(d) -> float:
    return datetime(d.year, d.month, d.day, tzinfo=TZ).timestamp()


def _open(t: dict) -> float | None:
    try:
        return datetime.fromisoformat(str(t.get("opened_at")).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def build(trades: list[dict], aba_of, now: float | None = None) -> dict:
    """`trades` = todos os trades fechados de UMA carteira (fictícia ou real) da conta. Devolve os períodos do mais novo para o mais
    antigo. `antes_sol` = resultado de todos os trades (qualquer aba) fechados antes do período: serve para a carteira inicial."""
    now = time.time() if now is None else now
    todos = []
    for t in trades:
        c = ts(t)
        if c is None or float(t.get("pnl_pct") or 0) >= SUSPECT_PCT:         # ganho falso (preço errado) fica fora
            continue
        todos.append((c, t))
    todos.sort(key=lambda x: x[0])
    boost = [(c, t) for c, t in todos if aba_of(t) == ABA]
    if not boost:
        return {"periodos": [], "atual": None, "total_sol": round(sum(float(t.get("pnl_sol") or 0) for _, t in todos), 6), "tz": "Berlim"}
    d0, d1 = _dia(boost[0][0]), _dia(now)
    n_dias = (d1 - d0).days + 1
    por_dia: dict = {}
    for c, t in boost:
        por_dia.setdefault(_dia(c), []).append((c, t))
    out = []
    for i in range(n_dias):
        d = d0 + timedelta(days=i)
        ini, fim = _t0(d), _t0(d + timedelta(days=1))
        L = por_dia.get(d, [])
        if i == 0 and L:                                                     # o período 01 começa na abertura do primeiro trade
            o = _open(L[0][1])
            if o is not None and o < ini + 86400:
                ini = min(o, L[0][0])
        antes = sum(float(t.get("pnl_sol") or 0) for c, t in todos if c < _t0(d))
        g = [float(t.get("pnl_sol") or 0) for _, t in L]
        pcts = [float(t.get("pnl_pct") or 0) for _, t in L]
        inv = sum(float(t.get("sol_in") or 0) for _, t in L)
        ganhos = [p for p, s in zip(pcts, g) if s > 0]
        perdas = [p for p, s in zip(pcts, g) if s <= 0]
        cum, serie = 0.0, []
        for (c, _t), s in zip(L, g):
            cum += s
            serie.append([round(c, 1), round(cum, 6)])
        lista = [{"symbol": t.get("symbol"), "mint": t.get("mint"), "pnl_sol": round(s, 6), "pnl_pct": round(p, 2), "closed": c,
                  "reason": str(t.get("reason") or "")[:90]} for (c, t), s, p in zip(L, g, pcts)]
        mel = max(L, key=lambda x: float(x[1].get("pnl_sol") or 0))[1] if L else None
        pio = min(L, key=lambda x: float(x[1].get("pnl_sol") or 0))[1] if L else None
        out.append({
            "n": i + 1, "rotulo": f"{i + 1:02d}", "dia": d.isoformat(), "ini": ini, "fim": fim, "fechado": now >= fim,
            "trades": len(L), "ganhos": len(ganhos), "perdas": len(perdas),
            "acerto": round(len(ganhos) / len(L) * 100) if L else None,
            "saldo_sol": round(sum(g), 6), "investido_sol": round(inv, 6),
            "pct_sobre_investido": round(sum(g) / inv * 100, 2) if inv else None,
            "pct_ganhos_soma": round(sum(ganhos), 2), "pct_perdas_soma": round(sum(perdas), 2),
            "ganhos_sol": round(sum(x for x in g if x > 0), 6), "perdas_sol": round(sum(x for x in g if x <= 0), 6),
            "melhor": {"symbol": mel.get("symbol"), "sol": mel.get("pnl_sol"), "pct": mel.get("pnl_pct")} if mel else None,
            "pior": {"symbol": pio.get("symbol"), "sol": pio.get("pnl_sol"), "pct": pio.get("pnl_pct")} if pio else None,
            "antes_sol": round(antes, 6), "serie": serie, "lista": lista[-60:],
        })
    out.reverse()
    return {"periodos": out[:MAX_PERIODOS], "atual": out[0]["n"], "total_sol": round(sum(float(t.get("pnl_sol") or 0) for _, t in todos), 6),
            "tz": "Berlim"}
