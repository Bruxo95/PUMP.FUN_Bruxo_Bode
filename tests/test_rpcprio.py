"""0.32.395 (pedido do dono, 20/11: "quando a real estiver ligada a prioridade é da real… depois de 1 s a fictícia"):
consultas ao RPC que não são da REAL esperam a REAL terminar + 1 s. Sem internet."""
import asyncio
import time

import httpx

from app import rpcprio


def _run(c):
    return asyncio.new_event_loop().run_until_complete(c)


def test_resto_espera_a_real_mais_1s_e_a_real_nao_espera(monkeypatch):
    rpcprio.reset()
    monkeypatch.setattr(rpcprio, "GAP_S", 0.2)
    ordem = []

    def net(req):
        import json
        ordem.append(json.loads(req.content)["method"])
        return httpx.Response(200, json={"result": 1})

    async def go():
        http = httpx.AsyncClient(transport=httpx.MockTransport(net), event_hooks={"request": [rpcprio.hook]})
        url = "https://mainnet.helius-rpc.com/?api-key=x"

        async def real():
            with rpcprio.real_scope():
                await http.post(url, json={"method": "real1"})
                await asyncio.sleep(0.3)               # a REAL ainda está saindo (simulação, envio…)
                await http.post(url, json={"method": "real2"})

        async def outro():
            await asyncio.sleep(0.05)
            await http.post(url, json={"method": "monitor"})
        t0 = time.monotonic()
        await asyncio.gather(real(), outro())
        return time.monotonic() - t0
    dur = _run(go())
    assert ordem == ["real1", "real2", "monitor"]       # o monitor esperou a REAL inteira…
    assert dur >= 0.5                                    # …e mais o intervalo depois dela
    v = rpcprio.view()
    assert v["esperas"] == 1 and v["operacoes_real"] == 1 and v["ativas"] == 0


def test_sem_real_ninguem_espera_e_outros_sites_nao_entram():
    rpcprio.reset()
    assert not rpcprio.busy()
    assert _run(rpcprio.wait_low()) == 0.0
    assert rpcprio.is_rpc("mainnet.helius-rpc.com") and rpcprio.is_rpc("api.mainnet-beta.solana.com")
    assert not rpcprio.is_rpc("api.dexscreener.com") and not rpcprio.is_rpc("vnvfluimpqvxbvdbmwqa.supabase.co")


def test_espera_tem_limite(monkeypatch):
    rpcprio.reset()
    monkeypatch.setattr(rpcprio, "MAX_WAIT_S", 0.2)
    rpcprio.state["ativas"] = 1                          # REAL presa: o resto não fica parado para sempre
    w = _run(rpcprio.wait_low())
    assert 0.15 <= w < 1.0
    rpcprio.reset()
