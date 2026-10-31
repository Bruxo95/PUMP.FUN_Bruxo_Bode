"""0.32.104: toda chave diz onde vale; chave nova que compra na REAL precisa entrar na lista da tela."""
import re


def test_every_real_switch_is_labeled_real():
    html = open("web/app.html", encoding="utf-8").read()
    js = open("web/app.js", encoding="utf-8").read()
    bloco = re.search(r"const TGL_REAL = \[(.*?)\]", js).group(1)
    for k in set(re.findall(r'data-toggle="(pump_[a-z0-9_]*real[a-z0-9_]*)"', html)):
        assert f'"{k}"' in bloco, k
    assert '"pump_pp_copy"' in re.search(r"const TGL_NOBUY = \[(.*?)\]", js).group(1)
