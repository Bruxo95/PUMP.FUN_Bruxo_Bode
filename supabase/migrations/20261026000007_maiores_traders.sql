-- Maiores traders (0.31.2, pedido do dono em 2026-10-26): sinais (tokens em que os maiores traders entraram) e o que
-- aconteceu em 60 min, para estudar e sugerir melhorias. Só o backend lê e grava (RLS sem política).
create table if not exists public.elite_signals (
  id         text primary key,
  mint       text not null,
  symbol     text,
  criado_em  timestamptz not null,
  data       jsonb not null
);
create index if not exists elite_signals_criado on public.elite_signals (criado_em desc);
alter table public.elite_signals enable row level security;
revoke all on public.elite_signals from anon, authenticated;

-- compras automáticas dos sinais entram na mesma tabela das outras automáticas, com origem "elite"
alter table public.auto_trades drop constraint if exists auto_trades_origem_check;
alter table public.auto_trades add constraint auto_trades_origem_check check (origem in ('base', 'explorar', 'elite'));
