"""0.32.338 (pedido do dono, 13/11/2026): BOT LIVE — carteira simulada própria com a estratégia da Robinhood da versão 0.32.308.

O motor (botlive_copy308.Copier) é o da 0.32.308 sem mudança. Ele recebe os mesmos trades da rede que a /hood (HoodWatch.extra), mas
enxerga o ranking pela regra da 0.32.308 (rank e clean_cfg copiados daquela versão): sem contar a perda que o trader ainda segura,
3 tokens fechados e robô acima de 400 trades/dia. A /hood e as outras salas não mudam. Nunca compra de verdade."""
from __future__ import annotations

import time

from .botlive_copy308 import Copier

CFG_DEFAULT = {"days": 1, "min_trades": 20, "min_winrate": 50.0, "min_closed": 3, "min_wallet_usd": 1000.0,
               "online_min": 10.0, "top_n": 10, "bot_per_day": 400}
CFG_LIMITS = {"days": (1, 1), "min_trades": (0, 100000), "min_winrate": (0, 100), "min_closed": (1, 1000),
              "min_wallet_usd": (0, 10_000_000), "online_min": (1, 1440), "top_n": (1, 50), "bot_per_day": (10, 100000)}


def clean_cfg(raw: dict | None) -> dict:
    out = dict(CFG_DEFAULT)
    for k, v in (raw or {}).items():
        if k not in CFG_DEFAULT:
            continue
        try:
            lo, hi = CFG_LIMITS[k]
            val = float(v)
            if val != val:
                continue
            val = min(hi, max(lo, val))
            out[k] = int(val) if isinstance(CFG_DEFAULT[k], int) else round(val, 4)
        except (TypeError, ValueError):
            continue
    return out


def rank(trades, now: float, cfg: dict, balances: dict) -> dict:
    """Ranking próprio pela regra do Top traders: os que mais lucraram no período (lucro realizado, em ETH); apto = trades
    mínimos, acerto acima do mínimo (tokens fechados com lucro), carteira com saldo mínimo, sem robô; copiaria os N
    melhores aptos que negociaram nos últimos X minutos. A proporção vendida usa a quantidade de token (as casas se cancelam)."""
    cfg = clean_cfg(cfg)
    since = now - cfg["days"] * 86400
    W: dict[str, dict] = {}
    for t in trades:
        if t["t"] < since:
            continue
        w = W.setdefault(t["wallet"], {"n": 0, "tk": {}, "first": t["t"], "last": t["t"], "vol": 0.0})
        w["n"] += 1
        w["first"], w["last"] = min(w["first"], t["t"]), max(w["last"], t["t"])
        w["vol"] += t["eth"]
        k = w["tk"].setdefault(t["token"], {"buy": 0.0, "sell": 0.0, "got": 0.0, "out": 0.0})
        if t["side"] == "buy":
            k["buy"] += t["eth"]
            k["got"] += t["amount"]
        else:
            k["sell"] += t["eth"]
            k["out"] += t["amount"]
    rows = []
    for wal, w in W.items():
        realized, win, closed, opened = 0.0, 0, 0, 0
        for k in w["tk"].values():
            if k["got"] <= 0:
                continue                                   # vendeu o que comprou antes da janela: sem custo conhecido
            frac = min(1.0, k["out"] / k["got"])
            if frac > 0:
                realized += k["sell"] - k["buy"] * frac
            if frac >= 0.9:
                closed += 1
                win += 1 if k["sell"] > k["buy"] * frac else 0
            else:
                opened += 1
        span_d = max(1.0, (w["last"] - w["first"]) / 86400)
        rows.append({"wallet": wal, "trades": w["n"], "realized_eth": round(realized, 6), "vol_eth": round(w["vol"], 4),
                     "tokens": len(w["tk"]), "closed": closed, "open": opened,
                     "winrate": round(100 * win / closed, 1) if closed else None, "last_t": w["last"],
                     "per_day": round(w["n"] / span_d, 1)})
    rows.sort(key=lambda r: r["realized_eth"], reverse=True)
    top = rows[:50]
    win_s = cfg["online_min"] * 60
    for r in top:
        flags = []
        if r["trades"] < cfg["min_trades"]:
            flags.append(f"{r['trades']} trades (precisa ≥ {cfg['min_trades']})")
        if r["winrate"] is None or r["closed"] < cfg["min_closed"]:
            flags.append(f"acerto desconhecido ({r['closed']} tokens fechados, precisa ≥ {cfg['min_closed']})")
        elif r["winrate"] <= cfg["min_winrate"]:
            flags.append(f"acerto {r['winrate']:.0f}% (precisa > {cfg['min_winrate']:.0f}%)")
        if r["per_day"] > cfg["bot_per_day"]:
            flags.append(f"robô: {r['per_day']:.0f} trades por dia")
        bal = balances.get(r["wallet"])
        if bal and bal.get("contrato"):
            flags.append("é um contrato (robô), não uma pessoa: costuma negociar em pools que só ele consegue vender")
        r["contrato"] = bool(bal and bal.get("contrato"))
        r["wallet_usd"] = bal.get("usd") if bal else None
        if cfg["min_wallet_usd"]:
            if bal is None or bal.get("usd") is None:
                flags.append("conferindo saldo da carteira…")
            elif bal["usd"] < cfg["min_wallet_usd"]:
                flags.append(f"carteira ${bal['usd']:,.0f} < ${cfg['min_wallet_usd']:,.0f}".replace(",", "."))
        r["flags"], r["eligible"] = flags, not flags
        r["online"] = now - r["last_t"] <= win_s
    chosen = [r["wallet"] for r in top if r["eligible"] and r["online"]][:cfg["top_n"]]
    for r in top:
        r["copiaria"] = r["wallet"] in chosen
    return {"rows": top, "copiaria": chosen, "carteiras": len(rows),
            "aptos": sum(1 for r in top if r["eligible"]), "aptos_online": sum(1 for r in top if r["eligible"] and r["online"])}


