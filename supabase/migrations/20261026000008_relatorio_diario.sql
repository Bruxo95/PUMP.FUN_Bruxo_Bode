-- Relatório do dia (0.31.5, pedido do dono em 2026-10-26): fotos dos números da Visão geral a cada 30 min, diagnóstico
-- e sugestões do dia. Uma linha por usuário por dia. O navegador só lê as próprias linhas; quem grava é o backend.
create table if not exists public.daily_report (
  user_id        uuid not null references auth.users (id) on delete cascade,
  dia            date not null,
  data           jsonb not null,
  atualizado_em  timestamptz not null default now(),
  primary key (user_id, dia)
);
alter table public.daily_report enable row level security;
drop policy if exists "relatorio diario: ver o proprio" on public.daily_report;
create policy "relatorio diario: ver o proprio" on public.daily_report
  for select to authenticated using (user_id = (select auth.uid()));
revoke insert, update, delete on public.daily_report from anon, authenticated;
revoke all on public.daily_report from anon;
