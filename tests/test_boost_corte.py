"""0.32.466 (checklist do dono): corte do BOOST pela análise das carteiras — bundle, snipers segurando, 10 maiores sem a curva,
mesma origem do dinheiro e valores repetidos nas últimas transações. Sem internet."""
import asyncio
import json
import time
import types

import httpx

from app import settings, sybil
from app.boostmig import BoostMig
from app.hub import PumpHub
from tests.test_boostmig import Svc, cfg, pronto
from tests.test_espelho_real import _pf

M = "Mint9999"


def test_build_sniper_e_top10_sem_curva():
    hs = [{"wallet": "Pool", "pct": 50.0, "kind": "programa"},
          {"wallet": "A", "pct": 6.0, "kind": "carteira", "first_slot": 101},     # bundle (bloco +1)
          {"wallet": "B", "pct": 7.0, "kind": "carteira", "first_slot": 110},     # sniper (bloco +10)
          {"wallet": "C", "pct": 5.0, "kind": "carteira", "first_slot": 124},     # sniper (bloco +24)
          {"wallet": "D", "pct": 4.0, "kind": "carteira", "first_slot": 200}]     # comprou depois
    r = sybil.build(M, "Dev", hs, 100, None, now=1e7)
    assert r["bundle_pct"] == 6.0 and r["sniper_pct"] == 12.0 and r["sniper_n"] == 2
    assert r["top10_pct"] == 22.0                                   # o pool (programa) fica de fora
    tags = {w["w"]: w["tags"] for w in r["carteiras"]}
    assert "sniper" in tags["B"] and "sniper" not in tags["A"] and "sniper" not in tags["D"]
    assert {"sniper_pct", "top10_pct", "micro_pct"} <= set(sybil.compact(r))


def test_micro_valores_repetidos():
    assert sybil.micro([0.01] * 3)["micro_pct"] is None                 # poucas lidas: sem veredito
    r = sybil.micro([0.0101, 0.0099, 0.01, 0.01, 0.5, 1.2, -0.01, None])
    assert r["micro_n"] == 5 and r["micro_sol"] == 0.01 and r["micro_lidas"] == 7 and r["micro_pct"] == round(5 / 7 * 100, 1)
    assert sybil.micro([0.1, 0.2, 0.3, 0.4, 0.5, 0.6])["micro_pct"] == 0.0
    tx = {"meta": {"preBalances": [2_000_000_000], "postBalances": [1_989_995_000], "fee": 5000}}
    assert abs(sybil.sol_of(tx) - 0.01) < 1e-9


def test_cuts_cada_ponto_e_zero_desliga():
    s = {"bundle_pct": 16, "sniper_pct": 11, "top10_pct": 31, "funder_max_pct": 21, "funder_max_n": 2, "micro_pct": 60, "micro_n": 7}
    lim = {"bundle": 15, "sniper": 10, "top10": 30, "funder": 20, "micro": 50}
    c = sybil.cuts(s, lim)
    assert len(c) == 5 and "bundle" in c[0] and "snipers" in c[1] and "10 maiores" in c[2] and "mesma origem" in c[3]
    assert sybil.cuts(s, {k: 0 for k in lim}) == []
    assert sybil.cuts({"bundle_pct": 15, "sniper_pct": 10, "top10_pct": 30}, lim) == []      # igual ao limite passa
    assert sybil.cuts({"erro": True, "bundle_pct": 90}, lim) == []
    assert settings.USER_KEYS["pump_bmr_cut_on"] == settings.USER_KEYS["pump_bm_cut_on"]
    assert settings.AJUSTES[5]["pump_bm_max_top10"] == 35.0 and settings.SAIDAS_V == 5


def test_analise_le_as_ultimas_transacoes_do_token():
    """As últimas transações do token entram na parte rápida: 6 de 8 com 0,02 SOL = robô de volume."""
    def h(req):
        b = json.loads(req.content)
        m, p = b["method"], b["params"]
        if m == "getTokenSupply":
            res = {"value": {"uiAmountString": "1000"}}
        elif m == "getTokenLargestAccounts":
            res = {"value": [{"address": "ataP", "uiAmountString": "600"}, {"address": "ataA", "uiAmountString": "100"}]}
        elif m == "getMultipleAccounts" and p[1]["encoding"] == "jsonParsed":
            res = {"value": [{"data": {"parsed": {"info": {"owner": {"ataP": "Pool", "ataA": "A"}[a]}}}} for a in p[0]]}
        elif m == "getMultipleAccounts":
            res = {"value": [{"owner": "pAMM" if a == "Pool" else sybil.SYSTEM_PROGRAM} for a in p[0]]}
        elif m == "getSignaturesForAddress":
            res = [{"signature": f"t{i}", "slot": 300} for i in range(8)] if p[0] == M else []
        elif m == "getTransaction":
            v = 0.02 if p[0] in ("t0", "t1", "t2", "t3", "t4", "t5") else 0.3
            res = {"meta": {"preBalances": [10**10], "postBalances": [10**10 - int(v * 1e9) - 5000], "fee": 5000}}
        else:
            res = None
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": res})

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(h)) as c:
            return await sybil.analyze(sybil.Rpc(c, sybil.alchemy_url("k" * 20)), M, None, now=5000)
    r = asyncio.run(go())
    assert r["micro_lidas"] == 8 and r["micro_n"] == 6 and r["micro_sol"] == 0.02 and r["micro_pct"] == 75.0
    assert "valores repetidos" not in r                              # vai no resultado como micro_*
    assert sybil.cuts(r, {"micro": 50})


def test_boost_nao_entra_quando_estoura_o_checklist(tmp_path):
    pf = _pf(tmp_path)
    pf.role = "admin"
    now = time.time()
    pf.tokens[M] = {"price": 1e-6, "last_t": now, "symbol": "BUN", "name": "Bundle", "pool": "pumpswap"}
    for k, v in vars(cfg(pump_bm_on=True, pump_bm_sol=0.05, pump_bm_ext_on=False, pump_bm_sg_after=False)).items():
        setattr(pf.cfg, k, v)
    pf.cfg.pump_bm_cut_on, pf.cfg.pump_bm_cut_sniper_pct = True, 10.0
    bm = BoostMig(Svc(pf.tokens), clock=lambda: now)
    b = pronto(bm, M, now - 60, now)
    hub = types.SimpleNamespace(bm=bm, system_keys={"alchemy_api_key": "k" * 20})
    b["sybil_want"] = now
    b["sybil"] = {"nivel": "baixo", "bundle_pct": 3, "sniper_pct": 18, "top10_pct": 20}
    asyncio.run(PumpHub._bm_user(hub, "u1", pf, now))
    u = b["users"]["u1"]
    assert u["estado"] == "fora" and "snipers ainda segurando" in u["motivo"]
    assert not [p for p in pf.positions() if p["mint"] == M]
    u.clear()
    pf.cfg.pump_bm_cut_on = False                                     # desligado: só informa e entra
    asyncio.run(PumpHub._bm_user(hub, "u1", pf, now + 1))
    assert u["estado"] == "entrou"
