-- Estado da base da pump.fun (0.24.0): tokens ainda em observação, gravados a cada 2 min para não sumirem quando o
-- servidor reinicia numa versão nova (o dono perdeu de vista 3 tokens em 2026-10-26). Uma linha (id = 'live').
-- Só o backend lê e grava.
create table if not exists public.lab_state (
  id             text primary key,
  data           jsonb not null,
  atualizado_em  timestamptz not null default now()
);
alter table public.lab_state enable row level security;
revoke all on public.lab_state from anon, authenticated;
