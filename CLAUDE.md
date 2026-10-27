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
- **Relatório da mudança (regra do dono, 2026-10-26):** toda IA que corrigir ou mudar a lógica de trades (a partir de
  um relatório do dia ou de um pedido) cria, na MESMA entrega, `app/relatorios_ia/AAAA-MM-DD-versao.md` no formato de
  `app/changes.py` (cabeçalho com versao, data, autor, baseado_em, projecao_sol_dia, projecao_texto + texto do que
  mudou e como medir). A projeção é em SOL por dia na carteira fictícia, com a conta; sem base, `nao_estimado` e por
  quê. Aparece em Relatórios → "Mudanças feitas pela IA" com o realizado 7 dias antes × depois.
  `tests/test_changes.py` falha se algum arquivo estiver fora do formato.
- Visual: tema escuro "painel profissional" (estilo inspirado em rbp-security-template.vercel.app — só o
  estilo, nada copiado). Botões liga/desliga: **verde = ON, vermelho = OFF**. Tem que funcionar no celular
  (menu vira gaveta, sem rolagem lateral). JS sem handlers inline (a CSP bloqueia).

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
- **Radar de KOLs / "ondas de influencer" (pedido do dono em 2026-10-25; primeira etapa implementada na 0.16.0, detalhes abaixo).** Exemplo:
  https://pump.fun/coin/C5xph2yL6gMdxmuLGxJBkGpmuDFfyi5fqkBNhvL6pump — no gráfico da pump.fun aparecem dezenas de
  avatares de traders conhecidos comprando em sequência e o preço sobe forte. Objetivo: identificar RÁPIDO quando
  várias carteiras conhecidas entram no mesmo token e decidir se vale entrar cedo e sair na onda. Sugestão:
  1. Primeira etapa FEITA: N carteiras em estudo comprando o mesmo token em X minutos; sem identidade KOL verificada.
     Pendente: carteiras rotuladas (KOL/influencer/smart money).
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

## Radar de KOLs — primeira etapa (2026-10-25, versão 0.16.0)
- Novo menu `Radar de KOLs`, com marca NOVO, ON/OFF (começa OFF) e critérios por usuário:
  `pump_radar_min_wallets` (2–30, padrão 2), `pump_radar_window_min` (1–30 minutos, padrão 5).
  Configurações salvas pela rota existente `/api/pump/settings`; leitura autenticada `/api/pump/radar`.
- `app/radar.py`: buffer compartilhado limitado a 5.000 eventos/30 min; deduplica por carteira+assinatura
  e filtra a lista ATUAL `pf.study` de cada conta antes de calcular. Conta carteiras distintas por token,
  volume de compras/vendas em SOL, pressão desse volume e vendas posteriores à primeira compra observada.
  Mostra início, participantes e janela incompleta caso atinja limites. Reiniciar o processo zera as ondas.
- `app/monitor.py`: carteiras apenas em estudo agora chegam à fila de leitura mesmo sem seguidores.
  Notificação deduplicada por carteira+assinatura para observar duas carteiras na mesma transação.
  Observação de robô/outro mercado não libera cópia: filtros existentes continuam no caminho de execução.
- Avisos efêmeros `Radar:` via `_emit` para nova onda e primeira venda, com toast, reação do mascote e
  som opcional no painel conectado. Consultar o radar não repete alertas; OFF e remoção do estudo suprimem sinais.
  Avisos não entram no histórico persistido do Feed. Nenhuma ordem simulada ou real é criada pelo Radar.
- Fonte nesta etapa: somente carteiras adicionadas ao estudo, sem identidade de influencer comprovada,
  descoberta automática, importação Kolscan ou consultas novas à Solana Tracker. Pressão observada não é
  todo o mercado, saldo da carteira nem previsão de lucro. Monitor pode perder eventos.
- Limitação histórica preservada: `wallet_trades` ainda tem PK só por assinatura e guarda uma carteira por
  transação. `flush_trades` remove assinaturas repetidas no lote antes do upsert para o PostgreSQL não recusar
  o lote inteiro. O Radar guarda as carteiras separadas em memória; corrigir a PK histórica exige migração futura.
- Sem dependências, migrações ou acesso administrativo remoto novos. Inventário Markdown/JSON/PDF regenerado
  com runtime PDF preexistente por causa dos hashes de versão/HTML; nenhum pacote instalado no Windows.
- Validação local: 8 testes puros do Radar com Python padrão; sintaxe Python/JS e `git diff --check`.
  Integração coberta por 18 novos casos para o CI; pytest local indisponível sem dependências (não reinstaladas).
  Prévia com dados fictícios inspecionada em desktop e 390 px, sem rolagem lateral; controles ON/OFF conferidos.
  CI do commit `ae0e81054f7285e06b95cfbbf2e7255872a061eb`: **130 testes passaram**, 7 subtestes passaram e 1 aviso.
  Actions `40242835935` concluído com sucesso (testes, banco, imagem e deploy); o próprio workflow confirmou
  a versão 0.16.0 no `/health`. Nenhum acesso administrativo remoto feito pelo agente. O fluxo do Radar com
  dados reais, login de produção e RLS efetivo do Supabase não foram validados nesta tarefa.
- Próximas etapas: fontes de identidade verificadas e ranking de copiabilidade na onda; simulação de entrada/saída
  específica do Radar e medição de atraso; Telegram somente se solicitado. Não habilitar execução automática real.

## Hot callouts dentro do Radar (2026-10-25, versão 0.17.0)
- Pedido confirmado pelo dono: destacar e ordenar as ondas existentes dentro do Radar de KOLs.
  A lista de ondas virou `Hot callouts`, com posição, estado, motivos e KPI `HOT agora`. Mesma tela,
  GET `/api/pump/radar`, buffer, lista em estudo, configurações e botão ON/OFF; sem módulo, rota ou monitor paralelo.
- `app/radar.py`: `callout_policy` devolve os critérios junto da resposta. HOT exige o mínimo configurado de
  primeiras entradas distintas nos últimos 120 s, última compra até 60 s, pressão observada >=80%, fluxo positivo,
  zero vendas observadas dos participantes e dados completos com monitor conectado. Sem compra por mais de
  180 s, a onda esfria. Estados: `hot`, `selling`, `watch`, `stale`, `incomplete`; dados incompletos e vendas
  impedem HOT. Não há nota de lucro, probabilidade ou verificação de identidade de influencer.
- Recompras não viram primeiras entradas novas ao sair da janela visível: uma varredura dos eventos retidos
  constrói âncoras efêmeras por carteira/token nos últimos 30 min (`entry_memory_s=1800`). Participantes, volumes,
  vendas e `convergence_span_s` continuam na janela configurada; `recent_wallets` usa essas âncoras maiores.
  Perda de âncoras por capacidade torna os callouts incompletos mesmo se anterior à janela visível. A memória
  continua limitada a 5.000 eventos e zera ao reiniciar; não reconstrói entradas anteriores ao que foi observado.
