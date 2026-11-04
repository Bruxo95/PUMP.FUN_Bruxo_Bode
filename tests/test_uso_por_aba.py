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


def test_bnb_is_another_project_and_is_not_counted():
    u = Usage()

    async def bnb():
        u.count("api.dexscreener.com", now=T0)
        u.count("bsc-rpc.publicnode.com", now=T0)

    async def go():
        await run_as(apiusage.BNB_ORIGEM, bnb())
        u.count("bsc-rpc.publicnode.com", now=T0)                  # mesmo sem marca, RPC da BNB não aparece
    asyncio.run(go())
    W = u.windows(now=T0)
    assert all(r["desde_inicio"] == 0 and r["api"] not in apiusage.BNB_APIS for r in W) and u.por_aba(now=T0) == [] and not u.month


def test_windows_survive_a_restart_and_main_services_always_show():
    u = Usage()

    async def explorar():
        u.count("data.solanatracker.io", now=T0 - 3 * 3600)
        u.count("data.solanatracker.io", now=T0 - 30 * 3600)          # mais de 24 h: não volta

    async def go():
        await run_as("Explorar", explorar())
    asyncio.run(go())
    d = u.dump_win(now=T0)
    v = Usage()
    v.load_win(d, now=T0)
    r = next(x for x in v.windows(now=T0) if x["api"] == "Solana Tracker" and x["tipo"] == "requisições")
    assert r["janelas"]["6"]["n"] == 1 and r["janelas"]["1"]["n"] == 0 and r["janelas"]["24"]["n"] == 1
    ex = {(s["api"], s["tipo"]): s["janelas"]["6"] for s in next(x for x in v.por_aba(now=T0) if x["aba"] == "Explorar")["servicos"]}
    assert ex[("Solana Tracker", "requisições")] == 1
    nomes = {(x["api"], x["tipo"]) for x in Usage().windows(now=T0)}
    assert ("Helius (RPC da Solana)", "créditos") in nomes and ("Solana Tracker", "requisições") in nomes
