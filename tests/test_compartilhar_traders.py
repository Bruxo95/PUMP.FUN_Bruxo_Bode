"""Compartilhar a lista de traders adicionados à mão (0.31.74): vira convite; só entra ao aceitar."""
from tests.test_api import UA, UB, env, tok  # noqa: F401  (fixture env)

W1, W2 = "Wa11".ljust(44, "1"), "Wb22".ljust(44, "2")


def test_share_traders_list_is_an_invite(env):
    c, hub = env["c"], env["hub"]
    A, B = tok(UA), tok(UB, "b@x.com")
    c.get("/api/pump", headers=A)
    c.get("/api/pump", headers=B)
    a, b = hub.engines[UA], hub.engines[UB]
    a.add_manual(W1)
    a.add_manual(W2)
    r = c.post("/api/pump/traders/share", json={"to": UB}, headers=A).json()
    assert r.get("ok") and r["carteiras"] == 2
    assert W1 not in b.manual                                            # nada entra antes de aceitar
    off = c.get("/api/pump/config/offers", headers=B).json()["offers"][0]
    assert off["tipo"] == "traders"
    c.post(f"/api/pump/config/offers/{off['id']}", json={"accept": True}, headers=B)
    assert W1 in b.manual and W2 in b.manual
    assert c.get("/api/pump/config/applied", headers=B).json().get("applied", []) == []   # não vira "configuração copiada"
