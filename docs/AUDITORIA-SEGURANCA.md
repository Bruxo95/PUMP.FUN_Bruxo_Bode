# Auditoria de segurança — PUMP FUN COPY

## Identificação da auditoria

- ID: `AUD-2026-10-25-0.8.2-1cec6a0`; revisão do relatório: **1.0**.
- Versão da aplicação auditada: **0.8.2**.
- Commit auditado: `1cec6a04dfe076be8ddbad5258359d2afb225f38`.
- IA responsável: **OpenAI Codex, família GPT-6**. Identificador exato do modelo/revisão
  não exposto nesta sessão; não foi inferido a partir de configurações de outros chats.
- Manifesto comum dos relatórios e evidências: `auditoria/2026-10-25/identificacao-auditoria.json`.

## Estado e ponto de retomada

- Data: **2026-10-25**, Europe/Dublin.
- Estado: **revisão do repositório concluída; remediação não iniciada**.
- Base: `1cec6a04dfe076be8ddbad5258359d2afb225f38`, aplicação **0.8.2**.
- Resultado: **11 achados abertos: 1 alto condicional, 7 médios, 3 baixos**.
- Última etapa: revisão manual, scanners, reproduções offline e consolidação.
- Próxima ação: corrigir **SEC-02 (bloqueio concorrente)** e **SEC-03 (RPC/SSRF)** com regressões.
- Antes de uso real: resolver **SEC-01 (assinatura)** e **SEC-04 (ordens pendentes)**, além dos riscos de persistência.
- Aplicação, workflows, banco e servidores não foram alterados; versão do produto permanece 0.8.2.
- A fase técnica não fez commit/push, deploy, login real, acesso administrativo ou transação real.
- Publicação posterior: commit e push destes documentos autorizados pelo usuário em 2026-10-25,
  mantendo os 11 achados abertos e as correções para a próxima etapa. O commit de publicação
  não altera a identificação do código auditado; consultar o histórico Git deste relatório.

## Remediação 1 — SEC-01 a SEC-04 (2026-10-25, aplicação 0.9.1)

- IA: Claude Code, modelo Claude Opus 5.5 (`claude-opus-5-5`). Base: main com a 0.9.0 do remoto (top traders online).
- **SEC-01 — corrigido no código, aguardando CI:** `app/txguard.py` confere a mensagem antes de assinar
  (única assinante/pagadora, lista fechada de programas, sem transferência/approve/troca de autoridade de token,
  fechamento só para a própria carteira, máximo da compra e entrada da Jupiter dentro do pedido, tetos de
  taxa para terceiros, prioridade, aluguel e contas novas). Ligado em `PumpReal._tx` e `JupiterWallet._swap_tx`.
  Falha fechada: rotas Jupiter v2/ExactOut e programas fora da lista são recusados — validar no primeiro teste
  real com carteira nova e pouco saldo. Regressão: `tests/test_seguranca.py` (caso dos 9 SOL: zero envios).
- **SEC-02 — corrigido no código, aguardando CI:** carga do motor e bloqueio usam a mesma trava; a carga confere
  o bloqueio antes de publicar; rotas de real/troca/venda/chave conferem de novo antes de agir (403).
- **SEC-03 — corrigido no código, aguardando CI:** RPC pessoal só HTTPS na 443, sem userinfo, sem IP/nome interno
  ao salvar; DNS conferido antes de cada uso (cache 60 s). RPC salvo antes da regra e agora inválido é ignorado
  (usa o público). Pendência de infraestrutura: bloquear saída para rede interna no ambiente (DNS rebinding).
- **SEC-04 — corrigido no código, aguardando CI:** "pendente" passa por reconciliação (assinatura no histórico ou
  blockhash vencido) antes de qualquer nova tentativa; compra/venda não trocam de rota enquanto pendentes; a
  assinatura fica gravada na posição (`sell_pending`) e segura nova venda por até 5 min, inclusive após reiniciar.
