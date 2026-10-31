-- 0.32.114 (pedido do dono, 31/10): estudo do Resultado por período, guardado para a Base geral aprender.
-- origem = 'manual' (botão Estudar) ou 'dia' (dia fechado, gravado sozinho). Só o backend lê e grava (RLS sem política).
create table if not exists public.result_studies (
  id       text primary key,
  user_id  uuid not null references auth.users (id) on delete cascade,
  real     boolean not null default false,
  origem   text not null check (origem in ('manual', 'dia')),
  dia      date,
  em       timestamptz not null default now(),
  data     jsonb not null default '{}'::jsonb
);
create index if not exists result_studies_user_em on public.result_studies (user_id, em desc);
create index if not exists result_studies_dia on public.result_studies (origem, dia desc);
alter table public.result_studies enable row level security;
revoke all on public.result_studies from anon, authenticated;

do $$ begin
  if exists (select 1 from pg_roles where rolname = 'leitor_ia') then
    grant select on public.result_studies to leitor_ia;
    create policy "leitor_ia: ler" on public.result_studies for select to leitor_ia using (true);
  end if;
end $$;
