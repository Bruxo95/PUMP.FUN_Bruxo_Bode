"""Acesso ao Supabase (Postgres via PostgREST) com a SERVICE KEY — só no servidor, nunca vai para o navegador.

Como a service key passa por cima do RLS, TODA consulta aqui filtra por user_id explicitamente; o user_id vem
sempre do token validado (app/auth.py), nunca do que o navegador manda.

- `SupaREST`: cliente HTTP mínimo (select / insert / upsert / delete / rpc).
- `SupabaseStore`: os dados de UM usuário em memória (igual ao MemStore) + gravação no banco em segundo plano.
- `Vault`: chaves pessoais criptografadas (AES-256-GCM) — salvar, remover, abrir.
- `audit()`: registra ações sensíveis no audit_log.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import deque

from .crypto import SecretBox
from .keystore import SECRET_NAMES
from .store import FEED_KEEP, MemStore

log = logging.getLogger("db")

LIST_KIND = {"pump_manual": "manual", "pump_banned": "banida", "pump_paused": "pausada"}


class DBError(Exception):
    pass


class SupaREST:
    def __init__(self, url: str, service_key: str, http):
        self.base = url.rstrip("/") + "/rest/v1"
        self.http = http
        self._h = {"apikey": service_key, "Authorization": f"Bearer {service_key}",
                   "Content-Type": "application/json"}

    @staticmethod
    def _params(filters: dict | None) -> dict:
        out = {}
        for k, v in (filters or {}).items():
            if isinstance(v, bool):
                v = "true" if v else "false"
            out[k] = f"eq.{v}"
        return out

    async def _req(self, method: str, table: str, params=None, body=None, prefer: str | None = None):
        h = dict(self._h)
        if prefer:
            h["Prefer"] = prefer
        r = await self.http.request(method, f"{self.base}/{table}", params=params or {},
                                    content=json.dumps(body) if body is not None else None, headers=h, timeout=15)
        if r.status_code >= 300:
            raise DBError(f"Supabase {method} {table}: HTTP {r.status_code} {r.text[:200]}")
        if not r.content:
            return []
        try:
            return r.json()
        except ValueError:
            return []

    async def select(self, table: str, filters: dict | None = None, order: str | None = None,
                     limit: int | None = None, columns: str = "*") -> list[dict]:
        p = self._params(filters)
        p["select"] = columns
        if order:
            p["order"] = order
        if limit:
            p["limit"] = str(limit)
        return await self._req("GET", table, p)

    async def insert(self, table: str, rows: list[dict] | dict, upsert: bool = False,
                     on_conflict: str | None = None) -> None:
        p = {"on_conflict": on_conflict} if on_conflict else None
        prefer = "return=minimal" + (",resolution=merge-duplicates" if upsert else "")
        await self._req("POST", table, p, rows, prefer)

    async def update(self, table: str, filters: dict, values: dict) -> None:
        if not filters:
            raise DBError("update sem filtro")
        await self._req("PATCH", table, self._params(filters), values, "return=minimal")

    async def delete(self, table: str, filters: dict) -> None:
        if not filters:
            raise DBError("delete sem filtro")
        await self._req("DELETE", table, self._params(filters), None, "return=minimal")

    async def rpc(self, fn: str, args: dict):
        return await self._req("POST", f"rpc/{fn}", None, args)


# --------------------------------------------------------------------------- dados de um usuário
class SupabaseStore(MemStore):
    """Igual ao MemStore (o motor lê da memória), mas cada mudança entra numa fila que `flush()` grava no banco."""

    def __init__(self, db, user_id: str):
        super().__init__()
        self.db, self.user_id = db, user_id
        self._q: deque = deque()
        self._feed_added = 0
        self.last_error: str | None = None

    def new_id(self):
        return uuid.uuid4().hex

    def _persist(self, op: str, data) -> None:
        self._q.append((op, data))
        if len(self._q) > 20000:                   # banco fora do ar por muito tempo: não estoura a memória
            self._q.popleft()

    async def load(self) -> None:
        uid = self.user_id
        for r in await self.db.select("pump_positions", {"user_id": uid}):
            self._pos[r["id"]] = dict(r.get("data") or {}, id=r["id"], real=bool(r.get("real")))
        rows = await self.db.select("pump_trades", {"user_id": uid}, order="fechada_em.desc", limit=20000)
        self._trades = [dict(r.get("data") or {}, id=r["id"], real=bool(r.get("real"))) for r in rows]
        lists = await self.db.select("pump_lists", {"user_id": uid})
        man = sorted([r for r in lists if r["tipo"] == "manual"], key=lambda r: (r.get("extra") or {}).get("ord", 0))
        self._meta["pump_manual"] = [r["wallet"] for r in man]
        self._meta["pump_banned"] = [r["wallet"] for r in lists if r["tipo"] == "banida"]
        self._meta["pump_paused"] = {r["wallet"]: dict(r.get("extra") or {}) for r in lists if r["tipo"] == "pausada"}
        for r in await self.db.select("pump_feed", {"user_id": uid}, order="id.desc", limit=FEED_KEEP):
            self._feed.append(r.get("data") or {})

    async def flush(self) -> int:
        """Grava o que mudou. Se o banco falhar, a fila fica e tenta de novo na próxima rodada."""
        n = 0
        while self._q:
            seg = []
            while self._q and self._q[0][0] != "reset_sim":
                seg.append(self._q.popleft())
            try:
                await self._write(seg)
                n += len(seg)
            except Exception as e:
                for item in reversed(seg):
                    self._q.appendleft(item)
                self.last_error = str(e)[:200]
                log.warning("Gravação no banco (usuário %s…) falhou: %s", self.user_id[:8], self.last_error)
                return n
            if self._q and self._q[0][0] == "reset_sim":
                try:
                    await self.db.delete("pump_positions", {"user_id": self.user_id, "real": False})
                    await self.db.delete("pump_trades", {"user_id": self.user_id, "real": False})
                    self._q.popleft()
                    n += 1
                except Exception as e:
                    self.last_error = str(e)[:200]
                    return n
        self.last_error = None
        return n

    async def _write(self, seg: list) -> None:
        uid = self.user_id
        pos: dict = {}                                # id -> último estado (upsert) ou None (apagar)
        trades, feed, meta, feed_clear = [], [], {}, False
        for op, d in seg:
            if op == "pos_upsert":
                pos[str(d["id"])] = d
            elif op == "pos_delete":
                pos[str(d)] = None
            elif op == "trade_insert":
                trades.append(d)
            elif op == "meta":
                meta[d[0]] = d[1]
            elif op == "feed":
                feed.append(d)
            elif op == "feed_clear":
                feed, feed_clear = [], True
        up = [{"id": k, "user_id": uid, "real": bool(v.get("real")), "data": {x: y for x, y in v.items() if x != "id"}}
              for k, v in pos.items() if v is not None]
        if up:
            await self.db.insert("pump_positions", up, upsert=True, on_conflict="id")
        for k, v in pos.items():
            if v is None:
                await self.db.delete("pump_positions", {"user_id": uid, "id": k})
        if trades:
            await self.db.insert("pump_trades", [{"id": str(t["id"]), "user_id": uid, "real": bool(t.get("real")),
                                                  "data": {x: y for x, y in t.items() if x != "id"}} for t in trades],
                                 upsert=True, on_conflict="id")
        for key, val in meta.items():
            tipo = LIST_KIND.get(key)
            if not tipo:
                continue
            await self.db.delete("pump_lists", {"user_id": uid, "tipo": tipo})
            if key == "pump_paused":
                rows = [{"user_id": uid, "tipo": tipo, "wallet": w, "extra": x} for w, x in (val or {}).items()]
            else:
                rows = [{"user_id": uid, "tipo": tipo, "wallet": w, "extra": {"ord": i}} for i, w in enumerate(val or [])]
            if rows:
                await self.db.insert("pump_lists", rows)
        if feed_clear:
            await self.db.delete("pump_feed", {"user_id": uid})
        if feed:
            await self.db.insert("pump_feed", [{"user_id": uid, "data": f} for f in reversed(feed)])
            self._feed_added += len(feed)
            if self._feed_added >= 100:
                self._feed_added = 0
                await self.db.rpc("trim_pump_feed", {"p_user": uid, "p_keep": FEED_KEEP})


# --------------------------------------------------------------------------- chaves criptografadas
class Vault:
    def __init__(self, db, box: SecretBox):
        self.db, self.box = db, box

    async def load(self, user_id: str) -> dict:
        """Chaves do usuário já abertas (só na memória do servidor). Chave que não abre é ignorada."""
        out = {}
        for r in await self.db.select("user_secrets", {"user_id": user_id}):
            try:
                out[r["nome"]] = self.box.decrypt(user_id, r["nome"], r["valor_criptografado"])
            except Exception:
                log.warning("Chave %s do usuário %s… não abriu (APP_ENCRYPTION_KEY trocada?)", r["nome"], user_id[:8])
        return out

    async def names(self, user_id: str) -> set:
        return {r["nome"] for r in await self.db.select("user_secrets", {"user_id": user_id}, columns="nome")}

    async def save(self, user_id: str, name: str, value: str) -> None:
        if name not in SECRET_NAMES:
            raise ValueError("nome de chave desconhecido")
        await self.db.insert("user_secrets", {"user_id": user_id, "nome": name,
                                              "valor_criptografado": self.box.encrypt(user_id, name, value)},
                             upsert=True, on_conflict="user_id,nome")

    async def delete(self, user_id: str, name: str) -> None:
        await self.db.delete("user_secrets", {"user_id": user_id, "nome": name})


async def audit(db, user_id: str, acao: str, detalhe: str = "") -> None:
    """Nunca coloque chave no detalhe. Falha ao gravar não derruba a ação (fica no log do servidor)."""
    try:
        await db.insert("audit_log", {"user_id": user_id, "acao": acao, "detalhe": (detalhe or "")[:500]})
    except Exception as e:
        log.warning("audit_log não gravou (%s): %s", acao, str(e)[:120])


async def flush_all(stores) -> None:
    await asyncio.gather(*(s.flush() for s in stores), return_exceptions=True)
