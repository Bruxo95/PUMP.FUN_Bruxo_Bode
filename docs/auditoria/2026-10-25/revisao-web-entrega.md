# Revisão de frontend e entrega — 2026-10-25

ID da auditoria: `AUD-2026-10-25-0.8.2-1cec6a0`; revisão do relatório 1.0.
IA: OpenAI Codex, família GPT-6; identificador exato do modelo/revisão não exposto nesta sessão.
Manifesto de identificação: `identificacao-auditoria.json`, nesta pasta.

Baseline: commit `1cec6a04dfe076be8ddbad5258359d2afb225f38`, versão `0.8.2`.
Análise estática e provas locais; nenhum acesso a servidores, banco remoto, conta Google,
webhook de deploy ou transação real foi feito por esta revisão.

## Cobertura

- `web/common.js`, `landing.js`, `app.js`, HTMLs e referências externas.
- Cabeçalhos/CSP de `app/api.py`, fronteiras de dados de `app/jupiter.py` e `app/pumpfun.py`.
- `Dockerfile`, `.dockerignore`, `.gitignore`, `docker-compose.yml`, stack Swarm,
  `.github/workflows/imagem.yml`, manifesto Python e presença de lockfiles.
- Consulta pública OSV para a biblioteca npm Supabase e suas cinco dependências diretas exatas.

## WEB-01 — Erro de RPC é inserido como HTML

**Baixa; confirmado localmente; condicionado a provedor RPC malicioso/comprometido.**

- Origem: `app/jupiter.py:140-167` aceita `error.message` do RPC definido pelo usuário e retorna
  esse texto em `sol_balances().error`.
- Caminho: `web/app.js:311` usa `w.error` como descrição do cartão e `web/app.js:48` coloca a
  descrição em `innerHTML` sem `esc()`.
- Pré-condições: usuário configurou carteira e RPC externo sob controle de adversário, ou seu
  RPC foi comprometido. Normalmente afeta a sessão do próprio usuário desse RPC.
- Impacto demonstrado: inclusão de marcação arbitrária na interface, permitindo conteúdo enganoso
  ou links. **Não foi demonstrada execução de JavaScript, roubo de sessão ou escalada entre usuários.**
  A CSP bloqueia handlers inline, portanto esta prova não deve ser descrita como XSS executável comprovado.
- Prova: `poc-web-render.cjs` injeta somente `<b data-audit-probe="1">RPC error</b>` em um mock de
  erro e confirma sua presença sem escape no HTML gerado. O script não faz requisições.
- Correção sugerida: escapar `w.error` antes do cartão ou separar APIs de texto/HTML no renderer;
  revisar igualmente `RP.error` usado em `web/app.js:169`.

Defesa adicional: campos esperados numéricos de Solana Tracker (`tokens`, `days_active`, `trades`)
são retornados sem conversão em `app/pumpfun.py:557-559` e escritos via `String()` em
`web/app.js:247-248`. A prova local confirma marcação se o provedor devolver texto nesses campos.
Não foi identificado caminho para um usuário comum alterar os contadores no provedor oficial;
tratar como validação de fronteira externa, sem alegar exploração arbitrária em produção.

Comando executado na raiz:

```text
node docs/auditoria/2026-10-25/poc-web-render.cjs
```

Saída esperada/observada:

```json
{"probe":"rpc_error_is_inserted_as_html","confirmed":true}
{"probe":"leaderboard_render","nameEscaped":true,"numericFieldsMarkup":true}
```

## CI-01 — Verificação de deploy aceita versão antiga

**Média; condição lógica confirmada no workflow; deploy real não acionado.**

Em `.github/workflows/imagem.yml:64-68`, o job considera concluído o deploy se `/health` contiver
`"ok":true`. Não compara a versão nem o SHA da imagem publicada. Uma instância antiga saudável
responde a essa condição durante atualização atrasada, falha de pull ou rollback; o workflow pode
anunciar sucesso sem que o código corrigido esteja publicado. O endpoint em `app/api.py` retorna
`VERSION`, mas o workflow não usa esse valor.

Recomendação: expor também a revisão Git na imagem e em `/health`, e comparar com o commit esperado,
com falha explícita caso a versão esperada não apareça. Não basta validar disponibilidade HTTP.

## CI-02 — Corrida entre pushes pode republicar imagem antiga como latest

**Média; risco de integridade da entrega inferido diretamente da configuração.**

Todos os runs publicam `:latest` em `.github/workflows/imagem.yml:42-44`; não existe `concurrency`,
serialização nem verificação de que o commit ainda é o HEAD de `main`. A stack usa essa tag mutável
em `deploy/portainer-stack.yml:5`. Com dois pushes próximos, o run antigo A pode terminar depois de B,
sobrescrever `latest` e chamar o webhook. O teste de CI-01 tampouco detecta o rollback.

Não foi provocado rollback em infraestrutura real. Recomendação: ordenar/cancelar entregas antigas,
rever se o SHA ainda é o atual antes de publicar/implantar e preferir implantação pela tag SHA ou digest.

