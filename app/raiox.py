"""Raio-X do token (0.31.86, pedido do dono em 2026-10-28: "abrir os gráficos de compra e venda, analisar as transações,
horários e saídas; ver quem compra, segura e depois despeja").

Fonte: Solana Tracker `GET /trades/{token}?limit=500&sortDirection=ASC` (OpenAPI oficial conferido em 2026-10-28: limite
máximo 500, 1 crédito por chamada). Lê as PRIMEIRAS 500 negociações — o começo da vida do token, onde aparecem os
primeiros compradores, as compras em bloco e o primeiro despejo. Não é o histórico inteiro de tokens muito negociados.
Tudo aqui é calculado depois do fato: serve para estudar e anotar, não para decidir uma compra em tempo real.
"""
from __future__ import annotations

from collections import defaultdict

TRADES_URL = "https://data.solanatracker.io/trades/"
PAGE = 500
FIRST_N = 20                    # primeiros compradores acompanhados
QUICK_S = 300                   # "vendeu cedo" = vendeu metade ou mais até 5 min depois da 1ª compra
BUNDLE_S = 1.0                  # compras no mesmo segundo da primeira negociação = compra em bloco


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def parse(js) -> list[dict]:
    rows = (js or {}).get("trades") if isinstance(js, dict) else None
    out = []
    for t in rows or []:
        if not isinstance(t, dict) or t.get("type") not in ("buy", "sell") or not t.get("wallet"):
            continue
        tm = _f(t.get("time"))
        if tm is None:
            continue
        out.append({"t": tm / 1000 if tm > 1e12 else tm, "type": t["type"], "wallet": str(t["wallet"]),
                    "amount": _f(t.get("amount")) or 0.0, "sol": _f(t.get("volumeSol")) or 0.0, "usd": _f(t.get("volume")) or 0.0,
                    "px": _f(t.get("priceUsd")), "tx": t.get("tx")})
    out.sort(key=lambda x: x["t"])
    return out


