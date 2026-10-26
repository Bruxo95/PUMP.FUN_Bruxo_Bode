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
STOP = {"the", "of", "and", "a", "to", "in", "on", "coin", "token", "pump", "fun", "sol", "solana", "inu", "ai"}


def _hour(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:00:00+00:00")


def label(mcap0: float | None, snaps: dict, graduated: bool) -> str:
    vals = [v for v in snaps.values() if v]
    if graduated:
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
        self.done: deque = deque(maxlen=6000)          # resumos recentes (memória) para a tela
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
               "dev_buy": r["dev_buy"]}
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
        if lab in INTERESTING:
            self.new_rows.append(out)
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
                                   ("graduou", "5x", "2x", "subiu pouco", "morreu", "despencou", "sem dado")}},
                "hours": hours,
                "words": [{"word": w, "up": n, "all": a} for w, n, a in hot],
                "bad_creators": [{"creator": k, **v} for k, v in crs[:20]],
                "good_creators": [{"creator": k, **v} for k, v in good[:20]],
                "recent_up": list(reversed(ups))[:30]}
