-- Log de análise dos robôs (0.31.89, pedido do dono em 2026-10-28): cópia de traders, compra automática da Base e dos
-- Maiores traders; um registro por robô a cada 5 min e por conta (o que analisou, o que fez e por que não).
-- Só o backend lê e grava (o painel lê pela API, filtrando pelo user_id do token).
create table if not exists public.robot_log (
  id       text primary key,
  user_id  uuid not null references auth.users (id) on delete cascade,
  modulo   text not null,
  em       timestamptz not null default now(),
  data     jsonb not null default '{}'::jsonb
);
create index if not exists robot_log_user_mod_em on public.robot_log (user_id, modulo, em desc);
alter table public.robot_log enable row level security;
revoke all on public.robot_log from anon, authenticated;
