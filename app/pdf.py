"""PDF simples, só com a biblioteca padrão (0.31.7): texto em páginas A4 com títulos e parágrafos.

Sem dependência nova de propósito (regra do projeto: nada é instalado sem triagem). Usa as fontes padrão do PDF
(Helvetica) com a codificação WinAnsi, que cobre os acentos do português; símbolos fora dela viram equivalentes
simples ("→" vira "->").
"""
from __future__ import annotations

import textwrap
import zlib

W, H, M = 595, 842, 46                       # A4 em pontos e margem
STYLES = {"title": ("F2", 16, 22, 70), "h": ("F2", 11.5, 17, 95), "p": ("F1", 9.5, 13, 112), "small": ("F1", 8, 11, 130),
          "mono": ("F3", 8.5, 11.5, 105)}
SUBS = {"→": "->", "−": "-", "≥": ">=", "≤": "<=", "×": "x", "•": "-", "…": "...", "“": '"', "”": '"', "’": "'", "‘": "'",
        "–": "-", "—": "-", "✅": "", "⚠": "!"}


def _enc(s: str) -> bytes:
    for a, b in SUBS.items():
        s = s.replace(a, b)
    out = s.encode("cp1252", "replace")
    return out.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def make(blocks: list[tuple[str, str]], title: str = "Relatório") -> bytes:
    """blocks = [(estilo, texto), ...] com estilo em STYLES. Quebra linhas e páginas sozinho."""
    pages: list[list[bytes]] = [[]]
    y = H - M
    for style, text in blocks:
        font, size, lead, width = STYLES.get(style, STYLES["p"])
        if style in ("h", "title"):
            y -= lead * 0.4
        lines = []
        for para in str(text).split("\n"):
            lines += textwrap.wrap(para, width=width, break_long_words=True, replace_whitespace=False) or [""]
        for ln in lines:
            if y - lead < M:
                pages.append([])
                y = H - M
            y -= lead
            pages[-1].append(b"BT /%s %.1f Tf %d %.1f Td (%s) Tj ET" % (font.encode(), size, M, y, _enc(ln)))
    objs: list[bytes] = []

    def add(b: bytes) -> int:
        objs.append(b)
        return len(objs)
    f1 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    f2 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    f3 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>")
    pages_id = len(objs) + 1 + 2 * len(pages) + 1      # reservado depois das páginas
    kids = []
    for i, cmds in enumerate(pages):
        footer = b"BT /F1 7.5 Tf %d 24 Td (%s) Tj ET" % (M, _enc(f"{title} - página {i + 1} de {len(pages)}"))
        raw = b"\n".join(cmds + [footer])
        data = zlib.compress(raw)
        cid = add(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(data) + data + b"\nendstream")
        kids.append(add(b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %d %d] /Contents %d 0 R "
                        b"/Resources << /Font << /F1 %d 0 R /F2 %d 0 R /F3 %d 0 R >> >> >>" % (pages_id, W, H, cid, f1, f2, f3)))
    info = add(b"<< /Title (%s) /Producer (PUMP FUN COPY) >>" % _enc(title))
    assert len(objs) + 1 == pages_id
    add(b"<< /Type /Pages /Kids [%s] /Count %d >>" % (b" ".join(b"%d 0 R" % k for k in kids), len(kids)))
    catalog = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id)
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % x for x in offs)
    out += b"trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, catalog, info, xref)
    return bytes(out)
