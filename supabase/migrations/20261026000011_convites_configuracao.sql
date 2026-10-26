-- Convites de configuração (0.31.17, pedido do dono em 2026-10-26): "usuário X quer compartilhar a configuração dele";
-- quem recebe aceita e aplica, ou recusa. Os valores vão no convite. Nunca leva chaves, carteira real nem Telegram
-- (filtrado no backend). O navegador só lê os convites recebidos; quem grava é o backend.
create table if not exists public.config_offers (
  id             bigserial primary key,
  de_user        uuid not null references auth.users (id) on delete cascade,
  para_user      uuid not null references auth.users (id) on delete cascade,
  de_nome        text,
  parte          text,
  valores        jsonb not null default '{}'::jsonb,
  status         text not null default 'pendente' check (status in ('pendente', 'aceita', 'recusada')),
  criado_em      timestamptz not null default now(),
  respondido_em  timestamptz
);
create index if not exists config_offers_para on public.config_offers (para_user, status, criado_em desc);
alter table public.config_offers enable row level security;
drop policy if exists "convites: ver os recebidos" on public.config_offers;
create policy "convites: ver os recebidos" on public.config_offers
  for select to authenticated using (para_user = (select auth.uid()));
revoke insert, update, delete on public.config_offers from anon, authenticated;
revoke all on public.config_offers from anon;
