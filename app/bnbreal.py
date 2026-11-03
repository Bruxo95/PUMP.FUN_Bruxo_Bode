"""BNB · Four.Meme, carteira REAL (0.32.172). Começa DESLIGADA; só o dono liga, na tela, com a confirmação LIGAR.

Pedido do dono em 03/11/2026: "a real tem que ter tudo que tem na fictícia". Mesma decisão da cópia fictícia (o trader do
ranking comprou → compra; ele vendeu → vende a mesma parte; tempo máximo e stop), com valor e limites próprios.

Ao ligar, a REAL só entra nas compras NOVAS dos traders, a partir daquele momento. As posições que a fictícia já tinha não
são compradas na REAL (pergunta do dono: entrar depois, num preço que já andou, é arriscado). Cada posição REAL tem a sua
própria venda: só vende o que a REAL comprou.

Conferido na rede em 03/11/2026 (eth_call/estimateGas, nada enviado):
- compra de token cotado em BNB: TokenManager2.buyTokenAMAP(token, valor, mínimo) com o valor em BNB (0x87f27655);
- compra de token cotado em USDT pagando BNB: TokenManagerHelper3.buyWithEth(0, token, carteira, valor, mínimo) (0xc932b37b);
- estimativa: Helper3.tryBuy(token, 0, valor) e trySell(token, quantidade); mínimo alto demais devolve "Slippage";
- venda na curva: TokenManager2.sellToken(token, quantidade, mínimo) (0x3e11741f), depois de approve; token cotado em USDT
  recebe USDT, que é trocado por BNB na PancakeSwap V2; token que foi para a PancakeSwap vende pelo par V2.
Gás medido: ~430 mil na compra, 0,05 gwei no dia (≈ 0,00002 BNB).
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid

from . import evm

log = logging.getLogger("bnb.real")

CHAIN_ID = 56
TM2 = "0x5c952063c7fc8610ffdb798152d69f0b9550762b"
HELPER3 = "0xf251f83e40a78868fcfa3fa4599dad6494e46034"
ROUTER_V2 = "0x10ed43c718714eb63d5aa57b78b54704e256024e"   # PancakeSwap V2
FACTORY_V2 = "0xca143ce32fe78f1f7019d7d551a6402fc5350c73"
WBNB = "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c"
ZERO = "0x" + "0" * 40
MAX = 2 ** 256 - 1
SEL = {"buy": "0x87f27655", "buy_eth": "0xc932b37b", "sell": "0x3e11741f", "try_buy": "0xe21b103a", "try_sell": "0xc6f43e8c",
       "approve": "0x095ea7b3", "allowance": "0xdd62ed3e", "balance": "0x70a08231", "pair": "0xe6a43905",
       "amounts_out": "0xd06ca61f", "swap_eth": "0x791ac947"}
T_TRANSFER = "0x" + evm.keccak256(b"Transfer(address,address,uint256)").hex()
T_WITHDRAW = "0x" + evm.keccak256(b"Withdrawal(address,uint256)").hex()
T_SALE = "0x0a5575b3648bae2210cee56bf33254cc1ddfbc7bf637c0af2ac18b14fb1bae19"
FEE = 0.01
GAS_RESERVE = 0.002                 # BNB que fica na carteira para o gás das vendas
RETRY_S = 60                        # venda automática que falhou espera 1 min antes de tentar de novo

REAL_DEFAULT = {"real_on": False, "real_bnb_por_compra": 0.01, "real_max_abertas": 5, "real_slip_pct": 15.0,
                "real_perda_dia": 0.05, "real_gwei": 0.1}
REAL_LIMITS = {"real_bnb_por_compra": (0.001, 1), "real_max_abertas": (1, 30), "real_slip_pct": (1, 49),
               "real_perda_dia": (0.001, 10), "real_gwei": (0.05, 5)}


def clean(raw: dict | None, base: dict | None = None) -> dict:
    """Valores da REAL. real_on NÃO passa por aqui: só pela rota de ligar, com a confirmação."""
    out = dict(REAL_DEFAULT)
    out.update({k: v for k, v in (base or {}).items() if k in REAL_DEFAULT})
    for k, v in (raw or {}).items():
        if k not in REAL_LIMITS:
            continue
        try:
            val = float(v)
        except (TypeError, ValueError):
            continue
        if val != val:
            continue
        lo, hi = REAL_LIMITS[k]
        val = min(hi, max(lo, val))
        out[k] = int(val) if isinstance(REAL_DEFAULT[k], int) else round(val, 6)
    return out


class ChainError(Exception):
    pass


class RealBook:
    """Posições REAIS de uma conta (mesmo formato das fictícias, para as telas serem as mesmas)."""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.pos: dict[str, dict] = {}
        self.trades: list[dict] = []
        self.events: list[dict] = []
        self.dirty_pos: set = set()
        self.closed_pos: set = set()
        self.new_trades: list[dict] = []
        self.lock = asyncio.Lock()              # uma transação por vez (nonce)
        self.busy: set = set()                  # (trader, token) com compra saindo
        self.address: str | None = None
        self.balance: float | None = None
        self.balance_t = 0.0
        self.on_since: float | None = None

    def ev(self, t: float, wallet: str, token: str, acao: str, motivo: str = "", tx: str | None = None) -> None:
        self.events.insert(0, {"t": t, "wallet": wallet, "token": token, "acao": acao, "motivo": motivo, "tx": tx, "real": True})
        del self.events[200:]

    @staticmethod
    def value_now(p: dict, slip: float) -> float:
        px = p.get("px_now") or p.get("px_in") or 0
        return p["tokens_left"] * px * (1 - FEE - slip / 100)

    def pnl_now(self, p: dict, slip: float) -> tuple[float, float]:
        v = p["proceeds"] + max(0.0, self.value_now(p, slip)) - p["bnb_in"]
        return v, (100 * v / p["bnb_in"] if p["bnb_in"] else 0.0)

    def lost_today(self, now: float) -> float:
        day = now - now % 86400
        return -sum(x["pnl_bnb"] for x in self.trades if x["close_t"] >= day and x["pnl_bnb"] < 0)

    def wallet(self, now: float, slip: float, periods) -> dict:
        open_val = sum(max(0.0, self.value_now(p, slip)) for p in self.pos.values())
        closed = self.trades
        wins = [x for x in closed if x["pnl_bnb"] > 0]
        aberto = sum(self.pnl_now(p, slip)[0] for p in self.pos.values())
        realizado = sum(x["pnl_bnb"] for x in closed)
        inv = sum(x["bnb_in"] for x in closed) + sum(p["bnb_in"] for p in self.pos.values())
        saldo = self.balance
        return {"saldo": None if saldo is None else round(saldo, 6), "em_posicoes": round(open_val, 6),
                "total": None if saldo is None else round(saldo + open_val, 6), "inicial": None,
                "resultado": round(realizado + aberto, 6), "resultado_pct": round(100 * (realizado + aberto) / inv, 2) if inv else 0,
                "abertas": len(self.pos), "fechadas": len(closed), "acerto": round(100 * len(wins) / len(closed), 1) if closed else None,
                "realizado": round(realizado, 6), "periodos": periods(closed, now), "endereco": self.address}

    def close(self, p: dict, t: float, motivo: str, px: float | None) -> dict:
        pnl = p["proceeds"] - p["bnb_in"]
        tr = {**{k: p.get(k) for k in ("id", "wallet", "token", "open_t", "px_in", "bnb_in", "best_pct", "worst_pct", "lag_s",
                                       "tx_in", "aba", "vendas", "quote")},
              "close_t": t, "px_out": px, "bnb_out": round(p["proceeds"], 9), "pnl_bnb": round(pnl, 9),
              "pnl_pct": round(100 * pnl / p["bnb_in"], 2) if p["bnb_in"] else 0.0, "motivo": motivo, "real": True,
              "tx_out": p.get("tx_last")}
        self.pos.pop(p["id"], None)
        self.dirty_pos.discard(p["id"])
        self.closed_pos.add(p["id"])
        self.trades.insert(0, tr)
        del self.trades[3000:]
        self.new_trades.append(tr)
        return tr


class Chain:
    """Leitura e envio na BNB Chain com a chave da conta. rpc = BnbWatch.rpc (troca de RPC sozinho)."""

    def __init__(self, rpc):
        self.rpc = rpc

    async def call(self, to: str, data: str, frm: str | None = None, value: int = 0) -> str:
        p = {"to": to, "data": data}
        if frm:
            p["from"] = frm
        if value:
            p["value"] = hex(value)
        try:
            return await self.rpc("eth_call", [p, "latest"]) or "0x"
        except Exception as e:
            raise ChainError("simulação recusada: " + str(e)[:160])

    async def balance(self, addr: str) -> int:
        return int(await self.rpc("eth_getBalance", [addr, "latest"]) or "0x0", 16)

    async def token_balance(self, token: str, addr: str) -> int:
        w = evm.words(await self.call(token, SEL["balance"] + evm.w_addr(addr)))
        return w[0] if w else 0

    async def send(self, key: int, addr: str, to: str, data: str, value: int, gwei: float) -> dict:
        """Simula (estimateGas: se a transação daria erro, recusa aqui), assina, envia e espera o recibo."""
        try:
            est = int(await self.rpc("eth_estimateGas", [{"from": addr, "to": to, "data": data, "value": hex(value)}]), 16)
        except Exception as e:
            raise ChainError("a rede recusou na simulação: " + str(e)[:160])
        gp = int(await self.rpc("eth_gasPrice", []) or "0x0", 16)
        gp = max(gp, int(gwei * 1e9))
        nonce = int(await self.rpc("eth_getTransactionCount", [addr, "pending"]), 16)
        raw, h = evm.sign_tx(key, nonce, gp, int(est * 1.25) + 10000, to, value, data, CHAIN_ID)
        try:
            await self.rpc("eth_sendRawTransaction", [raw])
        except Exception as e:
            if "known" not in str(e).lower() and "already" not in str(e).lower():
                raise ChainError("envio recusado: " + str(e)[:160])
        for _ in range(120):
            await asyncio.sleep(1)
            try:
                rc = await self.rpc("eth_getTransactionReceipt", [h])
            except Exception:
                rc = None
            if rc:
                if int(rc.get("status") or "0x0", 16) != 1:
                    raise ChainError("transação falhou na rede (" + h + ")")
                rc["_gas_bnb"] = int(rc.get("gasUsed") or "0x0", 16) * int(rc.get("effectiveGasPrice") or hex(gp), 16) / 1e18
                return rc
        raise ChainError("sem confirmação em 2 min (" + h + "): confira no BscScan")

    async def ensure_allowance(self, key: int, addr: str, token: str, spender: str, amount: int, gwei: float) -> None:
        w = evm.words(await self.call(token, SEL["allowance"] + evm.w_addr(addr) + evm.w_addr(spender)))
        if w and w[0] >= amount:
            return
        await self.send(key, addr, token, evm.call_data(SEL["approve"], spender, MAX), 0, gwei)

    @staticmethod
    def received(rc: dict, token: str, addr: str) -> int:
        """Quanto do token chegou na carteira (eventos Transfer do recibo)."""
        n = 0
        for lg in rc.get("logs") or []:
            tp = lg.get("topics") or []
            if (lg.get("address") or "").lower() == token and len(tp) >= 3 and tp[0] == T_TRANSFER and tp[2][-40:] == addr[2:]:
                n += int(lg.get("data") or "0x0", 16)
        return n

    # ------------------------------------------------------------------ compra
    async def buy(self, key: int, addr: str, token: str, quote: str, amt_bnb: float, bnb_usd: float | None, slip: float,
                  gwei: float) -> dict:
        value = int(amt_bnb * 1e18)
        stable = quote not in ("", ZERO)
        if stable and not bnb_usd:
            raise ChainError("sem a cotação BNB/dólar para calcular o mínimo")
        funds = int(value * bnb_usd * 0.995) if stable else value          # na moeda da curva (0,25% da troca BNB→USDT + folga)
        w = evm.words(await self.call(HELPER3, evm.call_data(SEL["try_buy"], token, 0, funds)))
        if len(w) < 8:
            raise ChainError("tryBuy sem resposta")
        if ("0x%040x" % w[0]) != TM2:
            raise ChainError("token de outro gerenciador da Four.Meme (só o TokenManager2 é suportado)")
        min_amt = int(w[2] * (1 - slip / 100))
        if stable:
            data, to = evm.call_data(SEL["buy_eth"], 0, token, addr, value, min_amt), HELPER3
        else:
            data, to = evm.call_data(SEL["buy"], token, value, min_amt), TM2
        rc = await self.send(key, addr, to, data, value, gwei)
        got = self.received(rc, token, addr)
        if got <= 0:
            raise ChainError("comprou mas não achei o token no recibo (" + rc.get("transactionHash", "") + ")")
        return {"raw": got, "bnb": amt_bnb + rc["_gas_bnb"], "tx": rc.get("transactionHash"), "gas": rc["_gas_bnb"]}

    # ------------------------------------------------------------------ venda
    async def sell(self, key: int, addr: str, token: str, quote: str, raw: int, graduated: bool, slip: float, gwei: float) -> dict:
        have = await self.token_balance(token, addr)
        raw = min(raw, have)
        if raw <= 0:
            raise ChainError("a carteira não tem mais este token")
        stable = quote not in ("", ZERO)
        gas = 0.0
        if not graduated:
            w = evm.words(await self.call(HELPER3, evm.call_data(SEL["try_sell"], token, raw)))
            if len(w) < 4:
                raise ChainError("trySell sem resposta")
            min_f = int((w[2] - w[3]) * (1 - slip / 100))
            await self.ensure_allowance(key, addr, token, TM2, raw, gwei)
            rc = await self.send(key, addr, TM2, evm.call_data(SEL["sell"], token, raw, min_f), 0, gwei)
            gas += rc["_gas_bnb"]
            got_q = 0
            for lg in rc.get("logs") or []:
                if (lg.get("address") or "").lower() == TM2 and (lg.get("topics") or [""])[0] == T_SALE:
                    d = evm.words(lg.get("data"))
                    if len(d) >= 6 and ("0x%040x" % d[1]) == addr:
                        got_q += d[4] - d[5]
            tx = rc.get("transactionHash")
            if not stable:
                return {"bnb": got_q / 1e18 - gas, "tx": tx, "gas": gas}
            # recebeu a moeda da curva (USDT…): troca por BNB na PancakeSwap V2
            out = await self._swap_to_bnb(key, addr, [quote, WBNB], got_q, slip, gwei)
            return {"bnb": out["bnb"] - gas - out["gas"], "tx": out["tx"] or tx, "gas": gas + out["gas"]}
        path = None
        for p in ([token, WBNB], [token, quote, WBNB] if stable else None):
            pw = evm.words(await self.call(FACTORY_V2, evm.call_data(SEL["pair"], p[0], p[1]))) if p else []
            if pw and pw[0]:
                path = p
                break
        if not path:
            raise ChainError("o token foi para a PancakeSwap, mas não achei o par V2: venda manual pela PancakeSwap")
        out = await self._swap_to_bnb(key, addr, path, raw, slip, gwei)
        return {"bnb": out["bnb"] - out["gas"], "tx": out["tx"], "gas": out["gas"]}

    async def _swap_to_bnb(self, key: int, addr: str, path: list, amount: int, slip: float, gwei: float) -> dict:
        if amount <= 0:
            return {"bnb": 0.0, "tx": None, "gas": 0.0}
        w = evm.words(await self.call(ROUTER_V2, evm.call_data(SEL["amounts_out"], amount, path)))
        if len(w) < 2 + len(path):
            raise ChainError("PancakeSwap sem cotação para a venda")
        min_out = int(w[-1] * (1 - slip / 100))
        await self.ensure_allowance(key, addr, path[0], ROUTER_V2, amount, gwei)
        data = evm.call_data(SEL["swap_eth"], amount, min_out, path, addr, int(time.time()) + 300)
        rc = await self.send(key, addr, ROUTER_V2, data, 0, gwei)
        got = sum(int(lg.get("data") or "0x0", 16) for lg in rc.get("logs") or []
                  if (lg.get("address") or "").lower() == WBNB and (lg.get("topics") or [""])[0] == T_WITHDRAW)
        return {"bnb": got / 1e18, "tx": rc.get("transactionHash"), "gas": rc["_gas_bnb"]}


def new_position(tr: dict, res: dict, t: float, px: float | None, quote: str) -> dict:
    tokens = res["raw"] / 1e18
    return {"id": "r" + uuid.uuid4().hex[:15], "wallet": tr["wallet"], "token": tr["token"], "open_t": t,
            "px_in": res["bnb"] / tokens if tokens else px, "trader_px": px, "tokens": tokens, "tokens_left": tokens,
            "raw": str(res["raw"]), "raw_left": str(res["raw"]), "bnb_in": round(res["bnb"], 9), "proceeds": 0.0,
            "fees": res.get("gas", 0), "px_now": px, "px_t": t, "best_pct": 0.0, "worst_pct": 0.0,
            "lag_s": round(max(0.0, t - tr["t"]), 1), "tx_in": res["tx"], "aba": "top", "quote": quote, "real": True}
