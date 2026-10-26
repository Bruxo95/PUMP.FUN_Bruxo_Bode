-- Permite 'rpc_url' nas chaves do sistema (app_secrets) e chaves pessoais (user_secrets)
alter table public.app_secrets drop constraint if exists app_secrets_nome_check;
alter table public.app_secrets add constraint app_secrets_nome_check check (
  nome in ('solanatracker_api_key', 'pumpportal_api_key', 'jupiter_api_key', 'rpc_url')
);

alter table public.user_secrets drop constraint if exists user_secrets_nome_check;
alter table public.user_secrets add constraint user_secrets_nome_check check (
  nome in ('solanatracker_api_key', 'pumpportal_api_key', 'wallet_private_key', 'rpc_url', 'jupiter_api_key', 'telegram_bot_token', 'telegram_chat_id')
);
