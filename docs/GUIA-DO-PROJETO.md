# PUMP FUN COPY — Guia do projeto

Documento de referência para quem vai **usar**, **operar** ou **desenvolver** o sistema.
Explica o que o sistema faz, como configurar e usar, como as transações chegam à blockchain Solana e o papel de
cada serviço externo (API).

| | |
|---|---|
| Produção | https://pump.rachar.app.br (versão no ar em `/health` e no rodapé do painel) |
| Repositório | `github.com/Bruxo95/PUMP.FUN_Bruxo_Bode` (privado), branch `main` |
| Contexto para agentes de IA | `CLAUDE.md` e `AGENTS.md` (raiz do repositório) |
| Auditoria de segurança | `docs/AUDITORIA-SEGURANCA.md` |
| Origem do código | `docs/ORIGEM.md` (aba PUMP.FUN do `hermes-jev-trader`) |

> **Aviso.** Memecoins da pump.fun são extremamente arriscadas: a maioria vai a zero e copiar traders sempre
> tem atraso. O sistema nasce em modo **simulado**. A execução real fica travada no servidor e, conforme a
> auditoria de 2026-10-25, **não está aprovada para uso com dinheiro real** até os achados abertos serem
> corrigidos.

---

## 1. O que o sistema faz

O PUMP FUN COPY acompanha, em tempo real, as carteiras dos melhores traders da pump.fun e **replica as
operações deles** numa carteira do usuário.

1. **Escolhe quem copiar.** Busca o ranking oficial de top traders do app da pump.fun (via Solana Tracker) e
   aplica filtros: acerto mínimo, número mínimo de trades, saldo mínimo da carteira e exclusão de robôs, devs
   de token e corretoras. Os N primeiros aptos são seguidos, além das carteiras adicionadas manualmente.
2. **Observa as carteiras.** Mantém uma conexão com a rede Solana e é avisado a cada transação dessas
   carteiras. Lê a transação e identifica se foi compra ou venda, de qual token e em que valor.
3. **Copia.** Quando o trader compra, o sistema compra um valor fixo do mesmo token; quando ele vende, o
   sistema vende a mesma proporção.
4. **Protege.** Cada posição tem stop de perda, stop móvel (conferido a cada ~1 s), tempo máximo, alvo
   opcional, "segurar até lucro" e pausa automática de traders que batem stop repetidamente. Antes de
   copiar, filtros de token barram ativos com pouco volume, poucas negociações, market cap baixo ou
   concentrados em poucas carteiras.
5. **Mostra tudo.** Painel com saldo, resultado, posições, histórico líquido de taxas, feed ao vivo e
   notificações sonoras.

### Dois modos de operação

| Modo | O que acontece | Dinheiro real? |
|---|---|---|
| **Fictício (simulado)** | Sempre ativo. Cada cópia é calculada com o preço logo depois do trader, mais slippage extra e **todas as taxas reais** (pump.fun/PumpSwap, PumpPortal, rede). Nada é enviado à blockchain. | Não |
| **Real** | Além do fictício, a cópia vira uma transação de verdade, assinada com a carteira do usuário e enviada à Solana. | Sim |

O modo real tem **três travas independentes**:
1. **Trava do servidor:** `PUMP_REAL_ALLOWED=false` no stack — ninguém consegue ligar.
2. **Botão por usuário:** começa desligado, exige digitar `LIGAR` e volta a desligar **toda vez que o
   servidor reinicia**.
3. **Limites por usuário:** valor máximo por compra, posições reais simultâneas e perda máxima no dia.

### Multiusuário

Cada pessoa entra com Google e tem o próprio painel, configurações, carteira, posições, histórico e chaves.
O isolamento é garantido no banco (RLS do Supabase) e no servidor, que sempre filtra pelo usuário do token
de login. O monitor da rede é **um só para todos**: cada transação é lida uma vez e entregue a quem segue
aquela carteira.

---

## 2. Como usar (usuário)

### 2.1 Primeiro acesso
1. Abra https://pump.rachar.app.br e clique em **Entrar com Google**.
2. O primeiro usuário cadastrado no sistema vira **administrador**; os demais entram como usuário comum.
3. O painel abre na **Visão geral** com a carteira fictícia (padrão: 5 SOL fictícios).

### 2.2 Chaves (Configurações → Chaves pessoais)

