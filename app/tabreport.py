"""Relatório de cada aba de trade a cada 30 min (0.32.41, pedido do dono em 29/10: "todas as tabs de trade gerem seus
relatórios de ganhos e perdas, tentar analisar o que está errado, a cada 30 min, com veredito, e usar isso na Base geral
para aprender com os erros"). Também analisa os maiores ganhos e as maiores perdas, um por um, com o veredito.

Só lê os trades e as posições; não muda nenhuma regra nem configuração."""
from __future__ import annotations

from datetime import datetime, timezone

WINDOW_S = 1800


def _ts(v) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


# causa de cada perda e como corrigir
CAUSES = {
    "entrou_no_topo": ("entrou no topo: nunca passou de +3% e bateu o stop",
                       "o gatilho de entrada chega tarde; esperar confirmação menor ou entrar mais cedo"),
    "devolveu_ganho": ("chegou a +20% ou mais e fechou no prejuízo",
                       "proteger o ganho: stop móvel ou venda parcial mais cedo"),
    "stop_escorregou": ("o stop fechou 10+ pontos abaixo do configurado (despencou de uma vez ou preço atrasado)",
                        "token que cai de uma vez costuma ser rug/despejo: filtrar criador/concentração; o stop não protege nesse caso"),
    "tempo_no_prejuizo": ("saiu pelo tempo máximo no prejuízo", "token parado: tempo máximo menor ou sair quando não sobe em X min"),
    "trader_vendeu": ("o trader copiado vendeu e a cópia fechou no prejuízo", "atraso da cópia; preferir traders que seguram mais"),
    "stop_normal": ("stop de perda dentro do esperado", "normal da estratégia; olhar o acerto da aba"),
    "outra": ("outra saída no prejuízo", "ver o motivo do trade"),
}


def loss_cause(t: dict) -> str:
    r = str(t.get("reason") or "").lower()
    best = t.get("best_pct")
    pct = t.get("pnl_pct")
    if best is not None and best >= 20:
        return "devolveu_ganho"
    if "stop de perda" in r:
        try:
            stop = float(r.split("−")[1].split("%")[0]) if "−" in r else float(r.split("-")[1].split("%")[0])
        except Exception:
            stop = 30.0
        if pct is not None and pct < -(stop + 10):
            return "stop_escorregou"
        if best is not None and best < 3:
            return "entrou_no_topo"
        return "stop_normal"
    if "tempo máximo" in r:
        return "tempo_no_prejuizo"
    if "trader" in r and "vend" in r:
        return "trader_vendeu"
    return "outra"


def trade_verdict(t: dict) -> str:
    pnl, best, pct = t.get("pnl_sol") or 0, t.get("best_pct"), t.get("pnl_pct")
    if pnl > 0:
        if best is not None and pct is not None and best - pct >= 30:
            return f"ganhou, mas deixou {best - pct:.0f} pontos na mesa (pico {best:+.0f}%)"
        return "ganhou bem: a saída pegou perto do pico" if best is not None and pct is not None and best - pct < 15 else "ganhou"
    return CAUSES[loss_cause(t)][0]


def _row(t: dict, aba: str) -> dict:
    return {"aba": aba, "symbol": t.get("symbol"), "mint": t.get("mint"), "pnl_sol": round(t.get("pnl_sol") or 0, 5),
            "pnl_pct": t.get("pnl_pct"), "best_pct": t.get("best_pct"), "reason": t.get("reason"),
            "opened_at": t.get("opened_at"), "closed_at": t.get("closed_at"), "hold_s": t.get("hold_s"),
            "veredito": trade_verdict(t), "causa": None if (t.get("pnl_sol") or 0) > 0 else loss_cause(t)}


def _group(rows: list[dict]) -> dict:
    n = len(rows)
    w = sum(1 for t in rows if (t.get("pnl_sol") or 0) > 0)
    pnl = sum(t.get("pnl_sol") or 0 for t in rows)
    gain = sum(t.get("pnl_sol") or 0 for t in rows if (t.get("pnl_sol") or 0) > 0)
    loss = -sum(t.get("pnl_sol") or 0 for t in rows if (t.get("pnl_sol") or 0) < 0)
    return {"n": n, "ganhos": w, "perdas": n - w, "acerto": round(w / n * 100) if n else None, "pnl_sol": round(pnl, 5),
            "fator": round(gain / loss, 2) if loss else None}


def verdict(g24: dict, causes: dict) -> tuple[str, str]:
    if g24["n"] < 3:
        return "poucos dados", "menos de 3 operações fechadas em 24 h"
    if g24["pnl_sol"] > 0 and (g24["acerto"] or 0) >= 45:
        return "ganhando", f"{g24['acerto']}% de acerto e {g24['pnl_sol']:+.4f} SOL em 24 h"
    if g24["pnl_sol"] > 0:
        return "atenção", "no lucro, mas acerta pouco: depende de poucos ganhos grandes"
    top = max(causes.items(), key=lambda kv: kv[1]["sol"])[0] if causes else "outra"
    return "perdendo", f"{g24['pnl_sol']:+.4f} SOL em 24 h; maior causa: {CAUSES[top][0]}"


