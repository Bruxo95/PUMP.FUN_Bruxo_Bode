# CLAUDE.md — contexto do projeto PUMP.FUN Bruxo Bode

Leia isto antes de mexer no projeto. Este é o contexto compartilhado para pessoas, Claude Code,
Codex e Cursor. `AGENTS.md` é a entrada para Codex/Cursor e aponta para este arquivo.
Ao concluir tarefas, atualize aqui decisões, pendências e validações relevantes, sem duplicar a memória
por ferramenta e sem guardar segredos. Confira sempre o código: registros históricos não comprovam o estado atual.

## O que é
Nome no site: **PUMP FUN COPY** (logo, títulos e rodapé). O repositório e as pastas continuam com o nome
interno `PUMP.FUN_Bruxo_Bode`.

Sistema web **multiusuário** de cópia de traders da **pump.fun** (Solana). Cada pessoa entra com Google,
tem o próprio painel, carteira fictícia, posições, histórico, configurações, chaves e (opcional) execução real.
Nasceu da aba PUMP.FUN do repositório `github.com/Bruxo95/hermes-jev-trader` (só essa aba foi trazida;
Futuros, Spot, Solana DEX, DEX-CEX, Relógio, Macro, Hermes/Jev e Gate.io ficaram de fora). O mapa do que veio
de onde está em `docs/ORIGEM.md`.

- Produção: **https://pump.rachar.app.br** · versão no ar: `/health` (também no rodapé do painel)
- Repositório: `github.com/Bruxo95/PUMP.FUN_Bruxo_Bode` (privado), branch `main`
- Supabase: projeto `vnvfluimpqvxbvdbmwqa` (`https://vnvfluimpqvxbvdbmwqa.supabase.co`)

## Como trabalhar aqui (regras do dono)
- **Responder sempre em português do Brasil**, direto e sem jargão.
- Ao terminar cada tarefa: dizer **o que mudou, a versão** e **o que o dono precisa fazer**
  (ex.: "commit enviado ao GitHub; confira o resultado do Actions"). Dizer o que **não** foi testado de verdade.
- **Escopo de deploy definido pelo dono em 2026-10-25: somente GitHub.** Neste projeto, pedidos de
  "deploy", "publicar" ou "subir" autorizam commit + push apenas para
  `https://github.com/Bruxo95/PUMP.FUN_Bruxo_Bode`, branch `main`, e o workflow existente do GitHub Actions.
  Confirmar o remoto antes de enviar. Não acessar nem alterar VPS, SSH, Portainer, Supabase remoto,
  servidores, domínios ou outros projetos do dono sem uma solicitação explícita para essa ação.
  Nunca reutilizar credenciais, destinos ou configurações de deploy de outros projetos.
- Antes de mudar a lógica de cópia, manter o comportamento do original: os testes `test_pump_*`
  (`tests/test_pump.py`) são a referência.
- **Todos os testes rodam sem internet** (respostas de rede falsas com `httpx.MockTransport`).
- Rodar `pytest -q` antes de cada commit; commits pequenos com mensagem clara em português; push no `main`.
- **Subir a versão** em `app/version.py` a cada entrega (aparece em `/health` e no rodapé — é assim que o dono
  confere se o redeploy pegou).
- Visual: tema escuro "painel profissional" (estilo inspirado em rbp-security-template.vercel.app — só o
  estilo, nada copiado). Botões liga/desliga: **verde = ON, vermelho = OFF**. Tem que funcionar no celular
  (menu vira gaveta, sem rolagem lateral). JS sem handlers inline (a CSP bloqueia).

## Segurança (nunca quebrar)
- Nunca mostrar, logar ou devolver chaves pela API; a tela só mostra "configurada: sim/não".
- **Nunca pedir chaves ou senhas no chat** — o usuário cola no painel (ou no Portainer, no caso do servidor).
- Execução REAL começa **desligada** para todo usuário e **volta a desligar quando o servidor reinicia**.
  Além disso existe a trava geral `PUMP_REAL_ALLOWED` (padrão `false`).
- **Durante o desenvolvimento não fazer nenhuma transação real e não ligar a execução real.**
- `audit_log` registra: ligar/desligar real, salvar/remover chave, vender manual, trocar USDC→SOL e toda ação
  do admin sobre um usuário.
- Toda consulta ao banco feita pelo servidor usa a service key (passa por cima do RLS), então **sempre filtra
  por `user_id`**, e o `user_id` vem **só do token validado**.

