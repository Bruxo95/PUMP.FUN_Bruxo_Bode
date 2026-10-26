"""Base própria da pump.fun (0.21.0, pedido do dono em 2026-10-26): ficha de vida de cada token novo.

O monitor já recebe TODO token criado (PumpPortal, grátis). Aqui cada um ganha 4 fotos do market cap (1, 5, 15 e
60 min depois de criado, lidas direto da curva on-chain, 1 consulta para até 100 tokens) e um rótulo no fim:
"graduou", "5x", "2x", "despencou", "subiu pouco" ou "morreu". Com isso:
- histórico do CRIADOR (quantos tokens, quantos deram 2x+, quantos despencaram) → entra na nota da entrada e o
  criador que só despenca vai para a lista negra;
- visão de MERCADO por hora (criados, % que deu 2x, graduou, despencou) e as palavras dos tokens que subiram.
Limites honestos: só 4 fotos (o pico real entre elas não é visto); no máx. MAX_PER_MIN tokens novos por minuto
entram (o resto só é contado); dados brutos não são guardados — só os resumos e os tokens "interessantes".
"""
from __future__ import annotations

import re
import time
from collections import deque
from datetime import datetime, timezone

SNAPS = (1, 5, 15, 60)                 # minutos de vida em que tira a foto
MAX_PER_MIN = 40
MAX_LIVE = 4000
INTERESTING = ("graduou", "5x", "2x", "despencou")
UP = ("graduou", "5x", "2x")
KEEP_DAYS = 14                         # 0.24.0: o dono pediu para guardar e estudar todos os tokens
KEEP_DONE = 30000
STOP = {"the", "of", "and", "a", "to", "in", "on", "coin", "token", "pump", "fun", "sol", "solana", "inu", "ai"}


