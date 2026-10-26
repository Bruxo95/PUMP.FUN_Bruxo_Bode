# Plano: entrada automática por "chance alta" no Explorar e na Base, com proteções, tela de operações e estudo no banco

Escrito em 2026-10-26 (aplicação 0.29.0, commit base `4cadfc6`) por Claude Opus 5.5, a pedido do dono, para o Codex
implementar **exatamente como está aqui**. Leia antes o `CLAUDE.md` (regras do projeto) e confira o código: os nomes
de funções citados existem na 0.29.0.

## 0. Regras que valem para tudo

- Tudo novo começa **DESLIGADO** e só no **simulado (carteira fictícia)**. Compra real só se `pump_auto_real` estiver
  ON **e** a execução real estiver ligada (que hoje fica travada por `PUMP_REAL_ALLOWED=false`). Não mexer nessa trava.
- Durante o desenvolvimento, **nenhuma transação real**.
- Rotas novas: só admin (`admin_engine` / `admin_only`, como as outras de "Usar ou descartar").
- Testes sem internet (`httpx.MockTransport`), `pytest -q` verde antes de cada push.
- Cada entrega: subir a versão em `app/version.py`, entrada no topo de `app/novidades.json`, atualizar o inventário
  (`py scripts/inventario_dependencias.py --refresh --date AAAA-MM-DD` e `--check`), registrar no `CLAUDE.md`,
  `git pull --rebase` antes do push. Botões ON/OFF: verde = ON, vermelho = OFF. Marca NOVO (`data-novo-ate`).
- Migração nova = arquivo novo em `supabase/migrations/` (`AAAAMMDDHHMMSS_nome.sql`); nunca editar as já aplicadas.
- Sugestão de entregas: **0.30.0** = etapas 1 a 4 (Explorar); **0.31.0** = etapa 5 (Base); **0.32.0** = etapa 6
  (aprendizado). Uma versão por vez, conferindo o Actions e o `/health` entre elas.

## 1. Margens de segurança (valores padrão sugeridos)

O dono pediu para "não perder". **Não existe garantia**: memecoin da pump.fun perde na maioria das vezes. Estas regras
servem para perder pouco quando erra e deixar correr quando acerta. Todos os valores ficam editáveis na tela, com
estes padrões:

| Regra | Padrão | Por quê |
|---|---|---|
| Valor por entrada automática (fictícia) | **0,05 SOL** | pequeno: o objetivo agora é medir, não lucrar |
| Máx. posições automáticas abertas ao mesmo tempo | **3** | uma onda ruim não leva tudo |
| Máx. entradas automáticas por hora | **4** | evita metralhar em mercado agitado |
| Perda máxima do dia (só automáticas) | **−0,25 SOL** → pausa as entradas automáticas até 00:00 UTC | trava o prejuízo do dia |
| Pausa por perdas seguidas | **3 perdas seguidas → pausa 1 h** | reaproveitar a ideia de `_streak_check`, mas só para as automáticas |
| Stop de perda | **−25%** | sai cedo do erro |
| Venda em partes | **+40% → vende 50%** | garante lucro cedo |
| Stop móvel (no resto) | **liga em +40%, sai 15 pontos abaixo do pico** | deixa correr o que está subindo |
| Alvo final | **+150%** (vende o resto) | trava ganho grande |
| Com Boost ON | **vende tudo em +80%** | regra já pedida pelo dono (0.26.0) |
| Tempo máximo na posição | **30 min** | memecoin parada costuma morrer |
| Saídas inteligentes | **ON nessas posições**: dev vendeu, pressão < 40% depois de 1 min, token graduou (se comprou na curva) | reaproveitar `PumpFun.smart_exit` |

Filtros de entrada (todos precisam passar, além do veredito "chance alta"):

- não é "lixo"/"suspeito"; criador fora da lista negra e sem 2+ tokens despencados (já existe nos vereditos);
- **pressão de compra ≥ 60%**; **holders ≥ 100** (Explorar); **risco ≤ 6/10** quando houver nota;
- **variação em 5 min entre 0% e +150%** (subindo, mas sem correr atrás de pico);
- no Explorar, lista "Quase graduando": **curva entre 60% e 95%**; nas outras listas não entra automático na 1ª versão;
- na Base: idade do token ≤ 15 min (já existe `pump_auto_max_age`);
- nunca o mesmo token duas vezes em 24 h (guardar no banco, ver etapa 3, para valer depois de reiniciar).

