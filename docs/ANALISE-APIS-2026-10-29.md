# Análise das APIs de consulta — 2026-10-29 (versão 0.32.63)

Pedido do dono (Bruxo95): "analise todo o projeto e veja quais alterações temos que fazer para melhorar a API de
consulta; estamos trabalhando em dois". Feita sobre o `main` do GitHub no commit `27ea310` (0.32.63, Douglas),
com os números do banco (`api_usage`, `study_wallets`, `study_positions`, `token_xray`) lidos só para consulta.
**Nada foi alterado no código nesta etapa.** As mudanças propostas estão no fim, divididas para os dois não
mexerem no mesmo arquivo ao mesmo tempo.

## 1. O problema

A Solana Tracker responde **"Insufficient credits"** (visto pelo Douglas na 0.32.62/0.32.63). O plano grátis da
Data API dá **10.000 consultas por mês e 3 por segundo** (página de preços deles). O robô, do jeito que está, pede
cerca de **2.500 a 3.000 consultas por dia** (≈ 75–90 mil por mês) quando tudo funciona — 7 a 9 vezes o plano.
Quando os créditos acabam, tudo que depende da Solana Tracker para junto: ranking dos top traders, Explorar,
risco do token, histórico das Carteiras em estudo, Raio-X e revisão de ganhos falsos.

`api_usage` só conta desde a 0.31.76 (27/10). Em ~2,5 dias, a chave mais usada fez 2.292 consultas
(≈ 900/dia) e as outras quatro chaves mais 1.366 — e boa parte das consultas que falham por falta de crédito
não aparece como dado útil.

## 2. Quem gasta a Solana Tracker (estimativa por mês, se tudo der certo)

| Parte do robô | Onde no código | Frequência hoje | Consultas/mês | Observação |
|---|---|---|---|---|
| **Carteiras em estudo** (histórico 30 dias) | `hub.refresh_study` → `refresh_study_wallet` (`/v2/pnl/wallets/{w}/positions`) | cada carteira a cada 30 min (`learning_loop`) | **≈ 52.000** (36 carteiras × 48/dia) | **maior gasto**. O monitor já grava os trades novos dessas carteiras ao vivo em `wallet_trades`; o histórico da Solana Tracker só precisa ser buscado ao adicionar e de vez em quando |
| **Explorar** | `monitor.explore_loop` → `fetch_explore` (`/tokens/multi/all`) | a cada 5 min (`explore.EVERY_S=300`) | ≈ 8.640 | sozinho já é quase o plano grátis inteiro |
| **Ranking dos top traders** | `monitor.lb_once` → `refresh_leaderboard` (`/v2/pnl/leaderboard/top`) | a cada 10 min por grupo de filtros (`pump_lb_every_s=600`, mudado na 0.9.0) | ≈ 4.300 por grupo | o status online vem do WebSocket, não do ranking: o ranking pode ser mais lento |
| **Risco do token** | `risk_check` (`/tokens/{mint}` **+** `/stats/{mint}` = 2 consultas) | toda compra de trader copiado em token novo (cache 10 min; falha tenta de novo em 1 min) | ≈ 3.000–15.000 (depende de quantos traders compram) | chamado antes dos outros filtros: gasta até em token que seria barrado por market cap, compra mínima etc. Existe em dois caminhos (`monitor.handle_ev` e `PumpFun.run`) |
| Raio-X | `hub.xray` (`/trades/{mint}`) | auto a cada 30 min + botão | ≈ 300–1.500 (49 nas últimas 24 h; o plano era até 10/dia) | |
| Ganhos falsos | `hub.false_gains` (`/price/history/timestamp`) | ao abrir a aba (até 30 tokens por revisão) | variável | dispara muitas seguidas → estoura os 3/seg |
| Saldo dos traders (não é Solana Tracker) | `wallet_values_once` | RPC | — | |

## 3. As outras APIs (outubro, `api_usage`)

| API | Uso em outubro | Limite | Situação |
|---|---|---|---|
| RPC público da Solana | 363.208 | ~600/min e muitas recusas (429) | **Gargalo da cópia**: no dia 28, de 16.287 leituras, 14.161 chegaram atrasadas (0.32.7). A 0.32.8 diminuiu a pressão, mas a solução é RPC próprio |
| DexScreener | 79.422 | 300/min | ok |
| Jupiter | 29.778 | API pública com limitador | ok |
| RPC próprio (Helius, de um usuário) | 12.017 | do plano dele | só serve a carteira real desse usuário |
| PumpPortal | 16 (WebSocket) | — | ok |

## 4. O que mudar (por prioridade)

