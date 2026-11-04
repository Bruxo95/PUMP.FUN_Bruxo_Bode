"""0.32.188 (pedido do dono): quanto cada aba gasta de cada serviço. Sem internet."""
import asyncio
import inspect

from app import apiusage, hub as hubmod, monitor
from app.apiusage import Usage, run_as

T0 = 1_800_000_000.0


def test_requests_inside_a_tagged_loop_count_for_that_tab():
    u = Usage()

    async def explorar():
        u.count("data.solanatracker.io", now=T0)
        u.count("mainnet.helius-rpc.com", body=b'{"method":"getProgramAccounts"}', now=T0)

    async def go():
        await run_as("Explorar", explorar())
        u.count("mainnet.helius-rpc.com", body=b'{"method":"getSlot"}', now=T0)          # clique numa tela
    asyncio.run(go())
    L = {x["aba"]: x for x in u.por_aba(now=T0 + 5)}
    ex = {(s["api"], s["tipo"]): s["janelas"]["1"] for s in L["Explorar"]["servicos"]}
    assert ex[("Solana Tracker", "requisições")] == 1 and ex[("Helius (RPC da Solana)", "créditos")] == 10
    assert L["Explorar"]["total"]["24"] == 2
    tela = {(s["api"], s["tipo"]): s["janelas"]["1"] for s in L[apiusage.SEM_ORIGEM]["servicos"]}
    assert tela[("Helius (RPC da Solana)", "créditos")] == 1


def test_every_background_loop_is_tagged():
    src = inspect.getsource(hubmod.PumpHub.start) if hasattr(hubmod.PumpHub, "start") else ""
    assert src.count("run_as(") >= 20 and "asyncio.create_task(self." not in src
    assert inspect.getsource(monitor.SharedMonitor.start).count("run_as") >= 3
