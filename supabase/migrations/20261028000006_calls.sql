-- Calls quentes pela blockchain (0.31.94, pedido do dono em 2026-10-28): cada compra de uma carteira acompanhada vira
-- uma call, com o preço de quem seguiria 1 min depois, aos 5/15/60 min, o pico e se o caller despejou. Dados públicos,
-- sem dono: só o backend lê e grava.
create table if not exists public.calls (
  id    text primary key,
  em    timestamptz not null default now(),
  data  jsonb not null default '{}'::jsonb
);
create index if not exists calls_em on public.calls (em desc);
alter table public.calls enable row level security;
revoke all on public.calls from anon, authenticated;
