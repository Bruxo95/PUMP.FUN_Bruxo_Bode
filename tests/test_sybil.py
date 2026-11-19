"""0.32.382 (pedido do dono): carteiras ligadas ao DEV nos tokens do BOOST (Alchemy). Sem internet: respostas falsas."""
import asyncio
import json

import httpx
import pytest

from app import sybil

MINT, DEV, FUND, CEX = "Mint1111", "Dev11111", "Fund1111", "Cex11111"
POOL = "PoolPda1"


def test_build_grupo_do_dev_bundle_e_nivel():
    hs = [
        {"wallet": POOL, "pct": 60.0, "kind": "programa"},
        {"wallet": "A", "pct": 8.0, "kind": "carteira", "first_slot": 100, "funder": DEV, "age_s": 3600},      # financiada pelo DEV
        {"wallet": "B", "pct": 6.0, "kind": "carteira", "first_slot": 101, "funder": FUND, "age_s": 7200},     # mesma origem do DEV
        {"wallet": "C", "pct": 5.0, "kind": "carteira", "first_slot": 102, "funder": "X", "age_s": 9e6},       # bundle (bloco +2)
        {"wallet": "D", "pct": 4.0, "kind": "carteira", "first_slot": 900, "funder": "A", "age_s": 9e6},       # financiada por A
        {"wallet": "E", "pct": 3.0, "kind": "carteira", "first_slot": 950, "funder": CEX, "age_s": 9e6},
        {"wallet": "F", "pct": 3.0, "kind": "carteira", "first_slot": 960, "funder": CEX, "age_s": 9e6},
    ]
    r = sybil.build(MINT, DEV, hs, 100, FUND, creator_pct=2.0, alert_pct=20, bundle_lim=25, now=1e7)
    assert r["cluster_n"] == 3                                   # A, B e D
    assert r["cluster_pct"] == 8 + 6 + 4 + 2                       # + o DEV fora dos maiores
    assert r["bundle_n"] == 3 and r["bundle_pct"] == 8 + 6 + 5      # recebeu até 2 blocos depois do lançamento
    assert r["real_dev_pct"] == 8 + 6 + 5 + 4 + 2
    assert r["nivel"] == "alto" and r["programas_pct"] == 60.0
    assert {"funder": CEX, "n": 2, "pct": 6.0, "dev": False} in r["grupos"]           # mesma origem, sem ligação com o DEV
    tags = {w["w"]: w["tags"] for w in r["carteiras"]}
    assert "ligada ao dev" in tags["A"] and "bundle" in tags["C"] and "mesma origem" in tags["E"] and "nova" in tags["A"]
    baixo = sybil.build(MINT, DEV, [{"wallet": "Z", "pct": 3.0, "kind": "carteira", "first_slot": 999, "funder": "Q"}], 100, FUND)
    assert baixo["nivel"] == "baixo"
    assert sybil.build(MINT, DEV, [{"wallet": POOL, "pct": 90.0, "kind": "programa"}], 100, None)["nivel"] == "sem dados"


def test_funder_e_chave():
    tx = {"transaction": {"message": {"accountKeys": [{"pubkey": FUND}, {"pubkey": "W"}],
                                      "instructions": [{"parsed": {"type": "transfer", "info": {"source": FUND, "destination": "W", "lamports": 50_000_000}}}]}},
          "meta": {"preBalances": [10, 0], "postBalances": [5, 5], "innerInstructions": []}}
    assert sybil.funder_of(tx, "W") == FUND
    tx2 = {"transaction": {"message": {"accountKeys": ["P", "W"], "instructions": []}}, "meta": {"preBalances": [100, 0], "postBalances": [40, 55]}}
    assert sybil.funder_of(tx2, "W") == "P"                          # sem instrução legível: quem perdeu SOL
    assert sybil.key_of("https://solana-mainnet.g.alchemy.com/v2/abcDEF1234567890xyz") == "abcDEF1234567890xyz"
    with pytest.raises(ValueError):
        sybil.key_of("https://outro-site.com/v2/abcDEF1234567890xyz")
    assert sybil.alchemy_url("k" * 20).endswith("/v2/" + "k" * 20)


