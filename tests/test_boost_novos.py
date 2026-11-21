"""0.32.432 (pedido do dono, 21/11, caso Prayge): tokens NOVOS (ainda na curva) com volume entram na lista e na análise do
BOOST antes de migrar. Tudo sem internet e com carteira falsa."""
import asyncio
import time
import types

from app.boostmig import BoostMig
from app.hub import PumpHub
from tests.test_boostmig import DEV, cfg
from tests.test_espelho_real import _pf

M = "Nov1".ljust(40, "1") + "pump"


def run(c):
    return asyncio.new_event_loop().run_until_complete(c)


class Svc:
    """DexScreener falsa: devolve o volume de 5 min (US$) que o teste mandar."""

    def __init__(self, tokens, vol=None):
        self.tokens, self.vol, self.calls = tokens, vol or {}, 0

    async def _fetch_prices(self, mints, set_price=True):
        self.calls += 1
        for m in mints:
            if m in self.vol:
                self.tokens.setdefault(m, {})["vol"] = {"m5": self.vol[m], "buys_m5": 120, "sells_m5": 30}
                self.tokens[m]["vol_t"] = time.time()


def novo(bm, now, age=40, vol=3000.0):
    bm.novo_cfg = {"on": True, "vol": 2000.0, "age_s": 120.0}
    bm.on_create({"mint": M, "txType": "create", "symbol": "PRAY", "name": "Prayge", "traderPublicKey": DEV}, now - age)
    run(bm._novos(now))
    b = bm.items[M]
    b.update(safety_ok=True, buys_m5=120, sells_m5=30,
             samples=[[now - 30, 1.0], [now - 25, 1.01], [now - 20, 1.02], [now - 5, 1.03], [now - 3, 1.04], [now, 1.05]])
    return b


def test_token_novo_so_entra_na_lista_com_volume_e_dentro_da_idade():
    now = time.time()
    svc = Svc({}, {M: 900.0})
    bm = BoostMig(svc, clock=lambda: now)
    bm.novo_cfg = {"on": True, "vol": 2000.0, "age_s": 120.0}
    bm.on_create({"mint": M, "txType": "create", "symbol": "PRAY"}, now - 30)
    run(bm._novos(now))
    assert M not in bm.items and M in bm.cands                       # volume baixo: só candidato
    svc.vol[M] = 2500.0
    run(bm._novos(now + 1))                                          # consulta a cada 8 s: ainda não
    assert M not in bm.items
    run(bm._novos(now + 9))
    b = bm.items[M]
    assert b["kind"] == "novo" and b["t0"] == now - 30 and b["vol_m5"] == 2500.0
    assert svc.tokens[M]["bm_curva"] is True
    bm2 = BoostMig(Svc({}, {M: 9000.0}), clock=lambda: now)
    bm2.novo_cfg = {"on": True, "vol": 2000.0, "age_s": 120.0}
    bm2.on_create({"mint": M, "txType": "create"}, now - 200)        # passou da idade: nem consulta
    run(bm2._novos(now))
    assert M not in bm2.items and not bm2.cands
    bm3 = BoostMig(Svc({}), clock=lambda: now)                        # ninguém ligou: não guarda nada
    bm3.on_create({"mint": M, "txType": "create"}, now)
    assert not bm3.cands


def test_decisao_usa_idade_e_volume_do_usuario():
    now = time.time()
    bm = BoostMig(Svc({}, {M: 3000.0}), clock=lambda: now)
    b = novo(bm, now)
    st, why = bm.decide(cfg(), b, now, set(), 0)
    assert st == "entrar" and "token novo" in why and "40 s de vida" in why
    assert bm.decide(cfg(pump_bm_new_vol_usd=5000), b, now, set(), 0)[0] == "esperar"
    assert bm.decide(cfg(pump_bm_new_age_max_min=0.5), b, now, set(), 0) == ("fora", "passou de 0.5 min de vida sem confirmar")
    assert bm.decide(cfg(pump_bm_new_on=False), b, now, set(), 0)[0] == "fora"
    assert bm.decide(cfg(pump_bm_enter_max_pct=1), b, now, set(), 0)[0] == "entrar"    # "% do BOOST" não vale para token novo


