-- 0.32.225: banco do ARQUIVO do PUMP FUN COPY no Postgres da VPS (stack "postgres"). Rodar UMA vez, como o usuário postgres:
--   Portainer → Containers → postgres_postgres… → Console (/bin/sh) → psql -U postgres → colar este arquivo.
-- Antes de colar, troque TROQUE_ESTA_SENHA por uma senha só de letras e números (24+ caracteres). Não mande a senha no chat.
-- Só dados PÚBLICOS entram aqui (trades da BNB, vida dos tokens, estudo do Jev). Nada de usuário, chave ou posição.

create role pump_arquivo nologin;                                   -- papel que o PostgREST assume (vem no token)
create role pump_arquivo_auth login noinherit password 'TROQUE_ESTA_SENHA';
grant pump_arquivo to pump_arquivo_auth;
create database pump_arquivo;
\c pump_arquivo

create table public.arquivo (
  tabela      text             not null,                            -- tabela de origem no Supabase
  pk          text             not null,                            -- chave da linha na origem
  t           double precision not null,                            -- hora (segundos desde 1970)
  dados       jsonb            not null,                            -- a linha inteira
  arquivado_em timestamptz     not null default now(),
  primary key (tabela, pk)
);
create index arquivo_tabela_t on public.arquivo (tabela, t);
revoke all on schema public from public;
grant usage on schema public to pump_arquivo;
grant select, insert, update on public.arquivo to pump_arquivo;     -- sem delete: o arquivo só cresce