def _fake():
    """Responde como um RPC da Solana para um token com pool, DEV, 1 carteira financiada pelo DEV e 1 bundle."""
    sigs = {"ataA": [{"signature": "sA", "slot": 101}], "ataB": [{"signature": "sB", "slot": 500}], "ataDev": [{"signature": "sD", "slot": 100}],
            "A": [{"signature": "fA", "slot": 50, "blockTime": 1000}], "B": [{"signature": "fB", "slot": 40, "blockTime": 1000}],
            DEV: [{"signature": "fDev", "slot": 30, "blockTime": 900}]}
    txs = {"fA": (DEV, "A"), "fB": (CEX, "B"), "fDev": (FUND, DEV)}

    def h(req):
        b = json.loads(req.content)
        m, p = b["method"], b["params"]
        if m == "getTokenSupply":
            res = {"value": {"uiAmountString": "1000"}}
        elif m == "getTokenLargestAccounts":
            res = {"value": [{"address": "ataPool", "uiAmountString": "600"}, {"address": "ataA", "uiAmountString": "150"},
                             {"address": "ataB", "uiAmountString": "50"}]}
        elif m == "getMultipleAccounts" and p[1]["encoding"] == "jsonParsed":
            own = {"ataPool": POOL, "ataA": "A", "ataB": "B"}
            res = {"value": [{"data": {"parsed": {"info": {"owner": own[a]}}}} for a in p[0]]}
        elif m == "getMultipleAccounts":
            res = {"value": [{"owner": "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA" if a == POOL else sybil.SYSTEM_PROGRAM} for a in p[0]]}
        elif m == "getTokenAccountsByOwner":
            res = {"value": [{"pubkey": "ataDev", "account": {"data": {"parsed": {"info": {"tokenAmount": {"uiAmountString": "20"}}}}}}]}
        elif m == "getSignaturesForAddress":
            res = sigs.get(p[0], [])
        elif m == "getTransaction":
            src, dst = txs[p[0]]
            res = {"blockTime": 1000, "transaction": {"message": {"accountKeys": [src, dst], "instructions": [
                {"parsed": {"type": "transfer", "info": {"source": src, "destination": dst, "lamports": 10**8}}}]}}, "meta": {"preBalances": [1, 0], "postBalances": [0, 1]}}
        else:
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "error": {"message": "?"}})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": res})
    return httpx.MockTransport(h)


def test_analyze_com_rpc_falso():
    async def go():
        async with httpx.AsyncClient(transport=_fake()) as h:
            rpc = sybil.Rpc(h, sybil.alchemy_url("k" * 20))
            return await sybil.analyze(rpc, MINT, DEV, top_n=15, now=5000)
    r = asyncio.run(go())
    assert r["launch_slot"] == 100 and r["dev_pct"] == 2.0 and r["programas_pct"] == 60.0
    w = {x["w"]: x for x in r["carteiras"]}
    assert POOL not in w                                            # pool fica de fora
    assert "ligada ao dev" in w["A"]["tags"] and "bundle" in w["A"]["tags"]
    assert w["B"]["tags"] == [] or "bundle" not in w["B"]["tags"]
    assert r["real_dev_pct"] == 15 + 2 and r["nivel"] == "médio"
    assert r["creator_funder"] == FUND and r["chamadas"] > 5


def test_hub_novo_primeiro_parcial_em_20s_e_termina_depois(tmp_path, monkeypatch):
    """0.32.385 (pedido do dono): resultado rápido em até 20 s; o que faltou só termina quando não há token novo esperando."""
    from tests.test_boostmig import Svc, _pf, cfg, M
    from app import boostmig
    from app.boostmig import BoostMig
    from app.hub import PumpHub
    import time as _t
    monkeypatch.setattr(sybil, "START_GAP_S", 0.0)
    monkeypatch.setattr(sybil, "MIN_GAP_S", 0.0)
    pf = _pf(tmp_path)
    pf.role = "admin"
    for k, v in vars(cfg(pump_bm_on=True)).items():
        setattr(pf.cfg, k, v)
    now = _t.time()
    bm = BoostMig(Svc(pf.tokens), clock=lambda: now)
    b = bm.on_migration({"mint": MINT, "pool": "pump-amm"}, now - 30)
    b["creator"], b["symbol"] = DEV, "GTAVI"
    hub = PumpHub.__new__(PumpHub)
    hub.bm, hub.system_keys, hub.engines = bm, {}, {"u1": pf}

    async def go():
        async with httpx.AsyncClient(transport=_fake()) as h:
            hub.http = h
            PumpHub.sybil_tick(hub, now)
            assert not b.get("sybil")                               # sem a chave da Alchemy nada roda
            hub.system_keys = {"alchemy_api_key": "k" * 20}
            monkeypatch.setattr(sybil, "DEADLINE_S", 0.0)          # prazo estourado: só a parte básica
            PumpHub.sybil_tick(hub, now)
            await hub.sybil_st["task"]
            assert b["sybil"]["parcial"] > 0 and b["sybil"]["primeiro_s"] is not None
            # chega um token NOVO: ele vai antes das pendências do anterior
            b2 = bm.on_migration({"mint": "Mint2222", "pool": "pump-amm"}, _t.time() - 6)
            b2["creator"] = DEV
            PumpHub.sybil_tick(hub, _t.time())
            assert hub.sybil_st["rodando"] == "Mint2222"
            await hub.sybil_st["task"]
            monkeypatch.setattr(sybil, "DEADLINE_S", 20.0)
            for _ in range(4):                                      # sem token novo: termina as pendências
                PumpHub.sybil_tick(hub, _t.time())
                if hub.sybil_st.get("task") and not hub.sybil_st["task"].done():
                    await hub.sybil_st["task"]
    asyncio.run(go())
    assert b["sybil"]["parcial"] == 0 and b["sybil"].get("completo_s") is not None
    assert "ligada ao dev" in {w["w"]: w for w in b["sybil"]["carteiras"]}["A"]["tags"]
    assert b["sybil"]["nivel"] in ("médio", "alto")
    assert any("alerta de carteiras" in e["msg"] for e in pf.events)
    assert bm.view(b)["sybil"]["nivel"] == b["sybil"]["nivel"] and "carteiras" not in bm.view(b)["sybil"]
    row = boostmig.history_row(b, now + 1300)
    assert row["sybil"]["nivel"] == b["sybil"]["nivel"]
    g = boostmig.hist_study([dict(row, p0=1.0)])["grupos"]
    assert any(x["grupo"].startswith("Carteiras: alerta") for x in g)


