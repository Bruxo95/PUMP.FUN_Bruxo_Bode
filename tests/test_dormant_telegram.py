"""0.32.329 (pedido do dono, 12/11/2026: "faz tudo"): alertas do Dormant no Telegram, por conta, com os tipos escolhidos."""
import asyncio

from app import dormant_buy
from app.dormant import tg_text
from app.hub import PumpHub


def run(c):
    return asyncio.new_event_loop().run_until_complete(c)


def test_text_lists_alerts_and_cuts_after_ten():
    al = [{"simbolo": "DGB", "nome": "DigiByte", "para": "acordando", "preco": 0.0123, "h1": 3.2, "h24": 18.2, "por": ["rompeu o topo"]}] * 12
    t = tg_text(al)
    assert t.startswith("Dormant: 12 alertas") and "DGB (DigiByte): ACORDANDO" in t and "+18.2%" in t and "e mais 2" in t


def test_default_is_off_and_types_are_cleaned():
    assert dormant_buy.CFG_DEFAULT["tg_on"] is False
    assert dormant_buy.clean_cfg(None, {"tg_on": True, "tg_tipos": ["pump"]})["tg_tipos"] == ["pump"]


class FakeDB:
    def __init__(self, rows, roles):
        self.rows, self.roles = rows, roles

    async def select(self, table, filters=None, **kw):
        if table == "dormant_buy_cfg":
            return self.rows
        if table == "profiles":
            return [{"role": self.roles.get(filters["user_id"]), "bloqueado": False}]
        raise AssertionError(table)


class FakeHub:
    def __init__(self, alertas, rows, roles):
        self.dormant = type("W", (), {"alertas": alertas})()
        self.db = FakeDB(rows, roles)
        self.sent = []

    async def engine(self, uid):
        return uid

    async def tg_send_now(self, pf, msg, force=False):
        self.sent.append((pf, msg))
        return True, ""


def test_tick_sends_only_new_alerts_of_chosen_types_to_admins_who_turned_it_on():
    al = [{"t": 100, "para": "pump", "simbolo": "OLD"}]
    rows = [{"user_id": "a", "cfg": {"tg_on": True, "tg_tipos": ["acordando"]}},
            {"user_id": "b", "cfg": {"tg_on": False}},
            {"user_id": "c", "cfg": {"tg_on": True}},          # usuário comum: não recebe
            {"user_id": "d", "cfg": {"tg_on": True, "tg_tipos": ["pump", "dump"]}}]
    h = FakeHub(al, rows, {"a": "admin", "b": "admin", "c": "user", "d": "admin"})
    last = run(PumpHub.dormant_tg_tick(h, None))
    assert last == 100 and not h.sent                         # na subida não manda o que já existia
    h.dormant.alertas = [{"t": 200, "para": "acordando", "simbolo": "NEW"}, {"t": 150, "para": "dump", "simbolo": "DMP"}] + al
    last = run(PumpHub.dormant_tg_tick(h, last))
    assert last == 200
    assert [(u, "NEW" in m, "DMP" in m) for u, m in h.sent] == [("a", True, False), ("d", False, True)]
    h.sent.clear()
    assert run(PumpHub.dormant_tg_tick(h, last)) == 200 and not h.sent
