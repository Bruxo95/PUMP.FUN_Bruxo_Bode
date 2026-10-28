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


# 0.32.24 (pedido do dono: "houve melhora? colocar porcentagem; mais informação; explicar cada linha no mouse"):
# direção boa de cada linha (+1 = maior é melhor, −1 = menor é melhor, 0 = só informação) e o que ela significa
EXTRA = (("dias", "Dias que a evolução valeu"), ("sombras_ganhariam", "Barrados que teriam ganho"),
         ("bloqueios", "Faixas bloqueadas (aprender com os erros)"))
SENTIDO = {"operacoes": 0, "ganhos": 1, "perdas": -1, "acerto": 1, "lucro_sol": 1, "por_trade": 1, "media_pct": 1,
           "sombras": 0, "sombras_media_pct": -1, "sombras_ganhariam": -1, "real_operacoes": 0, "real_lucro_sol": 1,
           "dias": 0, "bloqueios": 0}
EXPLICA = {
    "operacoes": "Compras automáticas do Explorar que fecharam (fictícia) enquanto esta evolução valia.",
    "ganhos": "Dessas operações, quantas fecharam no lucro, já com taxas.",
    "perdas": "Quantas fecharam no prejuízo ou zeradas, já com taxas.",
    "acerto": "Ganhos ÷ operações. Pts = diferença em pontos percentuais.",
    "lucro_sol": "Soma do resultado das operações em SOL (fictícia, já com taxas).",
    "por_trade": "Lucro ÷ operações: quanto cada operação rendeu em média. É a melhor medida para comparar evoluções de tamanhos diferentes.",
    "media_pct": "Média do resultado em % de cada operação.",
    "sombras": "Tokens 'chance alta' que o filtro barrou nesse período (entradas sombra: o sistema finge que entrou).",
    "sombras_media_pct": "Quanto os barrados teriam dado em média se tivessem entrado. MENOR é melhor: o filtro acertou ao barrar.",
    "sombras_ganhariam": "Quantos barrados teriam dado lucro. MENOR é melhor: o filtro barrou menos coisa boa.",
    "real_operacoes": "Operações do Explorar na carteira REAL no período.",
    "real_lucro_sol": "Resultado da carteira REAL no período, em SOL.",
    "dias": "Por quanto tempo esta evolução ficou valendo (até a próxima).",
    "bloqueios": "Faixas que o 'aprender com os erros' bloqueava nessa evolução (ex.: risco 4 a 6).",
}
MIN_BASE = 5                     # menos que isto nos dois lados = "poucos dados" (não dá para dizer se melhorou)


def _val(r: dict, k: str):
    if k == "bloqueios":
        return len((r.get("estado") or {}).get("bloqueios") or [])
    return r.get(k)


def comparar(a: dict, b: dict) -> list[dict]:
    """Linha a linha: valor da evolução A, da B, a diferença (B − A), a variação % e se melhorou."""
    out = []
    for k, nome in METRICS + EXTRA:
        va, vb = _val(a, k), _val(b, k)
        dif = None if va is None or vb is None else round(vb - va, 6)
        # linhas que já são % (acerto, médias) mostram a diferença em pontos; variação % só nas contagens e no SOL
        pct = (round((vb - va) / abs(va) * 100, 1) if dif is not None and va not in (0, 0.0)
               and k not in ("acerto", "media_pct", "sombras_media_pct") else None)
        s = SENTIDO.get(k, 0)
        melhor = None if dif is None or s == 0 or dif == 0 else ("melhorou" if dif * s > 0 else "piorou")
        out.append({"chave": k, "nome": nome, "a": va, "b": vb, "diferenca": dif, "pct": pct, "melhor": melhor,
                    "explica": EXPLICA.get(k, "")})
    return out


def veredito(a: dict, b: dict) -> dict:
    """Resumo: melhorou ou piorou, por quê e com que base. Operações fechadas mandam; sem base, usa os barrados."""
    na, nb = a.get("operacoes") or 0, b.get("operacoes") or 0
    if na >= MIN_BASE and nb >= MIN_BASE and a.get("por_trade") is not None and b.get("por_trade") is not None:
        d = b["por_trade"] - a["por_trade"]
        pct = round(d / abs(a["por_trade"]) * 100, 1) if a["por_trade"] else None
        return {"resultado": "melhorou" if d > 0 else "piorou" if d < 0 else "igual", "pct": pct, "base": "operações",
                "texto": f"Lucro por operação {a['por_trade']:+.4f} → {b['por_trade']:+.4f} SOL ({na} × {nb} operações)."}
    sa, sb = a.get("sombras") or 0, b.get("sombras") or 0
    if sa >= MIN_BASE and sb >= MIN_BASE and a.get("sombras_media_pct") is not None and b.get("sombras_media_pct") is not None:
        d = b["sombras_media_pct"] - a["sombras_media_pct"]
        return {"resultado": "melhorou" if d < 0 else "piorou" if d > 0 else "igual", "pct": None, "base": "barrados",
                "texto": f"Sem operações suficientes; pelos barrados, o filtro {'acertou mais' if d < 0 else 'errou mais'} "
                         f"({a['sombras_media_pct']:+.1f}% → {b['sombras_media_pct']:+.1f}% se tivesse entrado; {sa} × {sb} barrados)."}
    return {"resultado": "poucos dados", "pct": None, "base": None,
            "texto": f"Precisa de pelo menos {MIN_BASE} operações (ou {MIN_BASE} barrados) em cada evolução para dizer se melhorou. "
                     f"Agora: {na} × {nb} operações, {sa} × {sb} barrados."}


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
