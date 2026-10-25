# PUMP.FUN Bruxo Bode

Sistema web multiusuário de cópia de traders da pump.fun. Login só com Google (Supabase), cada pessoa com o
próprio painel, carteira, configurações e chaves. Criado a partir da aba PUMP.FUN do `hermes-jev-trader` —
veja `docs/ORIGEM.md`.
Guia completo (uso, chaves, transações e APIs): **`docs/GUIA-DO-PROJETO.md`**.

- Endereço: **https://pump.rachar.app.br**
- Conferir a versão no ar: **https://pump.rachar.app.br/health** (a mesma aparece no rodapé do painel)
- Supabase: projeto `vnvfluimpqvxbvdbmwqa`

> Execução real começa DESLIGADA para todo mundo, volta a desligar sempre que o servidor reinicia e, além disso,
> fica travada no servidor enquanto `PUMP_REAL_ALLOWED=false`.

---

## Como funciona por dentro (resumo)

| Parte | Onde |
|---|---|
| Servidor (FastAPI) + páginas | `app/` e `web/` — uma imagem Docker só |
| Login | Google pelo Supabase Auth; o servidor confere o token em toda rota `/api/*` |
| Banco | Supabase (Postgres) com RLS em todas as tabelas — `supabase/migrations/` |
| Chaves pessoais | criptografadas (AES-256-GCM) com a `APP_ENCRYPTION_KEY` do servidor; a tela só mostra "configurada: sim/não" |
| Monitor | um só para todos (WebSocket da Solana com a união das carteiras seguidas) — `app/monitor.py` |
| Motor de cópia | um por usuário, mesma lógica do original — `app/pumpfun.py` |
| HTTPS | o Traefik que já roda na VPS (rede `vpsrachar`, certificado Let's Encrypt) |

---

## Instalação (uma vez)

### 1. Banco no Supabase
A migração **já foi aplicada** no projeto `vnvfluimpqvxbvdbmwqa`. Se um dia precisar recriar: Supabase →
**SQL Editor** → cole o conteúdo de `supabase/migrations/20261025000001_inicial.sql` → **Run**.

### 2. Login com Google
**a) Google Cloud** (console.cloud.google.com → APIs e serviços → Credenciais):
1. **Criar credenciais → ID do cliente OAuth → Aplicativo da Web.**
2. Origens JavaScript autorizadas: `https://pump.rachar.app.br`
3. URIs de redirecionamento autorizados: `https://vnvfluimpqvxbvdbmwqa.supabase.co/auth/v1/callback`
4. Copie o **ID do cliente** e a **Chave secreta**.

**b) Supabase** → Authentication:
1. **Sign In / Providers → Google** → ligar, colar o ID do cliente e a chave secreta → Save.
2. **URL Configuration** → Site URL: `https://pump.rachar.app.br` · Redirect URLs: `https://pump.rachar.app.br/app`
   (para testar no seu computador, adicione também `http://localhost:8080/app`).

### 3. DNS
Crie o registro `pump.rachar.app.br` apontando para o IP da VPS (igual aos outros `*.rachar.app.br`).

### 4. Imagem Docker (automática)
A cada `git push` no `main`, o GitHub roda os testes e, se passarem, publica a imagem
`ghcr.io/bruxo95/pump.fun_bruxo_bode:latest` (aba **Actions** do repositório mostra o andamento).

Como o repositório é privado, a VPS precisa de permissão para baixar a imagem (uma vez):
1. GitHub → Settings → Developer settings → **Personal access tokens (classic)** → novo token só com
   `read:packages`.
2. Portainer → **Registries → Add registry → Custom registry**: URL `ghcr.io`, usuário `Bruxo95`, senha = o token.

### 5. Chave mestra
Gere **uma vez** e guarde num lugar seguro (sem ela, as chaves salvas no painel não abrem mais):

```
python3 -c "import secrets,base64;print(base64.b64encode(secrets.token_bytes(32)).decode())"
```

### 6. Stack no Portainer
Portainer → **Stacks → Add stack** → nome `pump_bruxo_bode` → **Web editor** → cole `deploy/portainer-stack.yml`.

Em **Environment variables** adicione (valores do Supabase em Project Settings → API):

| Nome | Valor |
|---|---|
| `SUPABASE_ANON_KEY` | chave anon / publishable (pública) |
| `SUPABASE_SERVICE_ROLE_KEY` | chave service_role / secret (**secreta**) |
| `APP_ENCRYPTION_KEY` | a chave mestra do passo 5 |

Marque o registry do `ghcr.io` e clique **Deploy the stack**. Confira em `https://pump.rachar.app.br/health`.

### 7. Primeiro acesso
Entre com o Google. **O primeiro usuário vira admin** (vê o status geral em Configurações, nunca as chaves dos
outros). Em Configurações → Chaves pessoais, cole a chave grátis da Solana Tracker para o ranking oficial.

---

## Atualização automática (recomendado, uma vez)
1. Portainer → **Services** → `pump_bruxo_bode_pump_bruxo_bode` → ligue **Service webhook** → copie a URL.
2. GitHub → repositório → **Settings → Secrets and variables → Actions → New repository secret**:
   nome `PORTAINER_WEBHOOK_URL`, valor = a URL copiada.
3. Pronto: a cada push no `main`, o GitHub testa, publica a imagem e manda o Portainer atualizar sozinho.
   O último passo do Actions mostra a resposta de `/health`.

A URL do webhook é secreta (quem tiver ela consegue reiniciar o serviço): não coloque no código nem no chat.

## Atualizar manualmente (se não usar o webhook)
1. Espere o GitHub terminar a imagem (aba **Actions**, bolinha verde).
2. Portainer → Stacks → `pump_bruxo_bode` → **Update the stack** → marque **Re-pull image and redeploy** → Update.
3. Confira a versão em `/health` ou no rodapé do painel.

As posições, histórico, listas e configurações ficam no Supabase: atualizar/reiniciar não perde nada.
A execução real volta DESLIGADA (de propósito).

## Rodar no seu computador (opcional)
Copie `.env.example` para `.env`, preencha, e: `docker compose up -d --build` → `http://localhost:8080`.
(O Google aceita `localhost` sem HTTPS; lembre de pôr `http://localhost:8080/app` nas Redirect URLs do Supabase.)

## Execução real (quando chegar a hora)
1. No `.env`/Portainer: `PUMP_REAL_ALLOWED=true` e atualize o stack.
2. No painel: Configurações → Chaves → carteira Solana **nova, só para o bot, com pouco saldo**.
3. Execução real → botão vermelho → digitar `LIGAR`. Tudo fica no registro de segurança (audit_log).

## Testes
`pip install -r requirements.txt pytest && pytest -q` — nenhum teste usa internet. O teste de isolamento do
banco (`tests/test_rls_postgres.py`) roda num Postgres local se existir na máquina; senão é pulado.

## Por que Traefik e não Caddy
A ideia inicial era Caddy, mas a VPS já tem o Traefik ocupando as portas 80/443 com certificados automáticos
para `*.rachar.app.br`. O stack segue o mesmo padrão dos outros serviços (rede `vpsrachar`, `letsencryptresolver`).
