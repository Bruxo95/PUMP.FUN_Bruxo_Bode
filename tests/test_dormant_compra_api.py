"""0.32.242: rotas de carteiras e compra do Dormant. Só o admin, só a própria conta, nunca devolvem a chave."""
import httpx
import pytest

from app import dormant
from tests.test_api import UA, UB, env, tok  # noqa: F401  (fixture env)

KEY = "0x" + "0" * 63 + "1"
SENHA = "cavalo-azul-77"
ROTAS_POST = ["/api/dormant/carteiras/salvar", "/api/dormant/carteiras/remover", "/api/dormant/carteiras/senha", "/api/dormant/compra/ligar",
              "/api/dormant/compra/limites", "/api/dormant/compra/cotar", "/api/dormant/compra/confirmar", "/api/dormant/venda/cotar", "/api/dormant/venda/confirmar", "/api/dormant/gas/cotar", "/api/dormant/gas/confirmar", "/api/dormant/cex/chave", "/api/dormant/cex/chave/remover", "/api/dormant/cex/cotar", "/api/dormant/cex/confirmar"]
ROTAS_GET = ["/api/dormant/carteiras", "/api/dormant/compras", "/api/dormant/gas", "/api/dormant/compra/limite", "/api/dormant/cex", "/api/dormant/cex/moeda"]


def _watch(env):
    hub = env["hub"]
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(500, json={})))
    hub.dormant = dormant.DormantWatch(http, hub.db)
    return hub


def test_routes_are_admin_only(env):
    _watch(env)
    c = env["c"]
    for r in ROTAS_POST:
        assert c.post(r, json={}, headers=tok(UB, "b@x.com")).status_code == 403, r
        assert c.post(r, json={}).status_code == 401, r
    for r in ROTAS_GET:
        assert c.get(r, headers=tok(UB, "b@x.com")).status_code == 403, r


def test_view_as_never_reaches_wallets(env):
    hub = _watch(env)
    c = env["c"]
    c.get("/api/me", headers=tok(UB, "b@x.com"))
    c.post("/api/dormant/carteiras/salvar", json={"rede": "ethereum", "chave": KEY, "senha": SENHA}, headers=tok(UA))
    hdr = {**tok(UA), "X-View-As": UB}
    for r in ROTAS_GET:
        assert c.get(r, headers=hdr).status_code == 403, r
    assert hub.dormant.buyer is not None


def test_key_never_comes_back_in_any_response_and_audit_has_only_the_address(env):
    hub = _watch(env)
    c = env["c"]
    r = c.post("/api/dormant/carteiras/salvar", json={"rede": "ethereum", "chave": KEY, "senha": SENHA}, headers=tok(UA))
    assert r.json()["endereco"] == "0x7e5f4552091a69125d5dfcb7b8c2659029395bdf" and KEY not in r.text and SENHA not in r.text
    lst = c.get("/api/dormant/carteiras", headers=tok(UA))
    assert KEY not in lst.text and "cifra" not in lst.text and SENHA not in lst.text
    assert KEY not in str(hub.db.tables["audit_log"]) and SENHA not in str(hub.db.tables["audit_log"])
    assert KEY not in str(hub.db.tables["dormant_wallets"])
    assert any(a.get("acao") == "Dormant: carteira salva" for a in hub.db.tables["audit_log"])


def test_buy_is_refused_by_default_and_trava_geral_closed(env):
    _watch(env)
    c = env["c"]
    c.post("/api/dormant/carteiras/salvar", json={"rede": "ethereum", "chave": KEY, "senha": SENHA}, headers=tok(UA))
    assert c.post("/api/dormant/compra/confirmar", json={"quote_id": "x", "senha": SENHA, "confirmar": "COMPRAR"}, headers=tok(UA)).json()["error"]
    w = c.get("/api/dormant/carteiras", headers=tok(UA)).json()
    assert w["cfg"]["on"] is False and w["trava_geral"] is False


def test_unknown_error_answers_only_the_type(env, monkeypatch):
    hub = _watch(env)
    c = env["c"]
    c.get("/api/dormant/carteiras", headers=tok(UA))

    async def boom(*a, **k):
        raise RuntimeError("segredo " + KEY)
    monkeypatch.setattr(hub.dormant.buyer, "wallets", boom)
    r = c.get("/api/dormant/carteiras", headers=tok(UA))
    assert r.json()["error"] == "erro interno (RuntimeError)" and KEY not in r.text


def test_dormant_page_has_tighter_csp_and_new_menus(env):
    c = env["c"]
    p = c.get("/dormant")
    csp = p.headers["content-security-policy"]
    assert "script-src 'self' https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.118.0/;" in csp and "frame-ancestors 'none'" in csp
    assert 'href="#carteiras"' in p.text and 'href="#compras"' in p.text
    assert "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.118.0/" not in c.get("/app").headers["content-security-policy"]


def test_txguard_output_check_refuses_route_to_another_account():
    pytest.importorskip("solders")
    from solders.keypair import Keypair

    from app import txguard

    class Ix:
        def __init__(self, prog, accs):
            self.program_id_index, self.accounts = prog, bytes(accs)

    class Msg:
        def __init__(self, keys, ix):
            self.account_keys, self.instructions = keys, ix
    owner, mint, other = str(Keypair().pubkey()), str(Keypair().pubkey()), str(Keypair().pubkey())
    ata = next(iter(txguard.token_atas(owner, mint)))
    txguard.check_output(Msg([owner, txguard.JUPITER, ata], [Ix(1, [0, 2])]), owner, mint)
    with pytest.raises(txguard.TxRejected):
        txguard.check_output(Msg([owner, txguard.JUPITER, other], [Ix(1, [0, 2])]), owner, mint)
    with pytest.raises(txguard.TxRejected):
        txguard.check_output(Msg([owner, txguard.SYSTEM], [Ix(1, [0])]), owner, mint)
