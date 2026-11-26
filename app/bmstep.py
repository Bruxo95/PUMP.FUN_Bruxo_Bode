"""0.32.471 (pedido do dono, 26/11/2026): "mudar o valor depois de alguns trades" no BOOST.

Depois de N compras com o valor normal, a compra seguinte usa o valor de "depois de N" e a contagem recomeça. N é 3, 4 ou 5,
fixo, ou sorteado a cada rodada entre os marcados. Só funções puras: o estado é um dicionário salvo junto das opções da conta.

Estado: {"sig": regra que gerou a contagem, "n": compras normais da rodada, "alvo": N da rodada, "devido": [N de compras com
valor diferente que falharam e ainda precisam sair]}.
"""
from __future__ import annotations

import random

PASSOS = (3, 4, 5)


def allowed(cfg) -> list[int]:
    """Os N que valem agora. Vazio = rodízio desligado."""
    if not getattr(cfg, "pump_bm_step_on", False):
        return []
    mode = int(getattr(cfg, "pump_bm_step_mode", 3) or 0)
    if mode in PASSOS:
        return [mode]
    if mode == 0:                                        # misturar
        return [n for n in PASSOS if getattr(cfg, f"pump_bm_step_mix{n}", True)]
    return []


def _sig(cfg) -> str:
    return f"{int(getattr(cfg, 'pump_bm_step_mode', 3) or 0)}:{','.join(map(str, allowed(cfg)))}"


def sync(state: dict | None, cfg, rnd=random) -> dict | None:
    """Estado válido para a regra atual: None se desligado; contagem nova se ligou agora ou trocou o "quando mudar".
    Mudar só os valores em SOL não recomeça a contagem."""
    ok = allowed(cfg)
    if not ok:
        return None
    sig = _sig(cfg)
    if isinstance(state, dict) and state.get("sig") == sig and state.get("alvo") in ok:
        return state
    return {"sig": sig, "n": 0, "alvo": rnd.choice(ok), "devido": []}


def amount(cfg, passo: int | None) -> float:
    """Valor em SOL: o de "depois de N" (0 ou vazio = o mesmo valor normal)."""
    base = float(getattr(cfg, "pump_bm_sol", 0.05))
    if not passo:
        return base
    return float(getattr(cfg, f"pump_bm_step_sol{passo}", 0.0) or 0.0) or base


def peek(state: dict | None, cfg) -> tuple[float, dict | None]:
    """Valor da PRÓXIMA compra e o bilhete dela (None = rodízio desligado). Não anda a contagem."""
    if not state:
        return amount(cfg, None), None
    devido = state.get("devido") or []
    if devido:
        passo, esp = devido[0], True
    else:
        passo, esp = state["alvo"], int(state.get("n") or 0) >= state["alvo"]
    amt = amount(cfg, passo if esp else None)
    return amt, {"esp": esp, "passo": passo, "feitos": int(state.get("n") or 0), "sig": state["sig"], "sol": amt,
                 "devia": bool(devido)}


def take(state: dict, cfg, ticket: dict, rnd=random) -> None:
    """A compra entrou (ou foi enviada para a carteira REAL): anda a contagem."""
    if not state or state.get("sig") != ticket.get("sig"):
        return
    if ticket.get("devia"):
        if state.get("devido"):
            state["devido"].pop(0)
    elif ticket.get("esp"):
        state["n"], state["alvo"] = 0, rnd.choice(allowed(cfg) or [state["alvo"]])
    else:
        state["n"] = int(state.get("n") or 0) + 1


def giveback(state: dict | None, ticket: dict) -> bool:
    """A compra enviada NÃO saiu: ela não conta. A de valor diferente volta como a próxima; a normal sai da contagem."""
    if not state or state.get("sig") != ticket.get("sig"):
        return False
    if ticket.get("esp"):
        state.setdefault("devido", []).insert(0, ticket["passo"])
    else:
        state["n"] = int(state.get("n") or 0) - 1       # pode ficar negativo se a rodada já virou: a próxima ganha uma compra
    return True


def view(state: dict | None, cfg) -> dict | None:
    """Para a tela: em que ponto da rodada está e quanto vai na próxima."""
    if not state:
        return None
    amt, t = peek(state, cfg)
    return {"feitos": max(0, int(state.get("n") or 0)), "alvo": t["passo"], "especial": t["esp"], "prox_sol": amt,
            "sol_especial": amount(cfg, t["passo"])}
