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
    "telegram_bot_token": "Bot do Telegram (token do @BotFather)",
    "telegram_chat_id": "ID do seu chat no Telegram",
}

# 0.32.172: chave da carteira BNB, guardada no mesmo cofre (user_secrets, criptografada), mas fora da lista acima para não
# aparecer nas Chaves pessoais do painel da Solana: o painel da BNB tem a tela própria.
BNB_SECRET_NAMES = {"bnb_private_key": "Chave privada da carteira BNB (Four.Meme)",
                    # 0.32.279: carteira da Robinhood Chain, mesma regra (só aparece no painel /hood)
                    "hood_private_key": "Chave privada da carteira da Robinhood Chain",
                    # 0.32.349: YouTube do BOT LIVE (comentar as compras no chat da live). Só aparecem em /botlive.
                    "youtube_client_id": "YouTube: Client ID (OAuth)",
                    "youtube_client_secret": "YouTube: Client Secret (OAuth)",
                    "youtube_refresh_token": "YouTube: autorização do canal"}


# chaves que o ADMIN pode configurar para todos usarem na VISUALIZAÇÃO (dados e cotações; nunca execução real)
SYSTEM_NAMES = {
    "solanatracker_api_key": "Chave da Solana Tracker",
    "pumpportal_api_key": "Chave da PumpPortal",
    "jupiter_api_key": "Chave da Jupiter (opcional)",
    "rpc_url": "RPC próprio (Helius etc.)",
    "jev_api_key": "Chave do Jev (TypeSafe AI) — modo sombra",
}
# 0.32.180 (pedido do dono: "tudo o que for BNB fica separado da rede Solana"): chaves do sistema da BNB. Ficam na mesma
# tabela app_secrets (criptografadas), mas só aparecem e só são salvas no painel da BNB (/bnb → Administração).
BNB_SYSTEM_NAMES = {"nodereal_bnb_key": "Chave da NodeReal (BNB) — histórico dos traders"}
# 0.32.227: chave Demo da CoinGecko, só no painel do Dormant (/dormant). Mesma tabela app_secrets, criptografada.
DORMANT_SYSTEM_NAMES = {"coingecko_key": "Chave Demo da CoinGecko (Dormant)"}
SYSTEM_OWNER = "__sistema__"                        # "dono" usado na criptografia das chaves do sistema

# onde cada pessoa cria a própria chave (mostrado em Configurações)
KEY_LINKS = {
    "solanatracker_api_key": "https://www.solanatracker.io/account/data-api",
    "pumpportal_api_key": "https://pumpportal.fun/trading-api/setup",
    "jupiter_api_key": "https://developers.jup.ag/portal",
    "rpc_url": "https://dashboard.helius.dev",
    "jev_api_key": "https://typesafe.ai",
    "nodereal_bnb_key": "https://nodereal.io/meganode",
    "wallet_private_key": "https://phantom.com",
    "telegram_bot_token": "https://t.me/BotFather",
    "telegram_chat_id": "https://t.me/userinfobot",
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
