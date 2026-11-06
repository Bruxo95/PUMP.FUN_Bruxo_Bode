"""Dormant: cofre das chaves privadas das carteiras (0.32.242, pedido do dono em 06/11/2026: "muito cuidado, estou guardando
chaves privadas, tem que estar bem segura").

Duas camadas, de propósito:
- por dentro, AES-256-GCM com uma chave tirada da SENHA DE COMPRA (scrypt). A senha não fica guardada em lugar nenhum: só quem
  digita abre a carteira. É o que protege se o banco E a APP_ENCRYPTION_KEY vazarem juntos, e se roubarem a sessão do Google;
- por fora, a mesma SecretBox das outras chaves do sistema (APP_ENCRYPTION_KEY, amarrada a usuário + rede).

As duas cifras ficam amarradas a usuário, rede e endereço: copiar a linha de uma conta ou rede para outra faz a abertura falhar.
scrypt com N=2^15, r=8, p=3: um dos conjuntos recomendados pela OWASP (cerca de 32 MB e 0,3 s por tentativa); quem chama roda em
thread para não travar o laço do servidor. Depois de esquecer a senha não há como recuperar: tira a carteira e cadastra de novo.
"""
from __future__ import annotations

import base64
import hashlib
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SCRYPT = {"n": 2 ** 15, "r": 8, "p": 3, "dklen": 32, "maxmem": 64 * 1024 * 1024}
SENHA_MIN, SENHA_MAX = 10, 200
PREFIXO = "dv1:"


class WrongPassword(Exception):
    """Senha de compra errada (ou o dado foi mexido: dá no mesmo, não abre)."""


def check_new_password(senha: str) -> str | None:
    """Motivo para recusar a senha nova; None = serve."""
    if not isinstance(senha, str) or not SENHA_MIN <= len(senha) <= SENHA_MAX:
        return f"a senha de compra precisa ter de {SENHA_MIN} a {SENHA_MAX} caracteres"
    if len(set(senha)) < 5:
        return "a senha de compra é fácil demais: use caracteres variados"
    return None


def _kdf(senha: str, salt: bytes) -> bytes:
    return hashlib.scrypt(senha.encode("utf-8"), salt=salt, **SCRYPT)


def _aad(user_id: str, chain: str, address: str) -> bytes:
    return f"{user_id}:{chain}:{address}".encode()


def _outer(chain: str) -> str:
    return "dormant:" + chain


def seal(box, user_id: str, chain: str, address: str, secret: str, senha: str) -> str:
    salt, nonce = os.urandom(16), os.urandom(12)
    ct = AESGCM(_kdf(senha, salt)).encrypt(nonce, secret.encode("utf-8"), _aad(user_id, chain, address))
    inner = PREFIXO + base64.b64encode(salt + nonce + ct).decode()
    return box.encrypt(user_id, _outer(chain), inner)


def unseal(box, user_id: str, chain: str, address: str, blob: str, senha: str) -> str:
    """A chave em texto, só para assinar agora. CryptoError = chave mestra diferente; WrongPassword = senha errada."""
    inner = box.decrypt(user_id, _outer(chain), blob)
    if not inner.startswith(PREFIXO):
        raise WrongPassword
    raw = base64.b64decode(inner[len(PREFIXO):])
    try:
        return AESGCM(_kdf(senha, raw[:16])).decrypt(raw[16:28], raw[28:], _aad(user_id, chain, address)).decode("utf-8")
    except (InvalidTag, ValueError):
        raise WrongPassword from None
