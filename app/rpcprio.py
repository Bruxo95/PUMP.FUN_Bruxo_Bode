"""0.32.395 (pedido do dono, 20/11: "quando a real estiver ligada a prioridade é da real… depois de 1 s a fictícia"):
fila de prioridade no RPC da Solana. Enquanto uma compra ou venda REAL está saindo (leitura de saldo, simulação, envio,
confirmação), as outras consultas ao RPC (monitor, fictícia, BOOST, vigia da carteira…) esperam; voltam 1 s depois que a
REAL termina. Nunca esperam mais que MAX_WAIT_S, para o resto do robô não parar. Só memória."""
from __future__ import annotations

import asyncio
import contextvars
import time
from contextlib import contextmanager

GAP_S = 1.0                    # o resto volta 1 s depois da última operação REAL
MAX_WAIT_S = 8.0               # nunca segura uma consulta por mais que isso
_real = contextvars.ContextVar("rpc_real", default=False)
state = {"ativas": 0, "ultima": 0.0, "esperas": 0, "espera_s": 0.0, "reais": 0}


def is_rpc(host: str) -> bool:
    h = (host or "").lower()
    return h.endswith("helius-rpc.com") or h == "api.mainnet-beta.solana.com" or h.startswith("solana-mainnet.") or "solana" in h and "rpc" in h


@contextmanager
def real_scope():
    """Tudo o que esta tarefa (e as que ela criar) pedir ao RPC aqui dentro é da REAL: passa na frente."""
    tok = _real.set(True)
    state["ativas"] += 1
    state["reais"] += 1
    try:
        yield
    finally:
        state["ativas"] = max(0, state["ativas"] - 1)
        state["ultima"] = time.monotonic()
        _real.reset(tok)


def is_real() -> bool:
    return _real.get()


def busy(now: float | None = None) -> bool:
    now = time.monotonic() if now is None else now
    return state["ativas"] > 0 or (state["ultima"] and now - state["ultima"] < GAP_S)


async def wait_low() -> float:
    """Consulta que não é da REAL: espera a REAL terminar + 1 s (no máximo MAX_WAIT_S). Devolve quanto esperou."""
    if _real.get() or not busy():
        return 0.0
    t0 = time.monotonic()
    while busy() and time.monotonic() - t0 < MAX_WAIT_S:
        await asyncio.sleep(0.1)
    w = time.monotonic() - t0
    state["esperas"] += 1
    state["espera_s"] += w
    return w


async def hook(request) -> None:
    """Gancho do httpx (pedido): consultas ao RPC da Solana que não são da REAL esperam a vez. Nunca falha a chamada."""
    try:
        if request.method == "POST" and is_rpc(request.url.host):
            await wait_low()
    except Exception:
        pass


def view() -> dict:
    return {"ativas": state["ativas"], "esperas": state["esperas"], "espera_media_s": round(state["espera_s"] / state["esperas"], 2)
            if state["esperas"] else 0.0, "operacoes_real": state["reais"]}


def reset() -> None:
    state.update(ativas=0, ultima=0.0, esperas=0, espera_s=0.0, reais=0)
