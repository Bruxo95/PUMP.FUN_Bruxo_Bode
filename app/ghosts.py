"""Estratégias fantasma (0.18.0, pedido do dono em 2026-10-26).

Cada cópia fictícia aberta também abre uma posição "fantasma" em cada variante abaixo, com a MESMA entrada (mesmo
preço, mesmas taxas). Cada variante sai por uma regra diferente. Em poucos dias dá para ver qual regra de saída
rende mais com os seus traders, sem arriscar nada e sem mexer na sua carteira fictícia.
Só simula: nada aqui compra, vende ou grava posição. O resultado agregado fica na tabela ghost_stats (uma linha por
usuário); posições fantasma abertas vivem só na memória e somem se o servidor reiniciar.
"""
from __future__ import annotations

from datetime import datetime, timezone

BASE = {"stop": 40.0, "trail": None, "tp1": None, "tp": None, "max_s": 6 * 3600.0, "follow": True, "dev": False,
        "migrate": False, "stale": None}
VARIANTS = [
    ("base", "Base: stop 40%, sai quando o trader vende", {}),
    ("stop20", "Stop de perda curto (20%)", {"stop": 20.0}),
    ("stop60", "Stop de perda largo (60%)", {"stop": 60.0}),
    ("trail_justo", "Stop móvel justo (liga em +10%, sai 5 pontos abaixo do pico)", {"trail": (10.0, 5.0)}),
    ("trail_largo", "Stop móvel largo (liga em +30%, sai 20 pontos abaixo do pico)", {"trail": (30.0, 20.0)}),
    ("partes", "Venda em partes (em +30% vende metade)", {"tp1": (30.0, 50.0)}),
    ("alvo50", "Alvo fixo +50%", {"tp": 50.0}),
    ("alvo100", "Alvo fixo +100%", {"tp": 100.0}),
    ("sem_trader", "Ignora a venda do trader (stop 40% + stop móvel +20%/10)", {"follow": False, "trail": (20.0, 10.0)}),
    ("rapido", "Sai em no máximo 5 minutos", {"max_s": 300.0}),
    ("dev", "Sai quando o dev vende (0.19.0)", {"dev": True}),
    ("migra", "Sai quando o token gradua (0.19.0)", {"migrate": True}),
    ("parado45", "Sai se ficar parado 45 min (entre -5% e +5%) (0.31.10)", {"stale": 45.0}),
    ("max1h", "Tempo máximo de 1 h (0.31.10)", {"max_s": 3600.0}),
]
NAMES = {v: n for v, n, _ in VARIANTS}

# Fantasmas das compras automáticas do Explorar (0.31.21, pedido do dono em 2026-10-26: "tive mais perdas do que
# ganhos"). Base = proteções sugeridas das automáticas; cada variante muda UMA coisa. "press" = depois de X min, sai se
# a pressão de compra cair abaixo de 40% (None = não usa); "migrate" = sai quando gradua; "dev" = sai quando o dev vende.
AUTO_BASE = {"stop": 25.0, "trail": (40.0, 15.0), "tp1": (40.0, 50.0), "tp": 150.0, "max_s": 1800.0, "follow": False,
             "dev": True, "migrate": True, "stale": None, "press": 1.0}
AUTO_VARIANTS = [
    ("a_base", "Proteções sugeridas (stop 25%, metade em +40%, móvel +40/15, alvo 150%, 30 min)", {}),
    ("a_stop15", "Stop de perda curto (15%)", {"stop": 15.0}),
    ("a_stop40", "Stop de perda largo (40%)", {"stop": 40.0}),
    ("a_press3", "Saída por pressão só depois de 3 min", {"press": 3.0}),
    ("a_sem_press", "Sem saída por pressão de compra", {"press": None}),
    ("a_segura_grad", "Não sai quando o token gradua", {"migrate": False}),
    ("a_rapido", "Tempo máximo de 10 min", {"max_s": 600.0}),
    ("a_trail_justo", "Stop móvel justo (liga em +15%, sai 8 pontos abaixo do pico)", {"trail": (15.0, 8.0)}),
    ("a_alvo60", "Alvo fixo +60% (sem venda em partes)", {"tp": 60.0, "tp1": None}),
]
KEEP = 30            # últimos fechados guardados por variante
MAX_OPEN = 840       # trava de memória (14 variantes × 60 posições)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")      # mesmo formato do motor (pumpfun.now_iso)


