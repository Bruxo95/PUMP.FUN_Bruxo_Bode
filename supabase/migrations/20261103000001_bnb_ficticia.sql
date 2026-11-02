-- 0.32.170 (pedido do dono, 03/11): painel BNB com carteira FICTÍCIA por conta de admin (nunca envia ordem).
-- bnb_books: configuração e saldo; bnb_positions: posições abertas; bnb_trades: posições fechadas. Só o backend lê e grava.
create table if not exists public.bnb_books (
  user_id  uuid primary key references auth.users (id) on delete cascade,
  cfg      jsonb not null default '{}'::jsonb,
  cash     double precision not null default 1,
  em       timestamptz not null default now()
);
create table if not exists public.bnb_positions (
  id       text primary key,
  user_id  uuid not null references auth.users (id) on delete cascade,
  data     jsonb not null default '{}'::jsonb,
  em       timestamptz not null default now()
);
create index if not exists bnb_positions_user on public.bnb_positions (user_id);
create table if not exists public.bnb_trades (
  id       text primary key,
  user_id  uuid not null references auth.users (id) on delete cascade,
  t        double precision not null,          -- hora em que fechou (segundos desde 1970)
  data     jsonb not null default '{}'::jsonb
);
create index if not exists bnb_trades_user_t on public.bnb_trades (user_id, t desc);

alter table public.bnb_books enable row level security;
alter table public.bnb_positions enable row level security;
alter table public.bnb_trades enable row level security;
revoke all on public.bnb_books, public.bnb_positions, public.bnb_trades from anon, authenticated;

do $$ begin
  if exists (select 1 from pg_roles where rolname = 'leitor_ia') then
    grant select on public.bnb_books, public.bnb_positions, public.bnb_trades to leitor_ia;
    create policy "leitor_ia: ler" on public.bnb_books for select to leitor_ia using (true);
    create policy "leitor_ia: ler" on public.bnb_positions for select to leitor_ia using (true);
    create policy "leitor_ia: ler" on public.bnb_trades for select to leitor_ia using (true);
  end if;
end $$;
