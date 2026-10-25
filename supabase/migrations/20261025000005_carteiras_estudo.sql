-- Carteiras em estudo (0.14.0): o dono escolhe carteiras para ESTUDAR (sem copiar). O sistema grava as operações
-- delas vistas ao vivo e o histórico por token puxado da Solana Tracker, para montar o perfil (ganho por minuto,
-- hora e dia, acerto, tempo segurando). Pedido do dono em 2026-10-25; aplicado pelo job "banco" do Actions.

-- lista de cada usuário (o navegador só lê a própria; quem grava é o backend)
create table if not exists public.study_wallets (
  user_id    uuid not null references auth.users (id) on delete cascade,
  wallet     text not null check (char_length(wallet) between 32 and 44),
  apelido    text check (apelido is null or char_length(apelido) <= 40),
  criado_em  timestamptz not null default now(),
  primary key (user_id, wallet)
);
alter table public.study_wallets enable row level security;
drop policy if exists "estudo: ver as próprias" on public.study_wallets;
create policy "estudo: ver as próprias" on public.study_wallets
  for select to authenticated using (user_id = (select auth.uid()));
revoke insert, update, delete on public.study_wallets from anon, authenticated;
revoke all on public.study_wallets from anon;

-- operações vistas ao vivo pelo monitor (dado público da blockchain, compartilhado; só o backend lê e grava)
create table if not exists public.wallet_trades (
  signature  text primary key,
  wallet     text not null,
  mint       text not null,
  side       text not null check (side in ('buy', 'sell')),
  sol        double precision,
  tokens     double precision,
  mcap_sol   double precision,
  at         timestamptz not null default now()
);
create index if not exists wallet_trades_wallet_at on public.wallet_trades (wallet, at desc);
alter table public.wallet_trades enable row level security;
revoke all on public.wallet_trades from anon, authenticated;

-- histórico por token da Solana Tracker (atualizado a cada 30 min; compartilhado; só o backend)
create table if not exists public.study_positions (
  wallet         text not null,
  token          text not null,
  data           jsonb not null,
  atualizado_em  timestamptz not null default now(),
  primary key (wallet, token)
);
alter table public.study_positions enable row level security;
revoke all on public.study_positions from anon, authenticated;

-- primeiras carteiras pedidas pelo dono (2026-10-25), na lista dos administradores
insert into public.study_wallets (user_id, wallet)
select p.user_id, v.w
from public.profiles p
cross join (values ('DQMqCjCiRS8BAkZ2xrJ7QJPqUjoHnRDoPtcXMiEPtSus'),
                   ('4nHt4vaFLw2t9o8Nvp7S6uAn1fKn8Ry6SSYbWM5NQAUc')) as v (w)
where p.role = 'admin'
on conflict do nothing;
