"""Explorar (0.28.0, pedido do dono em 2026-10-26: usar as informações do pump.fun/explore).

A API do próprio site da pump.fun fica atrás da proteção anti-robô da Cloudflare (conferido em 2026-10-26: devolve
"Just a moment...") e burlar isso não é permitido. Por isso a fonte é a "Token Overview" da Solana Tracker
(GET /tokens/multi/all, documentada em docs.solanatracker.io: listas latest / graduating / graduated, estilo
Axiom Pulse), com a mesma chave que o sistema já usa. Uma consulta a cada EVERY_S para todos os usuários.
O formato da resposta é lido de forma defensiva (não foi testado com a chave de verdade nesta entrega).

Aprendizado: cada token visto em "quase graduando" é anotado com a % da curva; quando ele aparece em "graduados", conta
como graduou. A tabela mostra, por faixa de curva, quantos % graduaram — e isso entra no veredito de cada token.
"""
from __future__ import annotations

import time

URL = "https://data.solanatracker.io/tokens/multi/all"
EVERY_S = 300                          # 288 consultas/dia: cabe com folga em plano gratuito
KEEP_S = 6 * 3600                      # quanto tempo espera um "quase graduando" virar graduado


def _num(x):
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def item(raw: dict, cat: str) -> dict | None:
    if not isinstance(raw, dict):
        return None
    tk = raw.get("token") if isinstance(raw.get("token"), dict) else raw
    mint = tk.get("mint") or tk.get("address")
    if not mint:
        return None
    pools = [p for p in raw.get("pools") or [] if isinstance(p, dict)]
    pool = max(pools, key=lambda p: _num((p.get("liquidity") or {}).get("usd")) or 0) if pools else {}
    ev = raw.get("events") if isinstance(raw.get("events"), dict) else {}
    tx = pool.get("txns") if isinstance(pool.get("txns"), dict) else {}
    buys = _num(raw.get("buys")) if raw.get("buys") is not None else _num(tx.get("buys"))
    sells = _num(raw.get("sells")) if raw.get("sells") is not None else _num(tx.get("sells"))
    rk = raw.get("risk") if isinstance(raw.get("risk"), dict) else {}
    # 0.31.76 (pedido do dono): volume de 24 h em US$ (txns do pool da Solana Tracker; sem ele, a rota usa a DexScreener)
    vol24 = _num(tx.get("volume24h")) if tx.get("volume24h") is not None else _num(tx.get("volume"))
    return {"mint": mint, "cat": cat, "symbol": str(tk.get("symbol") or "")[:20], "name": str(tk.get("name") or "")[:40],
            "creator": tk.get("creator") or tk.get("deployer"),
            "mcap_usd": _num((pool.get("marketCap") or {}).get("usd")),
            "liq_usd": _num((pool.get("liquidity") or {}).get("usd")),
            "curve_pct": _num(pool.get("curvePercentage")), "holders": _num(raw.get("holders")),
            "buys": buys, "sells": sells, "txns": _num(raw.get("txns")),
            "pressure": round(buys / (buys + sells) * 100, 1) if buys is not None and sells is not None and buys + sells else None,
            "chg_5m": _num((ev.get("5m") or {}).get("priceChangePercentage")),
            "chg_1h": _num((ev.get("1h") or {}).get("priceChangePercentage")),
            "risk": _num(rk.get("score")), "rugged": bool(rk.get("rugged")),
            "created": _num(tk.get("createdAt") or pool.get("createdAt")), "vol24_usd": vol24}


def parse(js) -> dict:
    js = js if isinstance(js, dict) else {}
    out = {}
    for cat in ("latest", "graduating", "graduated"):
        out[cat] = [x for x in (item(r, cat) for r in js.get(cat) or []) if x]
    return out


def bucket(curve: float | None) -> str | None:
    if curve is None:
        return None
    return "40 a 60%" if curve < 60 else "60 a 80%" if curve < 80 else "80 a 90%" if curve < 90 else "90% ou mais"


