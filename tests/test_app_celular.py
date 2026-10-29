"""0.32.75: atalho do iPhone (nome FUN COPY + ícone) e barra de abas só no celular. Sem internet."""
import json
from pathlib import Path

import struct
import zlib

WEB = Path(__file__).resolve().parent.parent / "web"


def _png(f):
    """Largura, altura e os primeiros bytes da 1ª linha (sem Pillow, que não está nas dependências)."""
    b = f.read_bytes()
    assert b[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = struct.unpack(">II", b[16:24])
    i, idat = 8, b""
    while i < len(b):
        n = struct.unpack(">I", b[i:i + 4])[0]
        if b[i + 4:i + 8] == b"IDAT":
            idat += b[i + 8:i + 8 + n]
        i += 12 + n
    raw = zlib.decompress(idat)
    return w, h, raw[1:10]


def test_iphone_shortcut_name_and_icon():
    for page in ("app.html", "index.html"):
        html = (WEB / page).read_text()
        assert '<meta name="apple-mobile-web-app-title" content="FUN COPY">' in html
        assert 'rel="apple-touch-icon" href="/static/apple-touch-icon.png' in html
        assert 'rel="manifest" href="/static/manifest.json' in html and "viewport-fit=cover" in html
    man = json.loads((WEB / "manifest.json").read_text())
    assert man["name"] == man["short_name"] == "FUN COPY" and man["display"] == "standalone" and man["start_url"] == "/app"
    for ic in man["icons"]:
        f = WEB / ic["src"].replace("/static/", "")
        w, h, first = _png(f)
        assert f"{w}x{h}" == ic["sizes"] and first[:9] == bytes(9)   # fundo preto no canto


def test_tabbar_only_on_phone():
    css = (WEB / "app.css").read_text()
    i = css.index("/* ===== 0.32.75")
    assert ".tabbar{display:none}" in css[i:i + 600]          # no PC a barra de abas não aparece
    assert 'id="tabbar"' in (WEB / "app.html").read_text()
