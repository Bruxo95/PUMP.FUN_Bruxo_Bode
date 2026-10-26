"""Maiores traders (0.31.2, pedido do dono em 2026-10-26: "seguir só os maiores traders, entender o que fazem minuto a
minuto, estudar, indicar o que comprar, comprar sozinho, mostrar ganhos com gráficos e sugerir melhorias").

- Quem: os N maiores por lucro realizado no ranking da Solana Tracker (o mesmo do menu Top traders; o ranking do
  próprio site da pump.fun fica atrás da proteção anti-robô e não pode ser lido). O monitor já assina essas carteiras
  pelo WebSocket da Solana (top 60 de cada ranking), então cada compra/venda delas chega aqui em segundos.
- Sinal: um token em que K ou mais desses traders compraram dentro de X minutos (padrão 2 em 10 min), ou uma compra
  grande de um só (padrão 5 SOL), sem venda deles no meio. Cada sinal guarda o preço do momento e é acompanhado por
  60 min (ganho aos 5, 15 e 60 min e o pico) — é isso que vira estudo, ranking de quem dá sinal bom e sugestões.
- Nada aqui compra: quem compra é o motor do usuário (`PumpFun.elite_auto`), só no simulado por padrão.
"""
from __future__ import annotations

import time
from collections import deque
from datetime import datetime, timezone

TRACK_S = 3600                         # acompanha cada sinal por 60 min
MARKS = (5, 15, 60)


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds")


