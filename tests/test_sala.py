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
    assert 'get("rede")' in js and 'REDE === "hood"' in js and '"/api/hood/painel"' in js and "/api/hood/real" not in js
    html = open(os.path.join(WEB, "hood.html"), encoding="utf-8").read()
    assert 'id="hoodSala" data-link href="/sala?rede=hood"' in html


def test_sala_do_forex_le_o_painel_do_forex():
    """0.32.368 (pedido do dono): /sala?rede=forex usa /api/forex/painel (US$) e nunca mostra o botão REAL."""
    js = open(os.path.join(WEB, "sala.js"), encoding="utf-8").read()
    assert 'REDE === "forex"' in js and '"/api/forex/painel"' in js and "/api/forex/real" not in js
    assert "const DEC = FOREX ? 2 : HOOD ? 4 : 3" in js     # sem referência a si mesma (quebrava a Sala normal)


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
    assert "tr(\"Hora\", \"Time\")" in js   # 0.32.346: cabeçalho traduzido na SALA LIVE (inglês)


def test_sala_tem_historico_e_evolucao_da_carteira():
    """0.32.305 (pedido do dono): Histórico das posições embaixo das abertas e evolução da carteira desenhada na mesa."""
    html = open(os.path.join(WEB, "sala.html"), encoding="utf-8").read()
    js = open(os.path.join(WEB, "sala.js"), encoding="utf-8").read()
    assert 'id="his"' in html and "function evo(" in js and "evo(f);" in js and "start_sol" in js


def test_vender_de_cada_posicao_fica_na_primeira_coluna():
    """0.32.311 (pedido do dono): o Vender de cada posição do /hood fica na 1ª coluna (na última saía da tela entre 860 e 1280 px)."""
    js = open(os.path.join(WEB, "hood.js"), encoding="utf-8").read()
    assert 'table("poTb", ["", "Aberta"' in js and "sellBtn(p)," in js


def test_sala_escritorio_com_personagens_balões_e_log():
    """0.32.333 (pedido do dono, com referências de pixel art): escritório com trader, BOT assistente, balões de fala, ícones e
    LOG DO ROBÔ; tudo desenhado no código (sem imagem de fora) e a sala continua só lendo os dados."""
    html = open(os.path.join(WEB, "sala.html"), encoding="utf-8").read()
    js = open(os.path.join(WEB, "sala.js"), encoding="utf-8").read()
    assert 'id="log"' in html and 'data-ico="bot"' in html
    assert "function balloon(" in js and "function botDraw(" in js and "function renderLog(" in js and "const SPR = {" in js
    assert "<img" not in html.split("<body>")[1].split("<script")[0]        # nenhuma imagem de fora na página
    assert "http" not in js.split("const SPR = {")[1].split("const CACHE")[0]


def test_sala_personagem_casual_com_humor_do_mercado():
    """0.32.334 (pedido do dono): personagem casual que trabalha e reage ao mercado (eufórico, feliz, atento, dedicado, nervoso)."""
    js = open(os.path.join(WEB, "sala.js"), encoding="utf-8").read()
    html = open(os.path.join(WEB, "sala.html"), encoding="utf-8").read()
    for m in ("euforia", "feliz", "atento", "dedicado", "nervoso"):
        assert m + ":" in js
    assert "S.mood =" in js and "MELHORANDO!" in js and 'id="mood"' in html and "HOOD_C" in js


def test_pagina_bot_live(env):
    """0.32.336/0.32.337 (pedido do dono): BOT LIVE no "Qual projeto você quer abrir?" → /botlive (configuração simples) com o botão
    SALA LIVE → /botlive/sala (a cena do BOT fazendo trades). Fora do menu Trocar rede."""
    r = env["c"].get("/botlive")
    assert r.status_code == 200 and "/static/botlivecfg.js?v=" in r.text and 'href="/botlive/sala"' in r.text and "SALA LIVE" in r.text
    assert "<script>" not in r.text.split("<body>", 1)[1] and 'id="cPriv"' in r.text
    r = env["c"].get("/botlive/sala")
    assert r.status_code == 200 and "/static/sala.js?v=" in r.text and "/static/botlive2.js?v=" in r.text and 'id="drawer"' not in r.text
    assert "<script>" not in r.text.split("<body>", 1)[1] and 'href="/botlive"' in r.text
    js = open(os.path.join(WEB, "botlive.js"), encoding="utf-8").read()
    assert 'rede: "hood"' in js and "window.SALA_CFG" in js                     # padrão: dados da Robinhood
    assert '"/botlive"' in open(os.path.join(WEB, "common.js"), encoding="utf-8").read()   # 0.32.369: o menu Trocar rede mostra todos
    assert 'href="/botlive"' in open(os.path.join(WEB, "entrar.html"), encoding="utf-8").read()
    sala = open(os.path.join(WEB, "sala.js"), encoding="utf-8").read()
    assert "PRIV()" in sala and "window.SALA =" in sala


