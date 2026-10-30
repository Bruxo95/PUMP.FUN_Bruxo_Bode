"""0.32.87: Jev Trade. O Jev decide entrada, stop, parcial e saída, só em simulação. Sem internet."""
import asyncio
import json

import httpx

from app import jevtrade
from app.jevtrade import JevTrade

M = "Jvtr".ljust(40, "1") + "pump"
KEY = "jev-" + "k" * 30
T0 = 1_000_000.0


def _live(age_min=5.5, mc=60.0, m0=30.0):
    return {M: {"mint": M, "symbol": "JVT", "creator": "C", "t0": T0 - age_min * 60, "mcap0": m0, "snaps": {"5": mc}, "dev_buy": 0.5}}


def _open(px=1.0, stop="perda_30"):
    j = JevTrade()
    r = _live()[M]
    it = j.on_checked(r, 45, T0)
    j.add_read(it, 45, px, 60.0, T0)
    assert j.on_entry(it, {"acao": "entrar", "stop": stop}, px, T0) == "entrar"
    return j, it


def test_only_live_tokens_after_5_min_and_40_holders_are_watched():
    j = JevTrade()
    assert j.candidates(_live(age_min=4), {}, T0) == []
    assert j.candidates(_live(age_min=9), {}, T0) == []
    assert j.candidates(_live(mc=350.0), {}, T0) == []                 # bundle
    assert j.candidates(_live(), {"C": {}}, T0) == []                  # criador na lista negra
    L = _live(mc=30.5)
    assert j.candidates(L, {}, T0) == [] and j.day(T0)["parados"] == 1 # não negociou: não gasta leitura
    assert j.candidates(L, {}, T0) == [] and j.day(T0)["parados"] == 1
    c = j.candidates(_live(), {}, T0)
    assert len(c) == 1
    assert j.on_checked(c[0], 39, T0) is None and M not in j.items and j.day(T0)["abaixo"] == 1
    assert j.on_checked(dict(c[0]), 40, T0)["estado"] == "olhando"
    assert j.candidates(_live(), {}, T0) == []                         # um token, uma conferência


def test_rpc_without_holder_count_pauses_the_scan():
    j = JevTrade()
    assert j.on_checked(_live()[M], None, T0) is None
    assert j.can_scan(T0) is False and j.can_scan(T0 + 301) is True


def test_budgets_limit_scan_and_jev():
    j = JevTrade()
    for _ in range(jevtrade.SCAN_HOUR):
        assert j.can_scan(T0)
        j.note_scan(T0)
    assert not j.can_scan(T0) and j.can_scan(T0 + 3600)
    j.day(T0)["leituras"] = int(jevtrade.READS_DAY * jevtrade.SCAN_SHARE)
    assert not j.can_scan(T0 + 3600)
    j.day(T0)["calls"] = jevtrade.JEV_DAY
    assert j.jev_left(T0) == 0


def test_jev_chooses_entry_and_stop_and_gives_up():
    j, it = _open(stop="perda_20")
    assert it["estado"] == "aberta" and it["stop"] == -20 and it["entrada"]["px"] == 1.0
    j2 = JevTrade()
    x = j2.on_checked(_live()[M], 50, T0)
    assert j2.on_entry(x, {"acao": "esperar"}, 1.0, T0) == "esperar" and x["estado"] == "olhando"
    assert j2.on_entry(x, {"acao": "desistir"}, 1.0, T0) == "desistir" and x["estado"] == "descartada"
    j3 = JevTrade()
    y = j3.on_checked(_live()[M], 50, T0)
    j3.on_entry(y, {"acao": "entrar", "stop": "outra"}, 1.0, T0)
    assert y["stop"] == -30                                            # resposta fora da lista = stop padrão


def test_partial_sales_sum_up_with_fees():
    j, it = _open()
    j.on_exit(it, {"acao": "vender_50", "stop": "manter"}, 2.0, T0 + 60)    # metade a +100%
    assert it["left"] == 0.5 and it["estado"] == "aberta"
    j.on_exit(it, {"acao": "vender_tudo", "stop": "manter"}, 1.5, T0 + 120) # resto a +50%
    assert it["estado"] == "fechada" and it["res"] == 75 - jevtrade.FEE_PCT


def test_stop_only_goes_up_and_never_above_the_price():
    j, it = _open(stop="perda_40")
    j.on_exit(it, {"acao": "segurar", "stop": "lucro_50"}, 1.3, T0 + 60)    # acima do preço: ignora
    assert it["stop"] == -40
    j.on_exit(it, {"acao": "segurar", "stop": "lucro_20"}, 1.3, T0 + 120)
    assert it["stop"] == 20
    j.on_exit(it, {"acao": "segurar", "stop": "empate"}, 1.3, T0 + 180)     # não baixa
    assert it["stop"] == 20
    j.on_price(it, 1.1, T0 + 200)
    assert it["estado"] == "fechada" and "stop" in it["motivo"]
    assert round(it["res"], 2) == round(10 - jevtrade.FEE_PCT, 2)           # sai no preço visto, não no limite


def test_holders_fall_and_time_limit_close_without_the_jev():
    j, it = _open()
    j.add_read(it, 100, 1.2, 70.0, T0 + 60)
    assert not j.holders_fell(it)
    j.add_read(it, 71, 1.2, 70.0, T0 + 120)
    assert not j.holders_fell(it)
    j.add_read(it, 70, 1.2, 70.0, T0 + 180)
    assert j.holders_fell(it)
    j2, it2 = _open()
    j2.on_price(it2, 1.1, T0 + jevtrade.MAX_HOLD_MIN * 60)
    assert it2["estado"] == "fechada" and "tempo" in it2["motivo"]
    j3 = JevTrade()
    w = j3.on_checked(_live()[M], 50, T0)
    j3.on_price(w, 1.0, T0 + jevtrade.WATCH_MAX_MIN * 60)
    assert w["estado"] == "descartada"


