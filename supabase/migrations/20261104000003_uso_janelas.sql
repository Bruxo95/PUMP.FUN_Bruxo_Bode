-- 0.32.190 (pedido do dono): as janelas de 1/6/12/24 h do uso de cada serviço e de cada tela zeravam a cada atualização do
-- sistema. Uma linha só (k = 'janelas') com os blocos de 10 min das últimas 24 h. Só o backend lê e grava (RLS sem política).
create table if not exists public.api_usage_janelas (
  k            text primary key,
  v            jsonb not null default '{}'::jsonb,
  atualizado_em timestamptz not null default now()
);
alter table public.api_usage_janelas enable row level security;
revoke all on public.api_usage_janelas from anon, authenticated;

do $$ begin
  if exists (select 1 from pg_roles where rolname = 'leitor_ia') then
    grant select on public.api_usage_janelas to leitor_ia;
    create policy "leitor_ia: ler" on public.api_usage_janelas for select to leitor_ia using (true);
  end if;
end $$;