def ts(x) -> float | None:
    try:
        d = datetime.fromisoformat(str(x).replace("Z", "+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()
    except (TypeError, ValueError):
        return None


class Elite:
    def __init__(self, market):
        self.market = market
        self.trades: deque = deque(maxlen=3000)          # atividade minuto a minuto (memória)
        self.tokens: dict[str, dict] = {}                # mint -> compras/vendas recentes dos maiores traders
        self.signals: dict[str, dict] = {}               # id -> sinal (abertos e fechados recentes)
        self.dirty: set[str] = set()
        self.names: dict[str, dict] = {}                 # carteira -> nome, twitter, avatar, lucro (do ranking)
        self.ages: dict[str, dict] = {}                  # carteira -> idade (0.31.3; RPC, renovada a cada 12 h)

    # ------------------------------------------------------------------ quem são
    def refresh_names(self, leaderboards: list[list[dict]], top: int) -> list[str]:
        best: dict[str, dict] = {}
        for lb in leaderboards:
            for r in lb or []:
                w = r.get("wallet")
                if not w or r.get("base_flags"):
                    continue                              # robô, dev, corretora, suspeita: fora da elite
                if w not in best or (r.get("realized_usd") or 0) > (best[w].get("realized_usd") or 0):
                    best[w] = r
        rows = sorted(best.values(), key=lambda r: -(r.get("realized_usd") or 0))[:top]
        self.names = {r["wallet"]: {k: r.get(k) for k in ("name", "twitter", "avatar", "realized_usd", "winrate",
                                                          "trades", "roi", "days_active")} for r in rows}
        return [r["wallet"] for r in rows]

    def wallets(self) -> set:
        return set(self.names)

    # ------------------------------------------------------------------ entrada
    def on_trade(self, w: str, ev: dict, t: float, cfg: dict) -> dict | None:
        """Uma compra/venda de um dos maiores traders. Devolve o sinal novo, se nasceu um."""
        if w not in self.names:
            return None
        mint, kind = ev.get("mint"), ev.get("txType")
        sol, tok = float(ev.get("solAmount") or 0), float(ev.get("tokenAmount") or 0)
        if not mint or kind not in ("buy", "sell"):
            return None
        tk = self.market.tokens.setdefault(mint, {"created_t": t})
        if sol and tok:
            tk["price"], tk["last_t"] = sol / tok, t      # preço da própria negociação (vale para o sinal)
            tk["mcap_sol"] = sol / tok * 1e9
        self.trades.append({"t": t, "wallet": w, "mint": mint, "kind": kind, "sol": round(sol, 4),
                            "symbol": tk.get("symbol"), "mcap_sol": tk.get("mcap_sol")})
        x = self.tokens.setdefault(mint, {"buys": {}, "sells": {}, "first_t": t})
        win = float(cfg.get("window_min", 10)) * 60
        x["buys"] = {k: v for k, v in x["buys"].items() if t - v["t"] <= win}
        if kind == "sell":
            x["sells"][w] = t
            for s in self.signals.values():               # o sinal registra quem saiu (estudo de "vende rápido")
                if s["mint"] == mint and not s.get("closed") and w in s["wallets"] and w not in s.setdefault("sold_by", {}):
                    s["sold_by"][w] = round(t - s["t"])
                    self.dirty.add(s["id"])
            return None
        b = x["buys"].setdefault(w, {"t": t, "sol": 0.0})
        b["sol"] += sol
        if any(s["mint"] == mint and not s.get("closed") for s in self.signals.values()):
            return None                                   # já existe sinal aberto para este token
        buyers = {k: v for k, v in x["buys"].items() if k not in x["sells"] or x["sells"][k] < v["t"]}
        total = sum(v["sol"] for v in buyers.values())
        big = float(cfg.get("big_sol", 5))
        if len(buyers) >= int(cfg.get("min_wallets", 2)):
            reason = f"{len(buyers)} maiores traders compraram em {cfg.get('window_min', 10):g} min"
        elif big and buyers.get(w, {}).get("sol", 0) >= big:
            reason = f"compra grande de {buyers[w]['sol']:.1f} SOL de um dos maiores traders"
        else:
            return None
        sid = f"{mint[:10]}-{int(t)}"
        s = {"id": sid, "mint": mint, "symbol": tk.get("symbol"), "t": t, "created_at": iso(t), "reason": reason,
             "wallets": sorted(buyers), "names": [self.label(k) for k in sorted(buyers)], "sol": round(total, 3),
             "px0": tk.get("price"), "mcap0": tk.get("mcap_sol"), "marks": {}, "peak_pct": 0.0, "low_pct": 0.0,
             "closed": False}
        self.signals[sid] = s
        self.dirty.add(sid)
        return s

    def label(self, w: str) -> str:
        n = self.names.get(w) or {}
        return n.get("name") or (w[:4] + "…" + w[-4:])

    # ------------------------------------------------------------------ acompanhar o que aconteceu depois
    def open_mints(self, t: float | None = None) -> set:
        t = t or time.time()
        return {s["mint"] for s in self.signals.values() if not s.get("closed") and t - s["t"] <= TRACK_S + 120}

    def tick(self, t: float | None = None) -> int:
        t = t or time.time()
        n = 0
        for s in list(self.signals.values()):
            if s.get("closed"):
                if t - s["t"] > 7 * 86400:
                    del self.signals[s["id"]]
                continue
            px = (self.market.tokens.get(s["mint"]) or {}).get("price")
            if px and s.get("px0"):
                g = (px / s["px0"] - 1) * 100
                s["peak_pct"], s["low_pct"] = round(max(s["peak_pct"], g), 1), round(min(s["low_pct"], g), 1)
                for m in MARKS:
                    if str(m) not in s["marks"] and t - s["t"] >= m * 60:
                        s["marks"][str(m)] = round(g, 1)
                s["now_pct"] = round(g, 1)
                n += 1
            if t - s["t"] >= TRACK_S:
                s["closed"] = True
            self.dirty.add(s["id"])
        return n

    # ------------------------------------------------------------------ banco
    def take_dirty(self) -> list[dict]:
        ids, self.dirty = self.dirty, set()
        return [{"id": s["id"], "mint": s["mint"], "symbol": s.get("symbol"), "criado_em": s["created_at"],
                 "data": {k: v for k, v in s.items() if k not in ("id", "mint", "symbol")}}
                for i in ids if (s := self.signals.get(i))]

    def load(self, rows: list[dict]) -> None:
        for r in rows or []:
            d = dict(r.get("data") or {})
            if r.get("id") and d.get("t"):
                self.signals[r["id"]] = {**d, "id": r["id"], "mint": r.get("mint"), "symbol": r.get("symbol")}

    # ------------------------------------------------------------------ estudo e sugestões
    def study(self) -> dict:
        done = [s for s in self.signals.values() if s.get("closed") and s.get("px0")]

        def agg(rows):
            n = len(rows)
            if not n:
                return {"n": 0}
            return {"n": n, "avg_peak": round(sum(s["peak_pct"] for s in rows) / n, 1),
                    "avg_60": round(sum(s["marks"].get("60", s.get("now_pct", 0)) for s in rows) / n, 1),
                    "hit30_pct": round(sum(1 for s in rows if s["peak_pct"] >= 30) / n * 100, 1),
                    "dump30_pct": round(sum(1 for s in rows if s["low_pct"] <= -30) / n * 100, 1)}
        by_n = {k: agg([s for s in done if (len(s["wallets"]) >= 3 if k == "3+" else len(s["wallets"]) == int(k))])
                for k in ("1", "2", "3+")}
        per: dict[str, list] = {}
        for s in done:
            for w in s["wallets"]:
                per.setdefault(w, []).append(s)
        traders = sorted(({"wallet": w, "name": self.label(w), **agg(rows),
                           "sells_fast_pct": round(sum(1 for s in rows if (s.get("sold_by") or {}).get(w, 1e9) <= 300) / len(rows) * 100, 1)}
                          for w, rows in per.items()), key=lambda x: -x.get("avg_peak", 0))
        return {"signals": len(done), "all": agg(done), "by_n": by_n, "traders": traders}

    def recommended(self, min_wr: float = 80.0, min_trades: int = 100) -> list[dict]:
        """Sugeridos (0.31.3, pedido do dono): acerto de 80%+ no ranking com base mínima de trades, os mais lucrativos
        primeiro. Acerto alto com poucos trades não entra (sorte)."""
        out = [{"wallet": w, **n} for w, n in self.names.items()
               if (n.get("winrate") or 0) >= min_wr and (n.get("trades") or 0) >= min_trades]
        return sorted(out, key=lambda x: -(x.get("realized_usd") or 0))

    def suggestions(self, st: dict, auto: dict | None = None) -> list[dict]:
        """Sugestões de melhoria tiradas do que aconteceu (só com base mínima; nada é aplicado sozinho)."""
        out = []
        one, two = st["by_n"].get("1") or {}, st["by_n"].get("2") or {}
        three = st["by_n"].get("3+") or {}
        if one.get("n", 0) >= 10 and two.get("n", 0) >= 10 and two["avg_60"] - one["avg_60"] >= 10:
            out.append({"tipo": "regra", "texto": f"Sinais com 2+ traders terminaram em média {two['avg_60']:+.0f}% em 60 min contra "
                        f"{one['avg_60']:+.0f}% com 1 só: exija 2 ou mais traders (desligue a compra grande de 1).",
                        "base": one["n"] + two["n"]})
        if three.get("n", 0) >= 10 and two.get("n", 0) >= 10 and three["avg_60"] - two["avg_60"] >= 10:
            out.append({"tipo": "regra", "texto": f"Com 3+ traders o resultado é melhor ({three['avg_60']:+.0f}% × {two['avg_60']:+.0f}%): "
                        "aumente o mínimo para 3.", "base": three["n"] + two["n"]})
        for tr in st["traders"]:
            if tr.get("n", 0) >= 8 and tr["avg_60"] <= -15:
                out.append({"tipo": "trader", "texto": f"Os sinais de {tr['name']} terminaram em média {tr['avg_60']:+.0f}% em 60 min "
                            f"({tr['n']} sinais): tire da lista ou não use os sinais só dele.", "base": tr["n"]})
            if tr.get("n", 0) >= 8 and tr["sells_fast_pct"] >= 60:
                out.append({"tipo": "saída", "texto": f"{tr['name']} vende em menos de 5 min em {tr['sells_fast_pct']:.0f}% dos sinais: "
                            "copie esse trader só com \"sair quando ele vender\" ligado.", "base": tr["n"]})
        a = st["all"]
        if a.get("n", 0) >= 15 and a["dump30_pct"] >= 50:
            out.append({"tipo": "risco", "texto": f"{a['dump30_pct']:.0f}% dos sinais caíram 30% ou mais em até 60 min: o stop de "
                        "perda é essencial e entrar depois do sinal é arriscado.", "base": a["n"]})
        if a.get("n", 0) >= 15 and a["avg_peak"] >= 40 and a["avg_60"] <= 0:
            out.append({"tipo": "saída", "texto": f"Em média os sinais chegam a {a['avg_peak']:+.0f}% mas terminam em {a['avg_60']:+.0f}%: "
                        "use venda em partes cedo e stop móvel justo.", "base": a["n"]})
        ar = ((auto or {}).get("summary") or {}).get("period") or {}
        if (ar.get("closed") or 0) >= 15 and (ar.get("profit_factor") or 0) < 1:
            out.append({"tipo": "código", "texto": "As compras automáticas desta tela estão no prejuízo depois das taxas: "
                        "deixe só observando até o estudo mostrar uma regra que dá lucro.", "base": ar.get("closed")})
        for r in self.recommended()[:5]:
            out.append({"tipo": "trader", "texto": f"{r.get('name') or r['wallet'][:4] + '…' + r['wallet'][-4:]} tem "
                        f"{r['winrate']:.0f}% de acerto em {int(r.get('trades') or 0)} trades e lucro de "
                        f"${(r.get('realized_usd') or 0):,.0f} no ranking: coloque em Carteiras em estudo e veja no "
                        "ranking de copiabilidade se compensa copiar com o seu atraso.", "base": int(r.get("trades") or 0)})
        if not out:
            out.append({"tipo": "info", "texto": "Ainda sem base para sugerir mudanças: cada sinal é estudado por 60 min e as "
                        "sugestões aparecem com 10+ sinais por faixa.", "base": st["signals"]})
        return out

    def steps(self, feed: list[dict], positions: list[dict], trades: list[dict], only: set | None = None,
              limit: int = 100) -> list[dict]:
        """Steps (0.31.4): cada compra/venda dos maiores traders ao lado do que o robô do usuário fez com ela (do feed:
        copiou, vendeu, não copiou e por quê) e de como está a posição dele nesse token."""
        idx: dict[tuple, list] = {}
        for e in feed:
            k = (e.get("wallet"), e.get("mint"), e.get("kind"))
            if k[0] and k[1]:
                idx.setdefault(k, []).append((ts(e.get("at")) or 0, e))
        pos = {(p.get("wallet"), p.get("mint")): p for p in positions}
        closed = {}
        for t in trades[:3000]:
            closed.setdefault((t.get("wallet"), t.get("mint")), t)
        out = []
        for x in reversed(list(self.trades)):
            if only is not None and x["wallet"] not in only:
                continue
            near = [(abs(t0 - x["t"]), e) for t0, e in idx.get((x["wallet"], x["mint"], x["kind"]), []) if abs(t0 - x["t"]) <= 180]
            e = min(near, key=lambda z: z[0])[1] if near else None
            p, c = pos.get((x["wallet"], x["mint"])), closed.get((x["wallet"], x["mint"]))
            out.append({**x, "name": self.label(x["wallet"]), "bot_action": (e or {}).get("action"),
                        "bot_reason": (e or {}).get("reason"),
                        "position": {"open": True, "chg_pct": p.get("chg_pct"), "sol_in": p.get("sol_in"), "real": bool(p.get("real"))} if p else
                        ({"open": False, "pnl_sol": c.get("pnl_sol"), "pnl_pct": c.get("pnl_pct"), "reason": c.get("reason")} if c else None)})
            if len(out) >= limit:
                break
        return out

    def snapshot(self, t: float | None = None) -> dict:
        t = t or time.time()
        recent = list(self.trades)[-80:][::-1]
        last = {}
        for x in self.trades:
            last[x["wallet"]] = x
        usd = getattr(self.market, "wallet_usd", {}) or {}
        traders = [{"wallet": w, **n, "last": last.get(w), "balance": usd.get(w), "age": self.ages.get(w)}
                   for w, n in self.names.items()]
        sigs = sorted(self.signals.values(), key=lambda s: -s["t"])
        st = self.study()
        return {"traders": traders, "feed": [{**x, "name": self.label(x["wallet"])} for x in recent],
                "open": [s for s in sigs if not s.get("closed")][:30],
                "closed": [s for s in sigs if s.get("closed")][:40], "study": st}
