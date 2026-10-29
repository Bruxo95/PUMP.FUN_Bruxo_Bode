import pytest


@pytest.fixture(autouse=True)
def _stkeys_reset():
    """0.32.71: a saúde das chaves da Solana Tracker é global (memória); cada teste começa limpo."""
    from app import stkeys
    stkeys.reset()
    yield
    stkeys.reset()
