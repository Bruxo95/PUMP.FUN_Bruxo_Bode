# PUMP FUN COPY — arquitetura e bancos de dados

Atualizado em 09/11/2026 (versão 0.32.271). Visão geral de onde cada parte roda, por onde os dados passam e onde ficam
guardados. Detalhes de cada arquivo e as regras de trabalho estão no `CLAUDE.md`; o uso do painel, no `GUIA-DO-PROJETO.md`.

## 1. Visão geral

```mermaid
flowchart TB
    USU["Navegador (PC e celular)<br/>/app · painel Solana<br/>/bnb · painel BNB"]

    subgraph SUPA["Supabase (nuvem)"]
        AUTH["Auth · login Google"]
        SDB[("Postgres + RLS<br/>usuários + últimos 7 dias")]
    end

    subgraph VPS["VPS — Docker Swarm + Portainer"]
        TRAEFIK["Traefik (HTTPS)<br/>pump.rachar.app.br"]
        subgraph STACK["stack pump_bruxo_bode"]
            API["Servidor PUMP FUN COPY<br/>FastAPI · PumpHub (um motor por usuário)<br/>SharedMonitor (Solana) · BnbWatch · HoodWatch"]
            PGR["pump_arquivo_api<br/>PostgREST (sem porta pública)"]
        end
        subgraph PGSTACK["stack postgres (compartilhado)"]
            PG[("PostgreSQL 14<br/>banco pump_arquivo<br/>histórico público · 90 dias")]
        end
    end

    EXT["APIs externas<br/>Solana RPC/WebSocket (Helius) · PumpPortal · Jupiter<br/>DexScreener · Solana Tracker · Jev (TypeSafe)<br/>BNB RPC · NodeReal · GoPlus"]

    USU -->|login| AUTH
    USU -->|HTTPS| TRAEFIK --> API
    API -->|service key| SDB
    API -->|token JWT, rede interna| PGR --> PG
    API -->|consultas e transações| EXT
```

- **Servidor (stack `pump_bruxo_bode`)**: um único container com o painel, a API e os robôs. Imagem
  `ghcr.io/bruxo95/pump.fun_bruxo_bode:latest`, publicada pelo GitHub Actions a cada push no `main`; o Portainer
  atualiza pelo webhook. Variáveis no stack (nunca no código): ver `deploy/portainer-stack.yml`.
- **Solana, BNB e Robinhood ficam separados**: cada rede tem o seu laço, as suas tabelas (`bnb_*`, `hood_*`) e o seu
  painel (`/app`, `/bnb`). Tela, chave ou opção da BNB vai no `/bnb`, nunca no `/app`.

## 2. Onde ficam os dados (divisão do banco, desde a 0.32.225)

```mermaid
flowchart TB
    subgraph S["Supabase — rápido, com RLS"]
        U["Usuários, perfis, configurações<br/>chaves criptografadas (AES-256-GCM)<br/>posições, trades, feed, audit_log"]
        R["Dados públicos recentes<br/>bnb_fm_trades (3 dias) · token_life (7 dias)"]
        J["jev_backtest: só a linha _run"]
    end
    subgraph L["Postgres da VPS — banco pump_arquivo"]
        A[("tabela arquivo<br/>(tabela, pk, t, dados jsonb)<br/>guarda 90 dias")]
    end
    R -- "a cada 30 min: copia → confere → só então apaga do Supabase<br/>(até 10 mil linhas por tabela)" --> A
    J -. "estudo do passado do Jev inteiro" .-> A
    A -- "leitura sob demanda: ranking BNB com mais de 7 dias,<br/>estudo do passado do Jev, casos da Base" --> APIX["Servidor"]
```