def test_compra_na_curva_e_vira_boost_quando_migra(tmp_path):
    pf = _pf(tmp_path)
    pf.role = "admin"
    now = time.time()
    pf.tokens[M] = {"price": 1e-6, "last_t": now, "symbol": "PRAY", "name": "Prayge"}
    for k, v in vars(cfg(pump_bm_on=True, pump_bm_sol=0.05, pump_bm_ext_on=False, pump_bm_sg_after=False)).items():
        setattr(pf.cfg, k, v)
    bm = BoostMig(Svc(pf.tokens, {M: 3000.0}), clock=lambda: now)
    b = novo(bm, now)
    run(PumpHub._bm_user(types.SimpleNamespace(bm=bm), "u1", pf, now))
    assert b["users"]["u1"]["estado"] == "entrou" and "token novo" in b["users"]["u1"]["motivo"]
    p = [p for p in pf.positions() if p["mint"] == M][0]
    assert p["origem"] == "boostmig" and "token novo (curva)" in str(p.get("auto") or p.get("entrou_porque") or "")
    assert pf.tokens[M].get("pool") != "pumpswap" and pf.tokens[M]["bm_curva"] is True   # compra na curva, não na PumpSwap
    b["users"]["u2"] = {"estado": "fora", "motivo": "passou de 2 min de vida sem confirmar"}
    b2 = bm.on_migration({"mint": M, "txType": "migrate", "pool": "pump-amm"}, now + 100)
    assert b2 is b and b["kind"] == "mig" and b["t0"] == now + 100 and b["novo_info"]["t0"] == now - 40
    assert b["users"]["u1"]["estado"] == "entrou" and "u2" not in b["users"]            # quem foi descartado volta a ser analisado
    assert pf.tokens[M]["pool"] == "pumpswap" and "bm_curva" not in pf.tokens[M]
    assert bm.on_migration({"mint": M, "txType": "migrate"}, now + 101) is None          # BOOST normal não duplica


def test_hub_junta_o_que_vale_dos_admins():
    a = types.SimpleNamespace(role="admin", cfg=types.SimpleNamespace(pump_bm_on=True, pump_bm_new_on=True, pump_bm_new_vol_usd=3000,
                                                                       pump_bm_new_age_max_min=2, pump_bm_real=False))
    b = types.SimpleNamespace(role="admin", cfg=types.SimpleNamespace(pump_bm_on=True, pump_bm_new_on=True, pump_bm_new_vol_usd=1500,
                                                                       pump_bm_new_age_max_min=3, pump_bm_real=False))
    u = types.SimpleNamespace(role="user", cfg=types.SimpleNamespace(pump_bm_on=True, pump_bm_new_on=True, pump_bm_new_vol_usd=10,
                                                                     pump_bm_new_age_max_min=10))
    assert PumpHub.bm_novo_cfg(types.SimpleNamespace(engines={"a": a, "b": b, "u": u})) == {"on": True, "vol": 1500.0, "age_s": 180.0}
    assert PumpHub.bm_novo_cfg(types.SimpleNamespace(engines={"u": u}))["on"] is False


