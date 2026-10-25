# De onde veio cada parte (etapa 1)

Origem: `github.com/Bruxo95/hermes-jev-trader`, branch `main`, commit `d91aa5e`
(versão `2026-10-25.1`). Só a aba **PUMP.FUN** foi trazida. Futuros, Spot, Solana DEX,
DEX-CEX, Relógio, Macro, Hermes/Jev e Gate.io **ficaram de fora**.

| Original | Novo | O que mudou |
|---|---|---|
| `app/pumpfun.py` (classes `PumpFun`, `PumpReal`) | `app/pumpfun.py` | Mesma lógica de cópia. Dados públicos (tokens, carteiras vistas, atividade, saldo dos traders) passam a ficar num `PumpMarket` compartilhado; posições, histórico, listas e feed ficam num "store" por usuário (memória nos testes, Supabase em produção). |
| `app/dexcex_exec.py` (`_swap_tx`, `_send_and_confirm`, `best_quote`, `_dex_swap`, `sol_balances`, `usdc_to_sol`, `_rpc`) | `app/jupiter.py` | Só a parte da Jupiter, sem nada da Gate.io. |
| `app/solana_dex.py` (`_quote`, limitador de consultas, `DEXES`) | `app/jupiter.py` | Cotação compartilhada entre todos os usuários (um limitador só). |
| `app/solana_wallet.py` (`parse_keypair`, `WalletStore`) | `app/solana_wallet.py` | A chave não fica mais em arquivo: vem do banco, descriptografada só na memória do servidor. |
| `app/keystore.py` | `app/keystore.py` | Vira `KeyRing` em memória por usuário; gravação criptografada no Supabase. |
| `app/logbuf.py` (máscara de segredos) | `app/logsafe.py` | Só a parte que esconde chaves nos logs. |
| `app/config.py` (todas as opções `PUMP_*`) | `app/settings.py` | Viram configurações **por usuário** (mesmos padrões). As que mexem no monitor compartilhado ficam só no `.env` do servidor. |
| `app/web.py` (aba PUMP.FUN: HTML + JS, endpoints `/api/pump/*`, sons) | `web/` + `app/api.py` | HTML/JS saem da string Python e viram arquivos estáticos; todas as rotas exigem login (JWT do Supabase). |
| `tests/test_offline.py` (27 testes `test_pump_*` + `test_wallet_usdc_to_sol_swap`) | `tests/test_pump.py` | Mesmos cenários, adaptados para o novo formato; nenhum usa internet. |

## Opções PUMP_* — por usuário × servidor

**Por usuário** (cada um muda no próprio painel): valor da cópia, saldo fictício, espera antes de copiar,
cópia fora da pump.fun (fictício/real), stop de perda, stop móvel, segurar até lucro, alvo, tempo máximo,
pausa automática, filtros de token e de trader, limites de posições, taxas/slippage simulados, top N,
período do leaderboard, trades e acerto mínimos, e todo o bloco de execução real.

**Do servidor** (`.env`, valem para o monitor compartilhado): `PUMP_ENABLED`, `PUMP_WS_URL`,
`PUMP_RPC_WS`, `PUMP_RPC_HTTP`, `PUMP_PRICE_EVERY_S`, `PUMP_DS_EVERY_S`, `PUMP_TRACK_TOKENS`,
`PUMP_MAX_TX_MIN`, `PUMP_LB_EVERY_S`, `PUMP_LB_PLATFORM`, `PUMP_WALLET_CHECK_S`, `PUMP_RANK_EVERY_S`,
`PUMP_PAID_STREAM`.
