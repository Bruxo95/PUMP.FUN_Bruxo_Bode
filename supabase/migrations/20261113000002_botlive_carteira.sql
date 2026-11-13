-- 0.32.338 (pedido do dono, 13/11/2026): BOT LIVE com carteira simulada própria, rodando a estratégia da Robinhood da versão 0.32.308.
-- Tabelas separadas (botlive_*), iguais às hood_*, para não mexer na /hood nem nas outras salas. Só o backend lê e grava.
create table if not exists public.botlive_books (
  user_id  uuid primary key references auth.users (id) on delete cascade,
  cfg      jsonb not null default '{}'::jsonb,
  cash     double precision not null default 0.1,
  em       timestamptz not null default now()
);
create table if not exists public.botlive_positions (
  id       text primary key,
  user_id  uuid not null references auth.users (id) on delete cascade,
  data     jsonb not null default '{}'::jsonb,
  em       timestamptz not null default now()
);
create index if not exists botlive_positions_user on public.botlive_positions (user_id);
create table if not exists public.botlive_trades (
  id       text primary key,
  user_id  uuid not null references auth.users (id) on delete cascade,
  t        double precision not null,
  data     jsonb not null default '{}'::jsonb
);
create index if not exists botlive_trades_user_t on public.botlive_trades (user_id, t desc);

alter table public.botlive_books enable row level security;
alter table public.botlive_positions enable row level security;
alter table public.botlive_trades enable row level security;
revoke all on public.botlive_books, public.botlive_positions, public.botlive_trades from anon, authenticated;

do $$ begin
  if exists (select 1 from pg_roles where rolname = 'leitor_ia') then
    grant select on public.botlive_books, public.botlive_positions, public.botlive_trades to leitor_ia;
    create policy "leitor_ia: ler" on public.botlive_books for select to leitor_ia using (true);
    create policy "leitor_ia: ler" on public.botlive_positions for select to leitor_ia using (true);
    create policy "leitor_ia: ler" on public.botlive_trades for select to leitor_ia using (true);
  end if;
end $$;
