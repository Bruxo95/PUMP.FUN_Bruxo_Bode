# Transmissor da SALA LIVE (0.32.364): Chromium sem tela + placa de som virtual + ffmpeg → RTMP (YouTube/TikTok).
# Imagem separada do site (ghcr.io/bruxo95/pump.fun_bruxo_bode-transmissor), para rodar em OUTRO PC com Docker/Portainer.
# Pacotes só dos repositórios oficiais do Debian 12.
FROM debian:12-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends chromium ffmpeg xvfb pulseaudio pulseaudio-utils procps tini ca-certificates \
      fonts-dejavu-core fonts-noto-color-emoji \
 && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 10002 live
COPY transmitir.sh /usr/local/bin/transmitir
RUN chmod 755 /usr/local/bin/transmitir
USER live
WORKDIR /home/live
# no ar = o ffmpeg está rodando
HEALTHCHECK --interval=60s --timeout=5s --start-period=90s --retries=3 CMD pgrep -x ffmpeg >/dev/null || pgrep -x sleep >/dev/null
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/transmitir"]
