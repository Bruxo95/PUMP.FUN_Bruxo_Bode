-- 0.32.85 (dono, 30/10: "tentei salvar a chave do Jev e não salvou"): a tabela app_secrets só aceitava 4 nomes de chave
-- (check app_secrets_nome_check). Libera 'jev_api_key'. E toda análise do Jev passa a ter tabela própria no Supabase.
alter table public.app_secrets drop constraint if exists app_secrets_nome_check;
alter table public.app_secrets add constraint app_secrets_nome_check check (
  nome in ('solanatracker_api_key', 'pumpportal_api_key', 'jupiter_api_key', 'rpc_url', 'jev_api_key')
);

-- Cada pergunta feita ao Jev ao vivo (sinais e lançamentos da Aba do Bruxo): o que foi mandado, o que ele respondeu
-- (ou o erro) e o tempo. O resultado do token fica no próprio sinal (bruxo_signals) e é ligado por sinal_id.
create table if not exists public.jev_decisions (
  id          bigint generated always as identity primary key,
  em          timestamptz not null default now(),
  fonte       text not null,                     -- bruxo | lancamento
  sinal_id    text,
  mint        text,
  symbol      text,
  acao        text,                              -- entrar | esperar | evitar (null = erro)
  p_entrar    numeric,
  p_esperar   numeric,
  p_evitar    numeric,
  confianca   numeric,
  qualidade   numeric,                           -- 0 a 4
  armadilha   numeric,                           -- 0 a 1
  ms          integer,
  tokens_in   integer,
  erro        text,
  estado      jsonb not null default '{}'::jsonb -- números mandados (nada de chave ou carteira)
);
create index if not exists jev_decisions_em on public.jev_decisions (em desc);
create index if not exists jev_decisions_sinal on public.jev_decisions (sinal_id);
alter table public.jev_decisions enable row level security;
revoke all on public.jev_decisions from anon, authenticated;

-- Uso do Jev por dia (ao vivo e estudo do passado): perguntas, erros, tokens e tempo. Os limites por dia
-- (3.000 ao vivo, 20.000 do passado) continuam valendo depois de um reinício.
create table if not exists public.jev_usage (
  dia         date not null,
  tipo        text not null check (tipo in ('ao_vivo', 'passado')),
  calls       integer not null default 0,
  erros       integer not null default 0,
  tokens_in   bigint not null default 0,
  ms          bigint not null default 0,
  atualizado  timestamptz not null default now(),
  primary key (dia, tipo)
);
alter table public.jev_usage enable row level security;
revoke all on public.jev_usage from anon, authenticated;

do $$ begin
  if exists (select 1 from pg_roles where rolname = 'leitor_ia') then
    grant select on public.jev_decisions, public.jev_usage, public.jev_backtest to leitor_ia;
    create policy "leitor_ia: ler" on public.jev_decisions for select to leitor_ia using (true);
    create policy "leitor_ia: ler" on public.jev_usage for select to leitor_ia using (true);
    create policy "leitor_ia: ler" on public.jev_backtest for select to leitor_ia using (true);
  end if;
end $$;
