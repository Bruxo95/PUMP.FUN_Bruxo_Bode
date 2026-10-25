"""Carteiras em estudo (0.14.0): perfil de uma carteira a partir de duas fontes.

- Histórico por token da Solana Tracker (tabela study_positions, valores em US$): lucro realizado, investido,
  tempo segurando, datas de compra/venda. É a base do "quanto ganha por minuto/hora/dia".
- Operações vistas ao vivo pelo nosso monitor (tabela wallet_trades, valores em SOL): últimas operações e, sem chave
  da Solana Tracker, o resultado calculado aqui mesmo (custo médio por token).
Só contas sobre o passado; cada número diz quantos casos tem por trás. Não é recomendação de investimento.
"""
from __future__ import annotations

import statistics
import time
from datetime import datetime, timezone

MAX_WALLETS = 30                     # por usuário (limita consultas pagas com a chave do sistema)


def _med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def _ts(v) -> float | None:
    """ms, s ou ISO → segundos."""
    if v in (None, ""):
        return None
    try:
        x = float(v)
        return x / 1000 if x > 1e11 else x
    except (TypeError, ValueError):
        try:
            return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None


def compact_position(p: dict) -> dict | None:
    """Só o que o perfil usa, do formato da Solana Tracker (/v2/pnl/wallets/{w}/positions)."""
    if not isinstance(p, dict) or not p.get("token"):
        return None
    pnl, meta, cnt, tim = p.get("pnl") or {}, p.get("meta") or {}, p.get("counts") or {}, p.get("timing") or {}

    def num(x):
        return float(x) if isinstance(x, (int, float)) else None
    return {"token": p["token"], "symbol": meta.get("symbol"), "market": meta.get("primaryMarket"),
            "realized": num(pnl.get("realized")), "unrealized": num(pnl.get("unrealized")),
            "invested": num(p.get("invested")), "proceeds": num(p.get("proceeds")), "roi": num(p.get("roi")),
            "buys": cnt.get("buys"), "sells": cnt.get("sells"), "first_buy": _ts(tim.get("firstBuy")),
            "last_sell": _ts(tim.get("lastSell")), "last_trade": _ts(tim.get("lastTrade")),
            "hold_s": num(tim.get("holdTimeSecs")), "mcap_usd": num(meta.get("marketCap")),
            "holding": num((p.get("current") or {}).get("value"))}


def from_positions(rows: list[dict], now: float) -> dict | None:
    pos = [r for r in rows if r]
    if not pos:
        return None
    closed = [p for p in pos if (p.get("sells") or 0) > 0 and p.get("realized") is not None and p.get("last_sell")]

    def win(sec):
        sel = [p for p in closed if now - p["last_sell"] <= sec]
        return round(sum(p["realized"] for p in sel), 2), len(sel)
    h1, n1 = win(3600)
    d1, nd1 = win(86400)
    d7, nd7 = win(7 * 86400)
    d30, nd30 = win(30 * 86400)
    days: dict[str, float] = {}
    for p in closed:
        if now - p["last_sell"] <= 30 * 86400:
            k = datetime.fromtimestamp(p["last_sell"], timezone.utc).date().isoformat()
            days[k] = round(days.get(k, 0.0) + p["realized"], 2)
    hours = [0] * 24
    for p in pos:
        if p.get("first_buy") and now - p["first_buy"] <= 30 * 86400:
            hours[datetime.fromtimestamp(p["first_buy"], timezone.utc).hour] += 1
    wins = [p for p in closed if p["realized"] > 0]
    best = sorted(closed, key=lambda p: -p["realized"])[:10]
    worst = sorted(closed, key=lambda p: p["realized"])[:5]
    return {"source": "Solana Tracker (US$)", "unit": "US$", "positions": len(pos), "closed": len(closed),
            "pnl_1h": h1, "pnl_24h": d1, "pnl_7d": d7, "pnl_30d": d30, "n_24h": nd1, "n_7d": nd7, "n_30d": nd30,
            "per_min": round(d1 / 1440, 4), "per_hour": round(d1 / 24, 3), "per_day_7d": round(d7 / 7, 2),
            "win_rate": len(wins) / len(closed) if closed else None,
            "hold_med_s": _med([p.get("hold_s") for p in closed]), "invested_med": _med([p.get("invested") for p in pos]),
            "roi_med": _med([p.get("roi") for p in closed]), "days": sorted(days.items(), reverse=True),
            "buys_by_hour_utc": hours, "best": best, "worst": worst,
            "holding_now": [p for p in pos if (p.get("holding") or 0) > 1][:10],
            "markets": _count(p.get("market") for p in pos)}


