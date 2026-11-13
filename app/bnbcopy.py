"""BNB · Four.Meme, etapa 2 (0.32.170): cópia FICTÍCIA dos traders do ranking, por conta de admin. Nunca envia ordem.

Pedido do dono em 03/11/2026: o painel da BNB com Visão geral, Top traders, Posições, Histórico, Semana × fim de semana,
Abas de trades (uma só), Configurações, Administração e Changelog, seguindo o padrão do painel da pump.fun.

Regra de cópia, igual ao Copiar igual da Solana: quando um trader que o ranking copiaria compra, a fictícia compra o valor
fixo; quando ele vende, vende a mesma parte. Sai também pelo tempo máximo e pelo stop opcional. Taxa da Four.Meme de 1% em
cada lado (lida nos eventos), gás e slippage configuráveis. Isolado do motor da Solana: memória e tabelas bnb_* próprias.
"""
from __future__ import annotations

import time
import uuid

from . import stopganho

FEE = 0.01                       # taxa da Four.Meme em cada lado (conferida nos eventos em 02/11/2026)
# 0.32.332 (pedido do dono, 13/11/2026): stop de ganho autônomo (app/stopganho.py). A BNB não tinha alvo nem stop móvel: a cópia
# só saía quando o trader vendia ou pelo tempo máximo. sg_fixo_pct 0 = o robô escolhe o nível pelo histórico.
CFG_DEFAULT = {"on": True, "bnb_por_compra": 0.05, "max_abertas": 10, "max_hold_h": 6.0, "stop_pct": 0.0,
               "slip_pct": 2.0, "gas_bnb": 0.0001, "saldo_inicial": 1.0, "sg_on": True, "sg_fixo_pct": 0.0}
CFG_LIMITS = {"bnb_por_compra": (0.001, 10), "max_abertas": (1, 100), "max_hold_h": (0.1, 168), "stop_pct": (0, 100),
              "slip_pct": (0, 50), "gas_bnb": (0, 0.01), "saldo_inicial": (0.01, 1000), "sg_fixo_pct": (0, 500)}
KEEP_TRADES = 3000


def clean_cfg(raw: dict | None, base: dict | None = None) -> dict:
    out = dict(base or CFG_DEFAULT)
    for k, v in (raw or {}).items():
        if k in ("on", "sg_on"):
            out[k] = bool(v)
        elif k in CFG_LIMITS:
            try:
                val = float(v)
            except (TypeError, ValueError):
                continue
            if val != val:
                continue
            lo, hi = CFG_LIMITS[k]
            val = min(hi, max(lo, val))
            out[k] = int(val) if isinstance(CFG_DEFAULT[k], int) else round(val, 6)
    return out


