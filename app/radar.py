"""Radar observacional: convergência das carteiras em estudo, sem criar ordens.

O buffer guarda apenas dados públicos vistos ao vivo neste processo. Cada consulta
filtra a lista atual do usuário antes de calcular qualquer número. Não infere
identidade de influencer nem reconstrói compras a partir de posições históricas.
"""
from __future__ import annotations

import math
import time
from collections import deque


MAX_WINDOW_S = 30 * 60
MAX_WAVES = 100


def callout_policy(min_wallets: int) -> dict:
    """Critérios observáveis do destaque; não são previsão ou chance de lucro."""
    return {"entry_window_s": 120, "entry_memory_s": MAX_WINDOW_S,
            "last_buy_max_age_s": 60, "stale_after_s": 180,
            "min_buy_pressure_pct": 80, "min_wallets": min_wallets,
            "order": ["hot", "selling", "watch", "stale", "incomplete"]}


def _callout(wave: dict, policy: dict, now: float, connected: bool, truncated: bool,
             first_entries: dict[tuple[str, str], float]) -> dict:
    participants = wave["wallets"]
    # A memória maior impede que uma recompra vire entrada nova ao sair da janela.
    recent = sum(first_entries[(wave["mint"], p["wallet"])] >= now - policy["entry_window_s"]
                 for p in participants)
    last_buy = max(p["last_buy"] for p in participants)
    age = max(0, now - last_buy)
    # Dispersão dos participantes na janela visível; não usa a memória de entradas.
    span = max(p["first_buy"] for p in participants) - min(p["first_buy"] for p in participants)
    pressure = wave["buy_pressure"]
    selling = wave["seller_count"] > 0
    if not connected or truncated:
        state = "incomplete"
    elif selling:
        state = "selling"
    elif age > policy["stale_after_s"]:
        state = "stale"
    elif (recent >= policy["min_wallets"] and age <= policy["last_buy_max_age_s"]
          and pressure is not None and pressure >= policy["min_buy_pressure_pct"] and wave["net_sol"] > 0):
        state = "hot"
    else:
        state = "watch"
    labels = {"hot": "HOT", "selling": "Participantes vendendo", "watch": "Em observação",
              "stale": "Esfriou", "incomplete": "Dados incompletos"}
    reasons = []
    if state == "incomplete":
        missing = []
        if not connected:
            missing.append("monitor desconectado")
        if truncated:
            missing.append("limite da janela atingido")
        reasons.append(" e ".join(missing).capitalize() + "; destaque HOT suspenso.")
    if selling:
        sellers = wave["seller_count"]
        reasons.append(("1 participante começou a vender" if sellers == 1 else f"{sellers} participantes começaram a vender")
                       + " após a primeira compra observada.")
    pressure_text = f"{pressure:.1f}".replace(".", ",") if pressure is not None else None
    net_text = f"{wave['net_sol']:+.4f}".replace(".", ",")
    reasons.extend([
        f"{recent} carteiras distintas começaram a comprar nos últimos {policy['entry_window_s']} s; "
        f"mínimo HOT: {policy['min_wallets']}.",
        f"Última compra há {age:.0f} s; HOT até {policy['last_buy_max_age_s']} s, "
        f"esfria após {policy['stale_after_s']} s.",
        (f"Pressão observada: {pressure_text}%" if pressure is not None else "Pressão observada: sem volume")
        + f"; mínimo HOT: {policy['min_buy_pressure_pct']}%. Fluxo líquido: {net_text} SOL.",
    ])
    return {"state": state, "label": labels[state], "reasons": reasons,
            "recent_wallets": recent, "last_buy_age_s": age, "convergence_span_s": max(0, span), "rank": 0}


