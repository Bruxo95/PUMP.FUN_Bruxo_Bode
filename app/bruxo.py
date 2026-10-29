"""Aba do Bruxo (0.32.41, pedido do Bruxo em áudios de 29/10 + prompt dele; "não muda nada no Explorar" — dono).

Estratégia: entrar JUNTO com os top traders em moedas NOVAS (o Explorar espera a moeda chegar perto de graduar, e o
Bruxo viu que "pump.fun dura uns 25 minutos": quando chega lá, despeja). Cada compra de um top trader num token com
poucos minutos de vida vira um SINAL; o sinal é acompanhado por 30 min, entrando ou não, para o robô aprender quanto
tempo a moeda dura, qual o pico e se o stop teria saído cedo demais.

Regras do prompt do Bruxo (com o que o Claude acrescentou, marcado com +):
1. top trader comprou; token com menos de 5 min de criação; ritmo de compra acima da média inicial dos tokens novos;
2. concentração dos 10 maiores detentores, liquidez mínima (market cap da curva) e criador sem fatia grande;
   + compra mínima do trader (tira robô de centavos), + lista negra / criador com rugs, + não graduado;
3. vende 50% em +100%; 4. stop móvel no resto; + stop de perda, + tempo máximo, + sai quando o trader vende.
Sempre só na carteira FICTÍCIA, a não ser que a pessoa ligue "Também na REAL" (começa desligado).
"""
from __future__ import annotations

import statistics
from datetime import datetime, timezone

MARKS = (1, 2, 5, 10, 15, 25, 30)       # minutos depois do sinal
WATCH_S = 30 * 60
CURVE_START_SOL = 28.0                   # market cap de um token recém-criado na curva (30 SOL virtuais)


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds")


def age_bucket(age: float | None) -> str:
    if age is None:
        return "sem idade"
    return "até 1 min" if age < 1 else "1–2 min" if age < 2 else "2–5 min" if age < 5 else "5–10 min" if age < 10 else "10+ min"