class Book:
    """Carteira fictícia em BNB de uma conta."""

    def __init__(self, user_id: str, cfg: dict | None = None, cash: float | None = None):
        self.user_id = user_id
        self.cfg = clean_cfg(cfg)
        self.cash = self.cfg["saldo_inicial"] if cash is None else float(cash)
        self.pos: dict[str, dict] = {}
        self.trades: list[dict] = []             # fechados, mais novo primeiro
        self.events: list[dict] = []             # o que a cópia fez ou deixou de fazer (memória, 200)
        self.dirty_pos: set = set()
        self.closed_pos: set = set()
        self.new_trades: list[dict] = []
        self.dirty_book = False
        self.sg_dec = None                       # 0.32.332: decisão do stop de ganho (cérebro com todas as contas)
        self.sombra_hook = None                  # 0.32.332: abre a sombra quando o stop de ganho vende

    # ------------------------------------------------------------------ util
    def _ev(self, t: float, wallet: str, token: str, acao: str, motivo: str = "") -> None:
        self.events.insert(0, {"t": t, "wallet": wallet, "token": token, "acao": acao, "motivo": motivo})
        del self.events[200:]

    def value_now(self, p: dict) -> float:
        px = p.get("px_now") or p["px_in"]
        return p["tokens_left"] * px * (1 - FEE - self.cfg["slip_pct"] / 100) - self.cfg["gas_bnb"]

    def pnl_now(self, p: dict) -> tuple[float, float]:
        sol = p["proceeds"] + max(0.0, self.value_now(p)) - p["bnb_in"]
        return sol, (100 * sol / p["bnb_in"] if p["bnb_in"] else 0.0)

    def sg_nivel(self, p: dict) -> float | None:
        """0.32.332: nível do stop de ganho desta posição (None = desligado)."""
        if not self.cfg.get("sg_on"):
            nv, fonte = None, "desligado"
        else:
            nv, fonte = stopganho.nivel_de(self.sg_dec() if self.sg_dec else None, self.cfg.get("sg_fixo_pct") or 0)
        if p.get("sg_nivel") != nv or p.get("sg_fonte") != fonte:
            p["sg_nivel"], p["sg_fonte"] = nv, fonte
        return nv

    # ------------------------------------------------------------------ cópia
    def buy(self, tr: dict, px: float, t: float) -> dict | None:
        c = self.cfg
        why = None
        amt = c["bnb_por_compra"]
        if not c["on"]:
            why = "cópia desligada nesta conta"
        elif not px or px <= 0:
            why = "sem preço do token"
        elif any(p["wallet"] == tr["wallet"] and p["token"] == tr["token"] for p in self.pos.values()):
            why = "já tem a posição deste trader neste token"
        elif len(self.pos) >= c["max_abertas"]:
            why = f"limite de {c['max_abertas']} posições abertas"
        elif self.cash < amt + c["gas_bnb"]:
            why = "saldo fictício insuficiente"
        if why:
            self._ev(t, tr["wallet"], tr["token"], "não copiou", why)
            return None
        px_in = px * (1 + c["slip_pct"] / 100)
        fee = amt * FEE
        tokens = (amt - fee) / px_in
        p = {"id": uuid.uuid4().hex[:16], "wallet": tr["wallet"], "token": tr["token"], "open_t": t, "px_in": px_in,
             "trader_px": px, "trader_bnb": tr.get("bnb"), "tokens": tokens, "tokens_left": tokens,
             "bnb_in": round(amt + c["gas_bnb"], 9), "proceeds": 0.0, "fees": fee + c["gas_bnb"], "px_now": px, "px_t": t,
             "best_pct": 0.0, "worst_pct": 0.0, "lag_s": round(max(0.0, t - tr["t"]), 1), "tx_in": tr.get("tx"),
             "aba": "top"}
        self.cash -= amt + c["gas_bnb"]
        self.pos[p["id"]] = p
        self.dirty_pos.add(p["id"])
        self.dirty_book = True
        self._ev(t, tr["wallet"], tr["token"], "copiou compra", f"{amt:.3f} BNB")
        return p

    def sell(self, p: dict, frac: float, px: float | None, t: float, motivo: str) -> dict | None:
        """Vende a parte frac (0–1) da posição; 0,95 ou mais vende tudo. Devolve o trade quando fecha."""
        c = self.cfg
        px = px or p.get("px_now") or p["px_in"]
        frac = 1.0 if frac >= 0.95 else max(0.0, frac)
        q = p["tokens_left"] * frac
        if q <= 0:
            return None
        pre = {"tokens": p["tokens_left"], "proceeds": p["proceeds"]}      # 0.32.332: a sombra parte daqui
        gross = q * px * (1 - c["slip_pct"] / 100)
        fee = gross * FEE
        got = gross - fee - c["gas_bnb"]
        p["tokens_left"] -= q
        p["proceeds"] += got
        p["fees"] += fee + c["gas_bnb"]
        p["px_now"], p["px_t"] = px, t
        self.cash += got
        self.dirty_book = True
        if frac < 1.0:
            p.setdefault("vendas", []).append({"t": t, "frac": round(frac, 4), "bnb": round(got, 6), "motivo": motivo})
            self.dirty_pos.add(p["id"])
            self._ev(t, p["wallet"], p["token"], "vendeu parte", f"{frac * 100:.0f}% · {motivo}")
            return None
        pnl = p["proceeds"] - p["bnb_in"]
        tr = {**{k: p.get(k) for k in ("id", "wallet", "token", "open_t", "px_in", "trader_px", "bnb_in", "fees",
                                        "best_pct", "worst_pct", "lag_s", "tx_in", "aba", "vendas")},
              "close_t": t, "px_out": px, "bnb_out": round(p["proceeds"], 9), "pnl_bnb": round(pnl, 9),
              "pnl_pct": round(100 * pnl / p["bnb_in"], 2) if p["bnb_in"] else 0.0, "motivo": motivo}
        if p.get("sg_hits"):
            tr["sg_hits"] = p["sg_hits"]
        if str(motivo).startswith(stopganho.MOTIVO):
            tr["sg"] = {"nivel": p.get("sg_nivel"), "fonte": p.get("sg_fonte"), "saiu": True}
            if self.sombra_hook:
                try:
                    self.sombra_hook(self.user_id, p, tr, pre, px, t)
                except Exception:
                    pass
        elif p.get("sg_nivel") is not None:
            tr["sg"] = {"nivel": p.get("sg_nivel"), "fonte": p.get("sg_fonte"), "saiu": False}
        self.pos.pop(p["id"], None)
        self.dirty_pos.discard(p["id"])
        self.closed_pos.add(p["id"])
        self.trades.insert(0, tr)
        del self.trades[KEEP_TRADES:]
        self.new_trades.append(tr)
        self._ev(t, p["wallet"], p["token"], "fechou", f"{motivo} · {pnl:+.4f} BNB")
        return tr

    def on_price(self, token: str, px: float, t: float) -> list[dict]:
        """Preço novo do token: atualiza as posições, aplica o stop opcional."""
        out = []
        for p in list(self.pos.values()):
            if p["token"] != token or px <= 0:
                continue
            p["px_now"], p["px_t"] = px, t
            _, pct = self.pnl_now(p)
            p["best_pct"], p["worst_pct"] = max(p["best_pct"], pct), min(p["worst_pct"], pct)
            stopganho.marcar(p, pct, t)
            self.dirty_pos.add(p["id"])
            why = f"stop de {self.cfg['stop_pct']:.0f}%" if self.cfg["stop_pct"] and pct <= -self.cfg["stop_pct"] else None
            if not why:                                 # 0.32.332 (pedido do dono): stop de ganho autônomo
                sgn = self.sg_nivel(p)
                if sgn is not None and pct >= sgn:
                    why = f"{stopganho.MOTIVO}: +{sgn:g}% ({pct:+.1f}% líquido)"
            if why:
                r = self.sell(p, 1.0, px, t, why)
                if r:
                    out.append(r)
        return out

    def timeouts(self, t: float) -> list[dict]:
        lim = self.cfg["max_hold_h"] * 3600
        return [r for p in list(self.pos.values()) if t - p["open_t"] >= lim
                for r in [self.sell(p, 1.0, None, t, f"tempo máximo de {self.cfg['max_hold_h']:g} h")] if r]

    # ------------------------------------------------------------------ contas
    def wallet(self, now: float) -> dict:
        open_val = sum(max(0.0, self.value_now(p)) for p in self.pos.values())
        total = self.cash + open_val
        ini = self.cfg["saldo_inicial"]
        closed = self.trades
        wins = [x for x in closed if x["pnl_bnb"] > 0]
        return {"saldo": round(self.cash, 6), "em_posicoes": round(open_val, 6), "total": round(total, 6),
                "inicial": ini, "resultado": round(total - ini, 6), "resultado_pct": round(100 * (total - ini) / ini, 2) if ini else 0,
                "abertas": len(self.pos), "fechadas": len(closed), "acerto": round(100 * len(wins) / len(closed), 1) if closed else None,
                "realizado": round(sum(x["pnl_bnb"] for x in closed), 6), "periodos": periods(closed, now)}


