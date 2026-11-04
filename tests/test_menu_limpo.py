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
    lg, cfg, adm = _sec("loggeral"), _sec("carteiras"), _sec("admin")
    for el in ('id="tAudit"', 'id="tAAudit"', 'id="logs"', 'id="aAudUser"'):
        assert el in lg and el not in cfg and el not in adm
    assert 'href="#loggeral"' in H and "loggeral:" in JS


def test_every_config_card_has_a_tab():
    cfg = _sec("carteiras")
    cards = re.findall(r'<div data-ct="(\w+)"', cfg)
    assert cards and set(cards) <= {"copia", "chaves", "share", "todas"}
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
    for v in ("tradershist", "explorar", "abas", "basegeral", "logs", "bruxo", "jevtrade", "jev", "calls"):
        assert f'href="#{v}"' not in nav and f'data-usg="{v}"' in usar
    assert 'href="#tradershist" data-us="tradershist">' in usar                                                        # de todos
    assert 'data-us="explorar" data-adm' in usar and 'id="usMode"' in usar and "result-tabs?real=" in JS


def test_status_do_sistema_is_a_page_with_two_tabs():
    sis = _sec("sistema")
    assert 'id="sysM"' in sis and 'data-syt="status"' in sis and 'data-syt="uso" data-adm' in sis and 'id="sysUse"' in sis
    assert 'class="modal" id="sysM"' not in H and 'location.hash = "#sistema"' in JS and "usebad" in JS


def test_carteiras_is_the_only_place_to_run_the_wallets():
    """0.32.193 (pedido do dono): Execução real, Configurações e Configuração do Trader viraram a aba Carteiras."""
    nav = H[H.index('<nav class="nav"'):H.index("</nav>")]
    cart = _sec("carteiras")
    assert 'href="#carteiras"' in nav
    for v in ("real", "config", "tradercfg", "feed", "novidades"):
        assert f'href="#{v}" data-v' not in nav and f'<section class="view" data-view="{v}"' not in H
        assert f'{v}: "' in JS[JS.index("const MOVED"):JS.index("const MOVED") + 140]     # link antigo continua funcionando
    assert 'data-wm="sim"' in cart and 'data-wm="real"' in cart
    sim = cart[cart.index('<div data-wp="sim">'):cart.index('<div data-wp="real"')]
    assert 'data-toggle="pump_copy_enabled"' in sim and 'data-cfg="pump_copy_sol"' in sim and 'data-cfg="pump_sim_balance_sol"' in sim
    real = cart[cart.index('<div data-wp="real"'):cart.index('class="h3s walcomm"')]
    assert 'id="realB"' in real and 'data-cfg="pump_real_max_sol"' in real and 'data-toggle="pump_real_mirror"' in real
    for k in ("pump_stop_pct", "pump_tp1_pct", "pump_min_winrate", "pump_copy_delay_s"):      # valem para as duas: uma vez só
        assert H.count(f'data-cfg="{k}"') == 1 and f'data-cfg="{k}"' in cart[cart.index("walcomm"):]


def test_feed_and_changelog_moved_into_tabs():
    assert 'id="tFeed"' in _sec("historico") and '"feed", "Feed ao vivo"' in JS
    assert 'id="tNov"' in _sec("loggeral") and 'data-lg="chg" data-adm' in _sec("loggeral") and 'LGT === "chg"' in JS


def test_on_off_buttons_are_switches():
    assert 'class="btn tgl sw off" id="realB"' in H and 'class="btn sm tgl sw on" id="logLive"' in H and 'class="btn tgl sw off" id="radarToggle"' in H
    assert '"REAL: ON' not in JS and '"Radar: " +' not in JS