Critério para pensar em dinheiro real (mostrar na tela, não ligar nada sozinho): **pelo menos 100 operações
automáticas no simulado, em pelo menos 7 dias, com acerto ≥ 45% e fator de lucro (ganhos ÷ perdas) ≥ 1,3 já com
taxas**. Enquanto não bater, a tela mostra "ainda não recomendado para dinheiro real".

## 2. Etapa 1 — opções novas (app/settings.py, `USER_KEYS`)

Explorar (prefixo `pump_ex_auto_`) e regras de risco compartilhadas pelas automáticas (`pump_ar_`):

```
"pump_ex_auto_on": (bool, False, 0, 1),            # Explorar: entra sozinho em "chance alta"
"pump_ex_auto_min_pressure": (float, 60.0, 0.0, 100.0),
"pump_ex_auto_min_holders": (int, 100, 0, 1000000),
"pump_ex_auto_max_risk": (int, 6, 1, 10),
"pump_ex_auto_curve_min": (float, 60.0, 0.0, 100.0),
"pump_ex_auto_curve_max": (float, 95.0, 0.0, 100.0),
"pump_ex_auto_max_chg5": (float, 150.0, 0.0, 10000.0),
"pump_ar_sol": (float, 0.05, 0.001, 100.0),       # valor por entrada automática (fictícia)
"pump_ar_max_open": (int, 3, 1, 50),
"pump_ar_max_h": (int, 4, 1, 100),
"pump_ar_daily_loss": (float, 0.25, 0.0, 1000.0),  # 0 desliga
"pump_ar_streak_n": (int, 3, 0, 50),               # 0 desliga
"pump_ar_streak_h": (float, 1.0, 0.1, 72.0),
"pump_ar_stop_pct": (float, 25.0, 1.0, 100.0),
"pump_ar_tp1_pct": (float, 40.0, 0.0, 10000.0),     # 0 desliga a venda em partes
"pump_ar_tp1_frac": (float, 50.0, 1.0, 99.0),
"pump_ar_trail_start": (float, 40.0, 1.0, 10000.0),
"pump_ar_trail_dist": (float, 15.0, 1.0, 1000.0),
"pump_ar_tp_pct": (float, 150.0, 0.0, 10000.0),
"pump_ar_max_hold_min": (float, 30.0, 1.0, 1440.0),
"pump_ar_smart": (bool, True, 0, 1),               # dev vendeu / pressão < 40% / graduou nessas posições
```

A Base continua usando `pump_auto_on`, `pump_auto_boost`, `pump_auto_chance`, `pump_auto_max_age`, `pump_auto_max_h`,
`pump_auto_real`, mas as **compras automáticas** (Base e Explorar) passam a usar as regras `pump_ar_*` (valor, stop,
venda em partes, stop móvel, alvo, tempo máximo). O botão **Comprar** manual continua com `pump_manual_*`.

## 3. Etapa 2 — motor (app/pumpfun.py)

1. `auto_rules()` (novo, ao lado de `manual_rules()`): devolve `stop_pct`, `tp_pct`, `trail_on=True`, `trail_start`,
   `trail_dist`, `boost_tp` (de `pump_manual_boost_*`), `tp1_pct`, `tp1_frac`, `max_hold_s`, `smart=True/False`.
2. `manual_buy(mint, t, auto="", origem="", info=None)`: quando `auto` vier preenchido, usar `pump_ar_sol` e
   `auto_rules()` em vez de `pump_manual_sol`/`manual_rules()`. Gravar na posição: `origem` ("explorar" ou "base"),
   `auto_info` (dict com veredito, chance e os números do momento da entrada; ver etapa 3) e `auto=True`.
3. `_check_stops`: quando a posição tiver `tp1_pct`, usar ele (e `tp1_frac`) no lugar das opções gerais
   `pump_tp1_*`; quando tiver `max_hold_s`, vender por "tempo máximo" ao passar disso (hoje o tempo máximo é geral,
   em `check_timeouts`; incluir lá também a regra por posição). Quando `smart` for True, aplicar as três saídas de
   `smart_exit` **só para essa posição**, mesmo com as opções gerais desligadas (dev vendeu; pressão < 40% após 60 s;
   graduou com `grad_in=False`). Hoje `smart_exit` lê só as opções gerais: acrescentar um parâmetro `force=True`.
