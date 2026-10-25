"""Chaves nunca aparecem em log (nem no do container/Portainer).

Todo valor secreto que o servidor descriptografa é registrado com add_secret(); o filtro troca esse valor por
*** em qualquer mensagem de log. Também mascara padrões comuns (api_key=..., Bearer ...).
"""
from __future__ import annotations

import logging
import re

SECRET = re.compile(r"(?i)((?:api[_-]?key|apikey|token|secret|password|passwd|authorization|bearer|private[_-]?key)"
                    r"[\"']?\s*[=:]\s*[\"']?(?:Bearer\s+)?|Bearer\s+)([^\s&\"',}]+)")
_SECRETS: set[str] = set()


def add_secret(value: str | None) -> None:
    """Valor que nunca pode aparecer em log (chave da carteira, chave de API, token do RPC…)."""
    if value and len(value) >= 8:
        _SECRETS.add(value)
        # RPCs que põem a chave na URL (?api-key=… ou no caminho): esconde também a parte da chave
        if "://" in value:
            if "?" in value:
                q = value.split("?", 1)[1]
                if len(q) >= 8:
                    _SECRETS.add(q)
            tail = value.rstrip("/").rsplit("/", 1)[-1]
            if value.count("/") > 2 and len(tail) >= 16:
                _SECRETS.add(tail)


def redact(text: str) -> str:
    text = str(text)
    for sec in sorted(_SECRETS, key=len, reverse=True):
        if sec in text:
            text = text.replace(sec, "***")
    return SECRET.sub(lambda m: m.group(1) + "***", text)


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            clean = redact(msg)
            if clean != msg:
                record.msg, record.args = clean, None
        except Exception:
            pass
        return True


def install() -> None:
    """Liga o filtro em todos os handlers do logger raiz (chamar depois do logging.basicConfig)."""
    f = RedactFilter()
    root = logging.getLogger()
    for h in root.handlers:
        h.addFilter(f)
    root.addFilter(f)
