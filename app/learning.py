"""Aprendizado diário (0.9.9): o que os top traders fizeram, o que as suas cópias fizeram e o que dá para ajustar.

Primeira etapa, só com o que o sistema já tem (pedido do dono em 2026-10-25): trades fechados do usuário (gravados
no banco), o que o monitor vê dos traders em tempo real (memória — recomeça quando o servidor reinicia) e o saldo das
carteiras dos traders. Não é IA: são contas sobre os dados, e cada conclusão mostra em quantos casos se baseia.
Nada muda sozinho: sugestões vêm com um botão que o usuário confirma. Guardar o histórico dia a dia (para aprender
por semanas) precisa de uma tabela nova no Supabase — próxima etapa, depende de autorização para aplicar.
"""
from __future__ import annotations

import statistics
import time
from datetime import datetime, timedelta, timezone

from .reports import build as report

MIN_TRADER = 5            # trades fechados copiando o trader antes de sugerir pausar
MIN_SAMPLE = 20           # tokens fechados pelos traders antes de sugerir limite de market cap


def _med(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def _pct(xs, q):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    return xs[min(len(xs) - 1, int(q * (len(xs) - 1) + 0.5))]


def traders_today(pf, hours: float = 24.0) -> dict:
    """Comportamento das carteiras que o usuário segue + top do ranking, visto pelo monitor nas últimas horas."""
    now = time.time()
    watch = list(dict.fromkeys(list(pf.followed) + [r["wallet"] for r in (pf.leaderboard or [])[:30]]))
    usd = getattr(pf.market, "wallet_usd", {}) or {}
    rows, closed_all, trades_by_hour = [], [], [0] * 24
    for w in watch:
        st = pf.wallets.get(w) or {}
        closed = [c for c in st.get("closed") or [] if now - c["t"] <= hours * 3600]
        for t in st.get("trades") or []:
            if now - t <= hours * 3600:
                trades_by_hour[datetime.fromtimestamp(t, timezone.utc).hour] += 1
        closed_all += closed
        if not closed:
            continue
        wins = [c for c in closed if c["pnl"] > 0]
        rows.append({"wallet": w, "closed": len(closed), "wins": len(wins), "win_rate": len(wins) / len(closed),
                     "pnl_sol": round(sum(c["pnl"] for c in closed), 4), "hold_med_s": _med([c["hold"] for c in closed]),
                     "mcap_in_med": _med([c.get("mcap_in") for c in closed]), "followed": w in pf.followed,
                     "wallet_usd": (usd.get(w) or {}).get("usd")})
    rows.sort(key=lambda r: -r["pnl_sol"])
    win = [c for c in closed_all if c["pnl"] > 0]
    lose = [c for c in closed_all if c["pnl"] <= 0]
    rich = sorted(({"wallet": w, "usd": (usd.get(w) or {}).get("usd")} for w in watch if (usd.get(w) or {}).get("usd")),
                  key=lambda r: -r["usd"])[:10]
    return {"hours": hours, "watched": len(watch), "tokens_closed": len(closed_all), "traders": rows,
            "winners": {"n": len(win), "hold_med_s": _med([c["hold"] for c in win]),
                        "mcap_in_med": _med([c.get("mcap_in") for c in win]),
                        "mcap_in_p75": _pct([c.get("mcap_in") for c in win], 0.75)},
            "losers": {"n": len(lose), "hold_med_s": _med([c["hold"] for c in lose]),
                       "mcap_in_med": _med([c.get("mcap_in") for c in lose])},
            "trades_by_hour_utc": trades_by_hour, "richest": rich}


def suggestions(pf, mine7: dict, tt: dict) -> list[dict]:
    """Regras simples e explicáveis. Cada uma diz a base (quantos casos) e, quando dá, uma ação para confirmar."""
    out, c = [], pf.cfg
    paused = set(pf.paused())
    for t in mine7["traders"]:
        if t["trades"] >= MIN_TRADER and t["pnl_sol"] < 0 and t["wallet"] not in paused:
            out.append({"kind": "pausar", "text": f"Copiando {t['wallet'][:4]}…{t['wallet'][-4:]} você perdeu "
                        f"{-t['pnl_sol']:.4f} SOL em {t['trades']} trades nos últimos 7 dias (acerto "
                        f"{(t['win_rate'] or 0) * 100:.0f}%). Pausar por 24 h?", "base": t["trades"],
                        "action": {"type": "pause", "wallet": t["wallet"], "hours": 24}})
    w, l = tt["winners"], tt["losers"]
    cap = getattr(c, "pump_max_mcap_sol", 0) or 0
    if (w["n"] + l["n"] >= MIN_SAMPLE and w["mcap_in_p75"] and l["mcap_in_med"]
            and l["mcap_in_med"] > w["mcap_in_p75"] and (not cap or cap > w["mcap_in_p75"] * 1.2)):
        val = round(w["mcap_in_p75"])
        out.append({"kind": "mcap", "text": f"Nas últimas 24 h os top traders lucraram entrando com market cap até ~{val} SOL "
                    f"(75% dos acertos) e perderam entrando em média com {l['mcap_in_med']:.0f} SOL. Limitar a cópia a "
                    f"{val} SOL de market cap?", "base": w["n"] + l["n"],
                    "action": {"type": "settings", "values": {"pump_max_mcap_sol": val}}})
    delay = float(getattr(c, "pump_copy_delay_s", 0) or 0)
    if w["n"] >= MIN_SAMPLE // 2 and w["hold_med_s"] and delay and delay > w["hold_med_s"] / 2:
        out.append({"kind": "espera", "text": f"Os acertos dos top traders duraram em média {w['hold_med_s']:.0f} s, e a sua "
                    f"espera antes de copiar é de {delay:.0f} s: você chega quando boa parte do movimento já passou. "
                    f"Reduzir a espera para {max(0, int(w['hold_med_s'] / 4))} s?", "base": w["n"],
                    "action": {"type": "settings", "values": {"pump_copy_delay_s": max(0, int(w["hold_med_s"] / 4))}}})
    tot = mine7["total"]
    gross = (tot["pnl_sol"] or 0) + (tot["fees_sol"] or 0)
    if tot["trades"] >= 10 and tot["fees_sol"] and gross > 0 and tot["fees_sol"] > gross * 0.5:
        out.append({"kind": "taxas", "text": f"Nos últimos 7 dias as taxas ({tot['fees_sol']:.4f} SOL) levaram mais da metade "
                    f"do resultado antes das taxas ({gross:.4f} SOL). Copiar menos trades e mais selecionados (filtros mais "
                    f"rígidos) tende a ajudar mais do que aumentar o valor.", "base": tot["trades"]})
    stops = next((e for e in mine7["exits"] if e["reason"] == "Stop de perda"), None)
    if stops and tot["trades"] >= 10 and stops["trades"] >= tot["trades"] * 0.4:
        out.append({"kind": "stop", "text": f"{stops['trades']} de {tot['trades']} posições ({stops['trades'] / tot['trades'] * 100:.0f}%) "
                    f"fecharam no stop de perda nos últimos 7 dias, somando {stops['pnl_sol']:.4f} SOL. Vale olhar se os "
                    f"traders copiados seguram a queda e se recuperam — se sim, o stop pode estar apertado.", "base": stops["trades"]})
    return out


def snapshot(r: dict) -> dict:
    """O que fica guardado do dia (tabela learning_daily): compacto, sem dados de outros usuários."""
    tt = r["traders_today"]
    return {"summary": r["summary"], "mine_24h": r["mine_24h"], "real": r["real"],
            "winners": tt["winners"], "losers": tt["losers"], "tokens_closed": tt["tokens_closed"],
            "traders": [{k: x.get(k) for k in ("wallet", "closed", "wins", "pnl_sol", "hold_med_s", "mcap_in_med", "followed")}
                        for x in tt["traders"][:40]],
            "suggestions": [{"kind": s["kind"], "text": s["text"], "base": s["base"]} for s in r["suggestions"]]}


def weekly(history: list[dict], followed) -> dict:
    """Junta os dias guardados: quem lucrou em vários dias (consistência vale mais do que um dia bom)."""
    days = sorted({h["dia"] for h in history})
    per: dict[str, dict] = {}
    for h in history:
        for x in (h.get("data") or {}).get("traders") or []:
            w = x.get("wallet")
            if not w:
                continue
            a = per.setdefault(w, {"wallet": w, "days_seen": 0, "days_positive": 0, "pnl_sol": 0.0, "tokens": 0})
            a["days_seen"] += 1
            a["days_positive"] += 1 if (x.get("pnl_sol") or 0) > 0 else 0
            a["pnl_sol"] = round(a["pnl_sol"] + (x.get("pnl_sol") or 0), 4)
            a["tokens"] += x.get("closed") or 0
    fol = set(followed)
    rows = sorted(per.values(), key=lambda a: (-a["days_positive"], -a["pnl_sol"]))
    for a in rows:
        a["followed"] = a["wallet"] in fol
    mine = [{"dia": h["dia"], **((h.get("data") or {}).get("mine_24h") or {})} for h in sorted(history, key=lambda h: h["dia"], reverse=True)]
    return {"days": len(days), "first": days[0] if days else None, "traders": rows[:30], "mine_by_day": mine[:30]}


def build(pf, real: bool = False, history: list[dict] | None = None) -> dict:
    trades, feed = pf.trades(100000), list(pf.feed)
    mine1 = report(trades, feed, 1, real, pf.followed, list(pf.paused()))
    mine7 = report(trades, feed, 7, real, pf.followed, list(pf.paused()))
    tt = traders_today(pf)
    sug = suggestions(pf, mine7, tt)
    wk = weekly(history or [], pf.followed)
    for a in wk["traders"]:
        # consistente: lucrou em pelo menos 3 dias e em 70% dos dias em que apareceu, e você ainda não copia
        if (wk["days"] >= 3 and a["days_positive"] >= 3 and a["days_positive"] >= 0.7 * a["days_seen"]
                and not a["followed"] and a["wallet"] not in pf.banned):
            sug.append({"kind": "consistente", "text": f"{a['wallet'][:4]}…{a['wallet'][-4:]} lucrou em {a['days_positive']} "
                        f"de {a['days_seen']} dias guardados ({a['pnl_sol']:+.3f} SOL em {a['tokens']} tokens). Adicionar à "
                        f"cópia como carteira manual?", "base": a["days_seen"],
                        "action": {"type": "add", "wallet": a["wallet"]}})
    best = tt["traders"][0] if tt["traders"] else None
    summary = []
    if tt["tokens_closed"]:
        w = tt["winners"]
        summary.append(f"Nas últimas 24 h o monitor viu {tt['tokens_closed']} tokens fechados por {len(tt['traders'])} "
                       f"das {tt['watched']} carteiras acompanhadas; {w['n']} com lucro.")
        if w["hold_med_s"]:
            summary.append(f"Quando acertaram, seguraram em média {w['hold_med_s'] / 60:.1f} min"
                           + (f" e entraram com market cap por volta de {w['mcap_in_med']:.0f} SOL." if w["mcap_in_med"] else "."))
        if best and best["pnl_sol"] > 0:
            summary.append(f"Melhor do dia: {best['wallet'][:4]}…{best['wallet'][-4:]} com {best['pnl_sol']:+.3f} SOL em "
                           f"{best['closed']} tokens ({best['win_rate'] * 100:.0f}% de acerto).")
    else:
        summary.append("O monitor ainda não viu tokens fechados pelos traders acompanhados nas últimas 24 h "
                       "(ou o servidor reiniciou há pouco — esta parte recomeça do zero a cada reinício).")
    t1 = mine1["total"]
    summary.append(f"Suas cópias ({'real' if real else 'fictício'}) nas últimas 24 h: {t1['trades']} trades fechados, "
                   f"resultado {t1['pnl_sol']:+.4f} SOL" + (f", acerto {t1['win_rate'] * 100:.0f}%." if t1["win_rate"] is not None else "."))
    sk = mine1["skips"][:1]
    if sk:
        summary.append(f"O filtro que mais barrou cópias hoje: {sk[0]['reason']} ({sk[0]['count']} vezes).")
    return {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "real": real,
            "summary": summary, "suggestions": sug, "traders_today": tt, "mine_24h": mine1["total"], "history": wk,
            "mine_7d": mine7["total"], "days": mine7["days_list"][:7],
            "limits": ["Comportamento dos traders: últimas 24 h vistas pelo monitor; recomeça quando o servidor reinicia. "
                       "O resumo de cada dia fica guardado (a cada 30 min) e forma o histórico abaixo.",
                       "Sugestões só aparecem com base mínima de casos e nunca são aplicadas sozinhas.",
                       "Resultado passado não garante o futuro; em memecoins os padrões mudam rápido."]}