def test_fixed_rule_keeps_running_after_the_jev_left_and_study_compares():
    j, it = _open()
    j.on_exit(it, {"acao": "vender_tudo", "stop": "manter"}, 1.2, T0 + 60)
    assert it["base_igual"]["res"] is None and it in j.active()
    j.on_price(it, 1.5, T0 + jevtrade.BASE_EXIT_MIN * 60)
    assert it["base_igual"]["res"] == 50 - jevtrade.FEE_PCT and it not in j.active()
    E = j.study(0, T0 + 3600)
    assert E["fechadas"] == 1 and E["media_pct"] == 20 - jevtrade.FEE_PCT and E["igual"]["media_pct"] == 46
    assert E["acerto"] == 100 and len(E["curva"]["jev"]) == 1 and "poucos dados" in E["leitura"]


def test_suspect_price_stays_out_of_the_totals():
    j, it = _open()
    j.on_price(it, 30.0, T0 + 60)
    j.on_exit(it, {"acao": "vender_tudo"}, 30.0, T0 + 120)
    E = j.study(0, T0 + 200)
    assert it["suspeito"] and E["fechadas"] == 0 and E["suspeitos"] == 1


def test_load_keeps_open_positions_after_restart():
    j, it = _open()
    k = JevTrade()
    k.load([{"id": M, "data": json.loads(json.dumps(it))}], T0)
    assert k.open()[0]["mint"] == M and k.day(T0)["leituras"] == 1


def _hub(handler):
    from app.hub import PumpHub

    class E:
        role = "admin"
        user_id = "u1"

        class cfg:
            pump_jt_on = True

    class Mk:
        tokens = {M: {"price": 1.0, "mcap_sol": 60.0}}
        blacklist = {}
        creator_stats = {}

    class Lab:
        live = _live()

    class Db:
        rows = []

        async def insert(self, t, row, **kw):
            self.rows.append((t, row["id"] if t == "jev_trades" else None))

    h = PumpHub.__new__(PumpHub)
    h.system_keys = {"jev_api_key": KEY}
    h.engines = {"u1": E()}
    h.jt, h.market, h.lab, h.db = JevTrade(), Mk(), Lab(), Db()
    h.monitor = None
    h.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    h.__dict__["_jev_usage_t"] = {"trade": 9e12}
    return h


def _answer(acao, stop):
    return {"answers": {"acao": {"choice": acao, "confidence": 0.8}, "stop": {"choice": stop}, "qualidade": {"score": 3}, "armadilha": {"noul": 0.1}},
            "usage": {"input_tokens": 100}}


def test_tick_watches_enters_and_sells_only_in_simulation():
    hosts = []
    seq = [("entrar", "perda_20"), ("vender_tudo", "manter")]

    def h(req):
        hosts.append(req.url.host)
        return httpx.Response(200, json=_answer(*seq.pop(0)))
    hub = _hub(h)

    async def count(mint):
        return 50
    hub.holders_count = count
    t = __import__("time").time()
    hub.lab.live = {M: {**_live()[M], "t0": t - 330}}
    asyncio.run(hub.jt_tick(t))
    it = hub.jt.items[M]
    assert it["estado"] == "aberta" and it["stop"] == -20 and it["decisoes"][0]["acao"] == "entrar"
    hub.market.tokens[M]["price"] = 2.0
    asyncio.run(hub.jt_tick(t + 60))
    assert it["estado"] == "fechada" and it["res"] == 100 - jevtrade.FEE_PCT
    assert hosts == ["api.typesafe.ai"] * 2                            # só o Jev: nada de compra, swap ou RPC de transação
    assert ("jev_trades", M) in hub.db.rows
    st = hub.jt_state(hub.engines["u1"], 24)
    assert st["ativo"] and st["fechadas"][0]["res"] == 96 and st["hoje"]["calls"] == 2


def test_no_key_means_no_jev_and_no_reads_but_open_position_still_stops():
    hub = _hub(lambda req: httpx.Response(500))
    hub.system_keys = {}
    t = __import__("time").time()
    hub.lab.live = {M: {**_live()[M], "t0": t - 330}}

    async def boom(mint):
        raise AssertionError("não deveria contar detentores")
    hub.holders_count = boom
    asyncio.run(hub.jt_tick(t))
    assert hub.jt.items == {}
    r = _live()[M]
    r["t0"] = t
    it = hub.jt.on_checked(r, 50, t)
    hub.jt.add_read(it, 50, 1.0, 60.0, t)
    hub.jt.on_entry(it, {"acao": "entrar", "stop": "perda_30"}, 1.0, t)
    hub.market.tokens[M]["price"] = 0.5
    asyncio.run(hub.jt_tick(t + 20))
    assert it["estado"] == "fechada" and it["res"] == -50 - jevtrade.FEE_PCT


def test_key_never_appears_in_error():
    def h(req):
        return httpx.Response(401, text="bad " + KEY)
    hub = _hub(h)
    out = asyncio.run(hub._jt_jev({}, jevtrade.Q_IN, T0))
    assert out is None and KEY not in hub.jt.stats["ultimo_erro"] and hub.jt.stats["erros"] == 1
