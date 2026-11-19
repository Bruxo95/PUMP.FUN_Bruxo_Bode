-- 0.32.378 (pedido do dono, 19/11/2026): histórico PERMANENTE de todo token que migrou para a PumpSwap (BOOST), entrando ou não.
-- Uma linha por token, gravada pelo servidor HIST_MIN minutos (padrão 20) depois da migração: série de preço, preço em cada
-- minuto, topo, dump (quanto e quando), compras/vendas, DEV, trava, scam e o nosso resultado. Base das métricas do BOOST.
-- Só o servidor lê e grava (RLS ligado, sem política para o navegador). Nada é apagado.
create table if not exists public.boost_history (
  mint text primary key,
  creator text,
  symbol text,
  t0 timestamptz not null,                 -- hora da migração
  analisado timestamptz not null default now(),
  classe text,                             -- subiu | lateral | caiu | despejou | sem preço
  top_pct numeric, top_s integer,          -- maior alta (% do 1º preço) e quando (s depois da migração)
  dump_pct numeric, dump_s integer,        -- maior queda depois do topo e quando
  fim_pct numeric,                         -- onde estava na análise
  scam boolean not null default false,
  trava boolean not null default false,
  entrou integer not null default 0,       -- quantas contas entraram
  pnl_sol numeric,
  dados jsonb not null default '{}'::jsonb -- registro completo (série, minutos, DEV, filtros…)
);
create index if not exists boost_history_t0 on public.boost_history (t0 desc);
create index if not exists boost_history_creator on public.boost_history (creator);
create index if not exists boost_history_classe on public.boost_history (classe);
alter table public.boost_history enable row level security;
revoke all on public.boost_history from anon, authenticated;

do $$
begin
  if exists (select 1 from pg_roles where rolname = 'leitor_ia') then
    grant select on public.boost_history to leitor_ia;
    create policy "leitor_ia: ler" on public.boost_history for select to leitor_ia using (true);
  end if;
end $$;
