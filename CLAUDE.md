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
Guia completo para usuários e desenvolvedores (uso, chaves, como as transações chegam à Solana e o papel de
cada API): `docs/GUIA-DO-PROJETO.md`.

- Produção: **https://pump.rachar.app.br** · versão no ar: `/health` (também no rodapé do painel)
- Repositório: `github.com/Bruxo95/PUMP.FUN_Bruxo_Bode` (privado), branch `main`
- Supabase: projeto `vnvfluimpqvxbvdbmwqa` (`https://vnvfluimpqvxbvdbmwqa.supabase.co`)

## Como trabalhar aqui (regras do dono)
- **Responder sempre em português do Brasil**, direto e sem jargão.
- Ao terminar cada tarefa: dizer **o que mudou, a versão** e **o que o dono precisa fazer**
  (ex.: "commit enviado ao GitHub; confira o resultado do Actions"). Dizer o que **não** foi testado de verdade.
- **Antes de todo push/deploy: `git pull` (ou `git fetch` + rebase) no `main`, integrar o que chegou, rodar a checagem e os testes e, se aparecer erro, corrigir ANTES de enviar.** Outra IA (Codex) e o dono também enviam ao mesmo repositório; push sem pull rejeita ou atropela a versão deles. Se a versão já foi usada por outro, subir para a próxima. Pedido do dono em 2026-10-25.
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
- Novidade visível no painel ganha marca verde "NOVO": atributo `data-novo-ate="AAAA-MM-DD"` (cerca de 14 dias
  depois da entrega) no elemento; `marcarNovos()` em `web/app.js` aplica a classe `novo` e ela some sozinha depois
  da data. Pedido do dono em 2026-10-25 ("está tudo preto, quero distinguir o que é novo").
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
- **Radar de KOLs / "ondas de influencer" (pedido do dono em 2026-10-25, para outra IA implementar).** Exemplo:
  https://pump.fun/coin/C5xph2yL6gMdxmuLGxJBkGpmuDFfyi5fqkBNhvL6pump — no gráfico da pump.fun aparecem dezenas de
  avatares de traders conhecidos comprando em sequência e o preço sobe forte. Objetivo: identificar RÁPIDO quando
  várias carteiras conhecidas entram no mesmo token e decidir se vale entrar cedo e sair na onda. Sugestão:
  1. Detectar a "onda": N carteiras rotuladas (KOL/influencer/smart money) comprando o mesmo token em X minutos.
     Fontes: rótulos `identity` da Solana Tracker (ex.: `/trades/{token}?enrich=identity`, identidade nas posições
     PnL v2), carteiras em estudo, top do ranking e lista de KOLs (Kolscan). Conferir na doc o que a chave cobre.
  2. Nota da onda: quantas carteiras distintas, se são as que dão lucro para quem copia (ranking de copiabilidade,
     0.15.0), pressão de compra, risco do token, progresso da curva e tempo desde a 1ª compra (entrar no começo).
  3. Alerta no painel (e depois Telegram); entrada automática primeiro só no SIMULADO, com ON/OFF e marca NOVO.
  4. Saída própria da onda: venda em partes rápida, stop curto, e sair quando os KOLs começarem a vender.
  5. Riscos a mostrar: KOL costuma vender em cima de quem chega depois (copiador vira "saída"); atraso decide tudo;
     medir no simulado por semanas antes de qualquer real. Base: arXiv 2601.08641 (bundles/snipers/isca) e
     etapa 3 das Carteiras em estudo (alerta de convergência), que é a mesma ideia e pode ser reaproveitada.
- Aprendizado diário (menu, `app/learning.py`, 0.9.9): 1ª etapa só com dados existentes (trades do usuário +
  memória do monitor, que zera ao reiniciar). (2) FEITA no código na 0.10.0: `learning_daily` guarda o resumo
  do dia a cada 30 min (`hub.save_learning`) e a página mostra a consistência por dias;
  (3) simulação "e se" (stop/filtros) sobre o histórico; (4) opcional: resumo escrito por IA (custo por uso).
- Pesquisa de mercado (2026-10-25; Trojan, GMGN, BullX, Cielo, Kolscan, chainstacklabs/pumpfun-bonkfun-bot,
  arXiv 2601.08641). Ideias por prioridade: (1) FEITA na 0.9.3 — checagem de risco do token pelo `risk` da
  Solana Tracker (`risk_check`/`risk_block` em `app/pumpfun.py`; não testada com a API de verdade); (2) FEITA na
  0.9.4 — `chase_block` (padrão 30%; na cópia imediata do simulado o preço é o do próprio trader, então só age na
  cópia com espera e no real); não copiar se o preço já subiu
  X% desde a compra do trader; (3) venda automática quando o dev vende e ao migrar para a PumpSwap;
  (4) nota de qualidade do trader (consistência, não só acerto/lucro; evitar carteiras "isca" e bundles);
  (5) resultado por trader copiado, para pausar quem dá prejuízo depois das taxas; (6) avisos no Telegram;
  (7) só para o real: envio protegido contra MEV (Jito/relay) e feed gRPC para reduzir atraso.
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

