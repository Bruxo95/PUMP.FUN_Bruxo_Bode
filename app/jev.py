"""Jev (TypeSafe AI) na Aba do Bruxo — MODO SOMBRA (0.32.83, pedido do dono em 30/10).

O Jev é um modelo de DECISÃO: recebe um estado (números já calculados pelo robô) e perguntas fechadas, e devolve
respostas tipadas com probabilidade (escolha, nota, sim/não). Aqui ele só OPINA sobre cada sinal da Aba do Bruxo
(top trader comprou moeda nova) e sobre cada lançamento estudado: a opinião fica gravada no sinal, e a aba JEV
compara depois com o que o token fez (1/5/10/25 min, pico, detentores). Nada é comprado pelo Jev nesta etapa.

Chave: Administração → Chaves do sistema → "Jev (TypeSafe AI)". Sem chave, nada é chamado.
Custo divulgado (nexos.ai, out/2026): ~US$ 0,042 por milhão de tokens de entrada; a saída é grátis.
"""
from __future__ import annotations

import time

JEV_URL = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = "jev-latest"
DAY_MAX = 3000              # chamadas por dia (todas as contas juntas)
TIMEOUT_S = 8.0
ACTIONS = ("entrar", "esperar", "evitar")

QUESTIONS = {
    "acao": {
        "type": "choice",
        "instructions": (
            "`token` is a pump.fun memecoin (Solana) only minutes old. `signal` says why we are looking at it: a top trader "
            "bought it (`signal.kind`=trader) or it is a fresh launch with no trader yet (`signal.kind`=lancamento). "
            "`numbers` are measured facts: age in minutes, buy pace (SOL per minute) against the average pace of new tokens, "
            "holders now and one minute ago, share of supply held by the top 10 holders and by the creator, the creator's "
            "past tokens, how much SOL the top traders put in, market cap in SOL. Most such tokens collapse within 25 "
            "minutes; a few double. Should a trader BUY this token right now, planning to sell within 25 minutes?"),
        "criteria": {
            "entrar": "Buy now: real demand, healthy distribution, good chance of rising soon.",
            "esperar": "Not now: unclear or mixed signals, wait for confirmation.",
            "evitar": "Avoid: looks like a dump, a bundle, a serial launcher or a trap for copy traders.",
        },
    },
    "qualidade": {
        "type": "score",
        "instructions": "How good is this entry, using only `numbers` and `signal`?",
        "criteria": ["Terrible: almost sure to dump", "Weak", "Average", "Good", "Excellent: strong demand and healthy holders"],
    },
    "armadilha": {
        "type": "noul",
        "instructions": "Is this token likely a trap (bundle, insiders, serial launcher, wash trading) that dumps on copy traders?",
        "criteria": {"true": "Likely a trap", "false": "No clear sign of a trap"},
    },
}


def state_for(s: dict, extra: dict | None = None) -> dict:
    """Estado enxuto (o Jev erra mais com informação sobrando). Só números já medidos; nada de chave ou carteira nossa."""
    f = {**(s.get("flow") or {}), **(s.get("filtros") or {})}
    H = s.get("holders") or {}
    st = {
        "token": {"symbol": s.get("symbol"), "age_min": s.get("age_min")},
        "signal": {"kind": s.get("kind", "trader"), "top_traders": len(s.get("wallets") or []),
                   "top_traders_sol": s.get("sol_traders")},
        "numbers": {"buy_pace_sol_per_min": f.get("flow"), "avg_pace_new_tokens": f.get("flow_base"),
                    "market_cap_sol": f.get("mcap") if f.get("mcap") is not None else s.get("mcap0"),
                    "top10_pct": f.get("top10"), "creator_pct": f.get("dev_pct"), "creator_buy_sol": f.get("dev_buy"),
                    "holders_now": H.get("0")},
    }
    if extra:
        st["numbers"].update({k: v for k, v in extra.items() if v is not None})
    return st


def parse(js: dict) -> dict:
    """Resposta do Jev → {acao, p:{entrar,esperar,evitar}, conf, qualidade (0–4), armadilha (0–1)}."""
    a = (js or {}).get("answers") or {}
    ac = a.get("acao") or {}
    probs = {k: round(float((ac.get("probabilities") or {}).get(k) or 0), 3) for k in ACTIONS}
    u = (js or {}).get("usage") or {}
    return {"acao": ac.get("choice"), "p": probs, "conf": ac.get("confidence"),
            "qualidade": (a.get("qualidade") or {}).get("score"), "armadilha": (a.get("armadilha") or {}).get("noul"),
            "tokens_in": int(u.get("input_tokens") or 0)}


