"""Arquivo do histórico no PostgreSQL local da VPS (0.32.225, pedido do dono em 05/11/2026).

"Dividir o banco: históricos no Postgres local, o Supabase só com dados de usuários e consultas rápidas, no mínimo 7 dias."

Como funciona
- O Postgres da VPS (stack `postgres`) ganha um banco só do PUMP (`pump_arquivo`) com UMA tabela genérica `arquivo`
  (tabela de origem, chave, hora, linha inteira em jsonb). Só dados PÚBLICOS vão para lá (trades da BNB, vida dos
  tokens, estudo do passado do Jev): nada de usuário, chave ou posição, porque lá não existe o RLS do Supabase.
- Na frente dele roda um PostgREST (mesmo protocolo do Supabase), então o servidor fala com o arquivo pelo mesmo
  cliente (`SupaREST`), sem biblioteca nova. O PostgREST só aceita pedido com um token assinado com ARQUIVO_JWT_SECRET
  e não tem porta aberta para a internet.
- `mover`: a cada volta copia para o arquivo as linhas que passaram de `dias` no Supabase, confere que entraram e só
  então apaga do Supabase, em lotes pequenos. Se o arquivo não responde, nada é apagado.
- Sem ARQUIVO_URL e ARQUIVO_JWT_SECRET no stack, nada disso liga e tudo funciona como antes.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

import jwt

from .db import DBError, SupaREST

log = logging.getLogger("arquivo")

# tabela do Supabase → chave, coluna de hora, formato da hora, dias que ficam no Supabase
SPECS = [
    {"tabela": "jev_backtest", "pk": "id", "t": "em", "tipo": "iso", "dias": 0, "fica": {"_run"}},
    {"tabela": "bnb_fm_trades", "pk": "id", "t": "t", "tipo": "epoch", "dias": 7},
    {"tabela": "token_life", "pk": "mint", "t": "criado_em", "tipo": "iso", "dias": 7},
]
LOTE = 500                    # linhas por lote
LOTES_POR_VOLTA = 20          # até 10 mil linhas por tabela a cada volta (não pesa no Supabase)
VOLTA_S = 30 * 60


def _epoch(v, tipo: str) -> float | None:
    if v is None:
        return None
    if tipo == "epoch":
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _corte(spec: dict, now: float):
    t = now - spec["dias"] * 86400
    return t if spec["tipo"] == "epoch" else datetime.fromtimestamp(t, timezone.utc).isoformat()


class ArquivoREST(SupaREST):
    """O mesmo cliente do Supabase, apontando para o PostgREST local (sem o /rest/v1)."""

    def __init__(self, url: str, secret: str, http):
        super().__init__(url, "-", http)
        self.base = url.rstrip("/")
        tok = jwt.encode({"role": "pump_arquivo", "iss": "pump-fun-copy"}, secret, algorithm="HS256")
        self._h = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}

    async def delete_in(self, table: str, col: str, values: list[str]) -> None:
        await self._req("DELETE", table, {col: "in.(" + ",".join('"' + str(v).replace('"', "") + '"' for v in values) + ")"},
                        None, "return=minimal")


class Arquivo:
    def __init__(self, url: str, secret: str, http):
        self.rest = ArquivoREST(url, secret, http)
        self.st = {"ligado": True, "ok": None, "ultimo_erro": None, "volta": None, "movidas": {}, "no_arquivo": {}}

    @classmethod
    def from_env(cls, http) -> "Arquivo | None":
        url, sec = os.environ.get("ARQUIVO_URL", "").strip(), os.environ.get("ARQUIVO_JWT_SECRET", "").strip()
        return cls(url, sec, http) if url and len(sec) >= 32 else None

    # ------------------------------------------------------------------ leitura
    async def pages(self, tabela: str, since: float | None = None, until: float | None = None, page: int = 5000):
        """Linhas guardadas de uma tabela (em ordem de hora), em páginas."""
        off = 0
        while True:
            rows = await self.rest.select("arquivo", {"tabela": tabela}, order="t.asc", limit=page, offset=off,
                                          columns="dados", gte={"t": since} if since is not None else None,
                                          lte={"t": until} if until is not None else None)
            if not rows:
                return
            yield [r["dados"] for r in rows if isinstance(r.get("dados"), dict)]
            if len(rows) < page:
                return
            off += len(rows)

    # ------------------------------------------------------------------ escrita
    async def put(self, spec: dict, rows: list[dict]) -> list[str]:
        out, keys = [], []
        for r in rows:
            k, t = r.get(spec["pk"]), _epoch(r.get(spec["t"]), spec["tipo"])
            if k is None or t is None:
                continue
            out.append({"tabela": spec["tabela"], "pk": str(k), "t": t, "dados": r})
            keys.append(str(k))
        if out:
            await self.rest.insert("arquivo", out, upsert=True, on_conflict="tabela,pk")
        return keys

    async def confere(self, tabela: str, keys: list[str]) -> set[str]:
        got = set()
        for i in range(0, len(keys), 200):
            part = keys[i:i + 200]
            rows = await self.rest._req("GET", "arquivo", {"tabela": f"eq.{tabela}", "select": "pk",
                                                           "pk": "in.(" + ",".join('"' + k.replace('"', "") + '"' for k in part) + ")"})
            got |= {r["pk"] for r in rows or []}
        return got

    async def mover(self, db, spec: dict, now: float | None = None) -> int:
        """Copia o que passou de `dias` no Supabase, confere e só então apaga de lá. Devolve quantas linhas moveu."""
        now = now or time.time()
        moved = 0
        for _ in range(LOTES_POR_VOLTA):
            rows = await db.select(spec["tabela"], None, order=f"{spec['t']}.asc", limit=LOTE,
                                   lte={spec["t"]: _corte(spec, now)})
            rows = [r for r in rows or [] if str(r.get(spec["pk"])) not in spec.get("fica", ())]
            if not rows:
                break
            keys = await self.put(spec, rows)
            ok = await self.confere(spec["tabela"], keys)
            gone = [k for k in keys if k in ok]
            for i in range(0, len(gone), 100):
                await _delete_in(db, spec["tabela"], spec["pk"], gone[i:i + 100])
            moved += len(gone)
            if len(gone) < len(rows) or len(rows) < LOTE:
                break                                      # algo não conferiu, ou acabou: para por esta volta
        return moved

    async def volta(self, db) -> dict:
        self.st["volta"] = time.time()
        for spec in SPECS:
            try:
                n = await self.mover(db, spec)
                self.st["movidas"][spec["tabela"]] = self.st["movidas"].get(spec["tabela"], 0) + n
                self.st["ok"], self.st["ultimo_erro"] = True, None
            except Exception as e:
                self.st["ok"] = False
                self.st["ultimo_erro"] = f"{spec['tabela']}: {type(e).__name__}: {str(e)[:140]}"
                log.warning("arquivo: %s", self.st["ultimo_erro"])
        return self.st

    def status(self) -> dict:
        return {**self.st, "regras": [{"tabela": s["tabela"], "dias_no_supabase": s["dias"]} for s in SPECS]}


async def _delete_in(db, table: str, col: str, values: list[str]) -> None:
    """DELETE … WHERE col IN (…) no Supabase (o SupaREST só tem igualdade)."""
    if not values:
        return
    if hasattr(db, "delete_in"):
        await db.delete_in(table, col, values)
        return
    await db._req("DELETE", table, {col: "in.(" + ",".join('"' + str(v).replace('"', "") + '"' for v in values) + ")"},
                  None, "return=minimal")


__all__ = ["Arquivo", "ArquivoREST", "SPECS", "DBError"]