- Validação local: lógica do `txguard` e da reconciliação com 20 casos em Python padrão; validação de RPC com
  17 endereços. **pytest não rodou nesta máquina** (sem dependências; regra de não instalar no Windows).
  Suíte completa passou no GitHub Actions (commit eb27091) e a 0.9.1 está no ar. SEC-05 a SEC-11 seguem abertos.

## Remediação 2 — SEC-05 a SEC-11 (2026-10-25, aplicação 0.9.2)

- IA: Claude Code, modelo Claude Opus 5.5 (`claude-opus-5-5`). Base: commit `9272186` (0.9.1).
- **SEC-05 — corrigido no código:** atualizar o ranking pelo painel tem intervalo de 60 s por conta e, com a
  chave do sistema, no máximo 6 consultas por minuto somando todas as contas (`refresh_leaderboard_user`).
  Limite de tamanho das listas manuais não foi alterado (segue como observação).
- **SEC-06 — corrigido no código:** token recusado fica lembrado por 60 s (falha de rede não); lista de chaves
  públicas vazia fica guardada 1 min e a recarga forçada por "kid" desconhecido acontece no máximo 1x por minuto.
- **SEC-07 — já corrigido** pelo commit `28b0465` (0.8.4, outra IA): o deploy exige a versão nova no `/health`;
  confirmado na publicação da 0.9.1.
- **SEC-08 — corrigido no workflow:** `concurrency` com `cancel-in-progress` — um envio novo cancela o anterior,
  então um run antigo não republica `latest` depois do novo.
- **SEC-09 — corrigido:** usuário/senha na URL do RPC são recusados desde a 0.9.1 (SEC-03); a 0.9.2 também passa
  a mostrar só o nome do servidor (`hostname`), mesmo para URL antiga.
- **SEC-10 — corrigido:** erros do RPC externo e do monitor entram escapados nos cartões do painel (`web/app.js`).
- **SEC-11 — corrigido:** `1e1000`/`nan`/infinito viram erro de validação (configurações e troca USDC→SOL).
- Regressões em `tests/test_seguranca.py`. pytest não rodou nesta máquina; a suíte roda no Actions no push.
- Fora do código, ainda pendente: bloquear saída do container para a rede interna e proteger o branch `main`.

`AGENTS.md` indica este relatório; `CLAUDE.md` mantém somente o resumo compartilhado.
Ao retomar, conferir o Git e comparar com a base antes de usar linhas ou reproduções.
Atualizar esta seção e a tabela de achados após cada etapa relevante e antes de
encerrar uma tarefa. Não registrar segredos reais ou dados de outros usuários.

**Conclusão:** as proteções existentes são úteis, mas esta auditoria não aprova o
projeto para operar com dinheiro real. O achado alto depende de comprometimento
da resposta de um builder; não se demonstrou comprometimento de provedor ou
retirada de fundos. Revisar o código não certifica VPS/cloud nem ausência de falhas desconhecidas.

## Escopo, método e limitações

Revisados: autenticação/JWT/OAuth, autorização/administração, isolamento entre contas,
PostgREST e três migrações/RLS, criptografia/logs/segredos/persistência, carteiras e
assinatura/confirmação de transações, integrações/monitor, frontend/CSP, dependências,
Docker/Compose/Swarm e GitHub Actions. Relatórios por área preservam linhas, cenários,
pré-condições e recomendações detalhadas.

Métodos: leitura manual por áreas independentes, suíte existente, Bandit, pip-audit,
Gitleaks no histórico local completo, OSV para seis pacotes JS, provas locais com
MockTransport/ASGITransport/FakeREST, quatro consultas públicas ao site e metadados GitHub.

Não cobertos: pentest autenticado/carga em produção, VPS/SSH/Portainer/Supabase
administrativo, valores de segredos, backups/restauração, SBOM/imagem e pacotes do SO,
rede/egress/MFA/provedores efetivos, fundos/transações reais. Não se exploraram redes
internas reais. Os cinco testes PostgreSQL/RLS foram pulados no Windows e devem ser
executados em Linux com PostgreSQL; banco falso e leitura de SQL não os substituem.

