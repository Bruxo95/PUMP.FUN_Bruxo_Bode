"""Semana × fim de semana (0.32.161, pedido do dono em 2026-11-02): o resultado dos dias de semana (segunda a sexta) e dos
fins de semana (sábado e domingo) separados, no horário de Berlim, por aba e por trader. Cada bloco fechado é guardado no
banco (`week_results`) para comparar depois. Só mede: nada aqui compra, vende ou muda configuração.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

from .auto_trades import SUSPECT_PCT
from .daily import TZ
from .resultstudy import ts

DIAS = {"semana": 5, "fds": 2}
NOME = {"semana": "Dias de semana", "fds": "Fim de semana"}
MAX_BLOCOS = 16
MAX_TRADERS = 40


def bloco(t: float) -> dict:
    """Bloco (dias de semana ou fim de semana) do instante `t`, no horário de Berlim."""
    d = datetime.fromtimestamp(t, TZ)
    seg = d.date() - timedelta(days=d.weekday())
    fds = d.weekday() >= 5
    ini_d = seg + timedelta(days=5 if fds else 0)
    fim_d = seg + timedelta(days=7 if fds else 5)
    ini = datetime(ini_d.year, ini_d.month, ini_d.day, tzinfo=TZ)
    fim = datetime(fim_d.year, fim_d.month, fim_d.day, tzinfo=TZ)
    tipo = "fds" if fds else "semana"
    ult = fim_d - timedelta(days=1)
    rot = (f"sáb {ini_d:%d/%m} – dom {ult:%d/%m}" if fds else f"seg {ini_d:%d/%m} – sex {ult:%d/%m}")
    return {"key": f"{ini_d:%Y-%m-%d}-{tipo}", "tipo": tipo, "nome": NOME[tipo], "rotulo": rot,
            "ini": ini.timestamp(), "fim": fim.timestamp()}


def _soma() -> dict:
    return {"trades": 0, "ganhos": 0, "perdas": 0, "saldo_sol": 0.0, "investido_sol": 0.0, "ganhos_sol": 0.0, "perdas_sol": 0.0}


def _add(g: dict, t: dict) -> None:
    pnl = float(t.get("pnl_sol") or 0)
    g["trades"] += 1
    g["investido_sol"] += float(t.get("sol_in") or 0)
    g["saldo_sol"] += pnl
    if pnl > 0:
        g["ganhos"] += 1
        g["ganhos_sol"] += pnl
    else:
        g["perdas"] += 1
        g["perdas_sol"] += pnl


def _fim(g: dict, dias: float | None = None) -> dict:
    out = {k: (round(v, 6) if isinstance(v, float) else v) for k, v in g.items()}
    out["acerto"] = round(g["ganhos"] / g["trades"] * 100) if g["trades"] else None
    out["pct"] = round(g["saldo_sol"] / g["investido_sol"] * 100, 2) if g["investido_sol"] else None
    if dias:
        out["dias"] = dias
        out["por_dia_sol"] = round(g["saldo_sol"] / dias, 6)
    return out


def _closed(trades: list[dict]) -> list[tuple[dict, float]]:
    out = []
    for t in trades:
        c = ts(t)
        if c is None or float(t.get("pnl_pct") or 0) >= SUSPECT_PCT:      # ganho falso (preço errado) fica fora
            continue
        out.append((t, c))
    return out


def _traders(L: list[dict], names: dict) -> list[dict]:
    g: dict[str, dict] = {}
    for t in L:
        w = t.get("wallet")
        if not w or w == "manual":
            continue
        _add(g.setdefault(w, _soma()), t)
    rows = [{"wallet": w, "nome": names.get(w), **_fim(x)} for w, x in g.items()]
    return sorted(rows, key=lambda x: -x["saldo_sol"])[:MAX_TRADERS]


def blocos(trades: list[dict], aba_of, names: dict | None = None, now: float | None = None) -> list[dict]:
    """Os blocos com trade fechado, do mais novo para o mais antigo, com o resultado por aba e por trader."""
    now = time.time() if now is None else now
    names = names or {}
    grupos: dict[str, dict] = {}
    for t, c in _closed(trades):
        b = bloco(c)
        x = grupos.setdefault(b["key"], {**b, "_L": []})
        x["_L"].append(t)
    out = []
    for x in sorted(grupos.values(), key=lambda y: -y["ini"])[:MAX_BLOCOS]:
        L = x.pop("_L")
        tot, abas = _soma(), {}
        for t in L:
            _add(tot, t)
            _add(abas.setdefault(aba_of(t), _soma()), t)
        o = sorted(L, key=lambda t: float(t.get("pnl_sol") or 0))
        x.update(_fim(tot, DIAS[x["tipo"]]))
        x["fechado"] = now >= x["fim"]
        x["abas"] = sorted(({"aba": a, **_fim(g)} for a, g in abas.items()), key=lambda y: -y["saldo_sol"])
        x["traders"] = _traders(L, names)
        x["melhor"] = {"symbol": o[-1].get("symbol"), "mint": o[-1].get("mint"), "sol": o[-1].get("pnl_sol")}
        x["pior"] = {"symbol": o[0].get("symbol"), "mint": o[0].get("mint"), "sol": o[0].get("pnl_sol")}
        out.append(x)
    return out


def resumo(trades: list[dict], aba_of, names: dict | None = None) -> dict:
    """Todos os fins de semana × todos os dias de semana: total, acerto e média por dia (a semana tem 5 dias e o fim de
    semana 2, então a comparação justa é por dia), por aba e por trader."""
    names = names or {}
    L = {"semana": [], "fds": []}
    dias = {"semana": set(), "fds": set()}
    for t, c in _closed(trades):
        b = bloco(c)
        L[b["tipo"]].append(t)
        dias[b["tipo"]].add(datetime.fromtimestamp(c, TZ).date())
    out: dict = {}
    for tp in ("semana", "fds"):
        g = _soma()
        for t in L[tp]:
            _add(g, t)
        out[tp] = _fim(g, len(dias[tp]) or None)
    abas: dict[str, dict] = {}
    for tp in ("semana", "fds"):
        for t in L[tp]:
            _add(abas.setdefault(aba_of(t), {"semana": _soma(), "fds": _soma()})[tp], t)
    out["abas"] = sorted(({"aba": a, "semana": _fim(v["semana"]), "fds": _fim(v["fds"])} for a, v in abas.items()),
                         key=lambda y: -(y["semana"]["saldo_sol"] + y["fds"]["saldo_sol"]))
    tr: dict[str, dict] = {}
    for tp in ("semana", "fds"):
        for x in _traders(L[tp], names):
            tr.setdefault(x["wallet"], {"wallet": x["wallet"], "nome": x.get("nome"), "semana": None, "fds": None})[tp] = x
    out["traders"] = sorted(tr.values(), key=lambda y: -(((y["semana"] or {}).get("saldo_sol") or 0) + ((y["fds"] or {}).get("saldo_sol") or 0)))[:MAX_TRADERS]
    out.update(dias_horas(trades))                     # 0.32.166: por dia da semana e por hora do dia
    out["serie"] = serie(trades)                       # 0.32.166: dia a dia, com o acumulado
    return out


def por_aba(trades: list[dict], aba_of) -> dict:
    """Para os quadrados de Abas de trades: cada aba com o total dos fins de semana e dos dias de semana."""
    g: dict[str, dict] = {}
    for t, c in _closed(trades):
        _add(g.setdefault(aba_of(t), {"semana": _soma(), "fds": _soma()})[bloco(c)["tipo"]], t)
    return {a: {"semana": _fim(v["semana"]), "fds": _fim(v["fds"])} for a, v in g.items()}


# ------------------------------------------------------------------ dia da semana, hora do dia e dia a dia (0.32.166)
DIAS_NOME = ("Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo")


def _aberto(t: dict, fechado: float) -> float:
    """Hora em que a compra entrou (é quando o robô decide); sem ela, a do fechamento."""
    v = t.get("open_t")
    if isinstance(v, (int, float)) and v > 0:
        return float(v)
    try:
        return datetime.fromisoformat(str(t.get("opened_at")).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return fechado


def dias_horas(trades: list[dict]) -> dict:
    """0.32.166 (pedido do dono: "dividir por dia da semana e pelas horas do dia"): o resultado por dia da semana (com a média
    por dia, porque cada dia da semana aparece um número diferente de vezes) e por hora do dia, pela hora em que a compra entrou,
    no horário de Berlim."""
    dias, horas, datas = [_soma() for _ in range(7)], [_soma() for _ in range(24)], [set() for _ in range(7)]
    for t, c in _closed(trades):
        d = datetime.fromtimestamp(_aberto(t, c), TZ)
        _add(dias[d.weekday()], t)
        datas[d.weekday()].add(d.date())
        _add(horas[d.hour], t)
    return {"dias_semana": [{"dia": i, "nome": DIAS_NOME[i], "fds": i >= 5, **_fim(g, len(datas[i]) or None)} for i, g in enumerate(dias)],
            "horas": [{"hora": h, **_fim(g)} for h, g in enumerate(horas)]}


def serie(trades: list[dict]) -> list[dict]:
    """O resultado de cada dia (pelo fechamento) e o acumulado, do mais antigo ao mais novo: a linha do progresso."""
    g: dict = {}
    for t, c in _closed(trades):
        d = datetime.fromtimestamp(c, TZ).date()
        x = g.setdefault(d, _soma())
        _add(x, t)
        x["_d"] = d
    out, acc = [], 0.0
    for d in sorted(g):
        x = g[d]
        acc += x["saldo_sol"]
        out.append({"dia": d.isoformat(), "nome": DIAS_NOME[d.weekday()], "fds": d.weekday() >= 5, "acumulado_sol": round(acc, 6),
                    **_fim({k: v for k, v in x.items() if k != "_d"})})
    return out