- Classifica e ordena antes de cortar as 100 ondas: HOT, vendas, observação, esfriou, incompleto; desempate por
  entradas recentes distintas, total de carteiras, pressão e última compra, depois mint. O filtro da lista ATUAL
  da conta vem antes de todas as métricas. Nenhuma nova consulta externa, migração ou dependência.
- Avisos `Radar: HOT callout...` reaproveitam `_radar_alerts`: primeira onda já HOT gera um único aviso;
  promoção posterior gera no máximo mais um por onda. GET só reclassifica; não avisa. ON/OFF, remoção e
  vendas continuam no caminho existente. Saturação com mais de 100 ondas pode repetir avisos normais quando
  uma onda sai/volta à lista limitada; nesse estado nenhuma recebe HOT. Não há ordens simuladas ou reais novas.
- `web/app.js`: critérios visíveis vindos da API, escape de motivos e símbolos, rascunho preservado.
  Falha de GET Radar ou `/api/pump` retira HOT; o intervalo existente do painel também vence a leitura após 8 s,
  antes da trava BUSY, inclusive se a consulta ficar pendurada. Salvar critérios/ON-OFF exige nova leitura.
- Validação local: 22 testes puros com Python padrão; QA Node/vm de renderização, escapes, rascunho, ON/OFF,
  falhas e consulta pendurada; sintaxe Python/JS e diff. Mais 4 testes API novos preparados para o CI, sem
  reinstalar dependências no Windows. Prévia com dados fictícios conferida no desktop e em 390 px, sem rolagem
  lateral; salvar o mínimo de 3 carteiras atualizou os destaques e falha simulada retirou todos os HOTs.
  CI do commit `0d1415f64a4c8d6e2cd00e22d743eb2c0d5ab0db`: **148 testes passaram**, 12 subtestes passaram e 1 aviso.
  Actions `40244372068` concluído com sucesso em testes, banco, imagem e deploy; o workflow confirmou a versão
  0.17.0 no `/health`. Nenhum acesso administrativo remoto foi feito pelo agente.
- Inventário Markdown/JSON/PDF atualizado por mudança de versão/HTML, usando o runtime PDF preexistente.
  O fluxo com dados reais e o login de produção não foram executados; execução real permaneceu fora do escopo.

## Compartilhar carteira em estudo (2026-10-25, versão 0.17.1)
- Botão Compartilhar em Carteiras estudadas: `GET /api/pump/study/share-targets` (outros usuários, sem bloqueados,
  e-mail mascarado `ab***@dominio`) e `POST /api/pump/study/share` (`hub.study_share`): só quem estuda a carteira
  compartilha; insere em `study_wallets` do destino com o apelido de quem envia (ou "de <nome>"); respeita o limite
  de 30; `audit_log` nos dois lados. Sem migração. Teste em `tests/test_estudo.py`.

## Menu "Usar ou descartar" (2026-10-25, versão 0.17.2)
- Pedido do dono: tudo que foi criado nas entregas do douglasdeodato fica num menu só, como submenu, para ele
  decidir o que usar ou descartar. Grupo `#navGrp` em `web/app.html` (abre/fecha, lembra em `pf_menu_grp`):
  Carteiras em estudo, Radar de KOLs, Relatórios, Aprendizado diário, Opções novas de cópia (`data-view="novas"`)
  e Novidades (admin). As opções ON/OFF novas saíram de Configurações para `novas` (mesmas chaves `pump_*`;
  "Só copiar traders online" é da 0.9.0 do Bruxo95 e ficou em Configurações). Marcas NOVO mantidas.
- Funcionalidade nova que ainda está em teste entra nesse grupo.
- 0.17.3: o grupo inteiro é só do admin (pedido do dono em 2026-10-25): `#navGrp` escondido, `route()` manda
  não admin para a Visão geral e o Status das configurações esconde as opções novas.
- 0.17.4: as rotas `/api/pump/study*`, `radar`, `reports` e `aprendizado` usam `admin_engine`/`admin_only` (403 para
  usuário comum); Compartilhar só lista e aceita admins. Testes que usam o usuário B nessas rotas chamam
  `db.set_role(UB, "admin")`; regra nova em `tests/test_admin.py::test_usar_ou_descartar_routes_are_admin_only`.

## Estratégias fantasma e pós-trade (2026-10-26, versão 0.18.0)
- Pedido do dono: "faz tudo" da lista de melhorias guardada na memória (estratégias fantasma, pós-trade, saídas,
  nota 0–100, banca, lista negra, Telegram, base da pump.fun…). Entregue em etapas; esta é a 1ª.
- `app/ghosts.py`: cada cópia fictícia aberta abre 10 posições fantasma (`VARIANTS`) com a mesma entrada; o motor
  avisa em `_copy` (abertura e venda do trader, via `_sell_frac`), `_check_stops` (preço) e `check_timeouts`.
  O monitor inclui os tokens dos fantasmas no preço e nos stops (`_gm`). Resultado agregado em `ghost_stats`
  (migração `20261026000001`, uma linha por usuário, gravada a cada 5 min em `hub.save_ghosts`); posições
  fantasma abertas só em memória. Tela `#fantasma` (admin), rota `/api/pump/ghosts` (admin).
- Pós-trade: `best_pct`/`worst_pct` na posição (`_check_stops`) e no trade fechado (simulado e real);
  `reports.mesa()` → cartão "Quanto ficou na mesa" em Relatórios.

## Saídas inteligentes, nota e banca (2026-10-26, versão 0.19.0)
- Opções novas em `USER_KEYS` (todas OFF): `pump_exit_dev_sell`, `pump_exit_migrate`, `pump_exit_pressure_*`,
  `pump_exit_kol_*`, `pump_score_min_*`, `pump_size_by_score`, `pump_streak_*`, `pump_cold_*`. Tela "Opções novas".
- `PumpFun.smart_exit` (em `_check_stops`): dev vendeu (`tk["dev_sold_t"]`, marcado no `ingest`), graduou
  (`p["grad_in"]`), pressão virou (após 60 s), N carteiras seguidas/estudadas vendendo (`p["kol_sellers"]`, no `react`).
- `entry_score` (0–100, pesos trader 25, risco 20, pressão 15, curva 15, preço 15, onda 10; parte sem dado sai da
  conta) gravado em `p["score"]`, no trade e no feed. `cold_market` e `_streak_check` (pausa só em memória).
