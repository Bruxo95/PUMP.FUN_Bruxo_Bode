"""Carteira Solana do bot de UM usuário (para a execução real).

- A chave privada é colada pelo dono no painel, vai criptografada para o banco e só é descriptografada na
  memória do servidor para ASSINAR transações.
- Nada aqui devolve a chave: só o endereço público e se está configurada.
- Use uma carteira NOVA, só para o bot, com pouco dinheiro: quem tem a chave tem todo o saldo dela.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
import time
import urllib.parse

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


# SEC-03 (auditoria 2026-10-25): o RPC pessoal aceitava qualquer https://, inclusive 127.0.0.1 e rede interna, e o
# servidor fazia POSTs para lá. Agora: só HTTPS na porta 443, sem usuário/senha, só endereço público — conferido ao
# salvar e de novo no DNS antes de usar (cache de 60 s). Bloquear a saída para a rede interna no ambiente continua
# recomendado (proteção de infraestrutura, fora do código).
LOCAL_SUFFIXES = (".localhost", ".local", ".internal", ".intranet", ".lan", ".home.arpa", ".corp")
NOT_PUBLIC = "o RPC precisa ser um endereço público da internet (nada de localhost ou rede interna)"


def internal_ip(ip: str) -> bool:
    a = ipaddress.ip_address(ip.split("%", 1)[0])
    if a.version == 6 and a.ipv4_mapped:
        a = a.ipv4_mapped
    return not a.is_global or a.is_multicast


def check_rpc_url(u: str) -> str:
    u = (u or "").strip()
    try:
        parts = urllib.parse.urlsplit(u)
        port = parts.port
    except ValueError:
        raise ValueError("endereço do RPC inválido") from None
    host = (parts.hostname or "").rstrip(".").lower()
    if parts.scheme != "https" or not host:
        raise ValueError("o RPC precisa começar com https://")
    if parts.username is not None or parts.password is not None:
        raise ValueError("o RPC não pode ter usuário/senha antes do endereço")
    if port not in (None, 443):
        raise ValueError("o RPC precisa usar a porta padrão do HTTPS (443)")
    try:
        literal = internal_ip(host)
    except ValueError:
        literal = None                                     # é um nome, não um IP
    # final numérico/hex (127.1, 2130706433, 0x7f.1) vira IP interno no resolvedor; nenhum domínio real termina assim
    if (literal or host == "localhost" or host.endswith(LOCAL_SUFFIXES) or "." not in host
            or re.fullmatch(r"0x[0-9a-f]*|[0-9]+", host.rsplit(".", 1)[-1])):
        raise ValueError(NOT_PUBLIC)
    return u


async def resolve(host: str) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    return [i[4][0] for i in infos]


class UserWallet:
    def __init__(self, private_key: str = "", rpc_url: str = "", public_rpc: str = PUBLIC_RPC,
                 jupiter_api_key: str = ""):
        self._kp = parse_keypair(private_key) if private_key else None
        self._rpc, self.rpc_rejected = (rpc_url or "").strip(), False
        if self._rpc:
            try:
                check_rpc_url(self._rpc)
            except ValueError:                             # salvo antes da regra nova: usa o RPC público
                self._rpc, self.rpc_rejected = "", True
        self.resolver = resolve                            # os testes trocam por um resolvedor falso
        self._rpc_ok_until = 0.0
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

    async def safe_rpc_url(self) -> str:
        """RPC para usar agora. O próprio do usuário só depois de conferir que o DNS aponta para endereço público."""
        if not self._rpc:
            return self._public
        if time.monotonic() >= self._rpc_ok_until:
            try:
                addrs = await self.resolver(urllib.parse.urlsplit(self._rpc).hostname)
            except OSError:
                raise ValueError("não consegui resolver o endereço do RPC") from None
            if not addrs or any(internal_ip(a) for a in addrs):
                raise ValueError(NOT_PUBLIC)
            self._rpc_ok_until = time.monotonic() + 60
        return self._rpc

    @property
    def own_rpc(self) -> bool:
        return bool(self._rpc)

    def public(self) -> dict:
        host = urllib.parse.urlsplit(self.rpc_url).hostname   # nunca usuário/senha da URL (SEC-09, 2026-10-25)
        return {"configured": self._kp is not None, "address": self.address, "rpc_set": self.own_rpc,
                "rpc_host": host, "rpc_rejected": self.rpc_rejected}