## Endurecimentos recomendados, sem comprometimento demonstrado

1. **Cadeia de suprimentos:** `requirements.txt:1-7` usa faixas amplas, sem lock/hashes;
   `Dockerfile:1` usa base mutável e `:7` resolve dependências de novo. Testes e imagem podem usar
   resoluções diferentes. Actions em `imagem.yml:18-19,29-31,38` usam tags mutáveis. Fixar versões/digests
   revisados e implementar atualização controlada, auditoria de dependências e varredura de imagem.
2. **Privilégio mínimo de CI:** `packages: write` está no nível global (`imagem.yml:10-12`), alcançando
   também testes e deploy. Restringir escrita de pacotes ao job `imagem`. Não foi constatado uso indevido.
3. **Isolamento do container:** já roda como UID 10001. A stack não declara filesystem somente leitura,
   `cap_drop`, `no-new-privileges` nem limites de CPU/memória, e usa rede compartilhada `vpsrachar`.
   Avaliar recursos e rede específica com o responsável; configuração efetiva da VPS não foi verificada.
4. **CSP:** restringe scripts e bloqueia inline, porém permite todo `cdn.jsdelivr.net`; reduzir para
   self-hosting ou política mais estrita pode diminuir o impacto de futura injeção HTML. O script Supabase
   atual tem versão fixa, SRI e `crossorigin`, uma proteção já existente. Ausência de HSTS não foi
   inferida apenas do código: pode estar configurado no proxy, fora do escopo desta revisão.
5. **Sessão no navegador:** `persistSession: true` em `web/common.js:15` usa o armazenamento padrão do
   SDK no navegador; não é vulnerabilidade isolada, mas um eventual XSS teria acesso à sessão. Não há
   evidência de XSS executável confirmado nesta revisão.

## Consulta de advisories do JavaScript

Em 2026-10-25 foram consultados metadados públicos de npm e
`POST https://api.osv.dev/v1/querybatch` para:

| Pacote npm | Versão | Advisories retornados |
|---|---|---|
| `@supabase/supabase-js` | `2.118.0` | 0 |
| `@supabase/auth-js` | `2.118.0` | 0 |
| `@supabase/storage-js` | `2.118.0` | 0 |
| `@supabase/realtime-js` | `2.118.0` | 0 |
| `@supabase/functions-js` | `2.118.0` | 0 |
| `@supabase/postgrest-js` | `2.118.0` | 0 |

Resultado limitado aos seis pacotes/versões consultados e à base no momento da consulta.
Não equivale a provar ausência de vulnerabilidades em todo o bundle, dependências transitivas,
serviço Supabase hospedado, Google OAuth, imagem/container ou sistema operacional da VPS.

## Proteções observadas

- PKCE no cliente OAuth, token Bearer e chamadas de API somente para caminhos internos definidos.
- Nomes, símbolos, motivos, logs, e-mails e avatares em contextos HTML geralmente passam por `BB.esc`;
  erro de OAuth da URL é exibido por `textContent`; links de carteira/token usam prefixo fixo HTTPS.
- Links de criação de chaves vêm de constantes HTTPS em `app/keystore.py:29-35`. Escapar atributo
  não validaria `javascript:`, mas não foi identificado caminho de usuário para controlar essas constantes;
  portanto não se registra bypass `javascript:` explorável nesses links.
- Links externos com `noopener`; sessões, chaves e tokens não são escritos em logs JavaScript do projeto.
- Campos de chaves são `type=password` e esvaziados após resposta; API responde com `no-store`.
- CSP, `nosniff`, `X-Frame-Options: DENY`, `frame-ancestors 'none'`, `base-uri 'self'`, `form-action 'self'`.
- Docker não roda como root e copia apenas `requirements.txt`, `app/` e `web/`; `.env` é ignorado.
- Nenhum workflow `pull_request_target`, execução de código vindo de PR externo ou interpolação
  de título/corpo de issue em shell foi encontrado.

## Limitações e retomada

- Não houve teste de navegador real com execução de payload: a prova é de strings entregues a `innerHTML`.
- Não foram examinadas permissões reais da VPS, rede, Portainer, secrets nem configuração de proxy.
- Não houve login em conta real, clique de consentimento Google ou teste de webhook.
- Revisão desta área concluída para o baseline. Para corrigir: priorizar CI-01/CI-02 e WEB-01,
  criar regressões locais e integrar somente após revisar os demais achados da auditoria principal.
- Retomar a consolidação em `docs/AUDITORIA-SEGURANCA.md`; não tratar este sub-relatório como estado
  autoritativo de correções já aplicadas.

## Fontes primárias de apoio

- [GitHub: uso seguro de Actions e fixação por SHA](https://docs.github.com/en/actions/reference/security/secure-use)
- [Docker: práticas de build e fixação da imagem base](https://docs.docker.com/build/building/best-practices/)
- [Releases oficiais do Supabase JS](https://github.com/supabase/supabase-js/releases)
- [OSV API](https://google.github.io/osv.dev/api/)
