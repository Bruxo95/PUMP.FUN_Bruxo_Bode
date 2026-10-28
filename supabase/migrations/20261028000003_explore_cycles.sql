-- Log de análise do Explorar (0.31.88, pedido do dono em 2026-10-28): um registro por lista do Explorar (a cada 5 min) e
-- por conta: quantos tokens vieram, quantos foram analisados, o que entrou e por que os outros foram barrados.
-- Só o backend lê e grava (o painel lê pela API, filtrando pelo user_id do token).
create table if not exists public.explore_cycles (
  id       text primary key,
  user_id  uuid not null references auth.users (id) on delete cascade,
  em       timestamptz not null default now(),
  data     jsonb not null default '{}'::jsonb
);
create index if not exists explore_cycles_user_em on public.explore_cycles (user_id, em desc);
alter table public.explore_cycles enable row level security;
revoke all on public.explore_cycles from anon, authenticated;
