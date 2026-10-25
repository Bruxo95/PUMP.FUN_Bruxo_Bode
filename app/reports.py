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

EXITS = [("stop móvel", "Stop móvel"), ("stop de perda", "Stop de perda"), ("trader vendeu", "Trader vendeu"),
         ("segurou até", "Segurou até ficar positivo"), ("alvo", "Alvo de lucro"), ("tempo máximo", "Tempo máximo"),
         ("fechada por você", "Fechada por você")]
SKIPS = [("10 maiores", "Concentração nas 10 maiores"), ("risco", "Risco do token"),
         ("preço já subiu", "Preço já subiu desde o trader"),
         ("volume", "Volume baixo"), ("negociações", "Poucas negociações"), ("market cap", "Market cap fora do limite"),
         ("compra pequena", "Compra pequena do trader"),
         ("pausado", "Trader pausado"), ("já tem posição", "Já tinha posição no token"),
         ("limite de", "Limite de posições abertas"), ("saldo", "Saldo insuficiente"),
         ("trader saiu em", "Trader saiu antes da espera"), ("sem preço", "Token sem preço"),
         ("cópia desligada", "Cópia desligada"), ("perda do dia", "Perda máxima do dia (real)"),
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
                "avg_hold_s": round(sum(t.get("hold_s") or 0 for t in rows) / n) if n else None}

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

    return {"days": days, "real": real, "total": agg(T), "fee_parts": fee_parts,
            "traders": traders,                                        # pior primeiro: é quem você quer ver
            "exits": sorted(({"reason": k, **agg(r)} for k, r in by_exit.items()), key=lambda x: -x["trades"]),
            "days_list": [{"day": d, **agg(r)} for d, r in sorted(by_day.items(), reverse=True)][:60],
            "skips": sorted(({"reason": k, "count": v} for k, v in skips.items()), key=lambda x: -x["count"]),
            "skips_seen": seen, "feed_kept": len(feed)}