Severidades qualitativas consideram impacto e pré-condições; não são pontuações CVSS.
Endurecimentos e riscos arquiteturais estão separados dos 11 achados.

## Checklist

- [x] Identificar base, sincronizar clone e criar registro de retomada.
- [x] Suíte existente: **61 passaram, 5 pulados, 1 aviso**.
- [x] Python: **34 versões locais consultadas; 0 vulnerabilidades conhecidas, 0 pacotes pulados**.
- [x] JS: OSV consultado para Supabase JS e cinco dependências diretas exatas, **0 advisories**.
- [x] Bandit: **3.970 linhas, 20 avisos brutos (0 altos, 1 médio, 19 baixos), triados**.
- [x] Gitleaks: **15 commits alcançáveis, clone não raso; 1 dado fictício, 0 segredos reais confirmados**.
- [x] Revisar autenticação, autorização, banco/RLS, segredos, persistência e administração.
- [x] Revisar integrações, RPC/SSRF e execução sem broadcast.
- [x] Revisar frontend, OAuth, HTML, containers, CI/CD e supply chain.
- [x] Reexecutar independentemente as três provas locais e consolidar evidências.
- [x] Registrar conclusão, prioridades e ponto de retomada.
- [ ] Aplicar correções e adicionar regressões que exijam comportamento seguro.
- [ ] Executar cinco testes PostgreSQL/RLS em Linux isolado.
- [ ] Completar checklist de infraestrutura com o responsável e autorização específica.

## Achados e acompanhamento

Todos permanecem **abertos**; nenhuma evidência abaixo demonstra ataque em produção.

| ID | Severidade | Problema | Referência detalhada |
|---|---|---|---|
| SEC-01 | Alta, condicional | Assinatura sem validar a intenção da transação upstream | CAR-02 |
| SEC-02 | Média | Requisição pendente recria motor de conta bloqueada | AUTH-01 |
| SEC-03 | Média | RPC pessoal aceita destinos internos, SSRF HTTPS | CAR-01 |
| SEC-04 | Média | Nova venda antes de reconciliar assinatura pendente | CAR-03 |
| SEC-05 | Média | Ranking forçado consome chave compartilhada sem limite | AUTH-02 |
| SEC-06 | Média | Tokens inválidos amplificam consultas de autenticação | AUTH-03 |
| SEC-07 | Média | Deploy considera saudável uma versão antiga | CI-01 |
| SEC-08 | Média | Runs concorrentes podem sobrescrever latest com versão antiga | CI-02 |
| SEC-09 | Baixa | Credenciais da URL RPC voltam na API do próprio usuário | CAR-04 |
| SEC-10 | Baixa | Erro de RPC externo é inserido como HTML | WEB-01 |
| SEC-11 | Baixa | Número fora do domínio provoca HTTP 500 | AUTH-04 |

### SEC-01 a SEC-04 — assinatura, bloqueio, RPC e reconciliação

- **SEC-01:** `app/pumpfun.py:1938-1953`, `app/jupiter.py:174-191`. O builder falso
  devolveu transferência SystemProgram de **9 SOL** para pedido de compra de **0,05 SOL**;
  houve assinatura válida, com chaves descartáveis, blockhash zero e **zero broadcasts**.
  Exige comprometimento/controle da resposta de PumpPortal/Jupiter; não foi encontrada
  rota para outro usuário submeter arbitrariamente uma transação. Validar programas,
  instruções, mints, destinos/autoridades, Address Lookup Tables, débitos e taxas antes
  de assinar, rejeitando mensagens desconhecidas. Simulação é apenas defesa adicional.
- **SEC-02:** `app/hub.py:68-97,224-237,278-289`, `app/api.py:53-74`, `app/monitor.py:47-78`.
  Uma carga de motor iniciada antes do bloqueio termina depois e recoloca o usuário no
  monitor, embora novas chamadas recebam 403. A prova usou rotas reais locais e dados
  fictícios. Serializar carga/bloqueio no mesmo lock, invalidar cargas pendentes e
  conferir o perfil antes de publicar o motor e executar ações sensíveis.
