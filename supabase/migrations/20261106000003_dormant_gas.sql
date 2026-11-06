-- 0.32.244 (pedido do dono, 06/11/2026): abastecer de gás uma carteira a partir de outra rede. Só o backend lê e grava.
create table if not exists public.dormant_gas (
  id          text primary key,
  user_id     uuid not null references auth.users(id) on delete cascade,
  em          timestamptz not null default now(),
  rede        text not null,
  destino     text not null,
  endereco    text not null,
  recebedor   text not null,
  nativo      double precision,
  nativo_usd  double precision,
  usd_in      double precision,
  saida       double precision,
  saida_usd   double precision,
  gas_usd     double precision,
  request_id  text,
  tx          text,
  status      text not null,
  motivo      text
);
create index if not exists dormant_gas_user_em on public.dormant_gas (user_id, em desc);
alter table public.dormant_gas enable row level security;
revoke all on public.dormant_gas from anon, authenticated;