async def ask(http, key: str, state: dict, url: str = JEV_URL, model: str = JEV_MODEL) -> dict:
    t0 = time.monotonic()
    r = await http.post(url, json={"state": state, "model": model, "questions": QUESTIONS}, timeout=TIMEOUT_S,
                        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    ms = round((time.monotonic() - t0) * 1000)
    if r.status_code != 200:
        txt = r.text[:120].replace(key, "***") if key else r.text[:120]
        raise RuntimeError(f"HTTP {r.status_code}: {txt}")
    out = parse(r.json())
    out["ms"] = ms
    return out


# ---------------------------------------------------------------------------- análise da aba JEV
EXITS = ("5", "10", "25")
FEE_PCT = 4.0               # compra + venda na pump.fun (mesma estimativa das sombras)


def sim_result(s: dict, exit_min: str, stop_pct: float = 30.0) -> float | None:
    """Resultado (%) de ter entrado no preço do sinal e saído na marca de `exit_min` min (ou no stop, se veio antes),
    já com as taxas. None = sem a foto da marca."""
    m = (s.get("marks") or {}).get(exit_min)
    if m is None:
        return None
    st = s.get("stop30_s")
    if stop_pct and st is not None and st <= int(exit_min) * 60:
        return -stop_pct - FEE_PCT
    return round(m - FEE_PCT, 2)


def study(signals: list[dict], exit_min: str = "10", sol: float = 0.1) -> dict:
    """Decisões do Jev × o que o token fez: acerto por ação, calibração por faixa de chance e a curva de ganho em SOL
    de três jeitos (entrar quando o Jev disse "entrar", quando a regra entrou, e em todos)."""
    js = sorted([s for s in signals if (s.get("jev") or {}).get("acao")], key=lambda s: s["t"])
    by_act: dict[str, dict] = {a: {"n": 0, "medidos": 0, "subiu": 0, "dobrou": 0, "stop": 0, "res": []} for a in ACTIONS}
    bands: dict[str, dict] = {}
    curve = {"jev": [], "regra": [], "todos": []}
    acc = {"jev": 0.0, "regra": 0.0, "todos": 0.0}
    for s in js:
        j = s["jev"]
        g = by_act.setdefault(j["acao"], {"n": 0, "medidos": 0, "subiu": 0, "dobrou": 0, "stop": 0, "res": []})
        g["n"] += 1
        r = sim_result(s, exit_min)
        if r is None:
            continue
        g["medidos"] += 1
        g["subiu"] += r > 0
        g["dobrou"] += s.get("hit100_s") is not None
        g["stop"] += s.get("stop30_s") is not None and (s.get("hit100_s") is None or s["stop30_s"] < s["hit100_s"])
        g["res"].append(r)
        pe = (j.get("p") or {}).get("entrar")
        if pe is not None:
            k = "0–20%" if pe < .2 else "20–40%" if pe < .4 else "40–60%" if pe < .6 else "60–80%" if pe < .8 else "80–100%"
            b = bands.setdefault(k, {"n": 0, "subiu": 0})
            b["n"] += 1
            b["subiu"] += r > 0
        sol_r = sol * r / 100
        acc["todos"] += sol_r
        if j["acao"] == "entrar":
            acc["jev"] += sol_r
        if s.get("entrou_regra"):
            acc["regra"] += sol_r
        for k in curve:
            curve[k].append([s["t"], round(acc[k], 5)])
    for g in by_act.values():
        res = g.pop("res")
        g["acerto"] = round(g["subiu"] / g["medidos"] * 100) if g["medidos"] else None
        g["media_pct"] = round(sum(res) / len(res), 2) if res else None
        g["sol"] = round(sum(res) * sol / 100, 5) if res else 0.0
    order = ["0–20%", "20–40%", "40–60%", "60–80%", "80–100%"]
    return {"n": len(js), "saida_min": exit_min, "sol_por_entrada": sol, "por_acao": by_act,
            "calibracao": [{"faixa": k, **bands[k], "subiu_pct": round(bands[k]["subiu"] / bands[k]["n"] * 100)} for k in order if k in bands],
            "curva": curve, "total": {k: round(v, 5) for k, v in acc.items()}}
