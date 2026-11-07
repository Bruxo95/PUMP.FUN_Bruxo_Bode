"""0.32.167: por que duas contas com a mesma configuração compraram moedas diferentes. Só leitura. Sem internet."""
import inspect

from app import buydiff
from tests.test_api import env  # noqa: F401  (fixture env)
from tests.test_pump import _W, _ev, _pump

M1, M2 = "Dif1".ljust(40, "1") + "pump", "Dif2".ljust(40, "1") + "pump"
W2 = "Trd2".ljust(44, "2")


def test_each_coin_bought_by_one_account_says_why_the_other_did_not(tmp_path):
    a = _pump(tmp_path / "a", paid=False, pump_min_trader_sol=0.2)
    b = _pump(tmp_path / "b", paid=False, pump_min_trader_sol=0.5)
    a.add_manual(_W)
    b.add_manual(_W)
    a.add_manual(W2)                                             # só a conta A copia este trader
    for e in (a, b):
        e.on_message(_ev("buy", _W, M1, 0.3, 1e6, 30, 3e7))      # A copia; B barra pela compra mínima
        e.on_message(_ev("buy", W2, M2, 1.0, 1e6, 30, 3e7))      # só chega na A
    r = buydiff.compare(a, b, 24)
    assert r["n"] == {"ambos": 0, "so_eu": 2, "so_outro": 0}
    why = {x["mint"]: x["por_que_nao"] for x in r["so_eu"]}
    assert "compra pequena" in why[M1] and "não copiou" in why[M1]
    assert why[M2].startswith("não copia este trader") and "não está na lista" in why[M2]
    t = {x["wallet"]: x for x in r["traders_so_eu"]}
    assert W2 in t and "lista manual" in t[W2]["fonte"]


def test_pause_shows_as_the_reason(tmp_path):
    a = _pump(tmp_path / "a", paid=False)
    b = _pump(tmp_path / "b", paid=False)
    for e in (a, b):
        e.add_manual(_W)
    b.pause(_W, 48, "ajuste automático: trader com prejuízo")
    assert b.follow_info(_W) == {"segue": False, "por": "pausado nesta conta (ajuste automático: trader com prejuízo)"}
    assert a.follow_info(_W)["segue"] is True


def test_copy_now_says_if_the_wallet_is_copied_in_each_wallet(tmp_path):
    """0.32.251: estar na lista não basta; a chave desligada e a carteira só fictícia aparecem como tal."""
    p = _pump(tmp_path / "a", paid=False)
    assert p.copy_now(W2) == {"estado": "nao", "por": p.follow_info(W2)["por"]}
    p.add_manual(_W)
    assert p.copy_now(_W)["estado"] == "sim" and "lista manual" in p.copy_now(_W)["por"]
    assert p.copy_now(_W, real=True) == {"estado": "parado", "por": "na lista, mas a carteira REAL está desligada"}
    p.cfg.pump_real_enabled, p.real = True, object()
    assert p.copy_now(_W, real=True)["estado"] == "sim"
    p.sim_only_list = [_W]
    assert p.copy_now(_W, real=True) == {"estado": "so_ficticia", "por": p.sim_only_why(_W)}
    assert p.copy_now(_W)["estado"] == "sim"                     # na fictícia continua copiando
    p.cfg.pump_sim_on = False
    assert p.copy_now(_W)["estado"] == "parado"
    p.cfg.pump_sim_on, p.cfg.pump_copy_enabled = True, False
    assert "Cópia de traders" in p.copy_now(_W)["por"] and p.copy_now(_W)["estado"] == "parado"
    p.cfg.pump_copy_enabled, p.cfg.pump_top_on = True, False
    assert p.copy_now(_W) == {"estado": "parado", "por": "na lista, mas a aba Top traders está desligada"}
    p.pause(_W, 48, "teste")
    assert p.copy_now(_W)["estado"] == "nao"


def test_module_only_reads():
    src = inspect.getsource(buydiff)
    for proibido in ("manual_buy", "save_settings", ".pause(", "_sell(", "add_manual", "_meta_set"):
        assert proibido not in src


def test_route_compares_two_admins(env):
    from tests.test_api import UA, UB, tok
    c = env["c"]
    env["db"].set_role(UB, "admin")
    c.get("/api/pump", headers=tok(UB, "b@x.com"))
    r = c.get("/api/pump/buy-diff?peer=" + UB + "&horas=24", headers=tok(UA)).json()
    assert r["n"] == {"ambos": 0, "so_eu": 0, "so_outro": 0} and "outro" in r
    assert "error" in c.get("/api/pump/buy-diff?peer=" + UA, headers=tok(UA)).json()
    assert "error" in c.get("/api/pump/buy-diff?peer=x", headers=tok(UA)).json()
