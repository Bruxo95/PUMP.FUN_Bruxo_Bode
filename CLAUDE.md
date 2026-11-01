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

- 0.31.48: `txguard.PUMPPORTAL_ROUTER` (FAdo9NCw…, intermediário da PumpPortal visto em 27/10; CPI para Buy/Sell da pump.fun):
  `check` aceita com token pedido + pump.fun nas contas e devolve `needs_simulation`; `PumpReal._sim_guard` simula
  (`simulateTransaction` com saldo da carteira e das outras contas de token) e recusa SOL acima do teto ou outro token
  mexido; sem simulação não envia. Jupiter de reserva para token pump usa `pump_real_slippage_pct`. `daily.build(real)`
  → `real_misses` (tabela `#dayMiss`). Relatório `app/relatorios_ia/2026-10-27-0.31.48.md`.

- 0.31.49: `txguard` não exige mais a pump.fun nas contas da rota da PumpPortal (na compra ela vem por lookup table —
  NEWMOON 15:45); `_sim_guard` exige o log de invoke da pump.fun/PumpSwap. `daily.build(real)` cria sugestões
  `falha_real_*` a partir de `real_misses` + `PumpFun.MISS_TIPS`; `hub.save_daily` guarda `data.real_report` (e no
  fechamento do dia); `daily_data(real)` usa os dias guardados. Pedido do dono: aprender com os erros e salvar tudo.

## Tudo num lugar e resultado por versão (2026-10-27, versão 0.31.50)
- Pedidos do dono. Botões `data-toggle` mostram "ON · Ligado"/"OFF · Desligado". `cfgItems()` lê do DOM todas as opções
  (`data-toggle`/`data-cfg`) das telas que a conta vê; `buildAllCfg` monta `#allCfgCard` em Configurações com cópias
  `data-clone` (mesmas chaves: os handlers globais salvam e o `render` atualiza); `renderSummary` monta `#sumCard` na Visão
  geral (cópia de configuração de `APPLIED`, real/espelho, chips ON/OFF). `cfgLabel`/`cfgUnit` ignoram `[data-clone]`.
- `compare(..., real=)` + `?real=1` em `/api/pump/compare/{id}`; `loadExCopy` segue `realMode()`.
- `app/versions_report.py` + `app/versoes.json` (gerado do Git; o script de versão acrescenta cada entrega no fim):
  `/api/pump/versions` e `/versions/ai` (admin), aba Relatórios → Por versão, `rep["versoes"]` no PDF/texto do dia.
  Métrica: média por trade fechado; veredito contra a última versão com 5+ trades. `tests/test_versoes.py`.

- 0.31.51: sino (`NTFL`/`NTFU`, `#ntfP`; som em `#ntfS`); `dhs()` dia+hora+segundos nos ganhos/perdas do dia;
  `balances`/`_sim_guard` com `asyncio.gather`, `skipPreflight` só para transação já simulada, `lat` (montar/confirmar/total)
  na posição/trade real e em `mirror_pairs`; `copyHtml`/`renderAllCfgCopy` (100% idêntica por tela em `#allCfgCard`);
  `_note_suspect_price` (20× a entrada → feed "preço suspeito", sem mudar decisão) e sugestão `preco_suspeito` no dia.
  Caso Jewlon: curva cotada em outra moeda (patch de preço continua fora, aguarda o dono).

- 0.31.52: aplicada com OK do dono a correção das curvas cotadas em outra moeda (`PumpFun.curve_quote`, bytes 83..115;
  em `_curve_prices` curva não-SOL ou `vs` < 29 SOL vai para DexScreener/Jupiter). Jewlon conferido on-chain (NTRNDM, 56,7×).
  `tests/test_curva_outra_moeda.py`. Relatório `app/relatorios_ia/2026-10-27-0.31.52.md` (antes × depois do Bruxo).

- 0.31.53: `liveCopies()` (só a cópia mais nova de cada opção conta; a antiga de 08:24 aparecia como "1 diferente"),
  botão `data-copydiff` → `openCopyDiff` (modal `#cfgDiff`: seu × dele) e `data-copyapply` (aplica só as diferentes via
  `setCfg`, ação do próprio usuário). `#navNov` (Changelog) saiu de `#navGrp` para o menu principal, ainda só admin.

- 0.31.54: `table()` ordena sozinha do mais novo para o mais antigo quando o cabeçalho tem coluna de data/hora (`TCOL`,
  `timeKey`, `byTimeDesc`; aceita "dd/mm hh:mm:ss", "dd/mm/aaaa" e "hh:mm:ss"; se a maioria das linhas não tiver horário, mantém
  a ordem). `mirror_misses.por_motivo` mostra o texto real do motivo. Pedido do dono.

- 0.31.55: `PumpReal._rpc_retry` (3 tentativas, a última no `SOL_HTTP` se a carteira usa outro RPC) nas consultas e na
  simulação de `_sim_guard`; motivo com o texto do erro; dica em `MISS_TIPS`. Histórico → `#hErr` (`renderErrs`, ações
  "REAL falhou"/"REAL não copiou"/"preço suspeito" do feed). Explorar: classe `.wrapcell` no motivo do Automático.

- 0.31.56: `OWN_TRADE` (/^\[PUMP (SIM|REAL)\]/) em `onEvent`: sino, som e toast só dos trades da própria conta (pedido do
  dono). `modules_report._auto("explorar")` acrescenta a foto do aprender com os erros (bloqueadas/aprendendo/ok) ao
  relatório do dia. Ajuda do Explorar: 6 operações (`autolearn.MIN_N`).

- 0.31.57: `/api/admin/novidades` acrescenta `inicio` (de `app/versoes.json`) e o Changelog mostra dia e hora com segundos. Pedido do dono.

- 0.31.58: `_sim_guard` simula em lotes de 21 contas + a carteira (`asyncio.gather`; RPC aceita no máx. 22 contas — AI,
  27/10 18:00) e confere cada lote em `_sim_check`. Sino: tag REAL/FICTÍCIA em cada notificação.

- 0.31.59: etiquetas REAL/FICTÍCIA em todo o painel (antes "Sim", "Simulado", "SIMULADO", "Real"); `data-mtag` também. Pedido do dono.

- 0.31.60: `daily.build` → `stops_slipped` (stop que fechou 10+ pontos abaixo do configurado) e sugestão `stop_escorregou`
  (guardada no `daily_report`, conta em `study.recurring`). Só registro e aprendizado; regras não mudaram. Pedido do dono (SHERKHAN).

## Copiar os trades de outro usuário (2026-10-27, versão 0.31.61)
- Pedido do dono (Pedro com config idêntica ao Bruxo fazia trades diferentes). `PumpFun.follow_user` (salvo como
  `_follow_user` em `user_settings.settings`, começa vazio) e `leader_hook` → `PumpHub._on_leader`: na abertura de posição
  fictícia da conta seguida (`manual_buy`, `_copy`) chama `manual_buy(..., follow={sol, rules, leader, pos})` em quem segue
  (mesmo valor e `FOLLOW_RULES`); no fechamento (`_sell`) fecha a posição com `follow_of.pos`. Real pelo espelho de quem segue.
  Sem cadeia (`follow_of` não repassa) nem círculo (`follow_set`). Rotas `/api/pump/follow-user` (admin). `#followCard`.
  Teste: `tests/test_copiar_trades.py`.

- 0.31.62: migração `20261027000003_pedro_copia_trades_bruxo.sql` (pedido do dono no chat): acrescenta `_follow_user` = Bruxo 9519
  em `user_settings` do Pedro Rodrigues (por e-mail; só essa chave). `hub.start` guarda o nome da conta seguida para os avisos.

## Aprendizado geral (2026-10-27, versão 0.31.63)
- Pedido do dono. `PumpFun.learn_trades()` (via `learn_pool` = `PumpHub._learn_pool`): trades automáticos fechados de todas as
  contas, `_mine` para os da própria; fora `real`, `follow_of` (cópia; `_sell` grava `follow_of` no trade) e `pnl_pct` ≥
  `SUSPECT_PCT`. `autolearn.study` devolve `n_sua`/`n_conhecimento` e `fechadas_suas`; tabela `alTbl` com coluna "De onde".
  Migração `20261027000004`: Pedro sem `_follow_user` (Explorar dele continua ligado). Teste `tests/test_aprendizado_geral.py`.

- 0.31.64: `PumpHub.ghosts_merged(pf, kind)` soma `stats` de `ghosts`/`ghosts_auto` de todas as contas (n_sua/n_conhecimento,
  `avg_sol`, melhor por trade); usado em `/api/pump/ghosts`, `ghosts_auto` do `/api/pump/explore` e no `auto_tune`
  (`pick_exit` compara por trade com as suas regras). Teste `tests/test_fantasma_geral.py`. Pedido do dono: tudo geral.

- 0.31.65: `Ghosts._drop_suspect` (no `load`) tira das somas os fechamentos ≥ `SUSPECT_PCT` que estão em `recent`; `_close` não soma
  fechamento com esse ganho. Evita o Ajuste automático escolher regra por ganho falso. Teste em `tests/test_fantasma_geral.py`.

- 0.31.66: `baseTag(total, sua)` nas colunas "De onde" (alTbl, gaTbl, ghTbl): "BASE GERAL n · sua conta m". Funil do filtro com
  `<header><h2>` próprio. Pedido do dono.

- 0.31.67: `explore_funnel` mostra o texto real do motivo (um exemplo por grupo) em vez do texto com "#". Pedido do dono.

- 0.31.68: `baseTag` mostra só "BASE GERAL n" (o número desta conta vai no `title`). Pedido do dono ("sua conta" confundia).

- 0.31.69: sugestão do Bruxo. `snapshot` devolve `hold_s`/`hold_src` por posição; `PumpFun.extend_hold(pid, add_min|None)`
  (também no par do espelho; `NO_LIMIT_S`) + `POST /api/pump/positions/hold` (audit "posição: tempo estendido"). Posições:
  coluna "Tempo de saída" com +30 min / +1 h / Sem limite. Teste `tests/test_tempo_saida.py`.

- 0.31.70: campo `data-hcfg` (horas na tela, minutos guardados) para `pump_ar_max_hold_min` no Explorar; render divide por 60 e
  o `change` grava ×60; `cfgLabel`/`cfgItems` reconhecem `data-hcfg` (no quadro de todas as opções aparece em min). Pedido do dono.
  Explorar segue a cada 5 min (`explore.EVERY_S`): plano grátis da Solana Tracker = 10 mil consultas/mês; 2 min daria ~21,6 mil.

## Base geral — o cérebro do robô (2026-10-27, versão 0.31.71)
- Pedido do dono. `app/basegeral.py` (`maturity` 40% faixas rumo a 30 operações + 30% regras rumo a 20 trades × 2 dias +
  30% dias rumo a 7; `upcoming`; `state_summary`; `diff`). `PumpHub.base_state`, `base_tick`/`base_loop` (30 min: foto em
  `base_snapshots` + mudanças em `base_log`; migração `20261027000005_base_geral.sql`, só backend). Rota `GET /api/pump/base-geral`
  (admin; inclui `auto_tune_log` com nome). Menu `#basegeral` (`#navBaseG`, abaixo do Explorar). Teste `tests/test_base_geral.py`.

- 0.31.72: entradas sombra (`PumpHub.shadow_note` via `pf.shadow_hook` no `_funnel_note` de token "chance alta" barrado;
  `shadow_tick`/`shadow_loop` 60 s mede px0 em até 2 min e o preço aos 15 min; `shadow_trades` entra no `_learn_pool` com
  `sombra`, resultado − 4%; tabela `base_shadows`, migração `20261027000006`; `load_shadows` no start). `autolearn` conta
  `n_sombra`. `learn_trades` não conta duas vezes o mesmo token em contas diferentes com até 10 min. Teste `tests/test_sombras.py`.

