"""Operações automáticas: persistência por conta, fotos posteriores e rotas sem rede real."""
import asyncio
import copy
import time
from datetime import datetime, timezone

from app.auto_trades import iso
from tests.test_api import UA, UB, env, tok  # noqa: F401
from tests.test_rls_postgres import pg  # noqa: F401

M = "AutoRegistro".ljust(40, "1") + "pump"


def engine(env, uid=UA):
    pf = asyncio.run(env["hub"].engine(uid))
    # travas da 0.31.0 têm testes próprios em test_auto_seguranca.py
    pf.cfg.pump_ar_min_age_min, pf.cfg.pump_ar_fresh_on, pf.cfg.pump_ar_smart_on = 0, False, False
    return pf


def buy(pf, t=None):
    t = time.time() - 120 if t is None else t
    pf.tokens[M] = {"price": 1e-6, "symbol": "REG", "mcap_sol": 40, "last_t": t}
    result = pf.manual_buy(M, t, auto="automático: chance alta", origem="explorar",
                           info={"veredito": "chance alta", "chance": None, "pressure": 75,
                                 "holders": 210, "curve_pct": 85, "risk": 3, "chg_5m": 12})
    assert result.get("auto_id"), result
    return pf.positions()[0]


def flush(env, pf):
    async def run():
        await pf.store.flush()
        return await env["hub"].save_auto(pf)
    return asyncio.run(run())


def test_auto_open_partial_close_and_reload_share_one_record(env):
    pf = engine(env)
    p = buy(pf)
    rid = str(p["id"])
    assert pf.auto_ready and pf.auto_rows[rid]["saida_em"] is None
    assert flush(env, pf) == 1
    row = env["db"].tables["auto_trades"][0]
    assert row["id"] == rid and row["user_id"] == UA and row["origem"] == "explorar"
    assert row["info"]["pressure"] == 75 and row["chance"] is None
    pf._sell(p, 0.5, 1.7e-6, "venda em partes", time.time() - 60)
    flush(env, pf)
    row = env["db"].tables["auto_trades"][0]
    assert row["saida_em"] is None and len(row["info"]["sells"]) == 1
    p = pf.positions()[0]
    pf._sell(p, 1.0, 2e-6, "alvo", time.time() - 30)
    flush(env, pf)
    row = env["db"].tables["auto_trades"][0]
    assert len(env["db"].tables["auto_trades"]) == 1 and pf.positions() == []
    assert str(pf.trades()[0]["id"]) == rid and row["saida_em"] and row["pnl_sol"] == pf.trades()[0]["pnl_sol"]
    assert row["motivo_saida"] == "alvo" and row["info"]["exit_price"] == 2e-6
    env["hub"].engines.pop(UA)
    restored = engine(env)
    assert restored.auto_ready and rid in restored.auto_rows
    assert "24 h" in restored.auto_guard(M)


def test_auto_write_failure_keeps_dirty_rows_and_pauses_new_entries_until_recovery(env):
    pf = engine(env)
    p = buy(pf)
    rid = str(p["id"])
    env["db"].fail = True
    assert asyncio.run(env["hub"].save_auto(pf)) == 0
    assert not pf.auto_ready and rid in pf._auto_dirty
    assert "indisponível" in pf.auto_guard()
    env["db"].fail = False
    assert asyncio.run(env["hub"].save_auto(pf)) == 1
    assert pf.auto_ready and not pf._auto_dirty


def test_auto_missing_table_never_becomes_an_empty_safe_history(env):
    del env["db"].tables["auto_trades"]
    pf = engine(env)
    assert not pf.auto_ready and not pf._auto_loaded
    pf.tokens[M] = {"price": 1e-6, "symbol": "REG"}
    result = pf.manual_buy(M, auto="chance alta", origem="explorar", info={})
    assert not result.get("auto_id") and not pf.positions()
    env["db"].tables["auto_trades"] = []
    assert asyncio.run(env["hub"].load_auto(pf))
    assert pf.auto_ready


