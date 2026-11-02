"""0.32.168: aba BNB · Four.Meme (etapa 1, só leitura). Sem internet: respostas do RPC falsas."""
import asyncio

from app import bnb
from tests.test_api import env  # noqa: F401  (fixture env)

TOK = "0x" + "a1" * 20
TOK_USDT = "0x" + "b2" * 20
W1, W2, W3 = "0x" + "11" * 20, "0x" + "22" * 20, "0x" + "33" * 20


def _w(v: int) -> str:
    return hex(v)[2:].rjust(64, "0")


def _a(a: str) -> str:
    return a[2:].rjust(64, "0")


def _log(side, token, wallet, amount, value, block=100, i=0, tx=None):
    """Log igual ao da rede: 8 palavras (token, conta, preço, quantidade, valor, taxa 1%, ofertas, fundos)."""
    e18 = 10 ** 18
    data = "0x" + _a(token) + _a(wallet) + _w(int(value / amount * e18)) + _w(int(amount * e18)) + _w(int(value * e18)) \
        + _w(int(value * 0.01 * e18)) + _w(0) + _w(0)
    return {"topics": [bnb.T_BUY if side == "buy" else bnb.T_SELL], "data": data, "blockNumber": hex(block),
            "logIndex": hex(i), "transactionHash": tx or f"0x{block:x}{i:04x}"}


def test_decode_real_log_from_bsc():
    """Log de verdade lido em 02/11/2026 (compra de 5,37 USDT; a taxa é 1% do valor)."""
    lg = {"topics": [bnb.T_BUY], "blockNumber": "0x7d3e5ee", "logIndex": "0x5", "transactionHash": "0xabc",
          "data": "0x000000000000000000000000a3c93bf7951782e92f89c9065a994c07a1a24444"
                  "00000000000000000000000094f4af0ac9c3244567a5d56d05ab7388ae27e65b"
                  "00000000000000000000000000000000000000000000000000001bf00bd63a19"
                  "00000000000000000000000000000000000000000000250cced4533fa0410200"
                  "0000000000000000000000000000000000000000000000004a8c6d1a648bc435"
                  "00000000000000000000000000000000000000000000000000bed8218b3ed671"
                  "0000000000000000000000000000000000000000003b9a210d209628252ac800"
                  "0000000000000000000000000000000000000000000001868f0118dbd8c7ed76"}
    t = bnb.decode(lg)
    assert t["side"] == "buy" and t["token"] == "0xa3c93bf7951782e92f89c9065a994c07a1a24444"
    assert t["wallet"] == "0x94f4af0ac9c3244567a5d56d05ab7388ae27e65b" and t["id"] == "0xabc:5"
    assert abs(t["value"] - 5.3718) < 0.001 and abs(t["fee"] / t["value"] - 0.01) < 1e-9
    assert abs(t["price"] * t["amount"] - t["value"]) / t["value"] < 0.01
    assert bnb.decode({"topics": ["0x48063b12"], "data": "0x"}) is None


def test_quote_in_usdt_is_converted_and_unknown_quote_is_left_out():
    tr = {"side": "buy", "value": 100.0, "fee": 1.0}
    assert bnb.to_bnb(tr, bnb.ZERO, 600) == 101.0
    assert abs(bnb.to_bnb(tr, "0x55d398326f99059ff775485246999027b3197955", 600) - 101 / 600) < 1e-12
    assert bnb.to_bnb({**tr, "side": "sell"}, bnb.ZERO, 600) == 99.0
    assert bnb.to_bnb(tr, "0x" + "cc" * 20, 600) is None
    assert bnb.to_bnb(tr, "0x55d398326f99059ff775485246999027b3197955", None) is None


def _tr(w, tok, side, amount, value, t):
    return {"wallet": w, "token": tok, "side": side, "amount": amount, "value": value, "fee": value * 0.01, "t": t}


def test_rank_follows_top_traders_rule():
    now = 1_000_000.0
    trades = []
    # W1: 3 tokens fechados, 2 com lucro, negociou agora
    for k, (cost, back) in enumerate([(1, 2), (1, 3), (1, 0.5)]):
        tk = f"0x{k:040x}"
        trades += [_tr(W1, tk, "buy", 100, cost, now - 3000 + k), _tr(W1, tk, "sell", 100, back, now - 60 + k)]
    # W2: lucra mais, mas parou de negociar há 2 h (offline)
    for k in range(3):
        tk = f"0x{k + 10:040x}"
        trades += [_tr(W2, tk, "buy", 100, 1, now - 9000), _tr(W2, tk, "sell", 100, 5, now - 7200)]
    # W3: comprou e não vendeu nada (acerto desconhecido)
    trades += [_tr(W3, TOK, "buy", 100, 1, now - 30)]
    cfg = {"min_trades": 2, "min_closed": 3, "min_winrate": 50, "min_wallet_usd": 0, "online_min": 10}
    r = bnb.rank(trades, now, cfg, {}, 600, {})
    by = {x["wallet"]: x for x in r["rows"]}
    assert r["rows"][0]["wallet"] == W2                                  # ordenado pelo lucro realizado
    assert by[W1]["winrate"] == 66.7 and by[W1]["eligible"] and by[W1]["online"] and by[W1]["copiaria"]
    assert by[W2]["eligible"] and not by[W2]["online"] and not by[W2]["copiaria"]
    assert not by[W3]["eligible"] and any("acerto desconhecido" in f for f in by[W3]["flags"])
    assert r["copiaria"] == [W1]
    # saldo mínimo: sem saldo conferido não é apto; saldo baixo também não
    r = bnb.rank(trades, now, {**cfg, "min_wallet_usd": 5000}, {}, 600, {W1: {"usd": 100.0}})
    by = {x["wallet"]: x for x in r["rows"]}
    assert any("carteira $100" in f for f in by[W1]["flags"]) and any("conferindo saldo" in f for f in by[W2]["flags"])
    assert r["copiaria"] == []