class Watch308:
    """O HoodWatch visto pelo BOT LIVE: tudo igual, menos o ranking (regra da 0.32.308)."""

    def __init__(self, watch):
        self._w = watch
        self._cache = None

    def __getattr__(self, k):
        return getattr(self._w, k)

    def danger_reason(self, wallet: str):
        """0.32.340 (pedido do dono): o BOT LIVE não usa as regras de bloqueio de trader (PERIGO): todo top trader é copiado."""
        return None

    def cfg308(self) -> dict:
        raw = dict(getattr(self._w, "cfg", {}) or {})
        # a regra nova (0.32.322) trocou 3 → 5 tokens fechados e 400 → 150 trades/dia; quem estava no padrão volta ao da 0.32.308
        if raw.get("v") == 2:
            if raw.get("min_closed") == 5:
                raw["min_closed"] = 3
            if raw.get("bot_per_day") == 150:
                raw["bot_per_day"] = 400
        return clean_cfg(raw)

    def ranking(self, now: float | None = None) -> dict:
        now = now or time.time()
        if self._cache and now - self._cache[0] < 15:
            return self._cache[1]
        r = rank(self._w.trades, now, self.cfg308(), self._w.balances)
        # todos os top traders: os TOP_N com mais lucro realizado no período, sem apto/online/PERIGO (0.32.340, pedido do dono)
        r["copiaria"] = [x["wallet"] for x in r["rows"] if (x.get("realized_eth") or 0) > 0][:TOP_N]
        for row in r["rows"]:
            row["copiaria"] = row["wallet"] in r["copiaria"]
        self._cache = (now, r)
        return r


# 0.32.340 (pedido do dono, 13/11: "o BOT LIVE entra em todos os top traders, sem as regras de bloqueio de traders, e sai nas melhores
# regras de stop móvel e stop de perda"): a carteira do BOT copia os TOP_N que mais lucraram no ranking da 0.32.308, sem os filtros de
# apto/online/PERIGO. A conferência do token (venda que o pool recusa) continua: sem ela a carteira compraria o que não consegue vender.
TOP_N = 20
# Saídas do BOT LIVE (a 0.32.308 vinha sem stop de perda: casos de −31% e −41% na fictícia da Robinhood). Aplicadas uma vez a quem ainda
# estava no padrão da 0.32.308; depois o dono muda pela tela.
SAIDAS = {"stop_pct": 15.0, "trail_on": True, "trail_ativa_pct": 15.0, "trail_dist_pct": 8.0, "max_hold_h": 3.0, "max_abertas": 20}
SAIDAS_308 = {"stop_pct": 0.0, "trail_ativa_pct": 20.0, "trail_dist_pct": 10.0, "max_hold_h": 6.0}


class BotLive(Copier):
    """Motor da 0.32.308 com o ranking da 0.32.308. Sem cofre e sem a trava geral: a parte REAL nunca roda."""

    def __init__(self, watch, http, db=None):
        super().__init__(Watch308(watch), http, db)
        self.vault, self.real_allowed = None, False
        self.obs: dict[str, str] = {}                # 0.32.347: conta → sha256 do código do link do OBS (o código mesmo nunca é guardado)

    # 0.32.347 (pedido do dono: "o link do OBS entra na tela de login, deveria entrar direto"): o link leva um código só de leitura
    # da SALA LIVE dessa conta. O banco guarda só o hash; gerar um novo derruba o anterior.
    def obs_new(self, uid: str) -> str:
        import hashlib
        import secrets
        k = secrets.token_urlsafe(24)
        self.obs[uid] = hashlib.sha256(k.encode()).hexdigest()
        self.book(uid).dirty_book = True
        return k

    def obs_user(self, k: str) -> str | None:
        import hashlib
        import hmac
        if not isinstance(k, str) or not 20 <= len(k) <= 80:
            return None
        h = hashlib.sha256(k.encode()).hexdigest()
        for uid, v in self.obs.items():
            if v and hmac.compare_digest(v, h):
                return uid
        return None

    def _book_extra(self, uid: str) -> dict:
        return {"obs_hash": self.obs[uid]} if self.obs.get(uid) else {}

    def _book_loaded(self, row: dict) -> None:
        h = (row.get("cfg") or {}).get("obs_hash")
        if isinstance(h, str) and len(h) == 64:
            self.obs[row["user_id"]] = h

    def on_trade(self, tr: dict, before: float, copiaria) -> None:
        return super().on_trade(tr, before, set(self.w.ranking()["copiaria"]))

    # 0.32.339 (pedido do dono: "mesmo que a sala não esteja online, o BOT estará fazendo automático"): toda conta que usa a Robinhood
    # ganha a carteira do BOT LIVE sozinha (gravada no banco), sem precisar abrir a página. Antes ela só nascia ao abrir o BOT LIVE.
    def book(self, uid: str):
        b = super().book(uid)
        if all(abs(float(b.cfg.get(k) or 0) - v) < 1e-9 for k, v in SAIDAS_308.items()):     # ainda no padrão da 0.32.308
            from .botlive_copy308 import clean_cfg
            b.cfg = clean_cfg(SAIDAS, b.cfg)
            b.dirty_book = True
        return b

    def ensure_books(self) -> int:
        n = 0
        for uid in list(getattr(getattr(self.w._w, "copier", None), "books", {}) or {}):
            if uid not in self.books:
                self.book(uid)
                n += 1
        return n

    async def load(self) -> None:
        await super().load()
        self.ensure_books()

    async def tick(self) -> None:
        self.ensure_books()
        await super().tick()
