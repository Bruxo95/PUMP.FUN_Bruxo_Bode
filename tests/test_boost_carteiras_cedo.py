"""0.32.486 (pedido do dono, caso PODIUM 27/11: comprou e o alerta ALTO das carteiras só chegou depois): a análise das carteiras
começa na hora em que o token tem nome, DEV e 80 compras, e para em 20 s de observação. Com a trava ligada, alerta ALTO (mesmo
parcial) não compra; análise que não fechou ou não respondeu no prazo compra assim mesmo. Tudo sem internet."""
import asyncio
import time
import types

from app import boostmig
from app.boostmig import BoostMig
from tests.test_boostmig import DEV, M, Svc, cfg, pronto


def run(c):
    return asyncio.new_event_loop().run_until_complete(c)


def _obs(now, desde):
    return [[now - desde, 1.0], [now - desde / 2, 1.01], [now, 1.02]]


def test_comeca_cedo_so_com_nome_dev_compras_e_tempo():
    now = 1_000_000.0
    bm = BoostMig(Svc({}), clock=lambda: now)
    b = pronto(bm, M, now - 30, now, buys_m5=80, samples=[])
    assert bm.sybil_early(b, now)                                     # padrão: na hora, sem esperar a observação
    b["samples"] = _obs(now, 10)
    assert bm.sybil_early(b, now)
    b["buys_m5"] = 79
    assert not bm.sybil_early(b, now)                                 # poucas compras
    b["buys_m5"], b["samples"] = 80, _obs(now, 9)
    antes, boostmig.SYBIL_EARLY_S = boostmig.SYBIL_EARLY_S, 10.0
    try:
        assert not bm.sybil_early(b, now)                             # com "observando há 10 s": ainda não
    finally:
        boostmig.SYBIL_EARLY_S = antes
    b["samples"], b["creator"] = _obs(now, 10), None
    assert not bm.sybil_early(b, now)                                 # sem DEV
    b["creator"], b["safety_ok"] = DEV, False
    assert not bm.sybil_early(b, now)                                 # trava de venda: não gasta a Alchemy
    b["safety_ok"], b["users"] = True, {"u1": {"estado": "fora"}}
    assert not bm.sybil_early(b, now)                                 # ninguém mais espera este token
    b["users"] = {"u1": {"estado": "esperar"}}
    assert bm.sybil_early(b, now)
    b["sybil_want"] = now
    assert not bm.sybil_early(b, now)                                 # já começou


def test_prazo_vinte_segundos_de_observacao():
    now = 1_000_000.0
    b = {"samples": _obs(now, 10)}
    assert boostmig.sybil_deadline(b, now) == now + 10                # começou aos 10 s: fecha aos 20 s de observação
    b = {"samples": _obs(now, 50)}
    assert boostmig.sybil_deadline(b, now) == now + 10                # começou tarde: ganha os mesmos 10 s
    assert boostmig.sybil_complete({"nivel": "baixo"})
    assert not boostmig.sybil_complete({"nivel": "baixo", "parcial": 3})
    assert not boostmig.sybil_complete({"nivel": "sem dados"})
    assert not boostmig.sybil_complete({"nivel": "baixo", "erro": True})
    assert not boostmig.sybil_complete(None)


def test_trava_barra_alto_e_compra_com_analise_incompleta(tmp_path):
    from app.hub import PumpHub
    from tests.test_espelho_real import _pf
    pf = _pf(tmp_path)
    pf.role = "admin"
    now = time.time()
    pf.tokens[M] = {"price": 1e-6, "last_t": now, "symbol": "GTAVI", "name": "GTA VI", "pool": "pumpswap"}
    for k, v in vars(cfg(pump_bm_on=True, pump_bm_sol=0.05, pump_bm_ext_on=False, pump_bm_sg_after=False, pump_bm_sybil_block=True)).items():
        setattr(pf.cfg, k, v)
    bm = BoostMig(Svc(pf.tokens), clock=lambda: now)
    b = pronto(bm, M, now - 60, now)
    hub = types.SimpleNamespace(bm=bm, system_keys={"alchemy_api_key": "k" * 20})
    b["sybil_want"], b["sybil_dl"] = now - 5, now + 5
    run(PumpHub._bm_user(hub, "u1", pf, now))
    u = b["users"]["u1"]
    assert u["estado"] == "esperar" and "faltam 5 s" in u["motivo"]
    b["sybil"] = {"nivel": "alto", "parcial": 4, "motivo": "DEV + carteiras ligadas com 21%"}
    run(PumpHub._bm_user(hub, "u1", pf, now + 1))                     # caso PODIUM: ALTO mesmo parcial = fora
    assert u["estado"] == "fora" and "alerta ALTO" in u["motivo"]
    assert not [p for p in pf.positions() if p["mint"] == M]
    u.clear()
    b["sybil"] = {"nivel": "baixo", "parcial": 4}                     # não fechou no prazo: compra assim mesmo
    run(PumpHub._bm_user(hub, "u1", pf, now + 6))
    assert u["estado"] == "entrou"
    pos = [p for p in pf.positions() if p["mint"] == M]
    assert pos and "faltaram 4" in str(pos[0].get("auto") or pos[0].get("entrou_porque") or "")


def test_sem_resposta_no_prazo_compra_assim_mesmo(tmp_path):
    from app.hub import PumpHub
    from tests.test_espelho_real import _pf
    pf = _pf(tmp_path)
    pf.role = "admin"
    now = time.time()
    pf.tokens[M] = {"price": 1e-6, "last_t": now, "symbol": "GTAVI", "name": "GTA VI", "pool": "pumpswap"}
    for k, v in vars(cfg(pump_bm_on=True, pump_bm_sol=0.05, pump_bm_ext_on=False, pump_bm_sg_after=False, pump_bm_sybil_block=True)).items():
        setattr(pf.cfg, k, v)
    bm = BoostMig(Svc(pf.tokens), clock=lambda: now)
    b = pronto(bm, M, now - 60, now)
    hub = types.SimpleNamespace(bm=bm, system_keys={"alchemy_api_key": "k" * 20})
    b["sybil_want"], b["sybil_dl"] = now - 15, now - 1
    run(PumpHub._bm_user(hub, "u1", pf, now))
    assert b["users"]["u1"]["estado"] == "entrou"


def test_hub_marca_a_analise_cedo():
    from app.hub import PumpHub
    now = time.time()
    bm = BoostMig(Svc({}), clock=lambda: now)
    b = pronto(bm, M, now - 30, now, buys_m5=90, samples=_obs(now, 12))
    eng = types.SimpleNamespace(role="admin", cfg=types.SimpleNamespace(pump_bm_on=True))
    hub = types.SimpleNamespace(bm=bm, system_keys={"alchemy_api_key": "k" * 20}, engines={"u1": eng})
    PumpHub._sybil_early(hub, now)
    assert b["sybil_want"] == now and b["sybil_cedo"] and b["sybil_dl"] == now + 10
