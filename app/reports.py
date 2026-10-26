"""Relatórios do usuário (aba Relatórios, 0.9.8): respostas em vez de listas.

- por trader copiado: quanto VOCÊ ganhou/perdeu copiando cada um, já depois das taxas (pesquisa de 2026-10-25:
  o lucro do trader e o de quem copia costumam ser bem diferentes);
- por motivo de saída: stop, stop móvel, trader vendeu, tempo máximo…;
- cópias barradas: quantas vezes cada filtro impediu uma cópia (dos últimos eventos guardados no feed);
- por dia e taxas pagas.
Só lê os dados do próprio usuário; nada aqui consulta a rede.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

EXITS = [("venda em partes", "Venda em partes"), ("antes da graduação", "Saída antes da graduação"),
         ("stop móvel", "Stop móvel"), ("stop de perda", "Stop de perda"), ("trader vendeu", "Trader vendeu"),
         ("segurou até", "Segurou até ficar positivo"), ("alvo", "Alvo de lucro"), ("tempo máximo", "Tempo máximo"),
         ("fechada por você", "Fechada por você")]
SKIPS = [("10 maiores", "Concentração nas 10 maiores"), ("risco", "Risco do token"),
         ("preço já subiu", "Preço já subiu desde o trader"),
         ("volume", "Volume baixo"), ("negociações", "Poucas negociações"), ("market cap", "Market cap fora do limite"),
         ("compra pequena", "Compra pequena do trader"),
         ("pausado", "Trader pausado"), ("já tem posição", "Já tinha posição no token"),
         ("limite de", "Limite de posições abertas"), ("saldo", "Saldo insuficiente"),
         ("trader saiu em", "Trader saiu antes da espera"), ("sem preço", "Token sem preço"),
         ("cópia desligada", "Cópia desligada"), ("graduou", "Token já graduado"),
         ("curva enchendo", "Curva enchendo devagar"), ("pressão de compra", "Pressão de compra fraca"), ("perda do dia", "Perda máxima do dia (real)"),
         ("fora da pump.fun", "Fora da pump.fun"), ("liquidez", "Liquidez baixa")]


def _when(s) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _label(text: str, table: list[tuple[str, str]]) -> str:
    low = (text or "").lower()
    for key, name in table:
        if key in low:
            return name
    # desconhecido: agrupa pelo começo do texto, sem números (não vira uma linha por valor)
    return re.sub(r"[\d.,%$+−-]+", "#", (text or "outro").strip())[:48] or "outro"


def mesa(T: list[dict]) -> dict:
    """Pós-trade (0.18.0): melhor e pior momento de cada posição × como ela fechou. Responde "estou saindo cedo
    demais?" (subiu bem e fechou mal) e "o stop está apertado?" (só trades com o dado, gravado desde a 0.18.0)."""
    R = [t for t in T if t.get("best_pct") is not None]
    n = len(R)
    if not n:
        return {"trades": 0}
    gave_back = [t for t in R if (t.get("best_pct") or 0) >= 30 and (t.get("pnl_pct") or 0) <= 0]
    left = [max(0.0, (t.get("best_pct") or 0) - (t.get("pnl_pct") or 0)) for t in R]
    stops = [t for t in R if str(t.get("reason") or "").startswith("stop de perda")]
    by_exit: dict[str, list] = {}
    for t in R:
        by_exit.setdefault(_label(t.get("reason"), EXITS), []).append(t)
    return {"trades": n,
            "avg_best_pct": round(sum(t.get("best_pct") or 0 for t in R) / n, 1),
            "avg_worst_pct": round(sum(t.get("worst_pct") or 0 for t in R) / n, 1),
            "avg_final_pct": round(sum(t.get("pnl_pct") or 0 for t in R) / n, 1),
            "avg_left_pct": round(sum(left) / n, 1),
            "gave_back": len(gave_back),                              # chegou a +30% ou mais e fechou no zero ou pior
            "stops": len(stops),
            "stops_were_up": sum(1 for t in stops if (t.get("best_pct") or 0) >= 10),   # stop depois de já ter ganhado 10%+
            "exits": sorted(({"reason": k, "trades": len(r),
                              "avg_best_pct": round(sum(t.get("best_pct") or 0 for t in r) / len(r), 1),
                              "avg_final_pct": round(sum(t.get("pnl_pct") or 0 for t in r) / len(r), 1)}
                             for k, r in by_exit.items()), key=lambda x: -x["trades"])}


