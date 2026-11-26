"""0.32.471 (pedido do dono, 26/11/2026): no BOOST, mudar o valor depois de 3, 4 ou 5 compras (ou misturando por sorteio).
Começa desligado; só conta compra que entrou de verdade. Sem internet e com carteira falsa."""
import random
import time
import types

from app import bmstep
from app.boostmig import BoostMig
from app.hub import PumpHub
from app.settings import BM_REAL_RULES, USER_KEYS
from tests.test_boostmig import Svc, cfg, pronto, run
from tests.test_espelho_real import _pf

MINTS = [f"Rod{i}".ljust(40, "1") + "pump" for i in range(1, 10)]


def regra(**kw):
    base = {"pump_bm_sol": 0.25, "pump_bm_step_on": True, "pump_bm_step_mode": 3, "pump_bm_step_mix3": True,
            "pump_bm_step_mix4": True, "pump_bm_step_mix5": True, "pump_bm_step_pct3": 100, "pump_bm_step_pct4": 50,
            "pump_bm_step_pct5": 25}
    base.update(kw)
    return types.SimpleNamespace(**base)


def anda(st, c, vezes, rnd=random):
    out = []
    for _ in range(vezes):
        amt, t = bmstep.peek(st, c)
        bmstep.take(st, c, t, rnd)
        out.append(amt)
    return out


def test_comeca_desligado_e_nao_muda_o_valor():
    assert USER_KEYS["pump_bm_step_on"][1] is False and USER_KEYS["pump_bmr_step_on"][1] is False
    assert "step_on" in BM_REAL_RULES
    c = regra(pump_bm_step_on=False)
    assert bmstep.sync(None, c) is None
    assert bmstep.peek(None, c) == (0.25, None)


def test_depois_de_3_o_quarto_muda_e_recomeca():
    c = regra()
    st = bmstep.sync(None, c)
    assert anda(st, c, 9) == [0.25, 0.25, 0.25, 0.5, 0.25, 0.25, 0.25, 0.5, 0.25]
    assert bmstep.view(st, c) == {"feitos": 1, "alvo": 3, "especial": False, "prox_sol": 0.25, "sol_especial": 0.5,
                                  "pct_especial": 100}


def test_misturar_sorteia_so_os_marcados():
    c = regra(pump_bm_step_mode=0, pump_bm_step_mix4=False)
    rnd = random.Random(7)
    st = bmstep.sync(None, c, rnd)
    seq = anda(st, c, 200, rnd)
    rodadas, n = [], 0
    for v in seq:
        if v == 0.25:
            n += 1
        else:
            rodadas.append((n, v))
            n = 0
    assert set(rodadas) == {(3, 0.5), (5, 0.3125)}


def test_porcentagem_e_acima_do_valor_por_entrada():
    for pct, sol in ((10, 0.275), (25, 0.3125), (50, 0.375), (75, 0.4375), (100, 0.5)):
        c = regra(pump_bm_step_pct3=pct)
        assert anda(bmstep.sync(None, c), c, 4) == [0.25, 0.25, 0.25, sol]
    c = regra(pump_bm_sol=0.1, pump_bm_step_pct3=50)               # mudou o valor por entrada: a % acompanha
    assert anda(bmstep.sync(None, c), c, 4)[-1] == 0.15
    assert USER_KEYS["pump_bm_step_pct3"][1] == 10 and USER_KEYS["pump_bm_step_pct3"][3] == 100


def test_desligado_a_compra_do_boost_fica_como_era(tmp_path):
    """Pedido do dono: o extra não pode mexer no BOOST que já existe."""
    pf, now = _conta(tmp_path, pump_bm_real=True, pump_bm_step_on=False)
    for m in MINTS[:5]:
        _entra(pf, m, now)
    itens = [pf._rq.get_nowait()[1] for _ in range(5)]
    for it in itens:
        assert it["amt_sol"] == 0.05 and "bm_step" not in it["pos_cfg"]
    assert pf.bm_step == {} and pf.bm_step_dirty is False