def test_sala_usa_o_visual_da_sala_live():
    """0.32.362 (pedido do dono): o visual da SALA LIVE do BOT LIVE vale para as outras salas (pump.fun e Robinhood): cena em resolução
    dobrada com o personagem do SpriteCook e o robô, letra grande em uma linha nas Posições/Histórico e LOG DO ROBÔ numa faixa. Só o visual."""
    js = open(os.path.join(WEB, "sala.js"), encoding="utf-8").read()
    html = open(os.path.join(WEB, "sala.html"), encoding="utf-8").read()
    assert "const HI = true;" in js and "function salaFit()" in js and 'box.classList.contains("logline")' in js
    assert '<div class="log logline" id="log"></div>' in html and 'class="box logb"' not in html
    assert "calc((100cqi - 36px) / 14)" in html and ".grid.fit{" in html


def test_botao_sala_de_toda_pagina_abre_a_sala_e_trocar_rede_lista_todos():
    """0.32.369 (pedido do dono): o botão Sala do /forex abria o menu de redes (faltava data-link); o menu Trocar rede
    lista todos os projetos da tela /entrar e o BOT LIVE também tem o botão."""
    import re
    for f in os.listdir(WEB):
        if not f.endswith(".html"):
            continue
        html = open(os.path.join(WEB, f), encoding="utf-8").read()
        for a in re.findall(r'<a [^>]*class="[^"]*hubbtn[^"]*"[^>]*>', html):
            if "/sala" in a:
                assert "data-link" in a, f + ": botão Sala sem data-link abre o menu de redes"
    js = open(os.path.join(WEB, "common.js"), encoding="utf-8").read()
    entrar = open(os.path.join(WEB, "entrar.html"), encoding="utf-8").read()
    for href in re.findall(r'class="hub-card[^"]*" href="([^"]+)"', entrar):
        assert '"' + href + '", "#' in js, href + " falta no menu Trocar rede"
    assert "hubbtn" in open(os.path.join(WEB, "botlive.html"), encoding="utf-8").read()


def test_sala_mostra_valores_em_dolar_ou_moeda():
    """0.32.470 (pedido do dono): botões no título do Histórico para ver Posições e Histórico em US$, SOL ou ETH."""
    html = open(os.path.join(WEB, "sala.html"), encoding="utf-8").read()
    js = open(os.path.join(WEB, "sala.js"), encoding="utf-8").read()
    assert 'id="cur"' in html and "function curBar(" in js and "data-cur" in js and "S.eth_usd = js.eth_usd" in js
    assert '"eth_usd"' in open(os.path.join(WEB, "..", "app", "api.py"), encoding="utf-8").read()


def test_sala_no_celular_vira_app_e_so_le_dados(env):
    """0.32.479 (pedido do dono): no celular em pé a Sala ganha barra de baixo (ao vivo, abertas, histórico, log, menu),
    histórico completo com filtros e janela de detalhes. Só lê o que o sala.js já buscou; não manda ordem nem chama API."""
    r = env["c"].get("/sala")
    assert "/static/salaapp.js?v=" in r.text and r.text.index("/static/sala.js?v=") < r.text.index("/static/salaapp.js?v=")
    assert env["c"].get("/static/salaapp.js").status_code == 200
    js = open(os.path.join(WEB, "salaapp.js"), encoding="utf-8").read()
    for t in ('"vivo"', '"abertas"', '"hist"', '"log"', '"menu"', "data-sadet", "data-samore", "#historico"):
        assert t in js
    assert "fetch(" not in js and "_api(" not in js and "method:" not in js and "onclick" not in js
    assert "max-width:700px" in js                                  # só no celular; no PC a Sala fica igual
    sala = open(os.path.join(WEB, "sala.js"), encoding="utf-8").read()
    assert "rede: REDE, unit: U" in sala and "logKind };" in sala
    html = open(os.path.join(WEB, "sala.html"), encoding="utf-8").read()
    assert ".sbar,.sapages,.sasheet{display:none}" in html and "html.sapp .sbar{" in html
    # a SALA LIVE do BOT LIVE (OBS) não recebe o modo app
    assert "salaapp.js" not in open(os.path.join(WEB, "botlive_sala.html"), encoding="utf-8").read()


def test_sala_tem_icone_e_nome_fun_bot_para_tela_de_inicio(env):
    """0.32.480: atalho do iPhone/Android abre a Sala com ícone próprio e o nome FUN BOT."""
    import json
    html = env["c"].get("/sala").text
    assert 'name="apple-mobile-web-app-title" content="FUN BOT"' in html
    assert 'rel="apple-touch-icon" href="/static/fun-bot-180.png' in html
    assert 'rel="manifest" href="/static/sala.json' in html
    man = json.loads(open(os.path.join(WEB, "sala.json"), encoding="utf-8").read())
    assert man["name"] == man["short_name"] == "FUN BOT"
    assert man["start_url"] == "/sala" and man["display"] == "standalone"
    assert any(i.get("purpose") == "maskable" for i in man["icons"])
    for i in man["icons"]:
        nome = i["src"].replace("/static/", "")
        assert os.path.exists(os.path.join(WEB, nome)), nome
        assert env["c"].get(i["src"]).status_code == 200
