-- Evoluções do cérebro (0.31.85, pedido do dono em 2026-10-28): cada mudança da Base geral (faixa bloqueada/liberada,
-- nova melhor regra de saída) vira E1, E2… com a foto das faixas bloqueadas, para relatório, comparação e "voltar para".
-- Dados gerais, sem dono: só o backend lê e grava (RLS ligado e sem política para o navegador).
create table if not exists public.base_evolutions (
  numero    integer primary key,
  em        timestamptz not null default now(),
  estado    jsonb not null default '{}'::jsonb,
  mudancas  jsonb not null default '[]'::jsonb
);
alter table public.base_evolutions enable row level security;
revoke all on public.base_evolutions from anon, authenticated;
