-- 0.32.172 (pedido do dono em 03/11/2026): carteira REAL da BNB. A chave privada da carteira BNB fica no mesmo cofre
-- das chaves pessoais (user_secrets, criptografada com AES-256-GCM no servidor). Só libera o nome novo; nada é apagado.
-- As posições e trades REAIS da BNB usam as tabelas bnb_positions/bnb_trades (data->>'real' = 'true').
alter table public.user_secrets drop constraint if exists user_secrets_nome_check;
alter table public.user_secrets add constraint user_secrets_nome_check check (
  nome in ('solanatracker_api_key', 'pumpportal_api_key', 'wallet_private_key', 'rpc_url', 'jupiter_api_key',
           'telegram_bot_token', 'telegram_chat_id', 'bnb_private_key')
);
