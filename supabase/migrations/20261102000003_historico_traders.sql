-- 0.32.163 (pedido do dono, 02/11: "quero guardar esse histórico"): resumo de cada trader copiado por conta e carteira
-- (fictícia/real), com o ranking do próprio trader por dia. Fica mesmo depois de zerar a fictícia. Só o backend lê e grava.
create table if not exists public.trader_history (
  id       text primary key,
  user_id  uuid not null references auth.users (id) on delete cascade,
  real     boolean not null default false,
  wallet   text not null,
  em       timestamptz not null default now(),
  data     jsonb not null default '{}'::jsonb
);
create index if not exists trader_history_user on public.trader_history (user_id, real);
alter table public.trader_history enable row level security;
revoke all on public.trader_history from anon, authenticated;

do $$ begin
  if exists (select 1 from pg_roles where rolname = 'leitor_ia') then
    grant select on public.trader_history to leitor_ia;
    create policy "leitor_ia: ler" on public.trader_history for select to leitor_ia using (true);
  end if;
end $$;
