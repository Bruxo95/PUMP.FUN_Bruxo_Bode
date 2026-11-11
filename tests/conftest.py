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
def _real_sem_prova(monkeypatch, request):
    """0.32.265: a prova "REAL só depois de lucro na fictícia" vale também para a lista manual; os testes antigos da REAL
    usam carteiras manuais sem histórico, então nela a prova fica desligada. O teste da regra usa o padrão."""
    if "test_real_prova" in request.node.nodeid:
        yield
        return
    from app import settings
    monkeypatch.setitem(settings.USER_KEYS, "pump_real_need_win", (bool, False, 0, 1))
    yield
