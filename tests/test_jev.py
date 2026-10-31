"""0.32.83: Jev (TypeSafe AI) em modo sombra na Aba do Bruxo — pergunta, guarda a decisão no sinal e a aba JEV compara
com o que o token fez. Nunca compra. Sem internet."""
import asyncio
import json

import httpx

from app import jev
from app.bruxo import Bruxo

M = "Jevx".ljust(40, "1") + "pump"
W = "Top1".ljust(44, "1")
KEY = "jev-" + "k" * 30


def _resp(choice="entrar"):
    probs = {"entrar": 0.1, "esperar": 0.2, "evitar": 0.7}
    probs[choice] = 0.8
    return {"answers": {"acao": {"choice": choice, "confidence": 0.8, "probabilities": probs},
                        "qualidade": {"score": 3.2}, "armadilha": {"noul": 0.15}},
            "usage": {"input_tokens": 420, "output_tokens": 0}}


def test_ask_sends_state_and_questions_and_parses():
    seen = {}

    def h(req):
        seen["auth"] = req.headers["authorization"]
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json=_resp("entrar"))
    http = httpx.AsyncClient(transport=httpx.MockTransport(h))
    b = Bruxo()
    s, _ = b.on_buy(W, "Top1", M, "JEV", 1.2, 1e-6, {"mcap_sol": 40}, 2.0, {"flow": 3.0, "flow_base": 1.0}, 1000.0)
    out = asyncio.run(jev.ask(http, KEY, jev.state_for(s)))
    assert seen["auth"] == "Bearer " + KEY
    assert seen["body"]["model"] == "jev-1.14.0" and set(seen["body"]["questions"]) == {"acao", "qualidade", "armadilha"}
    assert seen["body"]["state"]["numbers"]["buy_pace_sol_per_min"] == 3.0
    assert KEY not in json.dumps(seen["body"])                     # a chave só vai no cabeçalho
    assert out["acao"] == "entrar" and out["p"]["entrar"] == 0.8 and out["qualidade"] == 3.2 and out["armadilha"] == 0.15


def test_error_never_shows_the_key():
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(401, text="bad key " + KEY)))
    try:
        asyncio.run(jev.ask(http, KEY, {}))
        raise AssertionError("devia falhar")
    except RuntimeError as e:
        assert "401" in str(e) and KEY not in str(e)


def test_study_compares_decisions_with_what_happened():
    sigs = []
    for i, (act, m10, regra) in enumerate([("entrar", 50, True), ("entrar", -10, False), ("evitar", -40, True), ("esperar", 5, False)]):
        s = {"id": str(i), "t": 1000 + i, "marks": {"10": m10}, "jev": {"acao": act, "p": {"entrar": 0.9 if act == "entrar" else 0.1}},
             "entrou_regra": regra, "stop30_s": 120 if m10 <= -30 else None, "hit100_s": None}
        sigs.append(s)
    st = jev.study(sigs, "10")
    assert st["n"] == 4
    assert st["por_acao"]["entrar"]["medidos"] == 2 and st["por_acao"]["entrar"]["acerto"] == 50
    # jev: (50-4)+(-10-4) = 32% de 0,1 SOL; regra: 46% + stop(-34%) = 12%
    assert abs(st["total"]["jev"] - 0.032) < 1e-6 and abs(st["total"]["regra"] - 0.012) < 1e-6
    assert len(st["curva"]["todos"]) == 4
    assert {b["faixa"] for b in st["calibracao"]} == {"80–100%", "0–20%"}


def test_version_is_fixed_and_saved_with_the_answer():
    assert jev.JEV_MODEL == "jev-1.14.0"
    r = jev.parse({"model": "jev-1.14.0", "answers": {"acao": {"choice": "entrar"}}, "usage": {}})
    assert r["modelo"] == "jev-1.14.0"
    assert jev.compact({"t": 1, "res": {}}, {"acao": "entrar", "modelo": "jev-1.14.0"})["jev"]["modelo"] == "jev-1.14.0"


def _hub(handler, admin_on=True):
    from app.hub import PumpHub

    class E:
        role = "admin"
        user_id = "u1"

        class cfg:
            pump_jev_on = admin_on
    h = PumpHub.__new__(PumpHub)
    h.system_keys = {"jev_api_key": KEY}
    h.engines = {"u1": E()}
    h.bruxo = Bruxo()
    h.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return h, E()


def test_hub_shadow_stores_decision_and_never_buys():
    calls = []

    def h(req):
        calls.append(req.url.host)
        return httpx.Response(200, json=_resp("evitar"))
    hub, e = _hub(h)
    s, _ = hub.bruxo.on_buy(W, "Top1", M, "JEV", 1.0, 1e-6, {}, 1.0, {}, __import__("time").time())

    async def go():
        assert hub.jev_shadow(s) is True
        assert s["jev"] == {"pendente": True}
        await asyncio.sleep(0.05)
    asyncio.run(go())
    assert calls == ["api.typesafe.ai"]                            # só o Jev foi chamado (nada de compra)
    assert s["jev"]["acao"] == "evitar" and s["id"] in hub.bruxo.dirty
    assert hub.jev_shadow(s) is False                              # um sinal = uma pergunta
    st = hub.jev_state(e, 24, "10")
    assert st["chave"] and st["ativo"] and len(st["linhas"]) == 1 and st["uso"]["calls"] == 1


