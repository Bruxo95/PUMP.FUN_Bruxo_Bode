"""Laboratório do Top traders (0.32.124, pedido do dono: "acho que estamos achando o pote do ouro").

A aba parecia a melhor, mas com 34 trades e quase todo o lucro em um dia. Aqui se mede se é método ou sorte:
- `study`: resultado com faixa de confiança por dia, sem os 3 maiores ganhos, e por trader.
- `late`: a cópia fictícia entra no preço do próprio trader, o que é otimista. Compara com o preço do mercado 5/15/30 s depois.
- `Barred`: compras barradas pelos filtros, acompanhadas por 15 min como se tivessem entrado.

Só mede: nada aqui compra, vende, pausa ou muda opção.
"""
from __future__ import annotations

import re

from . import stats
from .auto_trades import SUSPECT_PCT

ABA = "Top traders"
MARCAS = ("5", "15", "30")
WATCH_S = 900
PRICE_S = 120
FIRST_S = 5
MAX_OPEN = 20                # com 15 min de acompanhamento dá no máximo ~80 por hora, para não pesar no preço nem no banco
COST_PCT = 4.0               # taxas + slippage de compra e venda, igual às sombras do Explorar
STOP_PCT = 30.0
MAX_KEEP = 20000
MIN_TRADER = 5


def _rows(trades: list[dict], aba_of) -> list[dict]:
    return [t for t in trades if not t.get("real") and aba_of(t) == ABA and float(t.get("pnl_pct") or 0) < SUSPECT_PCT]


def _ci(L: list[dict]) -> dict:
    return stats.ci_days([(stats.day_of(t.get("closed_at")), t.get("pnl_pct")) for t in L])


def trader_verdict(ci: dict, n: int, acerto: float, saldo: float) -> str:
    """"provado" e "ruim por faixa" exigem a faixa inteira de um lado do zero; o resto é pista."""
    if ci["lo"] is not None and ci["lo"] > 0:
        return "provado"
    if (ci["hi"] is not None and ci["hi"] < 0) or (n >= MIN_TRADER and acerto < 30 and saldo < 0):
        return "ruim"
    if n >= MIN_TRADER and saldo > 0:
        return "promissor"
    return "poucos dados"


def traders(L: list[dict]) -> list[dict]:
    g: dict[str, list] = {}
    for t in L:
        g.setdefault(t.get("wallet") or "?", []).append(t)
    out = []
    for w, R in g.items():
        ci = _ci(R)
        saldo = sum(float(t.get("pnl_sol") or 0) for t in R)
        acerto = round(sum(float(t.get("pnl_sol") or 0) > 0 for t in R) / len(R) * 100)
        out.append({"wallet": w, "trades": len(R), "dias": ci["dias"], "acerto": acerto, "saldo_sol": round(saldo, 6), "media_pct": ci["media"],
                    "lo": ci["lo"], "hi": ci["hi"], "veredito": trader_verdict(ci, len(R), acerto, saldo), **payoff(R)})
    return sorted(out, key=lambda x: (-(x["por_copia_pct"] if x["trades"] >= 3 else -1e9), -x["saldo_sol"]))


def payoff(R: list[dict]) -> dict:
    """0.32.275 (pedido do dono: "com stop de 40%, 10 perdas não se pagam com 20 ganhos de 10%"): o acerto sozinho engana.
    Ganho médio, perda média, resultado médio por cópia (o que importa), acerto que empata com essas médias e quanto os
    ganhos pagam das perdas (fator)."""
    P = [float(t.get("pnl_pct") or 0) for t in R]
    G, L = [x for x in P if x > 0], [-x for x in P if x <= 0]
    gs = sum(float(t.get("pnl_sol") or 0) for t in R if float(t.get("pnl_sol") or 0) > 0)
    ls = -sum(float(t.get("pnl_sol") or 0) for t in R if float(t.get("pnl_sol") or 0) < 0)
    gm, lm = (sum(G) / len(G) if G else 0.0), (sum(L) / len(L) if L else 0.0)
    return {"ganho_med_pct": round(gm, 2), "perda_med_pct": round(lm, 2), "por_copia_pct": round(sum(P) / len(P), 2) if P else 0.0,
            "acerto_empate": round(lm / (gm + lm) * 100) if gm + lm > 0 else None,
            "fator": round(gs / ls, 2) if ls > 0 else (None if gs == 0 else 99.0)}


def late(L: list[dict]) -> list[dict]:
    """Resultado estimado entrando no preço de alguns segundos depois, mantendo a mesma saída. Base = preço do trader, sem o slippage simulado."""
    out = []
    for m in MARCAS:
        A, H = [], []
        for t in L:
            px = (t.get("late") or {}).get(m)
            base = t.get("trader_px") or t.get("price_in")
            if not px or not base:
                continue
            A.append(float(t.get("pnl_pct") or 0))
            H.append((stats.day_of(t.get("closed_at")), ((1 + float(t.get("pnl_pct") or 0) / 100) * float(base) / float(px) - 1) * 100))
        ci = stats.ci_days(H)
        media = round(sum(A) / len(A), 2) if A else None
        out.append({"segundos": int(m), "n": len(A), "ficticia_pct": media, "honesta_pct": ci["media"], "lo": ci["lo"], "hi": ci["hi"],
                    "perda_pct": round(ci["media"] - media, 2) if A else None})
    return out