- 0.31.73: `whoLabel`/`shortW(w, x)`/`pfW(w, x)` em `web/app.js`: carteira "manual" vira a origem (Explorar/Base/Maiores traders/
  botão Comprar/copiou a conta X), sem link; chamadas `pfW(x.wallet)` → `pfW(x.wallet, x)`; "Resultado por trader" agrupa por origem. Pedido do dono.

- 0.31.74: `PumpHub.traders_offer` + `POST /api/pump/traders/share` (convite `config_offers` com `tipo="traders"` e
  `valores._traders`; `config_answer` soma em `pf.manual`); `_no_traders` tira esse tipo de comparar/selo/atualização/
  "usuários usando a sua configuração". Botão `#trShBtn` em Top traders; `offerList` mostra as carteiras. Legenda `.origleg`
  e `ORIG_DESC` (dica do mouse) em Histórico e Posições. Pedido do dono. Teste `tests/test_compartilhar_traders.py`.

- 0.31.75: `unlockAudio` no primeiro pointerdown/keydown/touchstart (autoplay do navegador); `classify` e `mascKind` reconhecem
  "] compra automática/manual"; sino usa `mascKind(msg)[2]` como nome da ação. Pedido do dono (sem som).

- 0.31.76: `app/apiusage.py` (`Usage`, gancho `request` do httpx em `main.py`; por API e, na Solana Tracker, por chave via hash;
  limites grátis conferidos: ST 10 mil/mês, DexScreener 300/min, RPC público 600/min); `hub.usage_loop` grava `api_usage`
  (migração `20261027000007`) a cada 5 min; `GET /api/admin/api-usage`; quadro em Administração. Explorar: `vol24_usd`
  (txns do pool ou DexScreener h24) e coluna "Volume 24 h". Rodízio de várias contas grátis NÃO feito (termos de uso).

- 0.31.77: `_fetch_prices` guarda `tokens[m]["pools"]` (cada par da DexScreener: dex, cotação, vol24, compras/vendas 24 h, liquidez);
  `explore_loop` pede os pares dos tokens de Quase graduando/Graduados (até 90, ~3 consultas/5 min); rota do Explorar devolve
  `pools`; `poolsCell` na coluna Volume 24 h com a média por negócio (vermelho < $5 com 20+ negócios). Pedido do dono (LILY).

- 0.31.78: `PumpFun._copy_note`/`copy_diag` (memória, 24 h, 50 mil) em cada saída de `_copy` (pausado, espera, filtros, limites,
  copiou); `GET /api/pump/copy-diag` (com os filtros da conta); quadro `#cdK/#cdM/#cdT` em Top traders. Pedido do dono (sem cópias
  dos top traders em 24 h; suspeita: traders de alta frequência com compras abaixo de `pump_min_trader_sol`). Teste `tests/test_copy_diag.py`.

- 0.31.79: `_auto_blocked` não grava no feed "token já teve entrada automática nas últimas 24 h" (normal; fica no funil) e os
  demais motivos no máximo 1 vez/6 h por token (antes 1/min por motivo, lotava o feed de 500). Feed com filtro "Só traders"
  (padrão, `FEEDF`) / "Tudo". Pedido do dono.

- 0.31.80: campo na tela para `pump_hold_min_profit_pct` (já existia no motor, sem campo) ao lado de "Trader saiu e estou no
  prejuízo", com atalhos 0/5/10/20%. Lógica igual: segura se o líquido < X% quando o trader vende; vende quando passa de X%;
  stop de perda segue valendo. Pedido do dono.

- 0.31.81 (item A, pedido do dono): `explore.extra_info` grava em `auto_info` (Explorar) e no `info` das sombras: `mayhem`/`quote`
  (lidos da curva em `_curve_prices`, byte 81 e 83..115), `top10`/`dev_pct`/`snipers_pct`/`insiders_pct`/`bundlers_pct` (risco da
  Solana Tracker em `explore.item`), `avg_trade_usd` e `age_min`. `autolearn.study_extra` (fora de `FEATURES`: nunca bloqueia) →
  `base_state["sinais"]` → tabela `#bgS` na Base geral. Lógica de entrada/saída do Explorar não mudou. `tests/test_sinais_novos.py`.

- 0.31.82 (opção A do dono): `pump_swap_fee_official` (OFF) + `PumpFun.SWAP_FEE_TABLE`/`swap_fee_official` (pump.fun/docs/fees de
  17/10/2026): em `_fee_rates`, token graduado cotado em SOL usa a taxa da tabela por valor de mercado (preço × 1e9). Botão em
  Configurações → Taxas. Relatório `app/relatorios_ia/2026-10-28-0.31.82.md`. `tests/test_taxa_oficial.py`.

- 0.31.83 (sugestões do Bruxo): erro 6063 da pump.fun = UnsupportedQuoteMint (curva em outra moeda, ex.: Grokbot/SPCX).
  `PumpReal.other_quote` → `buy` vai direto para a Jupiter; `PUMP_ERRORS` e `MISS_TIPS` explicam. `#sysS` mostra Solana RPC
  (carteiras, trades, último) e PumpPortal (tokens novos, último). Relatório `app/relatorios_ia/2026-10-28-0.31.83.md`. `tests/test_moeda_6063.py`.

- 0.31.84 ("sombra primeiro", pedido do dono): `autolearn.wilson` (90%, NIST) + por faixa `acerto_min/max`, `bloq_wilson`,
  `wilson` (igual/liberaria/bloquearia) e resumo `wilson`; NÃO entra em `bloqueios`. Base geral: `#bgWil` e 2 colunas em `#bgL`.
  Pesquisa conferida: `PUMP-FUN-LEARNING/pesquisa-pumpfun-conferencias-tecnicas-2026-10-28.md`. `tests/test_wilson_sombra.py`.

## Evoluções do cérebro (2026-10-28, versão 0.31.85)
- Pedido do dono (opção A + etapas 1, 2 e 3). `app/evolucoes.py` (`estado`, `relatorio`, `comparar`, `reverter_ajustes`);
  `hub.base_tick` grava `base_evolutions` (migração `20261028000001`, só backend) quando muda bloqueio/melhor regra (ou a 1ª);
  `hub.evo_list/evo_report/evo_rollback/evo_auto`; rotas `/api/pump/base/evolucoes[/comparar|/{n}|/{n}/voltar]` e
  `/api/pump/base/automatico` (admin). Congelar: `pf.brain_freeze` (salvo como `_brain_freeze`) → `PumpFun.learned_for_entry`
  (só a decisão de entrada do Explorar; o estudo mostra o atual) e `auto_tune` parado. Card `#evoTbl` na Base geral.
  Relatório `app/relatorios_ia/2026-10-28-0.31.85.md`. `tests/test_evolucoes.py`.

## Veredito medido e Raio-X do token (2026-10-28, versão 0.31.86)
- Pedido do dono (A, B, C). A: `_funnel_note` manda TODO barrado para `shadow_note` (guarda `veredito`); `shadow_tick` mede o `pico`
  em 15 min; `shadow_trades` só leva "chance alta" (ou sem veredito, antigas) ao aprender com os erros; `basegeral.verdict_study`
  → `base_state["veredito"]` → `#bgV`. `load_shadows` lê até 40 mil. B: `app/raiox.py` (Solana Tracker `/trades/{mint}` ASC 500,
  1 crédito; `analyze`: minutos, primeiros 20 compradores, despejo, sinais) + `hub.xray/xray_auto_once/xray_loop` (até 10/dia:
  operações do Explorar 24 h e sombras com pico 50%+) + tabela `token_xray` (migração `20261028000002`) + `GET /api/pump/raiox/{mint}`
  (admin) + botão na ficha do token. C: `raiox.study` × `hub.xray_outcomes` → `#bgX`. Nada bloqueia. `tests/test_raiox.py`.
- Conferido em 28/10: Jupiter cota SOL → Grokbot (curva SPCX) via Whirlpool SOL→SPCX + Pump.fun AMM (consulta pública).

- 0.31.87 (Bruxo, áudios de 28/10): `PumpFun.position_rule` (`off_stop`/`off_trail`/`off_tp1`, também no par do espelho) +
  `POST /api/pump/positions/rule` (audit); `_check_stops` respeita. Posições: botões `prule` e `soldCell`; Histórico: `#tPart`
  (vendas parciais de posições abertas). Relatório `app/relatorios_ia/2026-10-28-0.31.87.md`. `tests/test_regras_posicao.py`.

- 0.31.88 (pedido do dono: log de análise do Explorar): `PumpFun.explore_cycle_note` (1 registro por lista de 5 min; atualizado
  a cada volta, grava só quando muda) chamado em `SharedMonitor.explore_auto_once`; `hub.explore_cycle_save/explore_log`; tabela
  `explore_cycles` (migração `20261028000003`); `GET /api/pump/explore/log?horas=` (admin); `basegeral.filters_study` (sombras por
  motivo; também em `base_state["filtros"]`). Card `#exLogCard` no Explorar. Achado: só token com preço de até 30 s é analisado
  (`sem_preco` no log). `tests/test_explore_log.py`.

- 0.31.89 (pedido do dono: log para os outros robôs): `PumpFun.rlog/rlog_summary/rlog_pending` (blocos de 5 min, última decisão
  por item) em `_copy_note` (copia), `auto_check` (base) e `elite_auto` → `_elite_auto` (elite); `hub.rlog_flush/rlog_loop` (60 s) →
  tabela `robot_log` (migração `20261028000004`); `GET /api/pump/robot-log?modulo=&horas=` (admin); quadro `[data-rlog]` em Top
  traders, Base e Maiores traders (`loadRobotLog`). Lógica de decisão igual. `tests/test_robot_log.py`.

- 0.31.90: menu `#logs` (`#navLogs`, admin) com abas `data-logtab`/`data-logpane` (explorar, copia, base, elite; `showLogTab`);
  os quadros de log saíram das telas e ficaram atalhos `data-logtab`. Pedido do dono ("um menu para guardar e ver depois").

- 0.31.91 (pedido do dono: "depois de 14 dias criar um aprendizado e não deletar"): nenhum log é apagado; `app/robotlog.py`
  (`rollup`, `trend`) + `hub.rlog_daily` (de hora em hora no `rlog_loop`, dias fechados UTC, até 60 para trás) → tabela `robot_daily`
  (migração `20261028000005`); `GET /api/pump/robot-log/dias?modulo=` (admin); quadro "Aprendizado dos logs" em cada aba
  (`loadRobotDays`); períodos até 90 dias. `tests/test_robot_daily.py`.

- 0.31.92: botão `data-buy` (o do Comprar da Base, `pump_manual_*`) em cada linha de `#exFunUp`. Pedido do dono.

- 0.31.93: `#exTbl` com classe `extbl` (fonte menor), Comprar dentro da coluna Token, 5 min/1 h juntos, `poolsCell` curto (detalhe
  no `title`). Pedido do dono (sem rolagem lateral).

## Calls quentes pela blockchain (2026-10-28, versão 0.31.94)
- Pedido do dono (Hot callouts da pump.fun). A API do site (callouts e conversas) responde 403 com o desafio da Cloudflare
  (conferido em 28/10): não é lida. `app/calls.py` (`Calls`: `on_trade`, `tick`, `callers`, `verdict`, `summary`): toda compra
  de carteira acompanhada (handle_tx → `hub.calls_on_trade`) vira call; seguidor entra 1 min depois; marcas 5/15/60 min; pico;
  despejo = vendeu ≥50% em 10 min; nota do caller = Wilson 90% do acerto (15 min − 4%) − 0,3 × % de despejo (5+ calls);
  veredito 0–100 (nota, outros callers em 10 min, risco ≥7, MC < 30 SOL, lista negra). `hub.calls_tick/calls_loop` (30 s),
  tabela `calls` (migração `20261028000006`), `load_calls` (7 dias), `GET /api/pump/calls` (admin), menu `#calls` e aba
  `calls` em Logs dos robôs (`rlog("calls")`). Não compra sozinho. `tests/test_calls.py`.

