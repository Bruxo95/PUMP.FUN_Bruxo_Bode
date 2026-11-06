-- 0.32.242 (pedido do dono, 06/11/2026): Dormant compra na DEX, à mão, com as carteiras de cada blockchain.
-- dormant_wallets: a chave privada SEMPRE cifrada em duas camadas (senha de compra + APP_ENCRYPTION_KEY, app/dormant_vault.py).
-- dormant_buy_cfg: chave ligada/desligada (começa desligada), limites em dólar e as tentativas de senha.
-- dormant_buys: histórico das compras. Tudo só pelo backend: RLS ligado, sem política, sem acesso para anon nem authenticated.
-- De propósito sem acesso para leitor_ia (a leitura de banco da IA não vê carteiras nem cifras).
create table if not exists public.dormant_wallets (
  user_id   uuid not null references auth.users(id) on delete cascade,
  rede      text not null,
  endereco  text not null,
  cifra     text not null,
  em        timestamptz not null default now(),
  primary key (user_id, rede)
);
create table if not exists public.dormant_buy_cfg (
  user_id   uuid primary key references auth.users(id) on delete cascade,
  cfg       jsonb not null default '{}'::jsonb,
  erros     integer not null default 0,
  trava_ate timestamptz,
  em        timestamptz not null default now()
);
create table if not exists public.dormant_buys (
  id          text primary key,
  user_id     uuid not null references auth.users(id) on delete cascade,
  em          timestamptz not null default now(),
  rede        text not null,
  cmc         text,
  cg          text,
  nome        text,
  simbolo     text,
  token       text not null,
  endereco    text not null,
  dex         text,
  rota        text,
  nativo      double precision,
  nativo_usd  double precision,
  usd_in      double precision,
  gas_usd     double precision,
  casas       integer,
  qty         double precision,
  px_in       double precision,
  tx          text,
  status      text not null,
  motivo      text
);
create index if not exists dormant_buys_user_em on public.dormant_buys (user_id, em desc);

alter table public.dormant_wallets enable row level security;
alter table public.dormant_buy_cfg enable row level security;
alter table public.dormant_buys enable row level security;
revoke all on public.dormant_wallets from anon, authenticated;
revoke all on public.dormant_buy_cfg from anon, authenticated;
revoke all on public.dormant_buys from anon, authenticated;
