"""Aplica no Supabase as migrações de supabase/migrations/ que ainda não foram aplicadas (só biblioteca padrão).

Roda no GitHub Actions antes de publicar a imagem, com o segredo SUPABASE_ACCESS_TOKEN (autorizado pelo dono em
2026-10-25). Usa a Management API (POST /v1/projects/{ref}/database/query). Cada migração roda numa transação junto
com o registro em public.app_migracoes, então ou entra inteira e fica registrada, ou não entra.
As três primeiras já estavam aplicadas à mão antes desta automação e são só registradas (linha de base).
Nunca imprime o token. Sem o segredo, avisa e sai sem erro.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "vnvfluimpqvxbvdbmwqa"
API = f"https://api.supabase.com/v1/projects/{PROJECT}/database/query"
BASELINE = ("20261025000001_inicial.sql", "20261025000002_admin.sql", "20261025000003_chaves_sistema.sql")
NAME = re.compile(r"\d{14}_[a-z0-9_]+\.sql")

CONTROLE = """
create table if not exists public.app_migracoes (
  nome         text primary key,
  aplicada_em  timestamptz not null default now()
);
alter table public.app_migracoes enable row level security;
revoke all on public.app_migracoes from anon, authenticated;
"""


def query(token: str, sql: str):
    req = urllib.request.Request(API, data=json.dumps({"query": sql}).encode(), method="POST", headers={
        "Authorization": "Bearer " + token, "Content-Type": "application/json",
        "User-Agent": "pump-fun-copy-migracoes/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        body = e.read()[:400].decode("utf-8", "replace").replace(token, "***")
        raise SystemExit(f"Supabase recusou (HTTP {e.code}): {body}") from None
    return json.loads(raw) if raw else []


def pending(files: list[str], applied: set[str]) -> list[str]:
    for f in files:
        if not NAME.fullmatch(f):
            raise SystemExit(f"Nome de migração fora do padrão: {f}")
    return [f for f in sorted(files) if f not in applied]


def main() -> int:
    token = os.environ.get("SUPABASE_ACCESS_TOKEN", "").strip()
    if not token:
        print("SUPABASE_ACCESS_TOKEN não configurado: nenhuma migração aplicada (aplicar à mão no SQL Editor).")
        return 0
    query(token, CONTROLE)
    base = ", ".join(f"('{n}')" for n in BASELINE)
    query(token, f"insert into public.app_migracoes (nome) values {base} on conflict (nome) do nothing;")
    rows = query(token, "select nome from public.app_migracoes;")
    applied = {r["nome"] for r in rows if isinstance(r, dict) and r.get("nome")}
    files = [p.name for p in (ROOT / "supabase/migrations").glob("*.sql")]
    todo = pending(files, applied)
    if not todo:
        print(f"Banco em dia: {len(applied)} migrações registradas, nada a aplicar.")
        return 0
    for name in todo:
        sql = (ROOT / "supabase/migrations" / name).read_text(encoding="utf-8")
        query(token, f"begin;\n{sql}\ninsert into public.app_migracoes (nome) values ('{name}');\ncommit;")
        print(f"Aplicada: {name}")
    print(f"{len(todo)} migração(ões) aplicada(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
