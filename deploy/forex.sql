-- 0.32.368 (pedido do dono, 15/11/2026): Projeto Forex — banco LOCAL (Postgres da VPS, stack "postgres").
-- Rodar UMA vez, como o usuário postgres:
--   Portainer → Containers → postgres_postgres… → Console (/bin/sh) → psql -U postgres → colar este arquivo.
-- Antes de colar, troque TROQUE_ESTA_SENHA por uma senha só de letras e números (24+ caracteres). Não mande a senha no chat.
--
-- O que fica AQUI: o que cresce rápido e é lido pelo motor (trades dos mestres, eventos de ordem, curva de patrimônio, notas,
-- ordens copiadas). O que fica no SUPABASE: usuários (profiles), planos e as CREDENCIAIS das corretoras (cifradas com
-- AES-256-GCM em user_secrets/app_secrets). Este banco NUNCA guarda senha, token ou chave: só o nome do segredo (cred_ref).

create role pump_forex nologin;                                    -- papel que o serviço assume
create role pump_forex_auth login noinherit password 'TROQUE_ESTA_SENHA';
grant pump_forex to pump_forex_auth;
create database pump_forex;
\c pump_forex

create schema forex;
revoke all on schema public from public;
grant usage on schema forex to pump_forex;

-- ---------------------------------------------------------------------------------------------------------------- tipos
create type forex.plataforma  as enum ('ctrader', 'mt5', 'mt4');
create type forex.tipo_conta  as enum ('real', 'demo');
create type forex.lado        as enum ('buy', 'sell');
create type forex.status_conn as enum ('pendente', 'conectado', 'erro', 'pausado', 'desligado');
create type forex.modo_lote   as enum ('equity', 'multiplicador', 'fixo');
create type forex.evento      as enum ('abriu', 'modificou', 'fechou_parcial', 'fechou');
create type forex.status_copia as enum ('pendente', 'enviada', 'executada', 'rejeitada', 'ignorada', 'simulada');

-- ---------------------------------------------------------------------------------------------------------------- corretoras e ativos
create table forex.corretoras (
  id          serial primary key,
  nome        text not null,
  plataforma  forex.plataforma not null,
  servidor    text,                                                -- ex.: "ICMarketsSC-Live" (MT5) ou o id do cTrader
  fuso_min    integer not null default 0,                          -- fuso do servidor em minutos (MT5 grava hora do servidor)
  unique (plataforma, nome, servidor)
);

-- especificação do ativo em CADA corretora (o mesmo EURUSD pode ter lote mínimo e passo diferentes)
create table forex.ativos (
  corretora_id  integer not null references forex.corretoras(id) on delete cascade,
  simbolo       text not null,                                     -- como a corretora escreve (EURUSD, EURUSD.r, XAUUSD…)
  simbolo_base  text not null,                                     -- normalizado (EURUSD) para casar mestre × seguidor
  contrato      numeric(18,4) not null default 100000,             -- unidades por 1 lote
  lote_min      numeric(10,4) not null default 0.01,
  lote_passo    numeric(10,4) not null default 0.01,
  lote_max      numeric(10,4) not null default 100,
  pip           numeric(12,8) not null default 0.0001,             -- 0.01 nos pares com JPY e no ouro
  moeda_lucro   text not null default 'USD',
  primary key (corretora_id, simbolo)
);
create index ativos_base on forex.ativos (simbolo_base);

-- ---------------------------------------------------------------------------------------------------------------- mestres
create table forex.traders_monitored (
  id               bigserial primary key,
  plataforma       forex.plataforma not null,
  corretora_id     integer references forex.corretoras(id),
  conta_login      text not null,                                  -- número da conta (MT5) ou ctidTraderAccountId (cTrader)
  tipo_conta       forex.tipo_conta not null,                      -- conferido na conexão (cTrader: isLive; MT5: trade_mode)
  moeda            text not null default 'USD',
  alavancagem      integer,
  apelido          text,
  adicionado_por   uuid,                                           -- profiles.user_id no Supabase (sem FK: outro banco)
  cred_ref         text,                                           -- NOME do segredo no Supabase (ex.: "fx_mestre_12"); nunca o valor
  status           forex.status_conn not null default 'pendente',
  status_msg       text,
  conectado_em     timestamptz,
  ultimo_evento_em timestamptz,
  primeiro_trade_em timestamptz,                                   -- para o filtro de 60+ dias
  criado_em        timestamptz not null default now(),
  unique (plataforma, corretora_id, conta_login)
);
create index traders_status on forex.traders_monitored (status);

