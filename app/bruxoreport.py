"""Relatórios da Aba do Bruxo (0.32.80, pedido do dono: "relatório a cada 30 min de tudo lá e usar esse conhecimento na base;
relatórios de 1 dia também").

Um relatório junta, no período: os sinais de top trader (quantos, em quantos entrou, por que não), o que os sinais e os
lançamentos sem trader fizeram (pico, quantos dobraram, quantos caíram −30% antes), as operações fechadas da aba e do
lançamento (resultado, acerto, causas das perdas, maiores ganhos e perdas) e as lições. `learn` junta os relatórios de
1 dia para a Base geral: dia a dia e as lições que se repetem.
"""
from __future__ import annotations

import statistics
from datetime import datetime, timezone

from .bruxo import Bruxo
from .tabreport import CAUSES, _group, _ts, loss_cause, trade_verdict

EVERY_S = 1800
ORIGENS = {"bruxo": "Aba do Bruxo", "lancamento": "Lançamento sem trader"}


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds")


def build(signals: list[dict], uid: str, trades: list[dict], positions: list[dict], start: float, end: float,
          tipo: str = "30min", stop_pct: float = 30, tp1_pct: float = 100) -> dict:
    sig = [s for s in signals if start <= float(s.get("t") or 0) < end]
    tr_sig = [s for s in sig if s.get("kind", "trader") == "trader"]
    la_sig = [s for s in sig if s.get("kind") == "lancamento"]
    entrou, nao = [], {}
    for s in tr_sig:
        d = (s.get("decisoes") or {}).get(uid)
        if d and d.get("entrou"):
            entrou.append(s)
        else:
            k = ((d or {}).get("motivo") or ("não era top trader seu" if d is None else "não entrou")).split(" (")[0]
            nao[k] = nao.get(k, 0) + 1
    pk = lambda L: round(statistics.median([s["peak_pct"] for s in L if s.get("peak_pct") is not None]), 1) if [s for s in L if s.get("peak_pct") is not None] else None
    nao_s = [s for s in tr_sig if s not in entrou]
    ops = [t for t in trades if t.get("origem") in ORIGENS and not t.get("real") and start <= _ts(t.get("closed_at")) < end]
    grupos = []
    for o, nome in ORIGENS.items():
        L = [t for t in ops if t.get("origem") == o]
        if not L:
            continue
        causas: dict[str, dict] = {}
        for t in L:
            if (t.get("pnl_sol") or 0) < 0:
                c = causas.setdefault(loss_cause(t), {"n": 0, "sol": 0.0})
                c["n"] += 1
                c["sol"] = round(c["sol"] - (t.get("pnl_sol") or 0), 5)
        grupos.append({"origem": o, "nome": nome, **_group(L),
                       "causas": [{"causa": k, "texto": CAUSES[k][0], "corrigir": CAUSES[k][1], **v}
                                  for k, v in sorted(causas.items(), key=lambda kv: -kv[1]["sol"])]})
    row = lambda t: {"origem": ORIGENS.get(t.get("origem"), t.get("origem")), "symbol": t.get("symbol"), "mint": t.get("mint"),
                     "abriu": t.get("opened_at"), "fechou": t.get("closed_at"), "pnl_sol": t.get("pnl_sol"), "pnl_pct": t.get("pnl_pct"),
                     "pico_pct": t.get("best_pct"), "hold_s": t.get("hold_s"), "saida": t.get("reason"), "veredito": trade_verdict(t)}
    est = Bruxo.study(tr_sig, stop_pct, tp1_pct)
    est_l = Bruxo.study(la_sig)
    tot = _group(ops)
    licoes = list(est.get("dicas") or [])
    if len(entrou) >= 3 and len(nao_s) >= 3 and pk(entrou) is not None and pk(nao_s) is not None:
        if pk(nao_s) > pk(entrou) * 1.5 and pk(nao_s) > 20:
            licoes.append(f"os sinais em que NÃO entrou subiram mais (pico mediano {pk(nao_s):+.0f}% contra {pk(entrou):+.0f}%): algum filtro está barrando os bons")
        elif pk(entrou) > pk(nao_s) * 1.5 and pk(entrou) > 20:
            licoes.append(f"os filtros acertam: onde entrou o pico mediano foi {pk(entrou):+.0f}%, onde não entrou {pk(nao_s):+.0f}%")
    if est_l.get("n", 0) >= 10 and est.get("n", 0) >= 10 and est_l.get("dobrou_pct") is not None and est.get("dobrou_pct") is not None:
        if est_l["dobrou_pct"] > est["dobrou_pct"]:
            licoes.append(f"lançamento sem trader dobrou mais ({est_l['dobrou_pct']}%) que o sinal de top trader ({est['dobrou_pct']}%)")
    for g in grupos:
        if g["n"] >= 3 and g["causas"]:
            c = g["causas"][0]
            licoes.append(f"{g['nome']}: maior causa das perdas é \"{c['texto']}\" ({c['n']}×) → {c['corrigir']}")
    if tot["n"] == 0 and not sig:
        veredito, porque = "sem dados", "nenhum sinal nem operação no período"
    elif tot["n"] < 3:
        veredito, porque = "poucos dados", f"{len(tr_sig)} sinais, {len(la_sig)} lançamentos e {tot['n']} operação(ões) fechada(s)"
    elif tot["pnl_sol"] > 0:
        veredito, porque = "ganhando", f"{tot['pnl_sol']:+.4f} SOL e {tot['acerto']}% de acerto"
    else:
        veredito, porque = "perdendo", f"{tot['pnl_sol']:+.4f} SOL e {tot['acerto']}% de acerto"
    return {"tipo": tipo, "t": end, "em": _iso(end), "inicio": _iso(start), "fim": _iso(end),
            "dia": datetime.fromtimestamp(start, timezone.utc).date().isoformat() if tipo == "dia" else None,
            "sinais": {"n": len(tr_sig), "entrou": len(entrou), "nao_entrou": sorted(({"motivo": k, "n": v} for k, v in nao.items()), key=lambda x: -x["n"])[:8],
                       "pico_entrou": pk(entrou), "pico_nao_entrou": pk(nao_s)},
            "estudo": {k: est.get(k) for k in ("n", "pico_mediano", "tempo_ate_pico_mediano_s", "dobrou_pct", "stop_antes_pct", "melhor_minuto", "por_idade")},
            "lancamento": {"n": len(la_sig), **{k: est_l.get(k) for k in ("pico_mediano", "dobrou_pct", "stop_antes_pct", "tempo_ate_pico_mediano_s")}},
            "operacoes": {**tot, "grupos": grupos},
            "maiores_ganhos": [row(t) for t in sorted([t for t in ops if (t.get("pnl_sol") or 0) > 0], key=lambda t: -(t.get("pnl_sol") or 0))[:5]],
            "maiores_perdas": [row(t) for t in sorted([t for t in ops if (t.get("pnl_sol") or 0) < 0], key=lambda t: t.get("pnl_sol") or 0)[:5]],
            "lista": [row(t) for t in sorted(ops, key=lambda t: -_ts(t.get("closed_at")))[:200]],
            "abertas": sum(1 for p in positions if p.get("origem") in ORIGENS and not p.get("real")),
            "veredito": veredito, "por_que": porque, "licoes": licoes}


