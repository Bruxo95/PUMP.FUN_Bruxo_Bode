-- PUMP.FUN Bruxo Bode — estrutura inicial.
-- RLS ligado em TODAS as tabelas: cada usuário logado só enxerga as próprias linhas (user_id = auth.uid()).
-- O backend usa a service key (só no servidor) para gravar; o navegador nunca escreve direto nestas tabelas.

-- ---------------------------------------------------------------- perfis
create table if not exists public.profiles (
  user_id     uuid primary key references auth.users (id) on delete cascade,
  email       text,
  nome        text,
  avatar_url  text,
  role        text not null default 'user' check (role in ('admin', 'user')),
  criado_em   timestamptz not null default now()
);

-- ---------------------------------------------------------------- configurações PUMP_* por usuário
create table if not exists public.user_settings (
  user_id        uuid primary key references auth.users (id) on delete cascade,
  settings       jsonb not null default '{}'::jsonb,
  -- só vale para o admin: emprestar a chave da Solana Tracker para quem não tem (a chave nunca é mostrada)
  compartilhar_chave_st boolean not null default false,
  atualizado_em  timestamptz not null default now()
);

-- ---------------------------------------------------------------- chaves pessoais (criptografadas AES-256-GCM)
create table if not exists public.user_secrets (
  user_id             uuid not null references auth.users (id) on delete cascade,
  nome                text not null check (nome in ('solanatracker_api_key', 'pumpportal_api_key',
                                                    'wallet_private_key', 'rpc_url', 'jupiter_api_key')),
  valor_criptografado text not null,
  criado_em           timestamptz not null default now(),
  primary key (user_id, nome)
);

-- ---------------------------------------------------------------- carteira (fictícia e real)
create table if not exists public.pump_positions (
  id         text primary key,
  user_id    uuid not null references auth.users (id) on delete cascade,
  real       boolean not null default false,
  data       jsonb not null,
  aberta_em  timestamptz not null default now()
);
create index if not exists pump_positions_user on public.pump_positions (user_id);

create table if not exists public.pump_trades (
  id          text primary key,
  user_id     uuid not null references auth.users (id) on delete cascade,
  real        boolean not null default false,
  data        jsonb not null,
  fechada_em  timestamptz not null default now()
);
create index if not exists pump_trades_user on public.pump_trades (user_id, fechada_em desc);

-- ---------------------------------------------------------------- traders manuais / banidos / pausados
create table if not exists public.pump_lists (
  user_id  uuid not null references auth.users (id) on delete cascade,
  tipo     text not null check (tipo in ('manual', 'banida', 'pausada')),
  wallet   text not null,
  extra    jsonb not null default '{}'::jsonb,
  primary key (user_id, tipo, wallet)
);

-- ---------------------------------------------------------------- feed (só os últimos ~500 por usuário)
create table if not exists public.pump_feed (
  id       bigint generated always as identity primary key,
  user_id  uuid not null references auth.users (id) on delete cascade,
  at       timestamptz not null default now(),
  data     jsonb not null
);
create index if not exists pump_feed_user on public.pump_feed (user_id, id desc);

-- ---------------------------------------------------------------- auditoria
create table if not exists public.audit_log (
  id       bigint generated always as identity primary key,
  user_id  uuid references auth.users (id) on delete cascade,
  acao     text not null,
  detalhe  text,
  at       timestamptz not null default now()
);
create index if not exists audit_log_user on public.audit_log (user_id, at desc);

-- ---------------------------------------------------------------- RLS
alter table public.profiles       enable row level security;
alter table public.user_settings  enable row level security;
alter table public.user_secrets   enable row level security;
alter table public.pump_positions enable row level security;
alter table public.pump_trades    enable row level security;
alter table public.pump_lists     enable row level security;
alter table public.pump_feed      enable row level security;
alter table public.audit_log      enable row level security;

-- leitura só das próprias linhas; escrita só pelo backend (service role ignora RLS)
create policy "profiles: ver o próprio"       on public.profiles       for select to authenticated using (user_id = (select auth.uid()));
create policy "settings: ver as próprias"     on public.user_settings  for select to authenticated using (user_id = (select auth.uid()));
create policy "secrets: ver só nomes próprios" on public.user_secrets  for select to authenticated using (user_id = (select auth.uid()));
create policy "posições: ver as próprias"     on public.pump_positions for select to authenticated using (user_id = (select auth.uid()));
create policy "trades: ver os próprios"       on public.pump_trades    for select to authenticated using (user_id = (select auth.uid()));
create policy "listas: ver as próprias"       on public.pump_lists     for select to authenticated using (user_id = (select auth.uid()));
create policy "feed: ver o próprio"           on public.pump_feed      for select to authenticated using (user_id = (select auth.uid()));
create policy "auditoria: ver a própria"      on public.audit_log      for select to authenticated using (user_id = (select auth.uid()));

-- o navegador (anon / authenticated) nunca grava direto; nem lê o valor criptografado das chaves
revoke insert, update, delete on public.profiles, public.user_settings, public.user_secrets, public.pump_positions,
  public.pump_trades, public.pump_lists, public.pump_feed, public.audit_log from anon, authenticated;
revoke all on public.profiles, public.user_settings, public.user_secrets, public.pump_positions,
  public.pump_trades, public.pump_lists, public.pump_feed, public.audit_log from anon;
revoke select on public.user_secrets from authenticated;
grant select (user_id, nome, criado_em) on public.user_secrets to authenticated;   -- o valor criptografado não

-- ---------------------------------------------------------------- perfil automático (o 1º usuário vira admin)
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  n bigint;
begin
  perform pg_advisory_xact_lock(4207);            -- dois cadastros ao mesmo tempo: só um vira admin
  select count(*) into n from public.profiles;
  insert into public.profiles (user_id, email, nome, avatar_url, role)
  values (new.id, new.email,
          coalesce(new.raw_user_meta_data ->> 'full_name', new.raw_user_meta_data ->> 'name'),
          new.raw_user_meta_data ->> 'avatar_url',
          case when n = 0 then 'admin' else 'user' end)
  on conflict (user_id) do nothing;
  insert into public.user_settings (user_id) values (new.id) on conflict (user_id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function public.handle_new_user();

-- ---------------------------------------------------------------- feed: guarda só os últimos N
create or replace function public.trim_pump_feed(p_user uuid, p_keep integer default 500)
returns void
language sql
security definer
set search_path = ''
as $$
  delete from public.pump_feed
   where user_id = p_user
     and id < coalesce((select id from public.pump_feed where user_id = p_user
                         order by id desc offset greatest(p_keep, 1) - 1 limit 1), 0);
$$;
revoke all on function public.trim_pump_feed(uuid, integer) from public, anon, authenticated;
revoke all on function public.handle_new_user() from public, anon, authenticated;
grant execute on function public.trim_pump_feed(uuid, integer) to service_role;
