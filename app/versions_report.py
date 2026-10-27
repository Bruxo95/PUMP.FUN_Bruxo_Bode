"""Resultado por versão (0.31.50, pedido do dono em 2026-10-27).

Quanto o sistema ganhou e perdeu em cada versão (do momento em que ela entrou até a próxima), fictícia e real
separadas, e se a versão AJUDOU ou PIOROU em relação à anterior com base suficiente. A métrica é o resultado médio por
trade fechado (a duração e o movimento de cada versão variam muito, então o total sozinho engana).

As horas de entrada vêm de `app/versoes.json` (gerado do Git; cada entrega acrescenta a sua). O deploy entra uns minutos
depois do commit: trades desses minutos contam na versão nova. Só cálculo (sem rede).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

MIN_TRADES = 5            # menos que isso numa versão = "pouca base"
MARGIN_SOL = 0.001        # diferença de média por trade abaixo disso = "igual"
FILE = os.path.join(os.path.dirname(__file__), "versoes.json")


def _ts(x) -> float | None:
    try:
        d = datetime.fromisoformat(str(x).replace("Z", "+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()
    except (TypeError, ValueError):
        return None


def load(path: str = FILE) -> list[dict]:
    try:
        return list(json.load(open(path, encoding="utf-8")).get("versoes") or [])
    except Exception:
        return []


def _agg(T: list[dict]) -> dict:
    n = len(T)
    pnl = sum(t.get("pnl_sol") or 0 for t in T)
    wins = sum(1 for t in T if (t.get("pnl_sol") or 0) > 0)
    return {"trades": n, "pnl_sol": round(pnl, 6), "acerto": round(wins / n, 3) if n else None,
            "media": round(pnl / n, 6) if n else None}


def build(trades: list[dict], versions: list[dict], now: float | None = None, real: bool = False) -> dict:
    now = datetime.now(timezone.utc).timestamp() if now is None else now
    V = sorted([v for v in versions if _ts(v.get("inicio"))], key=lambda v: _ts(v["inicio"]))
    closed = sorted([(c, t) for t in trades if (c := _ts(t.get("closed_at")))], key=lambda x: x[0])
    rows, acc, acc_r, prev = [], 0.0, 0.0, None
    for i, v in enumerate(V):
        s = _ts(v["inicio"])
        e = _ts(V[i + 1]["inicio"]) if i + 1 < len(V) else now
        sim = _agg([t for c, t in closed if s <= c < e and not t.get("real")])
        rl = _agg([t for c, t in closed if s <= c < e and t.get("real")])
        main = rl if real else sim
        acc += sim["pnl_sol"]
        acc_r += rl["pnl_sol"]
        r = {"versao": v["versao"], "titulo": v.get("titulo") or "", "inicio": v["inicio"], "horas": round((e - s) / 3600, 2),
             "sim": sim, "real": rl, "acumulado_sim": round(acc, 6), "acumulado_real": round(acc_r, 6), "dif_media": None}
        if main["trades"] < MIN_TRADES:
            r["veredito"] = "pouca base"
        elif prev is None:
            r["veredito"] = "primeira medida"
        else:
            d = main["media"] - prev[("real" if real else "sim")]["media"]
            r["dif_media"], r["comparada_com"] = round(d, 6), prev["versao"]
            r["veredito"] = "ajudou" if d > MARGIN_SOL else "piorou" if d < -MARGIN_SOL else "igual"
        if main["trades"] >= MIN_TRADES:
            prev = r
        rows.append(r)
    based = [r for r in rows if r["veredito"] in ("ajudou", "piorou", "igual", "primeira medida")]
    key = "real" if real else "sim"
    best = max(based, key=lambda r: r[key]["media"], default=None)
    worst = min(based, key=lambda r: r[key]["media"], default=None)
    sug = []
    for r in rows:
        if r["veredito"] == "piorou":
            sug.append(f"A versão {r['versao']} ({r['titulo']}) piorou o resultado médio por trade em {r['dif_media']:+.4f} SOL "
                       f"em relação à {r['comparada_com']} ({r[key]['trades']} trades). Conferir o que ela mudou e, se for regra de "
                       "trade, testar voltar atrás nas Estratégias fantasma antes de mexer.")
    if best and best is not worst:
        sug.append(f"A melhor fase foi a versão {best['versao']} ({best['titulo']}): média {best[key]['media']:+.4f} SOL por trade "
                   f"em {best[key]['trades']} trades. O que ela mudou é candidato a manter.")
    if not based:
        sug.append("Ainda não há versões com base suficiente (5+ trades fechados) para comparar.")
    return {"modo": "real" if real else "simulado", "versoes": rows, "total_sim": round(acc, 6), "total_real": round(acc_r, 6),
            "ajudou": sum(1 for r in rows if r["veredito"] == "ajudou"), "piorou": sum(1 for r in rows if r["veredito"] == "piorou"),
            "melhor": best["versao"] if best else None, "pior": worst["versao"] if worst else None,
            "sugestoes": sug, "min_trades": MIN_TRADES}


def compact(rep: dict, n: int = 12) -> list[dict]:
    """As últimas versões com base, para o relatório do dia e o texto da IA."""
    key = "real" if rep.get("modo") == "real" else "sim"
    return [{"versao": r["versao"], "titulo": r["titulo"], "trades": r[key]["trades"], "pnl_sol": r[key]["pnl_sol"],
             "media": r[key]["media"], "veredito": r["veredito"]} for r in rep["versoes"] if r[key]["trades"]][-n:]


def ai_text(rep: dict, version: str) -> str:
    key = "real" if rep.get("modo") == "real" else "sim"
    L = [f"# Resultado por versão - PUMP FUN COPY (sistema {version}, carteira {rep['modo']})", "",
         f"Total fictícia {rep['total_sim']:+.4f} SOL · total real {rep['total_real']:+.4f} SOL · versões que ajudaram {rep['ajudou']} · "
         f"pioraram {rep['piorou']} · melhor {rep['melhor']} · pior {rep['pior']}", "",
         "## Versão a versão (trades fechados enquanto ela estava no ar; média = resultado por trade)",
         "versão    trades  resultado     média/trade  veredito         o que mudou"]
    for r in rep["versoes"]:
        x = r[key]
        if not x["trades"]:
            continue
        L.append(f"{r['versao']:<9} {x['trades']:>6}  {x['pnl_sol']:+.4f} SOL  {(x['media'] or 0):+.5f}     {r['veredito']:<16} {r['titulo']}")
    L += ["", "## O que ajudou e o que melhorar"] + [f"- {s}" for s in rep["sugestoes"]]
    L += ["", "## Instruções para a IA",
          "Repositório github.com/Bruxo95/PUMP.FUN_Bruxo_Bode (leia CLAUDE.md). Use esta tabela para dizer quais mudanças deram "
          "lucro e quais deram prejuízo, proponha o que manter, o que desfazer e o que testar (sempre primeiro no simulado e nas "
          "Estratégias fantasma). Não mude a lógica do Explorar nem as configurações salvas dos usuários sem pedido do dono."]
    return "\n".join(L)