- 0.31.95: `SharedMonitor` (aviso de log da carteira) trata as carteiras de `hub.elite.wallets()` como observadas (`studied`):
  a transação é lida (sinais dos Maiores traders e Calls quentes). Antes só eram lidas se alguém copiava ou estudava. Cópia igual.

- 0.31.96: Radar virou aba do menu "Calls e Radar" (`#navCalls`; abas em link no topo de `#calls` e `#radar`; link solto do Radar
  saiu do grupo). `Calls.for_wallets/waves` + `hub.radar_calls` (compras das Carteiras em estudo e ondas de 24 h das calls guardadas)
  no `GET /api/pump/radar`; `#rdBuys`/`#rdWaves` (`renderRadarCalls`). O Radar ao vivo (memória) continua igual. `tests/test_radar_calls.py`.

- 0.31.97: `GET /api/pump/radar` devolve `lista` (study_wallets da conta + compras 24 h + última compra das calls + online);
  quadro `#rdList` no Radar. Pedido do dono ("ver a lista, não só números").

- 0.31.98: `lista` do `GET /api/pump/radar` conta compras em 24 h/48 h/3 d/7 d e a última pela tabela `wallet_trades` (histórico das
  Carteiras em estudo, desde a 0.14.0), não só pelas calls. Pedido do dono.

## Itens 1–7 das melhorias (2026-10-28, versão 0.31.99)
- Pedido do dono ("faz 1 a 7"; 5 é botão da conta dele e 6 depende do print da Solana Tracker). (1) `Ghosts.dump/load` guardam
  `open` (24 h); `hub.shadow_save_open` grava sombras abertas a cada volta do `shadow_loop`; sombra que passou da foto de 15 min
  (+180 s) é descartada. (2) `pump_ex_possivel_on/_pct` em `explore_entry_reason` e no valor do `manual_buy`. (3)
  `pump_ar_learn_wilson` em `learned_for_entry` (usa `bloq_wilson`). (4) `pump_calls_auto_on/_min/_max_h` → `hub._calls_auto`
  → `manual_buy(origem="calls")`, que nunca vai para a real; `AUTO_ORIGINS` + migração `20261028000007`. (7) `hub.rlog_tips`
  (`resumo.dicas`) no log. Tudo OFF por padrão. Relatório `app/relatorios_ia/2026-10-28-0.31.99.md`. `tests/test_itens_2_3_4.py`.

- 0.32.0: `_fee_rates(mint, real=False)` — a tabela oficial (`pump_swap_fee_official`) só vale com real=False; `_exit_value` passa
  `p["real"]` e a compra/venda real passam True. Migração `20261028000008`: liga a opção só na conta do dono (onlineguyat@gmail.com),
  pedido dele no chat. Plano para outra sessão: `docs/PLANO-MOEDAS-QUE-ACORDAM.md` (moedas dormentes que voltam a subir).

- 0.32.1: revisão dos ganhos falsos (pedido do dono). `app/ganhos_falsos.py` (`collect`, `pair_real`, `judge`, `impact`, `report`, `ai_text`)
  + `hub.false_gains` (trades de todas as contas com `pnl_pct` ou `best_pct` ≥ `SUSPECT_PCT`; moeda da curva lida on-chain pelo
  `curve_quote`; preço em dólar na entrada/saída pela Solana Tracker `GET /price/history/timestamp`, até 30 tokens por revisão, cache em
  memória). Rotas `/api/pump/false-gains[?check=0]` e `/false-gains/ai` (admin). Relatórios → aba Ganhos falsos. Só leitura e marca:
  nenhum total, trade ou configuração muda. Pesquisa do ChatGPT de 28/10 (graduação, sinais, priority fee, mercado 30 dias, iscas)
  conferida em `PUMP-FUN-LEARNING/conferencia-claude-graduacao-riscos-mercado-2026-10-28.md`; nada aplicado no robô.

- 0.32.2: acesso SÓ LEITURA ao banco para a IA (pedido do dono, caminho 1). Migração `20261028000009_leitor_ia_somente_leitura.sql`:
  role `leitor_ia` (NOLOGIN até o dono pôr a senha no SQL Editor; `default_transaction_read_only`, 30 s por consulta; SELECT +
  política `leitor_ia: ler` nas tabelas de dados; fora `user_secrets`, `app_secrets`, `audit_log`; `profiles` sem e-mail).
  `scripts/ler_banco.py` (só biblioteca padrão: TLS + SCRAM-SHA-256; lê `~/.secrets/pump.env` → `PUMP_DB_URL` do Session pooler
  com usuário `leitor_ia.vnvfluimpqvxbvdbmwqa`; recusa o que não for consulta). Passo a passo: `docs/LEITOR-BANCO.md`.
  Teste `tests/test_ler_banco.py` (vetor do RFC 7677). Conexão real ainda não testada (falta a senha do dono).

- 0.32.3 (sugestões do Bruxo, áudios de 28/10): real separada da fictícia. Em `_copy`, com o espelho, se só a FICTÍCIA tem o token
  (`alone`), a compra do trader vai para a real pelo caminho direto (sem `sim_id`); em `manual_buy`, `sim_has` deixa a automática
  ir para a real quando o único motivo da fictícia é já ter o token. A fictícia não mudou. Status `#sysS`: `uptime_s` e `apis`
  (Jupiter, Solana Tracker, banco) no `/api/pump`; funil `queued`/`not_trade`/`reconnects` em `rpc_status` (monitor).
  Os contadores zeram a cada reinício. Relatório `app/relatorios_ia/2026-10-28-0.32.3.md`. Teste `tests/test_real_separada.py`.

- 0.32.4: menu `#igual` "Copiar igual" (pedido do dono). `EQ_SEED` (20 carteiras do leaderboard da pump.fun de 28/10; a API do
  site fica atrás da Cloudflare e NÃO é lida), `pf.copy_equal` (salvo como `_copy_equal` só se mudou), `pump_eq_*` (OFF),
  `PumpFun._copy_eq` (sem filtros/espera/pausa; venda proporcional; posição `eq` sem stop/trail/alvo, só `max_hold_s` e
  `pump_eq_stop_pct`; real só com `pump_eq_real`, pelo espelho), `hub.eq_set/eq_status`, rotas `/api/pump/copy-equal`.
  Monitor: fila `_tx_hi` só das carteiras copiadas (4 leitores); status `queued_hi`/`stale_hi`. O status no menu virou uma
  linha (`#sysBox`) e o completo abre no modal `#sysM`. Relatório `app/relatorios_ia/2026-10-28-0.32.4.md`. `tests/test_copiar_igual.py`.

- 0.32.5: migração `20261028000010_copiar_igual_dono.sql` (pedido do dono no chat): `pump_eq_on`=true e `pump_eq_real`=false só na conta
  dele (onlineguyat@gmail.com). Demais contas seguem com o Copiar igual desligado.

- 0.32.6: funil do Explorar (`#exFunM` e `#exFunUp`) empilhado em `.funstack` (antes `grid2` lado a lado, texto espremido). Pedido do dono.

- 0.32.7: `PumpFun._get_tx(sig, why)` guarda o motivo de cada tentativa (HTTP 429, result vazio, erro do RPC, exceção);
  `SharedMonitor.rpc_log` (300 por tipo: falha/atrasado/nao_trade/trade, só memória) + `rpc_why` + `rpc_report`; rota
  `GET /api/pump/monitor/leituras?tipo=` (admin); no modal `#sysM` as linhas do funil abrem `openRpcLog` (`SYS_SUB`). Pedido do dono.
  Visto em 28/10 depois da 0.32.6: 16.287 lidas, 2 trades, 580 falhas, 14.161 atrasadas — o RPC público quase não responde.

- 0.32.8: `SharedMonitor.LOW_PER_MIN`=6 (`_low_lim`; contador `limited`) para carteiras sem seguidor; robô sem seguidor não é lido
  (`skipped_bot`); `_tx_q` maxsize 600 e descarte em 60 s para não copiadas. `PumpFun._get_tx(..., low=)`: pausa conjunta no 429
  (`market.rpc_cool_until`/`rpc_429_streak`), 2 tentativas para baixa prioridade; erro `maxSupportedTransactionVersion` → tenta com 1.
  Relatório `app/relatorios_ia/2026-10-28-0.32.8.md`. Solução completa: RPC próprio (Portainer: `SOLANA_RPC_PUBLIC`, `PUMP_RPC_WS`), pelo dono.

- 0.32.9: `hub.wallet_facts(w)` (idade/`txs` de `market.wallet_facts` via `wallet_age`, saldo de `wallet_usd`, criados de `lab.creators`);
  `SharedMonitor.wallet_facts_once` (2 por minuto no `boost_loop`; estudo + `hub._facts_want`). `facts` em `/api/pump/study` (lista e log);
  `autostudy.facts_features` entra no `info` das decisões aprovou/descartou (aprende por idade/saldo/transações/criador).
  `pfW` abre o Solscan; `pflink` "pf" = perfil da pump.fun (só existe para quem usou o site). Pedido do dono.

- 0.32.10: `study.digest` (acertos/erros por token com `pump`, `sig` da última transação, `pump_pct`, `ultima_op`) no `profile` e no
  `summary`; `/api/pump/study` → `auto.log` via `_log_rows` (resumo de cada carteira; até 15 perfis extras fora do estudo); `#saLog` com
  `digestCells`/`tkLink` e botão Copiar nas aprovadas (aprovar só mantém no estudo). Pedido do dono.

- 0.32.11: `pump_st_auto_copy` (OFF; ligado só na conta do dono pela migração `20261028000011`). `pf.study_copy` (salvo `_study_copy`),
  `hub.study_copy_sync` no fim de `study_auto` (última decisão "aprovou" + ainda no estudo); `refresh_followed` inclui `study_copy_wallets()`
  (filtros normais). `PumpFun.sim_only(who)`: sem real direto e sem `_mirror_real`. Relatório `app/relatorios_ia/2026-10-28-0.32.11.md`.

- 0.32.12: `study.score` (70% Wilson 90% do acerto + 30% ganho ÷ (ganho+perda)) em `digest` (`score`, `score_base`, `ganho`, `perda`).
  `#saLog` em uma linha (`scoreTag`, `SA_LOG`) e modal `#saM` (`openSaDet`, botão `data-sadet`). Pedido do dono.

- 0.32.13: `study_copy_sync` põe a aprovada em `pf.manual` (`add_manual`) e tira na descartada (só as que a IA pôs, marcadas em
  `study_copy`); `sim_only` vale mesmo na lista manual; `followed[].ia_sim` → etiqueta "Manual · IA · só fictícia" em Top traders. Pedido do dono.

- 0.32.14: `#saLog` ordenado pela nota; `copyState`/`copyTag` ("copiando · só FICTÍCIA" / "REAL e FICTÍCIA", `data-gomine` desce até
  `#stMineCard`); `.decbox` com o motivo em Ver tudo. Pedido do dono.

- 0.32.15: cartões `#saK` com `data-saact` → `openSaList` (modal `#saM`, carteiras do grupo por nota). Pedido do dono.

- 0.32.16: `auto.log[].features` (valores de `info.features`); `#saRates` com `data-sarate` → `openSaRate` (modal `#saM`). Pedido do dono.

- 0.32.17: `sim_only` também vale para `pf.sim_only_list` (`_sim_only`; botão Copiar do estudo → `POST /api/pump/study/copy`) e para toda
  aprovada (mesmo já manual); `ia_added` (`_ia_added`) = só essas a IA tira da lista manual. `study_my_results` mostra a linha real de quem é
  copiado, com `real_state`; tabelas `#stMine` (fictícia) e `#stMineR` (real). Pedido do dono (por enquanto, só fictícia).