def whatif(T: list[dict]) -> dict:
    """Simulador "e se" (0.22.0): refaz o resultado com outro alvo ou outro stop usando o melhor e o pior momento de
    cada trade. É ESTIMATIVA: não se sabe o que veio primeiro, então quando o trade passou pelos dois o stop conta
    primeiro (o caso pior). Só trades com o dado (0.18.0 em diante)."""
    R = [t for t in T if t.get("best_pct") is not None and t.get("worst_pct") is not None and t.get("sol_in")]
    real = round(sum(t.get("pnl_sol") or 0 for t in R), 6)

    def total(stop=None, tp=None):
        out = 0.0
        for t in R:
            pct = t.get("pnl_pct") or 0.0
            if stop is not None and t["worst_pct"] <= -stop:
                pct = -stop
            elif tp is not None and t["best_pct"] >= tp:
                pct = tp
            out += t["sol_in"] * pct / 100
        return round(out, 6)
    rows = [{"regra": f"Alvo fixo +{x}%", "pnl_sol": total(tp=x)} for x in (20, 30, 50, 100)]
    rows += [{"regra": f"Stop de perda {x}%", "pnl_sol": total(stop=x)} for x in (15, 25, 40, 60)]
    rows += [{"regra": f"Stop {s}% + alvo +{x}%", "pnl_sol": total(stop=s, tp=x)} for s, x in ((20, 30), (25, 50), (40, 100))]
    for r in rows:
        r["diff_sol"] = round(r["pnl_sol"] - real, 6)
    return {"trades": len(R), "real_sol": real, "rows": sorted(rows, key=lambda r: -r["pnl_sol"])}


def custo(T: list[dict]) -> dict:
    """Onde o dinheiro vai (0.22.0): quanto mais caro você entrou que o trader (atraso + slippage) e o peso das taxas."""
    E = [t for t in T if t.get("trader_px") and t.get("price_in")]
    inv = sum(t.get("sol_in") or 0 for t in T)
    fees = sum(t.get("fees_sol") or 0 for t in T)
    gross = sum(t.get("gross_sol") or 0 for t in T)
    return {"trades": len(T), "with_px": len(E),
            "entry_worse_pct": round(sum((t["price_in"] / t["trader_px"] - 1) * 100 for t in E) / len(E), 2) if E else None,
            "fees_pct": round(fees / inv * 100, 2) if inv else None, "fees_sol": round(fees, 6),
            "gross_sol": round(gross, 6), "net_sol": round(sum(t.get("pnl_sol") or 0 for t in T), 6)}


# Por que está no vermelho (0.31.11, pedido do dono em 2026-10-26): cada trade no prejuízo ganha UMA causa principal
# (a primeira que bate, na ordem abaixo) e cada causa tem a correção recomendada. O relatório do dia guarda as contagens
# no banco (daily_report) e o "Aprendizado dos dias" mostra quando a mesma causa se repete.
CAUSES = {
    "rug": ("Rug ou dev vendeu", "Ligue a lista negra e \"sair quando o dev vende\" (Opções novas)."),
    "parado": ("Ficou parado até o tempo máximo", "Ligue \"sair quando a posição fica parada\" ou diminua o tempo máximo (veja antes as Estratégias fantasma)."),
    "devolveu": ("Chegou a ganhar e devolveu", "Ligue a venda em partes e use um stop móvel mais justo."),
    "taxas": ("As taxas viraram o resultado", "Copie com valor um pouco maior ou evite trades pequenos: a taxa fixa de rede pesa."),
    "entrada_cara": ("Entrou bem mais caro que o trader", "Ligue \"não copiar se o preço já subiu\" e use um RPC próprio para reduzir o atraso."),
    "trader_perdeu": ("O próprio trader saiu no prejuízo", "O erro é do trader: pause ou bana quem repete isso."),
    "so_caiu": ("Entrou e só caiu", "Aperte a entrada: pressão de compra mínima, nota mínima e barrar carteiras novas."),
    "outro": ("Outro motivo", "Veja o motivo de saída na lista."),
}


