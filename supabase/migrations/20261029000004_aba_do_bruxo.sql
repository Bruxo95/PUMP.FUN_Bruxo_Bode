-- 0.32.41 — Aba do Bruxo (áudios e prompt do Bruxo de 29/10) e relatório de cada aba a cada 30 min (pedido do dono).
-- bruxo_signals: cada compra de top trader em moeda nova, acompanhada por 30 min (dados públicos, sem dono).
-- tab_reports: o relatório de ganhos e perdas de cada aba, por conta, a cada 30 min (base geral aprende com eles).
-- Só o backend lê e grava (RLS sem política).
create table if not exists public.bruxo_signals (
  id    text primary key,
  em    timestamptz not null default now(),
  data  jsonb not null default '{}'::jsonb
);
create index if not exists bruxo_signals_em on public.bruxo_signals (em desc);
alter table public.bruxo_signals enable row level security;
revoke all on public.bruxo_signals from anon, authenticated;

create table if not exists public.tab_reports (
  id       bigint generated always as identity primary key,
  user_id  uuid not null references auth.users (id) on delete cascade,
  real     boolean not null default false,
  em       timestamptz not null default now(),
  data     jsonb not null default '{}'::jsonb
);
create index if not exists tab_reports_user_em on public.tab_reports (user_id, em desc);
alter table public.tab_reports enable row level security;
revoke all on public.tab_reports from anon, authenticated;

-- Pedido do dono no chat: a aba começa LIGADA só na conta dele, só na fictícia ("real sempre desativado; trabalhamos ativo
-- só fictícia"). Pela tabela settings_overrides (aplicada pelo servidor novo ao carregar a conta).
insert into public.settings_overrides (user_id, settings, motivo)
select p.user_id, '{"pump_bx_on": true, "pump_bx_real": false}'::jsonb,
       'pedido do dono (29/10): Aba do Bruxo ligada só na fictícia'
from public.profiles p where lower(p.email) = 'onlineguyat@gmail.com';
