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


class RingHandler(logging.Handler):
    """Últimos N registros do servidor (já com os segredos mascarados) para a tela de Logs do admin."""

    def __init__(self, size: int = 3000):
        super().__init__(level=logging.INFO)
        from collections import deque
        import threading
        self.buf = deque(maxlen=size)
        self._id = 0
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.split(".")[0].rstrip("0123456789") in ("httpx", "httpcore", "websockets", "asyncio", "uvicorn") and record.levelno < logging.WARNING:
            return
        try:
            msg = redact(record.getMessage())
            if record.exc_info and record.levelno >= logging.ERROR:
                msg += "\n" + redact(logging.Formatter().formatException(record.exc_info))[-1500:]
        except Exception:
            return
        with self._lock:
            self._id += 1
            self.buf.append({"id": self._id, "t": record.created, "level": record.levelname, "name": record.name,
                             "msg": msg[:2000]})

    def since(self, after: int = 0, level: str = "INFO", q: str = "", limit: int = 400) -> list[dict]:
        lv = logging.getLevelName(level.upper()) if isinstance(logging.getLevelName(level.upper()), int) else 20
        q = (q or "").lower()
        with self._lock:
            rows = [r for r in self.buf if r["id"] > after and logging.getLevelName(r["level"]) >= lv
                    and (not q or q in r["msg"].lower() or q in r["name"].lower())]
        return rows[-limit:]

    def counts(self) -> dict:
        with self._lock:
            return {"warnings": sum(1 for r in self.buf if r["level"] == "WARNING"),
                    "errors": sum(1 for r in self.buf if r["level"] in ("ERROR", "CRITICAL")), "total": len(self.buf)}


RING: RingHandler | None = None


def ring() -> RingHandler:
    """Instala (uma vez) o buffer de logs no logger raiz e devolve ele."""
    global RING
    if RING is None:
        RING = RingHandler()
        RING.addFilter(RedactFilter())
        logging.getLogger().addHandler(RING)
        if logging.getLogger().level > logging.INFO or logging.getLogger().level == logging.NOTSET:
            logging.getLogger().setLevel(logging.INFO)
    return RING
