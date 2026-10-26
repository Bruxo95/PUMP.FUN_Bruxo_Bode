"""Relatório de cada menu (0.31.9, pedido do dono em 2026-10-26: "cada menu gera um relatório diário e diz o que pode ser
alterado no código e na lógica para ganhar mais; tudo junto em Relatórios e no aprendizado").

Cada seção = {"menu", "linhas": [texto], "sugestoes": [{"area", "tipo", "texto", "base"}]}. Entra no relatório do dia
(PDF, texto para IA, Visão geral) e as sugestões contam no "Aprendizado dos dias" (o que se repete). Dados ao vivo
(radar, explorar, base, maiores traders) só existem para o dia de hoje; dias passados usam só os trades.
Cada menu é calculado à parte: se um falhar, os outros saem mesmo assim.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from .daily import _ts, day_of


def _sug(menu, area, chave, texto, base):
    return {"area": area, "tipo": f"menu:{menu}:{chave}", "titulo": f"{menu}: {chave.replace('_', ' ')}", "texto": texto, "base": base}


def _today_trades(pf, day):
    return [t for t in pf.trades(100000) if not t.get("real") and day_of(_ts(t.get("closed_at")) or 0) == day]


def _sum(rows):
    n = len(rows)
    pnl = round(sum(t.get("pnl_sol") or 0 for t in rows), 6)
    wins = sum(1 for t in rows if (t.get("pnl_sol") or 0) > 0)
    return n, pnl, (wins / n if n else None)


def build(hub, pf, day: str, live: bool) -> list[dict]:
    T = _today_trades(pf, day)
    out = []
    for fn in (_copies, _study, _auto("explorar", "Explorar (compra automática)"), _auto("base", "Base da pump.fun (compra automática)"),
               _auto("elite", "Maiores traders (compra automática)"), _manual, _ghosts, _whatif, _options, _learning,
               _elite, _explore, _base, _radar, _blacklist):
        try:
            sec = fn(hub, pf, day, T, live)
            if sec:
                out.append(sec)
        except Exception as e:                      # um menu com problema não derruba o relatório dos outros
            out.append({"menu": getattr(fn, "__name__", "menu").strip("_"), "linhas": [f"não calculado: {type(e).__name__}"], "sugestoes": []})
    return out


# ------------------------------------------------------------------ menus que dependem dos trades (todo dia)
def _copies(hub, pf, day, T, live):
    C = [t for t in T if not t.get("origem") and not t.get("manual") and t.get("wallet") != "manual"]
    n, pnl, wr = _sum(C)
    sec = {"menu": "Top traders (cópias)", "linhas": [f"{n} cópias fechadas · {pnl:+.4f} SOL · acerto " + (f"{wr * 100:.0f}%" if wr is not None else "-")],
           "sugestoes": []}
    if n >= 8 and pnl < 0:
        sec["sugestoes"].append(_sug("Top traders", "lógica", "copias_no_prejuizo", f"As cópias deram {pnl:+.4f} SOL em {n} trades: suba o acerto "
                                     "mínimo do trader e ligue a nota mínima, ou copie só os traders que dão lucro (Relatórios → por trader).", n))
    return sec


def _study(hub, pf, day, T, live):
    S = set(getattr(pf, "study", []) or [])
    if not S:
        return None
    rows = [t for t in T if t.get("wallet") in S]
    n, pnl, wr = _sum(rows)
    sec = {"menu": "Carteiras em estudo", "linhas": [f"{len(S)} carteiras em estudo · {n} cópias delas fechadas hoje · {pnl:+.4f} SOL"], "sugestoes": []}
    skips = sum(1 for e in pf.feed if e.get("wallet") in S and str(e.get("action") or "").endswith("não copiou")
                and day_of(_ts(e.get("at")) or 0) == day)
    if skips:
        sec["linhas"].append(f"{skips} compras dessas carteiras não foram copiadas (filtros)")
    if skips >= 10 and n == 0:
        sec["sugestoes"].append(_sug("Carteiras em estudo", "lógica", "filtros_barram", f"{skips} compras das carteiras em estudo foram "
                                     "barradas e nenhuma copiada: veja o motivo em \"Seu resultado copiando\" e afrouxe o filtro que mais barra.", skips))
    return sec


def _auto(origem, menu):
    def fn(hub, pf, day, T, live):
        rows = [t for t in T if t.get("origem") == origem]
        if not rows:
            return None
        n, pnl, wr = _sum(rows)
        stops = sum(1 for t in rows if str(t.get("reason") or "").startswith("stop de perda"))
        sec = {"menu": menu, "linhas": [f"{n} operações · {pnl:+.4f} SOL · acerto " + (f"{wr * 100:.0f}%" if wr is not None else "-")
                                        + f" · {stops} stops de perda"], "sugestoes": []}
        if n >= 5 and pnl < 0:
            sec["sugestoes"].append(_sug(menu, "lógica", "automatica_no_prejuizo", f"{menu}: {pnl:+.4f} SOL em {n} operações hoje. Aperte a regra "
                                         "de entrada desse menu (mais traders/filtros) ou deixe só observando até o estudo mostrar lucro.", n))
        return sec
    fn.__name__ = f"_auto_{origem}"
    return fn


def _manual(hub, pf, day, T, live):
    rows = [t for t in T if (t.get("manual") or t.get("wallet") == "manual") and not t.get("origem")]
    if not rows:
        return None
    n, pnl, wr = _sum(rows)
    return {"menu": "Botão Comprar (manual)", "linhas": [f"{n} compras fechadas · {pnl:+.4f} SOL"], "sugestoes": []}


def _whatif(hub, pf, day, T, live):
    from .reports import whatif
    w = whatif(T)
    if not w.get("trades"):
        return None
    best = w["rows"][0]
    sec = {"menu": "Relatórios (E se…)", "linhas": [f"real {w['real_sol']:+.4f} SOL · melhor regra estimada: {best['regra']} {best['pnl_sol']:+.4f} SOL"],
           "sugestoes": []}
    if w["trades"] >= 10 and best["diff_sol"] > 0.02:
        sec["sugestoes"].append(_sug("Relatórios", "lógica", "regra_de_saida", f"Com \"{best['regra']}\" o dia teria dado {best['diff_sol']:+.4f} SOL a mais "
                                     f"(estimativa com {w['trades']} trades). Se repetir, mude essa regra em Configurações.", w["trades"]))
    return sec


def _ghosts(hub, pf, day, T, live):
    g = getattr(pf, "ghosts", None)
    if g is None or not g.stats:
        return None
    snap = g.snapshot(pf.trades(100000))
    best = next((v for v in snap["variants"] if v["id"] == snap.get("best")), None)
    y = snap["yours"]
    sec = {"menu": "Estratégias fantasma", "linhas": [f"suas regras {y['pnl_sol']:+.4f} SOL em {y['trades']} trades desde {snap.get('since')}"
                                                      + (f" · melhor variante: {best['nome']} {best['pnl_sol']:+.4f} SOL" if best else "")],
           "sugestoes": []}
    if best and best["trades"] >= 15 and best["pnl_sol"] - y["pnl_sol"] > 0.05:
        sec["sugestoes"].append(_sug("Estratégias fantasma", "lógica", "variante_melhor", f"A regra \"{best['nome']}\" ganhou "
                                     f"{best['pnl_sol'] - y['pnl_sol']:+.4f} SOL a mais que as suas regras ({best['trades']} trades): copie essa regra de saída.",
                                     best["trades"]))
    return sec


def _options(hub, pf, day, T, live):
    c = pf.cfg
    keys = [("pump_exit_dev_sell", "sair quando o dev vende"), ("pump_exit_migrate", "sair quando gradua"),
            ("pump_exit_pressure_on", "sair com pressão virando"), ("pump_tp1_on", "venda em partes"),
            ("pump_score_min_on", "nota mínima"), ("pump_streak_on", "pausa por perdas seguidas"), ("pump_blacklist_on", "lista negra")]
    on = [n for k, n in keys if getattr(c, k, False)]
    off = [n for k, n in keys if not getattr(c, k, False)]
    sec = {"menu": "Opções novas de cópia", "linhas": ["ligadas: " + (", ".join(on) or "nenhuma"), "desligadas: " + (", ".join(off) or "nenhuma")],
           "sugestoes": []}
    gave = sum(1 for t in T if (t.get("best_pct") or 0) >= 30 and (t.get("pnl_pct") or 0) <= 0)
    if gave >= 3 and not getattr(c, "pump_tp1_on", False):
        sec["sugestoes"].append(_sug("Opções novas", "lógica", "ligar_venda_em_partes", f"{gave} trades chegaram a +30% e fecharam no zero ou pior com a "
                                     "venda em partes desligada: ligue \"Venda em partes\".", gave))
    if len(T) >= 10 and not getattr(c, "pump_blacklist_on", False):
        sec["sugestoes"].append(_sug("Opções novas", "lógica", "ligar_lista_negra", "A lista negra está desligada: ligue para não copiar criadores de rug e de bundle.", len(T)))
    return sec


def _learning(hub, pf, day, T, live):
    if not live:
        return None
    from .learning import build as lb
    r = lb(pf, False, [])
    sug = r.get("suggestions") or []
    if not sug:
        return None
    return {"menu": "Aprendizado diário", "linhas": [s["text"] for s in sug[:2]],
            "sugestoes": [_sug("Aprendizado diário", "trades", s.get("kind") or "sugestao", s["text"], s.get("base")) for s in sug[:4]]}


# ------------------------------------------------------------------ menus com dados ao vivo (só hoje)
def _elite(hub, pf, day, T, live):
    el = getattr(hub, "elite", None)
    if not live or el is None or not el.names:
        return None
    st = el.study()
    today = [s for s in el.signals.values() if day_of(s["t"]) == day]
    sec = {"menu": "Maiores traders", "linhas": [f"{len(el.names)} seguidos · {len(el.recommended())} com 80%+ · {len(today)} sinais hoje · "
                                                 f"{st['signals']} sinais estudados"], "sugestoes": []}
    for s in el.suggestions(st)[:3]:
        if s["tipo"] != "info":
            sec["sugestoes"].append(_sug("Maiores traders", s["tipo"] if s["tipo"] in ("código", "lógica", "trades") else "lógica",
                                         s["texto"][:40].replace(" ", "_"), s["texto"], s.get("base")))
    return sec


def _explore(hub, pf, day, T, live):
    ex = getattr(hub, "explore", None)
    if not live or ex is None:
        return None
    L = ex.learned()
    lines = [f"listas: {', '.join(f'{k} {len(v)}' for k, v in ex.lists.items())}" + (f" · erro: {ex.error}" if ex.error else "")]
    lines += [f"quase graduando com curva {x['faixa']}: {x['grad_pct']:.0f}% graduaram ({x['n']})" for x in L]
    sec = {"menu": "Explorar", "linhas": lines, "sugestoes": []}
    good = [x for x in L if x["n"] >= 20 and x["grad_pct"] >= 60]
    for x in good:
        sec["sugestoes"].append(_sug("Explorar", "lógica", "curva_" + x["faixa"].split()[0], f"Curva {x['faixa']}: {x['grad_pct']:.0f}% graduaram ({x['n']} tokens). "
                                     "Ajuste a faixa de curva da entrada automática do Explorar para essa faixa.", x["n"]))
    return sec


def _base(hub, pf, day, T, live):
    lab = getattr(hub, "lab", None)
    if not live or lab is None:
        return None
    s = lab.snapshot()
    d, L = s["day"], s["day"]["labels"]
    fin = d["finished"] or 0
    lines = [f"{fin} tokens fechados em 24 h · {d['up']} subiram · {L.get('bundle', 0)} bundles · {L.get('despencou', 0)} despencaram"]
    ls = s.get("lessons") or {}
    sec = {"menu": "Base da pump.fun", "linhas": lines, "sugestoes": []}
    for b in (ls.get("best") or [])[:3]:
        sec["linhas"].append(f"sinal forte: {b['sinal']} → {b['up_pct']:.0f}% subiram ({b['n']})")
        sec["sugestoes"].append(_sug("Base da pump.fun", "lógica", "sinal_" + str(b["sinal"])[:30].replace(" ", "_"),
                                     f"\"{b['sinal']}\" levou {b['up_pct']:.0f}% dos tokens a subir ({b['n']} tokens, média {ls.get('base_up_pct')}%): "
                                     "use esse sinal na nota da entrada / na compra automática da Base.", b["n"]))
    return sec


def _radar(hub, pf, day, T, live):
    if not live:
        return None
    hot = sum(1 for e in pf.events if "hot callout" in str(e.get("msg") or "").lower() and day_of(_ts(e.get("at")) or 0) == day)
    on = bool(getattr(pf.cfg, "pump_radar_enabled", False))
    return {"menu": "Radar de KOLs", "linhas": [("ligado" if on else "desligado") + f" · {hot} HOT callouts hoje · "
                                                 f"{len(getattr(pf, 'study', []) or [])} carteiras na lista"], "sugestoes": []}


def _blacklist(hub, pf, day, T, live):
    bl = hub.market.blacklist
    novos = sum(1 for v in bl.values() if day_of(_ts(v.get("criado_em")) or 0) == day)
    return {"menu": "Lista negra", "linhas": [f"{len(bl)} endereços · {novos} entraram hoje · bloqueio "
                                               + ("ligado" if getattr(pf.cfg, "pump_blacklist_on", False) else "desligado")], "sugestoes": []}
