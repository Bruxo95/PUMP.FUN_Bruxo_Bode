"""0.32.373 (pedido do dono, 18/11/2026): BOOST da migração, trazido do hermes-jev-trader e adaptado (vários usuários, Supabase,
carteira fictícia de cada um). Tudo sem internet e com carteira falsa: nenhuma transação de verdade."""
import asyncio
import os
import time
import types

from app import boostmig as bmod
from app.boostmig import BoostMig
from app.hub import PumpHub
from tests.test_espelho_real import _pf

M = "Bst1".ljust(40, "1") + "pump"
M2 = "Bst2".ljust(40, "1") + "pump"
DEV = "Dev1".ljust(44, "1")


def run(c):
    return asyncio.new_event_loop().run_until_complete(c)


class Svc:
    def __init__(self, tokens):
        self.tokens = tokens

    async def _pumpswap_prices(self, mints, *a, **k):
        return mints


def cfg(**kw):
    base = {"pump_bm_enter_max_pct": 40, "pump_bm_block_repeat": True, "pump_bm_block_scam": True, "pump_bm_vip_skip_repeat": True,
            "pump_bm_require_safety": True, "pump_bm_watch_s": 20, "pump_bm_min_trend_pct": -3, "pump_bm_max_dd_pct": 15,
            "pump_bm_min_buy_ratio": 1.2, "pump_bm_min_buys": 80, "pump_bm_max_top10": 35, "pump_bm_max_open": 3,
            "pump_bm_exit_pct": 90, "pump_bm_no_stop": True, "pump_bm_stop_pct": 40, "pump_bm_trail_start": 15, "pump_bm_trail_dist": 5,
            "pump_bm_partial_on": True, "pump_bm_partial_at": 20, "pump_bm_partial_frac": 50}
    base.update(kw)
    return types.SimpleNamespace(**base)


def pronto(bm, mint, t0, now, **kw):
    b = bm.on_migration({"mint": mint, "txType": "migrate", "pool": "pump-amm"}, t0)
    b.update(symbol="GTAVI", name="GTA VI", creator=DEV, safety_ok=True, buys_m5=120, sells_m5=40,
             samples=[[now - 30, 1.0], [now - 25, 1.01], [now - 20, 1.02], [now - 5, 1.03], [now - 3, 1.04], [now, 1.05]])
    b.update(kw)
    return b


def test_filtros_na_ordem_do_guia():
    now = 1_000_000.0
    bm = BoostMig(Svc({}), clock=lambda: now)
    b = pronto(bm, M, now - 60, now)                                   # 20% do BOOST
    assert bm.decide(cfg(), b, now, set(), 0)[0] == "entrar"
    assert bm.decide(cfg(pump_bm_enter_max_pct=10), b, now, set(), 0) == ("fora", "passou de 10% do BOOST sem confirmar")
    assert bm.decide(cfg(), b, now, {"gtavi"}, 0)[0] == "fora"         # já tem outro GTAVI aberto
    assert "limite de 3" in bm.decide(cfg(), b, now, set(), 3)[1]
    assert bm.decide(cfg(pump_bm_min_buys=200), b, now, set(), 0) == ("esperar", "aguardando compras: 120 de 200 nos últimos 5 min")
    b2 = pronto(bm, M2, now - 60, now, buys_m5=20, sells_m5=40)
    st, why = bm.decide(cfg(), b2, now, set(), 0)
    assert st == "fora" and "cópias" in why                            # mesmo nome migrando junto: DEV scam
    bm.items.pop(M2)
    b["samples"] = [[now - 30, 1.0], [now - 25, 1.0], [now - 20, 1.0], [now - 5, 0.9], [now - 3, 0.9], [now, 0.9]]
    assert "preço -10.0%" in bm.decide(cfg(), b, now, set(), 0)[1]
    b["samples"] = [[now - 5, 1.0]]
    assert bm.decide(cfg(), b, now, set(), 0) == ("esperar", "observando 5/20 s")
    b["safety_ok"], b["safety_why"] = False, "freeze authority ativa"
    assert bm.decide(cfg(), b, now, set(), 0)[0] == "fora"
    b.update(safety_ok=None, safety_tries=bmod.SAFETY_TRIES)
    assert bm.decide(cfg(), b, now, set(), 0) == ("fora", "não deu para conferir a trava de venda")


def test_nome_repetido_dev_scam_e_vip():
    now = 2_000_000.0
    bm = BoostMig(Svc({}), clock=lambda: now)
    velho = pronto(bm, M2, now - 3600, now)
    velho["track"] = {"n": 5, "dump_pct": -80.0, "dump_s": 240, "top_pct": 50}
    bm.scam_mark(now)
    assert DEV in bm.scam_devs and "full dump" in bm.scam_devs[DEV]["why"]
    b = pronto(bm, M, now - 30, now, symbol="OUTRO", name="Outro")
    st, why = bm.decide(cfg(), b, now, set(), 0)
    assert st == "fora" and "DEV scam" in why                          # mesmo DEV, outro nome: barrado
    assert bm.dev_action(DEV, "unscam") and DEV not in bm.scam_devs
    b.update(symbol="GTAVI", name="GTA VI", creator="Dev2".ljust(44, "1"))
    assert "nome repetido" in bm.decide(cfg(), b, now, set(), 0)[1]
    bm.dev_book["Dev2".ljust(44, "1")] = {"mints": {"x": {"pnl_sol": 0.02}}}
    assert bm.decide(cfg(), b, now, set(), 0)[0] == "entrar"           # DEV VIP pode repetir o nome