- **SEC-03:** `app/solana_wallet.py:34-38`, `app/api.py:224-240,135-144`, `app/jupiter.py:140-167`.
  Só se exige prefixo HTTPS. Destino loopback foi aceito e recebeu três POSTs mockados.
  O corpo JSON-RPC é definido pelo código, TLS permanece validado e redirects não são
  seguidos. Exploração interna real depende de destino alcançável com TLS aceito;
  não se demonstraram metadados HTTP nem vazamento service-role. Aplicar política de
  host/porta, negar userinfo e endereços privados/loopback/link-local/reservados,
  validar DNS ao conectar e restringir saída no ambiente.
- **SEC-04:** `app/pumpfun.py:1915-1936,2031-2075`. Após `pendente` e saldo ainda antigo,
  o código constrói outra transação; modelo offline produziu duas vendas de 50% e
  saldo final 250/1000, em vez de 500. Efeito on-chain depende de confirmação tardia,
  validade do blockhash e consistência do RPC. Persistir intenção/assinatura/blockhash
  e reconciliar confirmação ou expiração antes de reconstruir, inclusive após reinício.
  O reenvio interno da mesma assinatura não foi classificado como duplicação.

### SEC-05 a SEC-08 — disponibilidade e integridade da entrega

- **SEC-05:** `app/api.py:199-209`, `app/pumpfun.py:511-519,588-605`: três pedidos
  autenticados de ranking geraram três consultas mockadas com chave compartilhada,
  ignorando o cache. Adotar cooldown/cota por conta, limite global e deduplicação.
  Limitar também listas manuais/motores; controles do proxy não foram inspecionados.
- **SEC-06:** `app/auth.py:33-43,68-78,85-101`: dois tokens falsos com kid desconhecido
  foram rejeitados, mas geraram seis consultas mockadas. Cachear resultados negativos,
  limitar recargas JWKS/tentativas e deduplicar chamadas. **Não é bypass de JWT**;
  não houve teste de carga em produção.
- **SEC-07:** `.github/workflows/imagem.yml:64-68` aceita qualquer health com `ok:true`,
  sem conferir versão/SHA; imagem antiga saudável pode produzir falso sucesso.
  Expor revisão e exigir a revisão esperada na confirmação.
- **SEC-08:** `.github/workflows/imagem.yml:42-44` publica tag mutável `latest` sem
  serialização/checagem de HEAD. Run antigo pode terminar depois do novo e rebaixar
  a tag. Usar concorrência controlada, impedir entregas obsoletas e preferir SHA/digest.
  Não se provocou rollback em produção.

O último Actions consultado estava verde, mas os passos de webhook e conferência
de versão foram **pulados**, executando o aviso de webhook ausente. Isso não confirma
automação ativa. Ver `auditoria/2026-10-25/github-configuracao.json`.

### SEC-09 a SEC-11 — exposição e validação

- **SEC-09:** `app/solana_wallet.py:66-69`: `split('/')[2]` preserva `usuario:senha@`.
  Senha fictícia retornou em `rpc_host` para o próprio usuário. Rejeitar userinfo ou
  retornar apenas hostname/porta. Não se demonstrou leitura por terceiros.
- **SEC-10:** `app/jupiter.py:140-167` → `web/app.js:311,48`: erro externo entra em
  innerHTML sem escape. Markup foi confirmado; requer RPC malicioso/comprometido do
  usuário. **Não se demonstrou execução JavaScript**; CSP bloqueia handlers inline.
  Usar saída de texto/escape; revisar também RP.error e campos numéricos externos.
- **SEC-11:** `app/settings.py:131-143`, `app/api.py:109-116`: `pump_max_open="1e1000"`
  gerou OverflowError/500 genérico, sem queda ou vazamento demonstrado. Usar schemas,
  finitude, limites de campo/corpo e resposta 4xx de validação.

## Evidências e reprodução

Pasta [`auditoria/2026-10-25/`](auditoria/2026-10-25/):

