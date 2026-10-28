"""Calls quentes pela blockchain (0.31.94, pedido do dono em 2026-10-28).

Os "Hot callouts" e as conversas da pump.fun vêm da API privada do site, atrás do desafio anti-robô da Cloudflare
(HTTP 403 "Just a moment...", conferido em 2026-10-28) — não é lido. A call de verdade é a COMPRA da carteira de quem
chama: toda compra de uma carteira acompanhada (Maiores traders, Carteiras em estudo, traders copiados) vira uma call.

Para cada call: preço de quem entraria 1 min depois (o seguidor), o preço aos 5, 15 e 60 min, o pico, e se o caller
vendeu logo depois (despejou em quem entrou). A nota do caller é o que ele dá para QUEM SEGUE, já com o custo, e não o
lucro dele. O veredito de cada call nova junta a nota do caller, quantos callers compraram o mesmo token e o token.
Só estudo e tela: nada é comprado sozinho.
"""
from __future__ import annotations

import time

COST_PCT = 4.0                 # taxas + slippage de entrar e sair, aproximado (o mesmo das sombras)
FOLLOW_S = 60                  # o seguidor entra 1 min depois da call
MARKS = (300, 900, 3600)       # 5, 15 e 60 min
DUMP_S = 600                   # vendeu metade ou mais até 10 min depois = despejou
MIN_CALLS = 5                  # nota do caller só com 5+ calls medidas
MAX_OPEN = 400
WAVE_S = 600                   # outros callers no mesmo token em 10 min


def _wilson_lo(k: int, n: int, z: float = 1.6449) -> float:
    if n <= 0:
        return 0.0
    p = k / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / (1 + z * z / n)
    return max(0.0, c - h)