### A. Economia de créditos da Solana Tracker (sem custo, maior efeito)
1. **Carteiras em estudo: histórico a cada 6 h em vez de 30 min**, e na hora só ao adicionar a carteira (já é assim
   com `force=True`). Os trades novos continuam chegando ao vivo pelo monitor. **≈ 52.000 → ≈ 4.300/mês.**
2. **Ranking a cada 30 min** (`pump_lb_every_s` 600 → 1800, como era antes da 0.9.0). O "ativo agora" continua ao vivo
   pelo WebSocket. **≈ 4.300 → 1.440 por grupo.**
3. **Risco do token só para quem passou nos outros filtros** (market cap, compra mínima, posições, pausa…), cache de
   30 min, e a consulta `/stats` só quando for usar o fluxo. Unificar os dois caminhos. **Corta a maior parte.**
4. **Raio-X automático com teto diário de verdade** (10/dia como planejado) e **ganhos falsos com no máx. 2/seg**.
5. **Explorar: decidir 5 ou 10 min** (decisão do dono — mais fresco × metade do gasto: 8.640 → 4.320).

Com 1–4: ≈ 12–15 mil/mês com o Explorar a 5 min; ≈ 8–10 mil com o Explorar a 10 min. **Mesmo assim fica no limite do
grátis** — ver item C.

### B. Um "porteiro" único para a Solana Tracker (robustez)
Hoje cada parte chama a API por conta própria. Proposta: `app/stclient.py` usado por todos os pontos acima:
- **até 2 consultas/segundo por chave** (abaixo do limite de 3) e fila com prioridade:
  risco do token de cópia > Explorar > ranking > estudo > Raio-X/ganhos falsos;
- **"Insufficient credits" ou 401/403 → pausa a chave** por 1 h (não fica batendo), e 429 → espera e tenta de novo;
- **guarda o último resultado bom** (o robô usa os dados velhos marcados como "de X min atrás" em vez de ficar vazio);
- conta os erros por tipo (créditos, 429, 5xx, tempo esgotado) e lê `GET /credits` de hora em hora para mostrar
  **"créditos restantes"** por chave no Status do sistema e em Administração → uso de APIs;
- orçamento diário = créditos restantes ÷ dias até a renovação; acima disso, as partes de baixa prioridade param.

### C. Plano da Solana Tracker (decisão do dono)
O plano grátis só fecha a conta com o Explorar a 10 min e o resto enxuto. **Advanced: €50/mês, 200 mil consultas, sem
limite por segundo listado** — com A+B sobra muito. Rodízio de várias contas grátis continua fora (termos de uso,
decisão de 27/10).

### D. RPC próprio para o monitor (velocidade da cópia)
- Helius grátis: 1 milhão de créditos/mês, 10/seg (`getTransaction` = 1 crédito) — cobre os ~363 mil/mês de hoje.
  Developer US$ 49/mês: 10 milhões, 50/seg.
- No Portainer (stack `pump_bruxo_bode`): `SOLANA_RPC_PUBLIC` = endereço HTTPS do RPC e `PUMP_RPC_WS` = WSS. O RPC
  público fica como reserva onde o código já faz isso (ex.: `_rpc_retry`). Endereço com chave é segredo: só no
  Portainer, nunca no chat ou no Git.
- O RPC da Solana Tracker cobra 10 créditos por `getTransaction`: não compensa para o monitor.

## 5. Divisão sugerida entre os dois (evita conflito no Git)

| Quem | O quê | Arquivos |
|---|---|---|
| Bruxo95 (Claude) | B (`app/stclient.py` novo) + A1, A2, A4 | `app/stclient.py`, `app/hub.py` (estudo, Raio-X, ganhos falsos), `app/settings.py` (`pump_lb_every_s`) |
| Douglas (Claude/Codex) | A3 (risco só depois dos filtros, os dois caminhos) | `app/pumpfun.py` (`risk_check`, `_copy`), `app/monitor.py` (`handle_ev`) |
| Dono | C (plano) e D (RPC no Portainer), A5 (5 ou 10 min) | Portainer / painel da Solana Tracker |

Regra de sempre: `git pull` antes de começar e antes de enviar; versão nova a cada entrega.

## Fontes
- Solana Tracker, preços: https://docs.solanatracker.io/pricing
- Solana Tracker, créditos do RPC: https://docs.solanatracker.io/solana-rpc/credits
- Solana Tracker, consulta de créditos restantes (`GET /credits`): https://docs.solanatracker.io/data-api/credits/get-api-credits
- Helius, preços e planos: https://www.helius.dev/pricing · https://www.helius.dev/docs/billing/plans