class RadarBuffer:
    def __init__(self, max_events: int = 5000, now: float | None = None):
        if not isinstance(max_events, int) or isinstance(max_events, bool) or max_events < 1:
            raise ValueError("limite do buffer inválido")
        self.max_events = max_events
        self.observed_since = time.time() if now is None else now
        self._events: deque[dict] = deque()
        self._seen: set[tuple[str, str]] = set()
        self._dropped_at: dict[str, float] = {}
        self._sequence = 0

    def _trim(self, now: float) -> None:
        # Ordem de chegada, independente de eventos com blockTime fora de ordem.
        while self._events and self._events[0]["seen_at"] < now - MAX_WINDOW_S:
            old = self._events.popleft()
            self._seen.discard((old["wallet"], old["signature"]))
        self._dropped_at = {w: at for w, at in self._dropped_at.items() if at >= now - MAX_WINDOW_S}
        # Também limita metadados de truncamento caso muitas listas sejam alteradas.
        if len(self._dropped_at) > self.max_events:
            self._dropped_at = dict(sorted(self._dropped_at.items(), key=lambda item: -item[1])[:self.max_events])

    def record(self, wallet: str, ev: dict, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        self._trim(now)
        if not isinstance(ev, dict) or not isinstance(wallet, str) or not wallet or len(wallet) > 128:
            return False
        sig, mint, side = ev.get("signature"), ev.get("mint"), ev.get("txType")
        if (not isinstance(sig, str) or not sig or len(sig) > 256 or not isinstance(mint, str)
                or not mint or len(mint) > 128 or side not in ("buy", "sell")):
            return False
        try:
            at = float(ev["blockTime"]) if ev.get("blockTime") is not None else now
            sol = float(ev.get("solAmount") or 0)
            tokens = float(ev.get("tokenAmount") or 0)
        except (TypeError, ValueError, OverflowError):
            return False
        if (not all(math.isfinite(v) for v in (at, sol, tokens)) or not 0 <= sol <= 1e12
                or not 0 <= tokens <= 1e30
                or at <= 0 or at > now or at < now - MAX_WINDOW_S):
            return False
        key = (wallet, sig)
        if key in self._seen:
            return False
        if len(self._events) >= self.max_events:
            old = self._events.popleft()
            self._seen.discard((old["wallet"], old["signature"]))
            self._dropped_at[old["wallet"]] = max(old["at"], self._dropped_at.get(old["wallet"], 0))
        self._sequence += 1
        self._events.append({"wallet": wallet, "signature": sig, "mint": mint, "side": side,
                             "at": at, "order": self._sequence, "seen_at": now, "sol": sol})
        self._seen.add(key)
        self._trim(now)
        return True

    def snapshot(self, wallets, min_wallets: int = 2, window_min: int = 5,
                 now: float | None = None, *, connected: bool = True) -> dict:
        now = time.time() if now is None else now
        self._trim(now)
        allowed = set(wallets)
        policy = callout_policy(min_wallets)
        cutoff = now - min(MAX_WINDOW_S, max(60, window_min * 60))
        events = []
        first_entries: dict[tuple[str, str], float] = {}
        for e in self._events:
            if e["wallet"] not in allowed or not now - policy["entry_memory_s"] <= e["at"] <= now:
                continue
            if e["side"] == "buy":
                key = (e["mint"], e["wallet"])
                first_entries[key] = min(e["at"], first_entries.get(key, e["at"]))
            if e["at"] >= cutoff:
                events.append(e)
        by_token: dict[str, list[dict]] = {}
        for e in events:
            by_token.setdefault(e["mint"], []).append(e)
        waves = []
        for mint, rows in by_token.items():
            buys = [e for e in rows if e["side"] == "buy"]
            first_by_wallet: dict[str, tuple[float, int]] = {}
            for e in buys:
                stamp = (e["at"], e["order"])
                first_by_wallet[e["wallet"]] = min(stamp, first_by_wallet.get(e["wallet"], stamp))
            if len(first_by_wallet) < min_wallets:
                continue
            # Uma venda anterior à entrada observada não pertence a esta onda.
            sells = [e for e in rows if e["side"] == "sell" and e["wallet"] in first_by_wallet
                     and (e["at"], e["order"]) > first_by_wallet[e["wallet"]]]
            details = []
            for wallet, first in sorted(first_by_wallet.items(), key=lambda item: (item[1], item[0])):
                wb = [e for e in buys if e["wallet"] == wallet]
                ws = [e for e in sells if e["wallet"] == wallet]
                details.append({"wallet": wallet, "first_buy": first[0], "last_buy": max(e["at"] for e in wb),
                                "last_sell": max((e["at"] for e in ws), default=None),
                                "buy_sol": round(sum(e["sol"] for e in wb), 8),
                                "sell_sol": round(sum(e["sol"] for e in ws), 8)})
            buy_sol, sell_sol = sum(e["sol"] for e in buys), sum(e["sol"] for e in sells)
            first_buy = min(stamp[0] for stamp in first_by_wallet.values())
            waves.append({"mint": mint, "symbol": None, "wallet_count": len(first_by_wallet),
                          "buy_count": len(buys), "sell_count": len(sells),
                          "buy_sol": round(buy_sol, 8), "sell_sol": round(sell_sol, 8),
                          "net_sol": round(buy_sol - sell_sol, 8), "first_buy": first_buy,
                          "last_trade": max(e["at"] for e in buys + sells), "age_s": max(0, now - first_buy),
                          "status": "selling" if sells else "accumulating",
                          "seller_count": len({e["wallet"] for e in sells}),
                          "buy_pressure": round(100 * buy_sol / (buy_sol + sell_sol), 1)
                          if buy_sol + sell_sol else None, "wallets": details})
        # Uma perda anterior à janela visível também pode apagar a âncora de entrada.
        truncated = any(w in self._dropped_at and self._dropped_at[w] >= now - policy["entry_memory_s"]
                        for w in allowed) or len(waves) > MAX_WAVES
        for wave in waves:
            wave["callout"] = _callout(wave, policy, now, connected, truncated, first_entries)
        priority = {state: rank for rank, state in enumerate(policy["order"])}
        waves.sort(key=lambda w: (priority[w["callout"]["state"]], -w["callout"]["recent_wallets"],
                                 -w["wallet_count"], -(w["buy_pressure"] if w["buy_pressure"] is not None else -1),
                                 -max(p["last_buy"] for p in w["wallets"]), w["mint"]))
        waves = waves[:MAX_WAVES]
        for rank, wave in enumerate(waves, 1):
            wave["callout"]["rank"] = rank
        return {"observed_since": self.observed_since, "event_count": len(events),
                "truncated": truncated, "callout_policy": policy, "waves": waves}
