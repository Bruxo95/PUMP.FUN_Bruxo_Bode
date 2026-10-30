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
    assert seen["body"]["model"] == "jev-latest" and set(seen["body"]["questions"]) == {"acao", "qualidade", "armadilha"}
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
