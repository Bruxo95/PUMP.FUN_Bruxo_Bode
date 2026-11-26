"""Períodos do BOOST (0.32.459, pedido do dono em 2026-11-25): cada dia é um período numerado (01, 02, 03…), contado a partir do
primeiro trade fechado do BOOST. O período fecha à meia-noite (horário de Berlim, o mesmo dos outros relatórios) e fica no histórico.
Nada é guardado à parte: os períodos saem dos trades fechados da conta, que já ficam no banco, então o histórico não se perde.
Só mede: nada aqui compra, vende ou muda configuração.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

from .auto_trades import SUSPECT_PCT
from .daily import TZ
from .resultstudy import ts

ABA = "BOOST da migração"
MAX_PERIODOS = 120
EVITAR_TRADES = 5          # 0.32.477: base mínima para o resumo geral mandar ficar de fora de uma hora
EVITAR_DIAS = 3
SEMPRE_DIAS = 2


def _dia(t: float):
    return datetime.fromtimestamp(t, TZ).date()


def _t0(d) -> float:
    return datetime(d.year, d.month, d.day, tzinfo=TZ).timestamp()


def _open(t: dict) -> float | None:
    try:
        return datetime.fromisoformat(str(t.get("opened_at")).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def faixas(horas) -> list[list[int]]:
    """Horas soltas viram faixas seguidas: [0, 1, 5] → [[0, 2], [5, 6]] (o fim é a hora em que a faixa termina)."""
    out: list[list[int]] = []
    for h in sorted(horas):
        if out and out[-1][1] == h:
            out[-1][1] = h + 1
        else:
            out.append([h, h + 1])
    return out


def horarios(L: list, geral: bool = False) -> dict | None:
    """0.32.477 (pedido do dono, 27/11): em que hora do dia o BOOST ganha e em que hora perde, pela hora em que a COMPRA entrou
    (Berlim). `L` = [(fechou, trade)]. Só mede: nada aqui bloqueia compra nem muda configuração.
    "Sempre perda": num período, hora sem nenhum ganho; no geral, hora no prejuízo em todos os dias em que teve trade (2+ dias).
    "Não participar": num período, hora que fechou no prejuízo; no geral só com base mínima (EVITAR_TRADES trades em EVITAR_DIAS
    dias, prejuízo na soma e em pelo menos 2 de cada 3 dias). Prejuízo sem essa base fica em "observar"."""
    if not L:
        return None
    H: dict = {}
    for c, t in L:
        o = _open(t)
        d = datetime.fromtimestamp(c if o is None else o, TZ)
        s = float(t.get("pnl_sol") or 0)
        x = H.setdefault(d.hour, {"hora": d.hour, "trades": 0, "ganhos": 0, "saldo_sol": 0.0, "_dias": {}})
        x["trades"] += 1
        x["ganhos"] += s > 0
        x["saldo_sol"] += s
        x["_dias"][d.date()] = x["_dias"].get(d.date(), 0.0) + s
    horas = []
    for h in sorted(H):
        x = H[h]
        dias = x.pop("_dias")
        x.update(saldo_sol=round(x["saldo_sol"], 6), perdas=x["trades"] - x["ganhos"], acerto=round(x["ganhos"] / x["trades"] * 100),
                 dias=len(dias), dias_neg=sum(1 for v in dias.values() if v < 0))
        horas.append(x)
    ordem = sorted(horas, key=lambda x: (-x["saldo_sol"], -x["acerto"], x["hora"]))          # da melhor para a pior
    if geral:
        sempre = [x for x in horas if x["dias"] >= SEMPRE_DIAS and x["dias_neg"] == x["dias"]]
        evitar = [x for x in horas if x["saldo_sol"] < 0 and x["trades"] >= EVITAR_TRADES and x["dias"] >= EVITAR_DIAS
                  and x["dias_neg"] * 3 >= x["dias"] * 2]
    else:
        sempre = [x for x in horas if not x["ganhos"]]
        evitar = [x for x in horas if x["saldo_sol"] < 0]
    fora = {x["hora"] for x in evitar}
    total = sum(x["saldo_sol"] for x in horas)
    perdido = sum(x["saldo_sol"] for x in evitar)
    return {
        "horas": horas, "trades": sum(x["trades"] for x in horas), "total_sol": round(total, 6),
        "media_hora_sol": round(total / len(horas), 6),
        "melhor": ordem[0], "pior": ordem[-1] if len(ordem) > 1 else None,
        "medio": ordem[len(ordem) // 2] if len(ordem) > 2 else None,                          # a do meio da fila
        "lucro": [x for x in ordem if x["saldo_sol"] > 0], "sempre_perda": sempre,
        "evitar": faixas(fora), "evitar_trades": sum(x["trades"] for x in evitar), "evitar_ganhos": sum(x["ganhos"] for x in evitar),
        "evitar_sol": round(perdido, 6), "sem_evitar_sol": round(total - perdido, 6),
        "observar": [x for x in horas if geral and x["saldo_sol"] < 0 and x["hora"] not in fora],
        "regra": {"trades": EVITAR_TRADES, "dias": EVITAR_DIAS} if geral else None,
    }


def build(trades: list[dict], aba_of, now: float | None = None, since: float | None = None, conta=None) -> dict:
    """`trades` = todos os trades fechados de UMA carteira (fictícia ou real) da conta. Devolve os períodos do mais novo para o mais
    antigo. `antes_sol` = resultado de todos os trades (qualquer aba) fechados antes do período: serve para a carteira inicial."""
    now = time.time() if now is None else now
    conta = conta or (lambda _t: True)           # 0.32.465: carteira fictícia recomeçada — o saldo conta só desde o recomeço
    todos = []
    for t in trades:
        c = ts(t)
        if c is None or float(t.get("pnl_pct") or 0) >= SUSPECT_PCT:         # ganho falso (preço errado) fica fora
            continue
        todos.append((c, t))
    todos.sort(key=lambda x: x[0])
    boost = [(c, t) for c, t in todos if aba_of(t) == ABA]
    if not boost:
        return {"periodos": [], "atual": None, "total_sol": round(sum(float(t.get("pnl_sol") or 0) for _, t in todos), 6), "tz": "Berlim"}
    d0, d1 = _dia(boost[0][0]), _dia(now)
    n_dias = (d1 - d0).days + 1
    por_dia: dict = {}
    for c, t in boost:
        por_dia.setdefault(_dia(c), []).append((c, t))
    out = []
    for i in range(n_dias):
        d = d0 + timedelta(days=i)
        ini, fim = _t0(d), _t0(d + timedelta(days=1))
        L = por_dia.get(d, [])
        if i == 0 and L:                                                     # o período 01 começa na abertura do primeiro trade
            o = _open(L[0][1])
            if o is not None and o < ini + 86400:
                ini = min(o, L[0][0])
        antes = sum(float(t.get("pnl_sol") or 0) for c, t in todos if c < _t0(d) and conta(t))
        g = [float(t.get("pnl_sol") or 0) for _, t in L]
        pcts = [float(t.get("pnl_pct") or 0) for _, t in L]
        inv = sum(float(t.get("sol_in") or 0) for _, t in L)
        ganhos = [p for p, s in zip(pcts, g) if s > 0]
        perdas = [p for p, s in zip(pcts, g) if s <= 0]
        cum, serie = 0.0, []
        for (c, t), s, pct in zip(L, g, pcts):
            cum += s                                  # 0.32.469: [fechou, acumulado, resultado, moeda, %] de todos os trades (dicas da tela)
            serie.append([round(c, 1), round(cum, 6), round(s, 6), str(t.get("symbol") or "")[:24], round(pct, 2)])
        lista = [{"symbol": t.get("symbol"), "mint": t.get("mint"), "pnl_sol": round(s, 6), "pnl_pct": round(p, 2), "closed": c,
                  "reason": str(t.get("reason") or "")[:90]} for (c, t), s, p in zip(L, g, pcts)]
        mel = max(L, key=lambda x: float(x[1].get("pnl_sol") or 0))[1] if L else None
        pio = min(L, key=lambda x: float(x[1].get("pnl_sol") or 0))[1] if L else None
        out.append({
            "n": i + 1, "rotulo": f"{i + 1:02d}", "dia": d.isoformat(), "ini": ini, "fim": fim, "fechado": now >= fim,
            "trades": len(L), "ganhos": len(ganhos), "perdas": len(perdas),
            "acerto": round(len(ganhos) / len(L) * 100) if L else None,
            "saldo_sol": round(sum(g), 6), "investido_sol": round(inv, 6),
            "pct_sobre_investido": round(sum(g) / inv * 100, 2) if inv else None,
            "pct_ganhos_soma": round(sum(ganhos), 2), "pct_perdas_soma": round(sum(perdas), 2),
            "ganhos_sol": round(sum(x for x in g if x > 0), 6), "perdas_sol": round(sum(x for x in g if x <= 0), 6),
            "melhor": {"symbol": mel.get("symbol"), "sol": mel.get("pnl_sol"), "pct": mel.get("pnl_pct")} if mel else None,
            "pior": {"symbol": pio.get("symbol"), "sol": pio.get("pnl_sol"), "pct": pio.get("pnl_pct")} if pio else None,
            "antes_sol": round(antes, 6), "serie": serie, "lista": lista[-60:], "horarios": horarios(L),
            "saldo_carteira_sol": round(sum(s for (_c, t), s in zip(L, g) if conta(t)), 6),
            "antes_do_recomeco": bool(since and fim <= since), "recomecou_em": since if since and ini <= since < fim else None,
        })
    out.reverse()
    return {"periodos": out[:MAX_PERIODOS], "atual": out[0]["n"], "total_sol": round(sum(float(t.get("pnl_sol") or 0) for _, t in todos), 6),
            "horarios": horarios(boost, geral=True), "tz": "Berlim"}