| Arquivo | Conteúdo |
|---|---|
| `revisao-auth-db.md` | AUTH-01 a AUTH-04; cenários, linhas, pré-condições e recomendações |
| `revisao-carteiras-integracoes.md` | CAR-01 a CAR-04; fronteiras de confiança e limitações |
| `revisao-web-entrega.md` | WEB-01, CI-01/02; análise frontend/entrega e consulta OSV |
| `triagem-scanners.json` | versões e classificação manual dos scanners |
| `pacotes-testados.json`, `pip-audit.json` | inventário local de 34 versões e consulta PyPI |
| `bandit.json` | 20 avisos brutos em 3.970 linhas de app/ |
| `gitleaks.json`, `gitleaks-ferramenta.json` | resultado sanitizado, ferramenta oficial/checksum conferido |
| `verificacao-publica.json` | versão 0.8.2, cabeçalhos e duas rotas sem login retornando 401 |
| `github-configuracao.json` | repositório privado, main sem proteção, passos do último workflow |
| `identificacao-auditoria.json`, `README.md` | versão, SHA, IA, estado e associação dos arquivos brutos à auditoria |
| `reproduzir-auth-db.py`, `poc-carteiras.py`, `poc-web-render.cjs` | provas exclusivamente locais |

Gitleaks 8.30.1 varreu 15 commits alcançáveis de clone não raso. O único resultado é
string deliberada de teste de mascaramento em `tests/test_admin.py:86`, commit
`2bc642c`, sem credencial real confirmada. Campos Secret/Match/Author/Email/Message
foram removidos da evidência preservada. Não foram criadas exceções globais.

Bandit 1.9.4: B107 é default de segredo vazio configurável, não senha real embutida;
B104 é bind esperado no container; 18 B110/B112 indicam catches silenciosos que
exigem revisão de falhas, não 18 vulnerabilidades. Não há achado alto do scanner.

pip-audit 2.10.1 consultou PyPI para as 34 versões locais, incluindo dependências de
teste, sem advisories ou pacotes pulados. OSV retornou zero nos seis pacotes Supabase
JS 2.118.0 listados no relatório web. Isso não cobre todo bundle/transitivas, resolução
Linux, imagem de produção ou SO, nem detecta malware/falhas desconhecidas.

