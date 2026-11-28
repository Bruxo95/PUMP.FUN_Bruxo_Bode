# CLAUDE.md — contexto do projeto PUMP.FUN Bruxo Bode

Leia isto antes de mexer no projeto. Este é o contexto compartilhado para pessoas, Claude Code,
Codex e Cursor. `AGENTS.md` é a entrada para Codex/Cursor e aponta para este arquivo.
Ao concluir tarefas, acrescente o registro da versão no FIM de `docs/HISTORICO-VERSOES.md` (uma linha por versão) e,
só se for uma regra que vale sempre, uma linha em "Regras que valem sempre" abaixo. Sem guardar segredos. Confira sempre o código: registros históricos não comprovam o estado atual.

## O que é
Nome no site: **PUMP FUN COPY** (logo, títulos e rodapé). O repositório e as pastas continuam com o nome
interno `PUMP.FUN_Bruxo_Bode`.

Sistema web **multiusuário** de cópia de traders da **pump.fun** (Solana). Cada pessoa entra com Google,
tem o próprio painel, carteira fictícia, posições, histórico, configurações, chaves e (opcional) execução real.
Nasceu da aba PUMP.FUN do repositório `github.com/Bruxo95/hermes-jev-trader` (só essa aba foi trazida;
Futuros, Spot, Solana DEX, DEX-CEX, Relógio, Macro, Hermes/Jev e Gate.io ficaram de fora). O mapa do que veio
de onde está em `docs/ORIGEM.md`.
Guia completo para usuários e desenvolvedores (uso, chaves, como as transações chegam à Solana e o papel de
cada API): `docs/GUIA-DO-PROJETO.md`.
**Arquitetura e divisão do banco (Supabase × Postgres da VPS), com diagramas:** `docs/ARQUITETURA.md`.

- Produção: **https://pump.rachar.app.br** · versão no ar: `/health` (também no rodapé do painel)
- Repositório: `github.com/Bruxo95/PUMP.FUN_Bruxo_Bode` (privado), branch `main`
- Supabase: projeto `vnvfluimpqvxbvdbmwqa` (`https://vnvfluimpqvxbvdbmwqa.supabase.co`)

## Como trabalhar aqui (regras do dono)
- **Responder sempre em português do Brasil**, direto e sem jargão.
- Ao terminar cada tarefa: dizer **o que mudou, a versão** e **o que o dono precisa fazer**
  (ex.: "commit enviado ao GitHub; confira o resultado do Actions"). Dizer o que **não** foi testado de verdade.
- **Antes de todo push/deploy: `git pull` (ou `git fetch` + rebase) no `main`, integrar o que chegou, rodar a checagem e os testes e, se aparecer erro, corrigir ANTES de enviar.** Outra IA (Codex) e o dono também enviam ao mesmo repositório; push sem pull rejeita ou atropela a versão deles. Se a versão já foi usada por outro, subir para a próxima. Pedido do dono em 2026-10-25.
- **Nunca dar deploy (push no `main`) com posição aberta no BOOST (regra do dono, 2026-11-25).** O deploy reinicia o servidor e mexe
  nas posições em andamento. Antes de todo push: conferir se há posição aberta do BOOST (fictícia ou REAL; `origem = boostmig` em
  `pump_positions`, pelo leitor `scripts/ler_banco.py`, ou pelo painel em `/app#boost`). Se houver, esperar fechar e conferir de novo;
  se não der para conferir, não enviar e avisar o dono. Dizer na resposta o que foi conferido.
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
- Toda entrega acrescenta uma entrada NO TOPO de `app/novidades.json` (versão, data, tipo, onde fica no menu,
  título e o que faz, em linguagem de usuário); aparece no menu Novidades, SÓ PARA ADMIN (rota
  `/api/admin/novidades`; o arquivo fica fora de `web/` para não ser público — pedido do dono em 2026-10-25). `tests/test_novidades.py` falha se a
  primeira entrada não for a versão de `app/version.py`. Pedido do dono em 2026-10-25.
- **Área de cada entrega no Changelog (pedido do dono em 2026-10-29):** a entrada do topo leva `area` (Back-end (Python),
  Front-end (JavaScript), UI/UX (telas), Visual (CSS), Menu, Banco de dados, Motor de trades, Aprendizado…) e `arquivos`
  (código mexido). Gerar com `py scripts/changelog_area.py --current <versão>` ANTES do commit (lê os arquivos mudados);
  `tests/test_novidades.py` falha sem `area`. Aparece como etiquetas abaixo do tipo no Changelog.
- Novidade visível no painel ganha marca verde "NOVO": atributo `data-novo-ate="AAAA-MM-DD"` (cerca de 14 dias
  depois da entrega) no elemento; `marcarNovos()` em `web/app.js` aplica a classe `novo` e ela some sozinha depois
  da data. Pedido do dono em 2026-10-25 ("está tudo preto, quero distinguir o que é novo").