def test_sem_dev_le_o_dev_na_curva_pela_alchemy():
    """0.32.383: o RPC do sistema parou e o BOOST ficou sem DEV; a análise lê o DEV na conta da curva."""
    import base64
    from solders.keypair import Keypair
    dev = str(Keypair().pubkey())
    from solders.pubkey import Pubkey
    raw = bytes(49) + bytes(Pubkey.from_string(dev)) + bytes(10)
    inner = _fake()

    def h(req):
        b = json.loads(req.content)
        if b["method"] == "getAccountInfo":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"value": {"data": [base64.b64encode(raw).decode(), "base64"]}}})
        return inner.handle_request(req)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(h)) as c:
            return await sybil.analyze(sybil.Rpc(c, sybil.alchemy_url("k" * 20)), MINT, None, curve_pda="Curve111", now=5000)
    r = asyncio.run(go())
    assert r["creator"] == dev and r["creator_src"] == "alchemy"


def test_ritmo_e_429_tenta_de_novo():
    """0.32.384: a Alchemy respondeu 429 em todas as análises de 19/11; agora espera e tenta de novo."""
    n = {"c": 0}

    def h(req):
        n["c"] += 1
        if n["c"] <= 2:
            return httpx.Response(429, json={})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"ok": 1}})
    dormiu = []

    async def fake_sleep(s):
        dormiu.append(s)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(h)) as c:
            rpc = sybil.Rpc(c, "https://solana-mainnet.g.alchemy.com/v2/x", sleep=fake_sleep)
            return await rpc.call("getHealth", []), rpc
    r, rpc = asyncio.run(go())
    assert r == {"ok": 1} and rpc.limit_n == 2 and 1.0 in dormiu and 2.0 in dormiu


def test_boost_sem_rpc_usa_reserva_e_nao_espera_para_sempre():
    from app import boostmig
    from app.boostmig import BoostMig
    from tests.test_boostmig import Svc, cfg, M
    now = 1_000_000.0
    bm = BoostMig(Svc({}), clock=lambda: now)
    b = bm.on_migration({"mint": M, "pool": "pump-amm", "symbol": "ROCK", "name": "Rockstar"}, now - 40)
    est, why = bm.decide(cfg(pump_bm_watch_s=0, pump_bm_min_buys=0, pump_bm_require_safety=True), b, now, set(), 0)
    assert "DEV" not in why                                      # 40 s sem DEV: segue sem o filtro de DEV scam
    b2 = bm.on_migration({"mint": M[:-4] + "zzzz", "pool": "pump-amm", "symbol": "X2", "name": "X2"}, now - 50)
    est, why = bm.decide(cfg(pump_bm_watch_s=0, pump_bm_min_buys=0, pump_bm_require_safety=True), b2, now, set(), 0)
    assert est == "fora" and "trava" in why                        # 50 s sem trava lida: não conferido → fora (exigir trava ligado)

    async def sistema(keys, enc):
        return None

    async def reserva(keys, enc):
        return [{"ok": k} for k in keys]
    bm.rpc_multi, bm.rpc_backup = sistema, reserva
    vals = asyncio.run(bm._rpc(["a", "b"], "base64"))
    assert vals == [{"ok": "a"}, {"ok": "b"}] and bm.st["reserva"] == 1
    boostmig.ALCHEMY_BACKUP = 0.0
    try:
        bm.svc._rpc_multi = None
    except Exception:
        pass
    boostmig.ALCHEMY_BACKUP = 1.0