def test_auto_trades_route_is_admin_scoped_and_manual_base_screen_excludes_explore(env):
    c, db = env["c"], env["db"]
    assert c.get("/api/pump/auto-trades").status_code == 401
    assert c.get("/api/pump/auto-trades", headers=tok(UB)).status_code == 403
    assert c.post("/api/pump/settings", headers=tok(UB), json={"pump_ex_auto_on": True}).status_code == 403
    assert c.post("/api/pump/settings", headers=tok(UB), json={"pump_ar_sol": 0.05}).status_code == 403
    assert c.post("/api/pump/settings", headers=tok(UB), json={"pump_copy_sol": 0.1}).json()["applied"]
    pf = engine(env)
    p = buy(pf)
    flush(env, pf)
    result = c.get("/api/pump/auto-trades?origem=explorar", headers=tok(UA)).json()
    assert len(result["items"]) == 1 and result["items"][0]["open"]
    assert result["items"][0]["estimated"] and result["items"][0]["pnl_sol"] < 0
    assert result["summary"]["period"]["closed"] == 0 and result["summary_mode"] == "simulado"
    assert c.get("/api/pump/base", headers=tok(UA)).json()["mine"] == []
    db.set_role(UB, "admin")
    assert c.get("/api/pump/auto-trades?origem=explorar&user_id=" + UA, headers=tok(UB)).json()["items"] == []
    assert c.get("/api/pump/auto-trades?origem=outra", headers=tok(UA)).status_code == 422
    assert c.get("/api/pump/auto-trades?days=100000", headers=tok(UA)).status_code == 422
    pf._sell(p, 1.0, 2e-6, "alvo", time.time() - 1)
    flush(env, pf)
    result = c.get("/api/pump/auto-trades", headers=tok(UA)).json()
    assert result["summary"]["day"]["closed"] == 1 and result["readiness"]["closed_sim"] == 1
    assert not result["readiness"]["recommended"]
    assert all(call[2].get("user_id") in (UA, UB) for call in db.calls if call[0] == "select" and call[1] == "auto_trades")


def test_auto_after_exit_keeps_token_in_prices_and_saves_only_fresh_15m_and_60m_samples(env):
    from app.monitor import SharedMonitor
    pf = engine(env)
    p = buy(pf, time.time() - 120)
    exited = time.time()
    pf._sell(p, 1.0, 2e-6, "alvo", exited)
    row = pf.auto_rows[str(p["id"])]
    mon = SharedMonitor(env["hub"])
    assert M in mon.held()["trader"]
    env["hub"].market.tokens[M].update(price=3e-6, last_t=exited + 899)
    mon.auto_after_once(exited + 900)
    assert "15m" not in row["depois"]
    env["hub"].market.tokens[M]["last_t"] = exited + 901
    mon.auto_after_once(exited + 901)
    assert row["depois"]["15m"] == 50
    env["hub"].market.tokens[M].update(price=1e-6, last_t=exited + 3601)
    mon.auto_after_once(exited + 3601)
    assert row["depois"]["60m"] == -50 and row["info"]["depois_em"]["60m"]
    flush(env, pf)
    assert env["db"].tables["auto_trades"][0]["depois"] == {"15m": 50, "60m": -50}
    assert M not in mon.held()["trader"]


def test_explore_monitor_requires_current_source_fresh_prices_and_active_admin(env):
    from app.explore import parse
    from app.monitor import SharedMonitor
    from tests.test_explore import G, _sample
    pf = engine(env)
    pf.cfg.pump_ex_auto_on = True
    now = time.time()
    env["hub"].explore.update(parse(_sample()), now)
    mon = SharedMonitor(env["hub"])
    requests = []
    async def curve(mints, public_first=False):
        requests.extend(mints)
        for mint in mints:
            pf.tokens.setdefault(mint, {}).update(price=1e-6, last_t=now, mcap_sol=40)
        return []
    mon.svc._curve_prices = curve
    assert asyncio.run(mon.explore_auto_once(now)) == 1 and requests == [G]
    assert pf.positions()[0]["origem"] == "explorar"
    assert asyncio.run(mon.explore_auto_once(now + 301)) == 0
    env["db"].set_role(UA, "user")  # alteração externa ao cache do motor
    env["hub"].explore.at = now
    assert asyncio.run(mon.explore_auto_once(now)) == 0
    assert pf.role == "user" and pf.cfg.pump_ex_auto_on is False


def test_demotion_updates_loaded_engine_and_disables_explore_auto(env):
    env["db"].set_role(UB, "admin")
    pf = engine(env, UB)
    pf.cfg.pump_ex_auto_on = True
    assert asyncio.run(env["hub"].admin_update_user(UA, UB, {"role": "user"}))["ok"]
    assert pf.role == "user" and pf.cfg.pump_ex_auto_on is False


def test_auto_table_rls_and_browser_write_denial(pg):
    for uid, tag in ((UA, "a"), (UB, "b")):
        assert pg(f"insert into auth.users(id,email) values ('{uid}','{tag}@example.test') on conflict do nothing")[0] == 0
        assert pg(f"insert into public.auto_trades(id,user_id,origem,mint,entrada_em) values ('auto-{tag}','{uid}','explorar','M',now())")[0] == 0
    assert pg("select count(*) from public.auto_trades", claims=UA, role="authenticated")[1] == "1"
    assert pg(f"select count(*) from public.auto_trades where user_id='{UB}'", claims=UA, role="authenticated")[1] == "0"
    assert pg("select count(*) from public.auto_trades", role="anon")[0] != 0
    assert pg(f"insert into public.auto_trades(id,user_id,origem,mint,entrada_em) values ('x','{UA}','explorar','M',now())", claims=UA, role="authenticated")[0] != 0