- **Relatório da mudança (regra do dono, 2026-10-26):** toda IA que corrigir ou mudar a lógica de trades (a partir de
  um relatório do dia ou de um pedido) cria, na MESMA entrega, `app/relatorios_ia/AAAA-MM-DD-versao.md` no formato de
  `app/changes.py` (cabeçalho com versao, data, autor, baseado_em, projecao_sol_dia, projecao_texto + texto do que
  mudou e como medir). A projeção é em SOL por dia na carteira fictícia, com a conta; sem base, `nao_estimado` e por
  quê. Aparece em Relatórios → "Mudanças feitas pela IA" com o realizado 7 dias antes × depois.
  `tests/test_changes.py` falha se algum arquivo estiver fora do formato.
- Visual: tema escuro "painel profissional" (estilo inspirado em rbp-security-template.vercel.app — só o
  estilo, nada copiado). Botões liga/desliga: **verde = ON, vermelho = OFF**. Tem que funcionar no celular
  (menu vira gaveta, sem rolagem lateral). JS sem handlers inline (a CSP bloqueia).
- **Toda mudança de visualização web é conferida no PC E no celular (pedido do dono em 2026-10-31).** Antes do commit: tirar
  print da tela mexida em 1440 px e em 390 px (Playwright já instalado; copiar `web/` para uma pasta temporária, tirar o
  `?v=` e o `/static/` dos links, mostrar só a `section[data-view=...]` e desligar os scripts), olhar os dois prints e
  conferir que não há rolagem lateral (`scrollWidth - innerWidth = 0`). Dizer na resposta que os dois foram conferidos.

## Segurança (nunca quebrar)
- Nunca mostrar, logar ou devolver chaves pela API; a tela só mostra "configurada: sim/não".
- **Nunca pedir chaves ou senhas no chat** — o usuário cola no painel (ou no Portainer, no caso do servidor).
- Execução REAL começa **desligada** para todo usuário. Desde a 0.31.28 (pedido do dono em 2026-10-27), depois que o
  usuário liga com a confirmação, **continua ligada até ele desligar**, inclusive após reinício (`_real_on` em
  `user_settings.settings`; só volta com trava geral liberada, carteira configurada e conta liberada).
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
`20261025000004_aprendizado_diario.sql` (tabela `learning_daily`, 0.10.0) — aplicada pelo job `banco` em 2026-10-25
(run 40239286326, log "Aplicada").
`20261025000005_carteiras_estudo.sql` (0.14.0): `study_wallets` (lista por usuário), `wallet_trades` e
`study_positions` (dados públicos compartilhados, só o backend lê/grava); semeia as 2 carteiras pedidas pelo dono
na lista dos admins. Carteiras em estudo: `app/study.py`, `hub.study_*`, menu "Carteiras em estudo".
Etapas seguintes: (2) "se você tivesse copiado" com atraso e taxas + ranking de copiabilidade;
(3) alerta de convergência (2+ carteiras no mesmo token) e "possível ganho" por faixa histórica.
**Migrações automáticas (desde 0.12.0, autorizado pelo dono em 2026-10-25):** o job `banco` do Actions roda
`scripts/aplicar_migracoes.py` com o segredo `SUPABASE_ACCESS_TOKEN` (Management API) e aplica, antes da imagem,
toda migração de `supabase/migrations/` que não esteja em `public.app_migracoes` (cada uma em transação com o seu
registro). 0001–0003 entram só como linha de base. Migração nova = arquivo novo com nome `AAAAMMDDHHMMSS_nome.sql`,
nunca editar uma já aplicada. O token dá poder total sobre o banco: SQL de migração é revisado antes do push
(sem `WHERE` aberto, sem `drop` de dados).
Migração nova = arquivo novo em `supabase/migrations/`; o Actions aplica sozinho (job `banco`, ver acima).

## Variáveis do servidor (Portainer → Environment variables do stack)
`SUPABASE_URL`, `SUPABASE_ANON_KEY` (pública), `SUPABASE_SERVICE_ROLE_KEY` (secreta), `APP_ENCRYPTION_KEY`
(32 bytes base64 — se trocar, as chaves salvas param de abrir), `PUBLIC_BASE_URL=https://pump.rachar.app.br`,
`SOLANA_RPC_PUBLIC`, `PUMP_REAL_ALLOWED=false`, e padrões `PUMP_*` opcionais. Modelo em `.env.example`.

## Fluxo de entrega autorizado (somente GitHub)
1. Conferir o remoto, validar as alterações e fazer commit + push no `main` deste repositório.
2. GitHub Actions roda os testes e, se passarem, publica a imagem no GHCR. Se o segredo
   `PORTAINER_WEBHOOK_URL` existir no repositório (configurado pelo dono, pedido dele em 2026-10-25),
   o job `deploy` avisa o webhook do serviço no Portainer, que baixa a imagem nova sozinho, e confere
   `/health`. Sem o segredo, o job só avisa que a atualização é manual. Informar o resultado observado;
   se não foi conferido, dizer que está pendente.