- `reports.build` → `by_score` (faixas de nota). Fantasmas ganharam as variantes `dev` e `migra`.
- Testes: `tests/test_saidas.py`.

## Lista negra e Telegram (2026-10-26, versão 0.20.0)
- Lista negra compartilhada: `PumpMarket.blacklist` (+ `bl_new`), tabela `blacklist` (migração `20261026000002`,
  só backend). Entra sozinho: criador com `risk.rugged` e criador quando a cópia fecha por "dev vendeu" no prejuízo.
  `hub.load_blacklist` no start, `flush_blacklist` a cada 60 s (no `ghosts_loop`). Bloqueio só com
  `pump_blacklist_on`. Tela `#listanegra` e rotas `/api/pump/blacklist` (admin).
- Telegram: chaves pessoais `telegram_bot_token` e `telegram_chat_id` (validadas em `/api/secrets`); `pf.tg` →
  `hub.tg_queue` (só com `pump_tg_on`; `pump_tg_all` OFF = só `TG_KEYS`); `hub.tg_send_now` (máx. 20/min);
  `POST /api/pump/telegram/test` (admin). Testes: `tests/test_lista_telegram.py`.

## Base própria da pump.fun (2026-10-26, versão 0.21.0)
- `app/tokenlab.py` (`hub.lab`): todo `create` da PumpPortal (até `MAX_PER_MIN`=40/min) entra em observação;
  `SharedMonitor.lab_loop` (20 s) lê a curva on-chain em lotes de 100 e tira fotos aos 1/5/15/60 min; `label()` dá
  graduou/5x/2x/subiu pouco/morreu/despencou. Limite: só 4 fotos, o pico real entre elas não é visto.
- Tabelas (migração `20261026000003`, só backend): `token_life` (só tokens interessantes, 7 dias via
  `trim_token_life`), `market_hourly`, `creator_stats`. `hub.save_lab` a cada 2 min; `load_lab` no start.
- `PumpMarket.creator_stats` → parte "criador" (peso 10) da nota da entrada; criador com 3+ despencados e nenhum 2x
  entra na lista negra. Tela `#base` e rota `/api/pump/base` (admin). Testes: `tests/test_tokenlab.py`.

## E se e onde o dinheiro vai (2026-10-26, versão 0.22.0)
- `reports.whatif()` (estimativa com `best_pct`/`worst_pct`; se o trade passou pelos dois, o stop conta primeiro) e
  `reports.custo()` (entrada × `trader_px`, taxas sobre o investido, bruto × líquido). Trades guardam `trader_px`
  (preço do trader no evento) desde a 0.22.0. Testes: `tests/test_whatif.py`.
- Pedido "faz tudo" de 2026-10-26 entregue em 0.18.0–0.22.0. NÃO feito, por regra do projeto: velocidade para o modo
  real (RPC próprio/gRPC, Jito) — o real segue travado. Previsão por modelo fica para quando houver semanas de dados
  na base da pump.fun; por enquanto a calibração é a tabela "Nota da entrada × resultado".

## Botão Comprar na Base da pump.fun (2026-10-26, versão 0.23.0)
- Pedido do dono: comprar direto da tela ("não dá tempo de abrir e comprar"). `PumpFun.manual_buy` (sem filtros de
  cópia; `wallet="manual"`, `p["manual"]=True`): fictícia sempre; real só com `pump_real_enabled`, pela fila
  `_rq_put("buy")` (mesmos limites e `_real_buy`). Rota `POST /api/pump/manual-buy` (admin; lê a curva na hora se não
  houver preço; `audit_log` "compra manual"). O real continua travado por `PUMP_REAL_ALLOWED`.
- `TokenLab.rising()` → lista "Subindo agora"; rótulo "nasceu graduado" quando o market cap da criação já é ≥ 300 SOL
  (caso GTA6). Tela com "Como ler esta tela" e atualização a cada 20 s. Testes: `tests/test_compra_manual.py`.

## Boost, base persistente e aprendizado da base (2026-10-26, versão 0.24.0)
- Boost pago: `GET /orders/v1/solana/{mint}` da DexScreener (documentado; formato conferido em 2026-10-26) →
  `PumpFun.parse_orders` (ON = boost pago nas últimas 24 h; duração real do boost não documentada) e `boosts.active`
  dos pares; `SharedMonitor.boost_loop` (60 s, máx. 20 tokens/min, cada um a cada 2 min) para "Subindo agora" e
  tokens em posição; `market.boosts`. Ficha do token também traz `boost`.
- Pedido do dono: 3 tokens sumiram da tela depois da publicação da 0.23.0 (memória zerada no reinício). Agora
  `lab_state` (migração `20261026000004`) guarda os tokens em observação a cada 2 min e `load_lab` restaura;
  `token_life` guarda TODOS os tokens fechados por 14 dias (antes só os interessantes, 7 dias) e volta para a memória
  (`TokenLab.restore`, até 30 mil). Lista "Suas compras desta tela" (`mine` em `/api/pump/base`; trades com `manual`).
- `TokenLab.lessons()`: % que sobe/despenca por faixa de sinal (ganho 1 e 5 min, compra do dev, criador, boost,
  hora); "sinal forte" = 30+ tokens e o dobro da média. Testes: `test_boost.py`, `test_base_estado.py`.
- Volume esperado do `token_life`: até 40 tokens/min → algumas dezenas de MB em 14 dias; acompanhar o tamanho do banco.

## Ajuste da Base da pump.fun (2026-10-26, versão 0.24.1)
- "Tokens que subiram" em largura total no fim da tela (`#bsUpCard`), pedido do dono. `TokenLab.restore` refaz os
  rótulos graduou/nasceu graduado gravados antes da 0.23.0 (market cap de criação ≥ 300 SOL = nasceu graduado).

## Previsão na Base da pump.fun (2026-10-26, versão 0.25.0)
- `TokenLab.predict`: chance = média da base ajustada pela razão de chances de cada faixa aprendida com 30+ tokens
  (ganho 1/5 min, compra do dev, criador, boost); regras duras → "lixo" (lista negra, criador com 2+ despencados e
  nenhum 2x, voltou abaixo do início, 3+ clones do símbolo na última hora); market cap > `CURVE_MAX` (450) → "suspeito"
  (visto: vários tokens a 721 SOL em 2026-10-26, causa não confirmada). Previsão a cada foto; a dos 5 min fica em
  `pred5`/`chance5` e vira a tabela de acerto em `lessons()`. Opção `pump_base_hide_trash`. Testes: `test_previsao.py`.

