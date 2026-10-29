-- 0.32.48 (pedido do dono, 29/10): histórico dos relatórios das Carteiras em estudo enviados ao ChatGPT, com o estado
-- (gerado → esperando a resposta → resposta recebida → analisado pelo Claude) e a resposta colada. Só o backend lê e grava.
create table if not exists public.study_ai_reports (
  id           text primary key,
  user_id      uuid not null references auth.users (id) on delete cascade,
  em           timestamptz not null default now(),
  carteiras    jsonb not null default '[]'::jsonb,
  texto        text not null default '',
  status       text not null default 'gerado' check (status in ('gerado', 'esperando', 'resposta')),
  auto         boolean not null default false,
  copiado_em   timestamptz,
  resposta     text,
  resposta_em  timestamptz
);
create index if not exists study_ai_reports_user_em on public.study_ai_reports (user_id, em desc);
alter table public.study_ai_reports enable row level security;
revoke all on public.study_ai_reports from anon, authenticated;
