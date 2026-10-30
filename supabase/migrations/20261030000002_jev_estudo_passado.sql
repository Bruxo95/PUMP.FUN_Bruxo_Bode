-- 0.32.84 (pedido do dono, 30/10): o Jev analisa os casos JÁ PASSADOS (Aba do Bruxo, sombras do Explorar e todos os
-- lançamentos da Base da pump.fun) com só o que se sabia na hora; aqui fica a decisão dele e o que o token fez.
-- Só o backend lê e grava (RLS sem política). Nada daqui compra ou vende.
create table if not exists public.jev_backtest (
  id        text primary key,
  fonte     text not null,
  em        timestamptz not null,
  data      jsonb not null default '{}'::jsonb,
  feito_em  timestamptz not null default now()
);
create index if not exists jev_backtest_fonte_em on public.jev_backtest (fonte, em);
alter table public.jev_backtest enable row level security;
revoke all on public.jev_backtest from anon, authenticated;
