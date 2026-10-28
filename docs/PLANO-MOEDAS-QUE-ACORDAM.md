# Plano: estudar moedas que "acordam" (dormentes que voltam a subir)

Pedido do dono em 2026-10-28, para ser feito numa **outra sessão do Claude**. Este arquivo é o ponto de partida: leia
também o `CLAUDE.md` (regras do projeto) antes de mexer em qualquer coisa.

## O que o dono quer

Exemplo citado: **PUMP** (`pumpCmXqMfrsAkQ5r49WcJnRayYRqmXz6ae8H7H9Dfn`, market cap ~US$ 1,7 bi, volume 24 h ~US$ 2,6 mi,
404 mil holders). No gráfico de 4 h aparecem vários "avatares" de traders fortes comprando e vendendo, períodos de
subida forte, depois o preço "dorme" (lateral) e de repente alguém injeta muito dinheiro e ele volta a subir.

Objetivo: **entender a lógica para entrar no começo e saber a hora de sair**. Em especial:
1. Moedas grandes/antigas (começar com um **top 10**) que tiveram muito pump, pararam e, depois de um tempo, **voltaram a
   receber dinheiro** (volume e compras fortes de carteiras grandes).
2. Saber **quem** entrou no começo da volta (carteiras fortes, maiores traders, carteiras em estudo).
3. Saber **quando sair** (sinais de que a onda acabou: os mesmos compradores vendendo, volume caindo, despejo).
4. **Deixar tudo salvo** (banco) e virar aprendizado, como já é feito com o Explorar e as Calls quentes.

## O que já existe no sistema e deve ser reaproveitado (não duplicar)

- **Raio-X do token** (`app/raiox.py`, 0.31.86): lê negociações pela Solana Tracker `GET /trades/{mint}` (até 500 por
  consulta, 1 crédito). Hoje lê as PRIMEIRAS 500 (`sortDirection=ASC`); para "acordar" precisa ler as **mais recentes**
  (`DESC`) e/ou paginar com `cursor` dentro de um período.
- **Calls quentes** (`app/calls.py`, 0.31.94): toda compra de carteira acompanhada vira call, com resultado aos
  5/15/60 min, pico e despejo. Uma compra grande de carteira forte numa moeda dormente é exatamente uma "call".
- **Maiores traders** (`app/elite.py`): top por lucro da Solana Tracker; desde a 0.31.95 as compras deles são lidas.
- **Logs dos robôs** (`robot_log`, `robot_daily`) e **Base geral** (sombras, aprender com os erros): todo módulo novo
  deve gravar log de análise e resumo diário, sem apagar nada.
- **Preços**: DexScreener (grátis, 300/min) e cotação da Jupiter; volume por pool já é lido (`tokens[m]["pools"]`).
- **Medidor de uso das APIs** (Administração): a cota grátis da Solana Tracker pode ser só 2.500/mês (o dono ainda vai
  mandar o print). **Não gastar consultas à toa**: preferir DexScreener (grátis) e só chamar a Solana Tracker quando
  um token for candidato.

## Proposta de etapas (fazer em ordem, cada uma publicada separada)

1. **Lista de vigiadas** (`dormentes`): começar com um top 10 de moedas grandes da pump.fun/PumpSwap (escolha do dono,
   com o PUMP), com tela para adicionar/remover. Para cada uma, a cada 5 min pela DexScreener: preço, volume 5 min/1 h/24 h,
   compras × vendas, liquidez. Guardar série no banco (tabela nova, migração nova `AAAAMMDDHHMMSS_nome.sql`).
2. **Detector de "acordou"**: definir "dormente" (ex.: volume 1 h abaixo de X% da média de 7 dias e preço lateral) e
   "acordou" (volume 5 min/1 h muito acima da média + compras > vendas + preço saindo da faixa). Valores iniciais
   documentados e ajustáveis; registrar cada despertar com hora, preço e volume.
3. **Quem acordou a moeda**: no despertar, um Raio-X das negociações MAIS RECENTES (1 crédito): maiores compradores,
   se são carteiras conhecidas (Maiores traders, em estudo, copiadas), compra única grande × várias compras.
4. **Resultado e saída**: medir o preço 15 min, 1 h, 4 h e 24 h depois do despertar e o pico; quando os mesmos
   compradores começaram a vender (despejo). Daí sai a "hora de sair" que funciona (ex.: X% do pico, ou quando o
   comprador grande vende).
5. **Veredito com %** do despertar (como Explorar e Calls quentes) e tela própria com botão Comprar (o mesmo `data-buy`).
6. **Log de análise + resumo diário** no menu Logs dos robôs, e o aprendizado na Base geral (o que dá lucro).
7. **Compra automática só depois e só na fictícia**, DESLIGADA por padrão, com OK do dono.

## Regras que a outra sessão precisa seguir (resumo do CLAUDE.md e da memória)

- Responder em português do Brasil, direto. Dizer o que mudou, a versão e o que não foi testado.
- **Não fazer transação real**; nada novo compra sozinho na real. Opção nova que muda compra começa DESLIGADA.
- **Nunca mudar configuração salva dos usuários** sem pedido explícito do dono.
- **Lógica do Explorar é intocável** sem OK do dono.
- **Não burlar Cloudflare/anti-robô**: a API do site da pump.fun (`frontend-api-v3.pump.fun`) responde 403. Usar
  Solana Tracker, DexScreener, Jupiter e a blockchain (RPC).
- Antes de cada push: `git pull --rebase`, `scripts/inventario_dependencias.py --refresh` e `--check`, subir a versão
  (`app/version.py`), entrada no topo de `app/novidades.json`, nota no fim do `CLAUDE.md`; deploy = só push no `main`
  do GitHub (o Actions testa e publica). Conferir `/health` depois.
- Python local não tem as dependências: testes "puros" rodam com `py`; os de integração rodam no Actions.
- Migração nova = arquivo novo; revisar o SQL (sem `WHERE` aberto, sem apagar dados).

## Texto pronto para colar na outra sessão

> Leia `CLAUDE.md` e `docs/PLANO-MOEDAS-QUE-ACORDAM.md` no repositório `C:\xampp\htdocs\PUMP.FUN_Bruxo_Bode`. Faça a
> etapa 1 e a 2 do plano (lista de vigiadas com o top 10 + detector de "acordou", tudo salvo no banco, com tela e log),
> reaproveitando o que já existe. Não faça nada na carteira real. Antes de publicar, siga o fluxo de entrega do
> CLAUDE.md e me diga o que mudou, a versão e o que não foi testado.
