"""Criptografia das chaves pessoais: AES-256-GCM com a chave mestra APP_ENCRYPTION_KEY (só no .env da VPS).

- Sem a chave mestra, o que está no banco é inútil (nem o Supabase consegue abrir).
- Cada valor é "amarrado" ao usuário e ao nome da chave (dado associado): copiar a cifra de um usuário para
  outro, ou de um campo para outro, faz a abertura falhar.
- Formato gravado: "v1:" + base64(nonce de 12 bytes + texto cifrado + tag).

Gerar a chave mestra (uma vez):  python -c "import secrets,base64;print(base64.b64encode(secrets.token_bytes(32)).decode())"
"""
from __future__ import annotations

import base64
import binascii
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class CryptoError(Exception):
    pass


def load_master_key(raw: str) -> bytes:
    raw = (raw or "").strip()
    if not raw:
        raise CryptoError("APP_ENCRYPTION_KEY não configurada no .env")
    key = None
    try:
        key = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        pass
    if key is None or len(key) != 32:
        try:
            key = bytes.fromhex(raw)
        except ValueError:
            key = None
    if key is None or len(key) != 32:
        raise CryptoError("APP_ENCRYPTION_KEY precisa ter 32 bytes (base64 de 44 caracteres ou 64 dígitos hex)")
    return key


class SecretBox:
    def __init__(self, master_key: str | bytes):
        self._aes = AESGCM(master_key if isinstance(master_key, bytes) else load_master_key(master_key))

    @staticmethod
    def _aad(user_id: str, name: str) -> bytes:
        return f"{user_id}:{name}".encode()

    def encrypt(self, user_id: str, name: str, value: str) -> str:
        nonce = os.urandom(12)
        ct = self._aes.encrypt(nonce, value.encode(), self._aad(user_id, name))
        return "v1:" + base64.b64encode(nonce + ct).decode()

    def decrypt(self, user_id: str, name: str, blob: str) -> str:
        try:
            if not blob.startswith("v1:"):
                raise ValueError
            raw = base64.b64decode(blob[3:])
            return self._aes.decrypt(raw[:12], raw[12:], self._aad(user_id, name)).decode()
        except Exception:
            raise CryptoError("não consegui abrir a chave (chave mestra diferente ou dado alterado)") from None