- 0.32.18: `pump_pp_copy` (OFF). `SharedMonitor.pp_wanted` (chave PumpPortal do sistema + admin com a opção) → `_pp_sync` (subscribe/
  unsubscribeAccountTrade de `union_followed`, a cada 10 s na conexão da PumpPortal) → `_pp_trade` → `handle_ev` (parte de `handle_tx`
  depois de decodificar). Dedupe `_seen_sig(carteira:assinatura)`; `on_notification` pula transação pump de carteira assinada (`pp_skip`).
  Status: `acct_subs`/`acct_trades`/`acct_dup`. Custo na carteira da chave do sistema. Relatório `app/relatorios_ia/2026-10-28-0.32.18.md`.

- 0.32.19: menu `#tradercfg` "Configuração do Trader" (pedido do dono; escopo = só cópias). Os campos de compra/slippage/priority/stop/
  trail/tempo/parada/tp1/alvo/dev/graduação saíram de Configurações, Opções novas e Execução real (lá ficou um link) — mesmas chaves.
  Novas OFF: `pump_tp2_*`, `pump_timestop_*`, `pump_entry_curve_*` (em `_check_stops`/`curve_block`, só sem `own_rules`), `pump_real_jito_tip_sol`
  (só guardado; Jito não implementado). `#tcReset` grava os padrões pump.fun do dono só na conta de quem clica. Explorar/Base/botão Comprar iguais.

- 0.32.20: `sim_only` = também toda carteira em `pf.study` (salvo `pump_st_real`, OFF). Pedido do dono.

- 0.32.21: `manual_buy(..., target=sim|real|both, amt_sol=)` + `target` na rota; modal `#buyM` no clique de `data-buy`. `PumpFun.barred_auto`
  (`pump_bar_*`, OFF; ligado só no dono pela migração `20261028000012`), chamado no `lab_loop` depois do `explore_auto_once`: funil do Explorar
  (`_ex_funnel` guarda `vol`), `BAR_HARD` = motivos de segurança que nunca entram, origem "barrado", sempre só fictícia. Explorar igual.

- 0.32.22: `barred_watch` (até 40 barrados não-segurança da última 1,5 h entram no `held()` do monitor = preço ao vivo), `barred_track`
  (no `lab_loop`: `hi`/`lo` e entradas virtuais por gatilho `BAR_TRIGGERS` 10/20/30/50% em `g["v"]`, saída pelas regras do botão Comprar
  ou 30 min, −4% de taxas) e `barred_sim` → `cedo` no funil; tabela `#exFunCedo`. Só mede. Pedido do dono.

- 0.32.23: `data-nosanf` = cartão que a `sanfona()` nunca recolhe (funil do Explorar). Cuidado: cartão que ganha 3+ campos vira sanfona fechada.

- 0.32.24: `evolucoes.comparar` com `pct`, `melhor` (SENTIDO de cada linha), `explica` e linhas EXTRA (dias, sombras_ganhariam, bloqueios);
  `evolucoes.veredito` (MIN_BASE 5 operações, senão barrados, senão "poucos dados") na rota do comparar; tela com `.hovhelp`. Pedido do dono.

- 0.32.25: `PUMP_ERRORS["0x1771"]` explica os dois sentidos (Jupiter = slippage; pump.fun = AlreadyInitialized, IDL 13/10/2026). Lote 6 do
  ChatGPT conferido em `PUMP-FUN-LEARNING/conferencia-claude-lote6-2026-10-28.md`.

- 0.32.26: `markBought()` (a cada 1,5 s) põe `.bought` ao lado de todo `[data-buy]` com a posição aberta (fictícia/real); `data-gopos`
  troca o modo, abre `#posicoes` e pisca a linha (`tr.flash`). Pedido do dono.

- 0.32.27: `PUMP_ERRORS` 6063 explica curva (UnsupportedQuoteMint) × PumpSwap (InsufficientRealQuoteReserves). Lote 3 conferido em
  `PUMP-FUN-LEARNING/conferencia-claude-lote3-2026-10-28.md` (bytes 83–114 do `quote_mint` conferem com o IDL).

- 0.32.28: `_fetch_prices` ignora o par "pumpfun" da DexScreener quando `pool` é pumpswap (preço parado no final da curva). `snapshot`
  manda `pnl_now_sol/_pct`; `#tPos` curta + modal `#posM` (`openPosDet`, `data-posdet`). Relatório `app/relatorios_ia/2026-10-28-0.32.28.md`.

- 0.32.29: migração `20261028000013` (só o dono): `pump_bar_min_gain` 20 e `pump_bar_min_vol_usd` 0. Origem `barrado_btn` (Comprar da lista de
  barrados; `data-orig`, aceito na rota) e etiqueta `.tag.barr` no `pfW`. Relatório `app/relatorios_ia/2026-10-28-0.32.29.md`.

- 0.32.30: `barred_track`/`barred_auto`/`barred_sim` ignoram barrado com alta ≥ `SUSPECT_PCT` (marca `g["suspeito"]`). Caso HOUSECOIN.

- 0.32.31: `barred_auto` grava `g["auto_st"]` (entrou / esperando / não entrou) e só marca feito quando comprou; `pump_bar_max_open` (20)
  = vagas próprias dos barrados (fora do `pump_max_open` das cópias e do botão). Migração `20261028000014` (só o dono): 20/h e 30 abertas.
  Lista até 30 a partir do gatilho; coluna "Automático"; `markBought` mostra "✓ AUTO na FICTÍCIA". Pedido do dono.

- 0.32.32: `pump_ex_real_on` (ON) e `pump_ar_real_sol` (0 = `pump_real_max_sol`; nunca acima dele) em `manual_buy`/`_real_buy` para origem
  explorar; `#exRealDiag` no quadro Proteções das automáticas. Pedido do dono. Regras de entrada/saída do Explorar iguais.

- 0.32.33: **Ajuste de configuração pedido no chat = linha em `settings_overrides`** (migração `20261029000001`), aplicada por
  `hub._apply_overrides` no fim do `_load` (uma vez; audit_log). Não gravar direto em `user_settings` por migração: o servidor
  antigo salva a memória por cima antes de reiniciar (perdeu o ajuste dos barrados das migrações 13/14). Aprendizado das posições:
  `app/poslearn.py`, `market.px_hist` (monitor `_px_hist`), `pos_snapshots`/`_post_open`/`post_tick`/`post_watch_mints` no motor,
  `hub.flush_pos_learn` → `position_learn`, `pos_learn_state` → `posicoes` na rota da Base geral. `recent_closed` → `#tClosedNow`.
  Janela dos barrados 3 h. Só fictícia (a real fecha por outro caminho).
  `pump_bar_real` (OFF): barrados também na real pelo espelho (`manual_buy` com target both).

- 0.32.34: liga/desliga = classe `.tgl.sw` (chave estilo iPhone; `data-toggle`, regras da posição e "Som e aviso"; texto "Ligado"/"Desligado",
  `role=switch`). Notificação clicável (`data-ntfi` → `openNtf`: posição aberta ou `openTradeDet`). Quadro próprio dos barrados no Explorar.
  `_apply_overrides` com log e nova tentativa a cada 5 min no `ghosts_loop` (o ajuste dos barrados não pegou ao subir a 0.32.33). Pedido do dono.

- 0.32.35: `pump_ar_stop_pct` aceita 0 (= sem stop de perda); `_check_stops` usa `stop_pct` da posição mesmo quando é 0 (`no_stop`). Pedido do dono.

- 0.32.36 (sugestão do Bruxo, 28/10 22:11): `pump_ex_max_age_min` (0 = sem limite) em `explore_entry_reason` (sem idade não entra) e
  `pump_ex_min_age_min` (−1 = usa `pump_ar_min_age_min`) em `auto_safety` só para origem explorar; `age_min` em `autolearn.FEATURES`
  (a linha do Explorar ganha `age_min` antes do `blocked_reason`). Override só do dono e do Bruxo (migração `20261029000002`):
  máx. 10, mín. 0. Campo novo nos filtros do Explorar. Relatório `app/relatorios_ia/2026-10-29-0.32.36.md`. `tests/test_explorar_idade.py`.

- 0.32.37: `scripts/changelog_area.py` (`classify` arquivos → `area`/`arquivos`; `--backfill` preencheu 185 versões pelo Git;
  `--current` na versão nova). Changelog: `.novarea` abaixo do tipo e `.novfiles` (código mexido). Pedido do dono.

- 0.32.38: Copiar do estudo → modal `#stcM` (`target` sim|both na rota `/api/pump/study/copy`; `pf.real_ok_list`/`_real_ok` tira o `sim_only`).
  `hub.study_copy_judge` no fim do `study_auto`: resultado real das cópias (7 dias, 8+ trades) → `parou_de_copiar` (só as da IA) /
  `sugere_parar` / `copiou_lucro` no `study_auto_log` (migração `20261029000003` amplia o check); `autostudy.rates` conta como aprovação/descarte.

## Indicador "Carregando" (2026-10-29, versão 0.32.39)
- Pedido do dono: usar o LatticeLoader (React Bits) quando o site estiver carregando. O painel é JS puro, então foi
  reescrito sem React em `web/common.js`: `BB.loader(rótulo, {grid, pattern, font, cell, glow, key})` devolve o HTML;
  `BB.loaderEnd(el, "done"|"error")` congela o cronômetro e mostra ✓ "Pronto em" / ✗ "Falhou após";
  `<div data-ll="Carregando…">` no HTML vira indicador sozinho. Relógio guardado por rótulo (redesenhar a cada 2 s não
  zera o cronômetro nem pula a onda). CSS no fim de `web/app.css` (classes `lattice-loader*`, `.netload`).
- Topo da tela (`#netLoad`): `BB.api` mostra "Carregando"/"Salvando" quando um pedido passa de 0,4 s; a atualização
  automática `/api/pump?ev=` e chamadas com `{quiet:true}` não contam. Em `app.js`, `busy(id, rótulo)` troca o texto
  de um quadro pelo indicador só se o rótulo mudou.

## Posições em cards (2026-10-29, versão 0.32.40)
- Pedido do dono (celular ruim de ver; estilo de referência "prediction market" escuro). `#posCards` no lugar da tabela
  `#tPos`; `posCard(p, c)` e `posSpark(p)` em `web/app.js` (regras efetivas: as da posição, senão as da conta; faixa
  stop ↔ alvo com agora/pico/saída do stop móvel); `POS_OPEN` guarda os "Mais detalhes" abertos entre atualizações.
  CSS `.poscards`/`.pcard`/`.pc-*` no fim de `web/app.css` (grid `minmax(262px,1fr)`; 1 coluna até 860 px).
- Venda parcial manual: `PumpFun.close_position(pid, frac)` (5%–100%; motivo "venda parcial por você (N%)") e `frac`
  em `POST /api/pump/close` (audit "vender manual" com a %). Real usa `_real_sell(p, frac)`. Fictícia com par real: o par
  só vende junto no 100% (regra existente do `_sell`). Teste `tests/test_api.py::test_manual_partial_sell_*`.
- 0.32.41 (sugestões do Bruxo, áudios de 29/10 + prompt; dono: "não muda nada no Explorar"): `app/bruxo.py` (`Bruxo`: sinais de top
  trader em token < 30 min, acompanhados 30 min; `study`) + `hub.bruxo_on_trade` (monitor `handle_ev` → `_bruxo` em tarefa própria;
  tops = `pf.followed` ∪ `elite.wallets()`; `bruxo_facts`: idade, ritmo vs `bruxo_flow_base` do TokenLab, `top10_pct` via `holders_check`,
  fatia do criador) → `PumpFun.bruxo_entry/bruxo_reason/bruxo_rules/bruxo_sell` (`pump_bx_*`, OFF; REAL só com `pump_bx_real`).
  `manual_buy(pos_rules=)`; `OWN_SLOTS`/`_slot` = vagas próprias (barrado, bruxo). Tabela `bruxo_signals`; menu `#bruxo` (`loadBruxo`).
  `app/tabreport.py` + `hub.tab_report_tick/loop` (30 min, admin, fictícia e real) → `tab_reports`; `GET /api/pump/tab-reports`; card na
  Base geral (`loadTabReports`). `PumpFun.aba_of` → campo `aba` em posições/trades/recent_closed do snapshot; `abaTag` no `pfW`.
  `_fetch_prices`: par "pumpfun" ignorado quando o token tem outro par (preço parado). Migração `20261029000004` (+ override só do
  dono: `pump_bx_on`). Relatório `app/relatorios_ia/2026-10-29-0.32.41.md`. `tests/test_aba_bruxo.py`.