def from_trades(trades: list[dict], now: float) -> dict | None:
    """Sem Solana Tracker: custo médio por token sobre as operações que o nosso monitor gravou (SOL)."""
    if not trades:
        return None
    book: dict[str, dict] = {}
    closed = []
    for t in sorted(trades, key=lambda x: _ts(x.get("at")) or 0):
        at, m = _ts(t.get("at")) or now, t.get("mint")
        b = book.setdefault(m, {"tok": 0.0, "cost": 0.0, "first": at, "pnl": 0.0})
        sol, tok = float(t.get("sol") or 0), float(t.get("tokens") or 0)
        if t.get("side") == "buy":
            b["tok"] += tok
            b["cost"] += sol
            continue
        if b["tok"] <= 0 or tok <= 0:
            continue
        frac = min(1.0, tok / b["tok"])
        cost = b["cost"] * frac
        b["pnl"] += sol - cost
        b["cost"] -= cost
        b["tok"] = max(0.0, b["tok"] - tok)
        if b["tok"] <= 1e-9:
            closed.append({"token": m, "realized": b["pnl"], "last_sell": at, "hold_s": at - b["first"]})
            del book[m]

    def win(sec):
        sel = [c for c in closed if now - c["last_sell"] <= sec]
        return round(sum(c["realized"] for c in sel), 4), len(sel)
    d1, nd1 = win(86400)
    d7, nd7 = win(7 * 86400)
    return {"source": "monitor do sistema (SOL)", "unit": "SOL", "closed": len(closed), "pnl_1h": win(3600)[0],
            "pnl_24h": d1, "pnl_7d": d7, "n_24h": nd1, "n_7d": nd7, "per_min": round(d1 / 1440, 6),
            "per_hour": round(d1 / 24, 5), "per_day_7d": round(d7 / 7, 4),
            "win_rate": (sum(1 for c in closed if c["realized"] > 0) / len(closed)) if closed else None,
            "hold_med_s": _med([c["hold_s"] for c in closed])}


def _count(xs) -> dict:
    out: dict = {}
    for x in xs:
        if x:
            out[x] = out.get(x, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1])[:5])


def profile(wallet: str, positions: list[dict], trades: list[dict], now: float | None = None) -> dict:
    now = now or time.time()
    main = from_positions([r.get("data") if "data" in r else r for r in positions], now)
    live = from_trades(trades, now)
    recent = sorted(trades, key=lambda t: _ts(t.get("at")) or 0, reverse=True)[:40]
    return {"wallet": wallet, "main": main, "live": live, "recent": recent,
            "trades_seen": len(trades), "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "notes": ["Ganho por minuto/hora = lucro realizado nas últimas 24 h dividido pelo tempo; por dia = média dos últimos 7 dias.",
                      "Lucro do trader não é o lucro de quem copia: quem copia entra depois e paga taxas (etapa 2 calcula isso).",
                      "Números do passado; não é recomendação de investimento."]}


def summary(p: dict) -> dict:
    m = p.get("main") or p.get("live") or {}
    return {"source": m.get("source"), "unit": m.get("unit"), "per_hour": m.get("per_hour"), "per_day_7d": m.get("per_day_7d"),
            "pnl_24h": m.get("pnl_24h"), "pnl_7d": m.get("pnl_7d"), "win_rate": m.get("win_rate"),
            "hold_med_s": m.get("hold_med_s"), "closed": m.get("closed"), "trades_seen": p.get("trades_seen")}
