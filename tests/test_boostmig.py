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


def test_regras_do_dev_editaveis_como_no_original():
    """0.32.375 (pedido do dono: "as regras do BOOST não têm as mesmas opções"): % do full dump, minutos, cópias, dias do scam e
    do VIP vêm da tela; o livro do VIP esquece resultados mais velhos que os dias escolhidos."""
    from app.settings import USER_KEYS
    for k, v in (("pump_bm_scam_dump_pct", 70.0), ("pump_bm_scam_dump_min", 10.0), ("pump_bm_twin_min", 10.0),
                 ("pump_bm_scam_keep_d", 7.0), ("pump_bm_vip_keep_d", 30.0), ("pump_bm_fast", True)):
        assert USER_KEYS[k][1] == v
    try:
        got = bmod.apply_cfg({"pump_bm_scam_dump_pct": 50, "pump_bm_scam_dump_min": 5, "pump_bm_vip_keep_d": 1})
        assert got["pump_bm_scam_dump_pct"] == 50 and bmod.SCAM_DUMP_MIN == 300 / 60 and bmod.VIP_KEEP_S == 86400
        now = 3_000_000.0
        bm = BoostMig(Svc({}), clock=lambda: now)
        velho = pronto(bm, M2, now - 3600, now)
        velho["track"] = {"n": 5, "dump_pct": -55.0, "dump_s": 200, "top_pct": 30}       # −55% em 3 min: com 50% já é scam
        bm.dev_book["D9"] = {"mints": {"a": {"pnl_sol": 0.01, "t": now - 2 * 86400}, "b": {"pnl_sol": 0.02, "t": now - 60}}}
        bm.scam_mark(now)
        assert DEV in bm.scam_devs and list(bm.dev_book["D9"]["mints"]) == ["b"]
    finally:
        bmod.apply_cfg({"pump_bm_scam_dump_pct": 70, "pump_bm_scam_dump_min": 10, "pump_bm_twin_min": 10, "pump_bm_scam_keep_d": 7,
                        "pump_bm_vip_keep_d": 30})
    mon = open(os.path.join("app", "monitor.py"), encoding="utf-8").read()
    assert 'p.get("origem") == "boostmig" and getattr(e.cfg, "pump_bm_fast", True)' in mon
    html = open(os.path.join("web", "app.html"), encoding="utf-8").read()
    for k in ("pump_bm_scam_dump_pct", "pump_bm_scam_dump_min", "pump_bm_twin_min", "pump_bm_scam_keep_d", "pump_bm_vip_keep_d", "pump_bm_fast"):
        assert 'data-cfg="' + k + '"' in html or 'data-toggle="' + k + '"' in html


def test_observacao_cota_compra_na_jupiter_e_ignora_preco_da_curva():
    """0.32.376 (prints do dono, 19/11: o antigo mostrava DEV e trava; o nosso não): a observação cota uma compra de 0,01 SOL na
    Jupiter a cada volta (antes usava o preço guardado, que vinha da curva congelada); RPC sem resposta não gasta tentativa."""
    now = 5_000_000.0

    class Jup:
        async def _quote(self, inp, out, amount, dexes, direct=True):
            assert inp == bmod.SOL_MINT and amount == bmod.QUOTE_LAMPORTS
            return {"outAmount": str(20_000 * 10 ** 6)}                 # 0,01 SOL → 20.000 tokens = 5e-7 SOL cada

    class S(Svc):
        market = types.SimpleNamespace(jup=Jup())

        async def token_decimals(self, m):
            return 6

        async def _rpc_multi(self, keys, enc, pf=False):
            return None

        @staticmethod
        def curve_pda(m):
            return "PDA" + m[:4]

    tk = {M: {"price": 4e-7, "last_t": now}}                             # preço congelado da curva
    bm = BoostMig(S(tk), clock=lambda: now)
    b = bm.on_migration({"mint": M, "txType": "migrate"}, now - 10)
    run(bm._samples(now))
    assert b["samples"] == [[round(now, 1), 5e-7]]
    run(bm._creators(now))
    run(bm._safety(now))
    assert b.get("creator_tries", 0) == 0 and b.get("safety_tries", 0) == 0 and bm.st["rpc_falhou"] == 2
    assert bmod.finite({"a": float("inf"), "b": [float("nan"), 1.5]}) == {"a": None, "b": [None, 1.5]}


