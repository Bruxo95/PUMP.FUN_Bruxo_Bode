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
    assert 'id="menuSala" data-link href="/sala"' in html[i:i + 1200]
    # 0.32.267: o menu de redes (common.js) abre em todo .hubbtn; o Sala tem data-link para ficar de fora
    cjs = open(os.path.join(WEB, "common.js"), encoding="utf-8").read()
    assert '.hubbtn:not([data-link])' in cjs


def test_sala_so_le_os_dados_e_nao_manda_ordem():
    js = open(os.path.join(WEB, "sala.js"), encoding="utf-8").read()
    assert '"/api/pump?ev=' in js
    assert "method:" not in js and "body:" not in js and "/api/pump/close" not in js and "manual-buy" not in js


def test_sala_da_robinhood_le_so_o_painel_da_hood():
    """0.32.293 (pedido do dono): /sala?rede=hood usa /api/hood/painel (ETH) e o /hood tem o botão Sala."""
    js = open(os.path.join(WEB, "sala.js"), encoding="utf-8").read()
    assert 'get("rede") === "hood"' in js and '"/api/hood/painel"' in js and "/api/hood/real" not in js
    html = open(os.path.join(WEB, "hood.html"), encoding="utf-8").read()
    assert 'id="hoodSala" data-link href="/sala?rede=hood"' in html


def test_hood_tem_conversor_eth_dolar():
    """0.32.296 (pedido do dono): conversor ETH ↔ dólar na Carteira do /hood e "≈ US$" nos campos em ETH."""
    html = open(os.path.join(WEB, "hood.html"), encoding="utf-8").read()
    js = open(os.path.join(WEB, "hood.js"), encoding="utf-8").read()
    assert 'id="cvEth"' in html and 'id="cvUsd"' in html and "data-usd=" in js and "usdRate" in js


def test_enviar_para_robinhood_cota_sozinho():
    """0.32.299 (pedido do dono): o valor digitado já cota quanto chega na Robinhood; botão Enviar para a Robinhood."""
    js = open(os.path.join(WEB, "hood.js"), encoding="utf-8").read()
    html = open(os.path.join(WEB, "hood.html"), encoding="utf-8").read()
    assert "function gaAuto" in js and 'if (t.id === "gaUsd") { gaConv(); gaAuto(); }' in js and "Enviar para a Robinhood</button>" in js
    assert "<h2>Enviar para a Robinhood</h2>" in html


def test_sala_se_adapta_a_tela_e_mostra_hora_de_entrada():
    """0.32.300 (pedido do dono): palco que cabe na janela (zoom, celular, tablet, PC) e coluna Hora nas posições abertas."""
    html = open(os.path.join(WEB, "sala.html"), encoding="utf-8").read()
    js = open(os.path.join(WEB, "sala.js"), encoding="utf-8").read()
    assert "100dvh" in html and "container-type:size" in html and "calc(100cqh * 16 / 9)" in html
    assert "<span>Hora</span>" in js


def test_sala_tem_historico_e_evolucao_da_carteira():
    """0.32.305 (pedido do dono): Histórico das posições embaixo das abertas e evolução da carteira desenhada na mesa."""
    html = open(os.path.join(WEB, "sala.html"), encoding="utf-8").read()
    js = open(os.path.join(WEB, "sala.js"), encoding="utf-8").read()
    assert 'id="his"' in html and "function evo(" in js and "evo(f);" in js and "start_sol" in js


def test_vender_de_cada_posicao_fica_na_primeira_coluna():
    """0.32.311 (pedido do dono): o Vender de cada posição do /hood fica na 1ª coluna (na última saía da tela entre 860 e 1280 px)."""
    js = open(os.path.join(WEB, "hood.js"), encoding="utf-8").read()
    assert 'table("poTb", ["", "Aberta"' in js and "sellBtn(p)," in js
