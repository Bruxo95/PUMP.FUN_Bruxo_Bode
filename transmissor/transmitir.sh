#!/bin/bash
# Transmissor da SALA LIVE do BOT LIVE (0.32.364, pedido do dono): abre o link do OBS num Chromium sem tela (Xvfb), pega o som por
# uma placa de som virtual (PulseAudio) e manda tudo por RTMP (YouTube, TikTok...) com o ffmpeg. Roda num PC separado, com Docker
# no Portainer, para não pesar a VPS do site. Uma transmissão por container (WEB horizontal OU vertical).
#
# Variáveis (no Portainer, nunca no código):
#   LINK        link do OBS copiado em /botlive (Link para WEB ou Link para Mobile vertical)   — obrigatório
#   RTMP_URL    servidor RTMP (YouTube: rtmp://a.rtmp.youtube.com/live2; TikTok: o "Server URL" da Live)
#   STREAM_KEY  chave de transmissão                                                        — obrigatório (nunca aparece no log)
#   LAYOUT      h = horizontal 16:9 | v = vertical 9:16 (padrão: o que vier no link, senão h)
#   QUALIDADE   1080 | 720 (padrão 1080)      FPS (padrão 30)      VBITRATE (ex.: 4500k)      ABITRATE (padrão 160k)
#   PRESET      preset do x264 (padrão veryfast; mais leve: superfast/ultrafast)
#   MUSICA / SONS   1 = liga música lo-fi / sons da sala mesmo que o link venha com eles desligados (padrão 1)
#   REINICIAR_H reabre o navegador a cada N horas para não acumular memória (padrão 12; 0 = nunca)
set -u

say() { echo "[transmissor $(date '+%d/%m %H:%M:%S')] $*"; }
LINK="${LINK:-}"; KEY="${STREAM_KEY:-}"; RTMP="${RTMP_URL:-rtmp://a.rtmp.youtube.com/live2}"
if [ -z "$LINK" ] || [ -z "$KEY" ]; then
  say "sem LINK ou sem STREAM_KEY: parado (preencha no Portainer e reinicie o container). Não gasta processador assim."
  exec sleep infinity
fi
case "$LINK" in https://*|http://*) ;; *) say "LINK precisa começar com https://"; exec sleep infinity ;; esac

# 0.32.366 (pedido do dono): a live sempre sai COM som. O link do OBS leva a configuração do navegador onde foi copiado; se lá a
# música/os sons estavam desligados, o transmissor (que não tem como clicar na tela, como se fazia no OBS) ficava mudo.
# MUSICA=1 / SONS=1 (padrão) ligam música lo-fi e sons da sala no próprio link; MUSICA=0 / SONS=0 respeitam o link.
cfg_get() { printf '%s' "$1" | sed -n 's/.*[?&]cfg=\([^&]*\).*/\1/p' | sed 's/%2B/+/g;s/%2F/\//g;s/%3D/=/g'; }
cfg64=$(cfg_get "$LINK")
if [ -n "$cfg64" ] && json=$(printf '%s' "$cfg64" | base64 -d 2>/dev/null) && [ -n "$json" ]; then
  liga() { case "$json" in *"\"$1\":"*) json=$(printf '%s' "$json" | sed "s/\"$1\":[a-z]*/\"$1\":true/") ;; *) json="${json%\}},\"$1\":true}" ;; esac; }
  [ "${MUSICA:-1}" = "1" ] && liga musica
  [ "${SONS:-1}" = "1" ] && liga sfx
  novo=$(printf '%s' "$json" | base64 -w0 | sed 's/+/%2B/g;s/\//%2F/g;s/=/%3D/g')
  LINK=$(printf '%s' "$LINK" | sed "s|cfg=[^&]*|cfg=$novo|")
  say "som da live: música $([ "${MUSICA:-1}" = 1 ] && echo ligada || echo 'como no link') · sons $([ "${SONS:-1}" = 1 ] && echo ligados || echo 'como no link')"
fi

LAY="${LAYOUT:-}"
if [ -z "$LAY" ]; then
  # o link do /botlive leva a configuração em base64 (cfg=...); o formato vem nela ("layout":"v" = vertical)
  cfgb=$(printf '%s' "$LINK" | sed -n 's/.*[?&]cfg=\([^&]*\).*/\1/p' | sed 's/%2B/+/g;s/%2F/\//g;s/%3D/=/g')
  if printf '%s' "$cfgb" | base64 -d 2>/dev/null | grep -q '"layout":"v"'; then LAY=v; else LAY=h; fi
fi
Q="${QUALIDADE:-1080}"; FPS="${FPS:-30}"
if [ "$Q" = "720" ]; then S=720; L=1280; VB_DEF=2500k; else S=1080; L=1920; VB_DEF=4500k; fi
if [ "$LAY" = "v" ]; then W=$S; H=$L; else W=$L; H=$S; fi
VB="${VBITRATE:-$VB_DEF}"; AB="${ABITRATE:-160k}"; PRESET="${PRESET:-veryfast}"
REINICIAR_H="${REINICIAR_H:-12}"
CHROME="${CHROME_BIN:-$(command -v chromium || command -v chromium-browser || command -v google-chrome || echo chromium)}"
say "formato $([ "$LAY" = v ] && echo 'vertical' || echo 'horizontal') ${W}x${H} · ${FPS} quadros · vídeo $VB · áudio $AB · preset $PRESET"
say "link do OBS configurado (não aparece no log) · servidor $(printf '%s' "$RTMP" | sed 's|^\(rtmp[s]*://[^/]*\).*|\1|')"

