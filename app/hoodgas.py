"""Robinhood Chain: saldo da carteira e abastecer de outra rede pela Relay (0.32.286). Isolado no painel /hood.

Pedido do dono em 10/11/2026: "quando colocar a chave privada, falar quanto tem a carteira e se precisa abastecer; se não tiver nada,
abastecer de outra rede: identifica os saldos das outras redes e faz o mesmo esquema da Relay para transferir para a Robinhood (copia
do Dormant)".

A mesma chave da carteira da Robinhood abre o mesmo endereço nas redes EVM. Então os saldos de Ethereum, BNB Chain, Base e Arbitrum são
lidos do próprio endereço, e o destino é SEMPRE esse endereço na Robinhood: o navegador manda só o nome da rede de origem e o valor.
Conferido na Relay em 10/11/2026 (só cotação): as 4 origens cotam a Robinhood (chain 4663) com um passo só, depositNative no contrato
fixo DEPOSITORY, entrega em ~1 s. A transação vem da API deles, por isso passa pela mesma conferência do Dormant (dormant_gas.check_quote:
um passo, contrato fixo, seletor, valor, rede, depositante e destinatário) antes de assinar, e nunca há approve.
Diferente do Dormant: a entrega também é conferida na Robinhood (o saldo do destino tem que subir), porque o destino é a própria carteira.
Trava geral PUMP_REAL_ALLOWED, teto por abastecimento e limite de 24 h. Sem senha extra: a chave é a mesma da cópia REAL (cofre do servidor).
"""
from __future__ import annotations

import asyncio
import time
import uuid

from . import evm
from .dormant_buy import CHAINS
from .dormant_gas import DEPOSITORY, RELAY, check_quote

DEST_ID = 4663
ORIGENS = ("ethereum", "binance-smart-chain", "base", "arbitrum-one")
ZERO = "0x" + "0" * 40
FILL_MAX_USD = 50.0               # por abastecimento: o destino só é conferido depois da entrega
DIA_MAX_USD = 150.0               # em 24 h
AMOSTRA_USD = 2.0
MIN_ORIGEM_USD = 1.0
TAXA_AVISO, TAXA_BLOQ = 3.0, 15.0
OPS_ALVO = 5                      # "precisa abastecer" quando não dá para 5 compras REAL (+ gás das vendas)
QUOTE_S = 60
ENTREGA_S = 90


class FillError(Exception):
    pass