class Bruxo:
    def __init__(self) -> None:
        self.signals: dict[str, dict] = {}       # id -> sinal (um por token a cada 30 min)
        self.by_mint: dict[str, str] = {}
        self.dirty: set[str] = set()

    # ------------------------------------------------------------------ sinais
    def on_buy(self, w: str, label: str, mint: str, sym: str | None, sol: float, px: float | None, tk: dict,
               age_min: float | None, flow: dict, t: float, kind: str = "trader") -> tuple[dict, bool]:
        """Compra de um top trader. Devolve (sinal, novo?). Outro top trader no mesmo token em 30 min entra no mesmo sinal.
        0.32.59: kind="lancamento" = token no 1º minuto SEM trader (só estudo; nunca compra)."""
        key = mint if kind == "trader" else f"{kind}:{mint}"
        sid = self.by_mint.get(key)
        s = self.signals.get(sid) if sid else None
        if s and t - s["t"] < WATCH_S:
            if w not in s["wallets"]:
                s["wallets"].append(w)
                s["names"].append(label)
                s["sol_traders"] = round(s["sol_traders"] + sol, 4)
                self.dirty.add(s["id"])
            return s, False
        sid = f"{mint}:{int(t)}" + ("" if kind == "trader" else ":" + kind)
        s = {"id": sid, "t": t, "em": _iso(t), "mint": mint, "symbol": sym, "wallets": [w], "names": [label], "kind": kind,
             "sol_traders": round(sol, 4), "px0": px, "mcap0": tk.get("mcap_sol"), "age_min": age_min,
             "flow": flow, "marks": {}, "peak_pct": None, "peak_s": None, "low_pct": None, "hit100_s": None,
             "stop30_s": None, "decisoes": {}, "done": False,
             # 0.32.82: hora em que o token nasceu (a idade da tela era a da compra; a pump.fun mostra a idade de agora)
             "created_t": round(t - age_min * 60, 1) if age_min is not None else None, "holders": {}}
        self.signals[sid] = s
        self.by_mint[key] = sid
        self.dirty.add(sid)
        return s, True

    def decide(self, s: dict, user: str, why: str | None, filtros: dict | None = None) -> None:
        """Decisão de cada conta no sinal: None = entrou; texto = por que não entrou."""
        s["decisoes"][user] = {"entrou": why is None, "motivo": why}
        if filtros:
            s["filtros"] = filtros
        self.dirty.add(s["id"])

    def open_mints(self, now: float) -> list[str]:
        return sorted({s["mint"] for s in self.signals.values() if not s["done"] and now - s["t"] <= WATCH_S + 120})

    HOLD_MARKS = (0, 1, 5, 10, 25)          # 0.32.82: detentores no sinal e 1/5/10/25 min depois

    def holders_due(self, now: float, limit: int = 8) -> list[tuple[dict, str]]:
        """(sinal, marca) cujos detentores ainda não foram lidos. Marca perdida (passou 3 min) fica sem dado."""
        out = []
        for s in self.signals.values():
            if s.get("done"):
                continue
            el = now - s["t"]
            H = s.setdefault("holders", {})
            for m in self.HOLD_MARKS:
                k = str(m)
                if k in H or el < m * 60:
                    continue
                if el > m * 60 + 180:
                    H[k] = None
                    self.dirty.add(s["id"])
                    continue
                out.append((s, k))
                break
        out.sort(key=lambda x: x[0]["t"])
        return out[:limit]

    def tick(self, price_of, now: float) -> int:
        """Acompanha cada sinal por 30 min: preço nas marcas, pico, tempo até o pico e se teria batido +100% / −30%."""
        n = 0
        for s in self.signals.values():
            if s["done"]:
                continue
            px = price_of(s["mint"])
            el = now - s["t"]
            if s.get("px0") is None and px:
                s["px0"] = px
            if px and s.get("px0"):
                pct = (px / s["px0"] - 1) * 100
                if s["peak_pct"] is None or pct > s["peak_pct"]:
                    s["peak_pct"], s["peak_s"] = round(pct, 1), int(el)
                if s["low_pct"] is None or pct < s["low_pct"]:
                    s["low_pct"] = round(pct, 1)
                if pct >= 100 and s["hit100_s"] is None:
                    s["hit100_s"] = int(el)
                if pct <= -30 and s["stop30_s"] is None:
                    s["stop30_s"] = int(el)
                for m in MARKS:
                    if str(m) not in s["marks"] and el >= m * 60:
                        s["marks"][str(m)] = round(pct, 1) if el <= m * 60 + 180 else None   # foto atrasada = sem dado
                n += 1
                self.dirty.add(s["id"])
            if el > WATCH_S + 120:
                s["done"] = True
                for m in MARKS:
                    s["marks"].setdefault(str(m), None)
                self.dirty.add(s["id"])
        return n

    def trim(self, now: float, keep_s: float = 7 * 86400) -> None:
        for sid in [k for k, s in self.signals.items() if now - s["t"] > keep_s]:
            s = self.signals.pop(sid)
            key = s["mint"] if s.get("kind", "trader") == "trader" else f"{s['kind']}:{s['mint']}"
            if self.by_mint.get(key) == sid:
                self.by_mint.pop(key, None)

    def load(self, rows: list[dict]) -> None:
        for r in rows:
            d = r.get("data") if isinstance(r, dict) else None
            if isinstance(d, dict) and d.get("id") and d.get("mint"):
                self.signals.setdefault(d["id"], d)
                key = d["mint"] if d.get("kind", "trader") == "trader" else f"{d['kind']}:{d['mint']}"
                cur = self.by_mint.get(key)
                if cur is None or self.signals[cur]["t"] < d["t"]:
                    self.by_mint[key] = d["id"]

    def recent(self, hours: float, now: float) -> list[dict]:
        return sorted((s for s in self.signals.values() if now - s["t"] <= hours * 3600), key=lambda s: -s["t"])

    # ------------------------------------------------------------------ estudo
    @staticmethod
    def study(signals: list[dict], stop_pct: float = 30, tp1_pct: float = 100) -> dict:
        """O que os sinais terminados ensinam: quanto tempo a moeda dura, pico típico, quantas dobram, quantas batem o stop
        ANTES de dobrar (o problema do "estopado no começo" que o Bruxo falou) e o melhor minuto para estar fora."""
        done = [s for s in signals if s.get("done") and s.get("peak_pct") is not None]
        out = {"n": len(done), "n_total": len(signals)}
        if not done:
            return out
        peaks = [s["peak_pct"] for s in done]
        peak_s = [s["peak_s"] for s in done if s.get("peak_s") is not None]
        dob = [s for s in done if s.get("hit100_s") is not None]
        stop_first = [s for s in done if s.get("stop30_s") is not None and (s.get("hit100_s") is None or s["stop30_s"] < s["hit100_s"])]
        stop_then_up = [s for s in stop_first if s.get("hit100_s") is not None]
        marks = {}
        for m in MARKS:
            vals = [s["marks"].get(str(m)) for s in done if s.get("marks", {}).get(str(m)) is not None]
            if vals:
                marks[str(m)] = {"n": len(vals), "mediana": round(statistics.median(vals), 1),
                                 "subindo": round(sum(1 for v in vals if v > 0) / len(vals) * 100)}
        best = max(marks.items(), key=lambda kv: kv[1]["mediana"])[0] if marks else None
        by_age: dict[str, dict] = {}
        for s in done:
            g = by_age.setdefault(age_bucket(s.get("age_min")), {"n": 0, "dobrou": 0, "stop_antes": 0, "pico": []})
            g["n"] += 1
            g["dobrou"] += s.get("hit100_s") is not None
            g["stop_antes"] += s in stop_first
            g["pico"].append(s["peak_pct"])
        for g in by_age.values():
            g["pico_mediano"] = round(statistics.median(g.pop("pico")), 1)
            g["dobrou_pct"] = round(g["dobrou"] / g["n"] * 100)
        by_tr: dict[int, dict] = {}
        for s in done:
            k = min(3, len(s.get("wallets") or [1]))
            g = by_tr.setdefault(k, {"n": 0, "dobrou": 0})
            g["n"] += 1
            g["dobrou"] += s.get("hit100_s") is not None
        out.update({
            "pico_mediano": round(statistics.median(peaks), 1),
            "tempo_ate_pico_mediano_s": int(statistics.median(peak_s)) if peak_s else None,
            "dobrou": len(dob), "dobrou_pct": round(len(dob) / len(done) * 100),
            "tempo_ate_dobrar_mediano_s": int(statistics.median([s["hit100_s"] for s in dob])) if dob else None,
            "stop_antes": len(stop_first), "stop_antes_pct": round(len(stop_first) / len(done) * 100),
            "stop_e_depois_dobrou": len(stop_then_up),
            "marcas": marks, "melhor_minuto": best, "por_idade": by_age,
            "por_traders": {("3+" if k == 3 else str(k)): dict(v, dobrou_pct=round(v["dobrou"] / v["n"] * 100)) for k, v in sorted(by_tr.items())},
        })
        tips = []
        if len(done) >= 15:
            if out["stop_antes_pct"] >= 40 and len(stop_then_up) >= 3:
                tips.append(f"{len(stop_then_up)} sinais bateram −30% e DEPOIS dobraram: o stop de perda está apertado para moeda nova")
            if peak_s and statistics.median(peak_s) < 10 * 60:
                tips.append(f"o pico costuma vir em {int(statistics.median(peak_s) / 60)} min: um tempo máximo perto disso evita devolver o ganho")
            if out["dobrou_pct"] < 15:
                tips.append(f"só {out['dobrou_pct']}% dobram: o alvo de +100% para vender metade raramente chega; um alvo menor pode render mais")
            good = [k for k, v in by_age.items() if v["n"] >= 5 and v["dobrou_pct"] >= out["dobrou_pct"] * 1.5]
            if good:
                tips.append("idade que mais dobra: " + ", ".join(good))
        out["dicas"] = tips
        return out
