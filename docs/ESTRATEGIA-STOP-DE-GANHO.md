# Stop de ganho autônomo e revisão de entrada e saída (0.32.332, 13/11/2026)

Pedido do dono: "fazer uma estratégia sua autônoma de stop de ganho, ganhou 10% saiu fora, com tudo que já temos de histórico ... a
lógica da gente tá certa mas a estratégia de entrada e saída tá horrível; reveja Solana, Robinhood, BNB e os outros".

## 1. O que os dados já diziam (estudos 0.32.330 e 0.32.331, lidos no banco pela outra sessão)

| Achado | Número |
|---|---|
| Cópias em tokens da pump.fun (938) | média −8,4% por cópia |
| Melhor grade de stop × alvo nessas cópias | −6,8% (ainda negativa) |
| REAL desde 25/10 (187 trades) | −1,42 SOL; curva da pump.fun −30% por trade |
| Token que já tinha subido 100%+ em 15 min antes da cópia | −24% por cópia (44) |
| Token que tinha subido menos de 5% | −1,7% (290) |
| Trader "comprovado" (média ≥ 0 em 8+ cópias) nas cópias seguintes | −9,8% (69): o passado do trader não previu |
| Custo da ida e volta: fictícia simula ~9,5%; a REAL mediu 4,5% | a fictícia é pessimista no custo |

Conclusão honesta: **saída melhor diminui a perda, mas não vira lucro sozinha**. O problema principal é a entrada: copiar 11–14 s depois,
em token da curva, muitas vezes no topo.

## 2. O que foi feito nesta versão

### Saída: stop de ganho autônomo (Solana, Robinhood e BNB)
- A cada 10 min o robô refaz a conta por aba com as fictícias dos últimos 14 dias de todas as contas: para cada nível de +5% a +100%,
  quem passou pelo nível sai nele (menos 1 ponto de folga), quem não passou termina igual. Escolhe o que mais rende; sem base usa +10%; se
  nenhum ganhar das regras de hoje, a aba fica sem alvo.
- Depois que ele vende, a "sombra" segue o preço com as regras antigas e guarda o que teria acontecido. Assim o robô continua sabendo se o
  alvo ajuda e pode subir, descer ou desligar sozinho.
- Fica de fora: Explorar (lógica que dava lucro; chave própria, desligada), Copiar igual, botão Comprar, Copiar trades de usuário.
- REAL: a espelhada sai junto da fictícia (regra do espelho). A REAL sem par tem chave própria, desligada. A REAL continua desligada.

### Entrada
- Filtro "token já subiu 100% em 15 min" ligado por padrão (era só na conta do Bruxo). Quem já salvou outro valor fica com o dele.
- O cérebro também mede **onde a entrada perde** por aba (hora, atraso, market cap, nota; na Robinhood, preço acima do trader). Só mostra.

## 3. Propostas que ficam para decidir (não feitas)
1. **Custo da fictícia**: a folga simulada de 3% por lado deixa a ida e volta em ~9,5%, mas a REAL mediu 4,5%. Ajustar para ~1,5% por lado
   faria a fictícia medir a realidade. Muda todos os resultados fictícios daqui em diante, por isso precisa do OK do dono.
2. **Barrar as faixas de entrada ruins** quando o cérebro mostrar a mesma faixa ruim por 7+ dias (com sombra para poder liberar depois).
3. **Medir stop + alvo juntos** com o `sg_hits` (já gravado a partir desta versão) e deixar o robô escolher também o stop, só mais curto.
4. **Copiar só fora da curva** também na fictícia de quem quiser (a 0.32.330 fez isso só na REAL).
5. Jev Trade e Aba do Bruxo: as posições delas na carteira já seguem o stop de ganho da aba; a simulação global do Jev Trade não mudou.
6. Dormant: compra manual de longo prazo; não tem saída automática, então o stop de ganho não se aplica. Dá para criar um aviso "chegou a +X%".
