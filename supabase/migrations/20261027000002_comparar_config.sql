-- 0.31.34 (pedido do dono em 2026-10-27): análises salvas da tela "Comparar config copiada" (usuário X × usuário Y
-- depois de copiar a configuração), para uma IA estudar ganhos e perdas. Quem grava é o backend; o navegador só lê as
-- próprias linhas.
create table if not exists public.config_compare_reports (
  id         bigserial primary key,
  user_id    uuid not null references auth.users (id) on delete cascade,
  offer_id   bigint,
  data       jsonb not null default '{}'::jsonb,
  texto      text,
  criado_em  timestamptz not null default now()
);
create index if not exists config_compare_reports_user on public.config_compare_reports (user_id, criado_em desc);
alter table public.config_compare_reports enable row level security;
drop policy if exists "comparar: ver as próprias" on public.config_compare_reports;
create policy "comparar: ver as próprias" on public.config_compare_reports
  for select to authenticated using (user_id = (select auth.uid()));
revoke insert, update, delete on public.config_compare_reports from anon, authenticated;
revoke all on public.config_compare_reports from anon;

-- Atualização de configuração copiada: quando a origem muda a configuração, o backend cria um convite do tipo
-- "atualizacao" (base_id = cópia anterior) para quem ainda usa a configuração idêntica decidir aplicar ou não.
alter table public.config_offers add column if not exists tipo text not null default 'convite';
alter table public.config_offers add column if not exists base_id bigint;
