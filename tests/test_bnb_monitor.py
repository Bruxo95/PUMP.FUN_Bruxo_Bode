"""0.32.183: monitor da BNB parado em 04/11 sem erro. O publicnode recusa (HTTP 403) eth_getLogs com mais de 10 endereços e o
blockrazor responde "exceed max addresses"; a leitura da PancakeSwap ia com até 150 pares de uma vez, encolhia o trecho da
curva e a volta da leitura não terminava. Sem internet."""
import asyncio

from app import bnb, bnbpancake as pc

A, B = "https://a.test", "https://b.test"


class _R:
    def __init__(self, js):
        self._js = js

    def json(self):
        return self._js


class _Http:
    def __init__(self):
        self.calls = []

    async def post(self, url, json=None, timeout=None):
        m, p = json["method"], json["params"]
        if m == "eth_getLogs":
            addr = p[0].get("address")
            n = len(addr) if isinstance(addr, list) else 1
            self.calls.append((url, n))
            if n > 10:                                              # limite medido no publicnode em 04/11
                if url == A:
                    raise RuntimeError("HTTP 403 Forbidden")
                return _R({"error": {"message": "exceed max addresses or topics per search position"}})
            return _R({"result": []})
        return _R({"result": "0x0"})


def _watch(npairs):
    h = _Http()
    w = bnb.BnbWatch(h, None, rpcs=[A, B])
    for i in range(npairs):
        tok, pair = "0x" + f"{i:040x}", "0x" + f"{i + 1000:040x}"
        w.pairs[tok] = {**pc.pair_info(tok, bnb.ZERO, pair), "t": i}
    return w, h


def test_pancake_reads_in_batches_of_10_and_never_touches_the_curve_span():
    w, h = _watch(25)
    span = dict(w.span)
    out = asyncio.run(w._pancake_logs(100, 500))
    assert out == [] and w.pstat["erros"] == 0
    assert [n for _, n in h.calls] == [10, 10, 5]
    assert w.span == span and w.rpc_i == 0


def test_refused_side_query_pauses_pancake_but_not_the_curve(monkeypatch):
    monkeypatch.setattr(pc, "ADDR_MAX", 50)                     # força o lote grande que o RPC recusa
    w, h = _watch(25)
    span = dict(w.span)
    asyncio.run(w._pancake_logs(100, 500))
    assert w.pstat["erros"] == 1 and w._pk_off_until > 0
    assert w.span == span and w.rpc_i == 0                      # antes: o "exceed" encolhia o trecho da curva
    h.calls.clear()
    asyncio.run(w._pancake_logs(100, 500))
    assert h.calls == []                                         # pausada: nenhuma consulta nova


def test_a_stuck_step_becomes_an_error_and_the_loop_goes_on(monkeypatch):
    w, _ = _watch(0)
    monkeypatch.setattr(bnb, "STEP_MAX_S", 0.05)
    monkeypatch.setattr(bnb, "POLL_S", 0.01)
    n = {"voltas": 0}

    async def nada():
        return None

    async def trava():
        await asyncio.sleep(3600)

    async def conta():
        n["voltas"] += 1
    w.load, w.poll, w.refresh_bnb_usd, w.real_tick = nada, trava, nada, conta
    w.hist.run = nada

    async def go():
        t = asyncio.create_task(w.run())
        await asyncio.sleep(0.4)
        t.cancel()
    asyncio.run(go())
    assert n["voltas"] >= 2 and w.stat["erros"] >= 2
    assert "leitura: passou de" in w.stat["ultimo_erro"] and w.state()["status"]["volta_t"]
