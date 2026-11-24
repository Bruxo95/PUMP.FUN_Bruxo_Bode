"""0.32.442 (pedido do dono): o aviso de diferenças do BOOST tem Descartar, que mantém a configuração sem mudar nada."""
import pathlib
import re

JS = pathlib.Path("web/app.js").read_text(encoding="utf-8")


def test_descartar_existe_e_nao_salva_configuracao():
    assert 'data-bmc="skip"' in JS and 'data-bmc="skipm"' in JS and 'data-bmc="unskip"' in JS
    bloco = JS[JS.index('a === "skip" || a === "skipm"'):JS.index('a === "unskip"')]
    assert "/api/pump/settings" not in bloco and "setCfg" not in bloco      # descartar não grava nada no servidor
    assert "pf_bmc_skip" in JS and re.search(r"bmcSig\s*=\s*\(r\)", JS)
