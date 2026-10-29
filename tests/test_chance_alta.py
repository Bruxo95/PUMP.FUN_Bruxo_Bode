"""0.32.64: modal "Chance alta" em Logs — um token por linha, com decisão, variação, sombra de 15 min e resultado."""
import asyncio
import time
from datetime import datetime, timezone

from app.hub import PumpHub


class _DB:
    def __init__(self, rows):
        self.rows = rows

    async def select(self, table, where=None, **kw):
        return self.rows if table == "explore_cycles" else []


class _PF:
    user_id = "u1"

    def __init__(self, funnel, trades):
        self._ex_funnel, self._t = funnel, trades

    def trades(self, n):
        return self._t

    def positions(self):
        return []


class _M:
    def __init__(self, tokens):
        self.tokens = tokens


def test_chance_alta_one_row_per_token():
    now = time.time()
    em = datetime.fromtimestamp(now - 600, timezone.utc).isoformat()
    cyc = {"chance_alta_barrados": [{"symbol": "AAA", "mint": "A", "motivo": "pressão 40% abaixo de 60%"}]}
    h = PumpHub.__new__(PumpHub)
    h.db = _DB([{"em": em, "data": cyc}, {"em": em, "data": cyc}])     # o mesmo token em 2 listas = 1 linha
    h.market = _M({"A": {"price": 2e-6}, "C": {"price": 1e-6}})
    h.__dict__["shadows"] = {"A": {"px0": 1e-6, "pico": 120.0, "ret": 60.0, "info": {"curve_pct": 70, "holders": 150, "age_min": 12}}}
    funnel = {"C": {"t": now - 100, "first_t": now - 300, "symbol": "CCC", "chance": "chance alta", "why": None, "entrou": True, "px0": 1e-6},
              "D": {"t": now - 100, "symbol": "DDD", "chance": "fraco", "why": "x", "entrou": False}}
    trades = [{"mint": "C", "origem": "explorar", "pnl_pct": 25.0, "pnl_sol": 0.0125, "reason": "alvo", "hold_s": 300}]
    r = asyncio.run(h.chance_alta(_PF(funnel, trades), 24, now))
    by = {x["mint"]: x for x in r["tokens"]}
    assert set(by) == {"A", "C"} and r["resumo"]["tokens"] == 2 and r["resumo"]["entrou"] == 1
    assert by["A"]["listas"] == 2 and by["A"]["agora_pct"] == 100.0 and by["A"]["pico15_pct"] == 120.0 and by["A"]["curva_pct"] == 70
    assert not by["A"]["entrou"] and by["A"]["motivo"].startswith("pressão")
    assert by["C"]["entrou"] and by["C"]["op"]["pnl_pct"] == 25.0 and by["C"]["visto_s"] == 200
    assert r["resumo"]["ganhariam_15"] == 1 and r["resumo"]["pico_50"] == 1