def test_trava_de_venda_e_dev_da_curva():
    ok = bmod.safety_of({"data": {"parsed": {"info": {"freezeAuthority": None, "mintAuthority": None, "extensions": []}}}})
    assert ok == {"ok": True, "why": None}
    bad = bmod.safety_of({"data": {"parsed": {"info": {"freezeAuthority": "X", "extensions": [
        {"extension": "transferFeeConfig", "state": {"newerTransferFee": {"transferFeeBasisPoints": 500}}}]}}}})
    assert bad["ok"] is False and "freeze" in bad["why"] and "5.0%" in bad["why"]
    assert bmod.safety_of(None)["ok"] is None
    from solders.pubkey import Pubkey
    pk = Pubkey.from_string(DEV)
    assert bmod.creator_of(b"\x00" * 49 + bytes(pk) + b"\x00" * 60) == DEV
    assert bmod.creator_of(b"\x00" * 200) is None


def test_topo_e_full_dump():
    b = {"t0": 0.0}
    for t, px in ((10, 1.0), (60, 2.0), (120, 0.5), (200, 0.6)):
        bmod.track_point(b, px, t)
    k = b["track"]
    assert k["top_pct"] == 100.0 and k["top_s"] == 60 and k["dump_pct"] == -75.0 and k["dump_s"] == 120 and k["dump_dur_s"] == 60


def test_entra_na_ficticia_com_as_regras_e_sai_no_boost(tmp_path):
    pf = _pf(tmp_path)                                    # execução real ligada (carteira falsa)
    pf.role = "admin"
    now = time.time()
    pf.tokens[M] = {"price": 1e-6, "last_t": now, "symbol": "GTAVI", "name": "GTA VI", "pool": "pumpswap"}
    for k, v in vars(cfg(pump_bm_on=True, pump_bm_sol=0.05)).items():
        setattr(pf.cfg, k, v)
    bm = BoostMig(Svc(pf.tokens), clock=lambda: now)
    b = pronto(bm, M, now - 60, now)
    fake = types.SimpleNamespace(bm=bm)
    run(PumpHub._bm_user(fake, "u1", pf, now))
    u = b["users"]["u1"]
    assert u["estado"] == "entrou", u
    p = [p for p in pf.positions() if p["mint"] == M]
    assert len(p) == 1 and p[0]["origem"] == "boostmig" and p[0]["real"] is False
    p = p[0]
    assert p["stop_pct"] == 0.0 and p["tp1_pct"] == 20 and p["trail_start"] == 15 and p["hold_why"] == "BOOST 90% (saída em 90%)"
    assert abs(p["max_hold_s"] - (bmod.JANELA_S * 0.9 - 60)) < 2
    assert pf._rq is None or pf._rq.qsize() == 0          # REAL do BOOST desligada: nada na fila real
    assert pf.aba_of(p) == "BOOST da migração"
    run(PumpHub._bm_user(fake, "u1", pf, now + 1))              # não compra de novo
    assert len([x for x in pf.positions() if x["mint"] == M]) == 1
    msgs = pf.check_timeouts(now + bmod.JANELA_S)
    assert any("BOOST 90%" in m for m in msgs) or not [x for x in pf.positions() if x["mint"] == M]
    tr = [t for t in pf.trades(50) if t.get("mint") == M][0]
    assert tr["reason"].startswith("BOOST 90%") and tr["origem"] == "boostmig"


def test_real_so_com_a_chave_da_aba(tmp_path):
    pf = _pf(tmp_path)
    pf.role = "admin"
    now = time.time()
    pf.tokens[M] = {"price": 1e-6, "last_t": now, "symbol": "GTAVI", "pool": "pumpswap"}
    for k, v in vars(cfg(pump_bm_on=True, pump_bm_sol=0.05, pump_bm_real=True)).items():
        setattr(pf.cfg, k, v)
    bm = BoostMig(Svc(pf.tokens), clock=lambda: now)
    pronto(bm, M, now - 60, now)
    run(PumpHub._bm_user(types.SimpleNamespace(bm=bm), "u1", pf, now))
    assert pf._rq is not None and pf._rq.qsize() == 1     # com a chave ligada e a execução real ligada: vai para a fila real


def test_migracao_e_rotas():
    sql = open(os.path.join("supabase", "migrations", "20261118000001_boost_migracao.sql"), encoding="utf-8").read()
    assert "boost_tokens" in sql and "boost_devs" in sql and sql.count("enable row level security") == 2
    mon = open(os.path.join("app", "monitor.py"), encoding="utf-8").read()
    assert '"subscribeMigration"' in mon and "bm_on_migration" in mon
    from app.settings import USER_KEYS
    assert USER_KEYS["pump_bm_on"][1] is False and USER_KEYS["pump_bm_real"][1] is False   # começa desligado


def test_rota_exige_admin(env):
    c = env["c"]
    assert c.get("/api/pump/boost-migracao").status_code == 401
    assert c.post("/api/pump/boost-migracao/dev", json={}).status_code == 401


from tests.test_api import env  # noqa: E402,F401
