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
JEV_MODEL = "jev-1.14.0"     # 0.32.106: versão fixa; "jev-latest" muda sozinho e misturaria modelos nos estudos (docs.typesafe.ai/models)
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
            "tokens_in": int(u.get("input_tokens") or 0), "modelo": (js or {}).get("model")}


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


SLIP_LADO_PCT = 3.0         # 0.32.107: o valor de pump_extra_slip_pct; a única execução real publicada (lote 11) mediu perto disso, por lado


def real_cost_pct(sol: float, prio_sol: float = 0.0005, portal_pct: float = 0.5, slip_lado: float = 0.0) -> float:
    """0.32.106 (lotes 8 e 10, conta refeita): compra + venda na curva pela rota Local, antes de slippage e impacto:
    1,25% da curva + 0,5% da PumpPortal por lado, mais rede e priority fee. Os 4% dos estudos ficam como estão, para comparar
    com o passado; este número aparece ao lado."""
    return round(2 * (1.25 + portal_pct + slip_lado) + 100 * 2 * (0.000005 + prio_sol) / sol, 2)


def with_real_cost(total_sol: float, n: int, sol: float, slip_lado: float = 0.0) -> float:
    return round(total_sol - n * sol * (real_cost_pct(sol, slip_lado=slip_lado) - FEE_PCT) / 100, 5)


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
        r = s["_r"] if "_r" in s else sim_result(s, exit_min)
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
    cnt = {"todos": sum(g["medidos"] for g in by_act.values()), "jev": (by_act.get("entrar") or {}).get("medidos", 0)}
    return {"n": len(js), "saida_min": exit_min, "sol_por_entrada": sol, "por_acao": by_act, "custo_real_pct": real_cost_pct(sol),
            "custo_slip_pct": real_cost_pct(sol, slip_lado=SLIP_LADO_PCT),
            "total_real": {k: with_real_cost(acc[k], cnt[k], sol) for k in cnt},
            "total_slip": {k: with_real_cost(acc[k], cnt[k], sol, SLIP_LADO_PCT) for k in cnt},
            "calibracao": [{"faixa": k, **bands[k], "subiu_pct": round(bands[k]["subiu"] / bands[k]["n"] * 100)} for k in order if k in bands],
            "curva": curve, "total": {k: round(v, 5) for k, v in acc.items()}}


# ---------------------------------------------------------------------------- 0.32.84: estudo do passado (backtest)
# Pedido do dono (30/10): o Jev também analisa os casos JÁ PASSADOS guardados no banco desde o início do projeto.
# O Jev não "aprende" com eles (não é treinado com os nossos dados): ele recebe cada caso só com o que se sabia NA HORA
# (nada do futuro entra no estado) e responde como se fosse ao vivo. Depois comparamos com o que o token fez.
# É isso que mede se vale confiar nele — e em que faixa de chance.
BT_SOURCES = {"bruxo": "Aba do Bruxo (sinais e lançamentos)", "explorar": "Explorar (tokens barrados, sombras)",
              "base": "Base da pump.fun (todo lançamento, foto de 1 min)"}
BT_DAY_MAX = 20000          # perguntas por dia do estudo do passado (separado das 3.000 do ao vivo)
BT_GAP_S = 0.5              # meio segundo entre perguntas
PICK = {"5": ("5", "10", "15"), "10": ("10", "15", "5"), "25": ("25", "15", "60", "10")}


def _pct(a, b):
    try:
        return round((float(a) / float(b) - 1) * 100, 2) if a and b else None
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def case_bruxo(s: dict) -> dict | None:
    """Sinal da Aba do Bruxo já encerrado (30 min acompanhado)."""
    if not s.get("done") or not s.get("marks") or (s.get("jev") or {}).get("acao"):
        return None
    res = {k: sim_result(s, k) for k in ("5", "10", "25")}
    dec = s.get("decisoes") or {}
    return {"id": "bruxo:" + str(s["id"]), "fonte": "bruxo", "t": s["t"], "mint": s.get("mint"), "symbol": s.get("symbol"),
            "kind": s.get("kind", "trader"), "state": state_for(s), "res": {k: v for k, v in res.items() if v is not None},
            "pico": s.get("peak_pct"), "regra": any(d.get("entrou") for d in dec.values()) if s.get("kind", "trader") == "trader" else None,
            "dobrou": s.get("hit100_s") is not None,
            "stop": s.get("stop30_s") is not None and (s.get("hit100_s") is None or s["stop30_s"] < s["hit100_s"])}


