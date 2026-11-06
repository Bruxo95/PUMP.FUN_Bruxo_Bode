"""Dormant: comprar em exchange centralizada pela API (0.32.247, pedido do dono em 06/11/2026). Isolado em /dormant. Só compra; nunca saca.

Não há código de saque aqui, e a chave é conferida ANTES de ser guardada: nas exchanges que dizem pela API se a chave pode sacar
(Binance, Bybit, OKX, KuCoin), chave com saque ligado é recusada. A MEXC não mostra isso por chave: entra só com a confirmação do dono.
Conectadas só estas 5 porque são aquelas cuja documentação consegui ler em 06/11/2026; Gate, Bitget e outras ficam para depois, sem adivinhar.

Nunca usa ordem a mercado. Em moeda pequena o livro é fino (SCCP na MEXC: profundidade $0, spread de 18,7% na CoinGecko) e a mercado o preço dispara
sem limite. Aqui é ordem limitada que executa na hora ou cancela (IOC), com preço máximo calculado pelo livro e pela folga do dono.
A CoinGecko pode listar par antigo (SCCP/USDT na MEXC: "stale", e a API da MEXC responde Invalid symbol): quem decide se existe é a própria exchange.
A chave fica no mesmo cofre das carteiras (dormant_vault, com a senha de compra).
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import re
import time
import urllib.parse
import uuid
from datetime import datetime, timezone
from decimal import ROUND_DOWN, Decimal

from . import dormant_vault as vault
from .crypto import CryptoError  # noqa: F401
from .dormant_buy import PRECO_AVISO, PRECO_BLOQ, BuyError, _iso

log = logging.getLogger("pump.dormant.compra")

EXCHANGES = {
    "binance": {"nome": "Binance", "cg": "binance", "frase": False, "confere_saque": True, "doc": "https://www.binance.com/en/my/settings/api-management"},
    "bybit": {"nome": "Bybit", "cg": "bybit_spot", "frase": False, "confere_saque": True, "doc": "https://www.bybit.com/app/user/api-management"},
    "okx": {"nome": "OKX", "cg": "okex", "frase": True, "confere_saque": True, "doc": "https://www.okx.com/account/my-api"},
    "kucoin": {"nome": "KuCoin", "cg": "kucoin", "frase": True, "confere_saque": True, "doc": "https://www.kucoin.com/account/api"},
    "mexc": {"nome": "MEXC", "cg": "mxc", "frase": False, "confere_saque": False, "doc": "https://www.mexc.com/user/openapi"},
}
BY_CG = {v["cg"]: k for k, v in EXCHANGES.items()}
QUOTE = "USDT"
BASE_RE = re.compile(r"^[A-Z0-9]{1,20}$")
OFFERS_S = 300
ORDEM_TENTATIVAS, ORDEM_PASSO = 5, 1


class ExError(BuyError):
    pass


def d(v) -> Decimal:
    return Decimal(str(v))


def floor_to(v: Decimal, step: Decimal) -> Decimal:
    return (v / step).to_integral_value(rounding=ROUND_DOWN) * step


def plain(v: Decimal) -> str:
    s = format(v.normalize(), "f")
    return s


def hmac_hex(secret: str, msg: str, algo=hashlib.sha256) -> str:
    return hmac.new(secret.encode(), msg.encode(), algo).hexdigest()


def hmac_b64(secret: str, msg: str) -> str:
    return base64.b64encode(hmac.new(secret.encode(), msg.encode(), hashlib.sha256).digest()).decode()


def binance_query(params: dict, secret: str) -> str:
    q = urllib.parse.urlencode(params)
    return q + "&signature=" + hmac_hex(secret, q)


def bybit_sign(ts: str, key: str, recv: str, payload: str, secret: str) -> str:
    return hmac_hex(secret, ts + key + recv + payload)


def walk_book(asks: list, usd: Decimal, cap: Decimal) -> dict:
    """Quanto dá para comprar com usd pelo livro, sem passar do preço máximo. asks = [(preço, quantidade)] do mais barato para o mais caro."""
    left, qty, spent, worst = usd, Decimal(0), Decimal(0), None
    for p, q in asks:
        if p > cap or left <= 0:
            break
        take = min(q, left / p)
        qty += take
        cost = take * p
        spent += cost
        left -= cost
        worst = p
    return {"qty": qty, "gasto": spent, "ultimo": worst, "sobra": left}


class Conn:
    """Uma exchange. Parte pública sem chave; parte privada com keys = {"key", "secret", "frase"}. Nenhum método de saque existe."""
    def __init__(self, http, ex: str):
        self.http, self.ex = http, ex

    async def _send(self, method: str, url: str, headers: dict | None = None, content: str | None = None) -> dict:
        try:
            r = await self.http.request(method, url, headers={"User-Agent": "pump-fun-copy/1.0", **(headers or {})}, content=content, timeout=15)
        except Exception as e:
            raise ExError(f"{EXCHANGES[self.ex]['nome']} não respondeu ({type(e).__name__})") from None
        if r.status_code in (403, 451):
            raise ExError(f"{EXCHANGES[self.ex]['nome']} bloqueou o acesso a partir deste servidor (HTTP {r.status_code}): pode ser o país do servidor")
        try:
            js = r.json()
        except ValueError:
            raise ExError(f"{EXCHANGES[self.ex]['nome']} respondeu sem dados (HTTP {r.status_code})") from None
        js = js if isinstance(js, dict) else {"lista": js}
        js["_http"] = r.status_code
        return js

    def _err(self, js: dict, keys: dict | None = None) -> None:
        ex = self.ex
        bad = None
        if ex in ("binance", "mexc"):
            if js["_http"] >= 300 or (isinstance(js.get("code"), int) and js.get("code") < 0):
                bad = js.get("msg") or f"HTTP {js['_http']}"
        elif ex == "bybit":
            if js.get("retCode") not in (0, None):
                bad = js.get("retMsg")
        elif ex == "okx":
            if str(js.get("code")) != "0":
                bad = js.get("msg") or ((js.get("data") or [{}])[0].get("sMsg"))
            elif (js.get("data") or [{}])[0].get("sCode") not in (None, "0"):
                bad = js["data"][0].get("sMsg")
        elif ex == "kucoin":
            if str(js.get("code")) != "200000":
                bad = js.get("msg")
        if bad is not None:
            txt = str(bad)[:160]
            for k in ((keys or {}).get("key"), (keys or {}).get("secret"), (keys or {}).get("frase")):
                if k:
                    txt = txt.replace(k, "***")
            raise ExError(f"{EXCHANGES[ex]['nome']}: {txt}")

    # ------------------------------------------------------------------ público
    def symbol(self, base: str) -> str:
        return f"{base}-{QUOTE}" if self.ex in ("okx", "kucoin") else f"{base}{QUOTE}"

    async def rules(self, base: str) -> dict | None:
        """Regras do par na própria exchange; None = a exchange não negocia este par agora."""
        s, ex = self.symbol(base), self.ex
        try:
            if ex in ("binance", "mexc"):
                host = "https://api.binance.com" if ex == "binance" else "https://api.mexc.com"
                js = await self._send("GET", f"{host}/api/v3/exchangeInfo?symbol={s}")
                x = (js.get("symbols") or [None])[0]
                if not x:
                    return None
                if ex == "binance":
                    if x.get("status") != "TRADING":
                        return None
                    f = {a["filterType"]: a for a in x.get("filters") or []}
                    return {"tick": d(f["PRICE_FILTER"]["tickSize"]), "step": d(f["LOT_SIZE"]["stepSize"]), "min_qty": d(f["LOT_SIZE"]["minQty"]),
                            "min_usd": d((f.get("NOTIONAL") or f.get("MIN_NOTIONAL") or {}).get("minNotional") or 0)}
                if str(x.get("status")) not in ("1", "ENABLED") or x.get("isSpotTradingAllowed") is False:
                    return None
                return {"tick": Decimal(1).scaleb(-int(x.get("quotePrecision") or x.get("quoteAssetPrecision"))), "step": Decimal(1).scaleb(-int(x["baseAssetPrecision"])),
                        "min_qty": d(x.get("baseSizePrecision") or 0), "min_usd": d(x.get("quoteAmountPrecision") or 0)}
            if ex == "bybit":
                js = await self._send("GET", f"https://api.bybit.com/v5/market/instruments-info?category=spot&symbol={s}")
                x = ((js.get("result") or {}).get("list") or [None])[0]
                if not x or x.get("status") != "Trading":
                    return None
                L = x["lotSizeFilter"]
                return {"tick": d(x["priceFilter"]["tickSize"]), "step": d(L["basePrecision"]), "min_qty": d(L["minOrderQty"]), "min_usd": d(L.get("minOrderAmt") or 0)}
            if ex == "okx":
                js = await self._send("GET", f"https://www.okx.com/api/v5/public/instruments?instType=SPOT&instId={s}")
                x = (js.get("data") or [None])[0]
                if not x or x.get("state") != "live":
                    return None
                return {"tick": d(x["tickSz"]), "step": d(x["lotSz"]), "min_qty": d(x["minSz"]), "min_usd": Decimal(0)}
            js = await self._send("GET", f"https://api.kucoin.com/api/v2/symbols/{s}")
            x = js.get("data")
            if not x or not x.get("enableTrading"):
                return None
            return {"tick": d(x["priceIncrement"]), "step": d(x["baseIncrement"]), "min_qty": d(x["baseMinSize"]), "min_usd": d(x.get("minFunds") or 0)}
        except (KeyError, TypeError, ValueError, ArithmeticError, IndexError):
            raise ExError(f"{EXCHANGES[ex]['nome']}: não entendi as regras do par") from None

    async def asks(self, base: str) -> list[tuple[Decimal, Decimal]]:
        s, ex = self.symbol(base), self.ex
        if ex in ("binance", "mexc"):
            host = "https://api.binance.com" if ex == "binance" else "https://api.mexc.com"
            js = await self._send("GET", f"{host}/api/v3/depth?symbol={s}&limit=50")
            raw = js.get("asks")
        elif ex == "bybit":
            js = await self._send("GET", f"https://api.bybit.com/v5/market/orderbook?category=spot&symbol={s}&limit=50")
            raw = (js.get("result") or {}).get("a")
        elif ex == "okx":
            js = await self._send("GET", f"https://www.okx.com/api/v5/market/books?instId={s}&sz=50")
            raw = ((js.get("data") or [{}])[0]).get("asks")
        else:
            js = await self._send("GET", f"https://api.kucoin.com/api/v1/market/orderbook/level2_20?symbol={s}")
            raw = (js.get("data") or {}).get("asks")
        return sorted(((d(a[0]), d(a[1])) for a in raw or []), key=lambda x: x[0])

    # ------------------------------------------------------------------ privado
    async def _private(self, method: str, path: str, keys: dict, query: dict | None = None, body: dict | None = None) -> dict:
        ex = self.ex
        if ex in ("binance", "mexc"):
            host = "https://api.binance.com" if ex == "binance" else "https://api.mexc.com"
            q = binance_query({**(query or {}), **(body or {}), "recvWindow": 5000, "timestamp": int(time.time() * 1000)}, keys["secret"])
            js = await self._send(method, f"{host}{path}?{q}", {"X-MBX-APIKEY" if ex == "binance" else "X-MEXC-APIKEY": keys["key"], "Content-Type": "application/json"})
        else:
            qs = urllib.parse.urlencode(query or {})
            full = path + ("?" + qs if qs else "")
            txt = json.dumps(body, separators=(",", ":")) if body is not None else ""
            if ex == "bybit":
                ts, recv = str(int(time.time() * 1000)), "5000"
                h = {"X-BAPI-API-KEY": keys["key"], "X-BAPI-TIMESTAMP": ts, "X-BAPI-RECV-WINDOW": recv, "X-BAPI-SIGN": bybit_sign(ts, keys["key"], recv, txt if body is not None else qs, keys["secret"])}
                url = "https://api.bybit.com" + full
            elif ex == "okx":
                ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(time.time() * 1000) % 1000:03d}Z"
                h = {"OK-ACCESS-KEY": keys["key"], "OK-ACCESS-TIMESTAMP": ts, "OK-ACCESS-PASSPHRASE": keys.get("frase") or "", "OK-ACCESS-SIGN": hmac_b64(keys["secret"], ts + method + full + txt)}
                url = "https://www.okx.com" + full
            else:
                ts = str(int(time.time() * 1000))
                h = {"KC-API-KEY": keys["key"], "KC-API-TIMESTAMP": ts, "KC-API-KEY-VERSION": "3", "KC-API-SIGN": hmac_b64(keys["secret"], ts + method + full + txt),
                     "KC-API-PASSPHRASE": hmac_b64(keys["secret"], keys.get("frase") or "")}
                url = "https://api.kucoin.com" + full
            h["Content-Type"] = "application/json"
            js = await self._send(method, url, h, txt if body is not None else None)
        self._err(js, keys)
        return js

    async def check_key(self, keys: dict) -> dict:
        """{"saque": True/False/None (None = a exchange não diz), "trade": bool, "ip": True/False/None}. Nada é guardado se isto falhar."""
        ex = self.ex
        if ex == "binance":
            j = await self._private("GET", "/sapi/v1/account/apiRestrictions", keys)
            return {"saque": bool(j.get("enableWithdrawals")), "trade": bool(j.get("enableSpotAndMarginTrading")), "ip": bool(j.get("ipRestrict"))}
        if ex == "bybit":
            r = (await self._private("GET", "/v5/user/query-api", keys)).get("result") or {}
            p = r.get("permissions") or {}
            ips = [i for i in r.get("ips") or [] if i and i != "*"]
            return {"saque": "Withdraw" in (p.get("Wallet") or []), "trade": "SpotTrade" in (p.get("Spot") or []) and int(r.get("readOnly") or 0) == 0, "ip": bool(ips)}
        if ex == "okx":
            c = ((await self._private("GET", "/api/v5/account/config", keys)).get("data") or [{}])[0]
            perm = str(c.get("perm") or "")
            return {"saque": "withdraw" in perm, "trade": "trade" in perm, "ip": bool(c.get("ip"))}
        if ex == "kucoin":
            c = (await self._private("GET", "/api/v1/user/api-key", keys)).get("data") or {}
            perm = str(c.get("permission") or "")
            return {"saque": "Withdrawal" in perm, "trade": "Spot" in perm, "ip": None}
        c = await self._private("GET", "/api/v3/account", keys)
        return {"saque": None, "trade": bool(c.get("canTrade")), "ip": None}

    async def balance(self, keys: dict) -> Decimal:
        ex = self.ex
        if ex in ("binance", "mexc"):
            j = await self._private("GET", "/api/v3/account", keys)
            return next((d(b.get("free") or 0) for b in j.get("balances") or [] if b.get("asset") == QUOTE), Decimal(0))
        if ex == "bybit":
            j = await self._private("GET", "/v5/account/wallet-balance", keys, {"accountType": "UNIFIED", "coin": QUOTE})
            coins = (((j.get("result") or {}).get("list") or [{}])[0]).get("coin") or []
            return next((d(c.get("walletBalance") or 0) - d(c.get("locked") or 0) for c in coins if c.get("coin") == QUOTE), Decimal(0))
        if ex == "okx":
            j = await self._private("GET", "/api/v5/account/balance", keys, {"ccy": QUOTE})
            det = ((j.get("data") or [{}])[0]).get("details") or []
            return next((d(c.get("availBal") or 0) for c in det if c.get("ccy") == QUOTE), Decimal(0))
        j = await self._private("GET", "/api/v1/accounts", keys, {"currency": QUOTE, "type": "trade"})
        return sum((d(a.get("available") or 0) for a in j.get("data") or []), Decimal(0))

    async def buy_ioc(self, keys: dict, base: str, price: Decimal, qty: Decimal, cid: str) -> str:
        """Ordem limitada que executa na hora ou cancela. Devolve o id da ordem."""
        s, ex, P, Q = self.symbol(base), self.ex, plain(price), plain(qty)
        if ex == "binance":
            j = await self._private("POST", "/api/v3/order", keys, body={"symbol": s, "side": "BUY", "type": "LIMIT", "timeInForce": "IOC", "quantity": Q, "price": P, "newClientOrderId": cid})
            return str(j["orderId"])
        if ex == "mexc":
            j = await self._private("POST", "/api/v3/order", keys, body={"symbol": s, "side": "BUY", "type": "IMMEDIATE_OR_CANCEL", "quantity": Q, "price": P, "newClientOrderId": cid})
            return str(j["orderId"])
        if ex == "bybit":
            j = await self._private("POST", "/v5/order/create", keys, body={"category": "spot", "symbol": s, "side": "Buy", "orderType": "Limit", "qty": Q, "price": P, "timeInForce": "IOC", "orderLinkId": cid})
            return str(j["result"]["orderId"])
        if ex == "okx":
            j = await self._private("POST", "/api/v5/trade/order", keys, body={"instId": s, "tdMode": "cash", "side": "buy", "ordType": "ioc", "px": P, "sz": Q, "clOrdId": cid})
            return str(j["data"][0]["ordId"])
        j = await self._private("POST", "/api/v1/hf/orders", keys, body={"type": "limit", "symbol": s, "side": "buy", "price": P, "size": Q, "timeInForce": "IOC", "clientOid": cid})
        return str(j["data"]["orderId"])

    async def order_fill(self, keys: dict, base: str, oid: str) -> tuple[Decimal, Decimal, bool]:
        """(quantidade executada, dólar gasto, ordem já terminou)."""
        s, ex = self.symbol(base), self.ex
        if ex in ("binance", "mexc"):
            j = await self._private("GET", "/api/v3/order", keys, {"symbol": s, "orderId": oid})
            return d(j.get("executedQty") or 0), d(j.get("cummulativeQuoteQty") or 0), str(j.get("status")) not in ("NEW", "PARTIALLY_FILLED", "PENDING_NEW")
        if ex == "bybit":
            x = (((await self._private("GET", "/v5/order/realtime", keys, {"category": "spot", "orderId": oid})).get("result") or {}).get("list") or [{}])[0]
            return d(x.get("cumExecQty") or 0), d(x.get("cumExecValue") or 0), str(x.get("orderStatus")) not in ("New", "PartiallyFilled", "Created", "None")
        if ex == "okx":
            x = ((await self._private("GET", "/api/v5/trade/order", keys, {"instId": s, "ordId": oid})).get("data") or [{}])[0]
            q = d(x.get("accFillSz") or 0)
            return q, q * d(x.get("avgPx") or 0), str(x.get("state")) in ("filled", "canceled", "mmp_canceled")
        x = (await self._private("GET", f"/api/v1/hf/orders/{oid}", keys, {"symbol": s})).get("data") or {}
        return d(x.get("dealSize") or 0), d(x.get("dealFunds") or 0), not x.get("active", False)


class CexBuyer:
    def __init__(self, buyer):
        self.b = buyer

    def conn(self, ex: str) -> Conn:
        if ex not in EXCHANGES:
            raise BuyError("exchange inválida")
        return Conn(self.b.http, ex)

    # ------------------------------------------------------------------ onde a moeda é vendida
    async def offers(self, key: str) -> dict:
        w = self.b.watch
        m = next((x for x in w.todas() if x["cmc"] == key), None)
        if m is None:
            raise BuyError("esta moeda não está na lista")
        cid = w.pick.get(key)
        if not cid:
            raise BuyError("esta moeda não foi achada na CoinGecko")
        cache = self.b.__dict__.setdefault("_cex_off", {})
        hit = cache.get(cid)
        if hit and time.time() - hit[0] < OFFERS_S:
            lst = hit[1]
        else:
            try:
                r = await w.get(f"/coins/{cid}/tickers", {"depth": "true", "order": "volume_desc"})
            except Exception as e:
                raise BuyError("a CoinGecko não respondeu agora: " + str(e)[:100]) from None
            lst = []
            for t in (r or {}).get("tickers") or []:
                mk = t.get("market") or {}
                if mk.get("identifier") in (None, "") or not t.get("base") or not t.get("target"):
                    continue
                url = t.get("trade_url") or ""
                lst.append({"cg": mk["identifier"], "nome": mk.get("name"), "base": str(t["base"]).upper(), "alvo": str(t["target"]).upper(), "px": (t.get("converted_last") or {}).get("usd"),
                            "vol": (t.get("converted_volume") or {}).get("usd"), "spread": t.get("bid_ask_spread_percentage"), "antigo": bool(t.get("is_stale")), "anomalia": bool(t.get("is_anomaly")),
                            "url": url if url.startswith("https://") else None, "dex": len(str(t["base"])) >= 32})
            cache[cid] = (time.time(), lst)
            if len(cache) > 300:
                cache.clear()
        it = w.item(m)
        return {"moeda": {"key": key, "nome": it.get("nome"), "simbolo": it.get("simbolo"), "preco": it.get("preco")},
                "lista": [{**x, "ex": BY_CG.get(x["cg"]) if x["alvo"] == QUOTE and BASE_RE.match(x["base"]) else None} for x in lst if not x["dex"]]}

    # ------------------------------------------------------------------ chaves
    async def state(self, uid: str) -> dict:
        b = self.b
        rows = {r["exchange"]: r for r in await b.db.select("dormant_cex_keys", {"user_id": uid}, columns="exchange,rotulo,info,em") or []}
        cfg = await b.cfg(uid)
        gasto = await self.spent(uid)
        return {"exchanges": [{"id": k, "nome": v["nome"], "frase": v["frase"], "confere_saque": v["confere_saque"], "doc": v["doc"], "rotulo": (rows.get(k) or {}).get("rotulo"), "info": (rows.get(k) or {}).get("info")} for k, v in EXCHANGES.items()],
                "depois": ["Gate", "Bitget", "HTX", "Kraken", "Coinbase"], "ip": await self.server_ip(), "cfg": cfg, "gasto_dia_usd": gasto, "trava_geral": bool(b.allowed())}

    async def server_ip(self) -> str | None:
        c = self.b.__dict__.setdefault("_ip", [0.0, None])
        if time.time() - c[0] < 3600:
            return c[1]
        try:
            r = await self.b.http.get("https://api.ipify.org?format=json", timeout=8)
            c[1] = str(r.json().get("ip") or "")[:64] or None
        except Exception:
            c[1] = None
        c[0] = time.time()
        return c[1]

    async def save_key(self, uid: str, ex: str, key, secret, frase, senha, sem_saque: bool) -> dict:
        b = self.b
        conn = self.conn(ex)
        for v, nome in ((key, "API key"), (secret, "secret")):
            if not isinstance(v, str) or not 8 <= len(v.strip()) <= 300:
                raise BuyError(f"{nome} inválida")
        if EXCHANGES[ex]["frase"] and (not isinstance(frase, str) or not 1 <= len(frase) <= 100):
            raise BuyError("esta exchange pede a passphrase criada junto com a chave")
        keys = {"key": key.strip(), "secret": secret.strip(), "frase": (frase or "") if EXCHANGES[ex]["frase"] else ""}
        async with b.lock(uid):
            await b._check_senha(uid, senha)
            c = await conn.check_key(keys)                 # chave errada ou com saque nem chega ao cofre
            if c["saque"]:
                raise BuyError("esta chave pode SACAR: não guardo. Crie outra só com permissão de negociar (spot), sem saque.")
            if not c["trade"]:
                raise BuyError("esta chave não tem permissão de negociar no spot")
            if c["saque"] is None and not sem_saque:
                raise BuyError(f"a {EXCHANGES[ex]['nome']} não diz pela API se a chave pode sacar: confirme que criou sem saque")
            rot = keys["key"][:4] + "…" + keys["key"][-4:]
            cifra = await asyncio.to_thread(vault.seal, b.box, uid, "cex:" + ex, rot, json.dumps(keys), senha)
            info = {"saque_conferido": c["saque"] is False, "ip": c["ip"], "t": time.time()}
            await b.db.insert("dormant_cex_keys", {"user_id": uid, "exchange": ex, "rotulo": rot, "cifra": cifra, "info": info, "em": _iso(time.time())}, upsert=True, on_conflict="user_id,exchange")
        return {"rotulo": rot, "info": info}

    async def remove_key(self, uid: str, ex: str) -> None:
        if ex not in EXCHANGES:
            raise BuyError("exchange inválida")
        await self.b.db.delete("dormant_cex_keys", {"user_id": uid, "exchange": ex})

    async def _keys(self, uid: str, ex: str, senha: str) -> dict:
        rows = await self.b.db.select("dormant_cex_keys", {"user_id": uid, "exchange": ex}, limit=1) or []
        if not rows:
            raise BuyError(f"cadastre a chave da {EXCHANGES[ex]['nome']} em API exchanges")
        return json.loads(await self.b._open(uid, {"rede": "cex:" + ex, "endereco": rows[0]["rotulo"], "cifra": rows[0]["cifra"]}, senha))

    async def spent(self, uid: str) -> float:
        since = _iso(time.time() - 86400)
        rows = await self.b.db.select("dormant_buys", {"user_id": uid}, gte={"em": since}, columns="usd_in,status,rede") or []
        return round(sum(float(r.get("usd_in") or 0) for r in rows if str(r.get("rede") or "").startswith("cex:") and r.get("status") not in ("falhou", "expirada")), 4)

    # ------------------------------------------------------------------ compra
    async def preview(self, uid: str, key: str, ex: str, usd, senha: str) -> dict:
        b = self.b
        conn = self.conn(ex)
        off = await self.offers(key)
        o = next((x for x in off["lista"] if x.get("ex") == ex), None)
        if not o:
            raise BuyError(f"a CoinGecko não lista esta moeda em {QUOTE} na {EXCHANGES[ex]['nome']}")
        try:
            u = d(usd)
        except ArithmeticError:
            raise BuyError("valor inválido") from None
        if not u.is_finite() or u <= 0 or u > 10 ** 9:
            raise BuyError("valor inválido")
        cfg = await b.cfg(uid)
        bloq, avisos = [], []
        if not b.allowed():
            bloq.append("a trava geral do servidor (PUMP_REAL_ALLOWED) está fechada")
        if not cfg["on"]:
            bloq.append("as compras estão desligadas em Carteiras e compra")
        if float(u) > cfg["cex_max_usd"]:
            bloq.append(f"passa do seu limite por compra em exchange (${cfg['cex_max_usd']:g})")
        gasto = await self.spent(uid)
        if gasto + float(u) > cfg["cex_dia_usd"]:
            bloq.append(f"passa do seu limite de exchange em 24 h (${cfg['cex_dia_usd']:g}; já foram ${gasto:.2f})")
        keys = await self._keys(uid, ex, senha)
        saldo = await conn.balance(keys)
        if saldo < u:
            bloq.append(f"saldo insuficiente na {EXCHANGES[ex]['nome']}: {saldo:.2f} {QUOTE} (a compra é paga em {QUOTE})")
        base = o["base"]
        rules = await conn.rules(base)
        out = {"exchange": ex, "nome": EXCHANGES[ex]["nome"], "moeda": off["moeda"], "par": f"{base}/{QUOTE}", "usd": float(u), "saldo": float(saldo), "slip": cfg["slip_pct"], "bloqueia": bloq, "avisos": avisos}
        if not rules:
            bloq.append(f"a {EXCHANGES[ex]['nome']} não negocia {base}/{QUOTE} agora, apesar de a CoinGecko listar (pode ter saído da exchange)")
            return out
        asks = await conn.asks(base)
        if not asks:
            bloq.append("o livro de ofertas está vazio: ninguém vendendo agora")
            return out
        best = asks[0][0]
        cap = floor_to(best * (1 + d(cfg["slip_pct"]) / 100), rules["tick"])
        cap = max(cap, best)
        w = walk_book(asks, u, cap)
        qty = floor_to(u / cap, rules["step"])     # no preço máximo a ordem nunca gasta mais que o pedido
        if qty < rules["min_qty"] or qty * cap < rules["min_usd"]:
            bloq.append(f"abaixo do mínimo da {EXCHANGES[ex]['nome']} (${float(rules['min_usd']):g})")
        media = w["gasto"] / w["qty"] if w["qty"] else None
        out.update(melhor=float(best), maximo=float(cap), qty=float(qty), qty_estimada=float(w["qty"]), usd_estimado=float(w["gasto"]), media=float(media) if media else None, enche_pct=round(float(w["gasto"] / u * 100), 1))
        if w["sobra"] > u * d("0.02"):
            avisos.append(f"o livro só tem ${float(w['gasto']):.2f} até o seu preço máximo: o resto é cancelado e o dinheiro fica na conta")
        px = (off["moeda"] or {}).get("preco")
        if px and media:
            dif = float(media / d(px) - 1) * 100
            out["dif_cg"] = round(dif, 2)
            if dif > PRECO_BLOQ:
                bloq.append(f"o preço aqui está {dif:.0f}% acima da CoinGecko: livro fino demais ou preço errado")
            elif dif > PRECO_AVISO:
                avisos.append(f"o preço aqui está {dif:.0f}% acima da CoinGecko")
        if o["antigo"]:
            avisos.append("a CoinGecko marca os dados deste par como antigos")
        if not bloq:
            b._prune()
            qid = uuid.uuid4().hex
            b.quotes[qid] = {"lado": "cex", "uid": uid, "t": time.time(), "ex": ex, "key": key, "base": base, "qty": qty, "cap": cap, "usd": float(qty * cap), "cg": b.watch.pick.get(key),
                             "nome": off["moeda"]["nome"], "simbolo": off["moeda"]["simbolo"]}
            out.update(quote_id=qid, validade_s=60)
        return out

    async def buy(self, uid: str, quote_id: str, senha: str, confirmar: str) -> dict:
        b = self.b
        if confirmar != "COMPRAR":
            raise BuyError("digite COMPRAR para confirmar")
        async with b.lock(uid):
            b._prune()
            q = b.quotes.get(str(quote_id or ""))
            if not q or q["uid"] != uid or q.get("lado") != "cex":
                raise BuyError("esta cotação venceu: peça outra")
            cfg = await b.cfg(uid)
            if not b.allowed():
                raise BuyError("a trava geral do servidor (PUMP_REAL_ALLOWED) está fechada")
            if not cfg["on"]:
                raise BuyError("as compras estão desligadas")
            keys = await self._keys(uid, q["ex"], senha)
            b.quotes.pop(quote_id, None)
            if q["usd"] > cfg["cex_max_usd"] * 1.0001 or await self.spent(uid) + q["usd"] > cfg["cex_dia_usd"] * 1.0001:
                raise BuyError("passa dos seus limites de exchange")
            conn = self.conn(q["ex"])
            asks = await conn.asks(q["base"])
            if not asks or asks[0][0] > q["cap"]:
                raise BuyError("o preço subiu além da sua folga: nada foi enviado, peça outra cotação")
            cid = "dm" + uuid.uuid4().hex[:24]
            row = {"id": uuid.uuid4().hex, "user_id": uid, "em": _iso(time.time()), "rede": "cex:" + q["ex"], "cmc": q["key"], "cg": q["cg"], "nome": q["nome"], "simbolo": q["simbolo"], "token": conn.symbol(q["base"]),
                   "endereco": keys["key"][:4] + "…" + keys["key"][-4:], "dex": EXCHANGES[q["ex"]]["nome"], "rota": "limite IOC", "nativo": q["usd"], "nativo_usd": 1.0, "usd_in": q["usd"], "tx": cid, "status": "enviando"}
            await b.db.insert("dormant_buys", row)      # grava ANTES de mandar a ordem
            try:
                oid = await conn.buy_ioc(keys, q["base"], q["cap"], q["qty"], cid)
            except ExError as e:
                await b._finish(row, status="falhou", motivo=str(e)[:160])
                raise
            except Exception as e:
                await b._finish(row, status="confira", motivo=f"resposta inesperada ({type(e).__name__}): confira as ordens na exchange")
                raise BuyError("não sei se a ordem entrou: confira na exchange antes de tentar de novo") from None
            qty, gasto, fim = Decimal(0), Decimal(0), False
            for _ in range(ORDEM_TENTATIVAS):
                await asyncio.sleep(ORDEM_PASSO)
                try:
                    qty, gasto, fim = await conn.order_fill(keys, q["base"], oid)
                except ExError:
                    continue
                if fim:
                    break
            if qty > 0:
                await b._finish(row, status="confirmada", motivo=None if fim else "ordem ainda aberta na última leitura", qty=float(qty), px_in=float(gasto / qty), usd_in=float(gasto), nativo=float(gasto), tx=oid, gas_usd=0.0)
            elif fim:
                await b._finish(row, status="falhou", motivo="ninguém vendeu até o seu preço máximo: nada foi comprado", usd_in=0.0, tx=oid)
            else:
                await b._finish(row, status="confira", motivo="sem resposta da ordem: confira na exchange", tx=oid)
            b.watch.held.add(q["cg"]) if q["cg"] else None
            return {k: row.get(k) for k in ("id", "status", "motivo", "qty", "px_in", "usd_in", "nome", "simbolo", "dex")}
