-- 0.32.279 (pedido do dono, 10/11/2026: "faz 1 a 4"): Robinhood Chain, etapa 2. Cópia FICTÍCIA em ETH por conta de admin e
-- carteira REAL (começa DESLIGADA). Tabelas próprias hood_*, separadas da Solana e da BNB. Só o backend lê e grava.
-- hood_books: configuração (fictícia e REAL) e saldo fictício; hood_positions: abertas; hood_trades: fechadas
-- (data->>'real' = 'true' nas da carteira REAL).
create table if not exists public.hood_books (
  user_id  uuid primary key references auth.users (id) on delete cascade,
  cfg      jsonb not null default '{}'::jsonb,
  cash     double precision not null default 0.1,
  em       timestamptz not null default now()
);
create table if not exists public.hood_positions (
  id       text primary key,
  user_id  uuid not null references auth.users (id) on delete cascade,
  data     jsonb not null default '{}'::jsonb,
  em       timestamptz not null default now()
);
create index if not exists hood_positions_user on public.hood_positions (user_id);
create table if not exists public.hood_trades (
  id       text primary key,
  user_id  uuid not null references auth.users (id) on delete cascade,
  t        double precision not null,          -- hora em que fechou (segundos desde 1970)
  data     jsonb not null default '{}'::jsonb
);
create index if not exists hood_trades_user_t on public.hood_trades (user_id, t desc);

alter table public.hood_books enable row level security;
alter table public.hood_positions enable row level security;
alter table public.hood_trades enable row level security;
revoke all on public.hood_books, public.hood_positions, public.hood_trades from anon, authenticated;

do $$ begin
  if exists (select 1 from pg_roles where rolname = 'leitor_ia') then
    grant select on public.hood_books, public.hood_positions, public.hood_trades to leitor_ia;
    create policy "leitor_ia: ler" on public.hood_books for select to leitor_ia using (true);
    create policy "leitor_ia: ler" on public.hood_positions for select to leitor_ia using (true);
    create policy "leitor_ia: ler" on public.hood_trades for select to leitor_ia using (true);
  end if;
end $$;

-- chave da carteira da Robinhood no mesmo cofre (user_secrets, criptografada no servidor). Só libera o nome novo; nada é apagado.
alter table public.user_secrets drop constraint if exists user_secrets_nome_check;
alter table public.user_secrets add constraint user_secrets_nome_check check (
  nome in ('solanatracker_api_key', 'pumpportal_api_key', 'wallet_private_key', 'rpc_url', 'jupiter_api_key',
           'telegram_bot_token', 'telegram_chat_id', 'bnb_private_key', 'hood_private_key')
);
