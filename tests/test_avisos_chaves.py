"""0.32.104: toda chave diz onde vale; chave nova que compra na REAL precisa entrar na lista da tela."""
import re


def test_every_real_switch_is_labeled_real():
    html = open("web/app.html", encoding="utf-8").read()
    js = open("web/app.js", encoding="utf-8").read()
    bloco = re.search(r"const TGL_REAL = \[(.*?)\]", js).group(1)
    for k in set(re.findall(r'data-toggle="(pump_[a-z0-9_]*real[a-z0-9_]*)"', html)):
        assert f'"{k}"' in bloco, k
    assert '"pump_pp_copy"' in re.search(r"const TGL_NOBUY = \[(.*?)\]", js).group(1)


def test_status_window_only_uses_variables_it_has():
    """0.32.112: a janela do Monitor parava de abrir porque sysDetail usava `c`, que não existe nela."""
    js = open("web/app.js", encoding="utf-8").read()
    corpo = js[js.index("function sysDetail("):js.index("function openSys(")]
    assert not re.search(r"(?<![\w.])c\.pump_", corpo)


def test_tab_settings_never_show_real_options():
    import pathlib
    s = pathlib.Path("web/app.js").read_text(encoding="utf-8")
    assert "!/real|jito/.test(x.k)" in s[s.index("function abasPanel"):s.index("async function abasSet")]
    assert 'id="abPn"' in pathlib.Path("web/app.html").read_text(encoding="utf-8")
