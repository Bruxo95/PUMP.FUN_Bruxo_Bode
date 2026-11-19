"""0.32.379 (pedido do dono, 19/11/2026): uma chave liga/desliga para cada laço de consulta do servidor (vale para todos;
o valor é o do admin que mudou por último). Sem internet."""
from app import consultas
from tests.test_api import UA, UB, env, tok  # noqa: F401  (fixture env)

W1 = "Man1".ljust(44, "1")


def test_so_admin_desliga_e_vale_para_o_servidor(env):
    c, hub, db = env["c"], env["hub"], env["db"]
    A, B = tok(UA), tok(UB, "b@x.com")
    assert c.get("/api/pump/consultas", headers=B).status_code == 403
    assert c.post("/api/pump/settings", json={"pump_q_top": False}, headers=B).status_code == 403
    r = c.get("/api/pump/consultas", headers=A).json()["itens"]
    assert {x["key"] for x in r} == set(consultas.KEYS) and all(x["on"] for x in r)   # ninguém mudou = tudo ligado
    assert consultas.on("pump_q_boost") and consultas.on("pump_q_top")
    # "Só BOOST": desliga tudo menos o BOOST
    body = {k: k == "pump_q_boost" for k in consultas.KEYS}
    assert c.post("/api/pump/settings", json=body, headers=A).json()["applied"] == body
    assert consultas.on("pump_q_boost") and not consultas.on("pump_q_top") and not consultas.on("pump_q_jev")
    itens = {x["key"]: x for x in c.get("/api/pump/consultas", headers=A).json()["itens"]}
    assert itens["pump_q_top"]["on"] is False and itens["pump_q_top"]["de"] and itens["pump_q_boost"]["on"] is True
    acoes = [a["acao"] for a in db.tables["audit_log"] if a["user_id"] == UA]
    assert "consulta do servidor desligada" in acoes
    # nunca vai junto ao compartilhar a configuração
    assert not [k for k in hub.share_filter(consultas.KEYS, True)]
    # ligar de novo
    c.post("/api/pump/settings", json={"pump_q_top": True}, headers=A)
    assert consultas.on("pump_q_top")


def test_top_desligado_para_de_seguir_as_manuais_e_o_ranking(env):
    c, hub = env["c"], env["hub"]
    A = tok(UA)
    c.post("/api/pump/wallets", json={"wallet": W1, "action": "add"}, headers=A)
    pf = hub.engines[UA]
    pf.refresh_followed(force=True)
    assert W1 in pf.followed
    c.post("/api/pump/settings", json={"pump_q_top": False}, headers=A)
    assert W1 not in pf.followed and pf.top_active == []
    c.post("/api/pump/settings", json={"pump_q_top": True}, headers=A)
    assert W1 in pf.followed


def test_boost_desligado_ignora_migracao(env):
    c, hub = env["c"], env["hub"]
    A = tok(UA)
    c.get("/api/pump", headers=A)
    M = "Qbst".ljust(40, "1") + "pump"
    c.post("/api/pump/settings", json={"pump_q_boost": False}, headers=A)
    hub.bm_on_migration({"mint": M, "txType": "migrate", "pool": "pump-amm"})
    assert M not in hub.bm.items
    c.post("/api/pump/settings", json={"pump_q_boost": True}, headers=A)
    hub.bm_on_migration({"mint": M, "txType": "migrate", "pool": "pump-amm"})
    assert M in hub.bm.items