class Calls:
    def __init__(self):
        self.calls: dict[str, dict] = {}          # id -> call
        self.dirty: set[str] = set()

    # ------------------------------------------------------------------ registro
    def on_trade(self, w: str, ev: dict, t: float, label: str, fonte: str, price: float | None) -> dict | None:
        mint, kind = ev.get("mint"), ev.get("txType")
        if not mint or kind not in ("buy", "sell"):
            return None
        open_ = next((c for c in self.calls.values() if c["wallet"] == w and c["mint"] == mint and t - c["t"] < 6 * 3600), None)
        if kind == "sell":
            if open_ is not None:
                tok = float(ev.get("tokenAmount") or 0)
                open_["vendido_tok"] = open_.get("vendido_tok", 0.0) + tok
                if open_.get("venda_s") is None:
                    open_["venda_s"] = round(t - open_["t"], 1)
                if open_.get("despejo_s") is None and open_.get("tok") and open_["vendido_tok"] >= open_["tok"] * 0.5:
                    open_["despejo_s"] = round(t - open_["t"], 1)
                self.dirty.add(open_["id"])
            return None
        if open_ is not None:                     # recompra do mesmo caller: soma na mesma call
            open_["sol"] = round(open_["sol"] + float(ev.get("solAmount") or 0), 4)
            open_["tok"] = open_.get("tok", 0.0) + float(ev.get("tokenAmount") or 0)
            self.dirty.add(open_["id"])
            return None
        cid = f"{w}:{mint}:{int(t)}"
        c = {"id": cid, "wallet": w, "mint": mint, "symbol": ev.get("symbol"), "t": t, "label": label, "fonte": fonte,
             "sol": round(float(ev.get("solAmount") or 0), 4), "tok": float(ev.get("tokenAmount") or 0),
             "mcap_sol": ev.get("marketCapSol"), "px_call": price, "px1": None, "marcas": {}, "pico": None}
        self.calls[cid] = c
        self.dirty.add(cid)
        if len(self.calls) > MAX_OPEN * 5:
            for k in sorted(self.calls, key=lambda k: self.calls[k]["t"])[:len(self.calls) - MAX_OPEN * 5]:
                self.calls.pop(k, None)
        return c

    def open_mints(self, t: float) -> list[str]:
        return list(dict.fromkeys(c["mint"] for c in self.calls.values() if not c.get("fim") and t - c["t"] <= MARKS[-1] + 600))

    # ------------------------------------------------------------------ medição
    def tick(self, price_of, t: float) -> int:
        done = 0
        for c in self.calls.values():
            if c.get("fim"):
                continue
            age = t - c["t"]
            px = price_of(c["mint"])
            if c["px1"] is None:
                if px and age >= FOLLOW_S:
                    c["px1"] = px
                    self.dirty.add(c["id"])
                elif age > FOLLOW_S + 300:
                    c["fim"] = "sem preço"
                    self.dirty.add(c["id"])
                continue
            if px:
                r = (px / c["px1"] - 1) * 100
                if c["pico"] is None or r > c["pico"]:
                    c["pico"] = round(r, 2)
                for m in MARKS:
                    if age >= m + FOLLOW_S and str(m) not in c["marcas"] and age <= m + FOLLOW_S + 300:
                        c["marcas"][str(m)] = round(r, 2)
                        self.dirty.add(c["id"])
            if age > MARKS[-1] + FOLLOW_S + 300:
                c["fim"] = "medida"
                done += 1
                self.dirty.add(c["id"])
        return done

    # ------------------------------------------------------------------ aprendizado
    @staticmethod
    def result(c: dict) -> float | None:
        """Resultado de quem seguiu: preço 15 min depois de entrar, menos o custo."""
        r = (c.get("marcas") or {}).get(str(MARKS[1]))
        return None if r is None else round(r - COST_PCT, 2)

    def callers(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for c in self.calls.values():
            d = out.setdefault(c["wallet"], {"wallet": c["wallet"], "label": c.get("label"), "fonte": c.get("fonte"),
                                             "calls": 0, "medidas": 0, "ganhou": 0, "soma": 0.0, "despejou": 0, "picos50": 0})
            d["calls"] += 1
            r = self.result(c)
            if r is not None:
                d["medidas"] += 1
                d["ganhou"] += r > 0
                d["soma"] += r
                d["picos50"] += (c.get("pico") or 0) >= 50
            d["despejou"] += c.get("despejo_s") is not None and c["despejo_s"] <= DUMP_S
        for d in out.values():
            n = d["medidas"]
            d["acerto"] = round(d["ganhou"] / n, 3) if n else None
            d["media_pct"] = round(d["soma"] / n, 1) if n else None
            d["despejo_pct"] = round(d["despejou"] / d["calls"] * 100, 1) if d["calls"] else 0.0
            # nota 0–100: acerto mínimo provável (Wilson 90%) de quem segue, menos a taxa de despejo
            d["nota"] = round(max(0.0, _wilson_lo(d["ganhou"], n) * 100 - d["despejo_pct"] * 0.3), 1) if n >= MIN_CALLS else None
            d.pop("soma")
        return out

    def verdict(self, c: dict, callers: dict, risk_of=None, blacklisted=None) -> dict:
        """Veredito da call (0–100%): nota do caller + outros callers no mesmo token + o token."""
        why = []
        if blacklisted and blacklisted(c["mint"]):
            return {"verdict": "lixo", "chance": 0, "why": ["criador ou token na lista negra"]}
        d = callers.get(c["wallet"]) or {}
        base = d.get("nota")
        if base is None:
            base = 30.0
            why.append(f"caller novo ({d.get('medidas', 0)}/{MIN_CALLS} calls medidas)")
        else:
            why.append(f"nota do caller {base:.0f}")
        others = {x["wallet"] for x in self.calls.values() if x["mint"] == c["mint"] and x["wallet"] != c["wallet"]
                  and abs(x["t"] - c["t"]) <= WAVE_S}
        good = [w for w in others if (callers.get(w) or {}).get("nota") is not None and callers[w]["nota"] >= 40]
        score = base + min(20, 7 * len(others)) + 5 * len(good)
        if others:
            why.append(f"+{len(others)} caller(s) no mesmo token em 10 min" + (f" ({len(good)} bons)" if good else ""))
        if (d.get("despejo_pct") or 0) >= 40:
            score -= 15
            why.append(f"caller despeja em quem entra ({d['despejo_pct']:.0f}% das calls)")
        rk = risk_of(c["mint"]) if risk_of else None
        if rk is not None and rk >= 7:
            score -= 15
            why.append(f"risco do token {rk:.0f}/10")
        mc = c.get("mcap_sol")
        if mc is not None and float(mc) < 30:
            score -= 10
            why.append("market cap muito baixo na call")
        score = max(0.0, min(100.0, score))
        v = "chance alta" if score >= 65 else "possível" if score >= 45 else "fraco" if score >= 25 else "lixo"
        return {"verdict": v, "chance": round(score), "why": why}

    def for_wallets(self, wallets: set, hours: float = 24, now: float | None = None) -> list[dict]:
        """0.31.96: compras (calls) de um grupo de carteiras — as Carteiras em estudo do Radar —, mais novas primeiro."""
        now = time.time() if now is None else now
        return sorted((c for c in self.calls.values() if c["wallet"] in wallets and now - c["t"] <= hours * 3600), key=lambda c: -c["t"])

    @staticmethod
    def waves(buys: list[dict], minimum: int, window_s: float) -> list[dict]:
        """0.31.96: ondas a partir das calls GUARDADAS (sobrevivem ao reinício): N carteiras distintas comprando o mesmo
        token dentro da janela. Uma onda por token (a de mais carteiras)."""
        by: dict[str, list] = {}
        for c in buys:
            by.setdefault(c["mint"], []).append(c)
        out = []
        for mint, L in by.items():
            L = sorted(L, key=lambda c: c["t"])
            best = []
            for i, c in enumerate(L):
                grp = {}
                for x in L[i:]:
                    if x["t"] - c["t"] > window_s:
                        break
                    grp.setdefault(x["wallet"], x)
                if len(grp) > len(best):
                    best = list(grp.values())
            if len(best) >= minimum:
                out.append({"mint": mint, "symbol": best[0].get("symbol"), "inicio": best[0]["t"], "fim": best[-1]["t"],
                            "carteiras": [{"wallet": x["wallet"], "label": x.get("label"), "t": x["t"], "sol": x.get("sol"),
                                           "despejou": x.get("despejo_s") is not None} for x in best],
                            "sol": round(sum(x.get("sol") or 0 for x in best), 4),
                            "resultado": [Calls.result(x) for x in best if Calls.result(x) is not None][:1] or [None]})
        return sorted(out, key=lambda w: -w["inicio"])

    def summary(self, now: float | None = None, risk_of=None, blacklisted=None) -> dict:
        now = time.time() if now is None else now
        cl = self.callers()
        recent = sorted((c for c in self.calls.values() if now - c["t"] <= 3600), key=lambda c: -c["t"])[:150]
        rows = []
        for c in recent:
            r = dict(c, veredito=self.verdict(c, cl, risk_of, blacklisted), resultado=self.result(c),
                     caller=cl.get(c["wallet"], {}).get("nota"))
            rows.append(r)
        med = [c for c in self.calls.values() if self.result(c) is not None]
        by_v: dict[str, list] = {}
        for c in med:
            by_v.setdefault((c.get("veredito_na_call") or {}).get("verdict") or "sem veredito", []).append(self.result(c))
        return {"agora": sorted(rows, key=lambda r: -r["veredito"]["chance"]),
                "callers": sorted(cl.values(), key=lambda d: (d["nota"] is None, -(d["nota"] or 0), -d["calls"]))[:60],
                "medidas": len(med), "total": len(self.calls),
                "por_veredito": [{"veredito": k, "n": len(v), "acerto": round(sum(1 for x in v if x > 0) / len(v), 3),
                                  "media_pct": round(sum(v) / len(v), 1)} for k, v in by_v.items()]}