def test_migracao_com_chave_e_idade_maxima_desde_a_criacao():
    """0.32.433 (caso PUMPANY: migrou com ~7 min de vida e o dono só quer até 2 min)."""
    from tests.test_boostmig import pronto
    now = time.time()
    bm = BoostMig(Svc({}), clock=lambda: now)
    bm.on_create({"mint": M, "txType": "create"}, now - 450)          # visto na PumpPortal: nasceu há 7,5 min
    b = pronto(bm, M, now - 35, now)
    b["born_t"] = bm.born[M]
    assert bm.decide(cfg(), b, now, set(), 0)[0] == "entrar"           # sem limite (padrão 0)
    assert bm.decide(cfg(pump_bm_mig_age_max_min=2), b, now, set(), 0) == ("fora", "token com 7.5 min de vida (máximo 2 min)")
    assert bm.decide(cfg(pump_bm_mig_age_max_min=10), b, now, set(), 0)[0] == "entrar"
    assert bm.decide(cfg(pump_bm_mig_on=False), b, now, set(), 0)[0] == "fora"
    b.pop("born_t")
    assert bm.decide(cfg(pump_bm_mig_age_max_min=2), b, now, set(), 0)[0] == "esperar"          # ainda lendo a idade
    assert bm.decide(cfg(pump_bm_mig_age_max_min=2), b, now + 30, set(), 0)[0] == "fora"        # sem idade: não entra


def test_nascimento_pela_dexscreener():
    import httpx
    from tests.test_espelho_real import _pf
    import tempfile
    pf = _pf(__import__("pathlib").Path(tempfile.mkdtemp()))
    js = [{"chainId": "solana", "dexId": "pumpswap", "pairAddress": "P2", "pairCreatedAt": 1795284500000, "baseToken": {"address": M, "symbol": "X"},
           "quoteToken": {"address": "So11111111111111111111111111111111111111112"}, "priceNative": "0.0000001", "liquidity": {"usd": 9000}},
          {"chainId": "solana", "dexId": "pumpfun", "pairAddress": "P1", "pairCreatedAt": 1795284100000, "baseToken": {"address": M, "symbol": "X"},
           "quoteToken": {"address": "So11111111111111111111111111111111111111112"}, "priceNative": "0.0000001", "liquidity": {"usd": 1}}]
    pf.http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=js)))
    run(pf._fetch_prices([M], set_price=False))
    assert pf.tokens[M]["born_t"] == 1795284100.0


def test_carteiras_so_antes_de_entrar_e_trava_com_alerta_alto(tmp_path):
    """0.32.434 (pedido do dono, economizar a Alchemy): a análise das carteiras só começa quando o token passou nos filtros; a compra
    espera o resultado (até 25 s) e, com a trava ligada, alerta ALTO não compra."""
    from app import boostmig
    from tests.test_boostmig import pronto
    pf = _pf(tmp_path)
    pf.role = "admin"
    now = time.time()
    pf.tokens[M] = {"price": 1e-6, "last_t": now, "symbol": "GTAVI", "name": "GTA VI", "pool": "pumpswap"}
    for k, v in vars(cfg(pump_bm_on=True, pump_bm_sol=0.05, pump_bm_ext_on=False, pump_bm_sg_after=False, pump_bm_sybil_block=True)).items():
        setattr(pf.cfg, k, v)
    bm = BoostMig(Svc(pf.tokens), clock=lambda: now)
    b = pronto(bm, M, now - 60, now)
    hub = types.SimpleNamespace(bm=bm, system_keys={"alchemy_api_key": "k" * 20})
    run(PumpHub._bm_user(hub, "u1", pf, now))
    u = b["users"]["u1"]
    assert u["estado"] == "esperar" and "conferindo as carteiras" in u["motivo"] and b["sybil_want"] == now
    assert not [p for p in pf.positions() if p["mint"] == M]
    b["sybil"] = {"nivel": "alto", "motivo": "bundle 40%"}
    run(PumpHub._bm_user(hub, "u1", pf, now + 1))
    assert u["estado"] == "fora" and "alerta ALTO" in u["motivo"]
    u.clear()
    b["sybil"] = {"nivel": "baixo"}
    run(PumpHub._bm_user(hub, "u1", pf, now + 2))
    assert u["estado"] == "entrou"
    assert boostmig.SYBIL_WAIT_S == 25.0
