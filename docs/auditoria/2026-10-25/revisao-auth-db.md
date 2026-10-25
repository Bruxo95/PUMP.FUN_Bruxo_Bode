# Revisão de autenticação, autorização e persistência

- Data: 2026-10-25.
- ID da auditoria: `AUD-2026-10-25-0.8.2-1cec6a0`; revisão do relatório 1.0.
- Baseline: `1cec6a04dfe076be8ddbad5258359d2afb225f38`, versão 0.8.2.
- IA: OpenAI Codex, família GPT-6; identificador exato do modelo/revisão não exposto nesta sessão.
- Manifesto de identificação: `identificacao-auditoria.json`, nesta pasta.
- Escopo: `app/auth.py`, `app/api.py`, `app/hub.py`, `app/db.py`, `app/store.py`,
  validação em `app/settings.py`, regras de listas/ranking em `app/pumpfun.py`,
  consumo dos motores em `app/monitor.py`, três migrações e testes relacionados.
- Revisão e reproduções locais concluídas; correções não implementadas nesta revisão.
- Nenhuma conta de produção, banco remoto, carteira, segredo real ou transação foi usado.

## Reprodução preservada

Da raiz do repositório, com as dependências do projeto e pytest instalados:

```powershell
.\.venv\Scripts\python.exe -u docs\auditoria\2026-10-25\reproduzir-auth-db.py
```

O reprodutor usa somente `httpx.MockTransport`, `httpx.ASGITransport` e `FakeREST`.
Todos os valores de configuração no script são sintéticos. Ele não carrega `.env`.
**Exit 0 reproduz os problemas do baseline, não significa aprovação de segurança.**
O código de aplicação não é alterado pelo reprodutor.

## AUTH-01 — Bloqueio pode ser revertido por carregamento de motor já em andamento

- Severidade: **média confirmada**, com impacto potencial maior caso execução real seja liberada;
  não houve validação ou ativação de execução real.
- Referências: `app/api.py:53-74`, `app/hub.py:68-97`, `app/hub.py:224-237`,
  `app/hub.py:278-289`, `app/monitor.py:47-48` e `app/monitor.py:67-78`.
- Pré-condições: usuário possui token válido, inicia requisição que carrega seu motor enquanto
  o administrador bloqueia a conta; leituras do banco podem naturalmente ceder o event loop.
- Causa: o estado de bloqueio é verificado antes da carga; `unload()` não usa o lock da carga,
  não invalida a carga pendente e `engine()` publica o motor sem conferir novamente o perfil.
- Reprodução: o script pausa somente a leitura mockada de `user_settings` do usuário B.
  A requisição autenticada `POST /api/pump/wallets` está em andamento. O administrador faz
  `POST /api/admin/users/{B}` com `bloqueado=true`, recebe sucesso e nenhum motor está carregado.
  Liberada a leitura, a requisição anterior retorna 200, recoloca o motor na coleção global e
  adiciona a carteira à lista de carteiras seguidas. Nova requisição do usuário retorna 403,
  mas o motor já recriado continua visível ao monitor.
- Saída confirmada: `absent_after_block=true`, `pending_request_status=200`,
  `engine_present_after_pending_request=true`, `blocked_user_still_following_wallet=true`,
  `subsequent_request_status=403`.
- Impacto demonstrado: a garantia administrativa "parou de copiar" não se sustenta nessa
  intercalação; um usuário bloqueado pode manter motor/cópia simulada no monitor compartilhado.
  Não foi demonstrada transação real nem acesso a dados de outro usuário.
- Recomendação: serializar bloqueio/carga usando o mesmo lock por usuário; marcar bloqueio
  antes do cancelamento; conferir novamente o perfil antes de publicar/iniciar o motor e
  antes de ações sensíveis. Acrescentar teste concorrente que exija ausência do motor ao final.

## AUTH-02 — Usuário comum pode consumir a cota de API do sistema sem cache/limite