def test_rank_marks_bot_and_ignores_old_trades():
    now = 2_000_000.0
    trades = [_tr(W1, f"0x{k:040x}", s, 10, 1.0 if s == "buy" else 1.5, now - 3600 + k)
              for k in range(300) for s in ("buy", "sell")]
    trades.append(_tr(W2, TOK, "buy", 10, 1, now - 8 * 86400))        # fora dos 7 dias
    r = bnb.rank(trades, now, {"bot_per_day": 100, "min_wallet_usd": 0, "min_trades": 1}, {}, 600, {})
    assert [x["wallet"] for x in r["rows"]] == [W1]
    assert any(f.startswith("robô") for f in r["rows"][0]["flags"])


def test_clean_cfg_limits():
    c = bnb.clean_cfg({"days": 99, "top_n": "3", "min_winrate": "abc", "outra": 1})
    assert c["days"] == 7 and c["top_n"] == 3 and c["min_winrate"] == 50 and "outra" not in c


class _Resp:
    def __init__(self, js):
        self._js = js

    def json(self):
        return self._js


class _Http:
    """RPC falso: bloco 1000, logs da Four.Meme, moeda de cada token e reservas do par USDT/WBNB."""

    def __init__(self, logs, quotes, head=1000):
        self.logs, self.quotes, self.head, self.calls = logs, quotes, head, []

    async def post(self, url, json=None, timeout=None):
        m, p = json["method"], json["params"]
        self.calls.append(m)
        if m == "eth_blockNumber":
            return _Resp({"result": hex(self.head)})
        if m == "eth_getBlockByNumber":
            return _Resp({"result": {"timestamp": hex(1_700_000_000)}})
        if m == "eth_getLogs":
            a, b = int(p[0]["fromBlock"], 16), int(p[0]["toBlock"], 16)
            assert p[0]["address"] == bnb.TM2
            return _Resp({"result": [lg for lg in self.logs if a <= int(lg["blockNumber"], 16) <= b]})
        if m == "eth_call":
            to, data = p[0]["to"], p[0]["data"]
            if to == bnb.HELPER3:
                tok = "0x" + data[-40:]
                words = [_w(2), _a(bnb.TM2), _a(self.quotes.get(tok, bnb.ZERO))] + [_w(0)] * 9
                return _Resp({"result": "0x" + "".join(words)})
            if to == bnb.PAIR_USDT_WBNB:
                return _Resp({"result": "0x" + _w(600 * 10 ** 24) + _w(10 ** 24) + _w(0)})
        return _Resp({"error": {"message": "método não esperado"}})


def test_watch_reads_logs_converts_quote_and_saves():
    logs = [_log("buy", TOK, W1, 1000, 0.5, block=990, i=0), _log("buy", TOK_USDT, W2, 1000, 60, block=995, i=1),
            _log("sell", TOK, W1, 1000, 1.0, block=999, i=2)]
    http = _Http(logs, {TOK_USDT: "0x55d398326f99059ff775485246999027b3197955"})

    class _DB:
        def __init__(self):
            self.rows = {}

        async def insert(self, table, rows, upsert=False, on_conflict=None):
            for r in rows if isinstance(rows, list) else [rows]:
                self.rows.setdefault(table, {})[r.get("id") or r.get("k")] = r

        async def rpc(self, fn, args):
            return None

    db = _DB()
    w = bnb.BnbWatch(http, db, rpcs=["https://bsc-rpc.publicnode.com"])
    w.cursor = 980

    async def go():
        n = await w.poll()
        await w.refresh_bnb_usd()
        await w.flush()
        return n

    assert asyncio.run(go()) == 3
    assert w.cursor == 1000 and w.bnb_usd == 600
    st = w.state(1_700_000_000)
    rec = {(r["wallet"], r["side"]): r for r in st["recentes"]}
    assert rec[(W2, "buy")]["moeda"] == "USDT" and abs(rec[(W2, "buy")]["bnb"] - 60.6 / 600) < 1e-6
    assert rec[(W1, "buy")]["bnb"] == 0.505
    assert len(db.rows["bnb_fm_trades"]) == 3 and db.rows["bnb_state"]["cursor"]["v"]["block"] == 1000
    # a mesma volta de novo não duplica
    w.cursor = 980
    assert asyncio.run(w.poll()) == 0
    assert st["ranking"]["carteiras"] == 2


def test_bnb_route_is_admin_only_and_isolated(env):
    from tests.test_api import UA, UB, tok
    c, hub = env["c"], env["hub"]
    assert c.get("/api/pump/bnb").status_code == 401
    assert c.get("/api/pump/bnb", headers=tok(UB, "b@x.com")).status_code == 403
    assert c.get("/api/pump/bnb", headers=tok(UA)).json()["ligado"] is False          # sem a leitura ligada
    hub.bnb = bnb.BnbWatch(_Http([], {}), None)
    r = c.get("/api/pump/bnb", headers=tok(UA)).json()
    assert r["ligado"] and r["ranking"]["rows"] == [] and r["cfg"]["min_trades"] == 20
    r = c.post("/api/pump/bnb/cfg", json={"min_trades": 5}, headers=tok(UA)).json()
    assert r["ok"] and r["cfg"]["min_trades"] == 5
    assert c.post("/api/pump/bnb/cfg", json={"min_trades": 5}, headers=tok(UB, "b@x.com")).status_code == 403
    assert any(a["acao"] == "BNB: regra do ranking mudada" for a in env["db"].tables["audit_log"])
