-- Operações automáticas do Explorar e da Base: entrada, fechamento e observações posteriores.
-- Primeira entrega 0.30.0; sem alterar as tabelas ou operações já existentes.
create table if not exists public.auto_trades (
  id text primary key,
  user_id uuid not null references auth.users (id) on delete cascade,
  origem text not null check (origem in ('base', 'explorar')),
  real boolean not null default false,
  mint text not null,
  symbol text,
  entrada_em timestamptz not null,
  saida_em timestamptz,
  sol_in double precision,
  pnl_sol double precision,
  pnl_pct double precision,
  motivo_saida text,
  best_pct double precision,
  worst_pct double precision,
  veredito text,
  chance double precision,
  info jsonb not null default '{}'::jsonb,
  depois jsonb not null default '{}'::jsonb
);
create index if not exists auto_trades_user_entrada on public.auto_trades (user_id, entrada_em desc);
alter table public.auto_trades enable row level security;
create policy "automáticas: ver as próprias" on public.auto_trades
  for select to authenticated using (user_id = (select auth.uid()));
revoke insert, update, delete on public.auto_trades from anon, authenticated;
revoke all on public.auto_trades from anon;