## Stack
- Backend: Python 3.12, FastAPI (`app/`). Front: HTML/CSS/JS estáticos (`web/`), supabase-js 2.118.0 via
  jsDelivr com SRI.
- Login: **só Google**, pelo Supabase Auth (PKCE). O servidor confere o JWT (HS256 com segredo, ou JWKS
  ES256/RS256, ou pergunta ao `/auth/v1/user`) — `app/auth.py`.
- Banco: Supabase Postgres com **RLS em todas as tabelas** — `supabase/migrations/`.
- Chaves pessoais: AES-256-GCM com `APP_ENCRYPTION_KEY` (só no servidor); cifra amarrada a usuário+nome — `app/crypto.py`.
- Deploy: imagem Docker publicada pelo GitHub Actions em `ghcr.io/bruxo95/pump.fun_bruxo_bode:latest`;
  VPS com **Docker Swarm + Traefik** gerenciada pelo **Portainer** (rede `vpsrachar`,
  certresolver `letsencryptresolver`). Stack em `deploy/portainer-stack.yml`.
  (A ideia inicial era Caddy, mas o Traefik já ocupa 80/443 na VPS — por isso Traefik.)

## Arquitetura (arquivos principais)
| Arquivo | Papel |
|---|---|
| `app/pumpfun.py` | `PumpMarket` (dados públicos compartilhados) e `PumpFun` (motor de cópia de UM usuário — lógica do original), `PumpReal` (execução real via PumpPortal/Jupiter). `on_message` = `ingest` (parte pública) + `react` (parte do usuário). |
| `app/monitor.py` | `SharedMonitor`: UMA conexão WebSocket da Solana com a união das carteiras seguidas; lê cada transação uma vez e entrega a quem segue; preços (curva on-chain, Jupiter, DexScreener), stops e stop móvel de todos; leaderboard da Solana Tracker com cache por (dias, trades mín., acerto mín., plataforma). |
| `app/hub.py` | `PumpHub`: um motor por usuário, carrega/salva dados, chaves, carteira; gestão de usuários (admin); status geral. |
| `app/api.py` | Rotas. Tudo em `/api/*` exige login. Rotas `/api/admin/*` só para `role=admin`. |
| `app/db.py` | `SupaREST` (PostgREST com service key), `SupabaseStore` (dados do usuário em memória + gravação em segundo plano), `Vault` (chaves criptografadas), `audit()`. |
| `app/store.py` | `MemStore` (mesma interface, só memória — usado nos testes). |
| `app/settings.py` | Opções `PUMP_*`: `USER_KEYS` (por usuário, no banco) e `SERVER_KEYS` (só `.env`, monitor compartilhado). |
| `app/jupiter.py` | Cotação (compartilhada, com limitador) e trocas com a carteira do usuário; USDC→SOL. |
| `app/logsafe.py` | Máscara de segredos nos logs + buffer de logs para a tela do admin. |
| `web/index.html`, `landing.js` | Página inicial pública. |
| `web/app.html`, `app.js`, `app.css`, `common.js` | Painel (Visão geral, Top traders, Posições, Histórico, Feed, Execução real, Configurações, Administração, Como funciona). |

## Banco (Supabase)
Tabelas: `profiles` (role admin/user, bloqueado, ultimo_acesso), `user_settings` (settings jsonb,
compartilhar_chave_st), `user_secrets` (valor_criptografado), `pump_positions`, `pump_trades`, `pump_lists`
(manual/banida/pausada), `pump_feed` (últimos 500), `audit_log`. Gatilho `handle_new_user`: o **1º usuário
vira admin**. O navegador só lê as próprias linhas e nunca escreve.
Tabela `app_secrets`: **chaves do sistema** (Solana Tracker, PumpPortal, Jupiter) que o admin configura em
Administração para todo mundo VER a ferramenta funcionando sem chave própria (ranking, cotações, conexão
PumpPortal). Nunca são usadas para executar nada em nome de usuário: trocas usam a chave Jupiter do próprio
usuário ou a API pública; execução real usa só as chaves do usuário. Chave pessoal sempre tem prioridade.
Nenhum usuário lê `app_secrets` (RLS sem política). Em Configurações cada chave mostra "Usando: sua chave /
chave do sistema / não configurada" e o link para criar a própria.
Migrações registradas como aplicadas no projeto: `20261025000001_inicial.sql`, `20261025000002_admin.sql` e
`20261025000003_chaves_sistema.sql`.
Migração nova = arquivo novo em `supabase/migrations/`. Aplicar no Supabase remoto fica fora do deploy
autorizado (somente GitHub) e exige uma solicitação explícita para essa ação.

