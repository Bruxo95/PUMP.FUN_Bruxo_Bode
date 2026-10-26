"""Relatórios das mudanças feitas pela IA (0.31.7, pedido do dono em 2026-10-26).

Fluxo: o dono baixa o relatório do dia (PDF ou texto para IA) em Relatórios, manda para uma IA revisar; a IA corrige o
código e, na mesma entrega, cria aqui um arquivo `AAAA-MM-DD-versao.md` dizendo o que mudou, por quê, com base em qual
relatório e a PROJEÇÃO de ganho depois da mudança. O painel lista esses arquivos e compara a projeção com o realizado
(média de resultado por dia antes e depois da data da mudança, dos relatórios diários guardados).

Formato (cabeçalho entre --- obrigatório; o teste tests/test_changes.py confere todos os arquivos):
---
versao: 0.31.7
data: 2026-10-26
autor: nome da IA/modelo
baseado_em: relatório de AAAA-MM-DD (ou "pedido do dono")
projecao_sol_dia: +0.05          (número em SOL por dia na carteira fictícia, ou "nao_estimado")
projecao_texto: uma frase explicando a conta da projeção
---
texto livre em Markdown: o que estava errado, o que mudou, onde, como medir.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path

DIR = Path(__file__).resolve().parent / "relatorios_ia"
REQUIRED = ("versao", "data", "autor", "baseado_em", "projecao_sol_dia", "projecao_texto")


def parse(text: str, name: str = "") -> dict:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if not m:
        raise ValueError(f"{name}: sem cabeçalho entre ---")
    head = {}
    for ln in m.group(1).splitlines():
        if ":" in ln:
            k, v = ln.split(":", 1)
            head[k.strip()] = v.strip()
    miss = [k for k in REQUIRED if not head.get(k)]
    if miss:
        raise ValueError(f"{name}: faltam {', '.join(miss)}")
    datetime.strptime(head["data"], "%Y-%m-%d")
    proj = head["projecao_sol_dia"]
    head["projecao_sol_dia"] = None if proj.lower().startswith("nao") else float(proj.replace(",", "."))
    return {**head, "nome": name, "texto": m.group(2).strip()}


def load(folder: Path | None = None) -> list[dict]:
    out = []
    for p in sorted((folder or DIR).glob("*.md"), reverse=True):
        try:
            out.append(parse(p.read_text(encoding="utf-8"), p.stem))
        except ValueError as e:
            out.append({"nome": p.stem, "erro": str(e)})
    return out


def realized(change: dict, days: list[dict]) -> dict:
    """Média de resultado por dia (SOL, fictícia) 7 dias antes × depois da data da mudança (dia da mudança fora)."""
    d0 = datetime.strptime(change["data"], "%Y-%m-%d").date()
    by = {str(r.get("dia")): (r.get("pnl_sol") or 0) for r in days}
    before = [by[str(d0 - timedelta(days=i))] for i in range(1, 8) if str(d0 - timedelta(days=i)) in by]
    after = [by[str(d0 + timedelta(days=i))] for i in range(1, 8) if str(d0 + timedelta(days=i)) in by]
    avg = lambda xs: round(sum(xs) / len(xs), 6) if xs else None  # noqa: E731
    b, a = avg(before), avg(after)
    return {"antes_sol_dia": b, "depois_sol_dia": a, "dias_antes": len(before), "dias_depois": len(after),
            "diferenca_sol_dia": round(a - b, 6) if a is not None and b is not None else None}