def periods(trades: list[dict], now: float) -> list[dict]:
    out = []
    for h in (1, 6, 12, 24):
        xs = [x for x in trades if x["close_t"] >= now - h * 3600]
        out.append({"h": h, "n": len(xs), "ganhos": sum(1 for x in xs if x["pnl_bnb"] > 0),
                    "pnl": round(sum(x["pnl_bnb"] for x in xs), 6),
                    "investido": round(sum(x["bnb_in"] for x in xs), 6),
                    "traders": len({x["wallet"] for x in xs})})
    return out


def week_split(trades: list[dict], tz: str = "Europe/Berlin") -> dict:
    """Semana (segunda a sexta) × fim de semana, pela hora em que a posição fechou, e por dia da semana."""
    from datetime import datetime, timezone
    try:
        from zoneinfo import ZoneInfo
        z = ZoneInfo(tz)
    except Exception:
        z = timezone.utc
    names = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
    dias = {n: {"dia": n, "n": 0, "ganhos": 0, "pnl": 0.0} for n in names}
    blocos = {"semana": {"n": 0, "ganhos": 0, "pnl": 0.0, "investido": 0.0}, "fds": {"n": 0, "ganhos": 0, "pnl": 0.0, "investido": 0.0}}
    for x in trades:
        wd = datetime.fromtimestamp(x["close_t"], timezone.utc).astimezone(z).weekday()
        d, b = dias[names[wd]], blocos["fds" if wd >= 5 else "semana"]
        for o in (d, b):
            o["n"] += 1
            o["ganhos"] += 1 if x["pnl_bnb"] > 0 else 0
            o["pnl"] += x["pnl_bnb"]
        b["investido"] += x["bnb_in"]
    for o in list(dias.values()) + list(blocos.values()):
        o["pnl"] = round(o["pnl"], 6)
        o["acerto"] = round(100 * o["ganhos"] / o["n"], 1) if o["n"] else None
        if "investido" in o:
            o["investido"] = round(o["investido"], 6)
    return {"blocos": blocos, "dias": list(dias.values())}
