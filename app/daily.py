"""Relatório do dia (0.31.5, pedido do dono em 2026-10-26: "salvar o que está na Visão geral, aprender, e no fim do
dia sugerir o que melhorar no código, nos trades e na lógica").

- A cada 30 min guarda uma foto dos números da Visão geral (saldo, resultado, posições, trades, acerto, traders,
  monitor) na tabela daily_report (uma linha por usuário por dia, com as fotos do dia).
- O relatório olha os trades do dia (e o histórico) e devolve diagnósticos e sugestões com número e base mínima.
  Nada é aplicado sozinho: as sugestões dizem o que mudar e onde.
- Na virada do dia (UTC) o relatório do dia anterior fica fechado e, com o Telegram ligado, vai um resumo.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone

MAX_POINTS = 60


def _ts(x) -> float | None:
    try:
        d = datetime.fromisoformat(str(x).replace("Z", "+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()
    except (TypeError, ValueError):
        return None


def day_of(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).date().isoformat()


def kpis(pf) -> dict:
    """Os números da Visão geral (carteira fictícia), no formato guardado em cada foto."""
    w = pf.wallet(False)
    return {"t": time.time(), "saldo": w["equity_sol"], "resultado": w["pnl_sol"], "abertas": w["open"],
            "valor_aberto": w["open_value_sol"], "fechados": w["count"], "ganhos": w["wins"], "perdas": w["losses"],
            "acerto": w["win_rate"], "traders": len(pf.followed), "pausados": len(pf.paused()),
            "monitor": bool((pf.rpc_status or {}).get("ws"))}


def _origin(t: dict) -> str:
    if t.get("origem") in ("explorar", "base", "elite"):
        return {"explorar": "Explorar (automática)", "base": "Base (automática)", "elite": "Maiores traders (automática)"}[t["origem"]]
    if t.get("manual") or t.get("wallet") == "manual":
        return "Botão Comprar / Base (manual ou automática antiga)"
    return "Cópia de trader"


def _exit(reason: str) -> str:
    low = (reason or "").lower()
    for k, name in (("stop de perda", "stop de perda"), ("stop móvel", "stop móvel"), ("trader vendeu", "trader vendeu"),
                    ("venda em partes", "venda em partes"), ("alvo", "alvo"), ("tempo máximo", "tempo máximo"),
                    ("dev vendeu", "dev vendeu"), ("segurou", "segurou até lucro"), ("boost", "boost"),
                    ("elite vendeu", "trader da elite vendeu"), ("pressão", "pressão virou")):
        if k in low:
            return name
    return "outro"


def build(pf, day: str, points: list[dict] | None = None) -> dict:
    """Relatório de um dia (UTC) da carteira fictícia, com diagnósticos e sugestões."""
    trades = [t for t in pf.trades(100000) if not t.get("real")]
    T = [t for t in trades if day_of(_ts(t.get("closed_at")) or 0) == day]
    n = len(T)
    wins = [t for t in T if (t.get("pnl_sol") or 0) > 0]
    pnl = round(sum(t.get("pnl_sol") or 0 for t in T), 6)
    fees = round(sum(t.get("fees_sol") or 0 for t in T), 6)
    inv = sum(t.get("sol_in") or 0 for t in T)

    def group(key):
        g: dict[str, list] = {}
        for t in T:
            g.setdefault(key(t), []).append(t)
        return sorted(({"nome": k, "trades": len(r), "pnl_sol": round(sum(x.get("pnl_sol") or 0 for x in r), 6),
                        "acerto": round(sum(1 for x in r if (x.get("pnl_sol") or 0) > 0) / len(r), 3)}
                       for k, r in g.items()), key=lambda x: x["pnl_sol"])
    by_trader = group(lambda t: t.get("wallet") or "?")
    by_exit = group(lambda t: _exit(t.get("reason")))
    by_origin = group(_origin)
    gave_back = [t for t in T if (t.get("best_pct") or 0) >= 30 and (t.get("pnl_pct") or 0) <= 0]
    stops = [t for t in T if _exit(t.get("reason")) == "stop de perda"]
    lags = [t["lag_s"] for t in T if t.get("lag_s") is not None]
    skips: dict[str, int] = {}
    for e in pf.feed:
        if str(e.get("action") or "").endswith("não copiou") and day_of(_ts(e.get("at")) or 0) == day:
            k = re.sub(r"[\d.,%$+−-]+", "#", str(e.get("reason") or "?"))[:60]
            skips[k] = skips.get(k, 0) + 1
    top_skips = sorted(skips.items(), key=lambda kv: -kv[1])[:5]

    sug: list[dict] = []

    def add(area, texto, base):
        sug.append({"area": area, "texto": texto, "base": base})
    if n >= 10 and len(wins) / n < 0.45:
        add("trades", f"Acerto do dia {len(wins) / n * 100:.0f}% em {n} trades: aperte a entrada (Configurações → Filtros: acerto mínimo do "
            "trader, pressão de compra mínima, nota mínima) ou copie só os traders que dão lucro para você.", n)
    if n >= 8 and len(stops) / n >= 0.4:
        add("lógica", f"{len(stops)} de {n} trades fecharam no stop de perda: compare em Relatórios → \"E se…\" um stop diferente e veja "
            "em Estratégias fantasma qual regra de saída ganhou.", n)
    if len(gave_back) >= 3:
        add("lógica", f"{len(gave_back)} trades chegaram a +30% ou mais e fecharam no zero ou pior: ligue a venda em partes "
            "(Opções novas) ou use um stop móvel mais justo.", len(gave_back))
    for tr in by_trader:
        if tr["trades"] >= 3 and tr["pnl_sol"] < 0 and tr["acerto"] < 0.34 and tr["nome"] not in ("manual", "?"):
            add("trades", f"O trader {tr['nome'][:4]}…{tr['nome'][-4:]} deu {tr['pnl_sol']:+.4f} SOL em {tr['trades']} cópias com "
                f"{tr['acerto'] * 100:.0f}% de acerto: pause ou bana em Top traders.", tr["trades"])
    for og in by_origin:
        if og["trades"] >= 5 and og["pnl_sol"] < 0:
            add("lógica", f"{og['nome']}: {og['pnl_sol']:+.4f} SOL em {og['trades']} trades hoje. Se repetir amanhã, desligue essa origem "
                "até o estudo mostrar uma regra que dá lucro.", og["trades"])
    if inv and fees / inv >= 0.05 and n >= 5:
        add("trades", f"As taxas levaram {fees / inv * 100:.1f}% do valor investido hoje ({fees:.4f} SOL): menos trades e valor por cópia "
            "um pouco maior diluem a taxa fixa de rede.", n)
    if len(lags) >= 5 and sum(lags) / len(lags) > 5:
        add("código", f"Atraso médio das cópias {sum(lags) / len(lags):.1f} s: um RPC próprio (Configurações → Chaves) reduz o atraso e o "
            "preço pior na entrada.", len(lags))
    if top_skips and top_skips[0][1] >= 20:
        add("lógica", f"O filtro \"{top_skips[0][0]}\" barrou {top_skips[0][1]} cópias hoje: confira se ele está protegendo ou só tirando "
            "boas entradas (Relatórios → Por que o bot não copiou).", top_skips[0][1])
    pts = points or []
    if len(pts) >= 2 and pts[0].get("saldo") and pts[-1].get("saldo") is not None:
        ch = (pts[-1]["saldo"] / pts[0]["saldo"] - 1) * 100
        if ch <= -5:
            add("lógica", f"O saldo caiu {ch:.1f}% no dia: ligue \"Pausar depois de perdas seguidas\" (Opções novas) e o limite de perda "
                "do dia das automáticas.", len(pts))
    if not sug:
        add("info", "Sem problema claro hoje (ou poucos trades para concluir). As sugestões aparecem com base mínima.", n)
    return {"dia": day, "trades": n, "wins": len(wins), "acerto": round(len(wins) / n, 3) if n else None, "pnl_sol": pnl,
            "fees_sol": fees, "invested_sol": round(inv, 6), "by_trader": by_trader[:8], "by_exit": by_exit,
            "by_origin": by_origin, "gave_back": len(gave_back), "stops": len(stops),
            "avg_lag_s": round(sum(lags) / len(lags), 1) if lags else None, "top_skips": [{"motivo": k, "n": v} for k, v in top_skips],
            "suggestions": sug, "points": pts[-MAX_POINTS:], "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def telegram_text(rep: dict) -> str:
    lines = [f"PUMP FUN COPY · relatório de {rep['dia']}",
             f"Resultado: {rep['pnl_sol']:+.4f} SOL · {rep['trades']} trades · acerto "
             + (f"{rep['acerto'] * 100:.0f}%" if rep.get("acerto") is not None else "–")]
    for s in rep.get("suggestions") or []:
        lines.append(f"• [{s['area']}] {s['texto']}")
    return "\n".join(lines)[:3500]