def test_compra_que_falha_nao_conta():
    c = regra()
    st = bmstep.sync(None, c)
    anda(st, c, 3)
    amt, t = bmstep.peek(st, c)                        # a de valor diferente é enviada…
    bmstep.take(st, c, t)
    assert amt == 0.5 and bmstep.giveback(st, t)       # …e falha: volta a ser a próxima
    assert anda(st, c, 5) == [0.5, 0.25, 0.25, 0.25, 0.5]
    _amt, t = bmstep.peek(st, c)                       # normal enviada que falha não entra na conta
    bmstep.take(st, c, t)
    bmstep.giveback(st, t)
    assert anda(st, c, 4) == [0.25, 0.25, 0.25, 0.5]


def test_trocar_quando_mudar_recomeca_e_trocar_so_o_valor_nao():
    c = regra()
    st = bmstep.sync(None, c)
    anda(st, c, 2)
    c.pump_bm_step_pct3 = 75
    assert bmstep.sync(st, c) is st
    c.pump_bm_step_mode = 5
    novo = bmstep.sync(st, c)
    assert novo is not st and novo["n"] == 0 and novo["alvo"] == 5


def _conta(tmp_path, **kw):
    pf = _pf(tmp_path)
    pf.role = "admin"
    now = time.time()
    base = vars(cfg(pump_bm_on=True, pump_bm_sol=0.05, pump_bm_ext_on=False, pump_bm_sg_after=False, pump_bm_max_open=20,
                    pump_real_mirror=False, pump_auto_real=False, pump_bm_block_repeat=False))
    base.update(vars(regra(pump_bm_sol=0.05)))
    base.update(kw)
    for k, v in base.items():
        setattr(pf.cfg, k, v)
    pf.bm_step_sync()
    return pf, now


def _entra(pf, mint, now):
    pf.tokens[mint] = {"price": 1e-6, "last_t": now, "symbol": mint[:4], "pool": "pumpswap"}
    bm = BoostMig(Svc(pf.tokens), clock=lambda: now)
    b = pronto(bm, mint, now - 60, now, symbol=mint[:4], name=mint[:4])
    run(PumpHub._bm_user(types.SimpleNamespace(bm=bm), "u1", pf, now))
    return b


def test_na_ficticia_o_quarto_trade_usa_o_outro_valor(tmp_path):
    pf, now = _conta(tmp_path, pump_bm_real=False)
    for m in MINTS[:5]:
        _entra(pf, m, now)
    pos = {p["mint"]: p for p in pf.positions() if p.get("origem") == "boostmig"}
    assert [round(pos[m]["bm_step"]["sol"], 3) for m in MINTS[:5]] == [0.05, 0.05, 0.05, 0.1, 0.05]
    assert "+100% (depois de 3): 0.1 SOL" in pos[MINTS[3]]["auto"]
    assert pf.bm_step_view()["sim"]["feitos"] == 1


def test_token_descartado_nao_conta(tmp_path):
    pf, now = _conta(tmp_path, pump_bm_real=False, pump_bm_min_buys=5000)
    _entra(pf, MINTS[0], now)
    assert pf.bm_step_view()["sim"]["feitos"] == 0


def test_real_que_falha_nao_conta(tmp_path):
    pf, now = _conta(tmp_path, pump_bm_real=True)
    _entra(pf, MINTS[0], now)
    assert pf.bm_step_view()["sim"]["feitos"] == 1            # enviada: reservada
    it = pf._rq.get_nowait()[1]

    class Falha:
        async def buy(self, mint, amt, other=False):
            return {"ok": False, "reason": "teste"}

        def today_loss(self, trades):
            return 0.0
    pf.real = Falha()
    run(pf._real_buy_run(it))
    assert pf.bm_step_view()["sim"]["feitos"] == 0            # a fictícia entrou, mas a contagem segue a REAL


def test_real_com_regras_proprias_conta_separado(tmp_path):
    pf, now = _conta(tmp_path, pump_bm_real=True, pump_bmr_on=True)
    for k in BM_REAL_RULES:
        if hasattr(pf.cfg, "pump_bm_" + k):
            setattr(pf.cfg, "pump_bmr_" + k, getattr(pf.cfg, "pump_bm_" + k))
    pf.cfg.pump_bmr_step_on = False                           # a REAL com o rodízio desligado
    pf.cfg.pump_bmr_sol = 0.02
    pf.bm_step_sync()
    _entra(pf, MINTS[0], now)
    it = pf._rq.get_nowait()[1]
    assert it["amt_sol"] == 0.02 and "bm_step" not in it["pos_cfg"]
    assert set(pf.bm_step_view()) == {"sim"}
