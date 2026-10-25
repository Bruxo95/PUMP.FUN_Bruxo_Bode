# Auditoria de carteiras e integrações — 2026-10-25

ID da auditoria: `AUD-2026-10-25-0.8.2-1cec6a0`; revisão do relatório 1.0.
IA: OpenAI Codex, família GPT-6; identificador exato do modelo/revisão não exposto nesta sessão.
Manifesto de identificação: `identificacao-auditoria.json`, nesta pasta.

Base: `1cec6a04dfe076be8ddbad5258359d2afb225f38`, versão `0.8.2`.
Escopo: `solana_wallet.py`, `jupiter.py`, `crypto.py`, `keystore.py`, `logsafe.py`,
motor em `pumpfun.py`, `monitor.py` e ligações com `hub.py`/`api.py`.
Análise de código e provas locais; nenhuma transação de rede ou alteração em produção.

## Evidência reproduzível

Executar da raiz:

```powershell
.\.venv\Scripts\python.exe docs/auditoria/2026-10-25/poc-carteiras.py
```

O script exige as dependências normais do projeto e pytest. Usa `FakeREST`,
`httpx.MockTransport`, chaves aleatórias descartáveis, blockhash zero e interceptação
do envio. Nunca substituir os mocks por clientes de rede reais.

## CAR-01 — SSRF autenticado pelo RPC pessoal — média

**Referências:** `app/solana_wallet.py:34-38`, `app/api.py:224-240`,
`app/api.py:135-144`, `app/jupiter.py:140-167`.

Qualquer usuário autenticado pode salvar um RPC que começa por `https://`. Não há
restrição de host, porta, credenciais na URL ou resolução para endereços internos.
Depois de cadastrar uma chave de carteira de sua propriedade (pode ser vazia e
descartável), consultar `/api/pump/wallet?force=1` faz o servidor enviar três POSTs
JSON-RPC ao destino escolhido. Não é necessário habilitar a cópia real.

**Reprodução:** a rota de salvar aceitou um destino `https://127.0.0.1:8443/internal-rpc`;
a rota de saldo gerou `getBalance` e duas chamadas `getTokenAccountsByOwner` para ele,
todas capturadas no transporte falso. Nenhuma conexão à rede interna foi feita.

**Impacto/limites:** permite sondagem e requisições a serviços HTTPS alcançáveis pelo
servidor. O corpo é JSON-RPC definido pelo código, a validação TLS permanece ativa e
`follow_redirects=False`; não foi demonstrado acesso a metadados HTTP, vazamento de
credencial service-role ou alcance de serviço interno real. Respostas que se encaixem
no formato esperado podem influenciar o saldo/erro retornado. A exploração concreta
depende de um destino interno com TLS aceito ou de resolução DNS manipulada.

**Correção:** validar com parser de URL e política de destinos; rejeitar userinfo,
hosts/IPs privados, loopback, link-local, reservados e portas não aprovadas; validar
todas as respostas DNS no momento da conexão e restringir saída no ambiente.
Se RPCs arbitrários forem requisito, manter a saída num proxy com política própria.

## CAR-02 — assinatura irrestrita de transação montada por terceiros — alta, condicional

**Referências:** `app/pumpfun.py:1938-1953`, `app/jupiter.py:174-191`.

PumpPortal e Jupiter devolvem mensagens de transação que o servidor desserializa e
assina diretamente com a carteira do usuário. O código não verifica programas,
instruções, destino, mint, quantidade máxima debitada ou alterações de autoridade
antes da assinatura. O pedido de compra e os limites do motor não vinculam o
conteúdo efetivamente assinado.

**Reprodução:** um builder inteiramente falso devolveu uma transferência SystemProgram
de 9 SOL para uma chave descartável. Mesmo com pedido de compra de 0,05 SOL, `_tx`
produziu assinatura válida. `_swap_tx` da Jupiter também assinou a mesma mensagem.
A função de transmissão foi interceptada; não houve broadcast, consulta de saldo
real ou criação de transação válida para a rede (blockhash zero).

**Pré-condição essencial:** um atacante precisaria controlar/comprometer a resposta do
provedor de construção, sua cadeia de fornecimento ou outra parte dessa fronteira
de confiança. Não foi encontrada uma rota que permita a outro usuário comum enviar
diretamente uma transação arbitrária para assinatura. TLS protege o transporte, mas
não protege contra o próprio builder comprometido.

**Impacto:** uma resposta comprometida pode obter assinatura para gastar saldo muito
além do valor configurado ou modificar permissões de tokens. Não significa que o
provedor atual esteja comprometido. Nenhuma retirada foi tentada.

**Correção:** validar semanticamente a mensagem, incluindo Address Lookup Tables,
programas e instruções permitidos, mints, destinatários/autoridades e limites de
débitos/taxas; falhar fechado diante de instrução desconhecida. Usar simulação como
checagem adicional, sem tratá-la como validação suficiente de intenção, e carteira
segregada com saldo limitado. Bloquear dinheiro real até validação específica.

## CAR-03 — venda pendente permite criar outra ordem sem reconciliação — média

**Referências:** `app/pumpfun.py:1915-1936`, `app/pumpfun.py:2031-2075`.

