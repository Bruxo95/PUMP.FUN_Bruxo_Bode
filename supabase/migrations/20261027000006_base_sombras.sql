-- Entradas sombra (0.31.72, pedido do dono em 2026-10-27): tokens "chance alta" que o Explorar olhou e NÃO comprou, com os
-- números do momento e o que o preço fez em 15 min. Só aprendizado (base geral): não é trade nem dinheiro de ninguém.
-- Dados gerais, sem dono: só o backend lê e grava.
create table if not exists public.base_shadows (
  mint  text primary key,
  em    timestamptz not null default now(),
  data  jsonb not null default '{}'::jsonb
);
create index if not exists base_shadows_em on public.base_shadows (em desc);
alter table public.base_shadows enable row level security;
revoke all on public.base_shadows from anon, authenticated;
