"""Onde ficam os dados de UM usuário: posições, histórico, listas (manuais/banidas/pausadas) e feed.

`MemStore` guarda tudo na memória (usado nos testes e como cache). O `SupabaseStore` (app/db.py) herda dele e,
a cada mudança, agenda a gravação no banco em segundo plano — assim o motor de cópia continua síncrono e rápido,
igual ao original, e nada se perde ao reiniciar (o servidor recarrega do banco).
"""
from __future__ import annotations

import copy
import itertools
from collections import deque

FEED_KEEP = 500


class MemStore:
    def __init__(self):
        self._pos: dict = {}
        self._trades: list = []            # mais novo primeiro
        self._meta: dict = {}
        self._feed: deque = deque(maxlen=FEED_KEEP)
        self._ids = itertools.count(1)

    # ----------------------------------------------------------- ids
    def new_id(self):
        return next(self._ids)

    # ----------------------------------------------------------- posições
    def positions(self) -> list[dict]:
        """Cópias (como uma leitura do banco): mudar a posição só vale depois de save_pos()."""
        return [copy.deepcopy(p) for p in self._pos.values()]

    def save_pos(self, p: dict) -> None:
        if p.get("id") is None:
            p["id"] = self.new_id()
        self._pos[p["id"]] = copy.deepcopy(p)
        self._persist("pos_upsert", copy.deepcopy(p))

    def del_pos(self, p: dict) -> None:
        if self._pos.pop(p.get("id"), None) is not None:
            self._persist("pos_delete", p["id"])

    # ----------------------------------------------------------- histórico
    def trades(self, limit: int = 1000) -> list[dict]:
        return self._trades[:limit]

    def save_trade(self, t: dict) -> None:
        if t.get("id") is None:
            t["id"] = self.new_id()
        self._trades.insert(0, t)
        self._persist("trade_insert", dict(t))

    def reset_sim(self) -> None:
        """Apaga só o fictício (posições e trades com real=false)."""
        self._pos = {k: v for k, v in self._pos.items() if v.get("real")}
        self._trades = [t for t in self._trades if t.get("real")]
        self._persist("reset_sim", None)

    # ----------------------------------------------------------- listas (manual / banida / pausada)
    def meta_get(self, key: str, default):
        v = self._meta.get(key)
        return copy.deepcopy(v) if v is not None else default

    def meta_set(self, key: str, val) -> None:
        self._meta[key] = copy.deepcopy(val)
        self._persist("meta", (key, copy.deepcopy(val)))

    # ----------------------------------------------------------- feed (últimos 500)
    def feed_items(self) -> list[dict]:
        return list(self._feed)                  # mais novo primeiro

    def feed_add(self, item: dict) -> None:
        self._feed.appendleft(item)
        self._persist("feed", dict(item))

    def feed_clear(self) -> None:
        self._feed.clear()
        self._persist("feed_clear", None)

    # ----------------------------------------------------------- gravação (o SupabaseStore implementa)
    def _persist(self, op: str, data) -> None:
        return None
