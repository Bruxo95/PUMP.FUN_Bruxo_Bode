"""0.32.184 (pedido do dono): Configurações em abas, menu Log geral e Usar ou descartar como página de quadrados. Sem internet."""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
H = (WEB / "app.html").read_text(encoding="utf-8")
JS = (WEB / "app.js").read_text(encoding="utf-8")


def _sec(view):
    a = H.index(f'<section class="view" data-view="{view}"')
    return H[a:H.index("</section>", a)]


def test_logs_left_config_and_admin_for_log_geral():
    lg, cfg, adm = _sec("loggeral"), _sec("config"), _sec("admin")
    for el in ('id="tAudit"', 'id="tAAudit"', 'id="logs"', 'id="aAudUser"'):
        assert el in lg and el not in cfg and el not in adm
    assert 'href="#loggeral"' in H and "loggeral:" in JS


def test_every_config_card_has_a_tab():
    cfg = _sec("config")
    cards = re.findall(r'<div (data-ct="(\w+)" )?class="card', cfg)
    assert cards and all(c[1] in ("copia", "chaves", "share", "todas") for c in cards)
    assert set(re.findall(r'data-ct="(\w+)">', cfg)) == {"copia", "chaves", "share", "todas"}


def test_usar_ou_descartar_is_one_link_and_a_page_of_squares():
    nav = H[H.index('<nav class="nav"'):H.index("</nav>")]
    assert 'id="navSub"' not in nav and 'href="#usar"' in nav
    for v in ("estudo", "relatorios", "aprendizado", "fantasma", "elite", "igual", "base", "listanegra", "comparar", "novas"):
        assert f'href="#{v}"' not in nav
        assert f'class="uscard" href="#{v}"' in _sec("usar")
    assert "navGrpH" not in JS and '"usar"' in JS


def test_new_screens_moved_into_usar_with_room_for_results():
    nav = H[H.index('<nav class="nav"'):H.index("</nav>")]
    usar = _sec("usar")
    for v in ("tradershist", "explorar", "abas", "basegeral", "logs", "bruxo", "jevtrade", "jev", "calls", "tradercfg"):
        assert f'href="#{v}"' not in nav and f'data-usg="{v}"' in usar
    assert 'href="#tradershist" data-us="tradershist">' in usar and 'href="#tradercfg" data-us="tradercfg">' in usar   # de todos
    assert 'data-us="explorar" data-adm' in usar and 'id="usMode"' in usar and "result-tabs?real=" in JS
