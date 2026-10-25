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
                 now: float | None = None) -> dict:
        now = time.time() if now is None else now
        self._trim(now)
        allowed = set(wallets)
        cutoff = now - min(MAX_WINDOW_S, max(60, window_min * 60))
        events = [e for e in self._events if e["wallet"] in allowed and cutoff <= e["at"] <= now]
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
        waves.sort(key=lambda w: (-w["last_trade"], -w["wallet_count"], w["mint"]))
        truncated = any(self._dropped_at.get(w, 0) >= cutoff for w in allowed) or len(waves) > MAX_WAVES
        return {"observed_since": self.observed_since, "event_count": len(events),
                "truncated": truncated, "waves": waves[:MAX_WAVES]}
