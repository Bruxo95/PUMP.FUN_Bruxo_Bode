"""0.32.442 → 0.32.481 (pedido do dono): Descartar mantém a configuração sem mudar nada e fica guardado na conta (servidor),
não no navegador; o aviso só volta quando a outra pessoa mudar de novo."""
import pathlib

JS = pathlib.Path("web/app.js").read_text(encoding="utf-8")


def test_descartar_existe_e_nao_salva_configuracao():
    assert 'data-bmc="skip"' in JS and 'data-bmc="skipm"' in JS
    bloco = JS[JS.index('a === "skip" || a === "skipm"'):JS.index('a === "peeroff"')]
    assert "/api/pump/settings" not in bloco and "setCfg" not in bloco      # descartar não grava nenhuma opção
    assert 'cmpVisto("boost"' in bloco                                       # guarda na conta que você já viu
    assert "pf_bmc_skip" not in JS and "pf_cxok" not in JS                   # nada mais no localStorage


def test_comparar_so_no_botao_e_aviso_so_com_mudanca():
    assert "Comparar configurações" in JS and "!r.aviso" in JS
    assert JS.count('escopo: "') >= 3                                        # BOOST, geral e chaves
