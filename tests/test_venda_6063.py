"""0.32.182 (STARMIND, 04/11): venda REAL recusada com 6063 pela PumpPortal tem que tentar a PumpSwap e a Jupiter, não repetir
a mesma rota com mais slippage. Carteira falsa, sem internet."""
import asyncio
import types

from app.pumpfun import PumpReal

E6063 = "transação recusada pela simulação: {'InstructionError': [3, {'Custom': 6063}]}"
MINT = "B2hrd6M7z4xaY4Cxe6eYBSedmYxDhyFDaEAaLyZhpump"


def _real(jup_ok=True):
    r = PumpReal.__new__(PumpReal)
    r.wallet = types.SimpleNamespace(keypair=object(), address="W")
    r.cfg = types.SimpleNamespace(pump_real_slippage_pct=15)
    st = {"tok": 1000.0, "sol": 1.0, "calls": []}

    async def balances(mint):
        return st["sol"], st["tok"]

    async def tx(body):
        st["calls"].append(("pp", body["pool"], body["slippage"]))
        return {"status": "falhou", "reason": E6063}

    async def jup(inp, out, amount, slip_bps):
        st["calls"].append(("jup", slip_bps))
        if jup_ok:
            st["tok"], st["sol"] = 0.0, 1.27
            return {"status": "confirmada", "ok": True, "signature": "sigJ"}
        return {"status": "falhou", "reason": "sem rota"}

    async def raw_tok(mint):
        return 1000 * 10 ** 6, 6

    async def sol_change(sig):
        return 0.27
    r.balances, r._tx, r._jup, r._raw_tok, r._sol_change = balances, tx, jup, raw_tok, sol_change
    return r, st


def test_6063_on_sell_goes_to_pumpswap_then_jupiter():
    r, st = _real()
    res = asyncio.run(r.sell(MINT, 1.0))
    assert res["ok"] and res["signature"] == "sigJ" and abs(res["sol_received"] - 0.27) < 1e-9
    assert st["calls"] == [("pp", "auto", 15.0), ("pp", "pump-amm", 30.0), ("jup", 1000)]


def test_6063_everywhere_stops_after_jupiter_without_repeating_auto():
    r, st = _real(jup_ok=False)
    res = asyncio.run(r.sell(MINT, 1.0))
    assert not res["ok"]
    assert st["calls"] == [("pp", "auto", 15.0), ("pp", "pump-amm", 30.0), ("jup", 1000), ("jup", 2500)]
    assert "Jupiter 25%" in res["reason"]
