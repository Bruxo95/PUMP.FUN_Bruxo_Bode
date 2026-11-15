"""0.32.364 (pedido do dono): transmissor da SALA LIVE (Chromium sem tela + ffmpeg → RTMP) para rodar no PC do OBS, fora da VPS do site."""
import os
import re
import shutil
import subprocess

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _r(*p):
    return open(os.path.join(ROOT, *p), encoding="utf-8").read()


def test_script_valido_e_chave_nunca_no_log():
    sh = _r("transmissor", "transmitir.sh")
    if shutil.which("bash"):
        assert subprocess.run(["bash", "-n", os.path.join(ROOT, "transmissor", "transmitir.sh")]).returncode == 0
    assert "mask()" in sh and "| mask" in sh                      # o que o ffmpeg escreve passa pela máscara da chave
    assert 'say "link do OBS configurado (não aparece no log)' in sh
    assert "exec sleep infinity" in sh                            # sem link/chave fica parado, sem gastar processador
    assert "pkill -f" not in sh                                   # nunca derrubar processo pelo texto da linha de comando


def test_stack_sem_segredo_e_imagem_publicada_pelo_actions():
    st = _r("deploy", "transmissor-stack.yml")
    for k in ("LINK", "STREAM_KEY", "RTMP_URL"):
        for v in re.findall(rf"^\s+{k}: (.+)$", st, re.M):
            assert v.startswith("${"), v                            # chave e link só pelas variáveis do Portainer
    assert "pump.fun_bruxo_bode-transmissor:latest" in st and "cpus:" in st and "mem_limit:" in st
    wf = _r(".github", "workflows", "imagem.yml")
    assert "  transmissor:\n" in wf and "context: transmissor" in wf and "-transmissor" in wf
    assert "USER live" in _r("transmissor", "Dockerfile")