| Onde | O quê | Por quê |
|---|---|---|
| **Supabase** | Tudo que é de usuário (perfis, configurações, chaves, posições, trades, feed, audit_log) e os dados de consulta rápida dos últimos 7 dias | Tem RLS (cada usuário só vê o que é dele) e login Google |
| **Postgres da VPS** (`pump_arquivo`) | **Todo o histórico que cresce** (regra do dono, 09/11/2026: "tudo fica no Supabase por pouco tempo; quem guarda é o banco local"): trades da BNB com mais de 3 dias, vida dos tokens, calls, logs dos robôs (`robot_log`, `explore_cycles`), relatórios por aba (`tab_reports`), sinais da Aba do Bruxo, trades das carteiras em estudo (`wallet_trades`) com mais de 7 dias, estudo do passado do Jev | Tira peso do Supabase; guarda 90 dias |

Regras:
- **Nunca vão para o arquivo:** chaves, perfis, configurações, posições, trades das contas e `audit_log` (o painel e os relatórios
  leem o histórico inteiro deles e eles são pequenos). Logs e relatórios por conta podem ir: o arquivo não tem porta pública e
  só o servidor lê, sempre filtrando por `user_id` (`hub.hist_select`).
- O servidor **só apaga do Supabase depois de conferir** que a linha chegou ao arquivo. Arquivo fora do ar = nada é
  apagado, e o robô continua operando normal (só o histórico antigo fica indisponível).
- O arquivo guarda **90 dias**: uma vez por dia o que passou disso é apagado.
- Sem `ARQUIVO_URL` + `ARQUIVO_JWT_SECRET` no stack, o arquivo fica desligado e tudo volta a ficar só no Supabase.
- Nada de reler tabela inteira ao reiniciar: cada reinício carrega só a janela usada (ex.: BNB 7 dias); o resto vem
  sob demanda. Muitos deploys seguidos pesam no banco (incidente de 04/11/2026).

### Peças do arquivo

| Peça | Onde | Detalhe |
|---|---|---|
| Banco `pump_arquivo` | stack `postgres` (PostgreSQL 14, rede `vpsrachar`, host `postgres`) | Compartilhado com outros projetos da VPS; o PUMP só usa este banco. Criado uma vez com `deploy/arquivo.sql` |
| Usuários do banco | `pump_arquivo` (papel, sem login) e `pump_arquivo_auth` (login do PostgREST) | Permissões: ler, inserir, atualizar e apagar só na tabela `arquivo` |
| `pump_arquivo_api` | stack `pump_bruxo_bode` | PostgREST v12.2.3, sem porta pública e sem Traefik, sem acesso anônimo: só aceita token assinado com `ARQUIVO_JWT_SECRET` |
| Código | `app/arquivo.py` | `SPECS` (o que vai e com quantos dias), `mover`, `limpa`, `pages`; laço `hub.arquivo_loop` |
| Variáveis do stack | `ARQUIVO_DB_PASSWORD`, `ARQUIVO_JWT_SECRET` | A senha tem que ser a mesma do usuário `pump_arquivo_auth` no banco |
| Acompanhar | Painel → Administração → Status geral | Linhas "Arquivo (Postgres da VPS)" e "Movidas para o arquivo" |

Pendente: backup diário do banco `pump_arquivo` (hoje fica só no disco da VPS).

## 2.1 Esquema de bancos — regras para projetos novos e alterações

Vale para qualquer tela, robô ou projeto novo dentro do PUMP FUN COPY (Solana, BNB, Robinhood, Dormant…).

**Onde guardar cada dado**

| O dado é… | Vai para | Como |
|---|---|---|
| De um usuário (perfil, configuração, chave, posição, trade, feed, audit_log) | Supabase, sempre | Tabela com `user_id`, RLS ligado, leitura só da própria linha; o servidor sempre filtra por `user_id` |
| Chave/segredo | Supabase (`user_secrets` ou `app_secrets`) | Cifrado (AES-256-GCM, `APP_ENCRYPTION_KEY`); chave do sistema nova = acrescentar o nome na regra `app_secrets_nome_check` numa migração |
| Público e de consulta rápida (últimos dias) | Supabase | Tabela só do backend (RLS sem política para o navegador) |
| Público e histórico (mais de 7 dias) | Postgres da VPS (`pump_arquivo`, tabela `arquivo`) | Entra em `arquivo.SPECS`; o servidor move sozinho |
| Estado em memória que pode se perder | Nenhum banco | Só memória, recomeça no reinício |

