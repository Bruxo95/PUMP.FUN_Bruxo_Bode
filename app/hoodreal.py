"""Robinhood Chain, carteira REAL da cópia (0.32.279). Começa DESLIGADA; só o dono liga, na tela, com a confirmação LIGAR.

Pedido do dono em 10/11/2026 ("faz 1 a 4", item 4). Mesma decisão da cópia fictícia (o trader do ranking comprou → compra; ele
vendeu → vende a mesma parte; tempo máximo e stop), com valor e limites próprios, e só nas compras novas depois de ligar.

Compra e venda pela Uniswap V4, com os mesmos contratos e o mesmo formato de transação da compra do Dormant (0.32.257/258), que
foram conferidos byte a byte com trocas reais de GLC: Universal Router oficial, pool conferido (keccak da chave = id do pool,
pago em ETH), mínimo a receber pelo Quoter menos a folga, o token cai na própria carteira (TAKE_ALL paga quem chamou).
Na venda o roteador puxa o token pelo Permit2: logo depois da compra a carteira autoriza o Permit2 e o Permit2 autoriza o
roteador, os dois só na quantidade comprada (a venda depois sai numa transação só). Toda transação passa por eth_estimateGas
antes: se daria erro, não é enviada. A trava geral PUMP_REAL_ALLOWED também vale aqui.
"""
from __future__ import annotations

import asyncio
import time
import uuid

from . import evm
from .dormant_buy import (PERMIT2, SEL_P2_ALLOW, SEL_P2_APPROVE, T_V4_SWAP, v4_data, v4_pool_id, v4_quote_data,  # noqa: F401
                          v4_swap_eth)

CHAIN_ID = 4663
PM = "0x8366a39cc670b4001a1121b8f6a443a643e40951"
UR = "0x8876789976decbfcbbbe364623c63652db8c0904"        # Universal Router oficial da Robinhood (conferido em 07/11/2026)
QUOTER = "0x8dc178efb8111bb0973dd9d722ebeff267c98f94"
ZERO = "0x" + "0" * 40
SEL_APPROVE = evm.selector("approve(address,uint256)")
SEL_ALLOW = evm.selector("allowance(address,address)")
SEL_BALANCE = evm.selector("balanceOf(address)")
SEL_EXTSLOAD = evm.selector("extsload(bytes32)")
T_TRANSFER = "0x" + evm.keccak256(b"Transfer(address,address,uint256)").hex()
GAS_RESERVE = 0.0005                # ETH que fica na carteira para o gás das vendas
RETRY_S = 60                        # venda automática que falhou espera 1 min antes de tentar de novo
NO_LIQ_RETRY_S = 600                # pool sem liquidez: confere de novo a cada 10 min (o criador pode devolver)
RECIBO_S = 60

# 0.32.287 (pedido do dono: "a carteira real tá faltando umas coisas que tem na fictícia"): tempo máximo e stop próprios da REAL
REAL_DEFAULT = {"real_on": False, "real_eth_por_compra": 0.002, "real_max_abertas": 5, "real_slip_pct": 15.0, "real_perda_dia": 0.01,
                "real_max_hold_h": 6.0, "real_stop_pct": 0.0,
                # 0.32.290 (pedido do dono): sair quando o trader / o dev sai da moeda e stop móvel (mesma regra da Solana)
                "real_espelho": True, "real_um_por_token": True, "real_sair_travado": True, "real_sair_trader": True, "real_trader_so_lucro": True, "real_sair_dev": True, "real_trail_on": True, "real_trail_ativa_pct": 20.0,
                "real_trail_dist_pct": 10.0}
REAL_LIMITS = {"real_eth_por_compra": (0.0002, 0.5), "real_max_abertas": (1, 30), "real_slip_pct": (1, 49), "real_perda_dia": (0.0005, 5),
               "real_max_hold_h": (0.1, 168), "real_stop_pct": (0, 100), "real_trail_ativa_pct": (1, 10000),
               "real_trail_dist_pct": (1, 1000)}
REAL_BOOLS = ("real_espelho", "real_um_por_token", "real_sair_travado", "real_sair_trader", "real_trader_so_lucro", "real_sair_dev", "real_trail_on")


def clean(raw: dict | None, base: dict | None = None) -> dict:
    """Valores da REAL. real_on NÃO passa por aqui: só pela rota de ligar, com a confirmação."""
    out = dict(REAL_DEFAULT)
    out.update({k: v for k, v in (base or {}).items() if k in REAL_DEFAULT})
    for k, v in (raw or {}).items():
        if k in REAL_BOOLS:
            out[k] = bool(v)
            continue
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


def _taxa(x: dict) -> float:
    v = x.get("taxas_eth")
    return float(v if v is not None else (x.get("fees") or 0.0))


class ChainError(Exception):
    pass


