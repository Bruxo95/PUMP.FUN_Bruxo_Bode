"""Histórico de cada trader copiado (0.32.163, pedido do dono em 2026-11-02): tudo o que a conta copiou de cada carteira —
trades, acerto, quanto ganhou e perdeu, por aba e cada trade —, mais o que o ranking da Solana Tracker diz do próprio trader
quando ele aparece lá. `hub.th_save` guarda um resumo por trader de hora em hora (`trader_history`), que fica mesmo depois
de zerar a carteira fictícia. Só mede: nada aqui compra, vende ou muda configuração.
"""
from __future__ import annotations

from datetime import datetime

from .auto_trades import SUSPECT_PCT
from .daily import TZ
from .resultstudy import ts

MAX_TRADES = 2000
LB_DIAS = 60
LB_KEYS = ("rank", "name", "realized_usd", "roi", "winrate", "trades", "days_active")


def _ts_open(t: dict) -> float | None:
    v = t.get("open_t")
    if isinstance(v, (int, float)) and v > 0:
        return float(v)
    try:
        return datetime.fromisoformat(str(t.get("opened_at")).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def falso(t: dict) -> bool:
    """Ganho falso (preço lido errado, +1.900% ou mais): fica na lista, fora das contas."""
    return float(t.get("pnl_pct") or 0) >= SUSPECT_PCT


def _novo() -> dict:
    return {"trades": 0, "ganhos": 0, "perdas": 0, "saldo_sol": 0.0, "investido_sol": 0.0, "ganhos_sol": 0.0, "perdas_sol": 0.0, "falsos": 0}


def _soma(g: dict, t: dict) -> None:
    if falso(t):
        g["falsos"] += 1
        return
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


def _fim(g: dict) -> dict:
    out = {k: (round(v, 6) if isinstance(v, float) else v) for k, v in g.items()}
    out["acerto"] = round(g["ganhos"] / g["trades"] * 100) if g["trades"] else None
    out["pct"] = round(g["saldo_sol"] / g["investido_sol"] * 100, 2) if g["investido_sol"] else None
    return out


def lb_map(leaderboard: list[dict] | None) -> dict:
    """O que o ranking diz de cada carteira agora (nome, posição, acerto, lucro realizado)."""
    return {r["wallet"]: {k: r.get(k) for k in LB_KEYS} for r in (leaderboard or []) if r.get("wallet")}


def _base(L: list[dict], aba_of) -> dict:
    g, abas, dias, ini, fim = _novo(), {}, set(), None, None
    for t in L:
        _soma(g, t)
        a = aba_of(t)
        abas[a] = abas.get(a, 0) + 1
        c, o = ts(t), _ts_open(t)
        if c:
            dias.add(datetime.fromtimestamp(c, TZ).date().isoformat())
            fim = c if fim is None else max(fim, c)
        o = o or c
        if o:
            ini = o if ini is None else min(ini, o)
    ok = sorted((t for t in L if not falso(t)), key=lambda t: float(t.get("pnl_sol") or 0))
    pick = lambda t: {"symbol": t.get("symbol"), "mint": t.get("mint"), "sol": t.get("pnl_sol"), "pct": t.get("pnl_pct")} if t else None
    return {**_fim(g), "abas": dict(sorted(abas.items(), key=lambda kv: -kv[1])), "dias": len(dias), "primeiro": ini, "ultimo": fim,
            "melhor": pick(ok[-1] if ok else None), "pior": pick(ok[0] if ok else None)}


def resumo(trades: list[dict], aba_of, names: dict | None = None, lb: dict | None = None) -> list[dict]:
    """Uma linha por trader copiado (a carteira "manual" não é trader), do maior resultado para o menor."""
    names, lb = names or {}, lb or {}
    g: dict[str, list] = {}
    for t in trades:
        w = t.get("wallet")
        if w and w != "manual":
            g.setdefault(w, []).append(t)
    out = [{"wallet": w, "nome": names.get(w) or (lb.get(w) or {}).get("name"), "ranking": lb.get(w), **_base(L, aba_of)} for w, L in g.items()]
    return sorted(out, key=lambda r: -r["saldo_sol"])


def _item(t: dict, aba_of) -> dict:
    return {"id": t.get("id"), "symbol": t.get("symbol"), "mint": t.get("mint"), "opened_at": t.get("opened_at"), "closed_at": t.get("closed_at"),
            "sol_in": t.get("sol_in"), "pnl_sol": t.get("pnl_sol"), "pnl_pct": t.get("pnl_pct"), "reason": t.get("reason"), "aba": aba_of(t),
            "hold_s": t.get("hold_s"), "entrou_porque": t.get("entrou_porque"), "falso": falso(t)}


def detalhe(trades: list[dict], wallet: str, aba_of, names: dict | None = None, lb: dict | None = None,
            positions: list[dict] | None = None) -> dict:
    """Tudo o que a conta copiou desta carteira, na fictícia e na real: resumo, por dia, abertas agora e cada trade (o mais novo
    primeiro)."""
    names, lb = names or {}, lb or {}
    out = {"wallet": wallet, "nome": names.get(wallet) or (lb.get(wallet) or {}).get("name"), "ranking": lb.get(wallet)}
    for nome, real in (("ficticia", False), ("real", True)):
        L = [t for t in trades if t.get("wallet") == wallet and bool(t.get("real")) == real]
        L.sort(key=lambda t: ts(t) or 0, reverse=True)
        dia: dict[str, dict] = {}
        for t in L:
            c = ts(t)
            if c is None or falso(t):
                continue
            d = dia.setdefault(datetime.fromtimestamp(c, TZ).date().isoformat(), {"trades": 0, "saldo_sol": 0.0})
            d["trades"] += 1
            d["saldo_sol"] = round(d["saldo_sol"] + float(t.get("pnl_sol") or 0), 6)
        P = [p for p in (positions or []) if p.get("wallet") == wallet and bool(p.get("real")) == real]
        out[nome] = {**_base(L, aba_of), "por_dia": [{"dia": k, **v} for k, v in sorted(dia.items(), reverse=True)],
                     "trades_lista": [_item(t, aba_of) for t in L[:MAX_TRADES]], "total_lista": len(L),
                     "abertas": [{"id": p.get("id"), "symbol": p.get("symbol"), "mint": p.get("mint"), "opened_at": p.get("opened_at"),
                                  "sol_in": p.get("sol_in"), "chg_pct": p.get("chg_pct"), "aba": aba_of(p)} for p in P]}
    return out


def guardar(row: dict, antes: dict | None, hoje: str) -> dict:
    """O que vai para `trader_history`: o resumo de agora, o ranking mais recente que já se viu e uma foto do ranking por dia
    (até 60 dias), para acompanhar o próprio trader ao longo do tempo."""
    antes = antes or {}
    rk = row.get("ranking") or antes.get("ranking")
    dias = dict(antes.get("ranking_dias") or {})
    if row.get("ranking"):
        dias[hoje] = {k: row["ranking"].get(k) for k in ("rank", "realized_usd", "winrate", "trades")}
    dias = dict(sorted(dias.items())[-LB_DIAS:])
    return {**row, "ranking": rk, "ranking_dias": dias, "nome": row.get("nome") or antes.get("nome")}