def test_no_key_or_switched_off_means_no_call():
    hub, _ = _hub(lambda req: httpx.Response(500))
    s, _ = hub.bruxo.on_buy(W, "Top1", M, "JEV", 1.0, 1e-6, {}, 1.0, {}, __import__("time").time())
    hub.system_keys = {}
    assert hub.jev_shadow(s) is False and "jev" not in s
    hub2, _ = _hub(lambda req: httpx.Response(500), admin_on=False)
    s2, _ = hub2.bruxo.on_buy(W, "Top1", M, "JEV", 1.0, 1e-6, {}, 1.0, {}, __import__("time").time())
    assert hub2.jev_shadow(s2) is False


def test_jev_key_is_a_system_key():
    from app.keystore import KEY_LINKS, SYSTEM_NAMES
    assert "jev_api_key" in SYSTEM_NAMES and KEY_LINKS["jev_api_key"].startswith("https://")


# ------------------------------------------------------------------ 0.32.84: estudo do passado
TL = {"symbol": "OCT", "name": "Octover", "mcap0": 30.0, "dev_buy": 1.5, "peak": 90.0, "label": "despencou", "pred5": "lixo",
      "chance5": 45.2, "snaps": {"1": 60.0, "5": 30.0, "15": 30.0, "60": 27.0}, "created_at": "2026-10-30T06:03:36+00:00",
      "creator_before": {"tokens": 3, "rugs": 1}}
SH = {"t0": 1793343917.8, "px0": 1e-7, "ret": 25.0, "pico": 140.0, "veredito": "chance alta", "symbol": "HYPE",
      "why": "variação em 5 min fora da faixa", "info": {"age_min": 7.9, "holders": 117, "top10": 22.7, "pressure": 70.6}}


def test_past_cases_carry_nothing_from_the_future():
    c = jev.case_base(M, TL)
    blob = json.dumps(c["state"])
    for leak in ("despencou", "lixo", "45.2", "27.0", "90.0"):          # rótulo, previsão dos 5 min, fotos e pico futuros
        assert leak not in blob
    assert c["state"]["numbers"]["first_minute_change_pct"] == 100.0
    assert c["res"] == {"5": -54.0, "15": -54.0, "60": -59.0} and c["stop"] and c["pico"] == 50.0
    e = jev.case_explorar(M, SH)
    assert "ret" not in json.dumps(e["state"]) and "140" not in json.dumps(e["state"])
    assert e["res"] == {"15": 21.0} and e["regra"] is True and e["dobrou"] is True
    assert jev.case_base(M, {"snaps": {}}) is None and jev.case_explorar(M, {"t0": 1}) is None


def test_study_rows_uses_the_nearest_exit():
    rows = [dict(jev.compact(jev.case_explorar(M, SH), {"acao": "entrar", "p": {"entrar": 0.9}}), fonte="explorar"),
            dict(jev.compact(jev.case_base(M, TL), {"acao": "evitar", "p": {"entrar": 0.1}}), fonte="base")]
    st = jev.study_rows(rows, "10")                                     # explorar só tem 15 min; base usa 15 min
    assert st["n"] == 2 and st["por_acao"]["entrar"]["acerto"] == 100 and st["por_acao"]["evitar"]["acerto"] == 0
    assert abs(st["total"]["jev"] - 0.021) < 1e-6


class _DB:
    def __init__(self, tables):
        self.t, self.saved, self.by = tables, [], {}

    async def select(self, table, filters=None, order=None, limit=None, columns="*", offset=0, **kw):
        rows = self.t.get(table, [])
        return rows[offset:offset + (limit or len(rows))]

    async def insert(self, table, rows, upsert=False, on_conflict=None):
        rows = rows if isinstance(rows, list) else [rows]
        self.by.setdefault(table, []).extend(rows)
        if table == "jev_backtest":
            self.saved += rows


