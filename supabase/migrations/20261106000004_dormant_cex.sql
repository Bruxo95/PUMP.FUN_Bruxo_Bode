-- 0.32.247 (pedido do dono, 06/11/2026): comprar em exchange pela API. A chave fica cifrada em duas camadas (app/dormant_vault.py).
-- Só o backend lê e grava; de propósito sem acesso para leitor_ia. As compras entram em dormant_buys com rede = 'cex:<exchange>'.
create table if not exists public.dormant_cex_keys (
  user_id   uuid not null references auth.users(id) on delete cascade,
  exchange  text not null,
  rotulo    text not null,
  cifra     text not null,
  info      jsonb,
  em        timestamptz not null default now(),
  primary key (user_id, exchange)
);
alter table public.dormant_cex_keys enable row level security;
revoke all on public.dormant_cex_keys from anon, authenticated;
