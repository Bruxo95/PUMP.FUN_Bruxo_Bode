-- 0.32.319 (pedido do dono, 11/11/2026: "as configurações ficam salvas e eu posso voltar para o que era antes, isso já existe no PUMP FUN
-- Solana; implementa no /hood"). Uma versão por mudança da configuração da cópia da Robinhood (FICTÍCIA e REAL, traders e bloqueios).
-- Ligar a REAL, ligar a fictícia e o saldo inicial nunca entram (voltar nunca liga nada). Só o backend lê e grava.
create table if not exists public.hood_config_versions (
  user_id  uuid not null references auth.users (id) on delete cascade,
  n        integer not null,
  em       timestamptz not null default now(),
  origem   text not null default '',
  cfg      jsonb not null default '{}'::jsonb,
  primary key (user_id, n)
);
alter table public.hood_config_versions enable row level security;
revoke all on public.hood_config_versions from anon, authenticated;