class SellBlocked(ChainError):
    """O pool não aceita a venda do token (golpe que trava venda ou pool sem ETH)."""


class NoLiquidity(SellBlocked):
    """0.32.315 (casos TEXEL e mihao do dono, 11/11): o criador tirou toda a liquidez do pool (ModifyLiquidity negativo de 100% às
    13:00:30 e 14:01:22). A liquidez ativa do pool é zero: não existe ETH para receber, a venda é impossível e o token vale 0."""


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

    def ev(self, t: float, wallet: str, token: str, acao: str, motivo: str = "", tx: str | None = None) -> None:
        self.events.insert(0, {"t": t, "wallet": wallet, "token": token, "acao": acao, "motivo": motivo, "tx": tx, "real": True})
        del self.events[200:]

    @staticmethod
    def value_now(p: dict, slip: float) -> float:
        px = p.get("px_now")
        if px is None:                               # 0.32.315: 0 é preço de verdade (pool sem liquidez), não "sem preço"
            px = p.get("px_in") or 0
        return p["tokens_left"] * px * (1 - (p.get("fee") or 0) - slip / 100)

    def pnl_now(self, p: dict, slip: float) -> tuple[float, float]:
        v = p["proceeds"] + max(0.0, self.value_now(p, slip)) - p["eth_in"]
        return v, (100 * v / p["eth_in"] if p["eth_in"] else 0.0)

    def lost_today(self, now: float) -> float:
        day = now - now % 86400
        return -sum(x["pnl_eth"] for x in self.trades if x["close_t"] >= day and x["pnl_eth"] < 0)

    def wallet(self, now: float, slip: float, periods) -> dict:
        open_val = sum(max(0.0, self.value_now(p, slip)) for p in self.pos.values())
        closed = self.trades
        wins = [x for x in closed if x["pnl_eth"] > 0]
        aberto = sum(self.pnl_now(p, slip)[0] for p in self.pos.values())
        realizado = sum(x["pnl_eth"] for x in closed)
        inv = sum(x["eth_in"] for x in closed) + sum(p["eth_in"] for p in self.pos.values())
        saldo = self.balance
        return {"saldo": None if saldo is None else round(saldo, 6), "em_posicoes": round(open_val, 6),
                "total": None if saldo is None else round(saldo + open_val, 6), "inicial": None,
                "resultado": round(realizado + aberto, 6), "resultado_pct": round(100 * (realizado + aberto) / inv, 2) if inv else 0,
                "abertas": len(self.pos), "fechadas": len(closed), "acerto": round(100 * len(wins) / len(closed), 1) if closed else None,
                "realizado": round(realizado, 6), "periodos": periods(closed, now), "endereco": self.address,
                "taxas": round(sum(_taxa(x) for x in closed) + sum(p.get("fees") or 0.0 for p in self.pos.values()), 6),
                "taxas_fechadas": round(sum(_taxa(x) for x in closed), 6)}

    def close(self, p: dict, t: float, motivo: str, px: float | None) -> dict:
        pnl = p["proceeds"] - p["eth_in"]
        # 0.32.294 (pedido do Bruxo): taxas da REAL = gás pago de verdade + taxa do pool estimada nos dois lados (ela já sai do preço)
        f = float(p.get("fee") or 0.0)
        gas = float(p.get("fees") or 0.0)
        pool = (p["eth_in"] - gas) * f + (p["proceeds"] / (1 - f) * f if f < 1 else 0.0)
        tr = {**{k: p.get(k) for k in ("id", "wallet", "token", "open_t", "px_in", "trader_px", "eth_in", "best_pct", "worst_pct",
                                       "lag_s", "tx_in", "aba", "vendas", "fees", "nome", "simbolo", "px_src")},
              "close_t": t, "px_out": px, "eth_out": round(p["proceeds"], 9), "pnl_eth": round(pnl, 9),
              "pnl_pct": round(100 * pnl / p["eth_in"], 2) if p["eth_in"] else 0.0, "motivo": motivo, "real": True,
              "tx_out": p.get("tx_last"), "taxas_eth": round(gas + max(0.0, pool), 9)}
        self.pos.pop(p["id"], None)
        self.dirty_pos.discard(p["id"])
        self.closed_pos.add(p["id"])
        self.trades.insert(0, tr)
        del self.trades[3000:]
        self.new_trades.append(tr)
        return tr


