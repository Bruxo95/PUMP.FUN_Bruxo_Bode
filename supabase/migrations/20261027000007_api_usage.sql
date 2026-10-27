-- Uso das APIs externas (0.31.76, pedido do dono em 2026-10-27): chamadas por mês, por API e (Solana Tracker) por chave
-- (apelido feito com hash; a chave nunca é guardada). Só o backend lê e grava.
create table if not exists public.api_usage (
  mes    text not null,
  api    text not null,
  chave  text not null default '',
  n      bigint not null default 0,
  atualizado_em timestamptz not null default now(),
  primary key (mes, api, chave)
);
alter table public.api_usage enable row level security;
revoke all on public.api_usage from anon, authenticated;
