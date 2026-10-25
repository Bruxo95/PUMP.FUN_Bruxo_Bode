-- Chaves do SISTEMA (configuradas pelo admin) usadas por todos para VISUALIZAR a ferramenta funcionando
-- (top traders, cotações). Criptografadas como as pessoais. Nenhum usuário lê esta tabela: RLS ligado e
-- nenhuma política de leitura; só o backend (service key) acessa.
create table if not exists public.app_secrets (
  nome                text primary key check (nome in ('solanatracker_api_key', 'pumpportal_api_key', 'jupiter_api_key')),
  valor_criptografado text not null,
  atualizado_por      uuid references auth.users (id) on delete set null,
  atualizado_em       timestamptz not null default now()
);
alter table public.app_secrets enable row level security;
revoke all on public.app_secrets from anon, authenticated;