class HoodGas:
    def __init__(self, copier):
        self.c = copier
        self.quotes: dict[str, dict] = {}
        self.hist: dict[str, list[dict]] = {}
        self._px: dict[str, tuple[float, float]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    # ------------------------------------------------------------------ util
    async def _rpc(self, chain: str, method: str, params: list):
        r = await self.c.http.post(CHAINS[chain]["rpc"], json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                                   headers={"User-Agent": "pump-fun-copy/1.0"}, timeout=20)
        js = r.json()
        if js.get("error"):
            raise FillError(str(js["error"].get("message") or js["error"])[:160])
        return js.get("result")

    async def usd(self, cg: str) -> float | None:
        hit = self._px.get(cg)
        if hit and time.time() - hit[0] < 120:
            return hit[1]
        v = None
        if cg == "ethereum" and getattr(self.c.w, "eth_usd", None):
            v = float(self.c.w.eth_usd)
        else:
            try:
                r = await self.c.http.get("https://api.coingecko.com/api/v3/simple/price", params={"ids": cg, "vs_currencies": "usd"}, timeout=10)
                v = float(((r.json() or {}).get(cg) or {}).get("usd") or 0) or None
            except Exception:
                v = None
        if v:
            self._px[cg] = (time.time(), v)
        return v or (hit[1] if hit else None)

    async def _relay(self, origem: str, addr: str, value: int) -> dict:
        try:
            r = await self.c.http.post(RELAY + "/quote/v2", json={"user": addr, "recipient": addr, "originChainId": CHAINS[origem]["id"],
                                                                 "destinationChainId": DEST_ID, "originCurrency": ZERO, "destinationCurrency": ZERO,
                                                                 "amount": str(value), "tradeType": "EXACT_INPUT"},
                                       headers={"User-Agent": "pump-fun-copy/1.0"}, timeout=20)
            js = r.json()
        except Exception as e:
            raise FillError(f"a Relay não respondeu ({type(e).__name__})") from None
        if not isinstance(js, dict) or "steps" not in js:
            if isinstance(js, dict) and (js.get("errorCode") == "AMOUNT_TOO_LOW" or "too small" in str(js.get("message") or "").lower()):
                raise FillError("valor pequeno demais: não cobre a taxa da ponte; tente a partir de uns US$ 1")
            raise FillError("a Relay não cotou esta rota: " + str((js or {}).get("message") if isinstance(js, dict) else "")[:120])
        try:
            return check_quote(js, origem, addr, addr, value)
        except Exception as e:                       # BuyError do Dormant: mesma mensagem
            raise FillError(str(e)) from None

    def spent_24h(self, uid: str) -> float:
        lim = time.time() - 86400
        return sum(x["usd"] for x in self.hist.get(uid, []) if x["t"] >= lim and x["status"] not in ("falhou", "devolvida"))

    # ------------------------------------------------------------------ saldo e rotas (só leitura)
    async def status(self, uid: str) -> dict:
        key, addr = await self.c.get_key(uid)
        if not key:
            return {"chave": False}
        rc = self.c.rcfg(uid)
        eth_usd = await self.usd("ethereum")
        try:
            bal = int(await self.c.chain.rpc("eth_getBalance", [addr, "latest"]) or "0x0", 16) / 1e18
        except Exception:
            bal = None
        per = rc["real_eth_por_compra"]
        from .hoodreal import GAS_RESERVE
        ops = int(max(0.0, (bal or 0) - GAS_RESERVE) // per) if bal is not None and per else 0
        alvo = per * OPS_ALVO + GAS_RESERVE

        async def one(k: str) -> dict:
            c = CHAINS[k]
            r = {"origem": k, "nome": c["nome"], "moeda": c["moeda"]}
            un = await self.usd(c["cg"])
            try:
                b = int(await self._rpc(k, "eth_getBalance", [addr, "latest"]) or "0x0", 16) / 1e18
            except Exception:
                return {**r, "ok": False, "motivo": "não consegui ler o saldo"}
            r.update(saldo=b, saldo_usd=b * un if un else None, usd_moeda=un)
            if not un or not eth_usd:
                return {**r, "ok": False, "motivo": "sem a cotação em dólar agora"}
            if b * un < MIN_ORIGEM_USD:
                return {**r, "ok": False, "motivo": "sem saldo para mandar" if b <= 0 else f"saldo baixo (${b * un:.2f})"}
            try:
                q = await self._relay(k, addr, int(AMOSTRA_USD / un * 1e18))
            except FillError as e:
                return {**r, "ok": False, "motivo": str(e)[:160]}
            return {**r, "ok": True, "taxa_pct": round((1 - q["saida"] * eth_usd / AMOSTRA_USD) * 100, 2), "tempo_s": q["tempo_s"],
                    "max_usd": round(min(FILL_MAX_USD, b * un * 0.97), 2)}
        rotas = sorted(await asyncio.gather(*[one(k) for k in ORIGENS]), key=lambda x: (not x["ok"], x.get("taxa_pct") or 99))
        return {"chave": True, "endereco": addr, "saldo": bal, "saldo_usd": bal * eth_usd if bal is not None and eth_usd else None,
                "eth_usd": eth_usd, "compras": ops, "por_compra": per, "alvo": alvo, "precisa": bal is not None and bal < alvo,
                "falta_usd": round(max(0.0, alvo - (bal or 0)) * eth_usd, 2) if eth_usd else None,
                "rotas": rotas, "limites": {"por_vez_usd": FILL_MAX_USD, "dia_usd": DIA_MAX_USD, "gasto_24h": round(self.spent_24h(uid), 2)},
                "permitido": self.c.real_allowed, "historico": self.hist.get(uid, [])[:30], "ponte": "Relay"}

    # ------------------------------------------------------------------ cotação e envio
    async def preview(self, uid: str, origem: str, usd) -> dict:
        if origem not in ORIGENS:
            raise FillError("esta rede não serve de origem: use Ethereum, BNB Chain, Base ou Arbitrum")
        try:
            usd = float(usd)
        except (TypeError, ValueError):
            raise FillError("valor inválido") from None
        if not 0 < usd < 1e7:
            raise FillError("valor inválido")
        key, addr = await self.c.get_key(uid)
        if not key:
            raise FillError("salve antes a chave da carteira da Robinhood")
        c = CHAINS[origem]
        bloq, avisos = [], []
        if not self.c.real_allowed:
            bloq.append("a trava geral do servidor (PUMP_REAL_ALLOWED) está fechada: nada é enviado")
        if usd > FILL_MAX_USD:
            bloq.append(f"o teto por abastecimento é ${FILL_MAX_USD:g}")
        if self.spent_24h(uid) + usd > DIA_MAX_USD:
            bloq.append(f"passa do limite de ${DIA_MAX_USD:g} em 24 h (já foram ${self.spent_24h(uid):.2f})")
        un, ud = await self.usd(c["cg"]), await self.usd("ethereum")
        if not un or not ud:
            raise FillError("sem a cotação em dólar agora: tente de novo em instantes")
        value = int(usd / un * 1e18)
        q = await self._relay(origem, addr, value)
        taxa = (1 - q["saida"] * ud / usd) * 100
        if taxa > TAXA_BLOQ:
            bloq.append(f"a taxa ficaria em {taxa:.1f}%: cara demais (máx. {TAXA_BLOQ:g}%)")
        elif taxa > TAXA_AVISO:
            avisos.append(f"a taxa está em {taxa:.1f}%: valor pequeno ou rede cara")
        gp = int(await self._rpc(origem, "eth_gasPrice", []) or "0x0", 16)
        bal = int(await self._rpc(origem, "eth_getBalance", [addr, "latest"]) or "0x0", 16)
        gas = 60000
        if bal < value:
            bloq.append(f"saldo insuficiente na origem: {bal / 1e18:.6f} {c['moeda']}")
        else:
            try:
                gas = int(await self._rpc(origem, "eth_estimateGas", [{"from": addr, "to": DEPOSITORY, "data": q["data"], "value": hex(value)}]), 16)
            except FillError as e:
                bloq.append("a rede recusou na simulação: " + str(e))
            if bal < value + int(gas * 1.3) * gp:
                bloq.append(f"falta {c['moeda']} para pagar o gás da própria transação na origem")
        out = {"origem": origem, "origem_nome": c["nome"], "moeda": c["moeda"], "carteira": addr, "paga": value / 1e18, "usd": usd,
               "recebe": q["saida"], "usd_recebe": round(q["saida"] * ud, 4), "taxa_pct": round(taxa, 2), "gas_usd": round(gas * gp / 1e18 * un, 4),
               "tempo_s": q["tempo_s"], "ponte": "Relay", "bloqueia": bloq, "avisos": avisos}
        if not bloq:
            now = time.time()
            for k in [k for k, v in self.quotes.items() if now - v["t"] > QUOTE_S]:
                self.quotes.pop(k, None)
            qid = uuid.uuid4().hex
            self.quotes[qid] = {"uid": uid, "t": now, "origem": origem, "addr": addr, "value": value, "usd": usd, "saida": q["saida"], "gp": gp}
            out.update(quote_id=qid, validade_s=QUOTE_S)
        return out

    async def fill(self, uid: str, quote_id: str, confirmar: str) -> dict:
        if str(confirmar or "").strip().upper() != "ABASTECER":
            raise FillError("digite ABASTECER para confirmar")
        lock = self._locks.setdefault(uid, asyncio.Lock())
        async with lock:
            q = self.quotes.get(str(quote_id or ""))
            if not q or q["uid"] != uid or time.time() - q["t"] > QUOTE_S:
                raise FillError("esta cotação venceu: peça outra")
            self.quotes.pop(quote_id, None)
            if not self.c.real_allowed:
                raise FillError("a trava geral do servidor (PUMP_REAL_ALLOWED) está fechada")
            if q["usd"] > FILL_MAX_USD or self.spent_24h(uid) + q["usd"] > DIA_MAX_USD:
                raise FillError("passa dos limites de abastecimento")
            if any(x["status"] in ("enviando", "pendente") and x["origem"] == q["origem"] for x in self.hist.get(uid, [])):
                raise FillError("há um abastecimento desta rede sem confirmação: espere ele terminar")
            key, addr = await self.c.get_key(uid)
            if not key or addr != q["addr"]:
                raise FillError("a chave da carteira mudou: peça outra cotação")
            o = q["origem"]
            c = CHAINS[o]
            if int(await self._rpc(o, "eth_chainId", []) or "0x0", 16) != c["id"]:
                raise FillError("o RPC respondeu de outra rede: nada foi enviado")
            nova = await self._relay(o, addr, q["value"])                       # o depósito é sempre de uma cotação nova
            if nova["saida"] < q["saida"] * 0.97:
                raise FillError("a cotação piorou: nada foi enviado, peça outra")
            est = int(await self._rpc(o, "eth_estimateGas", [{"from": addr, "to": DEPOSITORY, "data": nova["data"], "value": hex(q["value"])}]), 16)
            gp = int(await self._rpc(o, "eth_gasPrice", []) or "0x0", 16)
            if gp > q["gp"] * 2:
                raise FillError("o gás mais que dobrou desde a cotação: nada foi enviado, peça outra")
            gp = int(gp * 1.1)
            gas = int(est * 1.3) + 10000
            if int(await self._rpc(o, "eth_getBalance", [addr, "latest"]) or "0x0", 16) < q["value"] + gas * gp:
                raise FillError(f"falta {c['moeda']} para pagar o valor e o gás: nada foi enviado")
            try:
                dest0 = int(await self.c.chain.rpc("eth_getBalance", [addr, "latest"]) or "0x0", 16)
            except Exception:
                dest0 = None
            nonce = int(await self._rpc(o, "eth_getTransactionCount", [addr, "pending"]), 16)
            raw, h = evm.sign_tx(key, nonce, gp, gas, DEPOSITORY, q["value"], nova["data"], c["id"])
            row = {"id": uuid.uuid4().hex[:16], "t": time.time(), "origem": o, "origem_nome": c["nome"], "moeda": c["moeda"], "paga": q["value"] / 1e18,
                   "usd": q["usd"], "recebe": nova["saida"], "request_id": nova["request_id"], "tx": h, "expl": c.get("expl"), "status": "enviando", "motivo": None}
            self.hist.setdefault(uid, []).insert(0, row)
            del self.hist[uid][100:]
            try:
                await self._rpc(o, "eth_sendRawTransaction", [raw])
            except FillError as e:
                if "known" not in str(e).lower() and "already" not in str(e).lower():
                    row.update(status="falhou", motivo="envio recusado: " + str(e)[:160])
                    raise
            row["status"] = "pendente"
        self.c._spawn(self._follow(row, o, addr, dest0, gp))
        return row

    async def _follow(self, row: dict, origem: str, addr: str, dest0: int | None, gp: int) -> None:
        """Recibo na origem, depois a entrega: status da Relay e o saldo da carteira na Robinhood subindo."""
        t0 = time.monotonic()
        rc = None
        while time.monotonic() - t0 < 90 and not rc:
            await asyncio.sleep(3)
            try:
                rc = await self._rpc(origem, "eth_getTransactionReceipt", [row["tx"]])
            except Exception:
                rc = None
        if not rc:
            row["motivo"] = "depósito sem confirmação em 90 s: confira no explorador"
            return
        if int(rc.get("status") or "0x0", 16) != 1:
            row.update(status="falhou", motivo="o depósito falhou na rede (só o gás foi gasto)")
            return
        row["motivo"] = "depositado: esperando a entrega na Robinhood"
        t0 = time.monotonic()
        while time.monotonic() - t0 < ENTREGA_S:
            await asyncio.sleep(3)
            st = ""
            try:
                r = await self.c.http.get(RELAY + "/intents/status/v3", params={"requestId": row["request_id"]}, timeout=15)
                st = str((r.json() or {}).get("status") or "")
            except Exception:
                pass
            if st == "refund":
                row.update(status="devolvida", motivo="a Relay devolveu o valor para a carteira de origem")
                return
            if st == "failure":
                row.update(status="falhou", motivo="a Relay disse que a entrega falhou: confira o saldo; se não voltar, procure o suporte dela com a transação")
                return
            try:
                now_bal = int(await self.c.chain.rpc("eth_getBalance", [addr, "latest"]) or "0x0", 16)
            except Exception:
                now_bal = None
            if st == "success" or (dest0 is not None and now_bal is not None and now_bal > dest0):
                row.update(status="confirmada", motivo=None)
                rb = self.c.real.get(next((u for u, k in self.c._keys.items() if k[1] == addr), ""), None)
                if rb:
                    rb.balance_t = 0
                return
        row["motivo"] = "a entrega ainda não apareceu: confira o saldo em alguns minutos"