As chaves são coladas **somente no painel**. São criptografadas no servidor (AES-256-GCM) antes de ir para o
banco e **nunca voltam para a tela**: o painel mostra apenas o estado de cada uma.

| Estado exibido | Significado |
|---|---|
| **Usando: sua chave** | A sua chave está salva e em uso. |
| **Usando: chave do sistema (só visualização)** | Você não tem chave própria; o sistema usa a chave configurada pelo admin para você ver os dados. |
| **Não configurada** | Nenhuma chave disponível para esse recurso. |

| Chave | Para que serve | Obrigatória? | Onde criar |
|---|---|---|---|
| **Solana Tracker** | Buscar o ranking oficial de top traders da pump.fun. | Não, se o admin configurou a do sistema. | solanatracker.io → Account → Data API (plano gratuito) |
| **PumpPortal** | Dados extras pagos da PumpPortal. **Não** é necessária para executar compras/vendas. | Não | pumpportal.fun → Trading API |
| **Chave privada da carteira Solana** | Assinar as transações do modo real e da troca USDC→SOL. | Só para o modo real | Crie uma carteira **nova** na Phantom ou Solflare e exporte a chave privada |
| **RPC próprio** | Endereço `https://` de um provedor Solana (Helius, QuickNode…), mais rápido e com limites maiores que o público. | Não (recomendado no modo real) | dashboard.helius.dev ou equivalente |
| **Jupiter** | Aumenta o limite de cotações nas trocas da **sua** carteira. | Não | developers.jup.ag → Portal → API Keys |

**Sobre a chave privada da carteira**
- Use uma carteira **exclusiva para o bot, com pouco saldo**. Quem tem a chave privada controla todo o saldo.
- Formatos aceitos: texto base58 (exportado pela Phantom/Solflare) ou a lista de 64 números do `id.json`.
- Ela é aberta **apenas na memória do servidor**, no momento de assinar. Nunca é enviada a nenhuma API
  externa, nunca aparece em log e nunca volta para o navegador. Após salvar, o painel mostra só o
  **endereço público** da carteira.

### 2.3 Configurar a cópia (Configurações)
- **Cópia automática** ON/OFF e **valor de cada cópia** (fictício).
- **Esperar antes de copiar**: só copia se o trader ainda estiver no token após X segundos.
- **Fora da pump.fun**: copiar também trades em Raydium/Orca/Meteora (via Jupiter), com liquidez mínima.
- **Segurar até lucro**: se o trader sair com a nossa posição no prejuízo, segura até o resultado líquido
  ficar positivo.
- **Proteções**: stop móvel (liga em +X%, sai se cair Y pontos do pico), stop de perda, tempo máximo, alvo
  fixo e pausa automática do trader.
- **Filtros**: acerto e trades mínimos do trader, top N, saldo mínimo do trader, compra mínima do trader,
  market cap, volume e negociações mínimas do token, concentração máxima nas 10 maiores carteiras e (0.9.3)
  nota de risco da Solana Tracker: não copia token sem liquidez, com alerta de perigo (mint/freeze authority,
  bundlers, insiders) ou com nota acima da máxima (padrão 7 de 10). Sem chave da Solana Tracker, não checa.
  (0.9.4) Não copia se o preço já subiu mais que X% (padrão 30%) desde a compra do trader — na cópia com espera
  e na compra real, conferida de novo na hora de enviar.
- **Só copiar traders online** (padrão ON, janela de 10 min): dos traders aptos do top, só entram na cópia os
  que negociaram nos últimos X minutos. A cada 10 min a lista é refeita: quem ficou inativo sai e entra o
  melhor do top que estiver online. Se sobrar vaga e um trader do top negociar, ele entra na hora. Carteiras
  manuais e traders com posição copiada aberta continuam. "Online" vem do WebSocket da Solana (top 60
  observados) ou, logo após reiniciar, do "último trade" informado pela Solana Tracker.
- **Taxas da simulação**: as mesmas cobradas no modo real.

Cada alteração vale na hora e fica salva só para o usuário.

### 2.4 Acompanhar
- **Visão geral**: saldo, resultado, posições, acerto, monitor ON/OFF, gráfico 24h/7d/30d e operações
  recentes com etiquetas (COMPRA, VENDA COM LUCRO, VENDA COM PREJUÍZO, STOP, STOP MÓVEL, ERRO, PAUSADO;
  REAL/SIMULADO).