def _hour(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:00:00+00:00")


def label(mcap0: float | None, snaps: dict, graduated: bool) -> str:
    vals = [v for v in snaps.values() if v]
    if graduated:
        # já nasceu com a curva completa (o criador comprou quase tudo): não "subiu" nada (visto no GTA6, 2026-10-26)
        # (a foto de quem gradua guarda o market cap anterior, então só o valor da criação serve de sinal)
        if mcap0 and mcap0 >= 300:
            return "nasceu graduado"
        return "graduou"
    if not mcap0 or not vals:
        return "sem dado"
    peak, last = max(vals), vals[-1]
    if peak >= mcap0 * 5:
        return "5x"
    if peak >= mcap0 * 2:
        return "2x"
    if last < peak * 0.5 and peak > mcap0 * 1.2:
        return "despencou"
    if last <= mcap0 * 1.1:
        return "morreu"
    return "subiu pouco"


class TokenLab:
    def __init__(self, market):
        self.market = market
        self.live: dict[str, dict] = {}
        self.done: deque = deque(maxlen=KEEP_DONE)     # resumos (memória) para a tela e o aprendizado
        self._lessons = (0.0, None)
        self.creators: dict[str, dict] = market.creator_stats      # compartilhado: a nota da entrada lê daqui
        self.hours: dict[str, dict] = {}
        self.new_rows: list[dict] = []                  # tokens interessantes ainda não gravados
        self.dirty_creators: set[str] = set()
        self.dirty_hours: set[str] = set()
        self.dropped = 0
        self._minute = (0, 0)
        self.since = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # ------------------------------------------------------------------ entrada
    def on_create(self, ev: dict, t: float) -> None:
        mint = ev.get("mint")
        if not mint or mint in self.live:
            return
        m = int(t // 60)
        n = self._minute[1] + 1 if self._minute[0] == m else 1
        self._minute = (m, n)
        h = self.hours.setdefault(_hour(t), {"created": 0, "tracked": 0, "labels": {}})
        h["created"] += 1
        self.dirty_hours.add(_hour(t))
        if n > MAX_PER_MIN or len(self.live) >= MAX_LIVE:
            self.dropped += 1
            return
        h["tracked"] += 1
        mc = ev.get("marketCapSol")
        self.live[mint] = {"mint": mint, "creator": ev.get("traderPublicKey"), "symbol": str(ev.get("symbol") or "")[:20],
                           "name": str(ev.get("name") or "")[:40], "t0": t, "mcap0": float(mc) if mc else None,
                           "snaps": {}, "dev_buy": float(ev.get("solAmount") or 0)}

    def due(self, t: float) -> list[str]:
        out = []
        for mint, r in self.live.items():
            nxt = next((k for k in SNAPS if str(k) not in r["snaps"]), None)
            if nxt is not None and t - r["t0"] >= nxt * 60:
                out.append(mint)
        return out

    def observe(self, t: float, mints: list[str]) -> int:
        """Depois que o monitor atualizou o preço (curva on-chain) desses tokens: tira a foto que estava vencida."""
        n = 0
        for mint in mints:
            r = self.live.get(mint)
            if not r:
                continue
            tk = self.market.tokens.get(mint) or {}
            grad = tk.get("pool") in ("pumpswap", "pump-amm")
            for k in SNAPS:
                if str(k) not in r["snaps"] and t - r["t0"] >= k * 60:
                    r["snaps"][str(k)] = round(float(tk["mcap_sol"]), 2) if tk.get("mcap_sol") else None
                    break
            n += 1
            if grad or len(r["snaps"]) == len(SNAPS):
                self.finalize(r, grad, t)
        return n

    # ------------------------------------------------------------------ fim da observação
    def finalize(self, r: dict, grad: bool, t: float) -> dict:
        self.live.pop(r["mint"], None)
        lab = label(r["mcap0"], r["snaps"], grad)
        vals = [v for v in r["snaps"].values() if v]
        out = {"mint": r["mint"], "creator": r["creator"], "symbol": r["symbol"], "name": r["name"], "label": lab,
               "mcap0": r["mcap0"], "snaps": r["snaps"], "peak": max(vals) if vals else None,
               "created_at": datetime.fromtimestamp(r["t0"], timezone.utc).isoformat(timespec="seconds"),
               "dev_buy": r["dev_buy"], "boost": bool((self.boost(r["mint"]) or {}).get("active")),
               "creator_before": dict(self.creators.get(r["creator"]) or {}) if r["creator"] else None}
        self.done.append(out)
        hk = _hour(r["t0"])
        h = self.hours.setdefault(hk, {"created": 0, "tracked": 0, "labels": {}})
        h["labels"][lab] = h["labels"].get(lab, 0) + 1
        self.dirty_hours.add(hk)
        cr = r["creator"]
        if cr and lab != "sem dado":
            c = self.creators.setdefault(cr, {"tokens": 0, "x2": 0, "rugs": 0})
            c["tokens"] += 1
            c["x2"] += 1 if lab in ("graduou", "5x", "2x") else 0
            c["rugs"] += 1 if lab == "despencou" else 0
            self.dirty_creators.add(cr)
            # criador que já despencou 3+ tokens e nunca deu 2x entra na lista negra compartilhada (0.20.0)
            bl = getattr(self.market, "blacklist", None)
            if bl is not None and c["rugs"] >= 3 and not c["x2"] and cr not in bl:
                bl[cr] = {"tipo": "dev", "motivo": f"{c['rugs']} tokens despencaram (base da pump.fun)",
                          "criado_em": out["created_at"]}
                self.market.bl_new.append(cr)
        if lab != "sem dado":                       # desde a 0.24.0 guarda todos para estudar (antes só os interessantes)
            self.new_rows.append(out)
        return out

    def rising(self, t: float, n: int = 15) -> list[dict]:
        """Tokens ainda em observação que mais subiram desde a criação (pela última foto) — para comprar a tempo."""
        out = []
        for r in self.live.values():
            vals = [v for v in r["snaps"].values() if v]
            if not vals or not r["mcap0"]:
                continue
            tk = self.market.tokens.get(r["mint"]) or {}
            out.append({"mint": r["mint"], "symbol": r["symbol"], "name": r["name"], "creator": r["creator"],
                        "mcap0": r["mcap0"], "mcap": vals[-1], "gain_pct": round((vals[-1] / r["mcap0"] - 1) * 100, 1),
                        "age_min": round((t - r["t0"]) / 60, 1), "fotos": len(r["snaps"]),
                        "price": bool(tk.get("price")), "creator_stats": self.creator_info(r["creator"]),
                        "boost": self.boost(r["mint"])})
        return sorted([x for x in out if x["gain_pct"] > 0], key=lambda x: -x["gain_pct"])[:n]

    def boost(self, mint: str) -> dict | None:
        b = dict(getattr(self.market, "boosts", {}).get(mint) or {})
        if (self.market.tokens.get(mint) or {}).get("boost_active"):
            b["active"] = True
        return b or None

    def lessons(self, t: float | None = None) -> dict:
        """O que a base aprendeu (0.24.0): para cada sinal visto nos primeiros minutos, quantos % dos tokens
        acabaram subindo (graduou/5x/2x) ou despencando. Usa tudo que está guardado (até 14 dias)."""
        t = t or time.time()
        if self._lessons[1] is not None and t - self._lessons[0] < 60:
            return self._lessons[1]
        rows = [r for r in self.done if r.get("label") not in (None, "sem dado", "nasceu graduado") and r.get("mcap0")]
        base_up = sum(1 for r in rows if r["label"] in UP) / len(rows) * 100 if rows else None

        def gain(r, k):
            v = (r.get("snaps") or {}).get(k)
            return (v / r["mcap0"] - 1) * 100 if v else None

        def bucket_gain(g):
            if g is None:
                return None
            return "caiu" if g < 0 else "0 a 30%" if g < 30 else "30 a 100%" if g < 100 else "mais de 100%"

        def dev(r):
            x = float(r.get("dev_buy") or 0)
            return "nada" if x <= 0 else "até 1 SOL" if x < 1 else "1 a 3 SOL" if x < 3 else "mais de 3 SOL"

        def creator(r):
            c = r.get("creator_before")
            if not c or not c.get("tokens"):
                return "criador novo"
            if c.get("x2"):
                return "já fez token que subiu"
            return "só despencou antes" if c.get("rugs") else "tokens parados antes"

        def hour(r):
            try:
                return int(str(r.get("created_at"))[11:13])
            except ValueError:
                return None

        def table(name, fn, order=None):
            g: dict = {}
            for r in rows:
                k = fn(r)
                if k is None:
                    continue
                x = g.setdefault(k, [0, 0, 0])
                x[0] += 1
                x[1] += 1 if r["label"] in UP else 0
                x[2] += 1 if r["label"] == "despencou" else 0
            keys = order or sorted(g)
            return {"nome": name, "linhas": [{"faixa": k, "n": g[k][0], "up_pct": round(g[k][1] / g[k][0] * 100, 1),
                                               "rug_pct": round(g[k][2] / g[k][0] * 100, 1)} for k in keys if k in g]}
        GO = ["caiu", "0 a 30%", "30 a 100%", "mais de 100%"]
        tabs = [table("Ganho na foto de 1 min", lambda r: bucket_gain(gain(r, "1")), GO),
                table("Ganho na foto de 5 min", lambda r: bucket_gain(gain(r, "5")), GO),
                table("Compra do dev na criação", dev, ["nada", "até 1 SOL", "1 a 3 SOL", "mais de 3 SOL"]),
                table("Histórico do criador", creator, ["criador novo", "já fez token que subiu", "tokens parados antes", "só despencou antes"]),
                table("Boost pago na DexScreener", lambda r: "boost ON" if r.get("boost") else "boost OFF", ["boost ON", "boost OFF"]),
                table("Hora de criação (UTC)", hour)]
        best = []
        for tb in tabs[:5]:
            for ln in tb["linhas"]:
                if ln["n"] >= 30 and base_up is not None and ln["up_pct"] >= base_up * 2:
                    best.append({"sinal": tb["nome"] + ": " + ln["faixa"], **ln})
        out = {"tokens": len(rows), "base_up_pct": round(base_up, 1) if base_up is not None else None,
               "tables": tabs, "best": sorted(best, key=lambda x: -x["up_pct"])[:8], "min_n": 30}
        self._lessons = (t, out)
        return out

    def creator_info(self, cr: str | None) -> dict | None:
        c = self.creators.get(cr) if cr else None
        return dict(c) if c else None

    # ------------------------------------------------------------------ banco
    def load(self, hours: list[dict], creators: list[dict]) -> None:
        for r in hours or []:
            self.hours[str(r.get("hora"))] = dict(r.get("data") or {})
        for r in creators or []:
            if r.get("creator"):
                self.creators[r["creator"]] = {"tokens": int(r.get("tokens") or 0), "x2": int(r.get("x2") or 0),
                                               "rugs": int(r.get("rugs") or 0)}

    def dump_live(self) -> dict:
        """Tokens ainda em observação, para gravar no banco: antes sumiam a cada versão publicada (o servidor reinicia;
        o dono perdeu de vista 3 tokens que tinha comprado em 2026-10-26)."""
        return {"live": list(self.live.values()), "dropped": self.dropped, "since": self.since}

    def restore(self, state: dict | None, recent: list[dict] | None, now: float | None = None) -> None:
        now = now or time.time()
        for r in (state or {}).get("live") or []:
            if isinstance(r, dict) and r.get("mint") and now - float(r.get("t0") or 0) < (SNAPS[-1] + 5) * 60:
                self.live.setdefault(r["mint"], {**r, "snaps": dict(r.get("snaps") or {})})
        self.since = (state or {}).get("since") or self.since
        seen = {r["mint"] for r in self.done}
        for row in sorted(recent or [], key=lambda x: str((x.get("data") or {}).get("created_at") or "")):
            d = dict(row.get("data") or {})
            try:
                ok = True if datetime.fromisoformat(str(d.get("created_at"))).timestamp() >= now - KEEP_DAYS * 86400 else None
            except ValueError:
                ok = None
            if ok is not None and row.get("mint") not in seen:
                lab = row.get("label")
                if lab in ("graduou", "nasceu graduado"):       # rótulos gravados antes da 0.23.0 são refeitos
                    lab = label(d.get("mcap0"), d.get("snaps") or {}, True)
                self.done.append({**d, "mint": row["mint"], "creator": row.get("creator"), "label": lab})

    def take_dirty(self) -> tuple[list[dict], list[dict], list[dict]]:
        rows, self.new_rows = self.new_rows, []
        hrs = [{"hora": k, "data": self.hours[k]} for k in self.dirty_hours if k in self.hours]
        crs = [{"creator": k, **self.creators[k]} for k in self.dirty_creators if k in self.creators]
        self.dirty_hours, self.dirty_creators = set(), set()
        tl = [{"mint": r["mint"], "creator": r["creator"], "label": r["label"],
               "data": {k: v for k, v in r.items() if k not in ("mint", "creator", "label")}} for r in rows]
        return tl, hrs, crs

    # ------------------------------------------------------------------ tela
    def snapshot(self, t: float | None = None) -> dict:
        t = t or time.time()
        keys = sorted(self.hours)[-24:]
        hours = []
        for k in keys:
            h = self.hours[k]
            L = h.get("labels") or {}
            fin = sum(L.values())
            up = sum(L.get(x, 0) for x in ("graduou", "5x", "2x"))
            hours.append({"hora": k, "created": h.get("created", 0), "tracked": h.get("tracked", 0), "finished": fin,
                          "up_pct": round(up / fin * 100, 1) if fin else None,
                          "grad": L.get("graduou", 0), "x5": L.get("5x", 0), "x2": L.get("2x", 0),
                          "rug_pct": round(L.get("despencou", 0) / fin * 100, 1) if fin else None,
                          "dead_pct": round(L.get("morreu", 0) / fin * 100, 1) if fin else None})
        day = [r for r in self.done if (datetime.fromisoformat(r["created_at"]).timestamp() >= t - 86400)]
        ups = [r for r in day if r["label"] in ("graduou", "5x", "2x")]

        def words(rows):
            c: dict[str, int] = {}
            for r in rows:
                for w in set(re.findall(r"[a-z]{3,}", (r["symbol"] + " " + r["name"]).lower())) - STOP:
                    c[w] = c.get(w, 0) + 1
            return c
        wa, wu = words(day), words(ups)
        hot = sorted(((w, n, wa.get(w, n)) for w, n in wu.items() if n >= 2), key=lambda x: (-x[1], x[2]))[:15]
        crs = sorted(((k, v) for k, v in self.creators.items() if v["tokens"] >= 2), key=lambda kv: (-kv[1]["rugs"], -kv[1]["tokens"]))
        good = sorted(((k, v) for k, v in self.creators.items() if v["x2"] >= 1), key=lambda kv: (-kv[1]["x2"], kv[1]["rugs"]))
        return {"since": self.since, "live": len(self.live), "dropped": self.dropped, "max_per_min": MAX_PER_MIN,
                "day": {"finished": len(day), "up": len(ups),
                        "labels": {lb: sum(1 for r in day if r["label"] == lb) for lb in
                                   ("graduou", "5x", "2x", "subiu pouco", "morreu", "despencou", "nasceu graduado",
                                    "sem dado")}},
                "rising": self.rising(t),
                "hours": hours,
                "words": [{"word": w, "up": n, "all": a} for w, n, a in hot],
                "bad_creators": [{"creator": k, **v} for k, v in crs[:20]],
                "good_creators": [{"creator": k, **v} for k, v in good[:20]],
                "recent_up": [{**r, "boost": self.boost(r["mint"])} for r in list(reversed(ups))[:30]],
                "lessons": self.lessons(t), "kept": len(self.done), "keep_days": KEEP_DAYS}