4. Travas das automáticas (função nova `auto_guard()` usada por Base e Explorar antes de comprar): conta posições
   abertas com `auto=True` (≤ `pump_ar_max_open`), entradas na última hora (≤ `pump_ar_max_h`, somando Base e
   Explorar), perda do dia das automáticas fechadas hoje (UTC) ≥ `pump_ar_daily_loss` → bloqueia, sequência de
   perdas das automáticas ≥ `pump_ar_streak_n` → bloqueia por `pump_ar_streak_h`. Devolve o motivo do bloqueio para
   aparecer na tela e no Feed ("compra automática pausada: perda do dia").
5. `auto_check` (Base) passa a chamar `auto_guard()` e `manual_buy(..., auto=..., origem="base", info=...)`.
6. `explore_auto_check(lists)` (novo, Explorar): percorre `lists["graduating"]` do `Explore.snapshot`, aplica os
   filtros da seção 1 e o veredito "chance alta", chama `auto_guard()` e `manual_buy(..., origem="explorar")`.
   Antes de comprar, garantir preço: se `self.tokens[mint]` não tiver `price`, quem chama (monitor) busca com
   `svc._curve_prices([mint], public_first=True)` e, se ainda faltar, `svc._fetch_prices([mint])`.
7. Trade fechado: copiar `origem`, `auto`, `auto_info` para o trade (como já é feito com `score`, `manual`).

## 4. Etapa 3 — banco e estudo (migração `AAAAMMDDHHMMSS_operacoes_auto.sql`)

Tabela **`auto_trades`** (uma linha por operação automática, Base ou Explorar):

```
id text primary key            -- mesmo id da posição/trade
user_id uuid not null references auth.users (id) on delete cascade
origem text not null check (origem in ('base','explorar'))
real boolean not null default false
mint text not null, symbol text
entrada_em timestamptz not null, saida_em timestamptz
sol_in double precision, pnl_sol double precision, pnl_pct double precision
motivo_saida text, best_pct double precision, worst_pct double precision
veredito text, chance double precision
info jsonb not null default '{}'   -- pressão, holders, curva, risco, variação 5 min, boost, criador, nota, motivos
depois jsonb not null default '{}' -- {"15m": %, "60m": %} preço depois da saída × preço de saída
```

RLS: `enable row level security`; política de leitura só das próprias linhas (`user_id = (select auth.uid())`);
`revoke insert, update, delete ... from anon, authenticated` (igual a `learning_daily`). Índice `(user_id, entrada_em desc)`.

Gravação (app/hub.py, mesmo padrão de `save_ghosts`/`save_lab`):
- ao abrir: upsert com os dados de entrada; ao fechar: upsert com saída, resultado, motivo, melhor/pior momento;
- **"continuou ou parou depois que saí"**: ao fechar, guardar em memória `{mint, preço de saída, hora}`; o monitor
  segue o preço desses tokens por 60 min (incluir na lista de preços como os fantasmas, `SharedMonitor.held`) e grava
  em `depois` a variação aos 15 e aos 60 min. Texto na tela: "subiu +X% depois que saiu" / "caiu −X% depois".
- carregar na partida as operações das últimas 24 h para saber "não repetir o mesmo token em 24 h".
- `tests/fakes.py`: acrescentar `"auto_trades": ("id",)` em `PKS`.

## 5. Etapa 4 — telas (web/app.html, web/app.js)

Em **Explorar** (`#explorar`), acima das listas:
1. Quadro **"Entrada automática (chance alta)"**: botão ON/OFF `pump_ex_auto_on`, os filtros da seção 1 com os
   valores já preenchidos e botões rápidos, e o quadro **"Proteções das automáticas"** (`pump_ar_*`) — o mesmo
   quadro aparece na Base (um só conjunto de valores). Mostrar o estado: "ativa", "pausada: perda do dia (−0,25 SOL)"
   ou "pausada: 3 perdas seguidas até 14:20".
2. Quadro **"Minhas operações automáticas"** (pequeno, logo abaixo), lendo uma rota nova
   `GET /api/pump/auto-trades?origem=explorar` (admin): colunas **Token · Entrou (hora, valor, veredito e chance) ·
   Situação (aberta / fechada) · Resultado (SOL e %) · Saiu (hora) · Por que saiu (stop, venda em partes, stop móvel,
   alvo, tempo máximo, dev vendeu, pressão virou, boost) · Duração · Melhor momento · Depois que saiu (15 e 60 min)**.
   No topo: total do dia e do período, acerto, fator de lucro e o aviso do critério para dinheiro real (seção 1).

