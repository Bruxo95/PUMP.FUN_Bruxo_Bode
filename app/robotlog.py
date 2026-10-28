"""Aprendizado dos logs dos robôs (0.31.91, pedido do dono em 2026-10-28: "depois de 14 dias criar um aprendizado e não
deletar o que ele fez").

Os registros de 5 min (explore_cycles e robot_log) nunca são apagados. Uma vez por dia cada robô ganha um resumo do dia
(robot_daily): quanto analisou, quanto entrou e os motivos de recusa somados. É o que fica para comparar dias, semanas e
meses sem precisar abrir milhares de registros.
"""
from __future__ import annotations

import re


def _key(m: str) -> str:
    return re.sub(r"[-+]?\d+(?:[.,]\d+)?", "#", str(m))[:90]


def rollup(blocos: list[dict]) -> dict:
    """Soma os registros de 5 min de um dia (do Explorar ou dos outros robôs)."""
    mot: dict[str, list] = {}
    nomes = set()
    for b in blocos:
        for m in b.get("motivos") or []:
            mot.setdefault(_key(m["motivo"]), [0, m["motivo"]])[0] += int(m.get("n") or 0)
        nomes.update(b.get("entrou") or [])
    tot = sum(v[0] for v in mot.values()) or 1
    motivos = sorted(({"motivo": v[1], "n": v[0], "pct": round(v[0] / tot * 100, 1)} for v in mot.values()), key=lambda m: -m["n"])[:12]
    return {"registros": len(blocos), "analisados": sum(int(b.get("analisados") or 0) for b in blocos),
            "entradas": len(nomes), "nomes": sorted(nomes)[:30],
            "chance_alta": sum(int(b.get("chance_alta") or 0) for b in blocos),
            "sem_preco": sum(int(b.get("sem_preco") or 0) for b in blocos),
            "motivos": motivos, "gargalo": motivos[0]["motivo"] if motivos else None}


def trend(dias: list[dict]) -> dict:
    """O que mudou ao longo dos dias: média de entradas por dia e o motivo que mais barrou no período inteiro."""
    if not dias:
        return {}
    mot: dict[str, list] = {}
    for d in dias:
        for m in (d.get("data") or {}).get("motivos") or []:
            mot.setdefault(_key(m["motivo"]), [0, m["motivo"]])[0] += int(m.get("n") or 0)
    top = max(mot.values(), key=lambda v: v[0])[1] if mot else None
    ent = [int((d.get("data") or {}).get("entradas") or 0) for d in dias]
    return {"dias": len(dias), "entradas_total": sum(ent), "entradas_media_dia": round(sum(ent) / len(dias), 2),
            "dias_sem_entrada": sum(1 for x in ent if x == 0), "motivo_principal": top}