## Atualização automática (2026-10-25, versão 0.8.2)
- Pedido do dono: atualizar sozinho a cada versão nova, "estilo Vercel". Implementado no workflow
  (`.github/workflows/imagem.yml`, job `deploy`): só age se o segredo `PORTAINER_WEBHOOK_URL` estiver
  configurado no GitHub; o próprio agente não acessa o Portainer. Passo a passo no README.
- `tests/test_rls_postgres.py`: `pwd` agora é importado só em Linux/macOS; no Windows o teste é pulado
  (antes quebrava a coleta da suíte).

## Auditoria de segurança (iniciada em 2026-10-25)
- Solicitada pelo usuário: revisão completa do escopo disponível e registro do ponto de retomada.
- Relatório e checklist: `docs/AUDITORIA-SEGURANCA.md`; consultar antes de continuar trabalho de segurança.
- Base inicial: commit `1cec6a04dfe076be8ddbad5258359d2afb225f38`, aplicação 0.8.2.
- IA responsável: OpenAI Codex, família GPT-6; identificador exato do modelo/revisão não exposto
  nesta sessão. Identificação comum: `docs/auditoria/2026-10-25/identificacao-auditoria.json`.
- Estado: revisão do repositório concluída; remediação não iniciada. Não interpretar como aprovação de segurança.
- Resultado: 11 achados abertos (1 alto condicional, 7 médios, 3 baixos); IDs e evidências no relatório.
- Validação: 61 testes passaram, 5 PostgreSQL/RLS pulados no Windows. Bandit triado; pip-audit sem
  vulnerabilidades conhecidas nas 34 dependências locais; Gitleaks sem segredo real confirmado em 15 commits.
- Próximo ponto de retomada: SEC-02 (bloqueio concorrente) e SEC-03 (RPC/SSRF); antes de uso real,
  resolver SEC-01 (validar mensagem antes de assinar) e SEC-04 (reconciliar vendas pendentes).
- A fase técnica não alterou a aplicação nem fez commit/push/deploy. Em seguida, o usuário autorizou
  commit e push dos relatórios em 2026-10-25; correções ficam para a próxima etapa. Aplicação segue 0.8.2.
  Relatório e reproduções em `docs/auditoria/2026-10-25/`; infraestrutura e RLS real seguem pendentes.
- Escopo operacional preservado: inspeção local, testes com fakes e consultas públicas sem alterações;
  sem acesso administrativo a servidores, sem transações reais e sem alterações no Supabase remoto.
- Regra para futuras auditorias: sempre identificar data, versão da aplicação, SHA auditado, IA/modelo
  (ou indisponibilidade do identificador exato), achados, validações e ponto de retomada; preservar a base
  histórica ao corrigir versões posteriores. Não confundir commit do relatório com commit auditado.

## Ambiente local removido a pedido do usuário (2026-10-25)
- Removidos `.venv/`, `.pytest_cache/`, caches Python de app/tests, o ambiente temporário
  `pump-security-audit-1cec6a0` (incluindo Bandit, pip-audit e Gitleaks) e o cache próprio do pip-audit.
- Também removidos 188 arquivos recentes de cache/download associados aos pacotes desta atividade;
  preservados os caches anteriores e os demais projetos. Não houve instalação global desses pacotes.
- Código, relatórios, histórico Git e autenticação Git/GitHub preservados. A auditoria continua como
  registro histórico da base 0.8.2; remover ferramentas não corrige os achados.
- Não reinstalar dependências no Windows principal. Combinar antes isolamento real/remoto para futuras
  instalações e testes; uma venv separa dependências, mas não é barreira contra código malicioso.
- A limpeza não fez correções ou deploy; o usuário autorizou depois o commit e push deste registro.
- Atualização somente documental, aplicação segue 0.8.2. Verificação: `git diff --check`; testes Python
  não reexecutados porque o ambiente foi removido. Nenhuma dependência foi reinstalada.
- Próximo passo: aguardar a nova instrução do usuário.

## Pré-visualização de link (2026-10-25, versão 0.8.3)
- O WhatsApp ainda mostrava "PUMP.FUN Bruxo Bode" ao colar o link: era cache da pré-visualização antiga
  dele (o site no ar já mostrava PUMP FUN COPY, conferido por consulta pública à página).