export DISPLAY=:99 XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp/run-$(id -u)}" HOME="${HOME:-/tmp}"
mkdir -p "$XDG_RUNTIME_DIR" && chmod 700 "$XDG_RUNTIME_DIR"
rm -f /tmp/.X99-lock

# tela virtual
Xvfb :99 -screen 0 "${W}x${H}x24" -nolisten tcp -ac >/dev/null 2>&1 &
for _ in $(seq 1 50); do [ -e /tmp/.X11-unix/X99 ] && break; sleep 0.2; done
# placa de som virtual: o navegador toca nela e o ffmpeg grava o "monitor" dela
pulseaudio -D --exit-idle-time=-1 --disallow-exit >/dev/null 2>&1
for _ in $(seq 1 50); do pactl info >/dev/null 2>&1 && break; sleep 0.2; done
pactl info >/dev/null 2>&1 || say "a placa de som virtual não subiu: a live vai sem som"
pactl load-module module-null-sink sink_name=live sink_properties=device.description=live >/dev/null 2>&1
pactl set-default-sink live >/dev/null 2>&1

CPID=""; FPID=""
start_chrome() {
  rm -rf /tmp/chrome-perfil
  "$CHROME" --no-sandbox --kiosk --app="$LINK" --window-position=0,0 --window-size="$W,$H" --force-device-scale-factor=1 \
    --user-data-dir=/tmp/chrome-perfil --autoplay-policy=no-user-gesture-required --no-first-run --no-default-browser-check \
    --disable-background-networking --disable-component-update --disable-sync --disable-default-apps \
    --disable-infobars --noerrdialogs --disable-session-crashed-bubble --disable-translate --hide-scrollbars \
    --disable-features=Translate,MediaRouter --disable-dev-shm-usage --password-store=basic \
    --enable-features=OverlayScrollbar >/dev/null 2>&1 &
  CPID=$!
  CSTART=$(date +%s)
  say "navegador aberto"
}
# a chave nunca vai para o log: o que o ffmpeg escrever passa por aqui e a chave vira ***
# 0.32.365: taxa CONSTANTE (CBR). A cena pixel art muda pouco e o x264 mandava ~200 Kbps; o YouTube avisava "taxa de bits inferior
# ao recomendado" e pode baixar a qualidade. Com nal-hrd=cbr o vídeo sai sempre na taxa pedida. As linhas de andamento do ffmpeg
# terminam em \r: viram linhas normais para aparecerem no log do Portainer (uma por minuto).
mask() { awk -v k="$KEY" 'BEGIN { RS = "[\r\n]+" } { if (k != "") { while ((i = index($0, k)) > 0) $0 = substr($0, 1, i-1) "***" substr($0, i+length(k)) } print; fflush() }'; }
start_ffmpeg() {
  ( ffmpeg -hide_banner -loglevel warning -stats_period 60 -stats \
      -thread_queue_size 512 -f x11grab -draw_mouse 0 -video_size "${W}x${H}" -framerate "$FPS" -i :99.0 \
      -thread_queue_size 512 -f pulse -i live.monitor \
      -c:v libx264 -preset "$PRESET" -pix_fmt yuv420p -b:v "$VB" -minrate "$VB" -maxrate "$VB" -bufsize "$(( ${VB%k} * 2 ))k" \
      -x264-params "nal-hrd=cbr:force-cfr=1" \
      -g "$(( FPS * 2 ))" -keyint_min "$(( FPS * 2 ))" -sc_threshold 0 \
      -c:a aac -b:a "$AB" -ar 44100 -ac 2 \
      -f flv "${RTMP%/}/$KEY" 2>&1 | mask ) &
  FPID=$!
  say "transmitindo"
}

trap 'say "parando"; pkill -P "$CPID" 2>/dev/null; kill "$CPID" "$FPID" 2>/dev/null; pkill -x ffmpeg; exit 0' TERM INT
start_chrome
sleep "${ESPERA_S:-10}"              # tempo para a cena, as fontes e a música carregarem antes de ir ao ar
start_ffmpeg
while true; do
  sleep 5
  if ! kill -0 "$CPID" 2>/dev/null; then say "o navegador fechou: abrindo de novo"; start_chrome; fi
  if ! pgrep -x ffmpeg >/dev/null; then say "a transmissão caiu: tentando de novo em 5 s"; sleep 5; start_ffmpeg; fi
  if [ "$REINICIAR_H" -gt 0 ] 2>/dev/null && [ $(( $(date +%s) - CSTART )) -ge $(( REINICIAR_H * 3600 )) ]; then
    say "reabrindo o navegador (a cada $REINICIAR_H h)"; pkill -P "$CPID" 2>/dev/null; kill "$CPID" 2>/dev/null; sleep 2; start_chrome
  fi
done
