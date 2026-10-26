"""Aprender com os erros, sozinho (0.31.12, pedido do dono em 2026-10-26: "se der negativo, já ir aprendendo e
melhorando automaticamente; o importante é aprender com o erro").

Cada compra automática guarda os números do momento da entrada (`auto_info`: pressão, holders, curva, risco, variação
em 5 min, boost). Aqui as operações FECHADAS são agrupadas por faixa de cada número. Uma faixa com base mínima
(MIN_N fechadas), acerto baixo e resultado médio negativo depois das taxas vira "faixa bloqueada": a entrada
automática daquela origem para de entrar ali (opção `pump_ar_learn`, ligada por padrão, só aperta — nunca afrouxa um
filtro). Quando a faixa melhorar (novas operações de outras faixas não mudam isso; o bloqueio some se os números da
faixa voltarem a ficar bons), o bloqueio sai sozinho. Tudo é recalculado do histórico guardado, então vale depois de
reiniciar.
"""
from __future__ import annotations

MIN_N = 10
MAX_WR = 0.35                    # acerto abaixo disso…
MAX_AVG_PCT = -5.0               # …e resultado médio pior que isso → bloqueia

FEATURES = {
    "pressure": ("Pressão de compra", [(0, 60, "abaixo de 60%"), (60, 70, "60 a 70%"), (70, 80, "70 a 80%"), (80, 101, "80% ou mais")]),
    "holders": ("Holders", [(0, 100, "menos de 100"), (100, 200, "100 a 200"), (200, 500, "200 a 500"), (500, 1e12, "500 ou mais")]),
    "curve_pct": ("Curva", [(0, 60, "abaixo de 60%"), (60, 80, "60 a 80%"), (80, 90, "80 a 90%"), (90, 101, "90% ou mais")]),
    "chg_5m": ("Variação em 5 min", [(-1e9, 0, "caindo"), (0, 30, "0 a 30%"), (30, 80, "30 a 80%"), (80, 1e9, "mais de 80%")]),
    "risk": ("Risco", [(0, 4, "0 a 3"), (4, 7, "4 a 6"), (7, 11, "7 ou mais")]),
}


def _num(x):
    try:
        return float(x) if x is not None else None
    except (TypeError, ValueError):
        return None


def bucket(feature: str, value) -> str | None:
    if feature == "boost":
        if isinstance(value, dict):
            value = value.get("active")
        return None if value is None else ("Boost ON" if value else "Boost OFF")
    v = _num(value)
    if v is None:
        return None
    for lo, hi, name in FEATURES[feature][1]:
        if lo <= v < hi:
            return name
    return None


def label(feature: str) -> str:
    return "Boost" if feature == "boost" else FEATURES[feature][0]


def study(trades: list[dict], origem: str) -> dict:
    """Faixas das compras automáticas FECHADAS de uma origem (fictícia): n, acerto, média e se está bloqueada."""
    rows = [t for t in trades if t.get("origem") == origem and not t.get("real") and isinstance(t.get("auto_info"), dict)]
    out = []
    for f in list(FEATURES) + ["boost"]:
        g: dict[str, list] = {}
        for t in rows:
            b = bucket(f, t["auto_info"].get(f))
            if b:
                g.setdefault(b, []).append(t)
        for b, r in g.items():
            n = len(r)
            wr = sum(1 for t in r if (t.get("pnl_sol") or 0) > 0) / n
            avg = sum((t.get("pnl_pct") or 0) for t in r) / n
            pnl = sum(t.get("pnl_sol") or 0 for t in r)
            blocked = n >= MIN_N and wr < MAX_WR and avg < MAX_AVG_PCT
            out.append({"feature": f, "nome": label(f), "faixa": b, "n": n, "acerto": round(wr, 3), "media_pct": round(avg, 1),
                        "pnl_sol": round(pnl, 6), "bloqueada": blocked})
    out.sort(key=lambda x: (not x["bloqueada"], x["pnl_sol"]))
    quick = [t for t in rows if (t.get("pnl_sol") or 0) < 0 and (t.get("hold_s") or 1e9) <= 60]
    return {"origem": origem, "fechadas": len(rows), "faixas": out, "bloqueios": [x for x in out if x["bloqueada"]],
            "morte_rapida": len(quick), "min_n": MIN_N}


def blocked_reason(learned: dict, info: dict) -> str | None:
    """Motivo de não entrar, se o token cai numa faixa que o aprendizado bloqueou."""
    for x in learned.get("bloqueios") or []:
        if bucket(x["feature"], info.get(x["feature"])) == x["faixa"]:
            return (f"aprendi com os erros: {x['nome']} {x['faixa']} perdeu em {x['n']} operações "
                    f"(acerto {x['acerto'] * 100:.0f}%, média {x['media_pct']:+.0f}%)")
    return None