def test_detalhes_do_dev(env):
    """0.32.377 (pedido do dono): página de cada DEV com situação, resultado por token, motivo do scam e tokens dele em 24 h."""
    now = time.time()
    bm = BoostMig(Svc({}), clock=lambda: now)
    b = pronto(bm, M, now - 120, now)
    b["track"] = {"n": 9, "top_pct": 40.0, "top_s": 60, "dump_pct": -80.0, "dump_s": 200}
    bm.scam_mark(now)
    bm.dev_book[DEV] = {"mints": {M2: {"symbol": "OLD", "pnl_sol": 0.01, "pnl_pct": 20.0, "real": False, "t": now - 50}}}
    fake = types.SimpleNamespace(bm=bm)
    d = PumpHub.bm_dev(fake, DEV)
    assert d["scam"] and "full dump" in d["scam_info"]["why"] and d["tokens_24h"][0]["symbol"] == "GTAVI"
    assert d["tokens_24h"][0]["scam_por"] and d["resultados"][0]["symbol"] == "OLD" and d["stats"]["wins"] == 1
    c = env["c"]
    assert c.get("/api/pump/boost-migracao/dev/" + DEV).status_code == 401


def test_historico_aos_20_min_guarda_tudo_e_calcula_as_metricas():
    """0.32.378 (pedido do dono): todo token que migrou (entrando ou não) é analisado 20 min depois e guardado em boost_history;
    as métricas dizem quando sobe, quando despeja e o resultado de entrar no minuto X e sair no Y."""
    now = 6_000_000.0
    bm = BoostMig(Svc({}), clock=lambda: now)
    b = pronto(bm, M, now - 21 * 60, now)
    for sec, px in ((15, 1.0), (60, 1.2), (120, 1.5), (180, 2.0), (300, 1.8), (600, 0.5), (900, 0.4), (1200, 0.45)):
        bmod.track_point(b, px, b["t0"] + sec)
    b["users"] = {"u1": {"estado": "fora", "motivo": "nome repetido"}}
    assert bm.due_history(now) == [M]
    r = bmod.history_row(b, now)
    assert r["top_pct"] == 100.0 and r["top_s"] == 180 and r["dump_pct"] == -80.0 and r["dump_s"] == 900
    assert r["marks"]["1"] == 20.0 and r["marks"]["3"] == 100.0 and r["marks"]["20"] == -55.0 and r["classe"] == "despejou"
    assert r["fora_motivo"] == "nome repetido" and r["entrou"] == 0 and len(r["serie"]) == 8
    out = bmod.hist_study([r, {**r, "mint": "x", "classe": "subiu", "fim_pct": 30.0, "marks": {"1": 5.0, "3": 10.0, "5": 30.0}, "scam": True}])
    assert out["n"] == 2 and out["classes"] == {"despejou": 1, "subiu": 1}
    um_tres = out["entra_sai"][0]["sai"]["3"]                                     # entra 1 min, sai 3 min
    assert um_tres["n"] == 2 and um_tres["media"] == round(((2.0 / 1.2 - 1) * 100 - 1.5 + (1.10 / 1.05 - 1) * 100 - 1.5) / 2, 1)
    assert any(g["grupo"] == "DEV scam" and g["n"] == 1 for g in out["grupos"])
    assert [c["min"] for c in out["curva"]][:3] == [1, 2, 3]

    class DB:
        rows = []

        async def insert(self, t, rows, upsert=False, on_conflict=None):
            assert t == "boost_history" and on_conflict == "mint"
            DB.rows += rows

    fake = types.SimpleNamespace(bm=bm, db=DB())
    run(PumpHub._bm_hist(fake, now))
    assert len(DB.rows) == 1 and DB.rows[0]["classe"] == "despejou" and DB.rows[0]["dados"]["serie"]
    assert bm.items[M]["hist_t"] == now and bm.due_history(now) == []
    sql = open(os.path.join("supabase", "migrations", "20261119000001_boost_historico.sql"), encoding="utf-8").read()
    assert "create table if not exists public.boost_history" in sql and "enable row level security" in sql and "delete" not in sql.lower()