-- histórico normalizado de ordens/posições (uma linha por posição; parciais somam em volume_fechado)
create table forex.trades_history (
  trader_id      bigint not null references forex.traders_monitored(id) on delete cascade,
  ticket         text not null,                                    -- positionId (cTrader) / position ticket (MT5)
  simbolo        text not null,
  simbolo_base   text not null,
  lado           forex.lado not null,
  volume         numeric(14,4) not null,                           -- lotes na abertura
  volume_fechado numeric(14,4) not null default 0,
  abriu_em       timestamptz not null,
  preco_entrada  numeric(18,8) not null,
  sl             numeric(18,8),
  tp             numeric(18,8),
  fechou_em      timestamptz,
  preco_saida    numeric(18,8),
  comissao       numeric(14,4) not null default 0,
  swap           numeric(14,4) not null default 0,
  lucro          numeric(14,4),                                    -- líquido (lucro + comissão + swap), moeda da conta
  magic          bigint,                                           -- MT5: número do robô (EA) que abriu
  aberta         boolean generated always as (fechou_em is null) stored,
  bruto          jsonb,                                            -- resposta original da API (para conferir depois)
  primary key (trader_id, ticket)
);
create index trades_fechou on forex.trades_history (trader_id, fechou_em);
create index trades_abertas on forex.trades_history (trader_id) where fechou_em is null;
create index trades_base on forex.trades_history (simbolo_base, abriu_em);

-- cada evento recebido da corretora, na ordem (é a fila que o motor de cópia lê; também serve para medir atraso)
create table forex.order_events (
  id            bigserial primary key,
  trader_id     bigint not null references forex.traders_monitored(id) on delete cascade,
  ticket        text not null,
  evento        forex.evento not null,
  ocorreu_em    timestamptz not null,                              -- hora do evento na corretora
  recebido_em   timestamptz not null default now(),                -- hora que chegou aqui
  dados         jsonb not null,                                    -- lado, volume, preço, sl, tp…
  unique (trader_id, ticket, evento, ocorreu_em)                   -- o mesmo evento repetido pela API não entra duas vezes
);
create index eventos_trader_t on forex.order_events (trader_id, ocorreu_em);

-- curva de saldo e patrimônio (para drawdown e Sharpe); uma foto por minuto com posição aberta, uma por hora sem
create table forex.equity_snapshots (
  trader_id   bigint not null references forex.traders_monitored(id) on delete cascade,
  t           timestamptz not null,
  saldo       numeric(16,4) not null,
  patrimonio  numeric(16,4) not null,                              -- equity = saldo + flutuante
  margem      numeric(16,4),
  margem_livre numeric(16,4),
  depositos   numeric(16,4) not null default 0,                    -- depósito/saque no intervalo (não é lucro nem prejuízo)
  primary key (trader_id, t)
);
create index equity_t_brin on forex.equity_snapshots using brin (t);

-- nota de cada mestre a cada cálculo (o ranking usa a mais nova; as antigas mostram a evolução)
create table forex.trader_scores (
  trader_id     bigint not null references forex.traders_monitored(id) on delete cascade,
  calculado_em  timestamptz not null default now(),
  dias          integer not null,
  trades        integer not null,
  retorno_pct   numeric(12,4),
  mdd_pct       numeric(8,4),
  profit_factor numeric(10,4),
  sharpe        numeric(10,4),
  consistencia  numeric(6,4),                                      -- 0..1 (fração de semanas positivas, com peso)
  martingale    numeric(6,4),                                      -- 0..1 (sinal de aumentar lote depois de perder)
  grade         numeric(6,4),                                      -- 0..1 (sinal de grade sem stop)
  score         numeric(6,2) not null,                             -- 0..100
  elegivel      boolean not null,
  motivos       text[] not null default '{}',                      -- por que não é elegível (ou alertas)
  primary key (trader_id, calculado_em)
);
create view forex.ranking as
  select distinct on (s.trader_id) s.*, t.apelido, t.plataforma, t.tipo_conta, t.status
  from forex.trader_scores s join forex.traders_monitored t on t.id = s.trader_id
  order by s.trader_id, s.calculado_em desc;

