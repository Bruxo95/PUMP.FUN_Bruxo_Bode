-- 0.32.161 (pedido do dono, 02/11): resultado de cada bloco de dias de semana (seg–sex) e de fim de semana (sáb–dom), por conta e
-- carteira (fictícia/real), guardado quando o bloco fecha para comparar depois. Só o backend lê e grava (RLS sem política).
create table if not exists public.week_results (
  id       text primary key,
  user_id  uuid not null references auth.users (id) on delete cascade,
  real     boolean not null default false,
  bloco    text not null,
  tipo     text not null check (tipo in ('semana', 'fds')),
  inicio   timestamptz not null,
  em       timestamptz not null default now(),
  data     jsonb not null default '{}'::jsonb
);
create index if not exists week_results_user on public.week_results (user_id, real, inicio desc);
alter table public.week_results enable row level security;
revoke all on public.week_results from anon, authenticated;

do $$ begin
  if exists (select 1 from pg_roles where rolname = 'leitor_ia') then
    grant select on public.week_results to leitor_ia;
    create policy "leitor_ia: ler" on public.week_results for select to leitor_ia using (true);
  end if;
end $$;
