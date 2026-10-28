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
            "closed_list": [p for p in closed if (p.get("holding") or 0) < 1],          # só tokens vendidos por inteiro
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
        b = book.setdefault(m, {"tok": 0.0, "cost": 0.0, "first": at, "pnl": 0.0, "in": 0.0})
        sol, tok = float(t.get("sol") or 0), float(t.get("tokens") or 0)
        if t.get("side") == "buy":
            b["tok"] += tok
            b["cost"] += sol
            b["in"] += sol
            continue
        if b["tok"] <= 0 or tok <= 0:
            continue
        frac = min(1.0, tok / b["tok"])
        cost = b["cost"] * frac
        b["pnl"] += sol - cost
        b["cost"] -= cost
        b["tok"] = max(0.0, b["tok"] - tok)
        if b["tok"] <= 1e-9:
            closed.append({"token": m, "realized": b["pnl"], "last_sell": at, "hold_s": at - b["first"], "invested": b["in"]})
            del book[m]

    def win(sec):
        sel = [c for c in closed if now - c["last_sell"] <= sec]
        return round(sum(c["realized"] for c in sel), 4), len(sel)
    d1, nd1 = win(86400)
    d7, nd7 = win(7 * 86400)
    return {"source": "monitor do sistema (SOL)", "unit": "SOL", "closed": len(closed), "closed_list": closed,
            "pnl_1h": win(3600)[0],
            "pnl_24h": d1, "pnl_7d": d7, "n_24h": nd1, "n_7d": nd7, "per_min": round(d1 / 1440, 6),
            "per_hour": round(d1 / 24, 5), "per_day_7d": round(d7 / 7, 4),
            "win_rate": (sum(1 for c in closed if c["realized"] > 0) / len(closed)) if closed else None,
            "hold_med_s": _med([c["hold_s"] for c in closed])}


# ---------------------------------------------------------------- etapa 2: e se você tivesse copiado (0.15.0)
def copy_params(pf) -> dict:
    """Mesmas taxas do modo simulado + o atraso real medido nas suas cópias (mediana; 3 s se ainda não houver)."""
    c = pf.cfg
    lags = [t["lag_s"] for t in pf.trades(1000) if t.get("lag_s") is not None]
    return {"amt": float(getattr(c, "pump_copy_sol", 0.1)),
            "fee": (float(getattr(c, "pump_fee_pct", 1.25)) + float(getattr(c, "pump_portal_fee_pct", 0.5))) / 100,
            "prio": float(getattr(c, "pump_priority_sol", 0.0005)), "slip": float(getattr(c, "pump_extra_slip_pct", 3.0)) / 100,
            "lag_s": statistics.median(lags) if lags else 3.0, "lag_measured": bool(lags),
            "delay_s": float(getattr(c, "pump_copy_delay_s", 0) or 0)}


def copy_sim(closed: list[dict], prm: dict, now: float) -> dict | None:
    """Recalcula cada token fechado pela carteira como se você tivesse copiado com o seu valor por cópia:
    entra e sai com slippage extra, paga taxa (plataforma + PumpPortal) nos dois lados e a prioridade.
    Se a carteira saiu antes do seu atraso + espera, você compraria depois da saída dela: conta como perda das
    taxas e do slippage (estimativa otimista — na prática o preço costuma cair depois que ela vende)."""
    rows = [p for p in closed if (p.get("invested") or 0) > 0 and p.get("realized") is not None and p.get("last_sell")]
    if not rows:
        return None
    a, fee, prio, slip = prm["amt"], prm["fee"], prm["prio"], prm["slip"]
    wait = prm["lag_s"] + prm["delay_s"]
    keep = (1 - slip) ** 2 * (1 - fee) ** 2
    out = []
    for p in rows:
        r = max(-1.0, p["realized"] / p["invested"])                   # retorno da carteira nesse token
        fast = p.get("hold_s") is not None and p["hold_s"] <= wait
        mine = a * (keep - 1) - 2 * prio if fast else a * ((1 + r) * keep - 1) - 2 * prio
        out.append({"t": p["last_sell"], "trader_r": r, "pnl": mine, "fast": fast})

    def win(sec):
        sel = [x for x in out if now - x["t"] <= sec]
        return sel, round(sum(x["pnl"] for x in sel), 4)
    s7, p7 = win(7 * 86400)
    s30, p30 = win(30 * 86400)
    n = len(s30)
    wins = sum(1 for x in s30 if x["pnl"] > 0)
    verdict = ("poucos dados" if n < 5 else "compensa copiar" if p30 > 0 and wins / n >= 0.4 else
               "não compensa" if p30 < 0 else "no limite")
    return {"amt": a, "pnl_7d": p7, "pnl_30d": p30, "per_day_7d": round(p7 / 7, 4), "n_30d": n, "n_7d": len(s7),
            "win_rate": wins / n if n else None, "fast_pct": (sum(1 for x in s30 if x["fast"]) / n) if n else None,
            "trader_win_rate": (sum(1 for x in s30 if x["trader_r"] > 0) / n) if n else None,
            "avg_pnl": round(p30 / n, 5) if n else None, "verdict": verdict,
            "assumptions": {"fee_pct_each_side": round(fee * 100, 2), "slip_pct_each_side": round(slip * 100, 2),
                            "prio_sol": prio, "lag_s": round(prm["lag_s"], 1), "lag_measured": prm["lag_measured"],
                            "delay_s": prm["delay_s"]}}