def test_hub_backtest_asks_each_past_case_once_and_saves():
    asked = []

    def h(req):
        asked.append(json.loads(req.content)["state"]["signal"]["kind"])
        return httpx.Response(200, json=_resp("entrar"))
    hub, e = _hub(h)
    hub.db = _DB({"bruxo_signals": [], "base_shadows": [{"mint": M, "data": SH}],
                  "token_life": [{"mint": M, "data": TL}, {"mint": "x", "data": {"snaps": {}}}]})

    async def go():
        assert hub.jev_bt_set(True, quiet=True)["ok"]
        for _ in range(50):
            await asyncio.sleep(0.01)
            if hub.jev_bt["fase"] == "em dia":
                break
        hub.jev_bt_set(False, quiet=True)
        hub.jev_bt["task"].cancel()
    import app.jev as J
    J.BT_GAP_S = 0
    asyncio.run(go())
    assert asked == ["explorar", "lancamento"]                          # caso sem foto de 1 min é pulado
    assert {r["id"] for r in hub.db.saved} == {"explorar:" + M + ":1793343917", "base:" + M}
    st = hub.jev_state(e, 0, "10", "todos")
    assert st["estudo"]["n"] == 2 and st["passado"]["feitos"] == {"explorar": 1, "base": 1} and len(st["linhas"]) == 2
    # de novo: nada é perguntado duas vezes
    asked.clear()
    hub.jev_bt["fase"] = "parado"

    async def again():
        hub.jev_bt_set(True, quiet=True)
        for _ in range(50):
            await asyncio.sleep(0.01)
            if hub.jev_bt["fase"] == "em dia":
                break
        hub.jev_bt_set(False, quiet=True)
        hub.jev_bt["task"].cancel()
    asyncio.run(again())
    assert asked == []


def test_backtest_needs_the_key():
    hub, _ = _hub(lambda req: httpx.Response(500))
    hub.system_keys = {}
    assert "error" in hub.jev_bt_set(True, quiet=True)


def test_live_decision_and_usage_go_to_supabase():
    """0.32.85: cada pergunta ao vivo vira linha em jev_decisions e o uso do dia em jev_usage (sem a chave)."""
    hub, _ = _hub(lambda req: httpx.Response(200, json=_resp("esperar")))
    hub.db = _DB({})
    s, _ = hub.bruxo.on_buy(W, "Top1", M, "JEV", 1.0, 1e-6, {}, 1.0, {}, __import__("time").time())

    async def go():
        hub.jev_shadow(s)
        await asyncio.sleep(0.05)
    asyncio.run(go())
    d = hub.db.by["jev_decisions"][0]
    assert d["acao"] == "esperar" and d["fonte"] == "bruxo" and d["sinal_id"] == s["id"] and d["p_esperar"] == 0.8
    assert KEY not in json.dumps(hub.db.by)
    u = hub.db.by["jev_usage"][0]
    assert u["tipo"] == "ao_vivo" and u["calls"] == 1


def test_usage_of_today_comes_back_after_restart():
    import time as _t
    hub, _ = _hub(lambda req: httpx.Response(500))
    day = _t.strftime("%Y-%m-%d", _t.gmtime())
    hub.db = _DB({"jev_usage": [{"dia": day, "tipo": "ao_vivo", "calls": 2999, "erros": 1, "tokens_in": 5, "ms": 9},
                                {"dia": day, "tipo": "passado", "calls": 7}]})
    asyncio.run(hub.jev_usage_load())
    assert hub.jev_stats["calls"] == 2999 and hub.jev_bt["calls_dia"] == 7
    s, _ = hub.bruxo.on_buy(W, "Top1", M, "JEV", 1.0, 1e-6, {}, 1.0, {}, _t.time())

    async def go():
        assert hub.jev_shadow(s) is True                     # a 3000ª ainda passa
        s2, _ = hub.bruxo.on_buy(W, "Top1", "Other".ljust(40, "1") + "pump", "X", 1.0, 1e-6, {}, 1.0, {}, _t.time())
        assert hub.jev_shadow(s2) is False                   # limite do dia continua valendo
        await asyncio.sleep(0.02)
    asyncio.run(go())


def test_migration_allows_every_system_key():
    """A chave do Jev não salvava: o banco só aceitava 4 nomes. Toda chave do sistema precisa estar na última regra."""
    import glob
    import re
    from app.keystore import SYSTEM_NAMES
    last = ""
    for f in sorted(glob.glob("supabase/migrations/*.sql")):
        txt = open(f, encoding="utf-8").read()
        m = re.findall(r"add constraint app_secrets_nome_check check \((.*?)\);", txt, re.S)
        if m:
            last = m[-1]
    assert last, "não achei a regra app_secrets_nome_check"
    for k in SYSTEM_NAMES:
        assert "'" + k + "'" in last, k + " falta na regra app_secrets_nome_check"


def test_dates_in_seconds_show_the_right_day():
    """0.32.89: as abas JEV e Jev Trade mandam a hora em segundos; dt() tratava como milissegundos (21/01/1970)."""
    js = open("web/app.js", encoding="utf-8").read()
    assert 'x < 1e11 ? x * 1000 : x' in js.split("const dt =", 1)[1].split("\n", 1)[0]


def test_jev_trade_token_opens_pump_fun_and_shows_holders_start_to_now():
    """0.32.90: nome do token abre a pump.fun e Detentores = 5 min → agora (diferença)."""
    js = open("web/app.js", encoding="utf-8").read()
    tk = js.split("const jtTk =", 1)[1].split("\n", 1)[0]
    assert "pfM(x.mint, x.symbol)" in tk and "data-jt" in tk
    ev = js.split("const jtEv =", 1)[1].split("};", 1)[0]
    assert "x.h0" in ev and "x.h - x.h0" in ev
