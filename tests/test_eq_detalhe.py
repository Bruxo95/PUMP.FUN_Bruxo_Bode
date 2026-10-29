"""0.32.70: acompanhar uma carteira do Copiar igual (monitor, atividade, decisões, posições)."""
import time
from datetime import datetime, timezone

from app.hub import PumpHub
from tests.test_copiar_igual import _eq
from tests.test_pump import _W, _ev

M = "Acom".ljust(40, "1") + "pump"


class _Mon:
    def union_followed(self):
        return {_W}


def test_eq_detail_shows_listening_events_and_positions(tmp_path):
    pf = _eq(tmp_path)
    pf.on_message(_ev("buy", _W, M, 0.1, 1e5, 30, 3e7), time.time())
    h = PumpHub.__new__(PumpHub)
    h.monitor, h.market = _Mon(), pf.market
    pf.market.rpc_status["ws"] = True
    r = h.eq_detail(pf, _W)
    assert r["ouvindo"] and r["monitor_ok"] and r["modo"] == "sim"
    assert r["abertas"] and r["abertas"][0]["mint"] == M
    assert any(e["mint"] == M for e in r["eventos"])
