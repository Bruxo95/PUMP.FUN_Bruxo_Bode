-- 0.32.382 (pedido do dono): chave da Alchemy (Solana) como chave do sistema, só para as carteiras ligadas ao DEV no BOOST.
-- Toda chave do sistema nova entra nesta regra (tests/test_jev.py confere).
alter table public.app_secrets drop constraint if exists app_secrets_nome_check;
alter table public.app_secrets add constraint app_secrets_nome_check check (
  nome in ('solanatracker_api_key', 'pumpportal_api_key', 'jupiter_api_key', 'rpc_url', 'jev_api_key', 'nodereal_bnb_key',
           'coingecko_key', 'alchemy_api_key')
);
