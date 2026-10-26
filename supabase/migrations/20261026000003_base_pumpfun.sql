-- Base própria da pump.fun (0.21.0, pedido do dono em 2026-10-26): resumo de cada token novo observado pelo
-- monitor. Só o backend lê e grava (RLS sem política). Para não encher o banco, guarda só os tokens
-- "interessantes" (graduou, 5x, 2x, despencou) por 7 dias, o resumo por hora e o histórico de cada criador.
create table if not exists public.token_life (
  mint       text primary key,
  creator    text,
  label      text not null,
  data       jsonb not null,
  criado_em  timestamptz not null default now()
);
create index if not exists token_life_criado on public.token_life (criado_em);
create index if not exists token_life_creator on public.token_life (creator);

create table if not exists public.market_hourly (
  hora  timestamptz primary key,
  data  jsonb not null
);

create table if not exists public.creator_stats (
  creator        text primary key,
  tokens         integer not null default 0,
  x2             integer not null default 0,
  rugs           integer not null default 0,
  atualizado_em  timestamptz not null default now()
);

alter table public.token_life    enable row level security;
alter table public.market_hourly enable row level security;
alter table public.creator_stats enable row level security;
revoke all on public.token_life, public.market_hourly, public.creator_stats from anon, authenticated;

-- apaga tokens interessantes com mais de p_days dias (sempre com filtro de data; só o backend executa)
create or replace function public.trim_token_life(p_days integer default 7)
returns integer language plpgsql security definer set search_path = public as $$
declare n integer;
begin
  delete from public.token_life where criado_em < now() - make_interval(days => greatest(p_days, 1));
  get diagnostics n = row_count;
  return n;
end $$;
revoke all on function public.trim_token_life(integer) from public, anon, authenticated;
grant execute on function public.trim_token_life(integer) to service_role;
