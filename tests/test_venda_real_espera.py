"""0.32.62 (PEPE do Bruxo, 29/10 20:55): venda REAL que falha não pode ser reenviada a cada 3 s. Carteira falsa."""
import asyncio

from tests.test_espelho_real import A, FakeReal, _pf


class BrokenReal(FakeReal):
    async def sell(self, mint, frac, other=False):
        self.calls.append(("sell", mint, frac))
        raise ValueError("Expecting value: line 1 column 1 (char 0)")


def _real_pos(pf):
    pf.tokens[A] = {"price": 1e-6, "symbol": "ESP", "mcap_sol": 40.0}
    pf.manual_buy(A, target="real")
    _k, it = pf._rq.get_nowait()
    asyncio.run(pf._real_buy(it))
    return [p for p in pf.positions() if p.get("real")][0]


def test_failed_real_sell_waits_before_retrying(tmp_path):
    pf = _pf(tmp_path)
    p = _real_pos(pf)
    pf.real = BrokenReal()
    assert pf._sell(p, 1.0, 2e-6, "stop móvel", 0.0)                  # 1ª vez: vai para a fila
    _k, it = pf._rq.get_nowait()
    asyncio.run(pf._real_run("sell", it, asyncio.Lock(), asyncio.Semaphore(1)))
    p = [x for x in pf.positions() if x.get("real")][0]                   # positions() devolve cópias
    assert not p["selling"] and p["sell_fails"] == 1 and p["sell_retry_at"] > 0
    assert pf._sell(p, 1.0, 2e-6, "stop móvel", 0.0) is None          # dentro da espera: não reenvia nem avisa
    assert pf._rq.empty()
    assert pf._sell(p, 1.0, 2e-6, "fechada por você", 0.0)            # você na tela: não espera
    p["sell_retry_at"] = 0
    p["selling"] = False
    while not pf._rq.empty():
        pf._rq.get_nowait()
    assert pf._sell(p, 1.0, 2e-6, "stop móvel", 0.0)                  # passou a espera: tenta de novo
