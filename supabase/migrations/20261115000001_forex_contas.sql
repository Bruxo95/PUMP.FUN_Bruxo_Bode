-- 0.32.368 (pedido do dono, 15/11/2026): Projeto Forex, etapa 1. Uma linha por conta com as regras da cópia e a carteira
-- FICTÍCIA (docs/FOREX.md). O histórico que cresce (trades dos mestres, curva de patrimônio, ordens copiadas) fica no Postgres
-- local (deploy/forex.sql). O navegador só lê a própria linha; quem grava é o servidor (service key).
create table if not exists public.forex_contas (
  user_id     uuid primary key references public.profiles(user_id) on delete cascade,
  dados       jsonb not null default '{}'::jsonb,
  atualizado  timestamptz not null default now()
);
alter table public.forex_contas enable row level security;
revoke all on public.forex_contas from anon, authenticated;
grant select on public.forex_contas to authenticated;
drop policy if exists "forex_contas: ler a própria" on public.forex_contas;
create policy "forex_contas: ler a própria" on public.forex_contas for select to authenticated using (user_id = auth.uid());

do $$ begin
  if exists (select 1 from pg_roles where rolname = 'leitor_ia') then
    grant select on public.forex_contas to leitor_ia;
    create policy "leitor_ia: ler" on public.forex_contas for select to leitor_ia using (true);
  end if;
end $$;
