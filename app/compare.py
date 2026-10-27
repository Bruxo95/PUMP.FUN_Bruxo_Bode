"""Comparar configuração copiada (0.31.34, pedido do dono em 2026-10-27).

Depois que a conta Y passa a usar a configuração da conta X (convite aceito ou "Copiar config" do Admin), o sistema
deveria fazer as mesmas coisas nas duas contas. Aqui comparamos os trades FECHADOS das duas carteiras fictícias a
partir do momento da cópia: resultado de cada lado, tokens em comum (e quanto cada um fez neles), o que só aconteceu
com X e não com Y (e o contrário), quanto a configuração de cada lado já se afastou da copiada e conclusões em texto.

Só cálculo (sem rede). O texto de `ai_text` é o que vai para uma IA estudar; nunca leva chaves nem carteiras reais.
"""
from __future__ import annotations

from datetime import datetime


def _ts(s) -> float | None:
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _eq(a, b) -> bool:
    try:
        if isinstance(a, bool) or isinstance(b, bool):
            return bool(a) == bool(b)
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return str(a) == str(b)


def _origem(t: dict) -> str:
    return t.get("origem") or ("manual" if t.get("wallet") == "manual" else "cópia de trader")


def summary(trades: list[dict]) -> dict:
    n = len(trades)
    wins = [t for t in trades if (t.get("pnl_sol") or 0) > 0]
    pnl = sum(t.get("pnl_sol") or 0 for t in trades)
    inv = sum(t.get("sol_in") or 0 for t in trades)
    por = {}
    for t in trades:
        o = por.setdefault(_origem(t), {"nome": _origem(t), "trades": 0, "wins": 0, "pnl_sol": 0.0})
        o["trades"] += 1
        o["wins"] += 1 if (t.get("pnl_sol") or 0) > 0 else 0
        o["pnl_sol"] += t.get("pnl_sol") or 0
    for o in por.values():
        o["pnl_sol"] = round(o["pnl_sol"], 6)
        o["acerto"] = round(o["wins"] / o["trades"], 3) if o["trades"] else None
    return {"trades": n, "wins": len(wins), "acerto": round(len(wins) / n, 3) if n else None, "pnl_sol": round(pnl, 6),
            "invested_sol": round(inv, 6), "retorno_pct": round(pnl / inv * 100, 2) if inv else None,
            "por_origem": sorted(por.values(), key=lambda o: -o["trades"])}


def _by_mint(trades: list[dict]) -> dict:
    out = {}
    for t in trades:
        m = t.get("mint")
        if not m:
            continue
        g = out.setdefault(m, {"mint": m, "token": t.get("symbol") or m[:6], "pnl_sol": 0.0, "trades": 0, "abriu": None, "motivos": []})
        g["pnl_sol"] += t.get("pnl_sol") or 0
        g["trades"] += 1
        a = _ts(t.get("opened_at"))
        if a and (g["abriu"] is None or a < g["abriu"]):
            g["abriu"] = a
        if t.get("reason") and len(g["motivos"]) < 3:
            g["motivos"].append(str(t["reason"])[:80])
    for g in out.values():
        g["pnl_sol"] = round(g["pnl_sol"], 6)
    return out


def drift(cfg_values: dict, offer_values: dict) -> list[str]:
    return [k for k, v in offer_values.items() if k in cfg_values and not _eq(cfg_values[k], v)]


