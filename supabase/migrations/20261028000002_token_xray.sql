-- Raio-X do token (0.31.86, pedido do dono em 2026-10-28): análise das primeiras 500 negociações (primeiros compradores,
-- quanto seguraram, despejo, compras em bloco). Dados públicos, sem dono: só o backend lê e grava.
create table if not exists public.token_xray (
  mint  text primary key,
  em    timestamptz not null default now(),
  data  jsonb not null default '{}'::jsonb
);
create index if not exists token_xray_em on public.token_xray (em desc);
alter table public.token_xray enable row level security;
revoke all on public.token_xray from anon, authenticated;