## Visão geral organizada (2026-10-29, versão 0.32.42)
- Pedido do dono: status primeiro, explicação por último, gráficos menores (2 por linha no PC). Ordem em `web/app.html`:
  `.kpirow` → `.grid2e.vgtop` (Evolução da carteira | Operações recentes) → `.grid2e.vgstat` (Status das configurações |
  `#sumCard`) → `#dayCard` → `#learnCard`. Nos relatórios: KPIs → `grid2e` (gráfico | tabelas) → tabelas → `details.vgexp`
  com as explicações (`#daySug`/`#lrnSug` abertos, `#dayMenus` fechado). CSS `.grid2e`/`.vg*` no fim de `web/app.css`
  (1 coluna até 1100 px). Os ids continuam os mesmos, então o JS de cada quadro não mudou.

## Top traders só ativos com vagas próprias (2026-10-29, versão 0.32.43)
- Pedido do dono. `refresh_followed`: com `pump_only_online`, `new = man + top_active` (`top_active` = os `pump_top_n` melhores aptos
  e online); sem a opção, cálculo original. `_fill_slot` usa `len(top_active)`. Snapshot `leaderboard[].top_active`.
  Tela: `#tLb` só ativos (`online` e não robô), `#lbAct` (contadores), `#tFol` só ativos, card `#lbOffCard` (`LBOFF`: copiados
  inativos | todos os inativos do ranking). Visão geral: `#dayChartCard` ao lado da Evolução e `#lrnChartCard` ao lado das Operações
  (`.vgtop` em `auto-fit`: sem os cards de admin, a Evolução ocupa a linha). Relatório `app/relatorios_ia/2026-10-29-0.32.43.md`.
  Teste `tests/test_online.py::test_active_top_traders_get_own_slots_even_with_many_manuals`.

- 0.32.44: migração `20261029000005` (pedido do dono no chat): `pump_bar_auto_on`=false só na conta dele, por `settings_overrides`
  (barrados entravam no topo: 11 stops de −30% em 15 fechadas em 3 h). Religar quando o Relatório de cada aba mostrar gatilho com lucro.

- 0.32.45: `#ntfP` fecha com clique fora (menos `#ntfB` e `.modal`) ou Esc. Pedido do dono.
- 0.32.46: na Base geral o cartão "O cérebro do robô" é sempre o primeiro (pedido do dono); cartão novo entra abaixo dele.
- 0.32.47: `app/study_ai.py` (`wallet_block`, `PROMPT`, `ai_text`) + `GET /api/pump/study/ai[?wallet=]` (admin; antes da rota `{wallet}`);
  botões `data-stai` e modal `#staiM` em Carteiras estudadas. O ChatGPT só levanta os dados; a análise é do Claude. `tests/test_estudo_ai.py`.
- 0.32.48: tabela `study_ai_reports` (migração `20261029000006`; estados gerado → esperando → resposta; "analisado" = existe
  `app/analises_carteiras/<id>.md`). `hub.study_ai_create/reports/auto/analysis`; `study_ai_auto` no fim do `study_auto` (5 carteiras
  novas sem relatório ou a mais antiga com 24 h: `study_ai.AUTO_MIN`/`AUTO_WAIT_S`). Rotas `/api/pump/study/ai/reports[/novas|/{id}]`.
  **Quando o dono trouxer a resposta do ChatGPT:** analisar e gravar `app/analises_carteiras/<id do relatório>.md` na mesma entrega.

- 0.32.49: `PumpMarket.ingest` marca `dev=True` na posição em memória criada pela compra do criador no evento `create`;
  `trader_positions()` devolve `dev`; `#tTP` mostra a etiqueta "criou o token". Lógica de cópia igual (lançamento nunca foi
  copiado). Caso: GeUn…UX1W (lançador em série, dev buy 3,0617 SOL, tudo "morreu"). Teste em `tests/test_online.py`.
- 0.32.50: `PumpFun.dump_block` (`pump_dump_*`, OFF) na cadeia de filtros de `_copy`; `SharedMonitor.handle_ev` lê `holders_check` (até 3 s)
  na compra só se algum seguidor ligou o filtro. Migração `20261029000007` (override só do dono): timestop 300 s/+10%, `pump_max_hold_h` 0,4,
  tp1 35%/50%, trail 13 pontos, filtro ligado. Relatório `app/relatorios_ia/2026-10-29-0.32.50.md`.
- 0.32.51: `ex()` em `web/app.js` devolve HTML (0,0<sub>6</sub>3831; só usar em HTML, não em textContent/title). `ntfMoney` na lista do sino;
  prefixo [PUMP SIM]/[PUMP REAL] escondido na tela (a mensagem continua igual para som/mascote). `.modal` fecha no fundo ou com Esc.
- 0.32.52: `hub._reassert_overrides` (no `_load` e a cada 5 min): ajuste de `settings_overrides` aplicado há até 20 min é reposto se o
  servidor ANTIGO gravou por cima na troca de versão (barrados voltaram às 11:05). Migração `20261029000008` desliga de novo os barrados
  do dono. Voz: `say`/`sayTrade` (speechSynthesis pt-BR, `localStorage` `ntf_voz`/`ntf_voz_f`), botão `#ntfV`. `daily.dhm` nos trades do dia.
- 0.32.53: `PumpFun.entry_guard` (`pump_guard_*`, OFF; migração `20261029000009` liga só no dono) em `manual_buy` para `GUARD_ORIGINS`
  (botão, barrados, Aba do Bruxo; nunca Explorar/auto/follow): graduado só com `main_dex` ≠ pumpfun, preço ≤ 30 s, `liq_usd` mínima, e
  `dump_block(force=True)`. A rota do botão lê preço e detentores antes. Relatórios ChatGPT: `#staiF` (arquivo), Salvar fecha a janela.
- 0.32.54: voz: `VOZ` padrão ligada, `unlockVoice` no 1º clique, `ptVoice` (prefere pt-BR natural/online), utterance guardada em `window.__fala`, botão `#ntfVT`.
  O Windows deste PC só tem vozes em inglês; Chrome/Edge trazem pt-BR próprias, o Brave não.
- 0.32.55: `app/analises_carteiras/20261029-0956-cfaf.md` (26 carteiras: 11 lançadoras, 7 alta frequência, 4 perdem na vida, 2 fora da pump.fun;
  observar DScqtG e dmuXAm). Propostas no fim do arquivo (barrar lançador/HFT, simular a cópia depois do lançador) aguardam o dono.
- 0.32.56: `_reassert_overrides` repõe TODOS os ajustes aplicados (mais novos ganham), exceto as opções que a pessoa mudou na tela
  depois (`pf._ov_user` {opção: quando}, gravado em `/api/pump/settings` e salvo como `_ov_user`). Aviso do fechamento usa `aba_of`;
  `ntfAba` no sino; voz na compra (`VOZ_F.buy`, `#ntfVb`).
- 0.32.57: `PumpFun.uncopiable` (`pump_nc_*`, OFF; migração `20261029000010` liga no dono e tira 24 carteiras do estudo/lista manual dele):
  `refresh_followed` põe em `bots`, `_copy` barra, `study_auto` descarta; `study.copy_sim` (FLIP_S 30 s → −30%, veredito "não dá para copiar").
  Relatório `app/relatorios_ia/2026-10-29-0.32.57.md`.
- 0.32.58: `bruxo_reason` não trava sem `top10`; `pp_wanted` inclui `elite.wallets()` com Aba do Bruxo ligada; `/api/pump/settings` grava
  audit "compra automática mudada na tela" (`AUTO_SWITCHES`, com user-agent). Barrados do dono religaram às 11:49 CET mesmo com o ajuste.
- 0.32.59: `curve_block` barra token graduado com a faixa da curva ligada; `pump_cx_copies_only` (saída antes da graduação só nas cópias)
  e `p["cx_pct"]` (regra da posição; Aba do Bruxo `pump_bx_grad_exit`); `pump_bx_curve_max`; `hub.bruxo_launch_scan` (`pump_lanc_on`,
  sinais `kind="lancamento"`, até 12/h, só estudo) e `bruxo_state["lancamento"]`. Migração `20261029000011` (override só do dono).
- 0.32.60: `PumpFun.entry_why(p)` → `tr["entrou_porque"]` (fictícia e real) e `entrou_porque` nas posições do snapshot; "Por que entrou" no detalhe.
- 0.32.61: `pump_stop_fast_on` (ON) põe toda posição com stop no `trail_once` (~1 s; Explorar fora); `PumpFun._stop_gap` explica stop que
  passou 5+ pontos do limite (`p["_chk"]` = leitura anterior). REAL por aba em `manual_buy`: `pump_auto_real` (Base, agora mesmo com espelho),
  `pump_el_real` e `pump_calls_real` (novos). Migração `20261029000012` (override do dono: fictícias ligadas, REAL desligado). `tests/test_real_por_aba.py`.
- 0.32.62: venda REAL que falha espera 10 s → 5 min (`PumpFun._real_sell` devolve bool, `_sell_failed`, `sell_retry_at`/`sell_fails`; "por você" não
  espera); `PumpReal._rpc` explica resposta sem JSON; `balances`/`_raw_tok` com `_rpc_retry`. Caso PEPE do Bruxo. `tests/test_venda_real_espera.py`.
- 0.32.63: `apis.solana_tracker.fonte` (sua chave / chave do sistema / nenhuma) na linha da Solana Tracker do `#sysM`.

- 0.32.65: `PumpFun.token_decimals` (getTokenSupply, cache em `tokens[m].decimals`; "…pump" = 6) em `_pumpswap_prices` — antes 6 casas para todo token
  (PEPE tem 4 → preço 100×, stop móvel em +9.547% falso). Casas ≠ 6 marcam `dec_fix_t` e `_check_stops` apaga pico/stop móvel/melhor momento
  da posição (feed "preço corrigido"). `JupiterWallet._rpc` explica resposta sem JSON e tenta uma vez em `PUBLIC_RPC`. `tests/test_pepe_casas.py`.
- 0.32.67: `_check_stops` apaga `sell_error`/`sell_fails`/`sell_retry_at` quando a venda que falhou não é tentada há 15 min (erro velho no card do PEPE).
- 0.32.69: `refresh_leaderboard` mostra "créditos do mês acabaram nesta chave" quando a Solana Tracker responde "Insufficient credits" (antes "sem permissão").

## Análise das APIs de consulta (2026-10-29, sobre a 0.32.63 — só documento, sem mudança no código)
- Pedido do dono (Bruxo95). `docs/ANALISE-APIS-2026-10-29.md`: a Solana Tracker pede ≈ 2.500–3.000 consultas/dia contra 10 mil/mês do
  grátis ("Insufficient credits"). Maior gasto: Carteiras em estudo a cada 30 min (≈ 52 mil/mês), Explorar (≈ 8,6 mil), ranking
  a cada 10 min (≈ 4,3 mil/grupo), risco do token (2 consultas por token, antes dos outros filtros). Propostas A (economia),
  B (`app/stclient.py`: 2/s por chave, prioridade, pausa em "Insufficient credits", último resultado bom, `GET /credits`),
  C (plano pago, decisão do dono), D (RPC Helius no Portainer). Divisão sugerida entre Bruxo95 e Douglas no fim do documento.
  Aguardando o OK do dono antes de mexer no código.
