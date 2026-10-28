-- Aprendizado dos logs dos robôs (0.31.91, pedido do dono em 2026-10-28): um resumo por dia, conta e robô (analisados,
-- entradas, motivos de recusa). Os registros de 5 min (explore_cycles, robot_log) continuam guardados, sem apagar.
-- Só o backend lê e grava.
create table if not exists public.robot_daily (
  id       text primary key,
  user_id  uuid not null references auth.users (id) on delete cascade,
  modulo   text not null,
  dia      date not null,
  data     jsonb not null default '{}'::jsonb
);
create index if not exists robot_daily_user_mod_dia on public.robot_daily (user_id, modulo, dia desc);
alter table public.robot_daily enable row level security;
revoke all on public.robot_daily from anon, authenticated;