- Severidade: **média** (disponibilidade e consumo de recursos compartilhados).
- Referências: `app/api.py:199-209`, `app/pumpfun.py:511-519`,
  `app/pumpfun.py:588-605`; agravantes em `app/pumpfun.py:201-209` e `app/pumpfun.py:491`.
- Pré-condições: conta comum autenticada e chave compartilhada do sistema configurada.
- Causa: a rota de atualização chama `refresh_leaderboard(force=True)` em toda requisição,
  ignorando o intervalo de cache; o código não contém rate limit por conta/IP ou uma cota
  global para esse caminho. O motor usa a chave compartilhada quando a conta não tem chave própria.
- Reprodução: três POSTs sequenciais idênticos de um usuário comum retornam 200 e provocam
  três chamadas mockadas à Solana Tracker. Não foi consumida cota de serviço real.
- Saída confirmada: `http_statuses=[200,200,200]`, `mock_upstream_calls=3`.
- Impacto: uma conta pode gastar a cota compartilhada/causar respostas 429 e prejudicar
  ranking para todos. A gravidade depende do plano, dos limites externos e de eventuais
  controles no proxy, que não foram inspecionados.
- Recomendação: rate limit por identidade, cota global e cache compartilhado com deduplicação
  de chamadas concorrentes; respeitar um cooldown mínimo mesmo em atualizações manuais.
  Limitar também tamanho das listas de carteiras e número de motores/contas ativos.
- Agravante revisado: listas manuais não têm cota; `refresh_followed()` usa
  `max(top_n, len(manual))`, portanto `pump_top_n` não limita assinaturas manuais. O
  monitor une essas assinaturas para todos, ampliando consumo compartilhado.

## AUTH-03 — Tokens inválidos amplificam consultas de autenticação

- Severidade: **média** (disponibilidade; não é bypass de assinatura).
- Referências: `app/auth.py:33-43`, `app/auth.py:68-78`, `app/auth.py:85-101`.
- Pré-condições: acesso HTTP à API; não exige conta válida.
- Causa: `kid` desconhecido dispara recarga JWKS forçada e depois consulta `/auth/v1/user`;
  resultado JWKS vazio não é cacheado pelo caminho rápido, pois exige `self._jwks` verdadeiro.
  Não há cooldown por `kid`, deduplicação de recarga ou rate limit no código.
- Reprodução: dois JWTs falsos, com header RS256/kid desconhecido e componentes base64 válidos,
  são corretamente rejeitados, mas provocam seis chamadas mockadas: JWKS, JWKS, `/user`, repetidas.
- Saída confirmada: `tokens_rejected=2`, seis entradas em `mock_requests`.
- Impacto: tráfego barato não autenticado produz chamadas externas, pode pressionar limites
  do Supabase/pool HTTP e prejudicar autenticação normal. DoS em produção não foi tentado.
- Recomendação: cachear resultados vazios/negativos por curto período, limitar recargas
  forçadas, deduplicar consultas JWKS concorrentes e limitar tentativas na borda e na aplicação.

## AUTH-04 — Valor numérico fora do domínio resulta em erro 500

- Severidade: **baixa**, robustez/validação; nenhum vazamento foi demonstrado.
- Referências: `app/settings.py:131-143`, `app/api.py:109-116`.
- Reprodução: POST autenticado `/api/pump/settings` com `pump_max_open="1e1000"`.
  A conversão `int(float(valor))` levanta `OverflowError`, que não é capturado.
- Saída confirmada: HTTP 500 e corpo genérico `Internal Server Error`.
- Impacto observado: erro da própria requisição. Não foi demonstrada queda do processo ou
  alteração de dados de outra conta; não tratar este caso isolado como falha crítica.
- Recomendação: schemas tipados, limites de campo/corpo, finitude explícita antes da conversão
  e tratamento de `OverflowError`, retornando erro 4xx de validação.

