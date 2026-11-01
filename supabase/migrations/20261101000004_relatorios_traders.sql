-- 0.32.140 (pedido do dono): relatório dos traders de cada aba, guardado para a Base geral. Só o backend lê e grava (RLS sem política).
create table if not exists public.trader_reports (
  id       text primary key,
  user_id  uuid not null references auth.users (id) on delete cascade,
  real     boolean not null default false,
  aba      text not null,
  origem   text not null default 'manual' check (origem in ('manual', 'dia')),
  em       timestamptz not null default now(),
  data     jsonb not null default '{}'::jsonb
);
create index if not exists trader_reports_em on public.trader_reports (em desc);
alter table public.trader_reports enable row level security;
revoke all on public.trader_reports from anon, authenticated;

do $$ begin
  if exists (select 1 from pg_roles where rolname = 'leitor_ia') then
    grant select on public.trader_reports to leitor_ia;
    create policy "leitor_ia: ler" on public.trader_reports for select to leitor_ia using (true);
  end if;
end $$;
