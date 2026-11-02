-- 0.32.168 (pedido do dono, 02/11: copiar traders da BNB, isolado do que já funciona): etapa 1 só lê a rede.
-- bnb_fm_trades: cada compra/venda da curva da Four.Meme (dados públicos, sem usuário); guarda 14 dias.
-- bnb_state: cursor do último bloco lido e a configuração do ranking da aba BNB. Só o backend lê e grava.
create table if not exists public.bnb_fm_trades (
  id      text primary key,                 -- hash da transação : índice do log
  tx      text not null,
  block   bigint not null,
  t       double precision not null,        -- hora (segundos desde 1970)
  token   text not null,
  wallet  text not null,
  side    text not null check (side in ('buy', 'sell')),
  price   double precision,
  amount  double precision,
  value   double precision,                 -- na moeda da curva (quote)
  fee     double precision,
  quote   text                              -- moeda da curva: 0x000… = BNB
);
create index if not exists bnb_fm_trades_t on public.bnb_fm_trades (t);
create index if not exists bnb_fm_trades_wallet on public.bnb_fm_trades (wallet, t);

create table if not exists public.bnb_state (
  k   text primary key,
  v   jsonb not null default '{}'::jsonb,
  em  timestamptz not null default now()
);

alter table public.bnb_fm_trades enable row level security;
alter table public.bnb_state enable row level security;
revoke all on public.bnb_fm_trades, public.bnb_state from anon, authenticated;

-- apaga trades com hora anterior a "antes" (nunca menos de 7 dias atrás; só o backend executa)
create or replace function public.bnb_trim(antes double precision)
returns integer language plpgsql security definer set search_path = public as $$
declare n integer;
begin
  delete from public.bnb_fm_trades
   where t < least(antes, extract(epoch from now()) - 7 * 86400);
  get diagnostics n = row_count;
  return n;
end $$;
revoke all on function public.bnb_trim(double precision) from public, anon, authenticated;
grant execute on function public.bnb_trim(double precision) to service_role;

do $$ begin
  if exists (select 1 from pg_roles where rolname = 'leitor_ia') then
    grant select on public.bnb_fm_trades, public.bnb_state to leitor_ia;
    create policy "leitor_ia: ler" on public.bnb_fm_trades for select to leitor_ia using (true);
    create policy "leitor_ia: ler" on public.bnb_state for select to leitor_ia using (true);
  end if;
end $$;
