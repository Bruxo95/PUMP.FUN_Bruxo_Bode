-- 0.32.199 (pedido do dono, 04/11): cada versão da configuração de cada conta, para ver o que mudou e voltar para uma
-- versão anterior. Só o backend lê e grava (RLS sem política para o navegador). Não guarda chave nenhuma.
create table if not exists public.config_versions (
  user_id  uuid not null references auth.users (id) on delete cascade,
  n        integer not null,
  em       timestamptz not null default now(),
  origem   text not null default '',
  settings jsonb not null default '{}'::jsonb,
  mudou    jsonb not null default '[]'::jsonb,
  primary key (user_id, n)
);
alter table public.config_versions enable row level security;
revoke all on public.config_versions from anon, authenticated;

do $$ begin
  if exists (select 1 from pg_roles where rolname = 'leitor_ia') then
    grant select on public.config_versions to leitor_ia;
    create policy "leitor_ia: ler" on public.config_versions for select to leitor_ia using (true);
  end if;
end $$;