- Adicionadas tags Open Graph/Twitter em `web/index.html` e `web/app.html` (título, descrição, site_name,
  imagem `web/og.png` 1200×630 com o nome novo). O endereço completo vem de `PUBLIC_BASE_URL` (`__BASE__`
  trocado pelo servidor). Teste em `tests/test_api.py::test_pages_and_security_headers`.
- Não verificado de verdade: a pré-visualização no WhatsApp depende do cache deles.

## Webhook do Portainer testado (2026-10-25, versão 0.8.4)
- A pedido do dono, o webhook do serviço foi testado: respondeu HTTP 204 e o site seguiu no ar.
  O job `deploy` do Actions já vinha rodando com sucesso (ex.: run #13, passos "avisar o Portainer" e
  "conferir a versão").
- O job `deploy` agora espera aparecer em `/health` exatamente a versão de `app/version.py` do commit
  (até 5 min); antes só conferia se o site respondia.
- O dono colou a URL do webhook no chat: recomendado gerar uma nova no Portainer e atualizar o segredo
  `PORTAINER_WEBHOOK_URL` no GitHub. A URL não foi gravada em nenhum arquivo.

## Top traders só online + hora do deploy (2026-10-25, versão 0.9.0)
- Novas configs por usuário: `pump_only_online` (padrão true) e `pump_online_min` (padrão 10 min).
  `refresh_followed` (roda a cada `pump_rank_every_s`=600 s) filtra os aptos automáticos por
  `PumpFun.last_seen()` = maior entre atividade do WebSocket, `wallets[w].last_t` e `last_trade` da Solana
  Tracker. Quem ficou inativo sai, entra o próximo melhor online; evento "Top traders atualizados: …".
  Manuais e quem tem posição aberta ficam. `SharedMonitor._fill_slot` refaz a lista na hora quando um trader
  do top negocia e o usuário tem vaga.
- Leaderboard da Solana Tracker agora renovado a cada 10 min (`pump_lb_every_s` padrão 600).
- Os testes de referência (`tests/test_pump.py`, `tests/test_monitor.py`) desligam `pump_only_online` no
  fixture para manter o comportamento original; a regra nova tem `tests/test_online.py`.
- `/health` e o rodapé mostram `no_ar_desde` (hora em que o container subiu, fuso Europe/Berlin; `tzdata`
  no requirements). O "Updated" da tela Stacks do Portainer NÃO muda com o webhook (ele atualiza o serviço).

## Inventário permanente de dependências (2026-10-25, aplicação 0.8.2)
- Pedido do usuário: manter quantidade, nomes e versões em documento e PDF, atualizando ao mudar dependências.
- Artefatos: `docs/DEPENDENCIAS.md`, `docs/dependencias/inventario.json` e
  `output/pdf/relatorio-dependencias.pdf`; geradores em `scripts/inventario_dependencias.py` e `scripts/pdf_dependencias.py`.
- Contagens separadas: 7 Python diretas de execução + 1 JavaScript direta; pytest de teste separado.
  Snapshot da auditoria contém 34 pacotes Python (inclui diretos e teste), de ambiente já removido;
  não somar 34 aos diretos nem afirmar que representam produção ou instalação atual.
- Sempre atualizar Markdown/JSON/PDF juntos após mudança de dependências/runtime/Actions/scripts externos;
  preservar o snapshot histórico e registrar versões novas somente com fonte comprovada.
- CI verifica consistência sem dependências extras. Gerar PDF apenas com recurso preexistente ou ambiente
  isolado/remoto aprovado; não recriar `.venv` nem instalar pacotes no Windows principal.
- Validação desta entrega: PDF de 3 páginas renderizado e inspecionado; todos os 34 nomes/versões presentes.
  Checker passou sem site-packages e rejeitou dependência nova sem documento atualizado, PDF divergente
  e manifesto novo não catalogado. Nenhuma dependência instalada; ReportLab 4.4.9 preexistente foi usado.
- Testes da aplicação não reexecutados (ambiente removido). Aplicação segue em 0.8.2. Arquivos e alteração
  de CI ainda locais, sem commit/push; publicar quando solicitado. Nenhum servidor foi alterado.

## Triagem de versões antes de instalar (iniciada em 2026-10-25)
- Novo pedido do usuário: consultar relatos de malware/comprometimento e vulnerabilidades antes de
  qualquer instalação/atualização; acrescentar downloads, estrelas, assinantes e classificação ao PDF.
