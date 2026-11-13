"""Aprendizado das posições (0.32.33, pedido do dono em 2026-10-29: "aprender se entrou na hora certa ou errada, relatório a
cada 15 min e quando sair ou fizer stop um relatório, alimentando a Base sozinho").

- Antes da entrada: com o histórico de preço que o monitor já tinha do token (só tokens acompanhados antes da compra), onde o
  preço de entrada ficou entre o mínimo e o máximo dos 15 min anteriores (0% = no fundo, 100% = no topo).
- Durante: uma foto a cada 15 min (ganho líquido, pico e pior queda até ali).
- Depois da saída: o preço 15, 30 e 60 min depois de vender. Subiu muito = saiu cedo; caiu = acertou a saída.
Só mede e sugere: nenhuma regra muda sozinha.
"""
from __future__ import annotations

SNAP_S = 900                       # foto a cada 15 min
AFTER_MIN = (15, 30, 60)           # minutos depois da saída
CEDO_PCT = 30.0                    # subiu 30%+ depois de vender = saiu cedo
ACERTOU_PCT = -15.0                # caiu 15%+ depois de vender = a saída acertou


def entry_context(hist: list, open_t: float, px: float | None) -> dict | None:
    """Onde a entrada ficou nos 15 min anteriores. `hist` = [(t, preço), …] do token."""
    if not px:
        return None
    pre = [p for t, p in hist if open_t - SNAP_S <= t <= open_t and p]
    if len(pre) < 3:
        return None
    lo, hi = min(pre), max(pre)
    pos = 50.0 if hi <= lo else max(0.0, min(100.0, (px - lo) / (hi - lo) * 100))
    return {"min": lo, "max": hi, "pos_pct": round(pos, 1), "subiu_antes_pct": round((px / lo - 1) * 100, 1) if lo else None,
            "n": len(pre)}


def entry_label(ctx: dict | None) -> str:
    if not ctx:
        return "sem dado (token não era acompanhado antes da compra)"
    p = ctx["pos_pct"]
    return "comprou perto do topo dos 15 min anteriores" if p >= 80 else "comprou perto do fundo" if p <= 20 else "comprou no meio da faixa"


def exit_label(after: dict, pnl_pct: float | None) -> str:
    """Saída comparada com o que o preço fez depois."""
    vals = [v for v in (after or {}).values() if v is not None]
    if not vals:
        return "sem dado depois da saída"
    best, worst = max(vals), min(vals)
    if best >= CEDO_PCT:
        return "saiu cedo (subiu depois)"
    if worst <= ACERTOU_PCT and best < 10:
        return "saída certa (caiu depois)"
    return "saída neutra (pouco mudou depois)"


def origin_of(t: dict) -> str:
    o = t.get("origem")
    if t.get("follow_of"):
        return "cópia de outra conta"
    if o == "explorar":
        return "Explorar (automática)"
    if o in ("barrado", "barrado_btn"):
        return "Barrado que subiu" + (" (automática)" if o == "barrado" else " (botão)")
    if o in ("base", "elite", "calls"):
        return {"base": "Base (automática)", "elite": "Maiores traders", "calls": "Calls"}[o]
    if t.get("eq"):
        return "Copiar igual"
    if t.get("wallet") == "manual" or t.get("manual"):
        return "botão Comprar"
    return "cópia de trader"


def exit_kind(reason: str | None) -> str:
    r = str(reason or "").lower()
    for k, nome in (("stop de ganho", "stop de ganho"), ("stop móvel", "stop móvel"), ("stop de perda", "stop de perda"), ("stop por tempo", "stop por tempo"),
                    ("tempo máximo", "tempo máximo"), ("alvo", "alvo"), ("venda em partes", "venda em partes"),
                    ("trader vendeu", "trader vendeu"), ("carteira vendeu", "carteira vendeu"), ("dev vendeu", "dev vendeu"),
                    ("gradua", "graduação"), ("manual", "você fechou"), ("espelho", "espelho")):
        if k in r:
            return nome
    return "outro"


def aggregate(rows: list[dict]) -> dict:
    """Junta as posições fechadas (já com o depois da saída) por origem e por tipo de saída, com sugestões."""
    def grp(key):
        g: dict = {}
        for r in rows:
            d = r.get("data") or r
            k = key(d)
            x = g.setdefault(k, {"nome": k, "n": 0, "ganhos": 0, "soma_pct": 0.0, "cedo": 0, "certa": 0, "com_depois": 0,
                                 "na_mesa": 0.0, "topo": 0, "com_antes": 0})
            x["n"] += 1
            x["ganhos"] += 1 if (d.get("pnl_pct") or 0) > 0 else 0
            x["soma_pct"] += float(d.get("pnl_pct") or 0)
            ex = d.get("saida") or ""
            if ex.startswith("saiu cedo"):
                x["cedo"] += 1
                x["na_mesa"] += max(v for v in (d.get("depois") or {}).values() if v is not None)
            if ex.startswith("saída certa"):
                x["certa"] += 1
            if not ex.startswith("sem dado"):
                x["com_depois"] += 1
            if d.get("antes"):
                x["com_antes"] += 1
                x["topo"] += 1 if d["antes"].get("pos_pct", 0) >= 80 else 0
        out = []
        for x in g.values():
            n = x["n"]
            out.append({"nome": x["nome"], "n": n, "acerto": round(x["ganhos"] / n * 100) if n else None,
                        "media_pct": round(x["soma_pct"] / n, 1) if n else None,
                        "saiu_cedo_pct": round(x["cedo"] / x["com_depois"] * 100) if x["com_depois"] else None,
                        "saida_certa_pct": round(x["certa"] / x["com_depois"] * 100) if x["com_depois"] else None,
                        "na_mesa_pct": round(x["na_mesa"] / x["cedo"], 1) if x["cedo"] else None,
                        "entrou_no_topo_pct": round(x["topo"] / x["com_antes"] * 100) if x["com_antes"] else None,
                        "com_antes": x["com_antes"], "com_depois": x["com_depois"]})
        return sorted(out, key=lambda y: -y["n"])
    por_origem, por_saida = grp(lambda d: d.get("origem_nome") or "?"), grp(lambda d: d.get("saida_tipo") or "outro")
    dicas = []
    for x in por_saida:
        if x["com_depois"] >= 8 and (x["saiu_cedo_pct"] or 0) >= 50:
            dicas.append(f"'{x['nome']}' saiu cedo em {x['saiu_cedo_pct']}% das vezes ({x['com_depois']} casos), deixando em média "
                         f"+{x['na_mesa_pct']}% na mesa: vale testar afrouxar essa saída.")
        if x["com_depois"] >= 8 and (x["saida_certa_pct"] or 0) >= 60:
            dicas.append(f"'{x['nome']}' acertou a saída em {x['saida_certa_pct']}% das vezes: está funcionando.")
    for x in por_origem:
        if x["com_antes"] >= 8 and (x["entrou_no_topo_pct"] or 0) >= 60:
            dicas.append(f"{x['nome']}: entrou perto do topo dos 15 min anteriores em {x['entrou_no_topo_pct']}% das vezes — entrada "
                         "tardia; vale testar um gatilho mais cedo ou esperar um recuo.")
    if not dicas:
        dicas.append("Ainda poucos casos para sugerir (precisa de 8+ posições com o depois medido em cada grupo).")
    return {"n": len(rows), "por_origem": por_origem, "por_saida": por_saida, "dicas": dicas}