## Botão Comprar configurado (2026-10-26, versão 0.26.0)
- Pedido do dono: valores prontos para comprar sem digitar. Opções `pump_manual_*` (sol 0,1; stop 30%; alvo 100%;
  stop móvel +30%/15 pts; `pump_manual_boost_on`/`_tp` = com Boost ON vende em +80%, interpretação do pedido "se o
  boost tá on 80% ele dá um stop"). `PumpFun.manual_rules()` grava na posição (`stop_pct`, `tp_pct`, `trail_*`,
  `boost_tp`); `_check_stops` usa os da posição quando existem (cópias seguem as regras gerais). Real: `pos_cfg` na fila.
  Testes: `tests/test_botao_comprar.py`.

## Compra automática da Base (2026-10-26, versão 0.27.0)
- Pedido do dono: entrar sozinho quando o token tiver Boost ON e deixar tudo automático ("não vamos estar online").
  `PumpFun.auto_check(rising)` (opções `pump_auto_*`, tudo OFF por padrão; real só com `pump_auto_real` E a execução
  real ligada) chama `manual_buy(..., auto=motivo)`; `SharedMonitor.auto_once` roda a cada ~20 s no `lab_loop`.
  Um token por vez (`_auto_done`, só memória), máx. N/hora, até X min de vida, nunca lixo/suspeito. Telegram avisa
  "compra automática" e "boost on". Testes: `tests/test_auto.py`.

## Explorar (2026-10-26, versão 0.28.0)
- Pedido do dono: usar o pump.fun/explore. A API do site (`frontend-api-v3.pump.fun`) responde com o desafio
  anti-robô da Cloudflare ("Just a moment...", conferido em 2026-10-26) — não burlar. Fonte: Solana Tracker
  `GET /tokens/multi/all` (documentada; latest/graduating/graduated), chave própria de algum usuário ou a do sistema,
  1 consulta a cada 5 min (`explore.EVERY_S`) no `SharedMonitor.explore_loop`. Formato lido de forma defensiva e NÃO
  testado com a chave real nesta entrega.
- `app/explore.py`: veredito (lixo/fraco/possível/chance alta) e aprendizado "quase graduando → graduou?" por faixa
  de curva (só memória; recomeça no reinício). Tela `#explorar`, rota `/api/pump/explore` (admin). A compra manual
  agora busca o preço na DexScreener quando o token já graduou. Testes: `tests/test_explore.py`.

## Seu resultado copiando (2026-10-26, versão 0.29.0)
- Pedido do dono: ver o ganho real depois de copiar, separado da estimativa do ranking. `study_my_results` em
  `app/api.py` (campo `mine` de `/api/pump/study`): trades e posições do usuário com `wallet` = carteira em estudo,
  fictício e real separados. Quadro "Seu resultado copiando" abaixo de Carteiras estudadas. Teste em `test_estudo.py`.

## Entrada automática do Explorar (2026-10-26, versão 0.30.0)
- Plano: `docs/PLANO-AUTO-EXPLORAR-E-BASE.md`. O dono confirmou a divisão: **0.30.0 = Explorar e estrutura
  compartilhada; Base na 0.31.0; estudo por faixas na 0.32.0**. `auto_check` e as regras antigas da Base continuam
  nesta entrega; o botão Comprar mantém `pump_manual_*`. Não avançar a próxima versão nesta tarefa.
- `pump_ex_auto_on` começa OFF, só admin: Quase graduando, veredito chance alta, pressão ≥60%, holders ≥100,
  risco ≤6 quando disponível, curva 60–95%, variação 5 min 0–150%, sem rug/criador bloqueado ou com 2+ rugs.
  Monitor usa a lista com até 5 min e cotação com até 30 s, revalida conta/admin e fonte depois dos awaits.
- `pump_ar_*`: 0,05 SOL fictício; máx. 3 posições/4 entradas por hora; perda diária 0,25 SOL pausa até 00 UTC;
  3 perdas seguidas pausam 1 h. Pausas derivadas do histórico sobrevivem ao reinício e à recuperação posterior.
  Stop25%, metade em +40%, stop móvel +40%/15 pontos, alvo150%, Boost80% pelas opções existentes, tempo30min;
  dev vendeu/pressão<40% após1min/graduação forçam saída só das posições configuradas. Perdas dessas operações
  não acionam a pausa ou a redução de valor das cópias. Real depende das duas travas existentes; não foi ligado.
- Migração nova `20261026000005_operacoes_auto.sql`: `auto_trades`, leitura RLS da própria conta, escrita do
  navegador revogada. `app/auto_trades.py` calcula registro/resumos; Hub carrega 24 h, fechamentos relevantes e
  aberturas antigas antes de liberar entradas. Falha no banco mantém pendências e pausa novas entradas.
  Posição e trade final compartilham id; cooldown do mint24h persiste. Fotos de preço15/60min exigem cotação
  após o marco em janela de até120s; foto perdida fica N/D. Saturação do limite de100 tokens da rotina de preços
  pode perder uma foto, sem inventar resultado. `GET /api/pump/auto-trades` é só admin, filtra user_id do token.
- Explorar ganhou três quadros: entrada/filtros, proteções e operações. Resumos de fechadas simuladas após taxas;
  critério informativo100fechadas/7dias distintos/acerto45%/fator1,3, sem ligar real. Ausência de chance não vira0%.
- Validação local: testes novos do motor e cálculos puros com Python já disponível, harnessJS e prévia fictícia
  desktop/celular; nenhum pacote instalado no Windows. O dono reiterou "fazer os commits e enviar": pytest
  completo fica no Actions existente antes dos jobs de banco/imagem/deploy. Resultado do CI/publicação a registrar.
- Segurança: esta entrega inclui regressões de autorização/RLS; não é nova auditoria completa e não altera os
  achados históricos em `docs/AUDITORIA-SEGURANCA.md`. Nenhuma transação real ou acesso direto a infraestrutura.

## Travas das entradas automáticas (2026-10-26, versão 0.31.0)
- Pedidos do dono em áudio (transcritos com o Whisper local, `~/whisper-local`, pasta `C:\Users\doug\audios-pump`):
  "esperar uns 20 min", "muita carteira nova = robô, não entrar", "só entrar quando um dos melhores traders entrou".
- `PumpFun.auto_safety(mint, idade)` em TODA entrada automática (Base `auto_check` e Explorar
  `explore_entry_reason`): `pump_ar_min_age_min` (20), `pump_ar_fresh_on`/`_max_pct` (30% dos 20 maiores
  detentores; `fresh_check` via RPC `getSignaturesForAddress`: nova = <25 transações e 1ª há <72 h; cache 3 min;
  `SharedMonitor.fresh_loop` checa até 4 candidatos a cada 30 s), `pump_ar_smart_on`/`_min` (`smart_in`: seguidas,
  aptas do ranking e em estudo com saldo no token). `pump_auto_max_age` padrão 15 → 45. `safety_marks` na API marca
  lixo por carteiras novas. Limite honesto: a pump.fun conta TODAS as carteiras novas; aqui só os 20 maiores.