def case_explorar(mint: str, d: dict) -> dict | None:
    """Token que o Explorar analisou e barrou (sombra): preço na hora e aos 15 min."""
    if d.get("ret") is None or not d.get("t0"):
        return None
    i = d.get("info") or {}
    st = {"token": {"symbol": d.get("symbol"), "age_min": i.get("age_min")},
          "signal": {"kind": "explorar", "our_verdict": d.get("veredito")},
          "numbers": {k: i.get(k) for k in ("holders", "top10", "dev_pct", "pressure", "curve_pct", "chg_5m", "risk",
                                            "snipers_pct", "bundlers_pct", "insiders_pct", "avg_trade_usd") if i.get(k) is not None}}
    r = round(float(d["ret"]) - FEE_PCT, 2)
    return {"id": "explorar:" + mint + ":" + str(int(d["t0"])), "fonte": "explorar", "t": float(d["t0"]), "mint": mint,
            "symbol": d.get("symbol"), "kind": "explorar", "state": st, "res": {"15": r}, "pico": d.get("pico"),
            "regra": d.get("veredito") == "chance alta", "dobrou": (d.get("pico") or 0) >= 100, "stop": r <= -30}


def case_base(mint: str, d: dict, created_em: str | None = None) -> dict | None:
    """Lançamento da pump.fun visto pela Base: decide no 1º minuto (foto de 1 min), resultado aos 5/15/60 min."""
    from datetime import datetime
    sn = d.get("snaps") or {}
    m1 = sn.get("1")
    if not m1:
        return None
    try:
        t0 = datetime.fromisoformat(str(d.get("created_at") or created_em).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None
    cb = d.get("creator_before") if isinstance(d.get("creator_before"), dict) else {}
    st = {"token": {"symbol": d.get("symbol"), "name": d.get("name"), "age_min": 1},
          "signal": {"kind": "lancamento"},
          "numbers": {"market_cap_sol": round(float(m1), 2), "market_cap_at_launch_sol": round(float(d.get("mcap0") or 0), 2),
                      "first_minute_change_pct": _pct(m1, d.get("mcap0")), "creator_buy_sol": d.get("dev_buy"),
                      "creator_past_tokens": {k: v for k, v in cb.items() if isinstance(v, (int, float))} or None}}
    res = {k: round(_pct(sn.get(k), m1) - FEE_PCT, 2) for k in ("5", "15", "60") if _pct(sn.get(k), m1) is not None}
    if not res:
        return None
    pico = _pct(max([float(v) for v in sn.values() if v] + [float(d.get("peak") or 0)]), m1)
    return {"id": "base:" + mint, "fonte": "base", "t": t0 + 60, "mint": mint, "symbol": d.get("symbol"), "kind": "lancamento",
            "state": st, "res": res, "pico": pico, "regra": None, "dobrou": (pico or 0) >= 100,
            "stop": any(v <= -30 - FEE_PCT for v in res.values())}


def compact(c: dict, j: dict) -> dict:
    """O que fica guardado do caso (sem o estado inteiro, para o banco e a memória não crescerem demais)."""
    return {"t": c["t"], "mint": c.get("mint"), "symbol": c.get("symbol"), "kind": c.get("kind"), "res": c["res"],
            "pico": c.get("pico"), "regra": c.get("regra"), "dobrou": c.get("dobrou"), "stop": c.get("stop"),
            "n": (c.get("state") or {}).get("numbers"),
            "jev": {k: j.get(k) for k in ("acao", "p", "qualidade", "armadilha", "ms", "erro", "modelo") if j.get(k) is not None}}


def pick(res: dict, saida: str):
    for k in PICK.get(saida, (saida,)):
        if (res or {}).get(k) is not None:
            return res[k]
    return None


def study_rows(rows: list[dict], saida: str = "10", sol: float = 0.1) -> dict:
    """Mesmo estudo do ao vivo, para casos guardados (cada um com jev, res, regra, dobrou, stop)."""
    sigs = []
    for c in rows:
        if not (c.get("jev") or {}).get("acao"):
            continue
        sigs.append({"t": c["t"], "jev": c["jev"], "_r": pick(c.get("res") or {}, saida), "entrou_regra": bool(c.get("regra")),
                     "hit100_s": 1 if c.get("dobrou") else None, "stop30_s": 0 if c.get("stop") else None})
    return study(sigs, saida, sol)
