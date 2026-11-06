"""0.32.236 (dono: "troquei as chaves e ainda não consegue fazer a leitura; o sistema tem que ver a troca e zerar a contagem")."""
import asyncio
import time

import httpx

from app.apiusage import Usage
from tests.test_api import UA, env, tok  # noqa: F401  (fixture env)

H = "Helius (RPC da Solana)"
NOVO = "https://mainnet.helius-rpc.com/?api-key=" + "n" * 30
VELHO = "https://mainnet.helius-rpc.com/?api-key=" + "v" * 30


def test_leitura_usa_o_rpc_do_sistema_e_pede_versao_1(tmp_path):
    from tests.test_pump import _pump
    pf = _pump(tmp_path)
    pf.market.sys_rpc = NOVO
    vistos = []

    def handler(req):
        import json
        vistos.append((str(req.url), json.loads(req.content)["params"][1]["maxSupportedTransactionVersion"]))
        return httpx.Response(200, json={"result": {"meta": {}, "transaction": {}}})
    pf.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    res = asyncio.run(pf._get_tx("sig"))
    assert res is not None and vistos[0][0] == NOVO and vistos[0][1] == 1
    assert pf.market.rpc_ok_at > 0


def test_zerar_apaga_a_contagem_da_api():
    u = Usage()
    now = time.time()
    u.count("mainnet.helius-rpc.com", now=now, body=b'{"method":"getTransaction"}')
    u.count("data.solanatracker.io", key="velha", now=now)
    u.count("data.solanatracker.io", key="outra", now=now)
    assert any(r["api"] == H and r["desde_inicio"] for r in u.windows(now))
    u.zerar(H)
    assert not any(r["api"] == H and r["desde_inicio"] for r in u.windows(now))
    assert all(n == 0 for (m, a, c), n in u.month.items() if a.startswith(H))
    u.zerar("Solana Tracker", "velha")                 # só a chave trocada
    st = {c: n for (m, a, c), n in u.month.items() if a == "Solana Tracker"}
    assert sorted(st.values()) == [0, 1]


def test_trocar_a_chave_do_sistema_zera_uso_e_recusas(env):
    c, hub = env["c"], env["hub"]
    A = tok(UA)
    assert c.post("/api/admin/keys", json={"name": "rpc_url", "value": VELHO}, headers=A).json()["ok"]
    us = hub.__dict__.setdefault("usage", Usage())
    us.count("mainnet.helius-rpc.com", body=b'{"method":"getTransaction"}')
    hub.market.rpc_429_at = time.time()
    hub.market.rpc_status.update(ws=True, prov=H, queued=500, parsed=0)
    assert c.post("/api/admin/keys", json={"name": "rpc_url", "value": NOVO}, headers=A).json()["ok"]
    assert hub.market.sys_rpc == NOVO and hub.market.rpc_429_at == 0.0 and hub.market.rpc_status["queued"] == 0
    assert not any(r["api"] == H and r["desde_inicio"] for r in us.windows())
    assert "rpc_url" in hub.key_resets
    snap = c.get("/api/pump", headers=A).text
    assert "n" * 30 not in snap and "v" * 30 not in snap          # a chave nunca volta pela API


def test_solana_tracker_conta_so_a_chave_em_uso():
    """0.32.237: o limite de 10 mil é por chave; a chave trocada deixa de contar no mês e no "estourou"."""
    from app.apiusage import key_tag
    u = Usage()
    now = time.time()
    mes = time.strftime("%Y-%m", time.gmtime(now))
    u.month[(mes, "Solana Tracker", key_tag("velha"))] = 10_432
    u.month[(mes, "Solana Tracker", key_tag("nova"))] = 17
    u.win[("Solana Tracker", "requisições")] = {int(now // 60): 17}
    u.st_tags = lambda: {key_tag("velha"), key_tag("nova")}
    assert "Solana Tracker" in u.estourou(now)
    u.st_tags = lambda: {key_tag("nova")}
    r = [x for x in u.windows(now) if x["api"] == "Solana Tracker" and x["tipo"] == "requisições"][0]
    assert r["mes"] == 17 and "Solana Tracker" not in u.estourou(now)
