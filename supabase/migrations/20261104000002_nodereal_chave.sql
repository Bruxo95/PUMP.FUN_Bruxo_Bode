-- 0.32.179 (pedido do dono, 04/11/2026): chave do sistema da NodeReal (BNB), usada só para buscar o histórico dos traders
-- da BNB. Toda chave do sistema nova precisa entrar nesta regra (tests/test_jev.py confere).
alter table public.app_secrets drop constraint if exists app_secrets_nome_check;
alter table public.app_secrets add constraint app_secrets_nome_check check (
  nome in ('solanatracker_api_key', 'pumpportal_api_key', 'jupiter_api_key', 'rpc_url', 'jev_api_key', 'nodereal_bnb_key')
);
