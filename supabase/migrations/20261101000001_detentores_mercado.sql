-- 0.32.116 (lote 12 conferido): detentores aos 5 min de cada token conferido, com o que aconteceu depois, e dia frio ou normal.
-- Só o backend lê e grava (RLS sem política).
create table if not exists public.holders_t5 (
  mint  text primary key,
  em    timestamptz not null default now(),
  data  jsonb not null default '{}'::jsonb
);
create index if not exists holders_t5_em on public.holders_t5 (em desc);
alter table public.holders_t5 enable row level security;
revoke all on public.holders_t5 from anon, authenticated;

create table if not exists public.market_days (
  dia   date primary key,
  data  jsonb not null default '{}'::jsonb
);
alter table public.market_days enable row level security;
revoke all on public.market_days from anon, authenticated;

do $$ begin
  if exists (select 1 from pg_roles where rolname = 'leitor_ia') then
    grant select on public.holders_t5, public.market_days to leitor_ia;
    create policy "leitor_ia: ler" on public.holders_t5 for select to leitor_ia using (true);
    create policy "leitor_ia: ler" on public.market_days for select to leitor_ia using (true);
  end if;
end $$;