Comandos, na raiz, com dependências normais e pytest num ambiente isolado:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -u docs\auditoria\2026-10-25\reproduzir-auth-db.py
.\.venv\Scripts\python.exe -u docs\auditoria\2026-10-25\poc-carteiras.py
node docs/auditoria/2026-10-25/poc-web-render.cjs
```

**Exit 0 nos reprodutores confirma a falha do baseline, não aprovação de segurança.**
Não substituir mocks por rede real. Após correção, criar regressões que exijam
comportamento seguro; os asserts atuais devem deixar de confirmar a falha.

Scanners em ambiente temporário separado (`<audit-python>`):

```text
<audit-python> -m bandit -r app -f json -o bandit.json
<audit-python> -m pip_audit --path .venv/Lib/site-packages --progress-spinner off --format json --desc on --aliases on --output pip-audit.json
gitleaks git --redact=100 --report-format json --report-path gitleaks.json --log-opts=--all --no-banner .
```

## Riscos arquiteturais e endurecimentos, sem exploração demonstrada

1. **Custódia/persistência:** servidor pode abrir chaves para assinar; AES-GCM não
   protege contra comprometimento do processo/chave mestra. A fila SupabaseStore é
   volátil e descarta o item mais antigo após 20.000 (`app/db.py:107-110`); o motor
   segue quando o banco falha e audit log não bloqueia ações em falha. Antes de uso
   real: durabilidade, reconciliação, backpressure e bloqueio de novas operações se
   estado não puder ser preservado. Não se provocou perda financeira.
2. **Admin/provedores:** primeiro cadastro vira admin por design; provisionar instalação
   vazia/restaurada por canal confiável. Fallback do backend não deve criar novo admin
   por contagem. Regra de login apenas Google depende de provedores Supabase efetivos.
3. **Recursos:** revisar cotas de listas/motores/corpos/segredos e crescimento do registro
   de redação de logs, além de limites de borda; não presumir ausência de controles externos.
4. **Supply chain:** Python sem lock/hashes, Actions por tags e base Docker mutável
   permitem resoluções diferentes entre teste e imagem. Fixar versões/digests revisados,
   adicionar SCA/SAST/segredos/imagem ao CI. Esta rodada não instalou workflow ou automação periódica.
5. **GitHub:** API retorna main `protected=false`; avaliar revisão/checks obrigatórios.
   Restringir packages:write ao job de imagem. Políticas extras/default token/Dependabot
   e secret scanning não ficaram visíveis pela consulta; não se concluiu seu estado.
6. **Containers/rede:** UID 10001 já existe; stack não declara limites de CPU/memória,
   filesystem somente leitura, remoção de capabilities ou rede exclusiva. Configuração
   efetiva de VPS/Swarm precisa ser verificada pelo responsável.
7. **Navegador:** CSP/nosniff/proteção de frames/referrer policy presentes. HSTS e
   Permissions-Policy não observados na resposta pública. Avaliar HSTS no proxy após
   confirmar HTTPS. Sessão persistente do SDK exige prevenção de XSS; não houve roubo de sessão demonstrado.
8. **Saídas/carteira:** venda e swap manual são independentes de desativar novas compras
   reais; não classificados como bypass por isso. Motor impede duas posições reais
   normais no mesmo mint. Saldos externos/airdrop exigem reconciliação e carteira dedicada.

## Proteções observadas sem bypass demonstrado

- JWT confere assinatura/issuer/audience/expiração e restringe algoritmos; tokens falsos foram rejeitados.
- Rotas usam identidade do token; não se demonstrou IDOR/leitura de outra conta; admin é verificado no backend.
- SQL define RLS, revoga escrita de browser e restringe valores cifrados e app_secrets.
- AES-GCM usa nonce aleatório/AAD por usuário e campo; testes de transplante de cifra falham.
- Chave privada não vai ao builder; há máscara de logs e separação de chaves do sistema/pessoais.
- Novas compras reais começam desligadas e exigem carteira, confirmação e trava geral liberada.
- OAuth PKCE, SRI/versionamento da biblioteca, escape da maioria dos textos, container sem root.
- Não se encontrou workflow pull_request_target executando código de contribuição externa.

## Ordem de correção e encerramento futuro

1. SEC-02/03 com regressões concorrentes e de destinos proibidos, sempre offline.
2. SEC-05/06 com cotas/cooldown/cache/deduplicação e limites de listas/payloads.
3. SEC-01/04 e durabilidade, obrigatórios antes de dinheiro real; rejeitar assinatura
   inesperada antes de transmitir e reconciliar intenções após falha/reinício.
4. SEC-07/08: identidade da revisão e serialização/obsolescência de entregas.
5. SEC-09/10/11: remover userinfo, escapar erros e validar entradas tipadas.
6. RLS em Linux/Postgres; repetir scanners/testes no novo commit e registrar correção por ID,
   commit, evidência e limitações. Não marcar corrigido apenas porque código foi alterado.

Para ampliar à produção, combinar com o responsável: provedores/redirect URLs/MFA,
RLS/grants efetivos, acesso à chave mestra/segredos sem expô-los, TLS/egress/rede,
Portainer, backups/restauração, imagem/SBOM, quotas/alertas, proteção de branches e
política Actions. Esses itens permanecem pendentes; não se acessou essa infraestrutura.

## Fontes primárias de apoio

- [OWASP: prevenção de SSRF](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html).
- [OWASP API4: recursos](https://owasp.org/API-Security/editions/2023/en/0xa4-unrestricted-resource-consumption/).
- [Solana: envio e confirmação](https://solana.com/docs/rpc/http/sendtransaction).
- [GitHub: concorrência](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency).
- [PyPA: alcance e limites de pip-audit](https://github.com/pypa/pip-audit).
- [Gitleaks: repositório oficial](https://github.com/gitleaks/gitleaks).

## Histórico de continuidade

| Data | Etapa | Próxima ação |
|---|---|---|
| 2026-10-25 | Base sincronizada, memória/checklist criados | Revisões e scanners |
| 2026-10-25 | 61 testes passaram/5 pulados; scanners triados | Consolidar provas |
| 2026-10-25 | 11 achados e reproduções revisados; relatório concluído | SEC-02/03; SEC-01/04 bloqueiam aprovação para uso real |
| 2026-10-25 | Identificação de versão/SHA/IA em cada revisão e preparação da publicação solicitada | Commit/push dos documentos; depois iniciar correções |
| 2026-10-25 | Remediação 1: SEC-01..04 no código (0.9.1), regressões em tests/test_seguranca.py | CI verde, 0.9.1 no ar; próximo SEC-05/06 |
| 2026-10-25 | Remediação 2: SEC-05..11 (0.9.2); SEC-07 já resolvido na 0.8.4 | Confirmar CI; pendências de infraestrutura |
| 2026-11-12 | Revisão 2 (PUMP FUN, BNB, Robinhood, Dormant) sobre 0.32.325, SHA 6479fc6; Claude Opus 5.5 | Achados abaixo; corrigidos na 0.32.326 |

## Revisão 2 (2026-11-12, aplicação 0.32.325, SHA `6479fc6d62f22bcfada20d6c1a9aaf7482647f4c`)

IA: Claude Opus 5.5 (`claude-opus-5-5`). Escopo: os quatro painéis deste repositório (`/app`, `/bnb`, `/hood`, `/dormant`) e o site no ar.
Só leitura do código, do Git e do site público; nenhum acesso a servidor, banco ou carteira.

O que foi conferido e passou:
- Rotas: todas as `/api/*` dos quatro painéis exigem login; as da BNB, Robinhood e Dormant são só admin; carteiras e compras do
  Dormant (`own`) recusam o "Visualizar tela"; o "Visualizar tela" só aceita GET e bloqueia chaves, registro e Administração.
  No ar: `/api/me` e `/api/hood` sem login respondem 401.
- Segredos: nenhuma chave, token ou `api-key=` no código nem no histórico do Git; `logsafe` esconde chaves nos logs; nenhuma rota
  devolve chave (só "configurada" ou rótulo curto).
- Banco: as 75 tabelas das migrações têm RLS ligado; nenhuma política ou permissão deixa o navegador gravar.
- Filtro por conta: atualizações e apagamentos levam `user_id`; os relatórios lidos por id sem conta (`trader_reports`,
  `result_studies`) são da Base geral, de propósito para os admins.
- Dinheiro real: a trava `PUMP_REAL_ALLOWED` vale na Solana, BNB, Robinhood (compra e abastecer) e Dormant (compra, venda, gás e
  exchanges). Exchanges sem código de saque.
- Dependências: 36 pacotes Python fixados em `constraints.txt` + supabase-js 2.118.0 sem vulnerabilidade conhecida no OSV
  (consulta de 12/11/2026). Todas as páginas carregam o supabase-js com SRI.

Achados (baixos) e correção na 0.32.326:
- R2-01: o `script-src` liberava o jsDelivr inteiro em `/app`, `/hood`, `/bnb`, `/entrar`, `/sala` e `/` (só o `/dormant` era
  restrito), e `/hood` e `/bnb` também recebem chave privada. Agora todas as páginas aceitam só o caminho exato do supabase-js.
- R2-02: faltavam `Strict-Transport-Security` (agora 1 ano, sem subdomínios) e `Permissions-Policy` (câmera, microfone, localização,
  pagamento e USB desligados).

Ficam como observação, sem mudança: o "Visualizar tela" de um admin olhando outro admin abre as telas só de leitura dele na BNB e
na Robinhood (é o que a função faz); algumas leituras (Raio-X com `novo=1`, Relatório do dia) gastam créditos ou gravam o
resumo, só para admin. Infraestrutura (Portainer, VPS, Supabase remoto) não foi vista nesta revisão.
