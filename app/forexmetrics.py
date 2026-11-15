"""0.32.368 (pedido do dono, 15/11/2026): motor de nota do Projeto Forex (docs/FOREX.md, seção 5).

Recebe a lista de trades FECHADOS de um mestre (e, se houver, a curva de patrimônio) e devolve as métricas, os alertas de
estratégia perigosa (martingale, grade sem stop) e a nota 0–100. Só biblioteca padrão: roda no servidor e nos testes, sem internet.

Formato de um trade (dict):
    {"ticket": "123", "simbolo": "EURUSD", "lado": "buy", "volume": 0.10, "abriu": <epoch s>, "fechou": <epoch s>,
     "lucro": -12.5, "sl": 1.0712 | None}
Formato de uma foto de patrimônio: {"t": <epoch s>, "patrimonio": 10234.5, "depositos": 0}
"""
from __future__ import annotations

import math
from collections import defaultdict

DIA = 86400

# filtros de qualidade (docs/FOREX.md): abaixo disso o mestre não entra no ranking
MIN_DIAS = 60
MIN_TRADES = 50
MAX_DD_PCT = 40.0
MAX_MARTINGALE = 0.25
MAX_GRADE = 0.25
MAX_SEM_STOP = 0.70


# ------------------------------------------------------------------------------------------------------------------ básicas
def profit_factor(trades: list[dict]) -> float | None:
    """Lucro bruto ÷ prejuízo bruto. None sem prejuízo nenhum (não dá para dividir; o ranking trata como "sem dado")."""
    ganho = sum(t["lucro"] for t in trades if t.get("lucro", 0) > 0)
    perda = -sum(t["lucro"] for t in trades if t.get("lucro", 0) < 0)
    if perda <= 0:
        return None if ganho <= 0 else float("inf")
    return ganho / perda


def max_drawdown(curva: list[float]) -> dict:
    """Maior queda percentual do pico ao vale. Devolve {"pct", "pico", "vale", "i_pico", "i_vale"} (pct em %, positivo)."""
    pico, i_pico, pior = None, 0, {"pct": 0.0, "pico": None, "vale": None, "i_pico": None, "i_vale": None}
    for i, v in enumerate(curva):
        if pico is None or v > pico:
            pico, i_pico = v, i
            continue
        if pico > 0:
            dd = (pico - v) / pico * 100
            if dd > pior["pct"]:
                pior = {"pct": dd, "pico": pico, "vale": v, "i_pico": i_pico, "i_vale": i}
    return pior


def curva_por_trades(trades: list[dict], saldo_inicial: float) -> list[float]:
    """Sem fotos de patrimônio: a curva do SALDO, trade a trade, na ordem de fechamento (não vê o flutuante — menos fiel)."""
    s, out = saldo_inicial, [saldo_inicial]
    for t in sorted(trades, key=lambda x: x["fechou"]):
        s += t["lucro"]
        out.append(s)
    return out


def curva_sem_depositos(fotos: list[dict]) -> list[float]:
    """Curva de patrimônio com os depósitos/saques tirados (um depósito não é lucro; um saque não é prejuízo)."""
    acum, out = 0.0, []
    for f in sorted(fotos, key=lambda x: x["t"]):
        acum += f.get("depositos", 0) or 0
        out.append(f["patrimonio"] - acum)
    return out


