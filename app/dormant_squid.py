"""Dormant: compras de MANTRA feitas no site da Squid entram sozinhas em Minhas compras (0.32.468, pedido do dono em 26/11/2026: "eu cliquei,
abriu lá a Squid, fiz o swap... agora não tem nada lá"). Só LÊ a blockchain: nunca assina nem envia nada.

O que foi visto na compra real dele (26/11): na Base saiu ETH para um endereço de depósito da Squid (a transação não diz o destino) e 11 s
depois, na MANTRA, o contrato SquidMulticall pagou a carteira (transferência interna, sem evento). Por isso:
1. a entrega é achada no explorador da MANTRA (transferências internas vindas do SquidMulticall para a carteira) e conferida no nó: a
   transação deu certo, foi no roteador da Squid e cita a carteira;
2. o pagamento é a última transação da MESMA carteira na Base nos 5 minutos antes da entrega, com ETH ou USDC saindo. Se a busca terminar sem
   achar (pagou por outra rede), a compra entra com o custo estimado pelo preço da hora e isso fica escrito. Se a Base não responder, nada é
   gravado e tenta de novo depois.
"""
from __future__ import annotations

import asyncio
import time
import uuid

from . import evm
from .dormant_buy import CHAINS, ZERO, BuyError, _iso, _ts

REDE = "mantra-evm"
# SquidMulticall e roteadores da MANTRA: docs.squidrouter.com/additional-resources/contracts, vistos na entrega real de 26/11/2026
MULTICALL = "0x073e81d92bd8b39562106819d12346240606f04a"
ROUTERS = ("0x2b4d4cf15dad79d3426d19674bd237c1dc9144aa", "0xce16f69375520ab01377ce7b88f5ba8c48f8d666")
EXPLORADOR = "https://blockscout.mantrascan.io/api/v2/addresses/{}/internal-transactions"
USDC_BASE = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
T_TRANSFER = "0x" + evm.keccak256(b"Transfer(address,address,uint256)").hex()
PAGO = "pago na Base: "
SEM_PAGAMENTO = "pagamento não identificado na Base: o custo é o valor do que chegou, pelo preço da hora"
JANELA_S, AMOSTRA, MAX_TX = 300, 5000, 5     # pagamento até 5 min antes da entrega; olha no máximo 5 transações da carteira
MINIMO_USD = 0.10                      # abaixo disto é poeira (qualquer um pode mandar centavos pela Squid para uma carteira)
CADA_S = 60


def _n(v) -> int:
    return int(v or "0x0", 16)


