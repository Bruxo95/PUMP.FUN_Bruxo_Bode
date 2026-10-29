"""0.32.71 — saúde das chaves da Solana Tracker (só em memória; nunca guarda nem mostra a chave em si).

Caso do dono (29/10 22:03): a chave do sistema tinha créditos, mas o ranking de todos vinha com "Insufficient credits"
porque o monitor usava a chave PESSOAL de outra conta (sem créditos) para a consulta compartilhada. Agora a chave que
responde "Insufficient credits" fica de fora por 1 h e o robô usa a próxima (outra pessoal ou a do sistema)."""
import hashlib
import time

DEAD_S = 3600
_dead: dict[str, float] = {}


def _h(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def no_credits(text) -> bool:
    return "insufficient credits" in str(text or "").lower()


def mark_dead(key: str, secs: float = DEAD_S) -> None:
    if key:
        _dead[_h(key)] = time.time() + secs


def clear(key: str) -> None:
    if key:
        _dead.pop(_h(key), None)


def is_dead(key: str) -> bool:
    return bool(key) and _dead.get(_h(key), 0) > time.time()


def pick(keys) -> str:
    """Primeira chave viva da lista (sem repetir); se todas estão sem créditos, a primeira (para o erro aparecer)."""
    ks = [k for k in dict.fromkeys(k for k in keys if k)]
    return next((k for k in ks if not is_dead(k)), ks[0] if ks else "")


def reset() -> None:
    _dead.clear()