def compare(offer: dict, src_trades: list[dict], my_trades: list[dict], src_cfg: dict, my_cfg: dict,
            src_nome: str, my_nome: str) -> dict:
    since = _ts(offer.get("em")) or 0
    pick = lambda L: [t for t in L if not t.get("real") and (_ts(t.get("closed_at")) or 0) >= since]   # noqa: E731
    S, M = pick(src_trades), pick(my_trades)
    a, b = summary(S), summary(M)
    ms, mm = _by_mint(S), _by_mint(M)
    common = []
    for m in set(ms) & set(mm):
        x, y = ms[m], mm[m]
        common.append({"mint": m, "token": x["token"], "pnl_x": x["pnl_sol"], "pnl_y": y["pnl_sol"],
                       "atraso_s": round(y["abriu"] - x["abriu"]) if x["abriu"] and y["abriu"] else None,
                       "motivo_x": "; ".join(x["motivos"]), "motivo_y": "; ".join(y["motivos"])})
    common.sort(key=lambda c: -abs((c["pnl_x"] or 0) - (c["pnl_y"] or 0)))
    only_x = sorted((ms[m] for m in set(ms) - set(mm)), key=lambda g: -g["pnl_sol"])
    only_y = sorted((mm[m] for m in set(mm) - set(ms)), key=lambda g: -g["pnl_sol"])
    vals = offer.get("valores") or {}
    dx, dy = drift(src_cfg, vals), drift(my_cfg, vals)
    conc = []
    if a["trades"] + b["trades"] < 6:
        conc.append(f"Base pequena: {a['trades']} trades de {src_nome} e {b['trades']} de {my_nome} desde a cópia. "
                    "Espere mais trades antes de concluir.")
    if dy:
        conc.append(f"A sua configuração já mudou em {len(dy)} opção(ões) depois da cópia; a comparação deixa de ser justa nessas regras.")
    if dx:
        conc.append(f"{src_nome} mudou {len(dx)} opção(ões) depois que você copiou; ele já não usa exatamente a mesma configuração.")
    tot_tok = len(set(ms) | set(mm))
    if tot_tok:
        conc.append(f"Tokens em comum: {len(common)} de {tot_tok} ({round(len(common) / tot_tok * 100)}%). "
                    + ("Com a mesma configuração, o esperado é perto de 100%; a diferença vem de traders seguidos diferentes, "
                       "horário em que cada conta estava ativa, limites de posições/saldo ou atraso." if len(common) < tot_tok else "As duas contas entraram nos mesmos tokens."))
    if only_x:
        ganhos = sum(g["pnl_sol"] for g in only_x if g["pnl_sol"] > 0)
        if ganhos > 0:
            conc.append(f"{src_nome} ganhou {ganhos:+.4f} SOL em tokens que você não pegou (ex.: {', '.join(g['token'] for g in only_x[:3])}).")
    if only_y:
        perdas = sum(g["pnl_sol"] for g in only_y if g["pnl_sol"] < 0)
        if perdas < 0:
            conc.append(f"Você perdeu {perdas:+.4f} SOL em tokens que {src_nome} não pegou.")
    atrasos = [c["atraso_s"] for c in common if c["atraso_s"] is not None]
    if atrasos:
        med = sorted(atrasos)[len(atrasos) // 2]
        conc.append(f"Nos tokens em comum você entrou em média {med:+d} s em relação a {src_nome} (negativo = antes).")
    if common:
        dif = sum((c["pnl_y"] or 0) - (c["pnl_x"] or 0) for c in common)
        conc.append(f"Nos tokens em comum o seu resultado foi {dif:+.4f} SOL em relação ao de {src_nome}"
                    + (" — saídas diferentes no mesmo token (veja os motivos)." if abs(dif) > 0.001 else "."))
    if a["trades"] and b["trades"]:
        conc.append(f"Resultado desde a cópia: {src_nome} {a['pnl_sol']:+.4f} SOL em {a['trades']} trades; "
                    f"{my_nome} {b['pnl_sol']:+.4f} SOL em {b['trades']} trades.")
    return {"desde": offer.get("em"), "x": {"nome": src_nome, **a}, "y": {"nome": my_nome, **b},
            "comum": common[:50], "so_x": only_x[:30], "so_y": only_y[:30],
            "drift_x": dx, "drift_y": dy, "opcoes": len(vals), "conclusoes": conc}


def ai_text(r: dict, parte: str = "") -> str:
    """Texto para uma IA estudar: o que aconteceu e o que não aconteceu depois de copiar a configuração."""
    x, y = r["x"], r["y"]
    L = [f"COMPARAÇÃO DE CONFIGURAÇÃO COPIADA ({parte})", f"Desde: {r.get('desde')}  · opções copiadas: {r.get('opcoes')}",
         f"{x['nome']} (origem): {x['trades']} trades, acerto {x['acerto']}, {x['pnl_sol']:+.4f} SOL, retorno {x['retorno_pct']}%",
         f"{y['nome']} (copiou): {y['trades']} trades, acerto {y['acerto']}, {y['pnl_sol']:+.4f} SOL, retorno {y['retorno_pct']}%",
         f"Opções que mudaram depois: origem {r['drift_x']} · cópia {r['drift_y']}", "", "CONCLUSÕES:"]
    L += [f"- {c}" for c in r["conclusoes"]]
    L += ["", "TOKENS EM COMUM (token, resultado origem, resultado cópia, atraso s, motivo origem | motivo cópia):"]
    L += [f"- {c['token']} {c['pnl_x']:+.4f} {c['pnl_y']:+.4f} {c['atraso_s']} | {c['motivo_x']} | {c['motivo_y']}" for c in r["comum"]]
    L += ["", f"SÓ {x['nome']} (aconteceu com a origem e não com a cópia):"]
    L += [f"- {g['token']} {g['pnl_sol']:+.4f} SOL · {'; '.join(g['motivos'])}" for g in r["so_x"]]
    L += ["", f"SÓ {y['nome']} (aconteceu com a cópia e não com a origem):"]
    L += [f"- {g['token']} {g['pnl_sol']:+.4f} SOL · {'; '.join(g['motivos'])}" for g in r["so_y"]]
    L += ["", "PERGUNTA PARA A IA: por que as duas contas, com a mesma configuração, tiveram resultados diferentes, "
              "e o que mudar no código ou na configuração para que a cópia reproduza a origem e ganhe mais?"]
    return "\n".join(L)