class SquidTracker:
    def __init__(self, buyer):
        self.b = buyer

    async def auto(self, uid: str) -> dict | None:
        """Chamado ao abrir Minhas compras. No máximo uma conferida por minuto; nunca derruba a tela."""
        wal = await self.b.wallet_row(uid, REDE)
        if not wal:
            return None
        estado = self.b.__dict__.setdefault("_squid", {})
        st = estado.setdefault(uid, {"t": 0.0, "erro": None, "tentou": 0.0})
        lock = self.b.__dict__.setdefault("_squid_locks", {}).setdefault(uid, asyncio.Lock())
        if not lock.locked() and time.time() - st["tentou"] >= CADA_S:
            async def go():
                async with lock:
                    st["tentou"] = time.time()
                    try:
                        await self.scan(uid, wal["endereco"].lower())
                        st["t"], st["erro"] = time.time(), None
                    except BuyError as e:
                        st["erro"] = str(e)[:160]
                    except Exception as e:             # só o tipo: nada de endereço de serviço na tela
                        st["erro"] = f"não consegui conferir ({type(e).__name__})"
            await self.b._early(go())
        return {"t": st["t"] or None, "erro": st["erro"]}

    async def scan(self, uid: str, addr: str) -> list[dict]:
        b = self.b
        try:
            r = await b.http.get(EXPLORADOR.format(addr), headers={"User-Agent": "pump-fun-copy/1.0", "accept": "application/json"}, timeout=20)
            itens = r.json()["items"]
        except Exception as e:
            raise BuyError(f"o explorador da MANTRA não respondeu ({type(e).__name__})") from None
        tem = await b.db.select("dormant_buys", {"user_id": uid, "rede": REDE}, columns="id,motivo", limit=1000) or []
        ids = {x.get("id") for x in tem}
        usados = {str(x.get("motivo"))[len(PAGO):] for x in tem if str(x.get("motivo") or "").startswith(PAGO)}
        novas = []
        for it in sorted(itens if isinstance(itens, list) else [], key=lambda x: str(x.get("timestamp"))):
            try:
                de = str((it.get("from") or {}).get("hash") or "").lower()
                para = str((it.get("to") or {}).get("hash") or "").lower()
                tx, wei, quando = str(it["transaction_hash"]).lower(), int(it["value"]), _ts(it.get("timestamp"))
            except (KeyError, TypeError, ValueError, AttributeError):
                continue
            if de != MULTICALL or para != addr or it.get("success") is not True or wei <= 0 or not quando:
                continue
            rid = uuid.uuid5(uuid.NAMESPACE_URL, f"squid:{uid}:{tx}").hex
            if rid in ids or not await self._confere(tx, addr):
                continue
            row = await self._linha(uid, rid, addr, tx, wei / 1e18, quando, usados)
            if not row:
                continue
            await b.db.insert("dormant_buys", row)
            ids.add(rid)
            b.watch.held.add("mantra")
            novas.append(row)
        return novas

    async def _confere(self, tx: str, addr: str) -> bool:
        """A entrega no nó: deu certo, foi no roteador da Squid e cita esta carteira."""
        url = CHAINS[REDE]["rpc"]
        t = await self.b.rpc(url, "eth_getTransactionByHash", [tx])
        rc = await self.b.rpc(url, "eth_getTransactionReceipt", [tx])
        if not t or not rc:
            raise BuyError("a rede MANTRA ainda não devolveu a transação")
        return _n(rc.get("status")) == 1 and str(t.get("to") or "").lower() in ROUTERS and addr[2:] in str(t.get("input") or "").lower()

    async def _pagamento(self, addr: str, quando: float, usados: set) -> dict | None:
        """A última transação desta carteira na Base antes da entrega. A Base faz um bloco a cada 0,2 s (medido em 26/11; a primeira versão
        contou 2 s e não achou a compra real), então em vez de ler bloco por bloco procura onde o contador de transações da carteira mudou."""
        url = CHAINS["base"]["rpc"]

        async def bloco(n, cheio=False):
            x = await self.b.rpc(url, "eth_getBlockByNumber", [hex(n) if isinstance(n, int) else n, cheio])
            if not x:
                raise BuyError("a Base não devolveu o bloco")
            return x

        async def contador(n):
            return _n(await self.b.rpc(url, "eth_getTransactionCount", [addr, hex(n)]))

        ult = await bloco("latest")
        topo, agora = _n(ult["number"]), _n(ult["timestamp"])
        passo = max(0.05, (agora - _n((await bloco(max(1, topo - AMOSTRA)))["timestamp"])) / min(AMOSTRA, max(1, topo - 1)))   # segundos por bloco
        alto = max(1, min(topo, topo - int((agora - quando) / passo)))
        for _ in range(3):                                   # acerta o palpite do bloco da hora da entrega
            alto = max(1, min(topo, alto + int((quando - _n((await bloco(alto))["timestamp"])) / passo)))
        baixo = max(1, alto - int(JANELA_S / passo))
        total, antes = await contador(alto), await contador(baixo)
        for k in range(total, max(antes, total - MAX_TX), -1):          # da mais nova para a mais antiga
            lo, hi = baixo, alto                                        # contador(lo) < k <= contador(hi)
            while hi - lo > 1:
                meio = (lo + hi) // 2
                if await contador(meio) >= k:
                    hi = meio
                else:
                    lo = meio
            bl = await bloco(hi, True)
            t = next((t for t in bl.get("transactions") or [] if str(t.get("from") or "").lower() == addr and _n(t.get("nonce")) == k - 1), None)
            if not t or str(t.get("hash") or "").lower() in usados or _n(bl["timestamp"]) > quando:
                continue
            rc = await self.b.rpc(url, "eth_getTransactionReceipt", [t["hash"]])
            if not rc:
                raise BuyError("a Base ainda não devolveu o recibo")
            if _n(rc.get("status")) != 1:
                continue
            gas = (_n(rc.get("gasUsed")) * _n(rc.get("effectiveGasPrice")) + _n(rc.get("l1Fee"))) / 1e18
            eth = _n(t.get("value")) / 1e18
            usdc = sum(_n(g.get("data")) for g in rc.get("logs") or [] if str(g.get("address") or "").lower() == USDC_BASE
                       and len(g.get("topics") or []) == 3 and g["topics"][0] == T_TRANSFER and g["topics"][1][-40:].lower() == addr[2:]) / 1e6
            if eth > 0 or usdc > 0:
                return {"tx": str(t["hash"]).lower(), "t": _n(bl["timestamp"]), "moeda": "ETH" if eth > 0 else "USDC", "qtd": eth or usdc, "gas_eth": gas}
        return None

    async def _preco(self, cg: str, rede: str, quando: float) -> float | None:
        """Preço em dólar na hora da compra; recente = o de agora."""
        if time.time() - quando > 3600:
            try:
                d = await self.b.watch.get(f"/coins/{cg}/market_chart/range", {"vs_currency": "usd", "from": int(quando - 3600), "to": int(quando + 3600)})
                perto = min(d["prices"], key=lambda p: abs(p[0] / 1000 - quando))
                if perto[1] > 0:
                    return float(perto[1])
            except Exception:
                pass
        return await self.b.native_usd(rede)

    async def _linha(self, uid: str, rid: str, addr: str, tx: str, qty: float, quando: float, usados: set) -> dict | None:
        pg = await self._pagamento(addr, quando, usados)
        pm = await self._preco("mantra", REDE, quando)
        pe = await self._preco("ethereum", "base", quando) if pg else None
        if not pm or (pg and not pe):
            raise BuyError("sem a cotação em dólar agora: tento de novo")
        if qty * pm < MINIMO_USD:
            return None
        if pg:
            usd = pg["qtd"] * pe if pg["moeda"] == "ETH" else pg["qtd"]
            gas, motivo = pg["gas_eth"] * pe, PAGO + pg["tx"]
            rota = f"{pg['qtd']:.8f}".rstrip("0").rstrip(".") + f" {pg['moeda']} na Base → MANTRA"
            usados.add(pg["tx"])
        else:
            usd, gas, motivo, rota = qty * pm, 0.0, SEM_PAGAMENTO, "pagamento não identificado → MANTRA"
        w = self.b.watch
        cmc = next((k for k, v in w.pick.items() if v == "mantra"), None) or next((k for k, v in w.map.items() if "mantra" in v), None)
        return {"id": rid, "user_id": uid, "em": _iso(pg["t"] if pg else quando), "rede": REDE, "cmc": cmc, "cg": "mantra", "nome": "MANTRA", "simbolo": "MANTRA",
                "token": ZERO, "endereco": addr, "dex": "Squid (comprada no site)", "rota": rota, "nativo": None, "nativo_usd": None, "usd_in": round(usd, 6),
                "gas_usd": round(gas, 6), "casas": 18, "qty": qty, "px_in": usd / qty, "tx": tx, "status": "confirmada", "motivo": motivo}