def _ts(x) -> float:
    try:
        d = datetime.fromisoformat(str(x).replace("Z", "+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()
    except (TypeError, ValueError):
        return 0.0


def params(vid: str, variants=None, base=None) -> dict:
    over = next((o for v, _, o in (variants or VARIANTS) if v == vid), {})
    return {"press": None, **(base or BASE), **over}


class Ghosts:
    def __init__(self, pf, variants=None, base=None, mine=None):
        self.pf = pf
        self.variants, self.base = variants or VARIANTS, base or BASE
        self.names = {v: n for v, n, _ in self.variants}
        # quais trades fechados são "as suas regras atuais" para comparar (cópias por padrão; o Explorar passa o seu)
        self.mine = mine or (lambda t: not t.get("manual") and not t.get("auto"))
        self.open: list[dict] = []
        self.stats: dict[str, dict] = {}
        self.since: str | None = None
        self.dirty = False

    # ------------------------------------------------------------------ estado
    def mints(self) -> set:
        return {g["mint"] for g in self.open}

    def reset(self) -> None:
        self.open, self.stats, self.since, self.dirty = [], {}, None, True

    def dump(self) -> dict:
        # 0.31.99 (item 1, pedido do dono: muitos deploys por dia): as posições fantasma abertas também vão para o banco,
        # senão cada reinício jogava fora os testes de regra de saída em andamento
        return {"since": self.since, "stats": self.stats, "open": self.open[-600:]}

    def load(self, d: dict | None) -> None:
        import time as _t
        d = d or {}
        self.since = d.get("since")
        self.stats = {k: v for k, v in (d.get("stats") or {}).items() if k in self.names}
        self.open = [g for g in d.get("open") or [] if isinstance(g, dict) and g.get("v") in self.names
                     and _t.time() - float(g.get("open_t") or 0) < 24 * 3600]
        self._drop_suspect()

    def _drop_suspect(self) -> None:
        """0.31.65 (pedido do dono, "sem os ganhos falsos"): tira das somas guardadas os fechamentos com ganho de +1.900% ou
        mais (preço de token cotado em outra moeda, antes da 0.31.52: SEALLIS, R1R2L1R2…). Eles faziam todas as regras
        parecerem +325 SOL e o Ajuste automático poderia escolher uma regra por números que não aconteceram."""
        from .auto_trades import SUSPECT_PCT
        for s in self.stats.values():
            bad = [r for r in s.get("recent") or [] if (r.get("pnl_pct") or 0) >= SUSPECT_PCT]
            if not bad:
                continue
            for r in bad:
                pnl = r.get("pnl_sol") or 0
                s["trades"] = max(0, (s.get("trades") or 0) - 1)
                s["wins"] = max(0, (s.get("wins") or 0) - (1 if pnl > 0 else 0))
                s["pnl_sol"] = round((s.get("pnl_sol") or 0) - pnl, 6)
                if r.get("pnl_pct"):
                    s["invested_sol"] = round(max(0.0, (s.get("invested_sol") or 0) - pnl / (r["pnl_pct"] / 100)), 6)
                s["best_sum"] = round((s.get("best_sum") or 0) - (r.get("best") or 0), 2)
            s["recent"] = [r for r in s.get("recent") or [] if r not in bad]
            self.dirty = True

    # ------------------------------------------------------------------ eventos do motor
    def on_open(self, p: dict, t: float) -> None:
        if len(self.open) >= MAX_OPEN:
            return
        self.since = self.since or now_iso()
        for vid, _, _ in self.variants:
            self.open.append({"v": vid, "mint": p["mint"], "wallet": p["wallet"], "symbol": p.get("symbol"),
                              "sol_in": p["sol_in"], "tokens": p["tokens"], "left": p["tokens"], "proceeds": 0.0,
                              "open_t": t, "opened_at": p.get("opened_at") or now_iso(), "peak": None,
                              "tp1_done": False, "best": 0.0, "worst": 0.0,
                              "grad_in": self.pf.graduated(p["mint"])})
        self.dirty = True                                  # 0.31.99: grava também as abertas

    def on_price(self, mint: str, px: float | None, t: float) -> None:
        if not px:
            return
        for g in [g for g in self.open if g["mint"] == mint]:
            P = self.params(g["v"])
            chg = self._chg(g, px)
            g["best"], g["worst"] = max(g["best"], chg), min(g["worst"], chg)
            tk = self.pf.tokens.get(mint) or {}
            if P["dev"] and tk.get("dev_sold_t") and tk["dev_sold_t"] >= g["open_t"]:
                self._sell(g, 1.0, px, "dev vendeu")
                continue
            if P["migrate"] and g.get("grad_in") is False and self.pf.graduated(mint):
                self._sell(g, 1.0, px, "token graduou")
                continue
            if P.get("press") and t and t - g["open_t"] >= P["press"] * 60:
                pr, _ = self.pf.pressure(mint)
                if pr is not None and pr < 40:
                    self._sell(g, 1.0, px, "pressão de compra virou")
                    continue
            if P["stale"] and t and t - g["open_t"] >= P["stale"] * 60 and abs(chg) <= 5:
                self._sell(g, 1.0, px, "parado")
                continue
            if P["trail"]:
                start, dist = P["trail"]
                if g["peak"] is not None or chg >= start:
                    g["peak"] = max(g["peak"] if g["peak"] is not None else chg, chg)
                    if chg <= g["peak"] - dist:
                        self._sell(g, 1.0, px, "stop móvel")
                        continue
            if P["tp1"] and not g["tp1_done"] and chg >= P["tp1"][0]:
                g["tp1_done"] = True
                self._sell(g, P["tp1"][1] / 100, px, "venda em partes")
                continue
            if chg <= -P["stop"]:
                self._sell(g, 1.0, px, "stop de perda")
            elif P["tp"] and chg >= P["tp"]:
                self._sell(g, 1.0, px, "alvo")
            elif t and t - g["open_t"] >= P["max_s"]:
                self._sell(g, 1.0, px, "tempo máximo")

    def on_trader_sell(self, who: str, mint: str, frac: float, px: float | None, t: float) -> None:
        if not px or frac < 0.01:
            return
        for g in [g for g in self.open if g["mint"] == mint and g["wallet"] == who]:
            if self.params(g["v"])["follow"]:
                self._sell(g, frac, px, "trader vendeu")

    def on_time(self, t: float) -> None:
        for g in list(self.open):
            if t - g["open_t"] >= self.params(g["v"])["max_s"]:
                px = (self.pf.tokens.get(g["mint"]) or {}).get("price")
                if px:
                    self._sell(g, 1.0, px, "tempo máximo")
                elif t - g["open_t"] >= self.params(g["v"])["max_s"] + 3600:
                    self._sell(g, 1.0, 0.0, "sem preço")           # token sumiu: conta como perda total

    def params(self, vid: str) -> dict:
        return params(vid, self.variants, self.base)

    # ------------------------------------------------------------------ contas (mesmas taxas da cópia fictícia)
    def _value(self, g: dict, px: float) -> float:
        fr = self.pf._fee_rates(g["mint"])
        return max(0.0, g["left"] * px * (1 - fr["slip"]) * (1 - fr["venue"] - fr["portal"]) - fr["prio"])

    def _chg(self, g: dict, px: float) -> float:
        cost = g["sol_in"] * (g["left"] / g["tokens"]) if g["tokens"] else 0
        return (self._value(g, px) / cost - 1) * 100 if cost else 0.0

    def _sell(self, g: dict, frac: float, px: float, why: str) -> None:
        fr = self.pf._fee_rates(g["mint"])
        qty = g["left"] * min(1.0, frac)
        got = max(0.0, qty * px * (1 - fr["slip"]) * (1 - fr["venue"] - fr["portal"]) - fr["prio"]) if px else 0.0
        g["left"] -= qty
        g["proceeds"] += got
        if g["left"] <= g["tokens"] * 0.005 or frac >= 1.0:
            self._close(g, why)

    def _close(self, g: dict, why: str) -> None:
        if g in self.open:
            self.open.remove(g)
        pnl = g["proceeds"] - g["sol_in"]
        from .auto_trades import SUSPECT_PCT
        if g["sol_in"] and pnl / g["sol_in"] * 100 >= SUSPECT_PCT:
            return                                   # 0.31.65: ganho de preço lido errado não entra nas somas
        s = self.stats.setdefault(g["v"], {"trades": 0, "wins": 0, "pnl_sol": 0.0, "invested_sol": 0.0,
                                           "best_sum": 0.0, "recent": []})
        s["trades"] += 1
        s["wins"] += 1 if pnl > 0 else 0
        s["pnl_sol"] = round(s["pnl_sol"] + pnl, 6)
        s["invested_sol"] = round(s["invested_sol"] + g["sol_in"], 6)
        s["best_sum"] = round(s["best_sum"] + g["best"], 2)
        s["recent"] = ([{"at": now_iso(), "symbol": g.get("symbol"), "mint": g["mint"], "pnl_sol": round(pnl, 6),
                         "pnl_pct": round(pnl / g["sol_in"] * 100, 2) if g["sol_in"] else None, "why": why,
                         "best": round(g["best"], 1)}] + s["recent"])[:KEEP]
        self.dirty = True

    # ------------------------------------------------------------------ tela
    def snapshot(self, trades: list[dict]) -> dict:
        def row(vid, name, n, wins, pnl, inv, best_sum, opened):
            return {"id": vid, "nome": name, "trades": n, "win_rate": (wins / n) if n else None,
                    "pnl_sol": round(pnl, 6), "roi_pct": round(pnl / inv * 100, 2) if inv else None,
                    "avg_best_pct": round(best_sum / n, 1) if n else None, "open": opened}
        rows = []
        for vid, name, _ in self.variants:
            s = self.stats.get(vid) or {}
            rows.append(row(vid, name, s.get("trades", 0), s.get("wins", 0), s.get("pnl_sol", 0.0),
                            s.get("invested_sol", 0.0), s.get("best_sum", 0.0),
                            sum(1 for g in self.open if g["v"] == vid)))
        # as SUAS regras atuais, no mesmo período (trades fictícios fechados desde o início dos fantasmas)
        # compara como horário, não como texto: "…:05+00:00" < "…:05.123+00:00" no texto (falhou no CI da 0.18.0)
        since = _ts(self.since) if self.since else None
        mine = [t for t in trades if not t.get("real") and self.mine(t) and since is not None and _ts(t.get("closed_at")) >= since]
        n, wins = len(mine), sum(1 for t in mine if (t.get("pnl_sol") or 0) > 0)
        best = sum((t.get("best_pct") or 0) for t in mine)
        yours = row("suas", "Suas regras atuais (carteira fictícia)", n, wins, sum(t.get("pnl_sol") or 0 for t in mine),
                    sum(t.get("sol_in") or 0 for t in mine), best,
                    sum(1 for p in self.pf.positions() if not p.get("real")))
        ranked = sorted([r for r in rows if r["trades"]], key=lambda r: -r["pnl_sol"])
        return {"since": self.since, "yours": yours, "variants": rows,
                "best": ranked[0]["id"] if ranked else None,
                "recent": {vid: (self.stats.get(vid) or {}).get("recent", [])[:10] for vid, _, _ in self.variants}}
