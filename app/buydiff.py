"""Por que duas contas compraram moedas diferentes (0.32.167, pedido do dono).

Com a mesma configuração, as compras ainda mudam porque a LISTA de traders de cada conta é dela: lista manual, carteiras
aprovadas pelo estudo automático, Copiar igual, pausas (as do ajuste automático também) e banidos. Este módulo junta as
compras FICTÍCIAS das duas contas num período e diz, moeda a moeda, por que a outra conta não comprou. Só lê: não compra,
não vende e não muda opção nem lista de ninguém.
"""
from __future__ import annotations

import time
from datetime import datetime

LIMITE = 200


def _t(x) -> float | None:
    if not x:
        return None
    try:
        return datetime.fromisoformat(str(x).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def short(w: str) -> str:
    return f"{w[:4]}…{w[-4:]}" if w and len(w) > 10 else (w or "")


def opens(pf, since: float) -> dict[str, dict]:
    """Primeira compra FICTÍCIA de cada moeda aberta desde `since` (aberta ou já fechada)."""
    out: dict[str, dict] = {}
    for x in list(pf.positions()) + list(pf.trades(5000)):
        if x.get("real"):
            continue
        t = _t(x.get("opened_at"))
        m = x.get("mint")
        if not m or not t or t < since:
            continue
        if m in out and out[m]["t"] <= t:
            continue
        out[m] = {"mint": m, "symbol": x.get("symbol") or short(m), "t": t, "wallet": x.get("wallet"), "aba": pf.aba_of(x),
                  "aberta": "closed_at" not in x, "pnl_sol": x.get("pnl_sol"), "pnl_pct": x.get("pnl_pct")}
    return out


def why_not(other, item: dict) -> str:
    """Por que a conta `other` não comprou a moeda que a outra comprou."""
    m, w = item["mint"], item.get("wallet")
    seen = [x for x in other.__dict__.get("_copy_mint") or [] if x[2] == m]
    if seen:
        _t0, who, _m, out = seen[-1]
        if out == "copiou":
            return f"copiou a compra de {short(who)}, mas a posição foi desfeita ou abriu antes do período"
        return f"viu a compra de {short(who)} e não copiou: {out}"
    if item["aba"] == "Explorar":
        g = (getattr(other, "_ex_funnel", None) or {}).get(m)
        if g and g.get("why"):
            return "o Explorar desta conta barrou: " + str(g["why"])
        if g:
            return "o Explorar desta conta analisou o token e não chegou a comprar"
        return "o Explorar desta conta não analisou o token (sem preço recente na hora ou fora da lista dela)"
    if w and w != "manual":
        f = other.follow_info(w)
        if not f["segue"]:
            return "não copia este trader: " + f["por"]
        return "copia este trader, mas a compra não chegou nesta conta desde o último reinício do servidor"
    return f"entrada da aba {item['aba']}, que nesta conta não fez esta compra"


def traders(a, b) -> list[dict]:
    """Traders que só a conta `a` copia agora, com a origem e o motivo de `b` não copiar."""
    fb = set(b.followed)
    return [{"wallet": w, "fonte": a.follow_info(w)["por"], "por_que_nao": b.follow_info(w)["por"]}
            for w in a.followed if w not in fb]


def compare(a, b, horas: float, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    since = now - horas * 3600
    A, B = opens(a, since), opens(b, since)
    ambos = sorted(({**x, "outro": B[m]} for m, x in A.items() if m in B), key=lambda x: -x["t"])
    so_a = sorted(({**x, "por_que_nao": why_not(b, x)} for m, x in A.items() if m not in B), key=lambda x: -x["t"])
    so_b = sorted(({**x, "por_que_nao": why_not(a, x)} for m, x in B.items() if m not in A), key=lambda x: -x["t"])
    since_diag = [d[0][0] for e in (a, b) if (d := e.__dict__.get("_copy_mint"))]
    return {"horas": horas, "ambos": ambos[:LIMITE], "so_eu": so_a[:LIMITE], "so_outro": so_b[:LIMITE],
            "n": {"ambos": len(ambos), "so_eu": len(so_a), "so_outro": len(so_b)},
            "traders_so_eu": traders(a, b), "traders_so_outro": traders(b, a),
            "copiados": {"eu": len(a.followed), "outro": len(b.followed)},
            "diag_desde": max(since_diag) if since_diag else None}
