-- Base geral (0.31.71, pedido do dono em 2026-10-27): fotos da base de aprendizado de todas as contas (a cada 30 min,
-- para o gráfico da evolução) e o log do que foi aprendido (faixa bloqueada/liberada, melhor regra de saída).
-- Dados gerais, sem dono: só o backend lê e grava (RLS ligado e sem política para o navegador).
create table if not exists public.base_snapshots (
  id    bigserial primary key,
  em    timestamptz not null default now(),
  data  jsonb not null default '{}'::jsonb
);
create index if not exists base_snapshots_em on public.base_snapshots (em desc);
alter table public.base_snapshots enable row level security;
revoke all on public.base_snapshots from anon, authenticated;

create table if not exists public.base_log (
  id     bigserial primary key,
  em     timestamptz not null default now(),
  tipo   text not null,
  texto  text not null,
  data   jsonb not null default '{}'::jsonb
);
create index if not exists base_log_em on public.base_log (em desc);
alter table public.base_log enable row level security;
revoke all on public.base_log from anon, authenticated;
