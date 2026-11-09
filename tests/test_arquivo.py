"""0.32.225: histórico no Postgres da VPS (PostgREST local). Sem internet: Supabase e arquivo falsos."""
import asyncio
import time

import jwt

from app import arquivo as A
from tests.test_api import env  # noqa: F401  (fixture env, 0.32.271)


class _Supa:
    def __init__(self, rows):
        self.rows, self.deleted = list(rows), []

    async def select(self, table, filters=None, order=None, limit=None, columns="*", offset=0, gte=None, lte=None, **k):
        col, lim = list(lte.items())[0]
        rs = [r for r in self.rows if r[col] <= lim]
        rs.sort(key=lambda r: r[col])
        return rs[:limit]

    async def delete_in(self, table, col, values):
        self.deleted += values
        self.rows = [r for r in self.rows if r[col] not in values]


class _Arq(A.Arquivo):
    def __init__(self, lose=()):
        self.st = {"ligado": True, "ok": None, "ultimo_erro": None, "volta": None, "movidas": {}, "no_arquivo": {}}
        self.saved, self.lose = {}, set(lose)

    async def put(self, spec, rows):
        keys = []
        for r in rows:
            k = str(r[spec["pk"]])
            if k not in self.lose:
                self.saved[(spec["tabela"], k)] = r
            keys.append(k)
        return keys

    async def confere(self, tabela, keys):
        return {k for k in keys if (tabela, k) in self.saved}


SPEC = {"tabela": "bnb_fm_trades", "pk": "id", "t": "t", "tipo": "epoch", "dias": 7}


def test_moves_only_older_than_7_days_and_deletes_after_check():
    now = time.time()
    supa = _Supa([{"id": "velho1", "t": now - 9 * 86400}, {"id": "velho2", "t": now - 8 * 86400}, {"id": "novo", "t": now - 3600}])
    arq = _Arq()
    assert asyncio.run(arq.mover(supa, SPEC, now)) == 2
    assert sorted(supa.deleted) == ["velho1", "velho2"] and [r["id"] for r in supa.rows] == ["novo"]
    assert ("bnb_fm_trades", "velho1") in arq.saved


def test_never_deletes_what_did_not_reach_the_archive():
    now = time.time()
    supa = _Supa([{"id": "a", "t": now - 9 * 86400}, {"id": "b", "t": now - 9 * 86400 + 1}])
    arq = _Arq(lose={"b"})
    assert asyncio.run(arq.mover(supa, SPEC, now)) == 1
    assert supa.deleted == ["a"] and [r["id"] for r in supa.rows] == ["b"]


def test_jev_state_row_stays_and_iso_times():
    spec = A.SPECS[0]
    supa = _Supa([{"id": "_run", "em": "2026-11-01T00:00:00+00:00"}, {"id": "base:x", "em": "2026-11-01T00:00:01+00:00"}])
    arq = _Arq()
    assert asyncio.run(arq.mover(supa, spec)) == 1 and supa.deleted == ["base:x"]
    assert A._epoch("2026-11-01T00:00:01Z", "iso") == 1793491201.0


def test_volta_records_errors_without_deleting():
    class Boom(_Supa):
        async def select(self, *a, **k):
            raise A.DBError("HTTP 503")
    arq = _Arq()
    st = asyncio.run(arq.volta(Boom([])))
    assert st["ok"] is False and "503" in st["ultimo_erro"]


def test_from_env_needs_url_and_long_secret(monkeypatch):
    monkeypatch.delenv("ARQUIVO_URL", raising=False)
    assert A.Arquivo.from_env(None) is None
    monkeypatch.setenv("ARQUIVO_URL", "http://pump_arquivo_api:3000")
    monkeypatch.setenv("ARQUIVO_JWT_SECRET", "curto")
    assert A.Arquivo.from_env(None) is None
    sec = "s" * 40
    monkeypatch.setenv("ARQUIVO_JWT_SECRET", sec)
    a = A.Arquivo.from_env(None)
    tok = a.rest._h["Authorization"].split()[1]
    assert jwt.decode(tok, sec, algorithms=["HS256"])["role"] == "pump_arquivo" and a.rest.base == "http://pump_arquivo_api:3000"


def test_keeps_only_90_days_once_a_day():
    calls = []

    class R:
        async def _req(self, method, table, params=None, body=None, prefer=None):
            calls.append((method, table, params))
            return []
    arq = _Arq()
    arq.rest = R()
    now = 2_000_000_000.0
    asyncio.run(arq.limpa(now))
    asyncio.run(arq.limpa(now + 3600))                         # no mesmo dia: não repete
    assert calls == [("DELETE", "arquivo", {"t": f"lt.{now - 90 * 86400}"})] and A.GUARDA_DIAS == 90


def test_fila_acelera_a_proxima_volta(monkeypatch):
    """0.32.229: enquanto uma tabela enche a volta (há fila no Supabase), a próxima vem em 5 min."""
    monkeypatch.setattr(A, "LOTE", 2)
    monkeypatch.setattr(A, "LOTES_POR_VOLTA", 2)
    old = time.time() - 30 * 86400
    arq = _Arq()
    arq.st["limpou_em"] = time.time()
    db = _Supa([{"id": str(i), "t": old + i} for i in range(9)])
    monkeypatch.setattr(A, "SPECS", [{"tabela": "bnb_fm_trades", "pk": "id", "t": "t", "tipo": "epoch", "dias": 7}])
    asyncio.run(arq.volta(db))
    assert arq.st["fila"] and arq.espera() == A.VOLTA_RAPIDA_S
    asyncio.run(arq.volta(db)); asyncio.run(arq.volta(db))
    assert not db.rows and not arq.st["fila"] and arq.espera() == A.VOLTA_S


def test_hist_select_junta_supabase_e_arquivo(env):
    """0.32.271: consulta que pede mais dias que o Supabase guarda completa com o arquivo, filtrando pelo conteúdo."""
    from datetime import datetime, timedelta, timezone
    hub = env["hub"]
    novo = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

    class _Sel:
        def __init__(self, rows):
            self.rows, self.calls = rows, []

        async def select(self, table, eq=None, order=None, limit=None, columns="*", gte=None, **k):
            self.calls.append((table, eq, gte))
            return self.rows[:limit]

    hub.db = _Sel([{"id": "a", "em": novo, "user_id": "u1"}])
    arq = _Arq()
    arq.rest = _Sel([{"dados": {"id": "b", "em": "2026-10-01T00:00:00+00:00", "user_id": "u1"}},
                     {"dados": {"id": "a", "em": novo, "user_id": "u1"}}])
    hub.arquivo = arq
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    rows = asyncio.run(hub.hist_select("robot_log", {"user_id": "u1"}, "em", 600, since))
    assert [r["id"] for r in rows] == ["a", "b"]                                   # sem repetir o que já veio do Supabase
    t, eq, gte = arq.rest.calls[0]
    assert eq == {"tabela": "robot_log", "dados->>user_id": "u1"} and gte["t"] > 0
    recente = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    arq.rest.calls.clear()
    asyncio.run(hub.hist_select("robot_log", {"user_id": "u1"}, "em", 600, recente))
    assert arq.rest.calls == []                                                    # dentro dos 7 dias: só o Supabase