class Explore:
    def __init__(self):
        self.at = 0.0
        self.error: str | None = None
        self.lists: dict = {"latest": [], "graduating": [], "graduated": []}
        self.seen: dict[str, dict] = {}            # mint -> {"t", "curve"} visto em "quase graduando"

    def update(self, data: dict, now: float | None = None) -> None:
        now = now or time.time()
        self.at, self.error, self.lists = now, None, data
        for x in data.get("graduating") or []:
            s = self.seen.setdefault(x["mint"], {"t": now, "curve": x.get("curve_pct"), "grad": None})
            s["last_curve"] = x.get("curve_pct")
        for x in data.get("graduated") or []:
            if x["mint"] in self.seen and not self.seen[x["mint"]].get("grad"):
                self.seen[x["mint"]]["grad"] = now
        for m in [m for m, s in self.seen.items() if now - s["t"] > 2 * KEEP_S]:
            del self.seen[m]

    def learned(self, now: float | None = None) -> list[dict]:
        """Por faixa de curva quando apareceu em "quase graduando": quantos % graduaram (só os já decididos)."""
        now = now or time.time()
        g: dict = {}
        for s in self.seen.values():
            b = bucket(s.get("curve"))
            if b is None or (not s.get("grad") and now - s["t"] < KEEP_S):
                continue                                   # ainda pode graduar: fora da conta
            x = g.setdefault(b, [0, 0])
            x[0] += 1
            x[1] += 1 if s.get("grad") else 0
        order = ["40 a 60%", "60 a 80%", "80 a 90%", "90% ou mais"]
        return [{"faixa": k, "n": g[k][0], "grad_pct": round(g[k][1] / g[k][0] * 100, 1)} for k in order if k in g]

    def verdict(self, x: dict, learned: dict, blacklist: dict, creators: dict) -> dict:
        why, bad = [], []
        if x.get("rugged"):
            bad.append("marcado como rug")
        if x.get("creator") and x["creator"] in blacklist:
            bad.append("criador na lista negra")
        c = creators.get(x.get("creator") or "") or {}
        if c.get("rugs", 0) >= 2 and not c.get("x2"):
            bad.append(f"criador já despencou {c['rugs']} tokens")
        if c.get("bundles", 0) >= 2:
            bad.append(f"criador lança tokens com bundle ({c['bundles']}x): robô")
        if x.get("risk") is not None and x["risk"] >= 8:
            bad.append(f"risco {x['risk']:.0f}/10")
        if x.get("pressure") is not None and x["pressure"] < 40:
            bad.append(f"mais vendas que compras ({x['pressure']:.0f}% compras)")
        if bad:
            return {"verdict": "lixo", "why": bad}
        score = 0
        if x.get("pressure") is not None:
            score += 1 if x["pressure"] >= 60 else 0
            why.append(f"{x['pressure']:.0f}% compras")
        if x.get("chg_5m") is not None and x["chg_5m"] > 0:
            score += 1
            why.append(f"+{x['chg_5m']:.0f}% em 5 min")
        if x.get("holders") is not None and x["holders"] >= 100:
            score += 1
            why.append(f"{x['holders']:.0f} holders")
        ln = learned.get(bucket(x.get("curve_pct")) or "")
        if ln and ln["n"] >= 20:
            why.append(f"curva {x['curve_pct']:.0f}%: {ln['grad_pct']:.0f}% graduaram")
            score += 1 if ln["grad_pct"] >= 50 else 0
        return {"verdict": "chance alta" if score >= 3 else "possível" if score >= 2 else "fraco", "why": why}

    def snapshot(self, blacklist: dict, creators: dict, boost_fn, now: float | None = None) -> dict:
        now = now or time.time()
        L = self.learned(now)
        lm = {x["faixa"]: x for x in L}
        lists = {}
        for cat, rows in self.lists.items():
            lists[cat] = [{**x, "pred": self.verdict(x, lm, blacklist, creators), "boost": boost_fn(x["mint"])} for x in rows[:40]]
        movers = sorted([x for rows in lists.values() for x in rows if x.get("chg_1h") is not None],
                        key=lambda x: -(x["chg_1h"] or 0))[:15]
        return {"at": self.at, "error": self.error, "every_s": EVERY_S, "lists": lists, "movers": movers,
                "learned": L, "watching": sum(1 for s in self.seen.values() if not s.get("grad"))}
