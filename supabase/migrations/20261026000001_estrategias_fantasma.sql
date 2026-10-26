-- Estratégias fantasma (0.18.0): resultado agregado de cada variante de saída testada em paralelo às cópias
-- fictícias do usuário (uma linha por usuário). Pedido do dono em 2026-10-26. Mesmo padrão das outras tabelas:
-- o navegador só lê a própria linha e nunca grava; quem grava é o backend (service role).
create table if not exists public.ghost_stats (
  user_id        uuid primary key references auth.users (id) on delete cascade,
  data           jsonb not null,
  atualizado_em  timestamptz not null default now()
);

alter table public.ghost_stats enable row level security;

drop policy if exists "fantasmas: ver o próprio" on public.ghost_stats;
create policy "fantasmas: ver o próprio" on public.ghost_stats
  for select to authenticated using (user_id = (select auth.uid()));

revoke insert, update, delete on public.ghost_stats from anon, authenticated;
revoke all on public.ghost_stats from anon;
