"""0.32.266 (pedido do dono): Sala ao vivo — página /sala e botão ao lado de "Trocar rede"."""
import os

from tests.test_api import env  # noqa: F401  (fixture env)

WEB = os.path.join(os.path.dirname(__file__), "..", "web")


def test_pagina_sala_abre_sem_script_inline(env):
    r = env["c"].get("/sala")
    assert r.status_code == 200 and "/static/sala.js?v=" in r.text and "__V__" not in r.text
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    body = r.text.split("<body>", 1)[1]
    assert "<script>" not in body                                   # a CSP bloqueia script inline
    assert env["c"].get("/static/sala.js").status_code == 200


def test_botao_sala_ao_lado_de_trocar_rede():
    html = open(os.path.join(WEB, "app.html"), encoding="utf-8").read()
    i = html.index('id="menuHub"')
    assert 'id="menuSala" href="/sala"' in html[i:i + 1200]


def test_sala_so_le_os_dados_e_nao_manda_ordem():
    js = open(os.path.join(WEB, "sala.js"), encoding="utf-8").read()
    assert '"/api/pump?ev=' in js
    assert "method:" not in js and "body:" not in js and "/api/pump/close" not in js and "manual-buy" not in js