- **Top traders**: ranking, traders copiados (adicionar, pausar, banir), monitor ao vivo das entradas e
  saídas deles e o que eles estão segurando.
- **Posições / Histórico / Feed ao vivo**: detalhes de cada cópia, taxas pagas e o motivo de cada decisão
  (inclusive por que **não** copiou).
- **Notificações**: botão no topo liga sons e avisos para compras, vendas, lucros, prejuízos e erros.
- **Busca**: Ctrl+K / ⌘K procura token, trader ou carteira.

### 2.5 Modo real (quando autorizado)
1. O responsável pela infraestrutura libera `PUMP_REAL_ALLOWED=true` no stack.
2. O usuário salva a chave privada da carteira do bot e envia SOL para o endereço mostrado.
3. Em **Execução real**, ajusta o valor por compra, a perda máxima no dia e as posições simultâneas.
4. Clica no botão vermelho **REAL: OFF** e digita `LIGAR`.
5. Ações ficam registradas no **Registro de segurança** (audit log).

**Troca USDC → SOL:** a carteira paga as compras em SOL. Se houver USDC, a tela de Execução real cota a troca
e, após confirmação, executa pela Jupiter.

### 2.6 Administração (somente admin)
- **Usuários**: mudar categoria (Usuário/Admin; sempre resta ao menos um admin), bloquear/desbloquear
  (a conta para de copiar na hora e perde o acesso), desligar a execução real de alguém e ver o registro de
  cada conta. O admin **nunca** vê as chaves de ninguém, só se estão configuradas.
- **Chaves do sistema**: Solana Tracker, PumpPortal e Jupiter usadas por quem não tem chave própria, **apenas
  para visualização** (ranking, cotações, conexão de dados). Nunca executam nada em nome de usuário.
- **Status geral**, **registro de segurança de todas as contas** e **logs do servidor em tempo real**
  (segredos mascarados).

---

## 3. Como funcionam as transações reais

### 3.1 Princípio
Em todas as rotas, a transação é **montada** por um serviço externo (PumpPortal ou Jupiter), **assinada
dentro do servidor do PUMP FUN COPY** com a chave do usuário e **enviada pelo próprio servidor diretamente à
rede Solana**, pelo RPC do usuário (ou o público). Nenhum serviço externo recebe a chave privada e nenhum
deles envia a transação em nome do usuário.

```
 ┌──────────────┐   1. pede a transação    ┌──────────────────────┐
 │  Servidor    │ ───────────────────────► │ PumpPortal (pump.fun)│
 │ PUMP FUN COPY│ ◄─────────────────────── │   ou Jupiter (DEXs)  │
 │              │   2. transação SEM       └──────────────────────┘
 │ 3. assina com│      assinatura
 │  a chave do  │
 │  usuário (na │   4. sendTransaction     ┌──────────────────────┐
 │  memória)    │ ───────────────────────► │  RPC Solana          │──► rede Solana
 │              │ ◄─────────────────────── │ (próprio ou público) │    (validadores)
 └──────────────┘   5. status / saldos     └──────────────────────┘
```

### 3.2 Compra de token da pump.fun (rota principal — **não passa pela Jupiter**)
1. **Montagem:** `POST https://pumpportal.fun/api/trade-local` com o endereço público da carteira, o token,
   o valor em SOL, slippage, taxa de prioridade e `pool` (`auto`). A PumpPortal devolve os bytes de uma
   transação **sem assinatura** que interage diretamente com o programa da pump.fun (curva de bonding) ou da
   PumpSwap (token já graduado). A taxa de 0,5% da PumpPortal está embutida nessa transação.
2. **Assinatura:** o servidor assina localmente (`solders.VersionedTransaction`) com a chave do usuário.
3. **Envio:** `sendTransaction` direto ao RPC Solana (com simulação prévia: se o preço não couber no
   slippage, a rede recusa sem custo).
4. **Confirmação:** consulta `getSignatureStatuses` a cada ~0,75 s por até ~60 s e reenvia a **mesma**
   transação a cada ~2 s (mesma assinatura, não duplica a compra).
5. **Medição:** compara saldo de SOL e do token **antes e depois** (`getBalance`,
   `getTokenAccountsByOwner`). O valor registrado é o que realmente saiu e entrou na carteira, já com todas
   as taxas.
