"""0.32.464 (pedido do dono): o BOOST avisa quando a conta comparada está desligada e pergunta se quer desligar o seu."""
import pathlib

from tests.test_api import UA, UB, env, tok  # noqa: F401  (fixture env)

JS = pathlib.Path("web/app.js").read_text(encoding="utf-8")


def test_comparacao_do_boost_traz_as_chaves_real_da_outra_conta(env):
    c = env["c"]
    A, B = tok(UA), tok(UB, "b@x.com")
    c.get("/api/pump", headers=A)
    c.post("/api/pump/settings", json={"pump_bm_on": False}, headers=B)
    r = c.post("/api/pump/config/peer", json={"user": UB, "tela": "boost", "reais": 1}, headers=A).json()
    assert r["valores"]["pump_bm_on"] is False
    assert r["reais"]["pump_bm_real"] is False and r["reais"]["pump_real_enabled"] is False


def test_pergunta_na_tela_e_so_desliga_no_clique():
    assert 'tela: "boost", reais: 1' in JS
    assert 'data-bmc="peeroff"' in JS and 'data-bmc="peerkeep"' in JS
    bloco = JS[JS.index("async function bmcPeerOff"):JS.index("async function bmcBar")]
    assert "pump_bm_on: false" in bloco and "pump_bm_real = false" in bloco
    assert ": true" not in bloco and "= true;" not in bloco          # este botão nunca liga nada
    assert JS.count("bmcPeerOff()") == 2                              # a definição e o clique
    assert "pf_bmc_keepon" in JS
