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
