-- 0.32.370 (pedido do dono, 15/11/2026): Projeto Forex, etapa 2 — conector do cTrader. O Client ID, o Client Secret do aplicativo
-- da cTrader Open API e o token das contas autorizadas (OAuth, só leitura) ficam no mesmo cofre (user_secrets, criptografados no
-- servidor). Só libera os nomes novos; nada é apagado.
alter table public.user_secrets drop constraint if exists user_secrets_nome_check;
alter table public.user_secrets add constraint user_secrets_nome_check check (
  nome in ('solanatracker_api_key', 'pumpportal_api_key', 'wallet_private_key', 'rpc_url', 'jupiter_api_key',
           'telegram_bot_token', 'telegram_chat_id', 'bnb_private_key', 'hood_private_key',
           'youtube_client_id', 'youtube_client_secret', 'youtube_refresh_token',
           'ctrader_client_id', 'ctrader_client_secret', 'ctrader_tokens')
);