- Política: `docs/dependencias/POLITICA-DE-DEPENDENCIAS.md`. Dados: `docs/dependencias/triagem-seguranca.json`.
- Popularidade não representa instalações/pessoas únicas nem garante segurança; ausência de métricas é N/D.
- Concluída em 2026-10-25 (Claude Opus 5.5, versão 0.9.1): versões exatas em `constraints.txt` (publicadas há
  14+ dias; exceção certifi 2026.10.23 por CA comprometida nas anteriores); CI e Dockerfile resolvem só metadados,
  conferem a triagem e consultam OSV/PyPI ao vivo; instalam com hash. Sem prazo de validade do registro (7 dias
  travaria o deploy automático toda semana). Revisões manuais em `docs/dependencias/revisoes-manuais.json`
  (jsonalias 0.1.1, pluggy 1.6.0). PDF ganhou a seção 04 (downloads, estrelas, assinantes, Favorável/Atenção/Perigo).
- Versão nova de dependência: rodar `py -I scripts/coletar_risco_dependencias.py --candidates-json <lista>`,
  revisar, trocar `constraints.txt`, `py scripts/inventario_dependencias.py --refresh --date AAAA-MM-DD` e `--check`.
- tzdata 2026.5 (entrou pelo remoto) triado Favorável e fixado. O gate ainda não rodou no GitHub; conferir o primeiro Actions.

## Remediação da auditoria — SEC-01 a SEC-04 (2026-10-25, versão 0.9.1)
- Detalhes em `docs/AUDITORIA-SEGURANCA.md` (seção "Remediação 1"); regressões em `tests/test_seguranca.py`.
- `app/txguard.py`: confere a transação antes de assinar e reconcilia transação pendente. Falha fechada — no
  primeiro teste real (carteira nova, pouco saldo, trava liberada só nessa hora) conferir se PumpPortal/Jupiter
  passam; se recusar, ajustar a lista de programas/rotas com evidência, nunca desligar a verificação.
- RPC pessoal: só endereço público (`app/solana_wallet.py`); bloqueio de conta serializado (`app/hub.py`).
- pytest não rodou localmente (sem dependências no Windows); a suíte roda no Actions após o push.
- CI verde e 0.9.1 no ar em 2026-10-25 (/health conferido). Próximo: SEC-05/06 (cotas e limites).

## Remediação da auditoria — SEC-05 a SEC-11 (2026-10-25, versão 0.9.2)
- Ranking pelo painel: 60 s por conta e 6/min na chave do sistema; token recusado lembrado 60 s; JWKS com
  recarga limitada; workflow com `concurrency` (um deploy por vez); RPC mostra só o hostname; erros externos
  escapados no painel; números absurdos viram erro de validação. SEC-07 já vinha resolvido (0.8.4).
- Todos os 11 achados da auditoria de 2026-10-25 têm correção no código. Pendências fora do código: saída do
  container para rede interna e proteção do branch `main` (exigem acesso do dono).
- Próximo: confirmar o CI da 0.9.2; nova auditoria completa quando houver mudança grande ou antes do uso real.

## Mascote animado na Visão geral (2026-10-25, versão 0.11.0)
- Pedido do dono: mascote do tamanho de um cartão, ao lado do Monitor, que mostra o humor da carteira e reage
  às notificações. Imagens em `web/mascote/*.webp` (recortadas do SVG que o dono enviou; ficou de fora a pose
  segurando o logo do Photoshop, por ser marca de terceiros).
- `web/app.js`: `mascMood()` (humor: ≥+5% rindo, ≥+1% acenando, entre −1% e +1% pensativo, até −5% triste,
  abaixo chorando; monitor parado = bravo; sem trades = acenando "Oi"). Simulado usa o resultado desde o início;
  Real usa as últimas 24 h. `mascReact()` reage a cada evento por 6 s (usa `classify()`), mesmo com o som desligado.
  `classify()` passou a tratar "Top traders atualizados" como `trader` (antes caía como venda).
- CSS: `.kpirow` com `.kpis{display:contents}` — o mascote é o 8º cartão da mesma grade (ao lado do Monitor
  também no celular). Animações respeitam `prefers-reduced-motion`.
- Lembrete: o inventário de dependências guarda o hash de `app/version.py` e `web/app.html`; toda subida de
  versão ou mudança no HTML exige `python scripts/inventario_dependencias.py --refresh --date AAAA-MM-DD`
  antes do push, senão o Actions para em "conferir inventário de dependências".

## Mascote: ação de cada notificação (2026-10-25, versão 0.13.1)
- `mascKind(msg)` em `web/app.js` traduz cada mensagem de evento num título de ação + pose (lista na novidade
  0.13.1). Mensagens novas emitidas pelo motor devem ganhar uma linha ali. `mascReact` enfileira (até 5; 2,5 s
  cada, a última 6 s). Teste no console do navegador: `BB.mascote("[PUMP SIM] fechou X (stop de perda) → -0.04 SOL (-40.0%)")`.
- `classify()` (som): PAUSADO/robô agora é "alert" (antes caía em "stop" → som de venda); "segurando" não toca som.