6. **Rotas de reserva:** se a curva já completou (token graduou — erro `0x1775`), tenta a PumpSwap
   (`pool=pump-amm`); se ainda falhar, a Jupiter.

### 3.3 Venda de token da pump.fun
Mesma rota da compra, vendendo a porcentagem correspondente à venda do trader. Se a rede recusar por preço,
tenta de novo com slippage crescente (padrão 15% → 30% → 50%). Token graduado → PumpSwap. Jupiter apenas como
último recurso (ela não negocia tokens que ainda estão na curva).

### 3.4 Token fora da pump.fun e troca USDC → SOL (rota Jupiter)
1. **Cotação:** `GET /swap/v1/quote` na Jupiter para Raydium, Orca e Meteora isoladamente e para a melhor
   rota agregada; escolhe a que entrega mais.
2. **Montagem:** `POST /swap/v1/swap` devolve a transação sem assinatura, com taxa de prioridade dinâmica
   (teto de 0,002 SOL).
3. **Assinatura, envio, confirmação e medição:** idênticos aos passos 2–5 da seção 3.2.

### 3.5 Garantias e limites do modo real
- Fila de execução **por usuário**: uma operação de cada vez, cada uma esperando a confirmação.
- Bloqueios antes de comprar: modo real desligado, carteira não configurada, saldo menor que o valor + 0,02
  SOL de reserva, limite de posições reais, perda do dia atingida.
- Chaves do sistema **nunca** são usadas nessas transações.
- Pendências de segurança antes de uso real: ver `docs/AUDITORIA-SEGURANCA.md` (em especial validar o
  conteúdo da transação montada por terceiros antes de assinar e reconciliar vendas pendentes).

---

## 4. Serviços externos (APIs)

Legenda — **Tipo**: *Consulta* = só lê dados; *Montagem* = gera transação sem assinar; *Escrita* = envia à
blockchain ou grava dados. **Uso**: *Compartilhado* = uma conexão/consulta para todos os usuários;
*Pessoal* = por usuário.

| Serviço | Endereço / método | Tipo | Chave | Uso | Para que o projeto usa |
|---|---|---|---|---|---|
| **Solana RPC — WebSocket** | `logsSubscribe` (mentions por carteira) | Consulta | Não | Compartilhado | Avisar em tempo real cada transação das carteiras seguidas e do top 60 (status online). |
| **Solana RPC — HTTP (leitura)** | `getTransaction` | Consulta | Não | Compartilhado | Ler a transação do trader e descobrir token, lado e valores. |
| | `getMultipleAccounts` | Consulta | Não | Compartilhado | Preço ao vivo pela curva da pump.fun (reservas virtuais on-chain), a cada ~3 s (~1 s com stop móvel). |
| | `getTokenSupply`, `getTokenLargestAccounts` | Consulta | Não | Compartilhado | Concentração nas 10 maiores carteiras (filtro anti-insider). |
| Solana Tracker | `GET /tokens/{mint}` (campo `risk`) | Consulta | Chave (própria ou do sistema) | Compartilhado, cache 10 min por token | Nota de risco do token antes de copiar (0.9.3). |
| | `getBalance`, `getTokenAccountsByOwner` | Consulta | Não | Compartilhado / Pessoal | Saldo dos traders (filtro de saldo mínimo) e saldos da carteira do usuário. |
| **Solana RPC — HTTP (envio)** | `sendTransaction`, `getSignatureStatuses` | Escrita | RPC próprio opcional | Pessoal | Enviar a transação assinada e acompanhar a confirmação (modo real e troca USDC→SOL). |
| **PumpPortal — WebSocket** | `wss://pumpportal.fun/api/data` · `subscribeNewToken` | Consulta | Opcional (sistema) | Compartilhado | Tokens novos e seus criadores (identifica devs de token). Streams de trades são pagos e ficam desligados. |
| **PumpPortal — Trading API** | `POST /api/trade-local` | Montagem | Não | Pessoal | Montar a transação de compra/venda da pump.fun/PumpSwap para o servidor assinar. |
| **Solana Tracker** | `GET /v2/pnl/leaderboard/top` | Consulta | Sim (pessoal ou do sistema) | Compartilhado com cache | Ranking dos top traders do app da pump.fun; cache por período e filtros, renovado a cada 10 min. |
| **DexScreener** | `GET /tokens/v1/solana/{mints}` | Consulta | Não | Compartilhado | Símbolo, preço, market cap, liquidez e volume/negociações por hora (filtros e tokens graduados). |
| **Jupiter — Quote** | `GET /swap/v1/quote` | Consulta | Opcional | Compartilhado (cotações) / Pessoal (trocas) | Preço do SOL em US$, preço executável de tokens graduados e escolha de rota nas trocas. |
| **Jupiter — Swap** | `POST /swap/v1/swap` | Montagem | Opcional (do usuário) | Pessoal | Montar a transação de troca fora da pump.fun e USDC→SOL. |
| **Supabase Auth** | OAuth Google, JWKS / `/auth/v1/user` | Login | Anon (pública) | — | Login com Google e validação do token de cada requisição. |
| **Supabase PostgREST** | `/rest/v1/*` com service key | Escrita / Consulta | Service key (servidor) | — | Perfis, configurações, chaves criptografadas, posições, histórico, listas, feed e audit log. |
| **GitHub Actions / GHCR** | `ghcr.io/bruxo95/pump.fun_bruxo_bode` | Build | Token do GitHub | — | Testes e publicação da imagem Docker a cada push. |
| **Portainer (webhook)** | URL do serviço (segredo do GitHub) | Deploy | Segredo | — | Atualização automática do serviço após a publicação da imagem (opcional). |

