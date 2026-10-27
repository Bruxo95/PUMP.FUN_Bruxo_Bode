"""Relatório do dia (0.31.5, pedido do dono em 2026-10-26: "salvar o que está na Visão geral, aprender, e no fim do
dia sugerir o que melhorar no código, nos trades e na lógica").

- A cada 30 min guarda uma foto dos números da Visão geral (saldo, resultado, posições, trades, acerto, traders,
  monitor) na tabela daily_report (uma linha por usuário por dia, com as fotos do dia).
- O relatório olha os trades do dia (e o histórico) e devolve diagnósticos e sugestões com número e base mínima.
  Nada é aplicado sozinho: as sugestões dizem o que mudar e onde.
- Na virada do dia (UTC) o relatório do dia anterior fica fechado e, com o Telegram ligado, vai um resumo.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone

MAX_POINTS = 60
MAX_TRADES = 300
try:                                                   # mesmo fuso do /health e do rodapé (Europe/Berlin)
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/Berlin")
except Exception:                                      # sem tzdata: horário UTC
    TZ = timezone.utc
TZ_NAME = "horário de Berlim (CET)" if TZ is not timezone.utc else "UTC"


def hhmm(t: float | None, seconds: bool = True) -> str:
    if not t:
        return "-"
    return datetime.fromtimestamp(t, TZ).strftime("%H:%M:%S" if seconds else "%H:%M")


def _ts(x) -> float | None:
    try:
        d = datetime.fromisoformat(str(x).replace("Z", "+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()
    except (TypeError, ValueError):
        return None


def day_of(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).date().isoformat()


def kpis(pf) -> dict:
    """Os números da Visão geral (carteira fictícia), no formato guardado em cada foto."""
    w = pf.wallet(False)
    return {"t": time.time(), "saldo": w["equity_sol"], "resultado": w["pnl_sol"], "abertas": w["open"],
            "valor_aberto": w["open_value_sol"], "fechados": w["count"], "ganhos": w["wins"], "perdas": w["losses"],
            "acerto": w["win_rate"], "traders": len(pf.followed), "pausados": len(pf.paused()),
            "monitor": bool((pf.rpc_status or {}).get("ws"))}


def _origin(t: dict) -> str:
    if t.get("origem") in ("explorar", "base", "elite"):
        return {"explorar": "Explorar (automática)", "base": "Base (automática)", "elite": "Maiores traders (automática)"}[t["origem"]]
    if t.get("manual") or t.get("wallet") == "manual":
        return "Botão Comprar / Base (manual ou automática antiga)"
    return "Cópia de trader"


def _exit(reason: str) -> str:
    low = (reason or "").lower()
    for k, name in (("stop de perda", "stop de perda"), ("stop móvel", "stop móvel"), ("trader vendeu", "trader vendeu"),
                    ("venda em partes", "venda em partes"), ("alvo", "alvo"), ("tempo máximo", "tempo máximo"),
                    ("dev vendeu", "dev vendeu"), ("segurou", "segurou até lucro"), ("boost", "boost"),
                    ("elite vendeu", "trader da elite vendeu"), ("pressão", "pressão virou")):
        if k in low:
            return name
    return "outro"


def build(pf, day: str, points: list[dict] | None = None, real: bool = False, all_trades: list[dict] | None = None) -> dict:
    """Relatório de um dia (UTC) da carteira fictícia ou, com real=True (0.31.45, pedido do dono: "o relatório do dia
    tem que acompanhar o real"), da carteira REAL, com diagnósticos e sugestões."""
    trades = [t for t in (pf.trades(100000) if all_trades is None else all_trades) if bool(t.get("real")) == real]
    T = [t for t in trades if day_of(_ts(t.get("closed_at")) or 0) == day]
    n = len(T)
    wins = [t for t in T if (t.get("pnl_sol") or 0) > 0]
    pnl = round(sum(t.get("pnl_sol") or 0 for t in T), 6)
    fees = round(sum(t.get("fees_sol") or 0 for t in T), 6)
    inv = sum(t.get("sol_in") or 0 for t in T)

    def group(key):
        g: dict[str, list] = {}
        for t in T:
            g.setdefault(key(t), []).append(t)
        return sorted(({"nome": k, "trades": len(r), "pnl_sol": round(sum(x.get("pnl_sol") or 0 for x in r), 6),
                        "acerto": round(sum(1 for x in r if (x.get("pnl_sol") or 0) > 0) / len(r), 3)}
                       for k, r in g.items()), key=lambda x: x["pnl_sol"])
    by_trader = group(lambda t: t.get("wallet") or "?")
    by_exit = group(lambda t: _exit(t.get("reason")))
    by_origin = group(_origin)
    gave_back = [t for t in T if (t.get("best_pct") or 0) >= 30 and (t.get("pnl_pct") or 0) <= 0]
    stops = [t for t in T if _exit(t.get("reason")) == "stop de perda"]
    lags = [t["lag_s"] for t in T if t.get("lag_s") is not None]
    skips: dict[str, int] = {}
    for e in pf.feed:
        act = str(e.get("action") or "")
        if act.endswith("não copiou") and act.startswith("REAL") == real and day_of(_ts(e.get("at")) or 0) == day:
            k = re.sub(r"[\d.,%$+−-]+", "#", str(e.get("reason") or "?"))[:60]
            skips[k] = skips.get(k, 0) + 1
    top_skips = sorted(skips.items(), key=lambda kv: -kv[1])[:5]

    sug: list[dict] = []

    def add(area, texto, base, tipo="outro"):
        sug.append({"area": area, "tipo": tipo, "texto": texto, "base": base})
    if n >= 10 and len(wins) / n < 0.45:
        add("trades", f"Acerto do dia {len(wins) / n * 100:.0f}% em {n} trades: aperte a entrada (Configurações → Filtros: acerto mínimo do "
            "trader, pressão de compra mínima, nota mínima) ou copie só os traders que dão lucro para você.", n, tipo="acerto_baixo")
    if n >= 8 and len(stops) / n >= 0.4:
        add("lógica", f"{len(stops)} de {n} trades fecharam no stop de perda: compare em Relatórios → \"E se…\" um stop diferente e veja "
            "em Estratégias fantasma qual regra de saída ganhou.", n, tipo="muitos_stops")
    if len(gave_back) >= 3:
        add("lógica", f"{len(gave_back)} trades chegaram a +30% ou mais e fecharam no zero ou pior: ligue a venda em partes "
            "(Opções novas) ou use um stop móvel mais justo.", len(gave_back), tipo="devolveu_lucro")
    for tr in by_trader:
        if tr["trades"] >= 3 and tr["pnl_sol"] < 0 and tr["acerto"] < 0.34 and tr["nome"] not in ("manual", "?"):
            add("trades", f"O trader {tr['nome'][:4]}…{tr['nome'][-4:]} deu {tr['pnl_sol']:+.4f} SOL em {tr['trades']} cópias com "
                f"{tr['acerto'] * 100:.0f}% de acerto: pause ou bana em Top traders.", tr["trades"], tipo="trader_ruim")
    for og in by_origin:
        if og["trades"] >= 5 and og["pnl_sol"] < 0:
            add("lógica", f"{og['nome']}: {og['pnl_sol']:+.4f} SOL em {og['trades']} trades hoje. Se repetir amanhã, desligue essa origem "
                "até o estudo mostrar uma regra que dá lucro.", og["trades"], tipo="origem_ruim")
    if inv and fees / inv >= 0.05 and n >= 5:
        add("trades", f"As taxas levaram {fees / inv * 100:.1f}% do valor investido hoje ({fees:.4f} SOL): menos trades e valor por cópia "
            "um pouco maior diluem a taxa fixa de rede.", n, tipo="taxas")
    if len(lags) >= 5 and sum(lags) / len(lags) > 5:
        add("código", f"Atraso médio das cópias {sum(lags) / len(lags):.1f} s: um RPC próprio (Configurações → Chaves) reduz o atraso e o "
            "preço pior na entrada.", len(lags), tipo="atraso")
    if top_skips and top_skips[0][1] >= 20:
        add("lógica", f"O filtro \"{top_skips[0][0]}\" barrou {top_skips[0][1]} cópias hoje: confira se ele está protegendo ou só tirando "
            "boas entradas (Relatórios → Por que o bot não copiou).", top_skips[0][1], tipo="filtro")
    pts = points or []
    if real and not pts:
        # a real não tem fotos de 30 min: a curva do dia é o resultado acumulado a cada trade fechado
        cum, pts = 0.0, [{"t": datetime.fromisoformat(day + "T00:00:00+00:00").timestamp(), "resultado": 0.0}]
        for t in sorted(T, key=lambda x: _ts(x.get("closed_at")) or 0):
            cum += t.get("pnl_sol") or 0
            pts.append({"t": _ts(t.get("closed_at")), "resultado": round(cum, 6)})
    if len(pts) >= 2 and pts[0].get("saldo") and pts[-1].get("saldo") is not None:
        ch = (pts[-1]["saldo"] / pts[0]["saldo"] - 1) * 100
        if ch <= -5:
            add("lógica", f"O saldo caiu {ch:.1f}% no dia: ligue \"Pausar depois de perdas seguidas\" (Opções novas) e o limite de perda "
                "do dia das automáticas.", len(pts), tipo="queda_saldo")
    if not sug:
        add("info", "Sem problema claro hoje (ou poucos trades para concluir). As sugestões aparecem com base mínima.", n, tipo="info")
    start = float(pf._c("pump_sim_balance_sol", 5.0))
    end_t = datetime.fromisoformat(day + "T23:59:59+00:00").timestamp()
    equity_end = None if real else round(start + sum(t.get("pnl_sol") or 0 for t in trades if (_ts(t.get("closed_at")) or 0) <= end_t), 6)
    # 0.31.8: cada trade com horário de entrada e saída, e o resultado por hora do dia (pedido do dono)
    tl = []
    for t in sorted(T, key=lambda x: _ts(x.get("closed_at")) or 0):
        o, c = _ts(t.get("opened_at")), _ts(t.get("closed_at"))
        tl.append({"entrada": hhmm(o), "saida": hhmm(c), "t_entrada": o, "t_saida": c, "token": t.get("symbol") or str(t.get("mint") or "")[:6],
                   "mint": t.get("mint"), "origem": _origin(t), "trader": t.get("wallet"), "sol_in": t.get("sol_in"),
                   "pnl_sol": t.get("pnl_sol"), "pnl_pct": t.get("pnl_pct"), "motivo": t.get("reason"), "duracao_s": t.get("hold_s"),
                   "melhor_pct": t.get("best_pct")})
    hours: dict[str, list] = {}
    for x in tl:
        if x["t_saida"]:
            hours.setdefault(hhmm(x["t_saida"], False)[:2] + "h", []).append(x)
    by_hour = [{"hora": h, "trades": len(r), "pnl_sol": round(sum(x.get("pnl_sol") or 0 for x in r), 6),
                "acerto": round(sum(1 for x in r if (x.get("pnl_sol") or 0) > 0) / len(r), 3)} for h, r in sorted(hours.items())]
    tmax = [t for t in T if _exit(t.get("reason")) == "tempo máximo"]
    if len(tmax) >= 2 and sum(t.get("pnl_sol") or 0 for t in tmax) < 0:
        add("lógica", f"{len(tmax)} trades saíram por tempo máximo com {sum(t.get('pnl_sol') or 0 for t in tmax):+.4f} SOL: ficaram parados "
            "por horas e saíram no prejuízo. Ligue \"Sair quando a posição fica parada\" (Opções novas) ou diminua o tempo máximo "
            "em Configurações; compare antes em Estratégias fantasma (\"parado 45 min\" e \"tempo máximo 1 h\").", len(tmax), tipo="tempo_maximo")
    from .reports import autopsy
    aut = autopsy(T)                                   # por que está no vermelho (0.31.11): vai para o banco no daily_report
    for c in aut["causes"]:
        if c["trades"] >= 3:
            add("lógica" if c["causa"] in ("parado", "devolveu", "so_caiu", "entrada_cara") else "trades",
                f"Causa de prejuízo \"{c['nome']}\": {c['trades']} trades, {c['perdido_sol']:+.4f} SOL. {c['correcao']}",
                c["trades"], tipo="causa_" + c["causa"])
    worst_trades = sorted([x for x in tl if (x.get("pnl_sol") or 0) < 0], key=lambda x: x.get("pnl_sol") or 0)[:5]
    best_trades = sorted([x for x in tl if (x.get("pnl_sol") or 0) > 0], key=lambda x: -(x.get("pnl_sol") or 0))[:5]   # 0.31.26
    if len([h for h in by_hour if h["trades"] >= 3]) >= 3:
        worst = min((h for h in by_hour if h["trades"] >= 3), key=lambda h: h["pnl_sol"])
        if worst["pnl_sol"] < 0:
            add("trades", f"O pior horário foi {worst['hora']} ({TZ_NAME}): {worst['pnl_sol']:+.4f} SOL em {worst['trades']} trades. "
                "Se repetir em outros dias, evite operar nesse horário.", worst["trades"], tipo="horario_ruim")
    # 0.31.48: na real, as compras/vendas que NÃO aconteceram no dia (erro ou desistência), com o motivo
    misses = [{"hora": hhmm(_ts(e.get("at"))), "token": e.get("symbol") or str(e.get("mint") or "")[:6], "mint": e.get("mint"),
               "acao": e.get("action"), "motivo": str(e.get("reason") or "")[:200]}
              for e in list(pf.feed) if real and str(e.get("action") or "") in ("REAL falhou", "REAL não copiou")
              and day_of(_ts(e.get("at")) or 0) == day][:60]
    if misses:
        # 0.31.49 (pedido do dono: "sempre ir aprendendo com os erros e salvando relatório"): cada motivo de falha da real
        # vira uma sugestão com a dica; o aprendizado de vários dias mostra os que se repetem
        from .pumpfun import PumpFun
        groups: dict[str, list] = {}
        for m in misses:
            key = next((k for k, _ in PumpFun.MISS_TIPS if k in m["motivo"].lower()), "outro")
            groups.setdefault(key, []).append(m)
        for key, ms in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            tip = next((tp for k, tp in PumpFun.MISS_TIPS if k == key), "Veja o motivo de cada falha na lista abaixo.")
            add("real", f"{len(ms)} compra(s)/venda(s) real(is) não aconteceram por \"{ms[0]['motivo'][:90]}\" "
                f"({', '.join(sorted({m['token'] for m in ms})[:4])}). {tip}", len(ms), tipo="falha_real_" + key.replace(" ", "_"))
        sug[:] = [s for s in sug if s["tipo"] != "info"]
    return {"dia": day, "real": real, "real_misses": misses, "equity_end": equity_end, "trades": n, "trades_list": tl[-MAX_TRADES:], "by_hour": by_hour, "tz": TZ_NAME,
            "worst_trades": worst_trades, "best_trades": best_trades, "loss_causes": aut["causes"], "loss_traders": aut["traders"][:8], "wins": len(wins), "acerto": round(len(wins) / n, 3) if n else None, "pnl_sol": pnl,
            "fees_sol": fees, "invested_sol": round(inv, 6), "by_trader": by_trader[:8], "by_exit": by_exit,
            "by_origin": by_origin, "gave_back": len(gave_back), "stops": len(stops),
            "avg_lag_s": round(sum(lags) / len(lags), 1) if lags else None, "top_skips": [{"motivo": k, "n": v} for k, v in top_skips],
            "suggestions": sug, "points": pts[-MAX_POINTS:], "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def telegram_text(rep: dict) -> str:
    lines = [f"PUMP FUN COPY · relatório de {rep['dia']}",
             f"Resultado: {rep['pnl_sol']:+.4f} SOL · {rep['trades']} trades · acerto "
             + (f"{rep['acerto'] * 100:.0f}%" if rep.get("acerto") is not None else "–")]
    for s in rep.get("suggestions") or []:
        lines.append(f"• [{s['area']}] {s['texto']}")
    return "\n".join(lines)[:3500]


def days_with_trades(pf, before_day: str, limit: int = 60, real: bool = False, all_trades: list[dict] | None = None) -> list[str]:
    """Dias (UTC) com trades fechados (fictícios, ou reais com real=True) antes de `before_day`, os mais recentes primeiro."""
    ds = sorted({day_of(t) for x in (pf.trades(100000) if all_trades is None else all_trades)
                 if bool(x.get("real")) == real and (t := _ts(x.get("closed_at")))}, reverse=True)
    return [d for d in ds if d < before_day][:limit]


TITLES = {"causa_parado": "Prejuízo: ficou parado", "causa_devolveu": "Prejuízo: devolveu o lucro",
          "causa_so_caiu": "Prejuízo: entrou e só caiu", "causa_taxas": "Prejuízo: taxas", "causa_entrada_cara": "Prejuízo: entrada cara",
          "causa_trader_perdeu": "Prejuízo: o trader errou", "causa_rug": "Prejuízo: rug/dev", "tempo_maximo": "Perdas por tempo máximo", "horario_ruim": "Horário ruim", "acerto_baixo": "Acerto baixo", "muitos_stops": "Muitos stops de perda", "devolveu_lucro": "Lucro devolvido",
          "trader_ruim": "Trader que dá prejuízo", "origem_ruim": "Origem no prejuízo", "taxas": "Taxas altas",
          "atraso": "Atraso alto", "filtro": "Filtro barrando demais", "queda_saldo": "Saldo caindo no dia"}


def study(reports: list[dict]) -> dict:
    """Aprendizado de vários dias (0.31.6): o que se repete, o que dá lucro de forma consistente e o que não dá."""
    R = sorted([r for r in reports if r.get("dia")], key=lambda r: r["dia"])
    n = len(R)
    pos = [r for r in R if (r.get("pnl_sol") or 0) > 0]
    rec: dict[str, dict] = {}
    for r in R:
        menu_sug = [x for m in r.get("modules") or [] for x in m.get("sugestoes") or []]     # 0.31.9: sugestões de cada menu
        for s in (r.get("suggestions") or []) + menu_sug:
            t = s.get("tipo") or "outro"
            if t in ("info", "outro"):
                continue
            x = rec.setdefault(t, {"tipo": t, "titulo": TITLES.get(t) or s.get("titulo") or t, "dias": 0, "ultimo": None, "exemplo": None})
            x["dias"] += 1
            x["ultimo"], x["exemplo"] = r["dia"], s.get("texto")
    def across(key):
        g: dict[str, dict] = {}
        for r in R:
            for x in r.get(key) or []:
                y = g.setdefault(x["nome"], {"nome": x["nome"], "dias": 0, "dias_positivos": 0, "trades": 0, "pnl_sol": 0.0})
                y["dias"] += 1
                y["dias_positivos"] += 1 if (x.get("pnl_sol") or 0) > 0 else 0
                y["trades"] += x.get("trades") or 0
                y["pnl_sol"] = round(y["pnl_sol"] + (x.get("pnl_sol") or 0), 6)
        return sorted(g.values(), key=lambda y: y["pnl_sol"])
    origins, exits, traders = across("by_origin"), across("by_exit"), across("by_trader")
    sug: list[dict] = []
    for x in sorted(rec.values(), key=lambda x: -x["dias"]):
        if x["dias"] >= 2:
            sug.append({"area": "repetido", "texto": f"\"{x['titulo']}\" apareceu em {x['dias']} de {n} dias: é um problema que se repete, "
                        "não um dia ruim. Priorize essa correção.", "base": x["dias"]})
    for o in origins:
        if o["dias"] >= 3 and o["pnl_sol"] < 0 and o["dias_positivos"] <= o["dias"] / 3:
            sug.append({"area": "lógica", "texto": f"{o['nome']}: {o['pnl_sol']:+.4f} SOL somando {o['dias']} dias e só {o['dias_positivos']} "
                        "positivos: desligue essa origem até mudar a regra.", "base": o["trades"]})
        if o["dias"] >= 3 and o["pnl_sol"] > 0 and o["dias_positivos"] >= o["dias"] * 0.6:
            sug.append({"area": "trades", "texto": f"{o['nome']} é consistente: {o['pnl_sol']:+.4f} SOL e {o['dias_positivos']} de {o['dias']} dias "
                        "positivos. É a melhor candidata a ganhar mais valor por trade.", "base": o["trades"]})
    for t in traders:
        if t["dias"] >= 2 and t["pnl_sol"] < 0 and t["dias_positivos"] == 0 and t["nome"] not in ("manual", "?"):
            sug.append({"area": "trades", "texto": f"Trader {t['nome'][:4]}…{t['nome'][-4:]} deu prejuízo em todos os {t['dias']} dias "
                        f"({t['pnl_sol']:+.4f} SOL): bana em Top traders.", "base": t["trades"]})
    for e in exits:
        if e["trades"] >= 15 and e["pnl_sol"] < 0 and e["nome"] in ("stop de perda", "tempo máximo"):
            sug.append({"area": "lógica", "texto": f"Saída \"{e['nome']}\" somou {e['pnl_sol']:+.4f} SOL em {e['trades']} trades nos dias "
                        "estudados: revise essa regra em Relatórios → \"E se…\" e nas Estratégias fantasma.", "base": e["trades"]})
    if n >= 5 and len(pos) / n < 0.4:
        sug.append({"area": "lógica", "texto": f"Só {len(pos)} de {n} dias fecharam no lucro: a estratégia atual não está pagando. Reduza o "
                    "valor por trade e teste mudanças uma de cada vez no simulado.", "base": n})
    if not sug:
        sug.append({"area": "info", "texto": "Ainda sem padrão que se repita: o estudo melhora a cada dia guardado.", "base": n})
    total = round(sum(r.get("pnl_sol") or 0 for r in R), 6)
    return {"days": n, "positive_days": len(pos), "pnl_sol": total,
            "best": max(R, key=lambda r: r.get("pnl_sol") or 0)["dia"] if R else None,
            "worst": min(R, key=lambda r: r.get("pnl_sol") or 0)["dia"] if R else None,
            "series": [{"dia": r["dia"], "pnl_sol": r.get("pnl_sol") or 0, "equity_end": r.get("equity_end"),
                        "trades": r.get("trades"), "acerto": r.get("acerto")} for r in R],
            "recurring": sorted(rec.values(), key=lambda x: -x["dias"]), "origins": origins, "exits": exits,
            "traders": traders[:10], "suggestions": sug}


def _br(d: str) -> str:
    return "/".join(reversed(str(d).split("-")))


def blocks(rep: dict, st: dict | None, version: str) -> list[tuple[str, str]]:
    """Conteúdo do PDF do relatório (0.31.7): o dia, as sugestões e o aprendizado de vários dias."""
    B = [("title", f"PUMP FUN COPY - relatório de {_br(rep['dia'])}"),
         ("small", f"Versão do sistema: {version} · gerado em {rep.get('generated_at')} · carteira {'REAL' if rep.get('real') else 'fictícia'}"
                   + (" · dia fechado" if rep.get("closed") else " · dia em andamento")
                   + (" · refeito a partir dos trades" if rep.get("backfilled") else "")),
         ("h", "Resumo do dia"),
         ("p", f"Resultado {rep.get('pnl_sol', 0):+.4f} SOL em {rep.get('trades', 0)} trades fechados; acerto "
               + (f"{rep['acerto'] * 100:.0f}%" if rep.get("acerto") is not None else "-")
               + f"; taxas {rep.get('fees_sol', 0):.4f} SOL; investido {rep.get('invested_sol', 0):.4f} SOL"
               + (f"; saldo no fim do dia {rep['equity_end']:.4f} SOL" if rep.get("equity_end") is not None else "")
               + f"; {rep.get('gave_back', 0)} trades devolveram lucro; {rep.get('stops', 0)} stops de perda"
               + (f"; atraso médio {rep['avg_lag_s']} s" if rep.get("avg_lag_s") is not None else "") + ".")]
    pts = rep.get("points") or []
    if len(pts) >= 2:
        B.append(("p", "Saldo ao longo do dia: " + " · ".join(f"{datetime.fromtimestamp(p['t'], timezone.utc).strftime('%H:%M')} "
                                                              f"{p.get('saldo', 0):.4f}" for p in pts[:: max(1, len(pts) // 12)])))
    if rep.get("loss_causes"):
        B.append(("h", "Por que ficou no vermelho (causas)"))
        B += [("p", f"{c['nome']}: {c['trades']} trades, {c['perdido_sol']:+.4f} SOL. Correção: {c['correcao']}") for c in rep["loss_causes"]]
        B += [("p", f"Trader {str(x['wallet'])[:4]}...{str(x['wallet'])[-4:]}: {x['trades']} trades, {x['pnl_sol']:+.4f} SOL, causa {x['causa_nome']}. "
                    f"{x['recomendacao']}") for x in rep.get("loss_traders") or []]
    if rep.get("worst_trades"):
        B.append(("h", "Maiores perdas do dia (onde o dinheiro foi perdido)"))
        B += [("mono", f"{x['entrada']}->{x['saida']}  {str(x['token'])[:12]:<12} {(x.get('pnl_sol') or 0):+.4f} SOL "
                       f"{(x.get('pnl_pct') or 0):+.1f}%  {str(x.get('origem'))[:22]:<22} {str(x.get('motivo') or '')[:40]}")
              for x in rep["worst_trades"]]
    if rep.get("best_trades"):
        B.append(("h", "Maiores ganhos do dia (onde o dinheiro foi ganho)"))
        B += [("mono", f"{x['entrada']}->{x['saida']}  {str(x['token'])[:12]:<12} {(x.get('pnl_sol') or 0):+.4f} SOL "
                       f"{(x.get('pnl_pct') or 0):+.1f}%  {str(x.get('origem'))[:22]:<22} {str(x.get('motivo') or '')[:40]}")
              for x in rep["best_trades"]]
    B.append(("h", "O que melhorar (dia)"))
    B += [("p", f"[{s['area']}] {s['texto']} (base: {s.get('base')})") for s in rep.get("suggestions") or []]
    for key, title in (("by_origin", "Por origem"), ("by_exit", "Por motivo de saída"), ("by_trader", "Por trader")):
        rows = rep.get(key) or []
        if rows:
            B.append(("h", title))
            B += [("mono", f"{str(x['nome'])[:44]:<44} {x['trades']:>4} trades  acerto {x['acerto'] * 100:>3.0f}%  {x['pnl_sol']:+.4f} SOL")
                  for x in rows]
    if rep.get("modules"):
        B.append(("h", "Relatório de cada menu"))
        for m in rep["modules"]:
            B.append(("p", f"{m['menu']}: " + " · ".join(m.get("linhas") or [])))
            B += [("p", f"    -> [{s['area']}] {s['texto']} (base: {s.get('base')})") for s in m.get("sugestoes") or []]
    if rep.get("by_hour"):
        B.append(("h", f"Por hora ({rep.get('tz') or 'UTC'})"))
        B += [("mono", f"{h['hora']:>4}  {h['trades']:>4} trades  acerto {h['acerto'] * 100:>3.0f}%  {h['pnl_sol']:+.4f} SOL") for h in rep["by_hour"]]
    if rep.get("trades_list"):
        B.append(("h", f"Trades do dia com horário ({rep.get('tz') or 'UTC'})"))
        B.append(("mono", "entrada   saída     token        resultado        motivo"))
        for x in rep["trades_list"]:
            pct = f"{x['pnl_pct']:+.1f}%" if x.get("pnl_pct") is not None else ""
            dur = f" ({int(x['duracao_s'] // 60)}m{int(x['duracao_s'] % 60):02d}s)" if x.get("duracao_s") is not None else ""
            B.append(("mono", f"{x['entrada']}  {x['saida']}  {str(x['token'])[:12]:<12} {(x.get('pnl_sol') or 0):+.4f} {pct:<8} "
                              f"{str(x.get('motivo') or '')[:44]}{dur}"))
    if rep.get("top_skips"):
        B.append(("h", "Por que o robô não copiou (mais frequentes)"))
        B += [("mono", f"{x['n']:>5}x  {x['motivo']}") for x in rep["top_skips"]]
    if st:
        B.append(("h", f"Aprendizado de {st.get('days', 0)} dias"))
        B.append(("p", f"Resultado somado {st.get('pnl_sol', 0):+.4f} SOL; {st.get('positive_days', 0)} de {st.get('days', 0)} dias no lucro; "
                       f"melhor dia {_br(st.get('best') or '-')}; pior dia {_br(st.get('worst') or '-')}."))
        B += [("p", f"[{s['area']}] {s['texto']} (base: {s.get('base')})") for s in st.get("suggestions") or []]
        if st.get("series"):
            B.append(("h", "Dia a dia"))
            B += [("mono", f"{_br(d['dia'])}  {d.get('pnl_sol') or 0:+.4f} SOL  {d.get('trades') or 0:>4} trades  "
                           f"acerto {((d.get('acerto') or 0) * 100):>3.0f}%") for d in st["series"]]
    return B


def ai_text(rep: dict, st: dict | None, version: str) -> str:
    """O mesmo relatório em texto, com as instruções para a IA que vai revisar e corrigir (0.31.7)."""
    lines = [f"# Relatório PUMP FUN COPY - {_br(rep['dia'])} (sistema {version})", ""]
    lines += [("## " + t) if s in ("h", "title") else t for s, t in blocks(rep, st, version)[1:]]
    lines += ["", "## Instruções para a IA que vai revisar",
              "Repositório: github.com/Bruxo95/PUMP.FUN_Bruxo_Bode (leia CLAUDE.md antes de mexer).",
              "1. Diga as 3 causas principais do resultado acima, com os números do relatório.",
              "2. Proponha mudanças no código ou nas configurações (arquivo e função), uma por problema, da mais importante para a menos.",
              "3. Implemente seguindo o CLAUDE.md (testes sem internet, versão nova, novidades.json, inventário, pull antes do push).",
              "4. Na mesma entrega, crie app/relatorios_ia/AAAA-MM-DD-versao.md no formato descrito em app/changes.py, com a "
              "PROJEÇÃO de ganho em SOL por dia depois da mudança e a conta que levou a ela (ex.: E se…, Estratégias fantasma).",
              "5. Não ligue a execução real e não faça transação real."]
    return "\n".join(lines)
