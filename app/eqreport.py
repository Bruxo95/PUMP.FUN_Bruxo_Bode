"""Relatório do Copiar igual a cada 6 h (0.32.73, pedido do dono: "relatório de ganhos e perdas a cada 6 h com todas as
informações de trade, compra etc., e usar na Base geral também").

Por carteira copiada: compras vistas, copiadas e o motivo das que não foram, operações fechadas, acerto, resultado, fator,
melhor e pior operação, tempo médio e o veredito (manter / parar / observar). Mais a lista de cada operação das 6 h e as
posições abertas. `learn` junta os relatórios guardados para a Base geral (quais carteiras dão lucro de forma repetida).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from .tabreport import _group, _ts, loss_cause, trade_verdict

EVERY_S = 6 * 3600
MIN_N = 5                       # operações fechadas para dar veredito de carteira


def wallet_verdict(g: dict) -> tuple[str, str]:
    if g["n"] < MIN_N:
        return "poucos dados", f"{g['n']} operação(ões) fechada(s); o veredito sai com {MIN_N}"
    if g["pnl_sol"] > 0 and (g["acerto"] or 0) >= 45:
        return "manter", f"{g['acerto']}% de acerto e {g['pnl_sol']:+.4f} SOL"
    if g["pnl_sol"] < 0 and (g["acerto"] or 0) < 40:
        return "parar", f"perde: {g['acerto']}% de acerto e {g['pnl_sol']:+.4f} SOL"
    return "observar", f"{g['acerto']}% de acerto e {g['pnl_sol']:+.4f} SOL: ainda não dá para dizer"


def _short(w: str) -> str:
    return f"{w[:4]}…{w[-4:]}" if w and len(w) > 10 else (w or "?")


def build(trades: list[dict], positions: list[dict], diag: list, wallets: list[str], modes: dict, now: float,
          real: bool = False, window_s: float = EVERY_S) -> dict:
    tr = [t for t in trades if t.get("eq") and bool(t.get("real")) == real]
    win = [t for t in tr if now - _ts(t.get("closed_at")) <= window_s]
    d = [x for x in diag or [] if now - x[0] <= window_s]
    ws = list(dict.fromkeys(list(wallets) + [t.get("wallet") for t in win]))
    rows = []
    for w in ws:
        mine = [t for t in win if t.get("wallet") == w]
        seen = [x for x in d if x[1] == w]
        nao: dict[str, list] = {}
        for x in seen:
            if x[2] != "copiou":
                k = re.sub(r"[-+]?\d+(?:[.,]\d+)?", "#", x[2])[:90]
                nao.setdefault(k, [0, x[2]])[0] += 1
        g = _group(mine)
        v, why = wallet_verdict(g)
        best = max(mine, key=lambda t: t.get("pnl_sol") or 0, default=None)
        worst = min(mine, key=lambda t: t.get("pnl_sol") or 0, default=None)
        holds = [t.get("hold_s") for t in mine if t.get("hold_s") is not None]
        rows.append({"wallet": w, "modo": (modes or {}).get(w, "off"), "vistas": len(seen),
                     "copiadas": sum(1 for x in seen if x[2] == "copiou"),
                     "nao_copiou": sorted(({"motivo": v_[1], "n": v_[0]} for v_ in nao.values()), key=lambda m: -m["n"])[:3],
                     **g, "veredito": v, "por_que": why,
                     "melhor": {"symbol": best.get("symbol"), "pnl_sol": best.get("pnl_sol"), "pnl_pct": best.get("pnl_pct")} if best else None,
                     "pior": {"symbol": worst.get("symbol"), "pnl_sol": worst.get("pnl_sol"), "pnl_pct": worst.get("pnl_pct")} if worst else None,
                     "tempo_medio_s": round(sum(holds) / len(holds)) if holds else None,
                     "abertas": sum(1 for p in positions if p.get("eq") and p.get("wallet") == w and bool(p.get("real")) == real)})
    rows.sort(key=lambda r: (r["n"] == 0 and r["vistas"] == 0, -(r["pnl_sol"] or 0)))
    ops = [{"carteira": _short(t.get("wallet")), "wallet": t.get("wallet"), "symbol": t.get("symbol"), "mint": t.get("mint"),
            "abriu": t.get("opened_at"), "fechou": t.get("closed_at"), "investido": t.get("sol_in"), "recebeu": t.get("sol_out"),
            "pnl_sol": t.get("pnl_sol"), "pnl_pct": t.get("pnl_pct"), "pico_pct": t.get("best_pct"), "hold_s": t.get("hold_s"),
            "saida": t.get("reason"), "veredito": trade_verdict(t),
            "causa": None if (t.get("pnl_sol") or 0) > 0 else loss_cause(t)} for t in sorted(win, key=lambda t: _ts(t.get("closed_at")), reverse=True)]
    abertas = [{"carteira": _short(p.get("wallet")), "wallet": p.get("wallet"), "symbol": p.get("symbol"), "mint": p.get("mint"),
                "abriu": p.get("opened_at"), "investido": p.get("sol_in"), "agora_pct": p.get("chg_pct")}
               for p in positions if p.get("eq") and bool(p.get("real")) == real]
    tot = _group(win)
    causas: dict[str, dict] = {}
    for t in win:
        if (t.get("pnl_sol") or 0) < 0:
            c = causas.setdefault(loss_cause(t), {"n": 0, "sol": 0.0})
            c["n"] += 1
            c["sol"] = round(c["sol"] - (t.get("pnl_sol") or 0), 5)
    vistas = len(d)
    if not vistas:
        geral = ("sem dados", "nenhuma compra das carteiras foi vista nas últimas 6 h (monitor fora ou nenhuma carteira marcada para copiar)")
    elif tot["n"] < 3:
        geral = ("poucos dados", f"{vistas} compras vistas e {tot['n']} operação(ões) fechada(s) em 6 h")
    elif tot["pnl_sol"] > 0:
        geral = ("ganhando", f"{tot['pnl_sol']:+.4f} SOL e {tot['acerto']}% de acerto em 6 h")
    else:
        geral = ("perdendo", f"{tot['pnl_sol']:+.4f} SOL e {tot['acerto']}% de acerto em 6 h")
    return {"t": now, "em": datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="seconds"), "real": real,
            "horas": round(window_s / 3600, 1), "total": tot, "vistas": vistas, "copiadas": sum(1 for x in d if x[2] == "copiou"),
            "veredito": geral[0], "por_que": geral[1], "causas": causas, "carteiras": rows, "operacoes": ops[:300], "abertas": abertas}


def learn(reports: list[dict]) -> dict:
    """Base geral: soma os relatórios guardados por carteira (quem dá lucro em vários períodos seguidos)."""
    by: dict[str, dict] = {}
    for r in reports:
        for c in r.get("carteiras") or []:
            if not c.get("n"):
                continue
            b = by.setdefault(c["wallet"], {"wallet": c["wallet"], "periodos": 0, "positivos": 0, "n": 0, "ganhos": 0, "pnl_sol": 0.0})
            b["periodos"] += 1
            b["positivos"] += 1 if (c.get("pnl_sol") or 0) > 0 else 0
            b["n"] += c["n"]
            b["ganhos"] += c.get("ganhos") or 0
            b["pnl_sol"] = round(b["pnl_sol"] + (c.get("pnl_sol") or 0), 5)
    rows = []
    for b in by.values():
        b["acerto"] = round(b["ganhos"] / b["n"] * 100) if b["n"] else None
        b["veredito"] = ("manter" if b["periodos"] >= 2 and b["positivos"] / b["periodos"] >= 0.6 and b["pnl_sol"] > 0
                         else "parar" if b["periodos"] >= 2 and b["pnl_sol"] < 0 and (b["acerto"] or 0) < 40 else "observar")
        rows.append(b)
    rows.sort(key=lambda b: -b["pnl_sol"])
    return {"relatorios": len(reports), "carteiras": rows,
            "pnl_sol": round(sum(b["pnl_sol"] for b in rows), 5), "n": sum(b["n"] for b in rows)}