- Plano do Codex renumerado: Base = 0.32.0, estudo = 0.33.0. Testes: `tests/test_auto_seguranca.py`.

## Criadores consertados: bundle (2026-10-26, versão 0.31.1)
- Dono: "criadores com tokens que subiram" sem sentido (283 tokens, 253 subiram). Medido ao vivo (Node + PumpPortal +
  RPC): robôs compram a curva inteira junto com a criação; 28 SOL viravam 733 SOL na foto de 1 min. `tokenlab.label`
  dá "bundle" (acima de `CURVE_MAX`, ≥300 SOL na foto de 1 min ou graduado antes da 2ª foto); não conta como subiu;
  `creator_stats.bundles` (migração `20261026000006`); 2+ bundles = lixo (`predict`, `explore.verdict`) e lista
  negra. `TokenLab.restore` refaz todos os rótulos e `rebuild()` recalcula criadores e rótulos por hora (o que estava
  no banco é sobrescrito). Tokens `is_mayhem_mode` não são vigiados (market cap da curva não bate).

## Maiores traders (2026-10-26, versão 0.31.2)
- Pedido do dono: menu dos maiores traders (como o leaderboard da pump.fun), atividade minuto a minuto, estudo,
  sinais, compra automática, gráficos e sugestões. O leaderboard do site da pump.fun fica atrás da Cloudflare; a fonte
  é o ranking da Solana Tracker que o sistema já usa (top 15 por lucro, sem bandeira de robô/dev/corretora).
- `app/elite.py` (`hub.elite`): `on_trade` (chamado em `SharedMonitor.handle_tx` para essas carteiras, que já são
  assinadas por estarem no top 60), sinal = 2+ em 10 min ou compra ≥5 SOL de um só (`SharedMonitor.ELITE`);
  `tick` acompanha 60 min (preço pelo `held()`), `study`/`suggestions` (base mínima 8–15). Tabela `elite_signals`
  (migração `20261026000007`, também libera `origem='elite'` em `auto_trades`). `AUTO_ORIGINS` em `pumpfun.py`.
- Compra automática: `pump_el_auto_*` (OFF), `PumpFun.elite_auto` usa `manual_buy(origem="elite")` com as proteções
  `pump_ar_*`; `elite_sell` vende quando um trader do sinal vende (`pump_el_follow_sell`). Tela `#elite` com gráfico de
  lucro acumulado (SVG, uma série) e barras por trader; rota `/api/pump/elite` (admin).
- Carteiras em estudo: "Seu resultado copiando" mostra carteiras copiadas sem trade e o `diag` (compras vistas,
  copiadas e motivos de "não copiou" do feed). Versão 0.31.2 para não colidir com a 0.32.0 do plano do Codex.

## Maiores traders: acerto, saldo, idade e sugeridos (2026-10-26, versão 0.31.3)
- Pedido do dono: abas por % de acerto em cima, portfólio, idade da carteira, sugestões de 80%+ de acerto.
  `Elite.recommended()` (acerto ≥80% e ≥100 trades), `PumpFun.wallet_age` (até 4 páginas de 1.000 assinaturas no RPC
  grátis; mais que isso = "pelo menos", `more=True`), `SharedMonitor.elite_info_once` (saldo via `wallet_value` e idade,
  3 consultas por minuto). "Portfólio" = SOL + USDC/USDT; memecoins que a carteira segura NÃO entram no valor.

## Copiar os sugeridos 80%+ e Steps ao vivo (2026-10-26, versão 0.31.4)
- Pedido do dono: "quando o acerto é 80%, acompanhar e copiar compra e venda; aba Steps em tempo real".
  `pump_el_copy80` (padrão ON a pedido do dono; só simulado, real depende da execução real liberada).
  `SharedMonitor.elite_follow_sync` põe `Elite.recommended()` em `PumpFun.elite_follow`; `refresh_followed` trata como
  manuais (copia compra e venda proporcional pelo motor normal, com os filtros de Configurações).
  `Elite.steps` junta cada negociação deles com o feed do usuário (±180 s) e a posição; rota `/api/pump/elite/steps`.

## Relatório do dia (2026-10-26, versão 0.31.5)
- Pedido do dono: guardar os números da Visão geral, aprender e, no fim do dia, sugerir melhorias no código, trades e
  lógica. `app/daily.py` (`kpis`, `build`, `telegram_text`), `hub.save_daily` a cada 30 min (`daily_loop`), tabela
  `daily_report` (migração `20261026000008`, uma linha por usuário/dia com as fotos); na virada do dia (UTC) fecha o dia
  anterior e manda o resumo no Telegram (se ligado). Rota `/api/pump/daily` (admin; hoje é calculado ao vivo).
  Quadro "Relatório do dia" na Visão geral só para admin. Testes: `tests/test_daily.py`.

## Relatórios dos dias passados e aprendizado de vários dias (2026-10-26, versão 0.31.6)
- `daily.days_with_trades` + `hub.backfill_daily` (uma vez por motor, até 60 dias, só os que faltam; marcados
  `backfilled`, sem as fotos de 30 min, com `equity_end`); também disparado pela rota se ainda não há dias passados.
  Cada sugestão tem `tipo`; `daily.study` junta os dias: problemas que se repetem (`recurring`), origens/saídas/traders
  somados, sugestões de vários dias. Quadro "Aprendizado dos dias" na Visão geral (admin). Onde ficam as sugestões:
  Visão geral (dia e vários dias), Maiores traders, Aprendizado diário e Relatórios.

## Relatórios em PDF e mudanças da IA (2026-10-26, versão 0.31.7)
- `app/pdf.py`: PDF só com a biblioteca padrão (Helvetica/WinAnsi; sem dependência nova). `daily.blocks`/`ai_text`;
  rotas `/api/pump/daily/pdf` e `/api/pump/daily/ai` (admin; `daily_data` em api.py), `BB.download` no common.js
  (baixa com o token). `app/changes.py` + pasta `app/relatorios_ia/` (vai na imagem Docker com `COPY app`), rotas
  `/api/pump/changes` e `/api/pump/changes/{nome}?pdf=1`. Abas em Relatórios. Regra para as IAs na seção "Como
  trabalhar aqui". Primeiro relatório: `app/relatorios_ia/2026-10-26-0.31.7.md` (projeção não estimada: sem base).

## Horário dos trades nos relatórios (2026-10-26, versão 0.31.8)
- Pedido do dono. `daily.build` devolve `trades_list` (entrada/saída em Europe/Berlin via zoneinfo, `TZ_NAME`, até 300)
  e `by_hour`; sugestão `horario_ruim` (3+ horas com 3+ trades e a pior no prejuízo). PDF/texto para IA e o quadro
  "Relatório do dia" mostram a lista.

