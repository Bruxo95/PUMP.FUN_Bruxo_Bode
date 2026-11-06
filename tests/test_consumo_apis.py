"""0.32.238 (dono: "só o Top traders ligado e ainda consome muito Helius e Solana Tracker")."""
import asyncio
import time

import httpx

from app.pumpfun import SOL_HTTP
from tests.test_api import UA, env, tok  # noqa: F401  (fixture env)


def test_dados_de_carteira_vao_no_rpc_publico(tmp_path):
    from tests.test_pump import _pump
    pf = _pump(tmp_path)
    pf.cfg.pump_rpc_http = "https://mainnet.helius-rpc.com/?api-key=" + "h" * 30
    pf.sol_usd = 150.0
    urls = []

    def handler(req):
        urls.append(str(req.url))
        return httpx.Response(200, json={"result": {"value": 1_000_000_000} if b"getBalance" in req.content else {"value": []}})
    pf.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert asyncio.run(pf.wallet_value("W" * 44))["sol"] == 1.0
    assert urls and all(u.rstrip("/") == SOL_HTTP for u in urls)


def test_carteiras_novas_so_com_compra_automatica_ligada(env):
    from app.monitor import SharedMonitor
    c, hub = env["c"], env["hub"]
    c.get("/api/pump", headers=tok(UA))
    mon = SharedMonitor(hub)
    called = []

    async def fc(m, now=None):
        called.append(m)
    mon.svc.fresh_check = fc
    hub.explore.lists = {"graduating": [{"mint": "M" * 44}]}
    pf = hub.engines[UA]
    pf.role = "admin"
    pf.cfg.pump_ar_fresh_on, pf.cfg.pump_ex_auto_on, pf.cfg.pump_auto_on = True, False, False
    assert asyncio.run(mon.fresh_once()) == 0 and not called
    pf.cfg.pump_ex_auto_on, pf.role = True, "user"            # usuário comum não tem compra do Explorar
    assert asyncio.run(mon.fresh_once()) == 0 and not called
    pf.role = "admin"
    assert asyncio.run(mon.fresh_once()) == 1 and called


def test_estudo_atualiza_a_cada_6_horas(env):
    hub = env["hub"]
    hub._study_key = lambda: "st-" + "k" * 30
    hub._study_at["W" * 44] = time.time() - 3600
    assert asyncio.run(hub.refresh_study_wallet("W" * 44)) is None and time.time() - hub._study_at["W" * 44] > 3000
