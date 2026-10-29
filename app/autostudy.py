"""Estudo automático de carteiras (0.31.13, pedido do dono em 2026-10-26: "deixar no modo automático procurando, ir
adicionando carteira sem precisar da minha ordem, ir aprendendo e melhorando para a próxima").

A cada 30 min, para cada admin com `pump_st_auto_on`:
1. Julga as carteiras que o próprio robô colocou no estudo (apelido começa com AUTO_TAG; as que o dono pôs nunca saem
   sozinhas). Usa o "se você tivesse copiado" (study.copy_sim, com atraso e taxas): com 5+ tokens fechados, "não
   compensa" sai e "compensa copiar" fica como aprovada; sem operações em 3 dias, ou ainda sem base em 7 dias, sai.
2. Preenche as vagas livres (até `pump_st_auto_max`, no máximo 3 por volta para poupar a chave da Solana Tracker) com
   candidatos do ranking da Solana Tracker e dos maiores traders, sem bandeira de robô/dev/corretora e sem ter sido
   descartados nos últimos 7 dias.
3. Aprende: cada decisão fica em `study_auto_log` com as características do candidato (fonte, faixa de acerto, faixa
   de trades). A taxa de aprovação por característica (com suavização, para poucos casos não mandarem) ordena os
   próximos candidatos: o tipo de carteira que costuma compensar entra primeiro.
Só estudo: nada aqui copia ou compra.
"""
from __future__ import annotations

AUTO_TAG = "auto · "
EVAL_MIN_N = 5                   # tokens fechados no "se você tivesse copiado" para julgar
STALE_S = 3 * 86400              # sem nenhuma operação vista em 3 dias → sai
NO_BASE_S = 7 * 86400            # ainda sem base para julgar em 7 dias → sai
BAN_S = 7 * 86400                # descartada não volta por 7 dias
PER_CYCLE = 3


def features(c: dict) -> dict:
    wr, n = c.get("winrate"), c.get("trades")
    return {"fonte": c.get("fonte") or "ranking",
            "acerto": None if wr is None else "acerto abaixo de 60%" if wr < 60 else "acerto 60 a 80%" if wr < 80 else "acerto 80% ou mais",
            "trades": None if n is None else "menos de 100 trades" if n < 100 else "100 a 500 trades" if n < 500 else "500 trades ou mais"}


def facts_features(fx: dict) -> dict:
    """0.32.9 (pedido do dono): idade, saldo, transações e tokens criados também viram características aprendidas."""
    a, u, n, c = fx.get("age_days"), fx.get("usd"), fx.get("txs"), fx.get("criados")
    return {"idade": None if a is None else "carteira com menos de 30 dias" if a < 30 and not fx.get("age_more")
            else "carteira de 30 a 180 dias" if a < 180 and not fx.get("age_more") else "carteira com 180 dias ou mais (ou muito ativa)",
            "saldo": None if u is None else "saldo abaixo de US$ 1 mil" if u < 1000 else "saldo US$ 1 mil a 10 mil" if u < 10000 else "saldo US$ 10 mil ou mais",
            "transacoes": None if n is None else "menos de 1.000 transações" if n < 1000 else "1.000 transações ou mais",
            "criador": None if c is None else "já criou token" if c else None}


def rates(log: list[dict]) -> list[dict]:
    """Taxa de aprovação por característica, das carteiras já julgadas (aprovou × descartou por não compensar)."""
    g: dict[tuple, list] = {}
    # 0.32.38: o resultado DE VERDADE de copiar também ensina (copiou_lucro conta como aprovação; parou/sugere parar, como descarte)
    good, bad = ("aprovou", "copiou_lucro"), ("descartou", "parou_de_copiar", "sugere_parar")
    for r in log:
        if r.get("acao") not in good + bad:
            continue
        for k, v in ((r.get("info") or {}).get("features") or {}).items():
            if v:
                g.setdefault((k, v), [0, 0])
                g[(k, v)][1] += 1
                g[(k, v)][0] += r["acao"] in good
    out = [{"chave": k, "valor": v, "aprovadas": ok, "julgadas": n, "taxa": round((ok + 1) / (n + 2), 3)}
           for (k, v), (ok, n) in g.items()]
    return sorted(out, key=lambda x: (-x["julgadas"], -x["taxa"]))


def score(c: dict, rt: list[dict]) -> float:
    m = {(x["chave"], x["valor"]): x["taxa"] for x in rt}
    vals = [m.get((k, v), 0.5) for k, v in features(c).items() if v]
    return sum(vals) / len(vals) if vals else 0.5


def candidates(pool: list[dict], skip: set, rt: list[dict]) -> list[dict]:
    best: dict[str, dict] = {}
    for c in pool:
        w = c.get("wallet")
        if not w or w in skip or c.get("base_flags"):
            continue
        if w not in best or (c.get("realized_usd") or 0) > (best[w].get("realized_usd") or 0):
            best[w] = c
    out = [{**c, "nota": round(score(c, rt), 3)} for c in best.values()]
    return sorted(out, key=lambda c: (-c["nota"], -(c.get("realized_usd") or 0)))


def judge(added_t: float, summary: dict, now: float) -> tuple[str, str] | None:
    """('descartou' | 'aprovou', motivo) ou None (continua estudando)."""
    cp = summary.get("copy") or {}
    n = cp.get("n_30d") or 0
    if n >= EVAL_MIN_N:
        pnl = cp.get("pnl_30d") or 0
        wr = (cp.get("win_rate") or 0) * 100
        if cp.get("verdict") == "não compensa":
            return "descartou", f"não compensa copiar: {pnl:+.4f} SOL em {n} tokens (acerto copiando {wr:.0f}%)"
        if cp.get("verdict") == "compensa copiar":
            return "aprovou", f"compensa copiar: {pnl:+.4f} SOL em {n} tokens (acerto copiando {wr:.0f}%)"
        return None
    age = now - added_t
    if age >= STALE_S and not summary.get("trades_seen") and not summary.get("closed"):
        return "descartou", "nenhuma operação em 3 dias"
    if age >= NO_BASE_S:
        return "descartou", f"só {n} tokens fechados em 7 dias: pouco para estudar"
    return None
