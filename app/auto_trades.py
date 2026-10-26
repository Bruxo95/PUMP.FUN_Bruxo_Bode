"""Registro e resumo das automáticas. Cálculos puros, sem rede ou ordens."""
from __future__ import annotations

import copy
import math
from datetime import datetime, timezone


FOLLOW_S = {"15m": 900, "60m": 3600}
FOLLOW_TOLERANCE_S = 120  # primeira cotação fresca até 2 min após cada marco; nunca inventa a foto perdida


def _json_values(value):
    """Metadados externos não podem introduzir NaN/infinito em uma coluna jsonb."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): _json_values(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_values(v) for v in value]
    return copy.deepcopy(value) if value is None or isinstance(value, (str, int, bool)) else None


def number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError, OverflowError):
        return None


def ts(value):
    if value in (None, ""):
        return None
    numeric = number(value)
    if numeric is not None:
        return numeric
    try:
        value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return value.replace(tzinfo=timezone.utc).timestamp() if value.tzinfo is None else value.timestamp()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def iso(value):
    value = ts(value)
    if value is None:
        return None
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def operation_row(p: dict, previous: dict | None = None, closed: bool = False) -> dict:
    """Uma posição e seu trade final compartilham ID; preserva as fotos posteriores já gravadas."""
    row = copy.deepcopy(previous or {})
    info = _json_values(row.get("info") or {})
    info.update(_json_values(p.get("auto_info") or {}))
    opened = ts(p.get("open_t")) or ts(p.get("opened_at")) or ts(row.get("entrada_em"))
    row.update({"id": str(p["id"]), "origem": p.get("origem") or row.get("origem") or "explorar",
                "real": bool(p.get("real")), "mint": p["mint"], "symbol": p.get("symbol"),
                "entrada_em": iso(opened), "sol_in": number(p.get("sol_in")),
                "best_pct": number(p.get("best_pct")), "worst_pct": number(p.get("worst_pct")),
                "veredito": info.get("veredito") or info.get("verdict"), "chance": number(info.get("chance")),
                "depois": copy.deepcopy(row.get("depois") or {})})
    info["entry_price"] = number(p.get("price_in")) or info.get("entry_price")
    info["sells"] = _json_values(p.get("sells") or info.get("sells") or [])
    if p.get("tokens_left") is not None:
        info["tokens_left"] = number(p.get("tokens_left"))
        info["proceeds"] = number(p.get("proceeds"))
        info["price_now"] = number(p.get("price_now"))
        info["chg_pct"] = number(p.get("chg_pct"))
    if closed:
        exited = ts(p.get("closed_t")) or ts(p.get("closed_at"))
        row.update({"saida_em": iso(exited), "pnl_sol": number(p.get("pnl_sol")),
                    "pnl_pct": number(p.get("pnl_pct")), "motivo_saida": p.get("reason")})
        info.update({"exit_t": exited, "exit_price": number(p.get("exit_price")) or number(p.get("price_out"))})
    else:
        row.update({"saida_em": None, "pnl_sol": None, "pnl_pct": None, "motivo_saida": None})
    row["info"] = info
    row.pop("user_id", None)
    return row


def summary(rows: list[dict]) -> dict:
    closed = [row for row in rows if row.get("saida_em") and number(row.get("pnl_sol")) is not None]
    values = [number(row["pnl_sol"]) for row in closed]
    gains = sum(max(0.0, value) for value in values)
    losses = -sum(min(0.0, value) for value in values)
    return {"closed": len(closed), "pnl_sol": round(gains - losses, 8),
            "win_rate": sum(value > 0 for value in values) / len(closed) if closed else None,
            "profit_factor": round(gains / losses, 4) if losses else None,
            "gains_sol": round(gains, 8), "losses_sol": round(losses, 8),
            "profit_factor_unbounded": bool(gains > 0 and losses == 0)}


def readiness(rows: list[dict]) -> dict:
    simulated = [row for row in rows if not row.get("real") and row.get("saida_em")
                 and number(row.get("pnl_sol")) is not None]
    stats = summary(simulated)
    days = {datetime.fromtimestamp(at, timezone.utc).date() for row in simulated
            if (at := ts(row.get("entrada_em"))) is not None}
    enough_pf = stats["profit_factor_unbounded"] or (stats["profit_factor"] or 0) >= 1.3
    ok = stats["closed"] >= 100 and len(days) >= 7 and (stats["win_rate"] or 0) >= 0.45 and enough_pf
    return {"recommended": ok, "closed_sim": stats["closed"], "days_sim": len(days),
            "win_rate": stats["win_rate"], "profit_factor": stats["profit_factor"],
            "profit_factor_unbounded": stats["profit_factor_unbounded"],
            "reason": ("Critério mínimo de observação atingido; nenhuma execução real é ligada automaticamente."
                       if ok else "Ainda não recomendado para dinheiro real: exige 100 operações simuladas fechadas, "
                       "7 dias de operações, acerto de 45% e fator de lucro de 1,3 após taxas.")}


def follow_mints(rows: dict, now: float) -> set:
    return {r["mint"] for r in rows.values() if r.get("saida_em") and (r.get("info") or {}).get("exit_price")
            and (exited := ts(r.get("saida_em"))) is not None and 0 <= now - exited <= 3600 + FOLLOW_TOLERANCE_S
            and any(key not in (r.get("depois") or {}) for key in FOLLOW_S)}


def observe_after(rows: dict, tokens: dict, now: float) -> set:
    """Só a cotação fresca na janela do marco. Uma foto perdida fica N/D, não usa o preço de uma hora depois."""
    changed = set()
    for rid, row in rows.items():
        exited = ts(row.get("saida_em"))
        info = row.get("info") or {}
        px0 = number(info.get("exit_price"))
        if exited is None or not px0 or px0 <= 0:
            continue
        token = tokens.get(row["mint"]) or {}
        px, quoted = number(token.get("price")), ts(token.get("last_t"))
        for key, seconds in FOLLOW_S.items():
            if key in row.setdefault("depois", {}):
                continue
            deadline = exited + seconds
            if now > deadline + FOLLOW_TOLERANCE_S:
                row["depois"][key] = None
                changed.add(rid)
            elif deadline <= now and quoted is not None and deadline <= quoted <= now and px and px > 0:
                variation = number((px / px0 - 1) * 100)
                if variation is None:
                    continue
                row["depois"][key] = round(variation, 4)
                info.setdefault("depois_em", {})[key] = iso(quoted)
                row["info"] = info
                changed.add(rid)
    return changed


def api_item(row: dict, now: float) -> dict:
    out = copy.deepcopy(row)
    out.pop("user_id", None)
    start, end = ts(out.get("entrada_em")), ts(out.get("saida_em"))
    out["open"] = end is None
    out["duration_s"] = max(0.0, (end if end is not None else now) - start) if start else None
    if end is None:
        info = out.get("info") or {}
        out["pnl_pct"] = number(info.get("chg_pct"))
        out["partial_exits"] = info.get("sells") or []
    return out
