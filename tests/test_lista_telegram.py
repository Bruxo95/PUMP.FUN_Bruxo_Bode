"""Lista negra compartilhada e avisos no Telegram (0.20.0). Nenhum teste usa internet."""
import asyncio
import json
import time

import httpx

from tests.test_api import UA, UB, env, tok  # noqa: F401  (fixture env)
from tests.test_pump import _W, _ev, _pump

_DEV = "DevRugger111111111111111111111111111111"
_BOT = "123456789:" + "A" * 35


def test_blacklist_blocks_creator_only_when_on(tmp_path):
    pf = _pump(tmp_path, paid=False)
    pf.add_manual(_W)
    m = "Black".ljust(40, "1") + "pump"
    t = time.time()
    pf.on_message(_ev("create", _DEV, m, 0, 0, 30, 3e7, symbol="BLK"), t - 5)
    pf.blacklist_add(_DEV, "dev", "teste")
    assert pf.market.bl_new == [_DEV]
    pf.on_message(_ev("buy", _W, m, 1.0, 1e6, 30, 3e7), t)                  # opção OFF: copia normalmente
    assert len(pf.positions()) == 1
    pf2 = _pump(tmp_path, paid=False, pump_blacklist_on=True)
    pf2.market = pf.market                                                  # a lista é compartilhada
    pf2.add_manual(_W)
    pf2.on_message(_ev("buy", _W, m, 1.0, 1e6, 30, 3e7), t + 1)
    assert not pf2.positions() and any("lista negra" in str(e.get("reason")) for e in pf2.feed)


def test_dev_sale_with_loss_feeds_the_blacklist(tmp_path):
    pf = _pump(tmp_path, paid=False, pump_exit_dev_sell=True)
    pf.add_manual(_W)
    m = "DevLoss".ljust(40, "1") + "pump"
    t = time.time()
    pf.on_message(_ev("create", _DEV, m, 0, 0, 30, 3e7, symbol="DL"), t - 5)
    pf.on_message(_ev("buy", _W, m, 1.0, 1e6, 30, 3e7), t)
    pf.on_message(_ev("sell", _DEV, m, 0.1, 1e5, 30, 3e7), t + 1)           # mesmo preço: fecha no prejuízo das taxas
    tr = pf.trades()[0]
    assert tr["reason"].startswith("dev vendeu") and tr["pnl_sol"] < 0
    assert pf.market.blacklist[_DEV]["tipo"] == "dev"


def test_blacklist_routes_are_admin_only_and_persist(env):
    c, hub, db = env["c"], env["hub"], env["db"]
    A, B = tok(UA), tok(UB, "b@x.com")
    assert c.post("/api/pump/blacklist", json={"endereco": _DEV, "tipo": "dev"}, headers=B).status_code == 403
    assert c.post("/api/pump/blacklist", json={"endereco": "x;drop", "tipo": "dev"}, headers=A).json()["error"]
    assert c.post("/api/pump/blacklist", json={"endereco": _DEV, "tipo": "dev", "motivo": "rug"}, headers=A).json()["ok"]
    assert db.tables["blacklist"][0]["endereco"] == _DEV and db.tables["blacklist"][0]["motivo"] == "rug"
    r = c.get("/api/pump/blacklist", headers=A).json()
    assert r["count"] == 1 and r["items"][0]["endereco"] == _DEV and r["on"] is False
    hub.market.blacklist.clear()
    asyncio.run(hub.load_blacklist())
    assert _DEV in hub.market.blacklist
    assert c.post("/api/pump/blacklist", json={"endereco": _DEV, "action": "remove"}, headers=A).json()["ok"]
    assert db.tables["blacklist"] == [] and _DEV not in hub.market.blacklist
    assert c.get("/api/pump/blacklist", headers=B).status_code == 403


def test_telegram_keys_are_validated_and_messages_filtered(env):
    c, hub = env["c"], env["hub"]
    A = tok(UA)
    assert c.post("/api/secrets", json={"name": "telegram_chat_id", "value": "abc"}, headers=A).json()["error"]
    assert c.post("/api/secrets", json={"name": "telegram_bot_token", "value": "curto"}, headers=A).json()["error"]
    assert c.post("/api/secrets", json={"name": "telegram_chat_id", "value": "987654321"}, headers=A).json()["ok"]
    assert c.post("/api/secrets", json={"name": "telegram_bot_token", "value": _BOT}, headers=A).json()["ok"]
    keys = c.get("/api/secrets", headers=A).json()["keys"]
    assert keys["telegram_bot_token"]["configured"] and _BOT not in json.dumps(keys)
    pf = hub.engines[UA]
    assert not hub.tg_wanted(pf, "Radar: HOT callout em X")                 # opção OFF
    pf.cfg.pump_tg_on = True
    assert hub.tg_wanted(pf, "Radar: HOT callout em X") and hub.tg_wanted(pf, "[PUMP SIM] fechou X (stop de perda) → -0.01")
    assert not hub.tg_wanted(pf, "[PUMP SIM] copiou X: compra")
    pf.cfg.pump_tg_all = True
    assert hub.tg_wanted(pf, "[PUMP SIM] copiou X: compra")


def test_telegram_send_uses_the_users_bot_and_chat(env):
    hub = env["hub"]
    env["c"].get("/api/pump", headers=tok(UA))
    pf = hub.engines[UA]
    seen = []

    def handler(req: httpx.Request):
        seen.append((str(req.url), json.loads(req.content)))
        return httpx.Response(200, json={"ok": True})
    hub.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    ok, err = asyncio.run(hub.tg_send_now(pf, "teste"))
    assert not ok and "Chaves pessoais" in err and seen == []
    pf.keys.set("telegram_bot_token", _BOT)
    pf.keys.set("telegram_chat_id", "987654321")
    ok, err = asyncio.run(hub.tg_send_now(pf, "aviso"))
    assert ok and seen[0][0] == f"https://api.telegram.org/bot{_BOT}/sendMessage"
    assert seen[0][1]["chat_id"] == "987654321" and seen[0][1]["text"] == "aviso"
    r = env["c"].post("/api/pump/telegram/test", headers=tok(UA)).json()
    assert r == {"ok": True} and "teste de aviso" in seen[-1][1]["text"]
