-- Aprendizado diário (0.10.0): uma linha por usuário por dia com o resumo do que os top traders fizeram,
-- o resultado das cópias e as sugestões do dia. Permite comparar semanas (ex.: trader lucrativo em vários dias).
-- Autorizado pelo dono em 2026-10-25. Mesmo padrão das outras tabelas: o navegador só lê as próprias linhas e
-- nunca grava; quem grava é o backend (service role).
create table if not exists public.learning_daily (
  user_id        uuid not null references auth.users (id) on delete cascade,
  dia            date not null,
  data           jsonb not null,
  atualizado_em  timestamptz not null default now(),
  primary key (user_id, dia)
);

alter table public.learning_daily enable row level security;

drop policy if exists "aprendizado: ver o próprio" on public.learning_daily;
create policy "aprendizado: ver o próprio" on public.learning_daily
  for select to authenticated using (user_id = (select auth.uid()));

revoke insert, update, delete on public.learning_daily from anon, authenticated;
revoke all on public.learning_daily from anon;