def study(trades: list[dict], aba_of) -> dict:
    L = _rows(trades, aba_of)
    ci = _ci(L)
    pnl = sorted((float(t.get("pnl_sol") or 0) for t in L), reverse=True)
    saldo = sum(pnl)
    inv = sum(float(t.get("sol_in") or 0) for t in L)
    return {"trades": len(L), "dias": ci["dias"], "saldo_sol": round(saldo, 6), "investido_sol": round(inv, 6), "pct": round(saldo / inv * 100, 2) if inv else None,
            "sem_top3_sol": round(sum(pnl[3:]), 6), "top3_sol": round(sum(pnl[:3]), 6), "ci": ci, "leitura": stats.reading(ci, "trades", "% por trade"),
            "traders": traders(L), "late": late(L), **payoff(L)}


def motivo(why: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[+\-−]?\d+(?:[.,]\d+)?", "#", str(why or "sem motivo"))).strip()[:80]


class Barred:
    """Compras barradas pelos filtros, acompanhadas como se tivessem entrado alguns segundos depois da compra do trader."""

    def __init__(self) -> None:
        self.items: dict[str, dict] = {}
        self.fora = 0

    def note(self, who: str, mint: str, symbol, why: str, t: float) -> None:
        key = f"{mint}|{who}"
        if key in self.items and t - self.items[key]["t0"] < 3600:
            return
        if sum(1 for x in self.items.values() if x.get("ret") is None) >= MAX_OPEN:
            self.fora += 1                 # sem vaga: fica de fora da conta, e a tela mostra quantas
            return
        self.items[key] = {"id": f"{key}|{int(t)}", "t0": t, "who": who, "mint": mint, "symbol": symbol, "why": str(why)[:160], "px0": None, "pico": 0.0, "fundo": 0.0, "parou": False, "ret": None}

    def mints(self) -> list[str]:
        return list({x["mint"] for x in self.items.values() if x.get("ret") is None})

    def tick(self, price, now: float) -> list[dict]:
        """`price(mint)` devolve o preço atual. Devolve as prontas. Sem preço no prazo: descarta, sem inventar resultado."""
        done = []
        for key, x in list(self.items.items()):
            if x.get("ret") is not None:
                continue
            px, age = price(x["mint"]), now - x["t0"]
            if x["px0"] is None:
                if px and age >= FIRST_S:
                    x["px0"] = px
                elif age > PRICE_S:
                    del self.items[key]
                continue
            if px:
                pct = (px / x["px0"] - 1) * 100
                if not x["parou"]:
                    x["pico"], x["fundo"] = max(x["pico"], pct), min(x["fundo"], pct)
                    x["parou"] = pct <= -STOP_PCT
                x["ultimo"] = pct
            if age >= WATCH_S and x.get("ultimo") is not None:
                x["ret"] = round((-STOP_PCT if x["parou"] else x["ultimo"]) - COST_PCT, 2)
                done.append(x)
                self.items[x["id"]] = self.items.pop(key)        # outra compra do mesmo token não apaga este resultado
            elif age > WATCH_S + PRICE_S:
                del self.items[key]
        for key in sorted(self.items, key=lambda k: self.items[k]["t0"])[:max(0, len(self.items) - MAX_KEEP)]:
            del self.items[key]
        return done

    def load(self, rows: list[dict]) -> None:
        for d in rows:
            if isinstance(d, dict) and d.get("mint") and d.get("who"):
                self.items[str(d.get("id") or f"{d['mint']}|{d['who']}|{d.get('t0')}")] = d

    def study(self) -> dict:
        g: dict[str, list] = {}
        P = [x for x in self.items.values() if x.get("ret") is not None and x["ret"] < SUSPECT_PCT]
        for x in P:
            g.setdefault(motivo(x["why"]), []).append(x)
        out = []
        for nome, L in g.items():
            ci = stats.ci_days([(stats.day_of(x["t0"]), x["ret"]) for x in L])
            if ci["lo"] is None:
                vd = "poucos dados"
            else:
                vd = "pode estar barrando ganhos" if ci["lo"] > 0 else "filtro ajudou" if ci["hi"] < 0 else "sem conclusão"
            out.append({"motivo": nome, "exemplo": L[0]["why"], "n": len(L), "dias": ci["dias"], "ganharia": sum(x["ret"] > 0 for x in L), "media_pct": ci["media"], "lo": ci["lo"], "hi": ci["hi"], "veredito": vd})
        return {"prontas": len(P), "abertas": sum(1 for x in self.items.values() if x.get("ret") is None), "fora": self.fora, "motivos": sorted(out, key=lambda x: -x["n"])}