## Variáveis do servidor (Portainer → Environment variables do stack)
`SUPABASE_URL`, `SUPABASE_ANON_KEY` (pública), `SUPABASE_SERVICE_ROLE_KEY` (secreta), `APP_ENCRYPTION_KEY`
(32 bytes base64 — se trocar, as chaves salvas param de abrir), `PUBLIC_BASE_URL=https://pump.rachar.app.br`,
`SOLANA_RPC_PUBLIC`, `PUMP_REAL_ALLOWED=false`, e padrões `PUMP_*` opcionais. Modelo em `.env.example`.

## Fluxo de entrega autorizado (somente GitHub)
1. Conferir o remoto, validar as alterações e fazer commit + push no `main` deste repositório.
2. GitHub Actions roda os testes e, se passarem, publica a imagem no GHCR. O workflow atual não faz
   atualização de servidor. Informar o resultado observado; se não foi conferido, dizer que está pendente.
3. Encerrar a entrega no GitHub. Não executar SSH, atualização de stack, migração remota ou comandos
   em servidores. Não afirmar que a versão do site mudou apenas porque houve push ou publicação da imagem.

Referência histórica de operação, fora desse escopo: o responsável pela produção usa Portainer →
Stacks → `pump_bruxo_bode` → **Update the stack** com **Re-pull image and redeploy** e confere `/health`.
Esta descrição não autoriza o agente a executar esses passos. Os arquivos do painel levam `?v=<versão>`.

## Rodar e testar localmente
- `pip install -r requirements.txt pytest && pytest -q` (o teste de RLS usa Postgres local se existir; senão pula).
- `cp .env.example .env` (preencher) e `docker compose up -d --build` → http://localhost:8080
  (no Supabase, adicionar `http://localhost:8080/app` nas Redirect URLs).

## Situação de produção registrada anteriormente (2026-10-25, versão 0.8.0; não reverificada nesta tarefa)
- Etapas 1–7 do plano concluídas: núcleo + Jupiter, Supabase/RLS/criptografia, login Google + painel,
  monitor compartilhado + motores por usuário, Docker/Portainer/README, menu de Administração (usuários,
  categoria, bloqueio, desligar real de alguém, registro de todas as contas, logs do servidor).
- No ar em pump.rachar.app.br; login Google funcionando; monitor da Solana conectado na VPS.
- Execução real **travada** (`PUMP_REAL_ALLOWED=false`) e nunca foi ligada.
- Ainda **não testado de verdade**: cópias acontecendo ao vivo com traders seguidos (precisa da chave da
  Solana Tracker no painel ou de carteiras manuais) e qualquer coisa do modo real.
- Ranking próprio fica vazio sem o stream pago da PumpPortal (comportamento igual ao original).

## Ideias / pendências
- Acompanhar as primeiras horas de cópia fictícia ao vivo e ajustar o que aparecer nos logs (Administração → Logs).
- Antes de qualquer uso real: testar com carteira nova e pouco saldo, com a trava liberada só nesse momento.

## Continuidade de desenvolvimento (2026-10-25, versão 0.8.1)
- Criado `AGENTS.md` para Codex/Cursor consultarem este contexto compartilhado.
- Registrado o limite de entrega: somente o GitHub deste projeto; sem acesso a servidores ou outros projetos.
- Alterações desta entrega: documentação dos agentes e identificação da versão; lógica da aplicação preservada.
- Integradas as atualizações recebidas durante a tarefa: nome público PUMP FUN COPY e chaves do sistema
  para visualização (commits `c99e89c` e `a43eadb`); mantido o código recebido, sem alterar essas funcionalidades.
- Clone local ainda sem `.env`; aplicação, login, cópia ao vivo e produção não foram executados nesta tarefa.
- Validação local após integrar as atualizações do GitHub: 61 testes passaram com `.venv/Scripts/python.exe -m pytest -q
  --ignore=tests/test_rls_postgres.py`. A suíte completa foi tentada, mas a coleta de
  `test_rls_postgres.py` falha no Windows ao importar `pwd` (módulo de Unix); o isolamento no Postgres
  não foi validado localmente. Há um aviso de depreciação do TestClient/HTTPX nas dependências instaladas.
- Ambiente `.venv/` local e ignorado pelo Git. CI e publicação da imagem devem ser conferidos no GitHub;
  nenhum resultado local comprova atualização do servidor de produção.