**Tabela nova pública que cresce sem parar** (trades, sinais, fotos de tokens, logs):
1. Criar no Supabase por migração nova (`supabase/migrations/AAAAMMDDHHMMSS_nome.sql`, nunca editar uma aplicada), com RLS ligado.
2. Ter uma coluna de hora (`timestamptz` ou epoch) **com índice nela** (sem índice a cópia para o arquivo ordena a tabela
   inteira e cai no limite de tempo do Supabase, erro 57014 — foi o caso do `jev_backtest` até a 0.32.240).
3. Acrescentar em `app/arquivo.py` → `SPECS`: `{"tabela", "pk", "t", "tipo": "iso"|"epoch", "dias"}` (`dias` = quanto fica no
   Supabase; `fica` = chaves que nunca saem). O laço move a cada 30 min (5 min enquanto houver fila).
4. Leitura do passado: `hub.arquivo.pages(tabela, since, until)` junto com a leitura do Supabase. Nunca reler a tabela
   inteira no reinício: carregar só a janela usada; o resto sob demanda.
5. Leitura que pode pedir mais dias que o Supabase guarda: `hub.hist_select(tabela, filtros, coluna_de_hora, limite, desde)`
   (junta Supabase + arquivo, filtra o arquivo pelo conteúdo `dados->>campo`).

**Cuidados com o Supabase (plano grátis: 500 MB de banco, 1 GB de logs por mês)**
- Apagar linhas não diminui o tamanho: depois de mover muita coisa, rodar `VACUUM FULL <tabela>` (trava a tabela por alguns
  segundos). Em 05/11/2026 o banco caiu de 546 para 309 MB assim.
- Cada consulta conta nos logs: laço que roda sozinho não deve repetir consulta que já sabe a resposta (ex.: dias vazios do
  `rlog_daily` lembrados, perfil guardado 30 s).
- Muitos deploys seguidos = muitas cargas iniciais (incidente de 04/11/2026).

**Postgres da VPS**
- O servidor fala com ele pelo PostgREST `pump_arquivo_api` (stack `pump_bruxo_bode`, rede `vpsrachar`, sem porta pública).
- Erro `ConnectError: Name or service not known` no log `arquivo` = o serviço `pump_arquivo_api` não está rodando (ver
  Portainer → Services → `pump_bruxo_bode_pump_arquivo_api` → Logs). Enquanto isso nada é apagado do Supabase e o robô segue.
- Senha do usuário `pump_arquivo_auth` = `ARQUIVO_DB_PASSWORD` do stack; segredo do token = `ARQUIVO_JWT_SECRET`.

**APIs externas e o banco**: o uso de cada API é contado em `api_usage` (mês, por chave na Solana Tracker e no Helius)
e `api_usage_janelas` (1–24 h). Dado "bom de ter" (saldo, idade de carteira, carteiras novas) usa o RPC público grátis;
o Helius fica para leitura das carteiras copiadas, preços e execução.

## 3. Caminho de uma cópia de trade (Solana)

```mermaid
sequenceDiagram
    participant T as Trader copiado
    participant RPC as Solana (WebSocket/RPC)
    participant M as SharedMonitor
    participant E as Motor do usuário (PumpFun)
    participant PP as PumpPortal / Jupiter
    participant DB as Supabase
    T->>RPC: compra um token
    RPC-->>M: aviso da transação (uma conexão para todos)
    M->>E: compra lida (carteira, token, valor)
    E->>E: filtros e regras da conta
    E->>DB: posição FICTÍCIA
    alt execução REAL ligada (trava do servidor + do usuário)
        E->>PP: monta a transação
        E->>E: confere e assina com a chave do usuário (só na memória)
        E->>RPC: envia e confirma
        E->>DB: posição REAL
    end
```

## 4. Entrega

GitHub (`main`) → Actions: testes → migrações do Supabase (`banco`) → imagem no GHCR → webhook do Portainer → o job
confere a versão no `/health`. Mudanças no stack (serviços, variáveis) são feitas pelo dono no Portainer.
