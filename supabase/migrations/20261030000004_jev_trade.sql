-- 0.32.87 (áudio do Bruxo, 30/10): aba Jev Trade. Cada token novo com 40+ detentores que o Jev acompanhou em simulação:
-- leituras por minuto, decisões, vendas e resultado. Só backend; nada aqui é posição de usuário ou carteira.
create table if not exists public.jev_trades (
  id    text primary key,                 -- mint do token
  em    timestamptz not null default now(),
  data  jsonb not null default '{}'::jsonb
);
create index if not exists jev_trades_em on public.jev_trades (em desc);
alter table public.jev_trades enable row level security;
revoke all on public.jev_trades from anon, authenticated;

alter table public.jev_usage drop constraint if exists jev_usage_tipo_check;
alter table public.jev_usage add constraint jev_usage_tipo_check check (tipo in ('ao_vivo', 'passado', 'trade'));

do $$ begin
  if exists (select 1 from pg_roles where rolname = 'leitor_ia') then
    grant select on public.jev_trades to leitor_ia;
    create policy "leitor_ia: ler" on public.jev_trades for select to leitor_ia using (true);
  end if;
end $$;
