"""0.32.33 (pedido do dono): aprendizado das posições — antes da entrada, fotos de 15 min, depois da saída; e ajustes
pendentes que o servidor antigo não consegue sobrescrever. Tudo sem internet."""
import asyncio

from app.poslearn import aggregate, entry_context, exit_label
from tests.test_pump import _W, _ev, _pump

M = "Lrn".ljust(40, "1") + "pump"


def test_entry_context_and_exit_label():
    hist = [(100.0 + i * 60, 1.0 + i * 0.1) for i in range(10)]           # subiu a janela toda
    ctx = entry_context(hist, 100.0 + 9 * 60, 1.9)
    assert ctx["pos_pct"] == 100.0 and ctx["subiu_antes_pct"] == 90.0
    assert entry_context([], 1000.0, 1.0) is None
    assert exit_label({"15": 5, "30": 45, "60": 10}, -20).startswith("saiu cedo")
    assert exit_label({"15": -20, "30": -30, "60": -40}, 5).startswith("saída certa")


def test_position_lifecycle_feeds_learning(tmp_path):
    pf = _pump(tmp_path, paid=False)
    pf.cfg.pump_hold_until_profit = False                  # vende junto com o trader (sem segurar até lucro)
    pf.add_manual(_W)
    pf.market.px_hist[M] = [(1000.0 - 600 + i * 60, 1e-6 * (0.9 + i * 0.01)) for i in range(10)]
    pf.on_message(_ev("buy", _W, M, 1.0, 1e6, 30, 3e7), 1000.0)
    pf.pos_snapshots(1000.0)
    p = [p for p in pf.positions() if p["mint"] == M][0]
    assert p["antes"] and p["antes"]["n"] >= 3
    pf.pos_snapshots(1000.0 + 901)
    assert len([p for p in pf.positions() if p["mint"] == M][0]["snaps"]) == 1
    pf.on_message(_ev("sell", _W, M, 1.0, 1e6, 30, 3e7, newTokenBalance=0), 2000.0)
    assert pf.post_watch_mints() == [M]
    import time
    now = time.time()
    x = list(pf._post_watch.values())[0]
    x["t_out"] = now - 61 * 60
    pf.tokens[M].update(price=x["px_out"] * 2, last_t=now)
    pf.post_tick(now)
    row = pf._learn_out[0]
    assert row["depois"]["60"] == 100.0 and row["saida"].startswith("saiu cedo") and row["origem_nome"] == "cópia de trader"
    agg = aggregate([{"data": row}])
    assert agg["n"] == 1 and agg["por_saida"][0]["saiu_cedo_pct"] == 100


def test_pending_override_is_applied_once_on_load():
    from tests.test_api import UA
    from app.crypto import SecretBox
    from app.hub import PumpHub
    from app.settings import ServerConfig
    from tests.fakes import FakeREST
    import base64
    import os
    import httpx
    os.environ.setdefault("SUPABASE_URL", "https://x.supabase.co")
    os.environ["APP_ENCRYPTION_KEY"] = base64.b64encode(os.urandom(32)).decode()
    cfg = ServerConfig()
    db = FakeREST()
    db.add_user(UA, "a@x.com")
    db.tables["settings_overrides"].append({"id": 1, "user_id": UA, "settings": {"pump_bar_max_h": 20}, "motivo": "teste",
                                            "aplicado_em": None})
    hub = PumpHub(cfg, httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404))), db, SecretBox(cfg.encryption_key))
    pf = asyncio.run(hub.engine(UA))
    assert pf.cfg.pump_bar_max_h == 20 and db.tables["settings_overrides"][0]["aplicado_em"]
    assert db.tables["user_settings"][0]["settings"]["pump_bar_max_h"] == 20
