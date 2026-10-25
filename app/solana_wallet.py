"""Carteira Solana do bot de UM usuário (para a execução real).

- A chave privada é colada pelo dono no painel, vai criptografada para o banco e só é descriptografada na
  memória do servidor para ASSINAR transações.
- Nada aqui devolve a chave: só o endereço público e se está configurada.
- Use uma carteira NOVA, só para o bot, com pouco dinheiro: quem tem a chave tem todo o saldo dela.
"""
from __future__ import annotations

import json

PUBLIC_RPC = "https://api.mainnet-beta.solana.com"


def parse_keypair(text: str):
    """Aceita a chave em base58 (formato exportado pela Phantom/Solflare) ou como lista JSON de 64 números
    (arquivo id.json do solana-keygen). Devolve um Keypair ou levanta ValueError."""
    from solders.keypair import Keypair
    t = (text or "").strip()
    if not t:
        raise ValueError("chave vazia")
    try:
        if t.startswith("["):
            nums = json.loads(t)
            if not (isinstance(nums, list) and len(nums) == 64 and all(isinstance(x, int) and 0 <= x < 256 for x in nums)):
                raise ValueError
            return Keypair.from_bytes(bytes(nums))
        return Keypair.from_base58_string(t)
    except Exception:
        raise ValueError("chave inválida: use a chave privada em base58 (exportada da carteira) ou a lista de 64 "
                         "números do id.json") from None


def check_rpc_url(u: str) -> str:
    u = (u or "").strip()
    if not u.startswith("https://"):
        raise ValueError("o RPC precisa começar com https://")
    return u


class UserWallet:
    def __init__(self, private_key: str = "", rpc_url: str = "", public_rpc: str = PUBLIC_RPC,
                 jupiter_api_key: str = ""):
        self._kp = parse_keypair(private_key) if private_key else None
        self._rpc = (rpc_url or "").strip()
        self._public = public_rpc or PUBLIC_RPC
        self.jupiter_api_key = jupiter_api_key or ""

    @property
    def address(self) -> str | None:
        return str(self._kp.pubkey()) if self._kp else None

    @property
    def keypair(self):
        """Só para assinar transações (uso interno; nunca vai para a API nem para os logs)."""
        return self._kp

    @property
    def rpc_url(self) -> str:
        return self._rpc or self._public

    @property
    def own_rpc(self) -> bool:
        return bool(self._rpc)

    def public(self) -> dict:
        host = self.rpc_url.split("/")[2] if "://" in self.rpc_url else None
        return {"configured": self._kp is not None, "address": self.address, "rpc_set": self.own_rpc,
                "rpc_host": host}
