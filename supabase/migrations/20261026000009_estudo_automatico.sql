-- Estudo automático de carteiras (0.31.13, pedido do dono em 2026-10-26): cada decisão da IA (adicionou, aprovou,
-- descartou) com o motivo e as características da carteira, para aprender que tipo de carteira compensa copiar.
-- O navegador só lê as próprias linhas; quem grava é o backend.
create table if not exists public.study_auto_log (
  id       bigserial primary key,
  user_id  uuid not null references auth.users (id) on delete cascade,
  wallet   text not null,
  acao     text not null check (acao in ('adicionou', 'aprovou', 'descartou')),
  motivo   text,
  info     jsonb not null default '{}'::jsonb,
  em       timestamptz not null default now()
);
create index if not exists study_auto_log_user_em on public.study_auto_log (user_id, em desc);
alter table public.study_auto_log enable row level security;
drop policy if exists "estudo automatico: ver o proprio" on public.study_auto_log;
create policy "estudo automatico: ver o proprio" on public.study_auto_log
  for select to authenticated using (user_id = (select auth.uid()));
revoke insert, update, delete on public.study_auto_log from anon, authenticated;
revoke all on public.study_auto_log from anon;
