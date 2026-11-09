"""0.32.270 (dono: "o Supabase continua enchendo"): a BNB fica 3 dias no Supabase; ao subir, o resto da janela do ranking
vem do arquivo (Postgres da VPS)."""
import asyncio
import time

from app import arquivo, bnb


def _tr(i, t):
    return {"id": f"t{i}", "tx": f"x{i}", "block": i, "t": t, "token": "0x" + "a" * 40, "wallet": "0x" + "b" * 40,
            "side": "buy", "price": 1.0, "amount": 1.0, "value": 0.1, "fee": 0, "quote": None, "venue": "fourmeme"}


class _DB:
    def __init__(self, rows):
        self.rows = rows

    async def select(self, table, eq=None, order=None, limit=None, offset=0, gte=None, lte=None, **k):
        if table != "bnb_fm_trades":
            return []
        r = [x for x in self.rows if not gte or x["t"] >= gte["t"]]
        return r[offset:offset + (limit or len(r))]


class _Arq:
    def __init__(self, rows):
        self.rows = rows

    async def pages(self, tabela, since=None, until=None, page=5000):
        yield [x for x in self.rows if (since is None or x["t"] >= since) and (until is None or x["t"] <= until)]


def test_bnb_fica_3_dias_no_supabase():
    assert next(s for s in arquivo.SPECS if s["tabela"] == "bnb_fm_trades")["dias"] == 3


def test_subida_carrega_os_dias_antigos_do_arquivo():
    now = time.time()
    velhos = [_tr(i, now - (5 - i * 0.1) * 86400) for i in range(5)]           # 5 a 4,6 dias atrás: só no arquivo
    novos = [_tr(100 + i, now - (1 + i * 0.1) * 86400) for i in range(4)]      # últimos dias: no Supabase
    w = bnb.BnbWatch(None, _DB(novos), rpcs=["https://x"])
    w.arquivo = _Arq(velhos)
    w.load_books = lambda: asyncio.sleep(0)
    asyncio.run(w.load())
    assert {t["id"] for t in w.trades} == {x["id"] for x in velhos + novos}
    assert w.stat["do_arquivo"] == 5