def analyze(trades: list[dict]) -> dict:
    """Gráfico por minuto, primeiros compradores (quanto seguraram), quem despejou e sinais do começo do token."""
    if not trades:
        return {"n": 0}
    t0 = trades[0]["t"]
    mins: dict[int, dict] = {}
    for x in trades:
        m = int((x["t"] - t0) // 60)
        b = mins.setdefault(m, {"min": m, "compras": 0, "vendas": 0, "sol_compra": 0.0, "sol_venda": 0.0, "px": None})
        if x["type"] == "buy":
            b["compras"] += 1
            b["sol_compra"] += x["sol"]
        else:
            b["vendas"] += 1
            b["sol_venda"] += x["sol"]
        if x["px"]:
            b["px"] = x["px"]
    w = defaultdict(lambda: {"first_buy": None, "bought": 0.0, "sold": 0.0, "sol_in": 0.0, "sol_out": 0.0, "first_sell": None, "half_t": None})
    for x in trades:
        s = w[x["wallet"]]
        if x["type"] == "buy":
            s["first_buy"] = s["first_buy"] if s["first_buy"] is not None else x["t"]
            s["bought"] += x["amount"]
            s["sol_in"] += x["sol"]
        else:
            s["first_sell"] = s["first_sell"] if s["first_sell"] is not None else x["t"]
            s["sold"] += x["amount"]
            s["sol_out"] += x["sol"]
            if s["half_t"] is None and s["bought"] > 0 and s["sold"] >= s["bought"] * 0.5:
                s["half_t"] = x["t"]
    order = sorted((k for k, v in w.items() if v["first_buy"] is not None), key=lambda k: w[k]["first_buy"])
    first = []
    for k in order[:FIRST_N]:
        s = w[k]
        sold_pct = min(100.0, s["sold"] / s["bought"] * 100) if s["bought"] else 0.0
        first.append({"wallet": k, "entrou_s": round(s["first_buy"] - t0, 1), "sol": round(s["sol_in"], 4),
                      "vendeu_pct": round(sold_pct, 1), "segurou_s": round((s["half_t"] or trades[-1]["t"]) - s["first_buy"], 1),
                      "lucro_sol": round(s["sol_out"] - s["sol_in"], 4),
                      "perfil": "vendeu tudo" if sold_pct >= 90 else "segurou" if sold_pct < 10 else "vendeu parte"})
    quick = sum(1 for k in order[:FIRST_N] if w[k]["half_t"] is not None and w[k]["half_t"] - w[k]["first_buy"] <= QUICK_S)
    bundle = sum(1 for k in order if w[k]["first_buy"] - t0 <= BUNDLE_S)
    sells = sorted(((k, v["sol_out"]) for k, v in w.items() if v["sol_out"] > 0), key=lambda kv: -kv[1])
    sell_total = sum(v for _, v in sells)
    worst = max(mins.values(), key=lambda b: b["sol_venda"] - b["sol_compra"])
    dumpers = [k for k in order if w[k]["half_t"] is not None and worst["min"] <= (w[k]["half_t"] - t0) / 60 < worst["min"] + 5]
    holds = sorted(f["segurou_s"] for f in first)
    return {
        "n": len(trades), "inicio": t0, "fim": trades[-1]["t"], "compradores": len(order),
        "minutos": [mins[m] for m in sorted(mins)],
        "primeiros": first,
        "despejo": {"minuto": worst["min"], "sol_venda": round(worst["sol_venda"], 4), "sol_compra": round(worst["sol_compra"], 4),
                    "carteiras": len(dumpers), "primeiros_no_despejo": sum(1 for k in dumpers if k in order[:FIRST_N])},
        "maiores_vendedores": [{"wallet": k, "sol": round(v, 4), "pct": round(v / sell_total * 100, 1)} for k, v in sells[:10]] if sell_total else [],
        "sinais": {
            "vendas_cedo_pct": round(quick / min(FIRST_N, len(order)) * 100, 1) if order else None,
            "bloco_n": bundle,
            "top5_venda_pct": round(sum(v for _, v in sells[:5]) / sell_total * 100, 1) if sell_total else None,
            "segurou_mediana_min": round(holds[len(holds) // 2] / 60, 1) if holds else None,
        },
        "completo": len(trades) < PAGE,
    }


SIGNALS = {
    "vendas_cedo_pct": ("Primeiros compradores que venderam em até 5 min", [(0, 25, "até 25%"), (25, 50, "25 a 50%"), (50, 75, "50 a 75%"), (75, 101, "75% ou mais")]),
    "bloco_n": ("Compras em bloco no 1º segundo", [(0, 3, "0 a 2"), (3, 6, "3 a 5"), (6, 1e9, "6 ou mais")]),
    "top5_venda_pct": ("Vendas concentradas nos 5 maiores vendedores", [(0, 30, "até 30%"), (30, 60, "30 a 60%"), (60, 101, "60% ou mais")]),
    "segurou_mediana_min": ("Quanto os primeiros seguraram (mediana)", [(0, 2, "menos de 2 min"), (2, 10, "2 a 10 min"), (10, 60, "10 a 60 min"), (60, 1e12, "mais de 1 h")]),
}


def bucket(k: str, v) -> str | None:
    v = _f(v)
    if v is None:
        return None
    for lo, hi, name in SIGNALS[k][1]:
        if lo <= v < hi:
            return name
    return None


def study(xrays: dict[str, dict], outcomes: dict[str, dict]) -> list[dict]:
    """Sinais do Raio-X × o que aconteceu (operação do Explorar ou sombra). Só anota: nunca bloqueia nada."""
    out = []
    for k, (nome, _b) in SIGNALS.items():
        g: dict[str, list] = {}
        for mint, x in xrays.items():
            o = outcomes.get(mint)
            b = bucket(k, ((x or {}).get("sinais") or {}).get(k))
            if o is None or b is None:
                continue
            g.setdefault(b, []).append(o)
        for b, r in g.items():
            n = len(r)
            out.append({"feature": k, "nome": nome, "faixa": b, "n": n, "n_sombra": sum(1 for o in r if o.get("sombra")),
                        "acerto": round(sum(1 for o in r if (o.get("pnl_pct") or 0) > 0) / n, 3),
                        "media_pct": round(sum(o.get("pnl_pct") or 0 for o in r) / n, 1)})
    return sorted(out, key=lambda x: (list(SIGNALS).index(x["feature"]), -x["n"]))
