-- 0.32.80 (pedido do dono, 29/10): relatório da Aba do Bruxo a cada 30 min e de 1 dia, guardado para a Base geral aprender.
-- Só o backend lê e grava (RLS sem política).
create table if not exists public.bruxo_reports (
  id       bigint generated always as identity primary key,
  user_id  uuid not null references auth.users (id) on delete cascade,
  tipo     text not null check (tipo in ('30min', 'dia')),
  dia      date,
  em       timestamptz not null default now(),
  data     jsonb not null default '{}'::jsonb
);
create index if not exists bruxo_reports_user_em on public.bruxo_reports (user_id, em desc);
alter table public.bruxo_reports enable row level security;
revoke all on public.bruxo_reports from anon, authenticated;
