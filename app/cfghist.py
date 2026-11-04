"""Histórico da configuração de cada conta (0.32.199, pedido do dono em 04/11/2026: "se eu aplicar a do Bruxo e depois
quiser voltar", com um botão para voltar à versão X). Só as contas: quem grava e aplica é o hub."""
from __future__ import annotations

SKIP = {"pump_real_enabled"}       # ligar a REAL nunca entra no histórico: só a chave da tela liga
TELA = "você mudou na tela"
# 0.32.206 (pedido do dono): aplicar a configuração da FICTÍCIA na REAL vira uma versão, e dá para voltar.
# Só estas opções da REAL têm par na FICTÍCIA; desfazer (hub.real_from_sim_undo) mexe só nesses valores, nunca liga a REAL.
REAL_DA_FICTICIA = "aplicou a configuração da FICTÍCIA na REAL"
SIM2REAL = (("pump_copy_sol", "pump_real_max_sol"), ("pump_max_open", "pump_real_max_open"), ("pump_copy_other", "pump_copy_other_real"))
VOLTA_REAL = frozenset(r for _, r in SIM2REAL)
JUNTA_S = 600                      # mudanças seguidas na tela, em até 10 min, viram uma versão só


def snap(d: dict) -> dict:
    return {k: v for k, v in d.items() if k not in SKIP}


def diff(a: dict, b: dict) -> list[dict]:
    return [{"k": k, "de": a.get(k), "para": b.get(k)} for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)]