def loss_cause(t: dict) -> str:
    why = str(t.get("reason") or "").lower()
    best = t.get("best_pct") or 0
    if "dev vendeu" in why or "rug" in why or "graduou" in why:
        return "rug"
    if "tempo máximo" in why or "parado" in why:
        return "parado"
    if best >= 10:
        return "devolveu"
    if (t.get("gross_sol") or 0) >= 0 > (t.get("pnl_sol") or 0):
        return "taxas"
    tp, pi = t.get("trader_px"), t.get("price_in")
    if tp and pi and pi / tp - 1 >= 0.10:
        return "entrada_cara"
    if "trader vendeu" in why or "elite vendeu" in why:
        return "trader_perdeu"
    if "stop de perda" in why:
        return "so_caiu"
    return "outro"


def autopsy(T: list[dict]) -> dict:
    L = [t for t in T if (t.get("pnl_sol") or 0) < 0]
    causes: dict[str, dict] = {}
    for t in L:
        k = loss_cause(t)
        c = causes.setdefault(k, {"causa": k, "nome": CAUSES[k][0], "correcao": CAUSES[k][1], "trades": 0, "perdido_sol": 0.0})
        c["trades"] += 1
        c["perdido_sol"] = round(c["perdido_sol"] + (t.get("pnl_sol") or 0), 6)
    by_tr: dict[str, list] = {}
    for t in T:
        by_tr.setdefault(t.get("wallet") or "?", []).append(t)
    traders = []
    for w, rows in by_tr.items():
        pnl = sum(t.get("pnl_sol") or 0 for t in rows)
        if pnl >= 0:
            continue
        ks: dict[str, int] = {}
        for t in rows:
            if (t.get("pnl_sol") or 0) < 0:
                ks[loss_cause(t)] = ks.get(loss_cause(t), 0) + 1
        main = max(ks, key=ks.get) if ks else "outro"
        wins = sum(1 for t in rows if (t.get("pnl_sol") or 0) > 0)
        hold = sum(t.get("hold_s") or 0 for t in rows) / len(rows)
        rec = CAUSES[main][1]
        if len(rows) >= 3 and wins == 0:
            rec = f"0 acertos em {len(rows)} cópias: pause ou bana este trader. " + rec
        if hold >= 3 * 3600:
            rec = f"Ele segura em média {hold / 3600:.1f} h (holder longo): não combina com a cópia de memecoin. " + rec
        traders.append({"wallet": w, "trades": len(rows), "acerto": round(wins / len(rows), 3), "pnl_sol": round(pnl, 6),
                        "causa": main, "causa_nome": CAUSES[main][0], "hold_s": round(hold), "recomendacao": rec})
    traders.sort(key=lambda x: x["pnl_sol"])
    worst = sorted(L, key=lambda t: t.get("pnl_sol") or 0)[:30]
    return {"losses": len(L), "lost_sol": round(sum(t.get("pnl_sol") or 0 for t in L), 6),
            "causes": sorted(causes.values(), key=lambda c: c["perdido_sol"]), "traders": traders[:15],
            "trades": [{"wallet": t.get("wallet"), "symbol": t.get("symbol"), "mint": t.get("mint"), "closed_at": t.get("closed_at"),
                        "pnl_sol": t.get("pnl_sol"), "pnl_pct": t.get("pnl_pct"), "best_pct": t.get("best_pct"), "hold_s": t.get("hold_s"),
                        "reason": t.get("reason"), "causa": loss_cause(t), "causa_nome": CAUSES[loss_cause(t)][0]} for t in worst]}