def retornos_diarios(trades: list[dict], saldo_inicial: float) -> list[float]:
    """Retorno de cada dia com trade fechado sobre o saldo do começo do dia (dias sem trade não entram)."""
    por_dia = defaultdict(float)
    for t in trades:
        por_dia[int(t["fechou"] // DIA)] += t["lucro"]
    s, out = saldo_inicial, []
    for d in sorted(por_dia):
        if s > 0:
            out.append(por_dia[d] / s)
        s += por_dia[d]
    return out


def sharpe(retornos: list[float]) -> float | None:
    if len(retornos) < 10:
        return None
    m = sum(retornos) / len(retornos)
    var = sum((r - m) ** 2 for r in retornos) / (len(retornos) - 1)
    return None if var <= 0 else m / math.sqrt(var) * math.sqrt(252)


def consistencia(trades: list[dict]) -> float | None:
    """Fração de semanas positivas, com peso pelo tamanho da semana (uma semana enorme não esconde dez ruins)."""
    sem = defaultdict(float)
    for t in trades:
        sem[int(t["fechou"] // (7 * DIA))] += t["lucro"]
    if len(sem) < 4:
        return None
    tot = sum(abs(v) for v in sem.values())
    if tot <= 0:
        return None
    pos = sum(v for v in sem.values() if v > 0)
    frac = sum(1 for v in sem.values() if v > 0) / len(sem)
    return round(0.5 * frac + 0.5 * pos / tot, 4)


# ------------------------------------------------------------------------------------------------------------------ alertas
def sinal_martingale(trades: list[dict]) -> float:
    """Das perdas, quantas foram seguidas (no mesmo símbolo) por um trade com lote ≥ 1,5× maior: 0 = nunca, 1 = sempre."""
    por_sim = defaultdict(list)
    for t in trades:
        por_sim[t["simbolo"]].append(t)
    perdas = dobrou = 0
    for lst in por_sim.values():
        lst.sort(key=lambda x: x["abriu"])
        for a, b in zip(lst, lst[1:]):
            if a["lucro"] < 0:
                perdas += 1
                if b["volume"] >= a["volume"] * 1.5:
                    dobrou += 1
    return round(dobrou / perdas, 4) if perdas >= 5 else 0.0


def sinal_grade(trades: list[dict], min_juntas: int = 4) -> float:
    """Fração dos trades que ficaram abertos junto com 3+ outros no MESMO símbolo e lado, todos sem stop (grade sem proteção)."""
    if not trades:
        return 0.0
    grupos = defaultdict(list)
    for t in trades:
        grupos[(t["simbolo"], t["lado"])].append(t)
    marcados = set()
    for lst in grupos.values():
        lst = [t for t in lst if "sl" in t and not t.get("sl")]      # sem a chave "sl" = stop desconhecido (não conta)
        for t in lst:
            juntos = [o for o in lst if o["abriu"] <= t["abriu"] < o["fechou"]]
            if len(juntos) + 1 >= min_juntas:
                marcados.add(id(t))
                marcados.update(id(o) for o in juntos)
    return round(len(marcados) / len(trades), 4)


def sem_stop(trades: list[dict]) -> float:
    """Fração dos trades sem stop, contando só os que têm o stop conhecido (0.32.370: o histórico do cTrader não traz o SL
    dos negócios; esses trades vêm sem a chave "sl" e não contam como "sem stop")."""
    conh = [t for t in trades if "sl" in t]
    return round(sum(1 for t in conh if not t.get("sl")) / len(conh), 4) if conh else 0.0


# ------------------------------------------------------------------------------------------------------------------ nota
def _faixa(v, zero, cheio):
    if v is None:
        return 0.0
    if v == float("inf"):
        return 1.0
    return max(0.0, min(1.0, (v - zero) / (cheio - zero)))


def avaliar(trades: list[dict], saldo_inicial: float, fotos: list[dict] | None = None, conta_real: bool = True,
            agora: float | None = None) -> dict:
    """Métricas + elegibilidade + nota 0–100 de um mestre (docs/FOREX.md, seção 5)."""
    fech = [t for t in trades if t.get("fechou")]
    n = len(fech)
    if not n:
        return {"trades": 0, "dias": 0, "score": 0.0, "elegivel": False, "motivos": ["sem trades fechados"]}
    ini = min(t["abriu"] for t in fech)
    fim = agora or max(t["fechou"] for t in fech)
    dias = max(0, int((fim - ini) // DIA))
    lucro = sum(t["lucro"] for t in fech)
    curva = curva_sem_depositos(fotos) if fotos and len(fotos) >= 2 else curva_por_trades(fech, saldo_inicial)
    dd = max_drawdown(curva)
    pf = profit_factor(fech)
    sh = sharpe(retornos_diarios(fech, saldo_inicial))
    cons = consistencia(fech)
    mart, grade, ss = sinal_martingale(fech), sinal_grade(fech), sem_stop(fech)
    ret_pct = lucro / saldo_inicial * 100 if saldo_inicial > 0 else 0.0
    anos = max(dias, 1) / 365
    ret_ano = ((1 + ret_pct / 100) ** (1 / anos) - 1) * 100 if ret_pct > -100 else -100.0
    calmar = ret_ano / dd["pct"] if dd["pct"] > 0 else (3.0 if ret_ano > 0 else 0.0)

    motivos = []
    if not conta_real:
        motivos.append("conta demo")
    if dias < MIN_DIAS:
        motivos.append(f"histórico curto ({dias} dias; mínimo {MIN_DIAS})")
    if n < MIN_TRADES:
        motivos.append(f"poucos trades ({n}; mínimo {MIN_TRADES})")
    if dd["pct"] > MAX_DD_PCT:
        motivos.append(f"drawdown de {dd['pct']:.1f}% (máximo {MAX_DD_PCT:.0f}%)")
    if mart >= MAX_MARTINGALE:
        motivos.append(f"sinal de martingale ({mart:.0%} das perdas seguidas de lote maior)")
    if grade >= MAX_GRADE:
        motivos.append(f"sinal de grade sem stop ({grade:.0%} dos trades)")
    if ss >= MAX_SEM_STOP:
        motivos.append(f"{ss:.0%} dos trades sem stop")
    if lucro <= 0:
        motivos.append("resultado total negativo")

    nota = (30 * _faixa(calmar, 0, 3.0) + 20 * _faixa(pf, 1.0, 2.5) + 20 * (cons or 0)
            + 15 * _faixa(sh, 0, 2.0) + 15 * _faixa(dias, MIN_DIAS, 365) - 40 * mart - 40 * grade)
    nota = round(max(0.0, min(100.0, nota)), 2)
    return {
        "trades": n, "dias": dias, "lucro": round(lucro, 2), "retorno_pct": round(ret_pct, 2), "retorno_ano_pct": round(ret_ano, 2),
        "mdd_pct": round(dd["pct"], 2), "profit_factor": None if pf is None else (round(pf, 3) if pf != float("inf") else None),
        "sharpe": None if sh is None else round(sh, 3), "consistencia": cons, "martingale": mart, "grade": grade, "sem_stop": ss,
        "acerto_pct": round(sum(1 for t in fech if t["lucro"] > 0) / n * 100, 1), "score": nota, "elegivel": not motivos,
        "motivos": motivos, "curva_fonte": "patrimônio" if fotos and len(fotos) >= 2 else "saldo pelos trades",
    }


def ranking(mestres: list[dict]) -> list[dict]:
    """mestres = [{"id", "apelido", "trades", "saldo_inicial", "fotos", "conta_real"}] → ordenado: elegíveis primeiro, maior nota."""
    out = []
    for m in mestres:
        r = avaliar(m.get("trades") or [], m.get("saldo_inicial") or 0, m.get("fotos"), bool(m.get("conta_real", True)))
        out.append({"id": m.get("id"), "apelido": m.get("apelido"), "plataforma": m.get("plataforma"), **r})
    out.sort(key=lambda r: (not r["elegivel"], -r["score"]))
    return out