## Relatório de cada menu (2026-10-26, versão 0.31.9)
- Pedido do dono: cada menu gera relatório diário com o que mudar para ganhar mais, tudo junto em Relatórios e no
  aprendizado. `app/modules_report.py` (`build(hub, pf, dia, ao_vivo)`, um menu por função, falha isolada) →
  `rep["modules"]` em `save_daily`, `backfill_daily` (sem dados ao vivo) e na rota; `daily.blocks` põe no PDF/texto
  para IA; `daily.study` conta as sugestões dos menus (`tipo` = `menu:<menu>:<chave>`). Quadro do dia mostra a seção.
  Menu novo daqui em diante deve ganhar uma função aqui.

## Correções a partir dos relatórios de 26/10 (2026-10-26, versão 0.31.10)
- Relatório da mudança: `app/relatorios_ia/2026-10-26-0.31.10.md` (projeção +0,02 SOL/dia se a saída por
  estagnação for ligada). `Elite.bot_reason` (compras <0,01 SOL repetidas ou `_is_bot`) tira dos sugeridos 24 h e o
  Steps explica; `pump_exit_stale_*` (OFF) em `smart_exit`; fantasmas `parado45` e `max1h`; `daily`: sugestão
  `tempo_maximo` e `worst_trades`. Testes: `tests/test_correcoes_2610.py`.

## Por que está no vermelho (2026-10-26, versão 0.31.11)
- Pedido do dono (print de "Quanto você ganhou ou perdeu copiando cada trader"). `reports.loss_cause`/`autopsy`
  (`CAUSES` com a correção de cada causa; por trader: causa principal, holder longo ≥3 h, 0 acertos → pausar/banir).
  `daily.build` guarda `loss_causes`/`loss_traders` no `daily_report` e cria sugestões `causa_*` (recorrência no
  aprendizado). Quadro em Relatórios → Números. Testes: `tests/test_autopsy.py`.