def build(trades: list[dict], feed: list[dict], days: int | None, real: bool, followed=(), paused=()) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=days) if days else None
    T = [t for t in trades if bool(t.get("real")) == real and (since is None or ((_when(t.get("closed_at")) or since) >= since))]

    def agg(rows):
        n, wins = len(rows), sum(1 for t in rows if (t.get("pnl_sol") or 0) > 0)
        pnl = sum(t.get("pnl_sol") or 0 for t in rows)
        return {"trades": n, "wins": wins, "win_rate": (wins / n) if n else None, "pnl_sol": round(pnl, 6),
                "fees_sol": round(sum(t.get("fees_sol") or 0 for t in rows), 6),
                "invested_sol": round(sum(t.get("sol_in") or 0 for t in rows), 6),
                "avg_pnl_sol": round(pnl / n, 6) if n else None,
                "avg_hold_s": round(sum(t.get("hold_s") or 0 for t in rows) / n) if n else None,
                "avg_lag_s": (round(sum(lags) / len(lags), 1) if (lags := [t["lag_s"] for t in rows if t.get("lag_s") is not None]) else None)}

    by_trader: dict[str, list] = {}
    by_exit: dict[str, list] = {}
    by_day: dict[str, list] = {}
    for t in T:
        by_trader.setdefault(t.get("wallet") or "?", []).append(t)
        by_exit.setdefault(_label(t.get("reason"), EXITS), []).append(t)
        by_day.setdefault(str(t.get("closed_at") or "")[:10], []).append(t)
    fol, pau = set(followed), set(paused)
    traders = sorted(({"wallet": w, **agg(r), "last": max(str(x.get("closed_at") or "") for x in r),
                       "status": "pausado" if w in pau else "copiando" if w in fol else "fora"}
                      for w, r in by_trader.items()), key=lambda x: x["pnl_sol"])
    fee_parts: dict[str, float] = {}
    for t in T:
        for k, v in (t.get("fee_parts") or {}).items():
            fee_parts[k] = round(fee_parts.get(k, 0.0) + (v or 0), 6)

    skips: dict[str, int] = {}
    seen = 0
    for e in feed:
        if not str(e.get("action") or "").endswith("não copiou"):
            continue
        if bool(str(e.get("action")).startswith("REAL")) != real:
            continue
        at = _when(e.get("at"))
        if since and at and at < since:
            continue
        seen += 1
        k = _label(e.get("reason"), SKIPS)
        skips[k] = skips.get(k, 0) + 1

    buckets = [(0, 40, "0–39"), (40, 60, "40–59"), (60, 80, "60–79"), (80, 101, "80–100")]
    by_score = [{"faixa": name, **agg([t for t in T if t.get("score") is not None and lo <= t["score"] < hi])}
                for lo, hi, name in buckets]
    return {"days": days, "real": real, "total": agg(T), "fee_parts": fee_parts, "mesa": mesa(T), "by_score": by_score,
            "whatif": whatif(T), "custo": custo(T), "autopsy": autopsy(T),
            "traders": traders,                                        # pior primeiro: é quem você quer ver
            "exits": sorted(({"reason": k, **agg(r)} for k, r in by_exit.items()), key=lambda x: -x["trades"]),
            "days_list": [{"day": d, **agg(r)} for d, r in sorted(by_day.items(), reverse=True)][:60],
            "skips": sorted(({"reason": k, "count": v} for k, v in skips.items()), key=lambda x: -x["count"]),
            "skips_seen": seen, "feed_kept": len(feed)}