def build(trades: list[dict], positions: list[dict], aba_of, now: float, real: bool = False) -> dict:
    """Um relatório: por aba, últimos 30 min e 24 h, causas das perdas, veredito e o que corrigir; maiores ganhos e
    perdas de 24 h com o veredito de cada um; posições abertas com preço parado."""
    tr = [t for t in trades if bool(t.get("real")) == real]
    abas: dict[str, dict] = {}
    big = []
    for t in tr:
        tc = _ts(t.get("closed_at"))
        if now - tc > 86400:
            continue
        aba = aba_of(t)
        a = abas.setdefault(aba, {"r24": [], "r30": []})
        a["r24"].append(t)
        if now - tc <= WINDOW_S:
            a["r30"].append(t)
        big.append(_row(t, aba))
    out_abas = []
    for aba, a in abas.items():
        causes: dict[str, dict] = {}
        for t in a["r24"]:
            if (t.get("pnl_sol") or 0) < 0:
                c = causes.setdefault(loss_cause(t), {"n": 0, "sol": 0.0})
                c["n"] += 1
                c["sol"] += -(t.get("pnl_sol") or 0)
        g24, g30 = _group(a["r24"]), _group(a["r30"])
        v, why = verdict(g24, causes)
        fixes = [{"causa": k, "texto": CAUSES[k][0], "n": c["n"], "sol": round(c["sol"], 5), "corrigir": CAUSES[k][1]}
                 for k, c in sorted(causes.items(), key=lambda kv: -kv[1]["sol"])]
        out_abas.append({"aba": aba, "h30": g30, "h24": g24, "veredito": v, "por_que": why, "causas": fixes})
    out_abas.sort(key=lambda a: a["h24"]["pnl_sol"])
    stuck = []
    for p in positions:
        if bool(p.get("real")) != real:
            continue
        age = now - float(p.get("open_t") or now)
        if age > 3600 and p.get("price_now") and p.get("price_in") and abs(p["price_now"] / p["price_in"] - 1) < 0.0005:
            stuck.append({"aba": aba_of(p), "symbol": p.get("symbol"), "mint": p.get("mint"), "horas": round(age / 3600, 1)})
    wins = sorted([b for b in big if b["pnl_sol"] > 0], key=lambda b: -b["pnl_sol"])[:10]
    losses = sorted([b for b in big if b["pnl_sol"] < 0], key=lambda b: b["pnl_sol"])[:10]
    tot24 = _group([t for a in abas.values() for t in a["r24"]])
    return {"t": now, "em": datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="seconds"), "real": real,
            "abas": out_abas, "maiores_ganhos": wins, "maiores_perdas": losses, "parados": stuck, "total24": tot24}


def learn(reports: list[dict]) -> dict:
    """O que os relatórios guardados ensinam (base geral): por aba, quantas vezes cada veredito apareceu e as causas que
    se repetem; e as causas que mais tiraram dinheiro em todas as abas."""
    per: dict[str, dict] = {}
    allc: dict[str, dict] = {}
    for r in reports:
        for a in r.get("abas") or []:
            g = per.setdefault(a["aba"], {"relatorios": 0, "vereditos": {}, "causas": {}, "ultimo": None})
            g["relatorios"] += 1
            g["vereditos"][a["veredito"]] = g["vereditos"].get(a["veredito"], 0) + 1
            if g["ultimo"] is None or r["t"] > g["ultimo"]["t"]:
                g["ultimo"] = {"t": r["t"], "veredito": a["veredito"], "por_que": a["por_que"], "pnl24": a["h24"]["pnl_sol"]}
            for c in a.get("causas") or []:
                g["causas"][c["causa"]] = g["causas"].get(c["causa"], 0) + 1
    # perdas por causa: soma só os trades distintos (cada perda aparece em vários relatórios seguidos)
    seen = set()
    for r in reports:
        for b in r.get("maiores_perdas") or []:
            k = (b.get("mint"), b.get("closed_at"))
            if k in seen or not b.get("causa"):
                continue
            seen.add(k)
            c = allc.setdefault(b["causa"], {"n": 0, "sol": 0.0, "texto": CAUSES[b["causa"]][0], "corrigir": CAUSES[b["causa"]][1]})
            c["n"] += 1
            c["sol"] = round(c["sol"] - b["pnl_sol"], 5)
    out = []
    for aba, g in per.items():
        rec = [k for k, n in g["causas"].items() if n >= 3]
        out.append({"aba": aba, **g, "repetem": [{"causa": k, "texto": CAUSES[k][0], "corrigir": CAUSES[k][1], "vezes": g["causas"][k]} for k in rec]})
    out.sort(key=lambda a: (a["ultimo"] or {}).get("pnl24", 0))
    return {"relatorios": len(reports), "abas": out,
            "causas": sorted(({"causa": k, **v} for k, v in allc.items()), key=lambda c: -c["sol"])}
