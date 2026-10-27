"""Base geral — o "cérebro" do robô (0.31.71, pedido do dono em 2026-10-27).

Junta num lugar o que o sistema aprendeu com TODAS as contas: as faixas do "aprender com os erros" (app/autolearn.py) e
as regras de saída das Estratégias fantasma (base geral, hub.ghosts_merged). Calcula a MATURIDADE da base (quanto de dado
ela já tem para decidir com confiança — não é chance de ganhar), o que está perto de acontecer e o que mudou desde a última
foto (vira o log do que foi aprendido). Só cálculo; quem grava as fotos e o log é o hub (tabelas base_snapshots/base_log).
"""
from __future__ import annotations

from datetime import datetime, timezone

CONF_N = 30            # operações por faixa para a faixa ser "confiável"
GHOST_N = 20           # trades por regra de saída (mesma base do Ajuste automático das automáticas)
GHOST_DAYS = 2.0       # dias de fantasmas para o Ajuste automático poder agir
HIST_DAYS = 7          # dias de histórico da meta
WEIGHTS = {"faixas": 0.4, "fantasmas": 0.3, "dias": 0.3}


def _ts(x) -> float | None:
    try:
        d = datetime.fromisoformat(str(x).replace("Z", "+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()
    except (TypeError, ValueError):
        return None


def history_days(trades: list[dict]) -> int:
    return len({datetime.fromtimestamp(t, timezone.utc).date() for x in trades if (t := _ts(x.get("closed_at")))})


def maturity(learned: dict, ghosts: dict, hist_days: int, ghost_days: float) -> dict:
    """0–100 por parte e no total, com o que falta em cada uma."""
    fx = learned.get("faixas") or []
    p_fx = sum(min(1.0, (x.get("n") or 0) / CONF_N) for x in fx) / len(fx) if fx else 0.0
    vs = [v for v in ghosts.get("variants") or []]
    p_gh = (sum(min(1.0, (v.get("trades") or 0) / GHOST_N) for v in vs) / len(vs) if vs else 0.0) * min(1.0, ghost_days / GHOST_DAYS)
    p_d = min(1.0, hist_days / HIST_DAYS)
    total = WEIGHTS["faixas"] * p_fx + WEIGHTS["fantasmas"] * p_gh + WEIGHTS["dias"] * p_d
    return {"total": round(total * 100, 1), "partes": [
        {"nome": f"Faixas com {CONF_N}+ operações", "pct": round(p_fx * 100, 1), "peso": WEIGHTS["faixas"],
         "falta": f"{sum(1 for x in fx if (x.get('n') or 0) < CONF_N)} de {len(fx)} faixas ainda com menos de {CONF_N} operações"},
        {"nome": f"Regras de saída com {GHOST_N}+ trades e {GHOST_DAYS:g} dias", "pct": round(p_gh * 100, 1), "peso": WEIGHTS["fantasmas"],
         "falta": f"{sum(1 for v in vs if (v.get('trades') or 0) < GHOST_N)} de {len(vs)} regras com menos de {GHOST_N} trades · "
                  f"{max(0.0, GHOST_DAYS - ghost_days) * 24:.0f} h para completar {GHOST_DAYS:g} dias"},
        {"nome": f"Dias de histórico (meta {HIST_DAYS})", "pct": round(p_d * 100, 1), "peso": WEIGHTS["dias"],
         "falta": f"{max(0, HIST_DAYS - hist_days)} dia(s) para a meta"}]}


def upcoming(learned: dict, ghosts: dict, ghost_days: float, min_n: int, max_wr: float, max_avg: float) -> list[str]:
    """O que está perto de acontecer: faixa perto de bloquear, regra perto de ter base, Ajuste automático."""
    out = []
    for x in learned.get("faixas") or []:
        if not x.get("bloqueada") and (x.get("n") or 0) < min_n and (x.get("acerto") or 0) < max_wr and (x.get("media_pct") or 0) < max_avg:
            out.append(f"{x['nome']} {x['faixa']}: está perdendo ({x['n']} operações, acerto {x['acerto'] * 100:.0f}%, média "
                       f"{x['media_pct']:+.1f}%). Com mais {min_n - x['n']} operação(ões) assim, será bloqueada.")
    vs = sorted([v for v in ghosts.get("variants") or [] if (v.get("trades") or 0) < GHOST_N], key=lambda v: -(v.get("trades") or 0))
    for v in vs[:3]:
        out.append(f"Regra \"{v['nome']}\": {v['trades']} de {GHOST_N} trades para entrar na conta do Ajuste automático.")
    if ghost_days < GHOST_DAYS:
        out.append(f"O Ajuste automático das automáticas só pode trocar a regra de saída daqui a {(GHOST_DAYS - ghost_days) * 24:.0f} h "
                   f"(precisa de {GHOST_DAYS:g} dias de fantasmas) e só nas contas sem a Execução real ligada.")
    best = next((v for v in ghosts.get("variants") or [] if v.get("id") == ghosts.get("best")), None)
    if best and (best.get("avg_sol") or 0) <= 0:
        out.append("Nenhuma regra de saída está no lucro por trade ainda: o problema principal está na ENTRADA (quais tokens comprar).")
    return out


def state_summary(learned: dict, ghosts: dict) -> dict:
    """O que vai na foto (para o gráfico e para comparar com a foto anterior)."""
    fx = learned.get("faixas") or []
    best = next((v for v in ghosts.get("variants") or [] if v.get("id") == ghosts.get("best")), None)
    return {"operacoes": learned.get("fechadas") or 0, "faixas": len(fx),
            "bloqueadas": sorted(f"{x['nome']} {x['faixa']}" for x in fx if x.get("bloqueada")),
            "aprendendo": sum(1 for x in fx if not x.get("bloqueada") and (x.get("n") or 0) < (learned.get("min_n") or 6)),
            "melhor_regra": best["nome"] if best else None, "melhor_por_trade": best.get("avg_sol") if best else None}


def diff(prev: dict | None, cur: dict) -> list[tuple[str, str]]:
    """(tipo, texto) do que mudou desde a foto anterior — vira o log do que foi aprendido."""
    if not prev:
        return [("inicio", f"Base geral começou a ser acompanhada: {cur['operacoes']} operações, {len(cur['bloqueadas'])} faixa(s) "
                           f"bloqueada(s), melhor regra de saída: {cur.get('melhor_regra') or '—'}.")]
    out = []
    a, b = set(prev.get("bloqueadas") or []), set(cur.get("bloqueadas") or [])
    out += [("bloqueou", f"Faixa bloqueada: {x} (o robô para de comprar aí)") for x in sorted(b - a)]
    out += [("liberou", f"Faixa liberada: {x} (melhorou)") for x in sorted(a - b)]
    if cur.get("melhor_regra") and cur.get("melhor_regra") != prev.get("melhor_regra"):
        out.append(("melhor_regra", f"Melhor regra de saída agora: {cur['melhor_regra']} "
                                    f"({(cur.get('melhor_por_trade') or 0):+.4f} SOL por trade)"))
    return out