Dentro de `_send_confirm` o reenvio reutiliza a mesma transação/assinatura, o que é
correto. O problema fica no nível seguinte: após retorno `pendente`, `sell` espera
três segundos, consulta o saldo uma vez e, se ele não caiu, monta outra transação
na próxima tentativa (por exemplo, alterando slippage de 15% para 30%). Não acompanha
a assinatura pendente até confirmação ou expiração comprovada do blockhash.

**Cenário:** venda solicitada de 50% de 1.000 tokens; assinatura A é transmitida, mas
o RPC não confirma e a consulta seguinte ainda apresenta saldo 1.000. O código
monta assinatura B, novamente por 50%. Se A confirmar e B vender 50% do saldo então
restante, ficam 250 tokens, venda total de 75% em lugar de 50%. Se ambas usarem
quantidade fixa com base no saldo antigo, o efeito pode ser maior. São transações
distintas: a deduplicação por assinatura do reenvio interno não resolve isso.

**Reprodução/limite:** o modelo offline retornou saldos `(1 SOL, 1000)`,
`(1 SOL, 1000)`, `(1,75 SOL, 250)` e respostas `pendente A`/`confirmada B`. Foram
observadas duas chamadas de venda por `50%` e retorno de 250 tokens. Isso confirma
o caminho de controle sem reconciliação; a possibilidade temporal na blockchain
depende de validade do blockhash, atraso de confirmação e consistência do RPC.
Nenhum congestionamento real ou operação on-chain foi provocado.

**Correção:** persistir estado/assinatura/blockhash de cada intenção; enquanto houver
resultado indeterminado, não construir outra transação da mesma intenção. Reconciliar
status, saldo e expiração comprovada, retomando apenas a quantidade ainda devida.
Manter isso também após reinício do processo.

## CAR-04 — credenciais na URL RPC reaparecem na API — baixa

**Referências:** `app/solana_wallet.py:66-69`, `app/api.py:217-222`,
`app/api.py:135-144`.

`UserWallet.public()` obtém o host com `split('/')[2]`, preservando `usuario:senha@`.
Uma URL HTTPS com Basic Auth é aceita e armazenada como segredo; depois
`GET /api/secrets` e a resposta do saldo devolvem essa credencial em `rpc_host`.

**Reprodução:** salvar `https://demo:discardable-pass@127.0.0.1:8443/internal-rpc`
retornou `ok`; a leitura autenticada trouxe `discardable-pass` em seu JSON.
O valor é apenas fictício. Não houve exposição de credencial real.

**Impacto/limite:** exposição ao próprio cliente logado, capturas/exportações de
resposta e eventuais ferramentas de diagnóstico, contrariando a promessa de
"configurada: sim/não". Não foi demonstrada leitura por outro usuário ou sem login.

**Correção:** rejeitar userinfo ou usar `urllib.parse.urlsplit(...).hostname`,
renderizando apenas host/porta aprovados. Aplicar redação a erros enviados pela API,
não apenas aos logs. Não mostrar URLs completas de RPC com chaves.

## Proteções e comportamentos confirmados no código

- Chave privada não é enviada aos builders; somente endereço público e parâmetros.
- AES-GCM usa nonce aleatório e AAD de usuário+nome, impedindo transplante simples
  de cifra entre usuários/campos; string de chave mestra exige 32 bytes.
- `pump_real_enabled` não é persistido e reinicia `False`; a rota de ligar exige
  trava geral liberada, confirmação `LIGAR` e carteira configurada.
- Chaves do sistema são separadas das chaves de execução de cada usuário.
- O HTTP compartilhado não segue redirects; isso reduz, mas não elimina, SSRF.
- Swaps USDC→SOL são operações manuais com confirmação própria; vendas de posições
  reais podem continuar com compras desativadas. A ausência de `pump_real_enabled`
  nessas saídas não foi classificada como bypass: o código as trata deliberadamente
  como caminhos independentes/proteção de saída. A interface deve descrever isso.
- Há filtros de segredos em logs, mascaramento de erro do leaderboard e do WebSocket
  PumpPortal; não se deve concluir que qualquer exceção em qualquer resposta esteja
  automaticamente mascarada, porque eventos e erros de API não passam pelo filtro.
- Não se confirmou o cenário de duas posições reais normais no mesmo mint: `_copy`
  bloqueia qualquer posição real já aberta no mint e o conjunto `_real_buying`
  bloqueia compras enfileiradas simultâneas (`pumpfun.py:765-772`). `sell`, contudo,
  usa o saldo agregado do mint da carteira, não uma quantidade vinculada à posição.
  Tokens externos/airdrop ou dados restaurados inconsistentes exigem reconciliação;
  por isso a carteira dedicada é uma premissa relevante. Não foi criado um achado
  separado por duas posições que o fluxo normal impede.

## Limitações e ponto de retomada

Revisão local encerrada nesta rodada com quatro achados e uma observação de
comportamento. Nenhuma correção aplicada a código de aplicação. Próximo passo:
priorizar correção de CAR-01 e CAR-02, definir política de vendas pendentes CAR-03,
adicionar regressões offline e rerodar a auditoria. A auditoria não verificou VPS,
certificados de destinos internos, segredos reais, configuração do Supabase remoto,
backups, permissões do Portainer ou operações reais em Solana. A validação de
criptografia em produção e semântica completa de transações permanece pendente.
