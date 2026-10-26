-- Ajuste automático (0.31.14, pedido do dono em 2026-10-26): cada mudança que o servidor faz sozinho nas opções da
-- carteira fictícia (regra de saída aplicada, mantida ou desfeita; trader pausado), com o motivo e os valores de antes.
-- O navegador só lê as próprias linhas; quem grava é o backend.
create table if not exists public.auto_tune_log (
  id       bigserial primary key,
  user_id  uuid not null references auth.users (id) on delete cascade,
  tipo     text not null check (tipo in ('saida', 'trader')),
  acao     text not null check (acao in ('aplicou', 'manteve', 'desfez', 'pausou')),
  motivo   text,
  detalhe  jsonb not null default '{}'::jsonb,
  em       timestamptz not null default now()
);
create index if not exists auto_tune_log_user_em on public.auto_tune_log (user_id, em desc);
alter table public.auto_tune_log enable row level security;
drop policy if exists "ajuste automatico: ver o proprio" on public.auto_tune_log;
create policy "ajuste automatico: ver o proprio" on public.auto_tune_log
  for select to authenticated using (user_id = (select auth.uid()));
revoke insert, update, delete on public.auto_tune_log from anon, authenticated;
revoke all on public.auto_tune_log from anon;
