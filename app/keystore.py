"""Chaves pessoais de UM usuário, já descriptografadas, só na memória do servidor.

Quem grava no banco (criptografado) é o app/secrets.py; aqui só se lê. Nada daqui vai para a API: o painel recebe
apenas "configurada: sim/não".
"""
from __future__ import annotations

from .logsafe import add_secret

# nomes aceitos (iguais em user_secrets.nome)
SECRET_NAMES = {
    "solanatracker_api_key": "Chave da Solana Tracker",
    "pumpportal_api_key": "Chave da PumpPortal",
    "wallet_private_key": "Chave privada da carteira Solana do bot",
    "rpc_url": "RPC próprio (Helius etc.)",
    "jupiter_api_key": "Chave da Jupiter (opcional)",
}


# chaves que o ADMIN pode configurar para todos usarem na VISUALIZAÇÃO (dados e cotações; nunca execução real)
SYSTEM_NAMES = {
    "solanatracker_api_key": "Chave da Solana Tracker",
    "pumpportal_api_key": "Chave da PumpPortal",
    "jupiter_api_key": "Chave da Jupiter (opcional)",
}
SYSTEM_OWNER = "__sistema__"                        # "dono" usado na criptografia das chaves do sistema

# onde cada pessoa cria a própria chave (mostrado em Configurações)
KEY_LINKS = {
    "solanatracker_api_key": "https://www.solanatracker.io/account/data-api",
    "pumpportal_api_key": "https://pumpportal.fun/trading-api/setup",
    "jupiter_api_key": "https://developers.jup.ag/portal",
    "rpc_url": "https://dashboard.helius.dev",
    "wallet_private_key": "https://phantom.com",
}


class KeyRing:
    def __init__(self, values: dict | None = None):
        self._d: dict[str, str] = {}
        for k, v in (values or {}).items():
            self.set(k, v)

    def get(self, name: str) -> str:
        return self._d.get(name, "")

    def set(self, name: str, value: str) -> None:
        value = (value or "").strip()
        if value:
            self._d[name] = value
            add_secret(value)
        else:
            self._d.pop(name, None)

    def configured(self) -> dict:
        return {k: bool(self._d.get(k)) for k in SECRET_NAMES}
