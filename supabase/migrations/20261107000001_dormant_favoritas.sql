-- 0.32.248 (pedido do dono, 07/11/2026): moedas favoritas de cada conta no Dormant. Só o backend lê e grava.
create table if not exists public.dormant_favs (
  user_id  uuid not null references auth.users(id) on delete cascade,
  cmc      text not null,
  em       timestamptz not null default now(),
  primary key (user_id, cmc)
);
alter table public.dormant_favs enable row level security;
revoke all on public.dormant_favs from anon, authenticated;
