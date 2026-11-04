-- 0.32.208 (pedido do dono, 04/11: mais um projeto isolado, como a BNB): Robinhood Chain, etapa 1 só lê a rede.
-- hood_state: ponto da leitura (último bloco lido) e a regra do ranking. Os trades ficam só na memória do servidor
-- (a rede tem ~470 trocas por minuto; guardar cada uma pesaria no banco). Só o backend lê e grava.
create table if not exists public.hood_state (
  k   text primary key,
  v   jsonb not null default '{}'::jsonb,
  em  timestamptz not null default now()
);
alter table public.hood_state enable row level security;
revoke all on public.hood_state from anon, authenticated;

do $$ begin
  if exists (select 1 from pg_roles where rolname = 'leitor_ia') then
    grant select on public.hood_state to leitor_ia;
    create policy "leitor_ia: ler" on public.hood_state for select to leitor_ia using (true);
  end if;
end $$;
