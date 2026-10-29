-- 0.32.73 (pedido do dono, 29/10): relatório do Copiar igual a cada 6 h (ganhos, perdas, cada operação, por carteira),
-- guardado para a Base geral aprender quais carteiras dão lucro de forma repetida. Só o backend lê e grava (RLS sem política).
create table if not exists public.eq_reports (
  id       bigint generated always as identity primary key,
  user_id  uuid not null references auth.users (id) on delete cascade,
  real     boolean not null default false,
  em       timestamptz not null default now(),
  data     jsonb not null default '{}'::jsonb
);
create index if not exists eq_reports_user_em on public.eq_reports (user_id, em desc);
alter table public.eq_reports enable row level security;
revoke all on public.eq_reports from anon, authenticated;
