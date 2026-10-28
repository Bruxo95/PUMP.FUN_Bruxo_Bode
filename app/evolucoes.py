"""Evoluções do cérebro (0.31.85, pedido do dono em 2026-10-28: "a cada evolução ter relatório, comparar uma com a
outra e poder voltar para a anterior se algo der errado").

Uma evolução (E1, E2…) é cada vez que o cérebro da Base geral muda: faixa bloqueada/liberada pelo aprender com os erros
ou nova melhor regra de saída. A foto da evolução guarda as faixas bloqueadas daquele momento. O relatório de uma
evolução é calculado do histórico (operações do Explorar fechadas no período em que ela valeu). "Voltar para" congela
o cérebro da conta naquela foto (opção A do dono: o robô continua aprendendo sozinho; voltar é só quando ele pedir).
"""
from __future__ import annotations

import re
from collections import Counter

from .auto_trades import ts

METRICS = (("operacoes", "Operações"), ("ganhos", "Ganhos"), ("perdas", "Perdas"), ("acerto", "Acerto"),
           ("lucro_sol", "Lucro (SOL)"), ("por_trade", "Por operação (SOL)"), ("media_pct", "Média por operação (%)"),
           ("sombras", "Barrados (sombras)"), ("sombras_media_pct", "Barrados: média se tivesse entrado (%)"),
           ("real_operacoes", "Operações reais"), ("real_lucro_sol", "Lucro real (SOL)"))


def estado(learned: dict, melhor_regra: str | None) -> dict:
    """O que a evolução guarda: as faixas bloqueadas completas (para poder voltar) e a melhor regra de saída."""
    keep = ("feature", "faixa", "nome", "n", "acerto", "media_pct")
    return {"bloqueios": [{k: x.get(k) for k in keep} for x in learned.get("bloqueios") or []],
            "melhor_regra": melhor_regra}


def _in(t: dict, ini: float, fim: float | None) -> bool:
    c = ts(t.get("closed_at"))
    return c is not None and c >= ini and (fim is None or c < fim)


def relatorio(trades: list[dict], ini: float, fim: float | None, mudancas: list | None = None,
              ajustes: list | None = None, real: list | None = None) -> dict:
    """Compras, vendas, o que aprendeu e o que deu errado no período em que a evolução valeu (só o Explorar)."""
    ops = [t for t in trades if t.get("origem") == "explorar" and not t.get("real") and not t.get("sombra") and _in(t, ini, fim)]
    sh = [t for t in trades if t.get("origem") == "explorar" and t.get("sombra") and _in(t, ini, fim)]
    rl = [t for t in (real or []) if t.get("origem") == "explorar" and t.get("real") and _in(t, ini, fim)]
    n = len(ops)
    wins = [t for t in ops if (t.get("pnl_sol") or 0) > 0]
    lucro = sum(t.get("pnl_sol") or 0 for t in ops)
    motivos = Counter(re.sub(r"[-+]?\d+(?:[.,]\d+)?", "#", str(t.get("reason") or "sem motivo"))[:80]
                      for t in ops if (t.get("pnl_sol") or 0) <= 0)
    exemplo = {}
    for t in ops:
        if (t.get("pnl_sol") or 0) <= 0:
            exemplo.setdefault(re.sub(r"[-+]?\d+(?:[.,]\d+)?", "#", str(t.get("reason") or "sem motivo"))[:80], str(t.get("reason") or "sem motivo")[:120])
    piores = sorted(ops, key=lambda t: t.get("pnl_sol") or 0)[:5]
    return {
        "inicio": ini, "fim": fim, "dias": round(((fim or max([ts(t.get("closed_at")) or ini for t in ops + sh] + [ini])) - ini) / 86400, 2),
        "operacoes": n, "ganhos": len(wins), "perdas": n - len(wins),
        "acerto": round(len(wins) / n, 3) if n else None, "lucro_sol": round(lucro, 6),
        "por_trade": round(lucro / n, 6) if n else None,
        "media_pct": round(sum(t.get("pnl_pct") or 0 for t in ops) / n, 1) if n else None,
        "sombras": len(sh), "sombras_media_pct": round(sum(t.get("pnl_pct") or 0 for t in sh) / len(sh), 1) if sh else None,
        "sombras_ganhariam": sum(1 for t in sh if (t.get("pnl_pct") or 0) > 0),
        "real_operacoes": len(rl), "real_lucro_sol": round(sum(t.get("pnl_sol") or 0 for t in rl), 6),
        "piores": [{"symbol": t.get("symbol"), "pnl_pct": t.get("pnl_pct"), "pnl_sol": t.get("pnl_sol"), "reason": t.get("reason"),
                    "closed_at": t.get("closed_at")} for t in piores if (t.get("pnl_sol") or 0) < 0],
        "motivos_perda": [{"motivo": exemplo[k], "n": v} for k, v in motivos.most_common(8)],
        "aprendeu": list(mudancas or []),
        "ajustes": [{"em": a.get("em"), "acao": a.get("acao"), "motivo": a.get("motivo")} for a in (ajustes or [])
                    if ts(a.get("em")) is not None and ts(a.get("em")) >= ini and (fim is None or ts(a.get("em")) < fim)],
    }


def comparar(a: dict, b: dict) -> list[dict]:
    """Linha a linha: valor da evolução A, da B e a diferença (B − A)."""
    out = []
    for k, nome in METRICS:
        va, vb = a.get(k), b.get(k)
        out.append({"chave": k, "nome": nome, "a": va, "b": vb,
                    "diferenca": None if va is None or vb is None else round(vb - va, 6)})
    return out


def reverter_ajustes(log_rows: list[dict], desde: float) -> dict:
    """Configuração de saída de antes do primeiro ajuste automático aplicado depois de `desde` (por tipo)."""
    out: dict = {}
    seen = set()
    for r in sorted(log_rows, key=lambda r: ts(r.get("em")) or 0):
        if r.get("acao") != "aplicou" or (ts(r.get("em")) or 0) < desde or r.get("tipo") in seen:
            continue
        seen.add(r.get("tipo"))
        out.update((r.get("detalhe") or {}).get("antes") or {})
    return out