- 0.32.64: `hub.chance_alta` + `GET /api/pump/explore/chance-alta?horas=` (admin; um token por linha a partir de `explore_cycles.chance_alta_barrados`,
  `_ex_funnel`, sombras e trades do Explorar); link `data-chance` no cartão Chance alta de Logs → modal `#chaM` (`openChance`). `tests/test_chance_alta.py`.
- 0.32.66: Copiar igual por carteira: `pf.eq_mode` {carteira: sim|both|off} (salvo `_eq_mode`; `eq_wallets` tira as "off"; "both" espelha na real
  só aquela), `hub.eq_mode_set` + `POST /api/pump/copy-equal/mode` (liga `pump_eq_on` se estava desligado; audit), coluna Cópia e modal `#eqM`.
- 0.32.68: Copiar igual só copia carteira com `eq_mode` sim/both (sem clique = "off"); antes, com `pump_eq_on`, toda a lista copiava.
- 0.32.70: `hub.eq_detail` + `GET /api/pump/copy-equal/wallet/{w}` (admin): monitor ouvindo, última atividade, Feed da carteira, decisões, abertas e
  fechadas do Copiar igual; botão `data-eqd` Acompanhar e modal `#eqD` (`openEqDetail`). `tests/test_eq_detalhe.py`.
- 0.32.71: `app/stkeys.py` (saúde das chaves da Solana Tracker, só memória, por hash): "Insufficient credits" deixa a chave de fora 1 h
  (`refresh_leaderboard` e gancho `response` do httpx em `apiusage.resp_hook`). `hub.st_pick(prefer)` (pessoais → sistema, pulando as sem créditos) no
  risco, Explorar, estudo e Raio-X; `lb_once` tenta a próxima chave na mesma volta; `PumpFun.lb_key` usa a do sistema se a sua está sem créditos;
  `lb_key_src` no Status. Caso do dono: a consulta compartilhada usava a chave pessoal sem créditos de outra conta. `tests/conftest.py` zera o estado.
- 0.32.72: Copiar todas (`data-eqc="*"` no topo de Carteiras da lista; `hub.eq_mode_set(pf, "*", modo)` aplica a todas da lista).
- 0.32.73: `app/eqreport.py` (`build` por carteira + operações + veredito; `learn` para a Base geral) + `hub.eq_report_tick/loop` (confere a cada 30 min,
  grava a cada 6 h; tabela `eq_reports`, migração `20261029000013`) + `GET /api/pump/copy-equal/reports[?real=1]`; cartão no `#igual` (`loadEqRep`)
  e `#bgEq` na Base geral. `tests/test_eq_relatorio.py`.
- 0.32.74: `D.live` (Monitor ao vivo) também no sino (aba `#ntfTab` "Traders copiados", `ntfTraders`, sem som) e no Histórico (`#hMon`, `renderHMon`);
  linha comum `monRow`/`MON_H`.
- 0.32.75 (pedido do dono): celular em formato de app, SÓ até 860 px (PC igual). Bloco no fim de `web/app.css` (`.tabbar` escondida fora do
  celular; topo compacto com `.ntfl` escondido; janelas `.modal` como folha de baixo; áreas seguras `env(safe-area-inset-*)`; campos 16px).
  `#tabbar` em `web/app.html` (Início/Traders/Posições/Histórico + `#tbMenu` abre a gaveta; `tbPos` copia `nbPos`; `route()` marca `.on`).
  Atalho do iPhone: `apple-mobile-web-app-title` = FUN COPY, `web/apple-touch-icon.png` (180), `web/icon-192.png`/`icon-512.png` (mascote do
  print do dono em fundo preto) e `web/manifest.json` (standalone, start_url /app) em `app.html` e `index.html`; `viewport-fit=cover`;
  `html.pwa` quando aberto pelo ícone. `tests/test_app_celular.py`.
- 0.32.76: ícones do atalho (`web/apple-touch-icon.png`, `icon-192.png`, `icon-512.png`) trocados pelo "Banker" (Symbolon, Noun Project, CC BY 3.0:
  crédito obrigatório, fica em Como funciona) em branco sobre preto, a pedido do dono.
- 0.32.77: ícones renomeados para `web/fun-copy-180/192/512.png` (o iPhone guardava os nomes antigos); favicon da aba = `fun-copy-192.png`.
- 0.32.78: Lançamento sem trader: `data-buy` com `data-orig="lancamento"` em cada linha e `#lnBuyAll` (Comprar todas os sinais não `done`, `BUY_ALL` no
  modal `#buyM`); origem `lancamento` aceita em `/api/pump/manual-buy`, em `GUARD_ORIGINS`, `ABA_ORIGEM` e `OWN_SLOTS` (`pump_lanc_max_open` 30).
- 0.32.79: Aba do Bruxo (`bxSig`, `lnT`): `bxMarks` (1/5/10/25 min) e `bxAfterPeak` (do pico até a última foto).
- 0.32.80: `app/bruxoreport.py` (`build` do período: sinais, lançamentos, operações bruxo/lancamento, lições; `learn` dos relatórios de 1 dia) +
  `hub.bx_report_tick/loop` (confere a cada 5 min; grava a cada 30 min e o dia anterior UTC uma vez; tabela `bruxo_reports`, migração
  `20261030000001`; só admin com `pump_bx_on` ou `pump_lanc_on`) + `GET /api/pump/bruxo/reports[?em=]`; cartão `#brK` na Aba do Bruxo e `#bgBx` na Base geral.
- 0.32.81: Aba do Bruxo — `#bxAuto`/`#bxEvery`/`#bxNow`/`#bxLast` (`BXR` em `localStorage` `pf_bx_ref`, 5–600 s, padrão 20; `bxSchedule` no fim de `loadBruxo`).
  Sinais da aba chegam ao vivo pelo monitor (`handle_ev` → `_bruxo`); `bruxo_loop` (lançamentos e acompanhamento) roda a cada 20 s. Pedido do dono.
- 0.32.82: Aba do Bruxo — sinal guarda `created_t` (nascimento = t − age_min; a idade da tela é a da compra, conferida com a DexScreener)
  e `holders` {0,1,5,10,25 min} via `Bruxo.holders_due` + `hub.holders_count` (RPC do sistema: Helius `getTokenAccounts` 1.000/página,
  senão `getProgramAccounts` nos 2 programas de token; cache 45 s; RPC público não conta). Tela: `bxAge`/`bxHold`. `tests/test_bruxo_detentores.py`.

## TESTE: Jev (TypeSafe AI) em modo sombra (2026-10-30, versão 0.32.83) — aviso para o Douglas
- Pedido do dono (Bruxo95): colocar a API do Jev direto aqui (não é o bot hermes-jev) e começar SÓ pela Aba do Bruxo, em sombra.
  **O Jev não compra nem vende nada.** Ele só opina; a decisão fica no sinal e a aba JEV compara com o que o token fez.
- Chave do SISTEMA `jev_api_key` (`keystore.SYSTEM_NAMES`/`KEY_LINKS`; Administração → Chaves do sistema, salva criptografada em
  `app_secrets`). Sem chave = nenhuma chamada. Opção `pump_jev_on` (padrão ON, por admin; chama se algum admin tiver ligada).
- `app/jev.py`: `QUESTIONS` (choice `acao` entrar/esperar/evitar, score `qualidade` 0–4, noul `armadilha`), `state_for(sinal)` (só números já
  medidos: idade, ritmo × média, mcap, top10, criador, detentores, SOL dos traders), `ask` (POST https://api.typesafe.ai/v1/systemone,
  modelo `jev-latest`, Bearer, 8 s; erro nunca mostra a chave), `sim_result`/`study` (acerto por decisão, calibração por faixa, curva em SOL
  com 0,1 SOL por entrada, saída na marca 5/10/25 min ou no −30%, −4% de taxas).
- `hub.jev_shadow(s, f)` no fim de `bruxo_on_trade` (sinal novo) e em `bruxo_launch_scan` (lançamento novo): tarefa em segundo plano,
  1 pergunta por sinal, até `jev.DAY_MAX`=3000/dia (contadores `hub.jev_stats` só em memória), 1 nova tentativa em 429/529. Resultado em
  `s["jev"]` → gravado junto com o sinal em `bruxo_signals` (sem migração nova). `hub.jev_state` + `GET /api/pump/jev?horas=&saida=` (admin).
- Front: menu `#navJev` "JEV (sombra)" logo abaixo da Aba do Bruxo, tela `data-view="jev"` (`loadJev`, `jvChart` com 3 séries, tabelas
  `#jvA`/`#jvB`/`#jvT`). Testes: `tests/test_jev.py`. **Não testado com a API real do Jev** (falta a chave; formato da resposta lido da doc).
- Próximo passo só com OK do dono e depois de dias de dados na aba JEV: usar o Jev como filtro da Aba do Bruxo (ainda só fictícia).
- 0.32.84 (pedido do dono: "estudar os casos passados desde o início"): estudo do passado (backtest) do Jev. `jev.case_bruxo`
  (sinais encerrados de `bruxo_signals`), `jev.case_explorar` (`base_shadows`: estado do `info`, resultado `ret` − 4% aos 15 min,
  regra = veredito "chance alta") e `jev.case_base` (`token_life`: decide na foto de 1 min, resultado 5/15/60 min) — o estado leva SÓ
  o que se sabia na hora (sem rótulo, previsão, fotos futuras ou pico). `hub._jev_bt_run` (liga em `jev_bt_set`, rota
  `POST /api/pump/jev/passado` com audit; 0,5 s entre perguntas, `jev.BT_DAY_MAX`=20 mil/dia, para após 20 erros seguidos, repete a
  cada 6 h) → tabela `jev_backtest` (migração `20261030000002`, só backend; linha `_run` guarda ligado/desligado e `jev_bt_load` retoma
  após reinício). `GET /api/pump/jev?fonte=ao_vivo|bruxo|explorar|base|todos&horas=0` (0 = tudo); `jev.study_rows`/`pick` (saída mais
  próxima que existe na fonte). Front: seletor `#jvF`, cartão "Estudo do passado" (`#jvPOn`, `#jvPK`, `jvPast`, `jvPastTable`).
  O Jev não é treinado com esses casos: responde um a um e nós medimos o acerto. Não testado com a API real.
- 0.32.85 (dono: "a chave do Jev não salvou"): a regra `app_secrets_nome_check` só aceitava 4 nomes; a migração
  `20261030000003_jev_chave_e_tabelas.sql` libera `jev_api_key` e cria `jev_decisions` (cada pergunta ao vivo: estado mandado, ação,
  chances, nota, armadilha, ms, tokens, erro; `hub._jev_save_decision`) e `jev_usage` (dia × ao_vivo|passado; `hub._jev_usage_save` a cada
  30 s, `jev_usage_load` no início para o limite do dia valer após reinício). Leitura para `leitor_ia` nas 3 tabelas do Jev.
  **Chave nova do sistema = acrescentar o nome também numa migração da regra `app_secrets_nome_check`** —
  `tests/test_jev.py::test_migration_allows_every_system_key` falha se faltar.

- 0.32.86 (áudio do Bruxo, 30/10): `app/detentores.py` (`entry`: mínimo de detentores + 2 altas seguidas + crescimento, até 10 min; `result`: entrada no preço da
  leitura, `hpx`, nunca no do sinal; `study`: faixas no início, evolução até 5 min, regra × todos × regra+Jev). `Bruxo.holders_due`: 40+ detentores = leitura a cada
  minuto até 10 min (`HOLD_WATCH`, `HOLD_EVERY`). `GET /api/pump/jev?hold_min=&hold_cresc=` devolve `detentores`; cartão na aba JEV (`jvHold`) e 4ª série do gráfico.
  Só mede, nunca compra. Sem RPC próprio não há leitura. Dados de produção não conferidos (sem `pump.env`). `tests/test_detentores.py`.
