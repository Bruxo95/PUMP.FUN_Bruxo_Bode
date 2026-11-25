"""0.32.449 (dono, Zeus 25/11): a compra REAL gastou mais SOL que o configurado (0,126 com 0,1) e o excesso aparecia como
"taxa de rede" (0,025 SOL), deixando "Taxas pagas" e "Ganho geral" errados. O líquido (diferença de SOL) continua o mesmo."""
import asyncio

from tests.test_espelho_real import A, FakeReal, _pf
from tests.test_fechar_conta import FakeRealClose


class GastaMais(FakeRealClose):
    async def buy(self, mint, amt, other=False):
        self.calls.append(("buy", mint, amt))
        return {"ok": True, "signature": "B", "sol_spent": amt * 1.26, "tokens": 1_000_000.0}


def test_excesso_da_compra_nao_vira_taxa(tmp_path):
    pf = _pf(tmp_path)
    pf.real = GastaMais(back=0.0015)
    pf.tokens[A] = {"price": 1e-6, "symbol": "ESP", "mcap_sol": 40.0}
    pf.manual_buy(A, target="real", amt_sol=0.01)
    asyncio.run(pf._real_buy(pf._rq.get_nowait()[1]))
    p = [x for x in pf.positions() if x.get("real")][0]
    prio = pf._fee_rates(A, True)["prio"]
    assert abs(p["fee_parts"]["network"] - prio) < 1e-12        # só a taxa da transação, não os 0,0026 a mais
    pf._real_sell(p, 1.0, "teste")
    asyncio.run(pf._real_do_sell(pf._rq.get_nowait()[1]))
    tr = [t for t in pf.trades() if t.get("real")][0]
    assert abs(tr["fee_parts"]["network"] - prio * 2) < 1e-6      # compra + 1 venda
    assert abs(tr["fees_sol"] - sum(tr["fee_parts"].values())) < 1e-5
    assert abs(tr["gross_sol"] - (tr["pnl_sol"] + tr["fees_sol"])) < 1e-5
    assert abs(tr["pnl_sol"] - (tr["sol_out"] - tr["sol_in"])) < 1e-6   # líquido = diferença real de SOL, igual antes
