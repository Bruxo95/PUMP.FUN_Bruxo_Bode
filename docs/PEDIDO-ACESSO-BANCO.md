# Pedido do acesso ao banco (arquivo pump.env)

O arquivo `C:\Users\doug\.secrets\pump.env` deixa a IA **só ler** o banco, para cruzar trades, abas, saídas e estudos com números reais.
Ele não muda nada no banco e não lê chaves, e-mails nem o registro de ações.

O modelo já está neste PC, nesse caminho, sem senha. Falta só a linha verdadeira.

## Mensagem para mandar ao outro desenvolvedor

> Preciso do acesso de leitura ao banco do PUMP FUN COPY neste PC.
> Você tem o arquivo `pump.env`, com uma linha que começa com `PUMP_DB_URL=`?
> Ela tem este formato:
> `PUMP_DB_URL=postgresql://leitor_ia.vnvfluimpqvxbvdbmwqa:SENHA@aws-0-REGIAO.pooler.supabase.com:5432/postgres`
> Preciso de duas informações: a **senha** do usuário `leitor_ia` e o **endereço do servidor**, a parte `aws-0-REGIAO.pooler.supabase.com`.
> Se você também usa uma linha `PUMP_DB_CA=`, me avise.
> Por favor, não mude a senha e me mande isso por um canal seguro, não em grupo.

## O que fazer quando receber

1. Abra `C:\Users\doug\.secrets\pump.env` no Bloco de Notas.
2. Troque `COLE-A-SENHA-AQUI` pela senha e `aws-0-REGIAO` pelo endereço recebido.
3. Salve e avise a IA: "salvei o pump.env". **Não cole a senha no chat.** A IA testa sozinha.

## Cuidados

- **Não crie outra senha no Supabase sem combinar.** Trocar a senha derruba o acesso do outro PC.
- Se o outro desenvolvedor não tiver mais o arquivo, o passo a passo para criar do zero está em `docs/LEITOR-BANCO.md`. Combine antes, pelo motivo acima.
- Não salve esse arquivo dentro de `C:\xampp\htdocs`: o Apache serve essa pasta.