Na **Base da pump.fun** (`#base`): o mesmo quadro "Minhas operações automáticas" com `origem=base`, logo abaixo de
"Compra automática". O quadro de compra automática ganha o estado de pausa e passa a citar as proteções `pump_ar_*`.

Texto "Como funciona" curto em cada um, explicando que é estimativa, que começa no simulado e o critério para real.

## 6. Etapa 5 — Base usa as mesmas proteções

`auto_check` da Base: mesma `auto_guard()`, mesmas regras `pump_ar_*`, gravar em `auto_trades` com `origem="base"`.
Mantém as regras próprias da Base (Boost ON, chance alta, idade ≤ 15 min, nunca lixo/suspeito).

## 7. Etapa 6 — aprender com as operações (estudo)

Rota `GET /api/pump/auto-study` (admin) e quadro **"O que as automáticas ensinaram"** em Explorar e Base:
- por **origem**, por **veredito/chance** (faixas 0–20, 20–40, 40–60, 60+%), por **pressão** (60–70, 70–80, 80+),
  por **curva** (60–80, 80–90, 90–95), por **holders** (100–200, 200–500, 500+), **Boost ON/OFF**, **variação em
  5 min** (0–30, 30–80, 80–150%) e **motivo de saída**: nº de operações, acerto, resultado médio, fator de lucro;
- linha "faixas que perdem dinheiro": faixas com 30+ operações e resultado médio negativo depois das taxas;
- opção `pump_ar_learn` (bool, padrão **OFF**): quando ON, a entrada automática **pula** as faixas da linha acima e
  mostra no Feed "não entrou: faixa X perde dinheiro (N operações)". Nunca afrouxa filtro sozinha, só aperta.
- "Depois que saiu": % das saídas em que o token subiu mais de 30% nos 60 min seguintes, por motivo de saída
  (mostra se o stop está apertado demais). Só mostrar o número, sem mudar regra sozinho.

## 8. Testes obrigatórios (novos arquivos em `tests/`)

- `test_auto_explorar.py`: sem `pump_ex_auto_on` não compra; com ON compra só "chance alta" que passa em todos os
  filtros (um teste por filtro barrando); usa `pump_ar_sol` e grava `stop_pct=25`, `tp1_pct=40`, `max_hold_s=1800`;
  não repete o token; real nunca é acionado com `pump_auto_real` OFF.
- `test_auto_protecoes.py`: máx. abertas, máx. por hora (somando Base + Explorar), perda do dia pausa até 00:00 UTC,
  3 perdas seguidas pausam 1 h; venda em partes em +40% e stop móvel no resto; tempo máximo 30 min; dev vendeu e
  pressão < 40% vendem só as posições automáticas (as cópias continuam com as opções gerais).
- `test_auto_trades_db.py`: abre/fecha grava em `auto_trades`; `depois` preenchido aos 15/60 min com preço simulado;
  rota só admin (403 para usuário comum, 401 sem login); carrega as últimas 24 h na partida.
- `test_auto_study.py`: faixas e fator de lucro calculados certo; `pump_ar_learn` ON pula faixa com 30+ operações e
  resultado médio negativo; OFF não pula.
- Rodar a suíte inteira (`pytest -q`); os testes antigos (`test_pump_*`, `test_auto.py`, `test_botao_comprar.py`)
  têm que continuar passando sem mudar o que eles conferem.

## 9. Pronto quando

- Explorar e Base entram sozinhos (simulado) em "chance alta" que passa nos filtros, com as proteções da seção 1;
- "Minhas operações automáticas" mostra cada operação com entrada, saída, motivo, resultado e o que o token fez depois;
- tudo fica em `auto_trades` no banco e sobrevive à publicação de uma versão nova;
- "O que as automáticas ensinaram" mostra as faixas que ganham e as que perdem;
- Actions verde e `/health` com a versão nova; entrada no `novidades.json` e registro no `CLAUDE.md`.

## 10. Dicas para o dono (não é código)

- Deixe rodar **só no simulado** por pelo menos 1 a 2 semanas e olhe o fator de lucro, não só o acerto.
- O Explorar atualiza a cada 5 min (limite da Solana Tracker): ele chega **atrasado** em token que dispara em
  segundos. A Base (curva on-chain a cada 20 s) é mais rápida; compare as duas origens no estudo antes de confiar.
- Se "Depois que saiu" mostrar muitos tokens subindo forte depois do stop, aumente o stop aos poucos (25% → 30%);
  se mostrar quedas grandes depois do alvo, o alvo está bom.
- Ligue o Telegram para acompanhar sem abrir o painel.
