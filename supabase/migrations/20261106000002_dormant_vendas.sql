-- 0.32.243 (pedido do dono, 06/11/2026): venda à mão no Dormant. Mesma regra das compras: só o backend lê e grava.
create table if not exists public.dormant_sells (
  id          text primary key,
  user_id     uuid not null references auth.users(id) on delete cascade,
  em          timestamptz not null default now(),
  rede        text not null,
  compra      text,
  cg          text,
  nome        text,
  simbolo     text,
  token       text not null,
  endereco    text not null,
  dex         text,
  rota        text,
  qty         double precision,
  casas       integer,
  nativo_out  double precision,
  nativo_usd  double precision,
  usd_out     double precision,
  gas_usd     double precision,
  tx          text,
  status      text not null,
  motivo      text
);
create index if not exists dormant_sells_user_em on public.dormant_sells (user_id, em desc);
alter table public.dormant_sells enable row level security;
revoke all on public.dormant_sells from anon, authenticated;