## Riscos condicionais e decisões a confirmar

1. **Primeiro cadastro vira administrador.** A migração inicial (`:119-125`) faz isso
   intencionalmente e usa advisory lock. Com cadastro aberto, uma instalação vazia/restaurada
   deve ser provisionada pelo dono antes de abrir acesso. Recomenda-se identidade administrativa
   explícita ou bootstrap por canal confiável. Não há prova de tomada de admin na instalação atual.
   O fallback em `app/hub.py:58-64` não usa a transação/lock do gatilho; perfis históricos ausentes
   devem ser recuperados com papel `user`, sem decidir novo admin por contagem no backend.
2. **"Só Google" depende do Supabase.** O backend aceita JWT Supabase válido de usuário autenticado,
   independentemente do provedor. Não foi confirmado no console que outros métodos de login estão
   desativados. Não foi demonstrado bypass; revisar configuração dos provedores e cadastro.
3. **Fila de persistência volátil e descarte.** `app/db.py:107-110` descarta a operação mais antiga
   após 20.000 itens. A fila e o estado ainda não gravado desaparecem em falha abrupta do processo;
   o motor não é interrompido automaticamente quando o banco falha. Isso pode desalinhar posições
   e histórico, com risco maior antes de qualquer uso real. Considerar fila durável, backpressure,
   fail-closed para novas operações reais e reconciliação; nenhuma perda financeira foi provocada.
4. **Audit log não bloqueia ação quando falha.** `app/db.py:232-237` captura falha e apenas registra
   aviso. Eventos sensíveis podem não ficar no banco; revisar durabilidade/idempotência para
   operações de dinheiro. Comportamento documentado no código, não uma exfiltração comprovada.

## Controles revisados sem bypass demonstrado

- JWT com assinatura, issuer, audience e expiração verificados; algoritmos explicitamente restritos.
  O fallback remoto só aceita resposta bem-sucedida do endpoint Supabase; tokens falsos do PoC rejeitados.
- `user_id` das rotas normais vem do token; não há campo de usuário arbitrário aceito para
  acessar posições/histórico/chaves de outra conta. `close` busca a posição no store do próprio usuário.
- Rotas administrativas usam dependência de admin; bloqueio do perfil é conferido em cada nova requisição.
- SQL define RLS por `auth.uid()` nas tabelas de usuário, revoga gravação direta de browser,
  restringe leitura de `user_secrets` às colunas não secretas, fecha `app_secrets` para browser
  e revoga execução pública das funções privilegiadas.
- Operações de delete do store filtram `user_id`; upserts de posições/trades usam IDs gerados
  internamente. Não foi encontrado caminho de API para escolher o ID de uma posição nova de outro usuário.
- Endpoints públicos observados no código são `/health`, `/api/public-config`, páginas e estáticos;
  a chave ANON publicada é esperada, distinta da service role.
- Ausência de cookies de autenticação próprios e uso de Bearer nas APIs reduzem a superfície de CSRF
  tradicional; isso não elimina riscos de XSS/token roubado, que pertencem à revisão do frontend.

## Limitações e retomada

- Não foi executado RLS em PostgreSQL real por este revisor. Os testes de RLS existem, mas
  usam Postgres local e podem ser pulados em ambientes sem os binários ou em Windows.
- Não foram inspecionados controles de borda, política do Supabase remoto, logs/segredos de
  produção, retenção de dados, backups, MFA administrativo ou versão real do PostgREST.
- Não houve carga/estresse, exploração em produção, autenticação de conta real ou uso de fundos.
- Os achados permanecem **abertos**. Retomar primeiro por AUTH-01 (bloqueio concorrente), depois
  AUTH-02/AUTH-03 (cotas e amplificação), validando regressões com mocks. Rever os riscos
  condicionais antes de liberar execução real. Reexecutar RLS em Linux com Postgres disponível.