def _count(xs) -> dict:
    out: dict = {}
    for x in xs:
        if x:
            out[x] = out.get(x, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1])[:5])


def is_pump_mint(m: str | None, market: str | None = None) -> bool:
    """Token da pump.fun: endereço termina em "pump" (padrão do site) ou o mercado principal é a pump.fun/PumpSwap."""
    return bool(m and m.endswith("pump")) or "pump" in str(market or "").lower()


def score(wins: int, losses: int, gain: float, lost: float) -> dict:
    """0.32.11 (pedido do dono: "score geral juntando acertos e erros"), nota 0–100:
    70% = acerto pelo limite inferior de Wilson a 90% (com poucos tokens a nota fica baixa, não 100%);
    30% = quanto do dinheiro movido foi ganho (ganho ÷ (ganho + perda)). Sem tokens fechados: sem nota."""
    n = wins + losses
    if not n:
        return {"score": None, "score_base": 0}
    z, ph = 1.645, wins / n
    wil = (ph + z * z / (2 * n) - z * ((ph * (1 - ph) + z * z / (4 * n)) / n) ** 0.5) / (1 + z * z / n)
    money = gain / (gain + lost) if gain + lost > 0 else ph
    return {"score": round(100 * (0.7 * wil + 0.3 * money)), "score_base": n}


def digest(main: dict | None, live: dict | None, trades: list[dict], now: float) -> dict:
    """0.32.10 (pedido do dono): resumo para as Decisões da IA — tokens que acertou e errou (nome, resultado, se é da
    pump.fun, última transação dela no token), quanto das operações é na pump.fun e quando operou por último."""
    sig_of: dict[str, str] = {}
    for t in sorted(trades, key=lambda x: _ts(x.get("at")) or 0):
        if t.get("mint") and t.get("signature"):
            sig_of[t["mint"]] = t["signature"]
    unit = "US$" if main else "SOL"
    src = (main or {}).get("closed_list") or (live or {}).get("closed_list") or []

    def item(p):
        m = p.get("token")
        return {"mint": m, "symbol": p.get("symbol"), "realized": round(float(p.get("realized") or 0), 4),
                "roi": p.get("roi"), "pump": is_pump_mint(m, p.get("market")), "sig": sig_of.get(m), "unit": unit}
    wins = sorted((p for p in src if (p.get("realized") or 0) > 0), key=lambda p: -p["realized"])
    loss = sorted((p for p in src if (p.get("realized") or 0) < 0), key=lambda p: p["realized"])
    mints = [t.get("mint") for t in trades if t.get("mint")]
    np_ = sum(1 for m in mints if is_pump_mint(m))
    mk = (main or {}).get("markets") or {}
    last = max((_ts(t.get("at")) or 0 for t in trades), default=0) or None
    gain = sum(float(p["realized"]) for p in wins)
    lost = -sum(float(p["realized"]) for p in loss)
    return {"acertos": [item(p) for p in wins[:5]], "erros": [item(p) for p in loss[:3]],
            "n_acertos": len(wins), "n_erros": len(loss), "unit": unit,
            "ganho": round(gain, 4), "perda": round(lost, 4), **score(len(wins), len(loss), gain, lost),
            "pump_ops": np_, "ops": len(mints), "pump_pct": round(np_ / len(mints) * 100) if mints else None,
            "mercados": mk, "ultima_op": last}


def profile(wallet: str, positions: list[dict], trades: list[dict], now: float | None = None,
            prm: dict | None = None) -> dict:
    now = now or time.time()
    main = from_positions([r.get("data") if "data" in r else r for r in positions], now)
    live = from_trades(trades, now)
    dg = digest(main, live, trades, now)
    copy = None
    if prm:
        src = (main or {}).get("closed_list") or (live or {}).get("closed_list") or []
        copy = copy_sim(src, prm, now)
    for m in (main, live):
        if m:
            m.pop("closed_list", None)
    recent = sorted(trades, key=lambda t: _ts(t.get("at")) or 0, reverse=True)[:40]
    return {"wallet": wallet, "main": main, "live": live, "recent": recent, "copy": copy, "digest": dg,
            "trades_seen": len(trades), "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "notes": ["Ganho por minuto/hora = lucro realizado nas últimas 24 h dividido pelo tempo; por dia = média dos últimos 7 dias.",
                      "Lucro do trader não é o lucro de quem copia: quem copia entra depois e paga taxas (etapa 2 calcula isso).",
                      "Números do passado; não é recomendação de investimento."]}


def summary(p: dict) -> dict:
    m = p.get("main") or p.get("live") or {}
    return {"source": m.get("source"), "unit": m.get("unit"), "per_hour": m.get("per_hour"), "per_day_7d": m.get("per_day_7d"),
            "pnl_24h": m.get("pnl_24h"), "pnl_7d": m.get("pnl_7d"), "win_rate": m.get("win_rate"),
            "hold_med_s": m.get("hold_med_s"), "closed": m.get("closed"), "trades_seen": p.get("trades_seen"),
            "digest": p.get("digest"),
            "copy": {k: (p.get("copy") or {}).get(k) for k in ("pnl_7d", "pnl_30d", "per_day_7d", "win_rate", "n_30d",
                                                                 "verdict", "fast_pct", "amt")} if p.get("copy") else None}
