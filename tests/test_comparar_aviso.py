"""0.32.481 (pedido do dono, 27/11): as regras do BOOST ficam salvas por usuário depois de um deploy (reinício), e a comparação
de configurações só avisa quando a configuração da OUTRA pessoa muda; descartar fica guardado na conta, não no navegador."""
import httpx
from fastapi.testclient import TestClient

from tests.test_api import SB, SECRET, UA, UB, _flush, env, net_handler, tok  # noqa: F401  (fixture env)


def _restart(env):
    from app.api import create_app
    from app.auth import Auth
    from app.crypto import SecretBox
    from app.hub import PumpHub
    _flush(env["hub"])
    http = httpx.AsyncClient(transport=httpx.MockTransport(net_handler))
    hub2 = PumpHub(env["cfg"], http, env["db"], SecretBox(env["cfg"].encryption_key))
    return TestClient(create_app(hub2, Auth(SB, "anon", http, SECRET), env["cfg"])), hub2


def test_regras_do_boost_sobrevivem_ao_deploy_por_usuario(env):
    c = env["c"]
    A, B = tok(UA), tok(UB, "b@x.com")
    rA = c.post("/api/pump/settings", json={"pump_bm_sol": 0.13, "pump_bm_stop_pct": 41, "pump_bmr_on": True,
                                            "pump_bmr_trail_dist": 5, "pump_bm_ext_on": False}, headers=A).json()
    assert not rA.get("errors")
    c.post("/api/pump/settings", json={"pump_bm_sol": 0.07, "pump_bm_stop_pct": 22}, headers=B)
    c2, _ = _restart(env)                                                  # "deploy": servidor novo lendo do banco
    a = c2.get("/api/pump", headers=A).json()["cfg"]
    b = c2.get("/api/pump", headers=B).json()["cfg"]
    assert (a["pump_bm_sol"], a["pump_bm_stop_pct"], a["pump_bmr_on"], a["pump_bmr_trail_dist"], a["pump_bm_ext_on"]) == (0.13, 41, True, 5, False)
    assert (b["pump_bm_sol"], b["pump_bm_stop_pct"]) == (0.07, 22)        # cada conta com a sua


def test_aviso_so_quando_a_outra_pessoa_muda_e_descartar_fica_na_conta(env):
    c, db = env["c"], env["db"]
    A, B = tok(UA), tok(UB, "b@x.com")
    c.get("/api/pump", headers=A)
    c.post("/api/pump/settings", json={"pump_bm_stop_pct": 41}, headers=B)
    q = {"user": UB, "tela": "boost", "reais": 1, "escopo": "boost"}
    r = c.post("/api/pump/config/peer", json=q, headers=A).json()
    assert r["aviso"] is False                                             # 1ª vez: guarda em silêncio, mesmo com diferenças
    assert c.post("/api/pump/config/peer", json=q, headers=A).json()["aviso"] is False   # "logar de novo" não avisa
    c.post("/api/pump/settings", json={"pump_bm_stop_pct": 35}, headers=B)              # a outra pessoa mudou
    r = c.post("/api/pump/config/peer", json=q, headers=A).json()
    assert r["aviso"] is True and {"k": "pump_bm_stop_pct", "de": 41, "para": 35} in r["mudou"]
    antes = dict(env["hub"].engines[UA].cfg.user_dict())
    assert c.post("/api/pump/config/visto", json=q, headers=A).json()["ok"] is True     # descartar
    assert env["hub"].engines[UA].cfg.user_dict() == antes                               # não mexe na sua configuração
    assert c.post("/api/pump/config/peer", json=q, headers=A).json()["aviso"] is False
    c2, _ = _restart(env)                                                  # depois de um deploy continua descartado
    assert c2.post("/api/pump/config/peer", json=q, headers=A).json()["aviso"] is False
    c2.post("/api/pump/settings", json={"pump_bm_stop_pct": 30}, headers=B)              # nova alteração: avisa de novo
    assert c2.post("/api/pump/config/peer", json=q, headers=A).json()["aviso"] is True
    assert c2.post("/api/pump/config/visto", json={"escopo": "x", "user": UB}, headers=A).json()["error"]
    assert c2.post("/api/pump/config/visto", json=q, headers=B).status_code == 403      # só admin