- 0.31.11 (Explorar): `pump_ex_auto_on` passa a vir LIGADO (fictício) a pedido do dono ("tem muita chance alta e nada
  foi feito"); `auto_safety(..., origem="explorar")` não exige trader bom (só com `pump_ex_auto_need_smart`) e não
  espera a checagem de carteiras novas; a rota do Explorar devolve `auto` (compra ou motivo) por token.

## Aprender com os erros sozinho (2026-10-26, versão 0.31.12)
- Pedido do dono. `app/autolearn.py` (faixas por número da entrada guardado em `auto_info`; bloqueio com
  `MIN_N`=10, acerto <35% e média <-5%), `PumpFun.learned(origem)` (cache 60 s, avisa bloqueio novo), aplicado em
  `explore_entry_reason` com `pump_ar_learn` (ON). Base/elite ainda não guardam esses números na entrada (o Codex
  conecta a Base na 0.32.0 do plano). Relatório da mudança: `app/relatorios_ia/2026-10-26-0.31.12.md`.

## Estudo automático de carteiras (2026-10-26, versão 0.31.13)
- Pedido do dono. `app/autostudy.py` + `PumpHub.study_auto` (`study_auto_loop`, 30 min; `pump_st_auto_on` ON,
  `pump_st_auto_max` 15; 3 por volta). Só carteiras com apelido "auto · " são julgadas/removidas. Decisões em
  `study_auto_log` (migração `20261026000009`); `rates()` aprende por fonte/faixa de acerto/faixa de trades.
  Rota `POST /api/pump/study/auto/run` e campo `auto` em `/api/pump/study` (admin). Não copia nada sozinho.
  Testes: `tests/test_autostudy.py`.

## Ajuste automático (2026-10-26, versão 0.31.14)
- Pedido do dono ("a IA ver, rever e corrigir sozinha"). `app/autotune.py` + `PumpHub.auto_tune` (`tune_loop`, 6 h;
  `pump_tune_on` ON). Aplica a variante dos fantasmas (`variant_settings`; `sem_trader` não tem opção equivalente)
  com `MIN_TRADES`=30, `MIN_DAYS`=2, margem 0,001 SOL/trade; avalia após 48 h/15 trades e desfaz se piorar
  (rejeita 7 dias); pausa trader ruim 48 h (só cópias de trader). Para com o real ligado. `auto_tune_log`
  (migração `20261026000010`), rotas `/api/pump/tune` e `/api/pump/tune/run` (admin). Testes: `tests/test_autotune.py`.
  Não é uma IA de linguagem: são regras com medição antes × depois.

## Tempo legível nas Carteiras em estudo (2026-10-26, versão 0.31.15)
- Pedido do dono: tempos em s/min/h/dias. `hms()` em `web/app.js` (agora "N dias" em vez de "N d") usado também em
  Carteiras em estudo (lista e perfil) e no Aprendizado diário.

## Compartilhar configuração do Explorar (2026-10-26, versão 0.31.16)
- Pedido do dono. `POST /api/pump/explore/share` {to, part: filtros|protecoes|tudo} → `hub.explore_share` (só para
  admin não bloqueado; copia `pump_ex_auto_*` e/ou `pump_ar_*`, salva, avisa e registra no `audit_log`). Destinos pela
  rota já existente `/api/pump/study/share-targets`. Testes: `tests/test_explore_share.py`.

## Convites de configuração (2026-10-26, versão 0.31.17)
- Pedido do dono. `hub.config_offer/config_offers/config_answer` + tabela `config_offers` (migração
  `20261026000011`). Rotas: `/api/pump/config/share-targets` e `/api/pump/config/share` (admin; seção = chaves dos
  campos do cartão, ou `all`), `/api/pump/config/offers` e `/api/pump/config/offers/{id}` (quem recebe).
  `share_filter` tira chaves com "real" e `pump_tg_*`; para não admin tira `pump_ex_auto_*`/`pump_ar_*`.
  Explorar → Compartilhar (0.31.16) agora também vira convite. Barra `#offerBar` no topo (`loadOffers`, a cada 30 s);
  botões das seções criados por `cfgShareButtons()`. Testes: `tests/test_explore_share.py`.

- 0.31.18: o quadro Compartilhar de Configurações lista as seções com caixinhas (`cfgShareCards()`, `#cfShSecs`) e
  "Marcar todas"; todas marcadas = `all` (toda a configuração). Pedido do dono ("enviar todas, não só uma").

- 0.31.19: Explorar → Minhas operações automáticas ganhou "Ganhou × perdeu" (`#exAutoWL`, calculado no navegador a partir
  de `items` de `/api/pump/auto-trades`) e filtro Todas/Ganhou/Perdeu/Abertas (`EX_AUTO.filt`). Pedido do dono.

- 0.31.20: sanfona (`sanfona()` em `web/app.js`, classes `.sanf`/`.fechado` em `app.css`): cartão com 3+ `data-cfg/
  toggle/set` (ou `#secretsCard`) começa fechado; estado em `localStorage` `pf_sanf`. Fora: telas `real` e `estudo` e
  os painéis `*Share`. Pedido do dono.

## Melhorias do Explorar depois de 9 perdas em 12 (2026-10-26, versão 0.31.21)
- Pedido do dono. `Ghosts(pf, variants, base, mine)` (configurável); `pf.ghosts_auto` com `AUTO_VARIANTS`/`AUTO_BASE`
  (abre em `manual_buy` para origem explorar; preço/tempo nos mesmos ganchos; salvo em `ghost_stats.data.auto`).
  `auto_variant_settings` + `tipo saida_auto` no `auto_tune` (`AUTO_MIN_TRADES`=20; migração `20261026000012`).
  Opções `pump_ar_press_min` (1; 0 = não usa) e `pump_ar_exit_grad` (ON) em `auto_rules`/`smart_exit`.
  `autolearn.MIN_N` 10 → 6; `autolearn.compare` → `compare_auto` em `/api/pump/explore`. Testes:
  `tests/test_explorar_melhorias.py`. Relatório: `app/relatorios_ia/2026-10-26-0.31.21.md`.

## Convite de configuração legível (2026-10-27, versão 0.31.22)
- Pedido do dono ("está muito sujo"). `config_offers` devolve `valores`; `offerList`/`cfgLabel`/`cfgUnit` em `web/app.js`
  pegam o nome da opção no próprio HTML (label, aria-label ou título) e mostram "seu valor → valor enviado", só o que muda.

## Resposta do convite avisa quem enviou (2026-10-27, versão 0.31.23)
- Pedido do dono. `hub.config_answer` carrega o motor de quem enviou (`self.engine`) e emite o aviso (entra no Telegram
  por `TG_KEYS` "seu convite de configuração"); `audit_log` nos dois lados com nomes ("convite de configuração aceito/recusado").

- 0.31.24: a seta da sanfona em `app.css` tinha um byte de controle no lugar do `\25BE` (aparecia "BE"); corrigido.
  Escapes com barra invertida gravados por heredoc viram bytes: gravar CSS/JS com escape por script Python.

- 0.31.25: `KEY_HOW`/`keyHow()` em `web/app.js` (passo a passo por chave, em `<details class="keyhow">`) em Chaves pessoais
  e Chaves do sistema. Pedido do dono. Os nomes de botões dos sites externos podem mudar: revisar o texto se mudarem.

- 0.31.26: `daily.build` → `best_trades` (5 maiores ganhos; PDF/texto para IA); tabela `#dayBest`; classe `daytbl` (fonte 12px,
  Origem/Motivo quebram linha) nas tabelas do Relatório do dia. Pedido do dono.

- 0.31.27: Chaves pessoais redesenhadas (`loadSecrets`: `#secretsSum`, `KEY_SHORT`, `KEY_NEED`, `KEY_EDIT`, `KEY_SAVED`,
  ação `secret-edit`; CSS `.keysum`, `.key-ok/sys/none`). Pedido do dono ("tudo junto, não sei se foi configurado").

## Execução real continua ligada após reinício (2026-10-27, versão 0.31.28)
- Pedido do dono: o real "desligava ao trocar de navegador"; a causa era o reinício do servidor a cada deploy.
  `hub.save_settings` grava `_real_on` quando o real está ligado; `/api/pump/real`, admin `real_off` e remover a carteira
  gravam. `hub._load` religa só com `real_allowed`, carteira e conta liberada (evento + `audit_log` "execução real
  religada após reinício"). Teste: `tests/test_api.py::test_real_stays_on_after_server_restart_until_user_turns_off`.

- 0.31.29: passo a passo da Jupiter (`KEY_HOW.jupiter_api_key`): Server key, nome 5–32 letras. Pedido do dono com print do portal.

- 0.31.30: menu "Novidades" renomeado para "Changelog" (só o texto; rota, arquivo `app/novidades.json` e regras iguais). Pedido do dono.

## Configuração recebida: idêntica ou mudou (2026-10-27, versão 0.31.31)
- Pedido do dono. Migração `20261027000001_convites_antes.sql` (coluna `antes` em `config_offers`); `hub.config_answer`
  guarda os valores de antes; `hub.config_applied` + `GET /api/pump/config/applied` (convites aceitos, 60 dias).
  `web/app.js`: `loadApplied`/`renderApplied` (selo `.cfgfrom` no cabeçalho de cada quadro de Configurações/Explorar,
  conferindo os valores atuais) e `openCfgDiff` (modal `#cfgDiff`). `/api/audit` e `/api/admin/audit` trocam uuid
  pelo nome (`_names`, `UUID_ANY`). Teste em `tests/test_explore_share.py`.

- 0.31.32: quadro `#cfShareTop` com `#cfAllU` + `#cfAllGo` (envia `all`); `cfgShareCards` ignora esse quadro. Pedido do dono.

- 0.31.33: Admin → Usuários: `POST /api/admin/users/{uid}/copy-config` (`hub.admin_copy_config`: cria um convite do usuário
  para o admin e aceita na hora com `config_answer(..., notify_sender=False)`) e `GET /api/admin/users/{uid}/trades`
  (fictícios). Modal `#uTrades` (`openUserTrades`/`renderUserTrades`). Pedido do dono. Teste em `tests/test_explore_share.py`.

## Comparar config copiada e atualização da origem (2026-10-27, versão 0.31.34)
- Pedido do dono. Explorar saiu do grupo (`#navExp`, só admin). `app/compare.py` (`compare`, `ai_text`, `summary`) +
  `hub.compare_list/compare_one/compare_save/compare_saved`; rotas `/api/pump/compare*` (admin); tela `#comparar`.
  Migração `20261027000002_comparar_config.sql`: `config_compare_reports` (análises salvas para IA) e colunas `tipo`/`base_id`
  em `config_offers`. `hub.config_watch` (`config_watch_loop`, 5 min): cópia mais recente de cada par; se quem recebeu
  ainda está idêntico e a origem mudou, cria convite `tipo=atualizacao` (não repete a mesma alteração recusada);
  `config_offers` devolve `mudou` e `efeito` (origem antes × depois da mudança e quem recebeu no mesmo período);
  banner `offerUpdate` no painel. Testes: `tests/test_comparar.py`.

- 0.31.35: `hub.config_sync` + `POST /api/pump/config/applied/{id}/sync` (valores ATUAIS da origem nas opções da cópia, como nova cópia aceita); botão "Aplicar idêntica" no selo `.cfgfrom`. Pedido do dono.

- 0.31.36: "Visualizar tela" (Admin → Usuários). Cabeçalho `X-View-As` (`BB.viewAs`, `sessionStorage` `pf_viewas`); a dependência
  `user()` em `app/api.py` troca a conta pela do usuário só para admin e só em GET; bloqueia `/api/secrets`, `/api/audit`,
  `/api/admin`; não grava `audit_log` (pedido do dono). Faixa `#viewBar`, `body.viewas`. Teste: `tests/test_visualizar.py`.

## Real espelha a fictícia — sugestão do Bruxo (2026-10-27, versão 0.31.37)
- Pedido do Bruxo (registrado na memória "sugestoes-do-bruxo"; commits com "Sugestões sugeridas pelo Bruxo").
  `pump_real_mirror` (ON): `PumpFun._mirror_real` depois que a posição fictícia abre (`_copy`, `manual_buy`); valor e
  limites só da real (`_real_buy`: `pump_real_max_sol`, `pump_real_max_open`, perda do dia, chase); a real guarda
  `sim_id` e vende 100% quando a fictícia fecha (`_sell`) ou se ela já fechou enquanto a compra estava na fila.
  Automáticas vão para a real sem `pump_auto_real` quando o espelho está ligado. Testes: `tests/test_espelho_real.py`
  (os antigos de "nunca real sem pump_auto_real" agora desligam o espelho). Relatório: `app/relatorios_ia/2026-10-27-0.31.37.md`.
- `hub.config_users` + `GET /api/pump/config/users`: quadro "Você tem N usuários usando a sua configuração" no topo do
  Explorar e de Configurações.

## Sugestões do Bruxo + aprendizagem do bot (2026-10-27, versão 0.31.38)
- Áudio do Bruxo (15×18 no Explorar). `auto_trades.SUSPECT_PCT` (1.900%): `summary` tira suspeitos dos totais/acerto/fator
  (`suspects`, `suspects_sol`), `api_item` marca `suspeito`. Quadro "A conta do bot" (`#exAutoEx`), funil
  (`PumpFun._funnel_note`/`explore_funnel`, campo `funnel` de `/api/pump/explore`), Real × fictícia (`mirror_pairs`,
  `GET /api/pump/real/mirror`, trades com `pos_id`/`sim_id`), CSS `autotbl`. Corrigido id duplicado `cmpK` → `cxK`
  na tela Comparar. Teste: `tests/test_bruxo_aprendizagem.py`. Causa do preço do SEALLIS não investigada (sem acesso ao banco).

- 0.31.39: a pedido do dono os ganhos ≥1.900% voltam aos totais (`auto_trades.summary` inclui todos; `suspects` só informa); marca "acima de 20×". A correção da curva cotada em outra moeda (SPCX/ZEC — causa provável do SEALLIS) está pronta em patch fora do repositório e NÃO foi aplicada: aguarda decisão do dono.

- 0.31.40: quadro `#exCopyCard` no Explorar (`loadExCopy`/`renderExCopy`; `compare(..., origem="explorar")` com `chance` e horários `abriu_x/abriu_y/fechou_x/fechou_y`). Pedido do dono. Áudios do Bruxo: não marcar ganho grande e não alterar o Explorar — marca removida da tela; lógica de entrada/saída do Explorar não mudou nesta sessão (só o registro do funil e o espelho da real).

- 0.31.41: funil do Explorar salvo em `ghost_stats.data.funil` (`funnel_dump`, 24 h, até 800 tokens; carregado no início); `hub.compare_one` acrescenta `por_que_nao` em `so_x`/`so_y` a partir do funil da outra conta. Pedido do dono (a conta dele não repetiu R1R2L1R2/OCAINE do Bruxo).

- 0.31.42: com `pump_real_mirror`, `auto_guard` conta só a fictícia e a real espelhada não repassa por ele (`manual_buy`, `_real_buy`). Relatório `app/relatorios_ia/2026-10-27-0.31.42.md`. Pedido do Bruxo (R1R2L1R2 não foi para a real).

- 0.31.43: no espelho (`sim_id`) `_real_buy` não aplica `chase_block` nem exige `auto_ready`; desistências/falhas da real no feed com `sim_id` (`miss`); `PumpFun.mirror_misses` + campo `misses` de `/api/pump/real/mirror`; quadro na Execução real. Relatório `app/relatorios_ia/2026-10-27-0.31.43.md`. Prioridade do dono: a real tem que replicar a fictícia.

## Operações automáticas da carteira real (2026-10-27, versão 0.31.44)
- Pedido do dono. Explorar ganhou o quadro `#exRealCard` (mesmo cálculo do simulado, feito no navegador com as linhas
  `real` de `/api/pump/auto-trades`): `renderRealAuto`, `autoBlocks` (ganhou × perdeu + conta do bot) e `autoTable`
  reaproveitados pelos dois quadros. `sanfona()` aceita o atributo `data-sanf` (cartão sem opções); os dois quadros
  começam fechados. O funil do filtro foi para um cartão próprio logo abaixo.

## Relatório do dia da carteira real (2026-10-27, versão 0.31.45)
- Pedido do dono: o Relatório do dia seguia fictício com o botão Real. `daily.build(..., real=True)` usa só os trades
  reais (curva = resultado acumulado; sem `equity_end`; "não copiou" só do feed REAL). `/api/pump/daily`, `/pdf` e `/ai`
  aceitam `real=1`; a real não é guardada no `daily_report`: cada dia (até 30) é calculado na hora. `loadDaily` manda
  `realMode()` e recarrega quando o botão muda. Teste em `tests/test_daily.py`.

- 0.31.46: `real_loop` despacha cada ordem em tarefa própria (`_real_run`, `REAL_PARALLEL`=6, `asyncio.Lock` por token);
  `_send_confirm` confere a cada 0,25 s; `PumpReal._sol_change` lê o SOL da transação (meta pré/pós) com volta para a
  diferença de saldo. Relatório `app/relatorios_ia/2026-10-27-0.31.46.md`. Pedido do dono ("sem delay entre fictícia e real").

- 0.31.47: prioridade da real (pedido do dono). `PumpFun._waits_real` (fictícia com compra real do espelho saindo não
  sai: guarda `exit_wait`), `_release_sim_exit` (no `finally` de `_real_buy`), `_align_to_real` (fictícia par recebe
  `open_t`/`opened_at` e preço efetivo da real; original em `sim_entry`; só sem venda parcial e com razão 0,2–5).
  Em `_sell` a venda real do par sai antes do fechamento da fictícia. Relatório `app/relatorios_ia/2026-10-27-0.31.47.md`.
