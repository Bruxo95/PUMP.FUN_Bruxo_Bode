# Transmissor da SALA LIVE (sem OBS) — 0.32.364

Pedido do dono em 15/11/2026: transmitir a live do BOT LIVE de um PC separado, com Docker no Portainer, sem pesar a VPS do site.

- **PC do transmissor:** 192.168.178.65 (Portainer em `https://192.168.178.65:9443`)
- **VPS do site:** 192.168.178.62 (não muda nada nela)

## Como funciona

Cada container abre o **link do OBS** do `/botlive` num Chromium sem tela (Xvfb), toca o som numa placa de som virtual
(PulseAudio) e manda vídeo + som por RTMP com o `ffmpeg` (x264 + AAC). É o mesmo que o OBS faz com a fonte "Navegador",
sem a parte gráfica do OBS.

- `live-web`: horizontal 1920×1080 (YouTube).
- `live-vertical`: vertical 1080×1920 (TikTok, Shorts, Reels).

Serviço sem `LINK` ou sem chave fica parado, sem gastar processador.

- **Se cair:** a transmissão volta sozinha em 5 s, e o navegador reabre se fechar.
- **Reabertura programada:** o navegador também reabre a cada 12 h, para não acumular memória (`REINICIAR_H`).
- **Rede local:** `extra_hosts` faz o navegador do container buscar `pump.rachar.app.br` direto na VPS do site (192.168.178.62, variável `SITE_IP`); só o vídeo sai pela internet.
- **Logs:** a chave de transmissão e o link do OBS nunca aparecem no log.

Arquivos: `transmissor/Dockerfile`, `transmissor/transmitir.sh`, `deploy/transmissor-stack.yml`.

- **Imagem:** `ghcr.io/bruxo95/pump.fun_bruxo_bode-transmissor:latest`, publicada pelo GitHub Actions (job `transmissor` do `imagem.yml`).
- **Quando reconstrói:** só quando a pasta `transmissor/` muda, ou pelo botão "Run workflow".

## Passo a passo (no Portainer do PC 192.168.178.65)

1. **Acesso à imagem (uma vez).** O pacote do GitHub é privado como o repositório.
   - No GitHub, crie um token clássico só com `read:packages` (Settings → Developer settings → Personal access tokens).
   - No Portainer, vá em Registries → Add registry → Custom registry.
   - Preencha: URL `ghcr.io`, usuário do GitHub e o token no campo de senha.
   - Não cole o token no chat.
2. **Criar a stack.**
   - No Portainer, vá em Stacks → Add stack, com o nome `transmissor-live`.
   - Cole o conteúdo de `deploy/transmissor-stack.yml` no Web editor.
3. **Variáveis (em Environment variables da stack, nunca no arquivo):**
   - `LINK_WEB`: o **Link para WEB** copiado em `/botlive`.
   - `KEY_WEB`: a chave de transmissão do YouTube.
     - YouTube Studio → Criar → Transmitir ao vivo → Stream → Chave de transmissão.
     - O servidor padrão já é `rtmp://a.rtmp.youtube.com/live2`.
   - `LINK_VERT`: o **Link para Mobile vertical** copiado em `/botlive`.
   - `RTMP_VERT` e `KEY_VERT`: o "Server URL" e a "Stream key" que o TikTok mostra na hora de abrir a Live.
     - Só aparecem em contas com acesso à chave de transmissão.
     - A chave do TikTok costuma mudar a cada live: troque a variável e reinicie o container `live-vertical`.
   - **Opcionais:**
     - `QUALIDADE_WEB` / `QUALIDADE_VERT`: `720` (padrão) ou `1080`. O PC do OBS tem 4 núcleos e 8 GB: 1080p só com uma live por vez.
     - `FPS_WEB` / `FPS_VERT`: padrão 30.
     - `CPU_WEB` / `CPU_VERT`: núcleos máximos por container, padrão 2 (memória máxima 2 GB cada).
4. **Deploy the stack.** Em Containers → `live-web` → Logs aparece "transmitindo". No YouTube Studio a prévia entra em alguns segundos.
5. **Atualizar a imagem depois de uma versão nova:** Stack → Update the stack → marcar "Re-pull image".

## Tela remota (ver e clicar, como no OBS) — 0.32.367

- Preencha `VNC_SENHA` nas variáveis da stack (até 8 caracteres; o VNC só usa os 8 primeiros) e faça Update com Re-pull.
- No navegador de qualquer PC da rede: `http://192.168.178.65:6080/vnc.html` (horizontal) ou `:6081/vnc.html` (vertical) → Connect → senha.
- Dá para ver exatamente o que vai para a live e clicar na sala (ligar música/sons, etc.). O que se clica vale até o navegador do
  transmissor reabrir (reinício ou a cada 12 h); o que deve valer sempre vai no link ou nas variáveis.
- Sem `VNC_SENHA` a tela remota fica desligada. A porta só deve ficar aberta na rede de casa (não abrir no roteador).

## Quanto pesa (estimativa, não medido no PC do dono)

- **Por transmissão em 1080p 30 qps:** 3–4 núcleos, 2–3 GB de memória e 4–6 Mbps de subida.
- **Em 720p:** cerca de metade.
- **As duas lives juntas:** quase o dobro.
- **Se o log mostrar `speed=` abaixo de 1.0x:** o PC não está dando conta. Use `QUALIDADE=720` ou `PRESET=superfast`.

Teste feito no desenvolvimento (15/11/2026):

- **Montagem:** script rodando com Xvfb + Chromium + PulseAudio + ffmpeg mandando para um servidor RTMP local, em 720p.
- **Resultado:** vídeo H.264 1280×720 + AAC com som, `speed=1.02x`, chave fora do log, volta sozinho quando o RTMP cai.
- **Não testado:** a imagem Docker (o Docker Hub não abria no ambiente de desenvolvimento; a construção é conferida no Actions) e a live real no YouTube/TikTok.