- 0.32.87 (Bruxo, áudio de 30/10 12:06): menu `#jevtrade` "Jev Trade", simulação global (fora do motor dos usuários, nunca compra). `app/jevtrade.py` (`JevTrade`, `Q_IN`, `Q_OUT`, `study`)
  + `hub.jt_tick/jt_loop` (20 s; lê `lab.live` aos 5–8 min vivos, 40+ detentores observados por até 15 min, Jev a cada 60 s, stop só sobe, detentores −30% do pico saem) +
  `jev_trades` e `tipo='trade'` em `jev_usage` (migração `20261030000004`) + `GET /api/pump/jev-trade[/{mint}]` (admin) + opção `pump_jt_on`. Limites: 60 conferências/h, 2.500 leituras/dia (≈750 mil créditos Helius/mês),
  6.000 perguntas/dia, 10 abertas. "Criador vendeu" só é conhecido se o monitor viu a venda. Régua fixa (−30%/25 min) mede se o Jev ajuda; decidir compra só com 20+ fechadas. Não testado com a API real do Jev.
- 0.32.88: `detentores._detail` (`detalhe` em `study`: itens, ganhos, perdas, mediana, sem os 3 maiores); `kpis()` aceita 6º campo → `data-kpi`/`.kpiclick`; `openJd`/`JD_INFO` usam o modal `#jtM`. Pedido do dono.
- 0.32.89: `dt()` em `web/app.js` aceita número em SEGUNDOS (< 1e11 → ×1000). As abas JEV e Jev Trade mandam `t` em segundos e tudo
  aparecia como 21/01/1970 19:09 (mesma hora). Dados no banco estavam certos (conferido: `jev_backtest` 26/10–30/10, `jev_decisions` 30/10).
- 0.32.90 (pedido do dono): Jev Trade — `jtTk` = `pfM` (nome abre a pump.fun + ficha "i") + link "leituras" (`data-jt`, janela de cada minuto);
  `jtEv` = detentores `h0 → h (±diferença)` (1ª leitura aos 5 min → agora/fim) nas tabelas `jtO`, `jtW` e `jtF` (coluna nova nos Encerrados).
- 0.32.91 (pedido do dono, caso SKIVE): Jev Trade com a REGRA DO BRUXO. Os 52 tokens até então foram descartados por "o Jev desistiu" na 1ª leitura.
  `jevtrade.STRAT` (20% de detentores em 2 min + preço subindo; prazo 7 min = `WATCH_MAX_MIN`; stop 25%; empate após +50%; metade em +100%;
  stop móvel 25% do pico após +30%; saída com detentores 15% abaixo do pico desde a entrada). `JevTrade.rule_check`, `bruxo_entry` (o hub usa no lugar
  de `on_entry`; o Jev só opina e escolhe o stop), `guard_exit` (em `on_price`), `holders_leaving` (em `hub._jt_read`). `_jt_scan` grava a 1ª contagem
  como leitura. `row(..., now)` → `regra`, `obs_s`, `ultima_s`, `prox_s`, `prazo_s`, `por`. `backtest_rule` + `from_bruxo_signal` → `regra_passado` em
  `/api/pump/jev-trade` (cartão `#jtRK`/`#jtR`). Relatório `app/relatorios_ia/2026-10-30-0.32.91.md`. Ainda só simulação.
- 0.32.92 (caso hunch): os Encerrados do Jev Trade mostravam `fechou_t` como "Hora" (parecia 13 min de atraso). `row` devolve `created_t`; tabelas
  `jtW`/`jtO`/`jtF` com Nasceu (`jtBorn`) e Na lista (`jtList`: entrou com X min de vida, saiu, tempo na lista). Conferido no banco: hunch nasceu
  20:32:29, entrou 20:38:04 (5,6 min, porta dos 5 min do Bruxo) e saiu 20:45:17 por "não entrou em 7 min" (detentores 77→84, só +9% em 2 min).
- 0.32.93 (pedido do dono, caso hunch): `rule_check` exige detentores SÓ subindo nas leituras dos últimos ~2 min (`subindo`), +20% e preço subindo.
  Fechamento dos 7 min: `market_positive` (preço e detentores acima da 1ª leitura) → `_enter` em `on_price`; senão descarta. `JevTrade.on_event`
  → `hub._jt_wallet`: entrada vira `manual_buy(origem="jevtrade", target="sim", amt_sol=0,1, pos_rules=JT_WALLET_RULES)` na fictícia de cada admin
  com `pump_jt_wallet` (padrão ON); vendas do Jev Trade vendem a mesma fração (`pf._sell`). `OWN_SLOTS["jevtrade"]` (`pump_jt_wallet_max` 10),
  `ABA_ORIGEM["jevtrade"]`. Nunca REAL. `backtest_rule` também considera a entrada do fechamento. Relatório `app/relatorios_ia/2026-10-30-0.32.93.md`.
- 0.32.94: confirmado pelo dono (30/10 21:30): os 20% da regra do Jev Trade são só dos DETENTORES (subindo em cada leitura); o preço só precisa estar
  positivo (qualquer alta). Código já era assim; textos da tela ajustados e teste `test_price_only_needs_to_be_positive_not_20_pct`.
- 0.32.95 (pedido do dono): Jev Trade sem o mínimo de +20% de detentores (`STRAT["cresc_pct"]`=0): detentores subindo em cada leitura e preço positivo;
  `rule_check` exige leituras cobrindo os 2 min (`cobre`, 3 leituras) para uma alta de 1 detentor em 1 min não disparar. Relatório `app/relatorios_ia/2026-10-30-0.32.95.md`.
- 0.32.96 (pedido do dono, caso xpad): a posição do Jev Trade na fictícia leva as regras do Jev Trade (`hub.jt_wallet_rules`: stop, `be_after` 50 = empate,
  tp1 100%/50%, stop móvel após +30% com `trail_rel` 25 = % abaixo do pico do preço) executadas pelo motor; `_jt_wallet_sync` aplica nas já abertas;
  parcial do Jev Trade não repete a do motor. `_check_stops` ganhou `trail_rel` e `be_after`; card mostra os textos. Relatório `app/relatorios_ia/2026-10-30-0.32.96.md`.
- 0.32.97 (pedido do dono): `pump_jt_real` (OFF) — botão "Também na carteira REAL" no Jev Trade; `hub._jt_wallet` usa `target="both"` e `manual_buy`
  deixa passar (`jt_real`) com a Execução real ligada; regras de saída iguais às da fictícia; em `AUTO_SWITCHES` (audit). Só o dono liga.
- 0.32.98 (erro do dono, 30/10 22:28): `PumpReal._send_raw` — `sendTransaction` com 429/sem dados/queda tenta de novo no RPC da carteira e depois no
  `SOL_HTTP`; erro da própria rede não repete. `tests/test_envio_429.py`. O RPC próprio do dono (`rpc_url`) respondeu 429 no envio do ">_" (Jev Trade).
- 0.32.99 (erro do dono, PIO 30/10 22:47): a simulação devolve o erro da pump.fun em DECIMAL (`{'Custom': 6005}` = BondingCurveComplete);
  `PumpReal.retryable`/`PUMP_ERRORS` agora reconhecem 6002–6005 em decimal → tenta PumpSwap e Jupiter. Teste em `tests/test_envio_429.py`.
- 0.32.100 (venda LENNY, 30/10 23:00): o RPC passou a aceitar no máx. 21 contas por `simulateTransaction` e toda simulação da rota PumpPortal falhava.
  `PumpReal.SIM_BATCH` = 19 + a carteira; com "Too many accounts provided; max N" refaz os lotes com N − 1 e lembra. Teste em `tests/test_seguranca.py`.
- 0.32.101 (BALLOON/MLC, 30/10 23:14): `_send_confirm` conferia a cada 0,25 s e reenviava a cada 1 s no RPC da carteira → 429 → confirmação só após o
  blockhash vencer (~172 s). Agora 0,5 s, reserva no `SOL_HTTP`, reenvio a cada 2 s; `reconcile`/`_sol_change` com `_rpc_retry` (sem isso o gasto
  caía na diferença de saldo e misturava compras simultâneas). `pos_cfg` leva `origem` (card mostrava "Botão comprar"). Teste em `tests/test_envio_429.py`.
- 0.32.102 (pedido do dono, 31/10): filtros do Jev Trade na tela — 13 opções `pump_jt_*` (padrão = regra que valia) → `hub.jt_cfg` (por opção, o admin
  que mudou por último em `_ov_user`) → `jevtrade.apply_cfg` (globais `MIN_HOLDERS`, `SCAN_*_AGE_MIN`, `WATCH_MAX_MIN` e `STRAT`) a cada `jt_tick` e
  no `jt_state` (`filtros` com `_de`). Cartão `#jtf_*` + `#jtFReset` + `#jtFNow`; `#jtWSub` dinâmico. Teste em `tests/test_jev_trade.py`.
- 0.32.103 (pedido do dono): `kpis()` com `data-kpi` nos cartões da Visão geral → `openOv` (modal `#jtM`; segue FICTÍCIA/REAL; trades = últimos 300 do snapshot). Cartão Execução real com chave `#realAll` = `pump_real_enabled` (`realAll`, `openRealPlaces`): desligar é na hora, ligar segue pedindo LIGAR; 
  `hub.REAL_PLACES`/`real_places` + `GET /api/pump/real/lugares`: a opção de cada aba não muda e a venda real não depende da chave. `pf.real_on_at/real_off_at` salvos como `_real_on_at/_real_off_at` (ligada antes: lê do `audit_log`). Aba nova que compra na REAL = linha em `REAL_PLACES`. 
  Detentores: `study(show=)`, `hub.hold_market` (DexScreener ao abrir, 30 s, 90 tokens), `s["top10"]`/`dev_pct` uma vez aos 40+ (`_bruxo_top10`), `HOLD_EVERY` até 20 min, `openJl`, filtro `#jvHS` (padrão 40+).
- 0.32.104 (pedido do dono): `tglScope(k, c)` em `web/app.js` (`TGL_REAL`, `TGL_ENTRY`, `TGL_NOBUY`; o resto = REGRA) escreve no botão de toda chave `data-toggle` onde ela vale, no `title`, no toast e na confirmação. Chave nova: classificar ali. `tests/test_avisos_chaves.py`.
- 0.32.105: `on_notification` só conta `pp_skip` com `acct_last` há menos de `PP_FRESH_S` (120 s); sem entrega da PumpPortal lê pelo RPC. `pp_wanted` liga para todos se um admin ligar. Relatório `app/relatorios_ia/2026-10-31-0.32.105.md`.
- 0.32.106 (propostas da conferência dos lotes, `PUMP-FUN-LEARNING/conferencia-claude-lotes7-10-e-lote8-31-10-2026-10-31.md`): `status.pp_msg` (mensagens da PumpPortal); `JEV_MODEL` fixo em `jev-1.14.0`, `modelo` nas respostas e em `jev_decisions` (migração `20261031000001`); `jev.real_cost_pct`/`with_real_cost` (`sol_real` ao lado dos 4%, que seguem iguais para comparar com o passado); `holders_count` tira a curva; `_hv2_sample`/`_holders_v2` testam `getProgramAccountsV2` em 1 de 5 contagens (300/dia, `hub.hv2`, só memória, aparece na aba JEV) e não mudam nada: trocar o método só com o OK do dono. `tests/test_contagem_v2.py`.
- 0.32.107 (lote 11 conferido): `_pp_subs` zera quando a conexão cai; `app/realgap.py` (`summary`, `sells`) → `resumo` em `/api/pump/real/mirror`, `#rmG`/`#rmV`; `sim_entry_px` no trade fictício; `sell_tries` na posição e no trade real; `jev.SLIP_LADO_PCT` e `sol_slip`; `past_decisions`/`partial_sales` no estado do Jev Trade. `tests/test_real_gap.py`. Relatório `app/relatorios_ia/2026-10-31-0.32.107.md`.
- 0.32.108 (dono, 31/10 11:35, faixa 3–4 min; saiu primeiro numerada 0.32.103 por engano, depois da 0.32.107): `JevTrade.candidates` exigia `snaps["5"]` da Base → nada antes dos 5 min. Agora usa `market.tokens[].mcap_sol`
  (ou a foto mais recente); parado conta uma vez (`_jt_p`) e segue olhado até o fim da faixa. Teste `test_age_window_before_5_min_uses_live_market_cap`.