def new_position(tr: dict, res: dict, t: float, px: float | None, key: list) -> dict:
    from .hoodcopy import pool_fee
    tokens = res["raw"] / 1e18
    return {"id": "r" + uuid.uuid4().hex[:15], "wallet": tr["wallet"], "token": tr["token"], "open_t": t,
            "px_in": (res["eth"] - res.get("gas", 0)) / tokens if tokens else None, "trader_px": px, "trader_eth": tr.get("eth"),
            "tokens": tokens, "tokens_left": tokens, "raw_left": str(res["raw"]), "eth_in": round(res["eth"], 9), "proceeds": 0.0,
            "fees": res.get("gas", 0), "fee": pool_fee(key, tr.get("fee")), "px_now": px, "px_t": t, "best_pct": 0.0, "worst_pct": 0.0,
            "lag_s": round(max(0.0, t - tr["t"]), 1), "tx_in": res["tx"], "aba": "manual" if not tr.get("_auto", True) else "top", "key": key, "real": True}


class Chain:
    """Envio na Robinhood Chain com a chave da conta. rpc = HoodWatch.rpc (o RPC grátis oficial)."""

    def __init__(self, rpc):
        self.rpc = rpc
        self.chain_ok = False

    async def call(self, to: str, data: str, frm: str | None = None) -> str:
        p = {"to": to, "data": data}
        if frm:
            p["from"] = frm
        try:
            return await self.rpc("eth_call", [p, "latest"]) or "0x"
        except Exception as e:
            raise ChainError("simulação recusada: " + str(e)[:160])

    async def balance(self, addr: str) -> int:
        return int(await self.rpc("eth_getBalance", [addr, "latest"]) or "0x0", 16)

    async def token_balance(self, token: str, addr: str) -> int:
        """0.32.307 (caso 4Robinhood, 11/11: -100% falso): resposta vazia do RPC ("0x") NÃO é saldo zero: é leitura que falhou."""
        w = evm.words(await self.call(token, SEL_BALANCE + evm.w_addr(addr)))
        if not w:
            raise ChainError("o RPC não devolveu o saldo do token (leitura vazia); tenta de novo")
        return w[0]

    async def liquidity(self, key: list) -> int:
        """Liquidez ativa do pool V4 (slot 3 do Pool.State no PoolManager: keccak(id, 6) + 3), lida por extsload. 0 = sem liquidez."""
        base = int.from_bytes(evm.keccak256(bytes.fromhex(v4_pool_id(key)[2:]) + (6).to_bytes(32, "big")), "big")
        w = evm.words(await self.call(PM, SEL_EXTSLOAD + evm.w_int(base + 3)))
        if not w:
            raise ChainError("o RPC não devolveu a liquidez do pool")
        return w[0] & ((1 << 128) - 1)

    async def quote(self, key: list, amount: int, buy: bool) -> int:
        w = evm.words(await self.call(QUOTER, v4_quote_data(key, amount, buy)))
        return w[0] if w else 0

    async def send(self, key: int, addr: str, to: str, data: str, value: int) -> dict:
        """Simula (estimateGas: se a transação daria erro, recusa aqui), assina, envia e espera o recibo."""
        if not self.chain_ok:
            if int(await self.rpc("eth_chainId", []) or "0x0", 16) != CHAIN_ID:
                raise ChainError("o RPC respondeu de outra rede: nada foi enviado")
            self.chain_ok = True
        try:
            est = int(await self.rpc("eth_estimateGas", [{"from": addr, "to": to, "data": data, "value": hex(value)}]), 16)
        except Exception as e:
            raise ChainError("a rede recusou na simulação: " + str(e)[:160])
        gp = int(int(await self.rpc("eth_gasPrice", []) or "0x0", 16) * 1.1)
        nonce = int(await self.rpc("eth_getTransactionCount", [addr, "pending"]), 16)
        raw, h = evm.sign_tx(key, nonce, gp, int(est * 1.3) + 20000, to, value, data, CHAIN_ID)
        try:
            await self.rpc("eth_sendRawTransaction", [raw])
        except Exception as e:
            if "known" not in str(e).lower() and "already" not in str(e).lower():
                raise ChainError("envio recusado: " + str(e)[:160])
        t0 = time.monotonic()
        while time.monotonic() - t0 < RECIBO_S:
            await asyncio.sleep(0.5)
            try:
                rc = await self.rpc("eth_getTransactionReceipt", [h])
            except Exception:
                rc = None
            if rc:
                if int(rc.get("status") or "0x0", 16) != 1:
                    raise ChainError("transação falhou na rede (" + h + ")")
                rc["_gas_eth"] = int(rc.get("gasUsed") or "0x0", 16) * int(rc.get("effectiveGasPrice") or hex(gp), 16) / 1e18
                return rc
        raise ChainError("sem confirmação em 1 min (" + h + "): confira no explorador")

    @staticmethod
    def received(rc: dict, token: str, addr: str) -> int:
        n = 0
        for lg in rc.get("logs") or []:
            tp = lg.get("topics") or []
            if (lg.get("address") or "").lower() == token and len(tp) >= 3 and tp[0] == T_TRANSFER and tp[2][-40:].lower() == addr[2:]:
                n += int(lg.get("data") or "0x0", 16)
        return n

    @staticmethod
    def checked(key: list, token: str) -> None:
        if len(key) != 5 or key[0] != ZERO or key[1] != token:
            raise ChainError("pool V4 não conferido (precisa ser o par ETH / este token): nada foi enviado")

    async def authorize(self, key: int, addr: str, token: str, amount: int, until: float) -> float:
        """Token → Permit2 e Permit2 → Universal Router, só na quantidade pedida. Devolve o gás gasto."""
        gas = 0.0
        w = evm.words(await self.call(token, SEL_ALLOW + evm.w_addr(addr) + evm.w_addr(PERMIT2)))
        if not w or w[0] < amount:
            if w and w[0] > 0:
                gas += (await self.send(key, addr, token, SEL_APPROVE + evm.w_addr(PERMIT2) + evm.w_int(0), 0))["_gas_eth"]
            gas += (await self.send(key, addr, token, SEL_APPROVE + evm.w_addr(PERMIT2) + evm.w_int(amount), 0))["_gas_eth"]
        w = evm.words(await self.call(PERMIT2, SEL_P2_ALLOW + evm.w_addr(addr) + evm.w_addr(token) + evm.w_addr(UR)))
        if len(w) < 2 or w[0] < amount or w[1] < time.time() + 120:
            data = SEL_P2_APPROVE + evm.w_addr(token) + evm.w_addr(UR) + evm.w_int(amount) + evm.w_int(int(until))
            gas += (await self.send(key, addr, PERMIT2, data, 0))["_gas_eth"]
        return gas

    async def buy(self, key: int, addr: str, token: str, pkey: list, amt_eth: float, slip: float, until: float) -> dict:
        self.checked(pkey, token)
        value = int(amt_eth * 1e18)
        out = await self.quote(pkey, value, True)
        if out <= 0:
            raise ChainError("o pool não cotou a compra")
        data = v4_data(pkey, value, int(out * (1 - slip / 100)), int(time.time()) + 120)
        rc = await self.send(key, addr, UR, data, value)
        got = self.received(rc, token, addr)
        if got <= 0:
            raise ChainError("comprou mas não achei o token no recibo (" + rc.get("transactionHash", "") + ")")
        gas = rc["_gas_eth"]
        try:                                         # deixa a venda pronta: autoriza só o que comprou
            gas += await self.authorize(key, addr, token, got, until)
        except Exception:
            pass                                     # a venda autoriza de novo se precisar
        return {"raw": got, "eth": amt_eth + gas, "tx": rc.get("transactionHash"), "gas": gas}

    async def sell_quote(self, pkey: list, raw: int) -> tuple[int, int]:
        """0.32.309 (caso HOLD, 11/11: "simulação recusada: execution reverted" ao vender): cota a venda inteira; se o pool recusar,
        tenta metade, um quarto e um oitavo (pool com pouca liquidez de ETH aceita só parte). Devolve (quantidade, ETH que volta)."""
        last = None
        for part in (1, 2, 4, 8):
            amt = raw // part
            if amt <= 0:
                break
            try:
                out = await self.quote(pkey, amt, False)
            except ChainError as e:
                last = e
                continue
            if out > 0:
                return amt, out
        try:
            liq = await self.liquidity(pkey)
        except ChainError:
            liq = None
        if liq == 0:
            raise NoLiquidity("o criador tirou toda a liquidez do pool (rug pull): não há ETH para receber, a venda é impossível e o token vale 0")
        raise SellBlocked("o pool recusou cotar a venda (nem 1/8 da posição): o token pode estar bloqueando vendas (golpe) ou o pool ficou sem ETH"
                          + (" · " + str(last)[-80:] if last else ""))

    async def sell(self, key: int, addr: str, token: str, pkey: list, raw: int, slip: float) -> dict:
        self.checked(pkey, token)
        have = await self.token_balance(token, addr)
        raw = min(raw, have)
        if raw <= 0:
            raise ChainError("a carteira não tem mais este token")
        raw, out = await self.sell_quote(pkey, raw)
        try:
            gas = await self.authorize(key, addr, token, raw, time.time() + 1800)
        except ChainError as e:
            raise ChainError("a autorização do token para a venda foi recusada: " + str(e)[-120:])
        out = await self.quote(pkey, raw, False)
        if out <= 0:
            raise ChainError("o pool não cotou a venda")
        rc = await self.send(key, addr, UR, v4_data(pkey, raw, int(out * (1 - slip / 100)), int(time.time()) + 120, sell=True), 0)
        gas += rc["_gas_eth"]
        got = v4_swap_eth(rc.get("logs") or [], PM)
        return {"eth": got / 1e18 - gas, "raw": raw, "tx": rc.get("transactionHash"), "gas": gas}