-- ---------------------------------------------------------------------------------------------------------------- seguidores
create table forex.follower_accounts (
  id           bigserial primary key,
  user_id      uuid not null,                                      -- profiles.user_id no Supabase
  plataforma   forex.plataforma not null,
  corretora_id integer references forex.corretoras(id),
  conta_login  text,
  tipo_conta   forex.tipo_conta not null default 'demo',
  simulada     boolean not null default true,                      -- true = carteira fictícia do sistema (sem corretora)
  saldo_inicial numeric(16,4),                                     -- só na simulada
  cred_ref     text,                                               -- NOME do segredo no Supabase; nunca o valor
  real_ligada  boolean not null default false,                     -- execução REAL começa desligada (regra do projeto)
  criado_em    timestamptz not null default now()
);
create index followers_user on forex.follower_accounts (user_id);

-- quem segue quem (M:N) e a regra do lote
create table forex.copy_relations (
  id                bigserial primary key,
  follower_id       bigint not null references forex.follower_accounts(id) on delete cascade,
  trader_id         bigint not null references forex.traders_monitored(id) on delete cascade,
  modo_lote         forex.modo_lote not null default 'equity',     -- equity: lote × (patrimônio seguidor ÷ patrimônio mestre)
  multiplicador     numeric(10,4) not null default 1,              -- usado em "multiplicador" e como ajuste fino no "equity"
  lote_fixo         numeric(10,4),                                 -- usado em "fixo"
  lote_max          numeric(10,4) not null default 1,              -- teto por ordem
  slippage_max_pips numeric(8,2) not null default 3,               -- não entra se o preço já andou mais que isso
  atraso_max_s      integer not null default 10,                   -- não copia evento mais velho que isso
  copiar_sl_tp      boolean not null default true,
  simbolos          text[],                                        -- null = todos (base normalizada, ex.: {EURUSD,XAUUSD})
  perda_dia_max     numeric(16,4),                                 -- para de copiar no dia se perder isso
  ativa             boolean not null default true,
  criado_em         timestamptz not null default now(),
  unique (follower_id, trader_id)
);
create index relations_trader on forex.copy_relations (trader_id) where ativa;

-- cada ordem espelhada (idempotente: o mesmo evento do mestre nunca gera duas ordens no seguidor)
create table forex.copy_orders (
  id              bigserial primary key,
  relation_id     bigint not null references forex.copy_relations(id) on delete cascade,
  evento_id       bigint references forex.order_events(id),
  ticket_mestre   text not null,
  ticket_seguidor text,
  evento          forex.evento not null,
  lote_mestre     numeric(14,4),
  lote_calculado  numeric(14,4),
  preco_mestre    numeric(18,8),
  preco_execucao  numeric(18,8),
  slippage_pips   numeric(10,2),
  status          forex.status_copia not null default 'pendente',
  motivo          text,
  tentativas      integer not null default 0,
  evento_em       timestamptz not null,
  executada_em    timestamptz,
  atraso_ms       integer,
  unique (relation_id, ticket_mestre, evento, evento_em)
);
create index copy_status on forex.copy_orders (status) where status in ('pendente', 'enviada');

-- ---------------------------------------------------------------------------------------------------------------- acesso
grant select, insert, update, delete on all tables in schema forex to pump_forex;
grant usage, select on all sequences in schema forex to pump_forex;
grant select on forex.ranking to pump_forex;
alter default privileges in schema forex grant select, insert, update, delete on tables to pump_forex;
alter default privileges in schema forex grant usage, select on sequences to pump_forex;
