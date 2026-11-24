"""0.32.439 (dono, 24/11): trocar a chave da Solana Tracker apaga o erro da chave antiga e testa a nova na hora."""
import asyncio

import httpx

from app.hub import PumpHub
from tests.test_espelho_real import _pf


class Vault:
    async def save(self, *a):
        pass


async def _noaudit(*a, **k):
    pass


def test_trocar_chave_limpa_o_erro_e_consulta_na_hora(tmp_path, monkeypatch):
    pf = _pf(tmp_path)
    pf.user_id = "u1"

    class Keys(dict):
        def set(self, k, v):
            self[k] = v

    pf.keys = Keys(solanatracker_api_key="chave-antiga")
    pf.lb_status.update(error="créditos do mês acabaram nesta chave (plano da Solana Tracker)")
    seen = []

    def handler(r):
        seen.append(r.headers.get("x-api-key"))
        return httpx.Response(200, json={"traders": []})

    hub = PumpHub.__new__(PumpHub)
    hub.vault, hub.db = Vault(), None
    hub.key_changed = lambda *a: None
    hub._wire_wallet = lambda pf: None
    monkeypatch.setattr("app.hub.audit", _noaudit)

    async def go():
        pf.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        await PumpHub.set_secret(hub, pf, "solanatracker_api_key", "chave-nova-de-teste-123")
        assert pf.lb_status.get("error") is None
        await asyncio.sleep(0.05)
        await pf.http.aclose()

    asyncio.new_event_loop().run_until_complete(go())
    assert seen == ["chave-nova-de-teste-123"] and pf.lb_status.get("error") is None and pf.lb_status.get("at")