3. Encerrar a entrega no GitHub. Não executar SSH, atualização de stack, migração remota ou comandos
   em servidores. Não afirmar que a versão do site mudou apenas porque houve push ou publicação da imagem.

Referência histórica de operação, fora desse escopo: o responsável pela produção usa Portainer →
Stacks → `pump_bruxo_bode` → **Update the stack** com **Re-pull image and redeploy** e confere `/health`.
Esta descrição não autoriza o agente a executar esses passos. Os arquivos do painel levam `?v=<versão>`.

## Rodar e testar localmente
- `pip install -r requirements.txt pytest && pytest -q` (o teste de RLS usa Postgres local se existir; senão pula).
- `cp .env.example .env` (preencher) e `docker compose up -d --build` → http://localhost:8080
  (no Supabase, adicionar `http://localhost:8080/app` nas Redirect URLs).

## Regras que valem sempre (tiradas do histórico; detalhes em `docs/HISTORICO-VERSOES.md`)
O histórico completo de cada versão (o que mudou, nomes de funções, casos) foi para `docs/HISTORICO-VERSOES.md`, para este
arquivo não pesar em toda sessão. Para saber como algo funciona: `grep` pelo nome da função, da opção ou da versão nesse arquivo.
- **O repositório é PÚBLICO (desde 2026-11-21):** nunca commitar chave, senha, e-mail ou nome real de usuário; ajuste de uma conta
  vai por `settings_overrides` referenciando o user_id.
- **Ajuste de configuração pedido no chat = linha em `settings_overrides`** (aplicada por `hub._apply_overrides`); nunca gravar
  direto em `user_settings` por migração (o servidor antigo regrava por cima no deploy).
- **Toda versão nova entra também em `app/versoes.json`**; `app/novidades.json` com `area` (`py scripts/changelog_area.py --current <versão>`);
  inventário de dependências refeito (`py scripts/inventario_dependencias.py --refresh --date AAAA-MM-DD` e `--check`) a cada versão.
- **Projetos separados:** tela, chave ou opção da BNB só no `/bnb`; da Robinhood só no `/hood`; do Dormant só no `/dormant`;
  BOT LIVE tem carteira simulada própria e não mexe em outra sala. Rede/projeto novo = cartão no `/entrar` + linha em `NETS` (`web/common.js`).
  Botão `.hubbtn` que só é link leva `data-link`.
- **Chave nova do sistema = nome também numa migração da regra `app_secrets_nome_check`** (o teste falha se faltar).
- **Banco:** nada de reler tabela inteira no início (carregar sob demanda ou só a janela usada); evitar muitos deploys seguidos.
  Tabela nova que cresce = entra em `arquivo.SPECS` (Postgres da VPS, banco `pump_arquivo`, 90 dias) e precisa de índice na
  coluna de hora; só dados públicos vão para o arquivo (lá não tem RLS). Ver `docs/ARQUITETURA.md` §2.1.
- **REAL:** opção nova de REAL começa OFF; nenhuma entrega liga a REAL de ninguém. Aba nova que compra na REAL = linha em
  `REAL_PLACES`, em `ABAS_TR`, origem em `GATE_ORIGINS` e `ABA_ORIGEM`; chave nova que decide se vai para a REAL entra no bloco Espelho.
- **BOOST:** extras nunca mexem em `boostmig.py` nem fazem o `bm_tick` esperar banco/rede; opção nova fora do BOOST não pode
  bloquear o BOOST; opção nova do BOOST = linha em `BM_SECS`; opção pessoal (valor por entrada) = entrar em `PERSONAL`.
- **Solana:** padrão novo de opção = etapa nova em `settings.AJUSTES`; posição mexida em `_check_stops` precisa de `_save_pos`;
  função nova que consulta uma moeda = embrulhar com `for_mints`; laço novo que consulta API = linha em `consultas.LOOPS`
  e criado com `run_as`; tela nova em teste = quadrado em `#usar` + `USAR_V` (+ `USAR_ABAS` se compra, `USAR_ORIG` para o uso).
- **Robinhood:** com a REAL ligada, compra e venda da REAL começam sempre antes da fictícia; opção nova da cópia = linha em
  `CFG_ROWS` (entrada: chave em `CFG_DEFAULT` + `entry_block`); nunca usar `key[2]` da PoolKey como taxa (`pool_fee`).
- **Dormant:** números no padrão da Uniswap (ponto no decimal, `$`); rede nova = linha em `CHAINS` com roteador conferido na rede.
- **Telas:** aba nova que compra = linha em `ABAS_TR` e `ABAS_OPT`; período novo = `renderOverview`, regex de `openOv` e `PERIODS_H`;
  tabela que nunca deve virar cartão no celular leva a classe `nocard`.
- **Quando o dono trouxer a resposta do ChatGPT** sobre carteiras: analisar e gravar `app/analises_carteiras/<id do relatório>.md`.
- **Deploy vermelho com testes, banco e imagem verdes = olhar o servidor, não o código.** Falha em "verificar triagem" com o
  código igual costuma ser a consulta ao vivo de alertas: conferir rodando o verificador localmente.
