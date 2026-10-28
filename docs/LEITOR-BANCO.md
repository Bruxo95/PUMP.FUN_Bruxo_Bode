# Acesso só de leitura ao banco para a IA (0.32.2)

Pedido do dono em 2026-10-28 (caminho 1 da conversa: "usuário só leitura"). Serve para a IA ler sozinha trades, sombras,
calls e logs de todas as contas, **sem conseguir mudar nada**. Mudanças continuam indo só pelo GitHub.

## O que já está pronto (feito pela migração `20261028000009_leitor_ia_somente_leitura.sql`)
- Usuário de banco `leitor_ia`, que nasce **sem poder entrar** (sem senha).
- Ele só faz `SELECT`; toda transação é somente leitura e cada consulta para em 30 s.
- Ele **não lê** `user_secrets`, `app_secrets` nem `audit_log`; de `profiles` vê só nome, categoria e bloqueado (sem e-mail).
- O leitor `scripts/ler_banco.py` usa só o Python padrão (nada instalado) e também recusa o que não for consulta.

## O que o dono faz (uma vez, uns 3 minutos)
1. **Criar a senha.** Supabase → projeto `vnvfluimpqvxbvdbmwqa` → menu da esquerda **SQL Editor** → **New query**.
   Cole a linha abaixo, troque `TROQUE-POR-UMA-SENHA-FORTE` por uma senha longa (só letras e números, 30+ caracteres)
   e clique **Run**:

   ```sql
   alter role leitor_ia with login password 'TROQUE-POR-UMA-SENHA-FORTE';
   ```
   Deve aparecer "Success. No rows returned".

2. **Pegar o endereço.** No topo do projeto, botão **Connect** → aba **Connection String** → tipo **URI** →
   **Session pooler**. Aparece algo como
   `postgresql://postgres.vnvfluimpqvxbvdbmwqa:[YOUR-PASSWORD]@aws-0-XX.pooler.supabase.com:5432/postgres`.

3. **Salvar no PC (não no chat).** Crie o arquivo `C:\Users\doug\.secrets\pump.env` com UMA linha, trocando
   `postgres.` por `leitor_ia.` e `[YOUR-PASSWORD]` pela senha do passo 1:

   ```
   PUMP_DB_URL=postgresql://leitor_ia.vnvfluimpqvxbvdbmwqa:SUA-SENHA@aws-0-XX.pooler.supabase.com:5432/postgres
   ```

4. Avise a IA: "salvei o pump.env". Ela roda `py -I scripts/ler_banco.py --teste` e confirma.

## Para desligar o acesso
SQL Editor: `alter role leitor_ia nologin;` (volta a não entrar). Para trocar a senha, repita o passo 1.

## Limites
- Sem `PUMP_DB_CA` no arquivo, a conexão é cifrada mas não confere o certificado (igual ao `sslmode=require` do psql).
  Para conferir, baixe o certificado em Supabase → Database → Settings → SSL Configuration e acrescente
  `PUMP_DB_CA=C:\Users\doug\.secrets\supabase-ca.crt`.
- A pasta `C:\Users\doug\.secrets` já está no `copiar-antes-de-formatar.ps1`.
