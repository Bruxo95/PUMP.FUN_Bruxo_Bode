-- 0.32.124: compras barradas do Top traders, acompanhadas por 15 min como se tivessem entrado. Só o backend lê e grava (RLS sem política).
create table if not exists public.top_shadows (
  id    text primary key,
  em    timestamptz not null default now(),
  data  jsonb not null default '{}'::jsonb
);
create index if not exists top_shadows_em on public.top_shadows (em desc);
alter table public.top_shadows enable row level security;
revoke all on public.top_shadows from anon, authenticated;

do $$ begin
  if exists (select 1 from pg_roles where rolname = 'leitor_ia') then
    grant select on public.top_shadows to leitor_ia;
    create policy "leitor_ia: ler" on public.top_shadows for select to leitor_ia using (true);
  end if;
end $$;
