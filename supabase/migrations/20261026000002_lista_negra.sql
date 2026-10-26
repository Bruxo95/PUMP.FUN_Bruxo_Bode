-- Lista negra compartilhada (0.20.0): criadores de token que deram rug ou venderam deixando a cópia no prejuízo, e
-- endereços que o admin adiciona. Vale para todos os usuários que ligarem a opção. Pedido do dono em 2026-10-26.
-- Só o backend lê e grava (service role); nenhum usuário acessa direto (RLS sem política).
create table if not exists public.blacklist (
  endereco   text primary key check (char_length(endereco) between 32 and 44),
  tipo       text not null check (tipo in ('dev', 'carteira')),
  motivo     text check (motivo is null or char_length(motivo) <= 120),
  criado_em  timestamptz not null default now()
);

alter table public.blacklist enable row level security;
revoke all on public.blacklist from anon, authenticated;