def learn(days: list[dict]) -> dict:
    """Base geral: os relatórios de 1 dia lado a lado e as lições que aparecem em 2 dias ou mais."""
    rep: dict[str, int] = {}
    for d in days:
        for l in set(d.get("licoes") or []):
            k = l.split(":")[0][:80]
            rep[k] = rep.get(k, 0) + 1
    seen, licoes = set(), []
    for d in reversed(days):
        for l in d.get("licoes") or []:
            k = l.split(":")[0][:80]
            if rep.get(k, 0) >= 2 and k not in seen:
                seen.add(k)
                licoes.append({"licao": l, "dias": rep[k]})
    dias = [{"dia": d.get("dia"), "veredito": d.get("veredito"), "sinais": (d.get("sinais") or {}).get("n"),
             "entrou": (d.get("sinais") or {}).get("entrou"), "operacoes": (d.get("operacoes") or {}).get("n"),
             "acerto": (d.get("operacoes") or {}).get("acerto"), "pnl_sol": (d.get("operacoes") or {}).get("pnl_sol"),
             "dobrou_pct": (d.get("estudo") or {}).get("dobrou_pct"), "pico_mediano": (d.get("estudo") or {}).get("pico_mediano"),
             "lanc_dobrou_pct": (d.get("lancamento") or {}).get("dobrou_pct")} for d in days]
    return {"dias": list(reversed(dias))[:30], "licoes_repetidas": licoes[:10],
            "pnl_sol": round(sum((d.get("operacoes") or {}).get("pnl_sol") or 0 for d in days), 5)}