- 0.32.109 (pedido do dono, 31/10): Posições com `POSF` (`localStorage` `pf_posf`: busca `#posQ`, ordem `#posSort` — padrão maior ganho %, resultado `data-posres`,
  aba `data-posaba` por `posAba` = `p.aba`), `posView` (KPIs `#posK`, tabela por aba `#posAbaT`); `POS_DET.list` continua com todas. CSS `.posbar`/`.posabas`.
  Atenção: antes de escolher o número da versão, conferir `app/version.py` DEPOIS do `git pull` (a 0.32.108 saiu como 0.32.103 por engano).
- 0.32.110 (pedido do dono, 31/10): Jev Trade na ordem Abertas (`.jtfirst`, `#jtOSub`) → Em observação → controle (chaves em `.jtsw`, "Como funciona"
  recolhido em `details.jtcomo`) → Filtros (`.jtfilt`, 2 colunas até 860 px) → Resultado (`#jtH`/`#jtK`/`#jtC`) → regra no passado → Encerrados → Por que saiu.
  Conferido em 1440 px e 390 px (sem rolagem lateral).
- 0.32.111 (pedido do dono, 31/10): Jev Trade sai com o mercado parado — `JevTrade.stalled` em `on_price` (posição aberta; `ticks` de preço a cada
  20 s, 15 min; janela `STRAT["parado_min"]`=3, faixa < `parado_pct`=5%, sem pico novo e sem detentores subindo). Opções `pump_jt_parado_min/_pct`
  nos Filtros (0 = desliga). Conferido em 1440 e 390 px. Relatório `app/relatorios_ia/2026-10-31-0.32.111.md`.
- 0.32.112: `sysDetail` usava `c`, inexistente ali (erro da 0.32.106): com carteiras assinadas na PumpPortal a janela do Monitor não abria. Usa `cfg()`. Teste em `tests/test_avisos_chaves.py`.
- 0.32.113 (pedido do dono): `PumpFun.periods` → `wallet()["periodos"]` (1/6/12/24 h, só trades fechados, todos, não os 300 do snapshot); tabela `#ovP` na janela Resultado. `tests/test_periodos.py`.
- 0.32.114 (pedido do dono): `app/resultstudy.py` (`build`, `learn`) + `hub.rs_study/rs_save/rs_saved/result_tick/result_loop/rs_learn`; tabela `result_studies` (migração `20261031000002`; `origem` manual ou dia); rotas `/api/pump/result-study[/learn]`. Botão Estudar (`data-rsh`, `openRs`) e cartão `#bgRsA` na Base geral (`loadRsBase`). A Base soma só dias fechados (7 para trás, gravados de hora em hora), porque as janelas se sobrepõem. Só mede. `tests/test_estudo_resultado.py`.
- 0.32.115 (pedido do dono): `hub.rs_marks/rs_base/rs_item` + rotas `/api/pump/result-study/marcas|base|item`; `openRs` grava antes de dizer enviado; `renderRs` serve à Visão geral e à Base geral (`#bgRsS`, `data-rsv`, `openRsItem`); botão `.rsdone`. Estudo do botão aparece na seção, mas o aprendizado soma só dias fechados.
- 0.32.116 (lote 12 conferido, `PUMP-FUN-LEARNING/conferencia-claude-lote12-2026-10-31.md`): `app/stats.py` (`ci_days` sorteia dias, `reading`, `wilson`) no lugar de 'vale a partir de 20' em detentores, Jev Trade e Real × fictícia; `holders_t5` + `JevTrade.h5`/`h5_close`/`h5_study` + `hub.h5_tick` (`h5` na rota do JEV, 40+ × menos, com Wilson); `app/marketday.py` + `market_days` + `hub.market_tick` + `resultstudy.by_market` (fonte pumpdata.fun, citada na tela; dia frio nunca é filtro de entrada); `hub.wallet_guard_*`/`wallet_leak` (alerta de transferência simples na carteira real, 60 s, não bloqueia); `#feeHint`. Migração `20261101000001`. `tests/test_estudo_incerteza.py`.
- 0.32.117: `app/brainshadow.py` (`aba`, `features`, `regras`, `run`) + `hub.brain_shadow` (cache 60 s) + `GET /api/pump/base-geral/sombra` (admin); cartão `#bgSh`/`#bgShF` na Base geral (`loadBrainShadow`). Regra do aprender com os erros medida nas outras abas, cada trade julgado só com o que fechou antes de ele abrir; não bloqueia nada. `tr["score_parts"]` novo nos trades. Base automática se separa do botão pelo `entrou_porque`. Relatório `app/relatorios_ia/2026-11-01-0.32.117.md`. `tests/test_cerebro_sombra.py`.
- 0.32.118 (pedido do dono): com a real ligada `auto_tune` para, então `hub.tune_suggest` faz as mesmas contas e `hub.tune_apply` + `POST /api/pump/tune/apply` aplicam só no clique (só o id vem do navegador; `_ov_user` e `auto_tune_log`); `sugestoes` em `/api/pump/tune`, tabelas `#tuSug` e `#bgTu` (`renderTuSug`). `brainshadow.evolucao` (7 dias × 7 anteriores, `#bgEv`) e `brainshadow.limites` (2/4/6/10 por hora, `#bgShL`): só medem, nenhum limite ligado. Veredito perto do início (`.shv`). O Playwright não está neste PC: a conferência de tela foi pelo navegador embutido. Relatório `app/relatorios_ia/2026-11-01-0.32.118.md`. `tests/test_ajuste_sugestao.py`.
- 0.32.119: `aba_of` reconhece a compra automática da Base pelo texto "automático:" em `auto` ou `entrou_porque` (ela não grava `origem` e caía como Botão Comprar). Etiqueta só aparece se houver posição aberta daquela aba.
- 0.32.120: site em 404 depois da 0.32.119. Suspeita, sem acesso aos logs: `hub.start` carrega tudo antes de abrir a porta e o HEALTHCHECK derrubava em ~90 s. `--start-period=600s` no Dockerfile e `subida_s` no `/health` para medir. Se `subida_s` vier perto de 90, a causa está confirmada e a subida precisa ficar mais leve.
- 0.32.121: `lifespan` roda `hub.boot()` em segundo plano e o `/health` devolve `subida` (etapa, segundos, carregando, tipo do erro). `stop` não salva base nem fantasmas com a carga pela metade. Mostrar o `/health` é o jeito de diagnosticar a subida sem o Portainer.
- 0.32.122: reenvio da 0.32.121. A queda de 01/11/2026 (404, tarefas `rejected`, deploy vermelho nas 0.32.119 a 0.32.121) foi disco cheio no servidor, confirmado pelo Bruxo; não foi a subida lenta, que levou 66,7 s (a suspeita da 0.32.120 não se confirmou). Deploy vermelho com testes, banco e imagem verdes = olhar o servidor, não o código.
- 0.32.123 (pedido do dono): `PumpFun.tabs` + `GET /api/pump/result-tabs?real=` (só quando a janela abre, nunca no snapshot); tabela `#ovA` na janela Resultado (`loadOvAbas`) e janela da aba (`openOvAba`, `data-ovaba`, textos em `ABA_INFO`). Aba nova ganha uma linha em `ABA_INFO`. `tests/test_periodos.py`.
- 0.32.124 (pedido do dono, etapas 1 a 5 do plano do Top traders): `app/toplab.py` (`study`, `traders`, `late`, `Barred`); `PumpFun._late_note` (`p["late"]`, `tr["late"]`), `_top_barred` + `top_hook` → `hub.top_note`, `top_tick`/`top_loop` (30 s, máx. 20 abertas, 15 min) → tabela `top_shadows` (migração `20261101000002`), `hub.top_lab` + `GET /api/pump/top-lab` (admin); cartão `#tlK` em Top traders (`loadTopLab`). Só mede; o botão Pausar usa `/api/pump/wallets`. A cópia fictícia entra no preço do trader (`px` em `_copy`), por isso a conta de entrada atrasada. Relatório `app/relatorios_ia/2026-11-01-0.32.124.md`. `tests/test_top_lab.py`.
- 0.32.125 (pedido do dono): janelas Resultado e da aba com `OV_CONTA`/`ovConta` (Investido, Ganhou, Perdeu, Resultado total = investido + saldo, %). O cartão de dentro da janela que era "Resultado total" (lucro) virou "Lucro total", para não confundir.
- 0.32.126 (pedido do dono): `PumpFun.tabs` traz `motivos[].itens` (até `TAB_ITENS`=60, mais recentes primeiro); `ovMot` e `data-ovmot` fazem as abas de motivo em `#ovAMt`/`#ovAM`.
- 0.32.127 (pedido do dono): menu `#abas` (`#navAbas`, admin) com `ABAS_TR` em `web/app.js` (aba, chave de compra, chave REAL, tela), `loadAbas`, `data-abafoco`, `#abOff`, `#abUndo` (`localStorage` `pf_abas_antes`). `pump_top_on` e `pump_st_copy_on` (ligadas) + `PumpFun.TAB_SWITCH`/`tab_off` em `_copy`. Aba nova que compra = linha em `ABAS_TR`. A tela nunca mexe nas chaves REAL. Relatório `app/relatorios_ia/2026-11-01-0.32.127.md`.
- 0.32.128 (pedido do dono): migração `20261101000003` anula o ganho falso do PEPE (fictícia, 29–30/10, +1.900% ou mais; todas as contas): resultado zero, original em `data->'corrigido'`, trade REAL fora. Relatórios já gravados (`daily_report`, `result_studies`) continuam com o número antigo. `tests/test_periodos.py`.
- 0.32.129 (pedido do dono): Abas de trades → `#abPn` (`abasPanel`, `ABAS_OPT`, `ABAS_TOPX`, `cfgCtl`, `data-abaopen`): cópias `data-clone` dos campos de cada tela, tiradas de `cfgItems()`; chaves com real/jito ficam fora. Aba nova = linha em `ABAS_TR` e em `ABAS_OPT`.
- 0.32.130 (pedido do dono: sem rolagem lateral): `table()` põe `data-l` (nome da coluna) em cada `td`; `labelTables` (MutationObserver) faz o mesmo nas tabelas montadas fora dela; `fitTables` põe `tcard` na tabela que não cabe no quadro (PC). CSS no fim de `web/app.css`: texto quebra linha; até 860 px toda tabela vira cartão; tabela que nunca deve virar cartão leva a classe `nocard`. Conferir sempre em 1440 e 390 px (Playwright) sem rolagem lateral.
- 0.32.131 (opção B aprovada pelo dono no PDF): tela `#abas` em quadrados (`abasDraw`, `abaBox`, `#abGrid`, `.abc`; `abasSync` no `render` redesenha quando uma chave muda) e janela Ajustes no `#jtM` (`openAba`, `abaRows`, `ABM`, abas `ABA_TAB`, ordem `ABA_ORD`, dicas `ABA_DICA`). Trocou `#abT`/`#abPn`. `abaTabOf` separa Saída, Entrada e Valores pelo nome da chave.
- 0.32.132 (pedido do dono): Abas de trades: as desligadas usam `abaBox` com `.abc.off`, sem as pílulas.
