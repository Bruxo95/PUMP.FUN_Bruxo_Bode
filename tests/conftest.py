import pytest


@pytest.fixture(autouse=True)
def _stkeys_reset():
    """0.32.71: a saúde das chaves da Solana Tracker é global (memória); cada teste começa limpo."""
    from app import stkeys
    stkeys.reset()
    yield
    stkeys.reset()


@pytest.fixture(autouse=True)
def _real_sem_idade_minima(monkeypatch, request):
    """0.32.254: os testes antigos da REAL compram tokens recém-criados; a idade mínima (padrão 10 min) fica em 0 neles.
    O teste da regra (test_real_idade_minima.py) usa o padrão de verdade."""
    if "test_real_idade_minima" in request.node.nodeid:
        yield
        return
    from app import settings
    monkeypatch.setitem(settings.USER_KEYS, "pump_real_min_age_min", (float, 0.0, 0.0, 10080.0))
    yield


@pytest.fixture(autouse=True)
def _saidas_do_original(monkeypatch, request):
    """0.32.323: os padrões de saída mudaram (stop 30, vende com o trader no prejuízo, stop móvel 25/20, "só quem dá resultado"
    ligado). Os testes antigos (e os de referência, tests/test_pump.py) foram escritos com os do original e continuam neles.
    O teste da regra nova (test_saidas_novas.py) usa o padrão de verdade."""
    if "test_saidas_novas" in request.node.nodeid:
        yield
        return
    from app import settings
    for k, v in settings.SAIDAS_OLD.items():
        spec = settings.USER_KEYS[k]
        monkeypatch.setitem(settings.USER_KEYS, k, (spec[0], v) + tuple(spec[2:]))
    yield


@pytest.fixture(autouse=True)
def _sem_liga_nos_testes_antigos(monkeypatch, request):
    """0.32.328: a liga de candidatos vem ligada. Os testes de referência (ordem do ranking) ficam sem ela; test_liga.py usa o padrão."""
    if "test_liga" in request.node.nodeid:
        yield
        return
    from app import settings
    spec = settings.USER_KEYS["pump_liga_on"]
    monkeypatch.setitem(settings.USER_KEYS, "pump_liga_on", (spec[0], False) + tuple(spec[2:]))
    yield


@pytest.fixture(autouse=True)
def _real_sem_trava_por_tela(monkeypatch, request):
    """0.32.325: a trava por tela (a REAL só compra de tela que provou lucro na fictícia) vem ligada. Os testes antigos da REAL
    começam sem histórico, então nela a trava fica desligada. O teste da regra (test_trava_tela.py) usa o padrão."""
    if "test_trava_tela" in request.node.nodeid:
        yield
        return
    from app import settings
    spec = settings.USER_KEYS["pump_tab_gate_on"]
    monkeypatch.setitem(settings.USER_KEYS, "pump_tab_gate_on", (spec[0], False) + tuple(spec[2:]))
    yield


@pytest.fixture(autouse=True)
def _real_sem_prova(monkeypatch, request):
    """0.32.265: a prova "REAL só depois de lucro na fictícia" vale também para a lista manual; os testes antigos da REAL
    usam carteiras manuais sem histórico, então nela a prova fica desligada. O teste da regra usa o padrão."""
    if "test_real_prova" in request.node.nodeid:
        yield
        return
    from app import settings
    monkeypatch.setitem(settings.USER_KEYS, "pump_real_need_win", (bool, False, 0, 1))
    yield


@pytest.fixture(autouse=True)
def _sem_exigir_preco_de_mercado(monkeypatch, request):
    """0.32.331: token de fora da pump.fun só é copiado com preço de mercado para conferir o do trade. Os testes antigos copiam
    token de fora sem DexScreener; o teste da regra (test_preco_conferido.py) usa o padrão."""
    if "test_preco_conferido" in request.node.nodeid:
        yield
        return
    from app import settings
    spec = settings.USER_KEYS["pump_px_need_mkt"]
    monkeypatch.setitem(settings.USER_KEYS, "pump_px_need_mkt", (spec[0], False) + tuple(spec[2:]))
    yield


@pytest.fixture(autouse=True)
def _sem_stop_de_ganho_nos_testes_antigos(monkeypatch, request):
    """0.32.332: o stop de ganho autônomo vem ligado na fictícia (Solana, Robinhood e BNB). Os testes antigos de saída (stop móvel,
    alvo, venda do trader) foram escritos sem ele e continuam assim. test_stop_ganho.py usa o padrão de verdade."""
    if "test_stop_ganho" in request.node.nodeid:
        yield
        return
    from app import bnbcopy, hoodcopy, settings
    spec = settings.USER_KEYS["pump_sg_on"]
    monkeypatch.setitem(settings.USER_KEYS, "pump_sg_on", (spec[0], False) + tuple(spec[2:]))
    spec = settings.USER_KEYS["pump_sg_entrada_on"]                 # 0.32.335: faixas de entrada ruins
    monkeypatch.setitem(settings.USER_KEYS, "pump_sg_entrada_on", (spec[0], False) + tuple(spec[2:]))
    monkeypatch.setitem(hoodcopy.CFG_DEFAULT, "sg_on", False)
    monkeypatch.setitem(bnbcopy.CFG_DEFAULT, "sg_on", False)
    spec = settings.USER_KEYS["pump_runup_max_pct"]                  # 0.32.332: filtro de entrada no topo ligado por padrão
    monkeypatch.setitem(settings.USER_KEYS, "pump_runup_max_pct", (spec[0], 0.0) + tuple(spec[2:]))
    yield