Notas:
- O RPC público da Solana tem limites; o monitor compartilhado usa o RPC público (`SOLANA_RPC_PUBLIC`). As
  operações do usuário usam o RPC próprio dele, se configurado.
- A Jupiter sem chave usa `lite-api.jup.ag`; com chave, `api.jup.ag` (cabeçalho `x-api-key`).
- As taxas reais modeladas na simulação: pump.fun na curva 1,25% por lado (PumpSwap ~0,30%), PumpPortal 0,5%
  por lado, taxa de prioridade por transação e slippage extra configurável.

---

## 5. Arquitetura

```
Navegador (web/)  ──login Google──►  Supabase Auth
     │ token JWT
     ▼
FastAPI (app/api.py) ── valida token (app/auth.py) ── user_id
     │
PumpHub (app/hub.py) ── um motor PumpFun por usuário (app/pumpfun.py)
     │                         │ dados do usuário: SupabaseStore (app/db.py) → Supabase (RLS)
     │                         │ chaves: Vault (AES-256-GCM, app/crypto.py)
     │                         └ execução real: PumpReal + JupiterWallet (app/jupiter.py)
     │
SharedMonitor (app/monitor.py) ── uma conexão para todos:
     Solana WebSocket · getTransaction · curva on-chain · DexScreener · Jupiter (cotações)
     PumpPortal (tokens novos) · Solana Tracker (ranking, cache)
```

Detalhes de cada arquivo, regras de trabalho e fluxo de entrega: `CLAUDE.md`.

### Dados no banco (Supabase)
`profiles`, `user_settings`, `user_secrets` (cifradas), `app_secrets` (chaves do sistema, cifradas e
inacessíveis ao navegador), `pump_positions`, `pump_trades`, `pump_lists`, `pump_feed` (últimos 500),
`audit_log`. RLS em todas as tabelas; o navegador só lê as próprias linhas e nunca grava.

### Configuração do servidor
Variáveis no stack do Portainer: `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`,
`APP_ENCRYPTION_KEY`, `PUBLIC_BASE_URL`, `SOLANA_RPC_PUBLIC`, `PUMP_REAL_ALLOWED` e padrões `PUMP_*`
opcionais (`.env.example`). Instalação e atualização: `README.md`.

---

## 6. Desenvolvimento

- Python 3.12 + FastAPI; front em HTML/CSS/JS sem framework (sem handlers inline por causa da CSP).
- Testes: `pytest -q`, **todos sem internet** (respostas de rede simuladas). `tests/test_pump.py` é a
  referência do comportamento de cópia herdado do projeto original.
- Antes de cada push: `git pull` no `main`, integrar o que chegou e rodar os testes; erro encontrado é corrigido
  antes de enviar (outras IAs e o dono também publicam aqui).
- A cada entrega: subir a versão em `app/version.py`, rodar os testes, commit e push no `main`. O GitHub
  Actions testa, publica a imagem e (se configurado) atualiza o servidor.
- Nunca registrar chaves em código, logs, documentos ou mensagens.
