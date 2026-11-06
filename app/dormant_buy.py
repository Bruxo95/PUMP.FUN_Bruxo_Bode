"""Dormant: comprar e vender uma moeda da lista na DEX, à mão (0.32.242 e 0.32.243, pedidos do dono em 06/11/2026). Isolado do resto:
nada aqui fala com o motor da Solana, da BNB ou da Robinhood. Nunca compra nem vende sozinho.

Só entram as redes onde dá para comprar pelo caminho mais seguro:
- Redes EVM: só o roteador oficial da DEX, com endereço FIXO aqui (conferido na rede em 06/11/2026: eth_call de factory() e
  WETH() batem com as fábricas oficiais). A transação é montada aqui, não por um agregador. Comprar com a moeda da rede não
  precisa de approve, então nenhum contrato fica autorizado a mexer nos tokens da carteira. O recebedor é sempre a própria carteira.
- Solana: Jupiter, com a conferência de txguard (programas, valor, slippage, assinante) + o token tem que cair na conta da carteira.
Rede que não está aqui (TRON, Cardano, Stellar…) não mostra o botão.

Antes de assinar, sempre: chave geral ligada (começa desligada), trava PUMP_REAL_ALLOWED, senha de compra, limites por compra e
por dia em dólar, cotação com validade de 60 s e uso único, cotação refeita na hora, simulação da rede, conferência do token na
GoPlus e comparação com o preço da CoinGecko. Falha fechada: o que não dá para conferir não compra. O endereço do token vem da lista
do servidor (CoinGecko), nunca do navegador. A chave em texto só existe durante a assinatura; nunca vai para log, banco ou tela.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import math
import re
import time
import uuid
from datetime import datetime, timezone

from . import dormant_vault as vault
from . import evm
from .crypto import CryptoError

log = logging.getLogger("pump.dormant.compra")

ZERO = "0x" + "0" * 40
T_TRANSFER = "0x" + evm.keccak256(b"Transfer(address,address,uint256)").hex()
SEL_AMOUNTS = evm.selector("getAmountsOut(uint256,address[])")
SEL_SWAP_ETH = evm.selector("swapExactETHForTokensSupportingFeeOnTransferTokens(uint256,address[],address,uint256)")
SEL_SWAP_AVAX = evm.selector("swapExactAVAXForTokensSupportingFeeOnTransferTokens(uint256,address[],address,uint256)")
SEL_V3_QUOTE = evm.selector("quoteExactInputSingle((address,address,uint256,uint24,uint160))")
SEL_V3_SWAP = evm.selector("exactInputSingle((address,address,uint24,address,uint256,uint256,uint256,uint160))")
SEL_DECIMALS = evm.selector("decimals()")
V3_ROUTER = "0xe592427a0aece92de3edee1f18e0157c05861564"     # Uniswap V3 (mesmo endereço nas 3 redes; fábrica 0x1f98… conferida)
V3_QUOTER = "0x61ffe014ba17989e743c5f6cb21bf9697530b21e"
V3_FEES = (500, 3000, 10000)
WSOL = "So11111111111111111111111111111111111111112"
T_WITHDRAW = "0x" + evm.keccak256(b"Withdrawal(address,uint256)").hex()
SEL_APPROVE = evm.selector("approve(address,uint256)")
SEL_ALLOW = evm.selector("allowance(address,address)")
SEL_BALANCE = evm.selector("balanceOf(address)")
SEL_SELL_ETH = evm.selector("swapExactTokensForETHSupportingFeeOnTransferTokens(uint256,uint256,address[],address,uint256)")
SEL_SELL_AVAX = evm.selector("swapExactTokensForAVAXSupportingFeeOnTransferTokens(uint256,uint256,address[],address,uint256)")
SEL_MULTI = evm.selector("multicall(bytes[])")
SEL_UNWRAP = evm.selector("unwrapWETH9(uint256,address)")

# chave = id da rede na CoinGecko. Tudo conferido em 06/11/2026 (chain id, código do contrato, fábrica, moeda embrulhada, ponte).
CHAINS = {
    "solana": {"nome": "Solana", "tipo": "solana", "moeda": "SOL", "cg": "solana", "dec": 9, "dex": "Jupiter", "expl": "https://solscan.io/tx/",
               "reserva": 0.005},
    "ethereum": {"nome": "Ethereum", "tipo": "evm", "id": 1, "moeda": "ETH", "cg": "ethereum", "dec": 18, "dex": "Uniswap", "expl": "https://etherscan.io/tx/",
                 "rpc": "https://ethereum-rpc.publicnode.com", "router": "0x7a250d5630b4cf539739df2c5dacb4c659f2488d",
                 "wrapped": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2", "ponte": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", "v3": True,
                 # sem isto o robô de sandwich leva quase toda a folga de preço; o Flashbots Protect não põe na fila pública
                 "envio": "https://rpc.flashbots.net"},
    "binance-smart-chain": {"nome": "BNB Chain", "tipo": "evm", "id": 56, "moeda": "BNB", "cg": "binancecoin", "dec": 18, "dex": "PancakeSwap", "expl": "https://bscscan.com/tx/",
                            "rpc": "https://bsc-rpc.publicnode.com", "router": "0x10ed43c718714eb63d5aa57b78b54704e256024e",
                            "wrapped": "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c", "ponte": "0x55d398326f99059ff775485246999027b3197955"},
    "base": {"nome": "Base", "tipo": "evm", "id": 8453, "moeda": "ETH", "cg": "ethereum", "dec": 18, "dex": "Uniswap", "expl": "https://basescan.org/tx/",
             "rpc": "https://base-rpc.publicnode.com", "router": "0x4752ba5dbc23f44d87826276bf6fd6b1c372ad24",
             "wrapped": "0x4200000000000000000000000000000000000006", "ponte": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"},
    "polygon-pos": {"nome": "Polygon", "tipo": "evm", "id": 137, "moeda": "POL", "cg": "polygon-ecosystem-token", "dec": 18, "dex": "QuickSwap e Uniswap", "expl": "https://polygonscan.com/tx/",
                    "rpc": "https://polygon-bor-rpc.publicnode.com", "router": "0xa5e0829caced8ffdd4de3c43696c57f7d7a678ff",
                    "wrapped": "0x0d500b1d8e8ef31e21c99d1db9a6444d3adf1270", "ponte": "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359", "v3": True},
    "avalanche": {"nome": "Avalanche", "tipo": "evm", "id": 43114, "moeda": "AVAX", "cg": "avalanche-2", "dec": 18, "dex": "Trader Joe", "expl": "https://snowtrace.io/tx/",
                  "rpc": "https://avalanche-c-chain-rpc.publicnode.com", "router": "0x60ae616a2155ee3d9a68541ba4544862310933d4",
                  "wrapped": "0xb31f66aa3c1e785363f0875a1b74e27b85fd66c7", "ponte": "0xb97ef9ef8734c71904d8002f8b6bc66dd9c48a6e", "swap_sel": SEL_SWAP_AVAX, "sell_sel": SEL_SELL_AVAX},
    "arbitrum-one": {"nome": "Arbitrum", "tipo": "evm", "id": 42161, "moeda": "ETH", "cg": "ethereum", "dec": 18, "dex": "Uniswap", "expl": "https://arbiscan.io/tx/",
                     "rpc": "https://arbitrum-one-rpc.publicnode.com", "router": "0x4752ba5dbc23f44d87826276bf6fd6b1c372ad24",
                     "wrapped": "0x82af49447d8a07e3bd95bd0d56f35241523fbab1", "ponte": "0xaf88d065e77c8cc2239327c5edb3a432268e5831", "v3": True},
}
EVM_CHAINS = [k for k, c in CHAINS.items() if c["tipo"] == "evm"]

# 0.32.246 (dono, 06/11/2026: abasteceu US$ 7 de gás e ficou sem poder comprar): gás tem limite próprio e não conta no das compras
CFG_DEFAULT = {"on": False, "max_usd": 50.0, "dia_usd": 200.0, "slip_pct": 3.0, "gas_max_usd": 10.0, "gas_dia_usd": 50.0}
CFG_LIMITS = {"max_usd": (1.0, 10000.0), "dia_usd": (1.0, 50000.0), "slip_pct": (0.1, 15.0), "gas_max_usd": (1.0, 25.0), "gas_dia_usd": (1.0, 200.0)}
QUOTE_TTL_S = 60                  # depois disso a cotação vale nada e o botão pede outra
MAX_TRIES, LOCK_S = 5, 15 * 60    # 5 senhas erradas seguidas: compra e chaves travadas por 15 min (sobrevive ao reinício)
PENDENTE_S = 15 * 60              # compra sem confirmação segura outra na mesma rede por 15 min (nonce, compra dobrada)
EXPIRA_S = 6 * 3600               # sem nada depois disso: marca como não confirmada
RECIBO_S = 90
RECIBO_PASSO = 3
PRECO_AVISO, PRECO_BLOQ = 10.0, 25.0     # % pagando acima da CoinGecko
IMPACTO_AVISO, IMPACTO_BLOQ = 10.0, 25.0  # % que a própria compra move o preço (pool pequeno)
TAXA_TOKEN_MAX = 10.0
VENDA_BLOQ = 50.0                 # % abaixo da CoinGecko que barra a venda (dormente tem pool ruim: até aqui é só aviso)
# campo da GoPlus → motivo. Bloqueia = não deixa vender ou o dono mexe no saldo. Aviso = aparece, a decisão é do dono.
GP_BLOQ = {"is_honeypot": "honeypot: não deixa vender", "cannot_sell_all": "não deixa vender tudo", "cannot_buy": "não deixa comprar",
           "owner_change_balance": "o dono pode mudar o saldo das carteiras", "selfdestruct": "o contrato pode se autodestruir"}
GP_AVISO = {"transfer_pausable": "o dono pode pausar as transferências", "is_blacklisted": "tem lista negra de carteiras",
            "hidden_owner": "dono escondido", "slippage_modifiable": "o dono pode mudar a taxa de venda",
            "trading_cooldown": "espera obrigatória entre compra e venda", "is_mintable": "o dono pode criar mais moedas",
            "is_proxy": "o contrato pode ser trocado pelo dono", "can_take_back_ownership": "o dono pode voltar a mandar no contrato"}
SOL_BLOQ = {"balance_mutable_authority": "o dono pode mudar o saldo das carteiras", "closable": "o dono pode fechar o token",
            "non_transferable": "o token não pode ser transferido"}
SOL_AVISO = {"freezable": "o dono pode congelar carteiras", "mintable": "o dono pode criar mais moedas",
             "metadata_mutable": "o dono pode mudar os dados do token", "transfer_hook": "o token roda um programa a cada transferência"}
ADDR_EVM = re.compile(r"^0x[0-9a-f]{40}$")
ADDR_SOL = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


class BuyError(Exception):
    """Motivo já em linguagem de usuário. Nunca leva chave nem senha."""


def clean_cfg(raw: dict | None, base: dict | None = None) -> dict:
    out = {**CFG_DEFAULT, **{k: v for k, v in (base or {}).items() if k in CFG_DEFAULT}}
    for k, (lo, hi) in CFG_LIMITS.items():
        if k not in (raw or {}):
            continue
        try:
            v = float(raw[k])
        except (TypeError, ValueError):
            continue
        if math.isfinite(v):
            out[k] = round(min(hi, max(lo, v)), 4)
    return out


def buyable(watch, cid: str | None) -> list[str]:
    """Redes onde esta moeda pode ser comprada aqui. A principal vem primeiro."""
    if not cid:
        return []
    adr = watch.addr.get(cid) or {}
    first = watch.chain_of(cid)
    return sorted([k for k, v in adr.items() if k in CHAINS and valid_token(k, v)], key=lambda k: k != first)


def valid_token(chain: str, adr: str) -> bool:
    c = CHAINS.get(chain)
    if not c or not isinstance(adr, str):
        return False
    return bool(ADDR_SOL.match(adr)) if c["tipo"] == "solana" else bool(ADDR_EVM.match(adr.lower())) and adr.lower() != ZERO


def key_address(chain: str, text: str) -> str:
    """Endereço público da chave colada. ValueError com texto para a tela, sem o valor da chave."""
    if CHAINS[chain]["tipo"] == "solana":
        from .solana_wallet import parse_keypair
        return str(parse_keypair(text).pubkey())
    return evm.address_of(evm.parse_key(text))


def v2_data(c: dict, min_out: int, path: list, addr: str, deadline: int) -> str:
    return evm.call_data(c.get("swap_sel") or SEL_SWAP_ETH, min_out, path, addr, deadline)


def v3_data(tok_in: str, tok_out: str, fee: int, addr: str, deadline: int, amount: int, min_out: int) -> str:
    return (SEL_V3_SWAP + evm.w_addr(tok_in) + evm.w_addr(tok_out) + evm.w_int(fee) + evm.w_addr(addr) +
            evm.w_int(deadline) + evm.w_int(amount) + evm.w_int(min_out) + evm.w_int(0))


def v3_sell_data(tok_in: str, wrapped: str, fee: int, addr: str, deadline: int, amount: int, min_out: int) -> str:
    """Uniswap V3 entrega a moeda embrulhada: troca para o próprio roteador e ele desembrulha e paga a carteira, na mesma transação."""
    a = v3_data(tok_in, wrapped, fee, V3_ROUTER, deadline, amount, min_out)[2:]
    b = (SEL_UNWRAP + evm.w_int(min_out) + evm.w_addr(addr))[2:]
    def enc(h):
        return evm.w_int(len(h) // 2) + h + "0" * ((64 - len(h) % 64) % 64)
    ea, eb = enc(a), enc(b)
    return SEL_MULTI + evm.w_int(32) + evm.w_int(2) + evm.w_int(64) + evm.w_int(64 + len(ea) // 2) + ea + eb


def judge_goplus(chain: str, d: dict | None) -> tuple[list[str], list[str]]:
    """(bloqueia, avisos) da resposta da GoPlus."""
    if d is None:
        return [], ["não deu para consultar a segurança do token na GoPlus agora"]
    if not d:
        return [], ["a GoPlus não tem dados de segurança deste token"]
    if CHAINS[chain]["tipo"] == "solana":
        st = lambda k: str((d.get(k) or {}).get("status") if isinstance(d.get(k), dict) else d.get(k) or "").strip()  # noqa: E731
        return [v for k, v in SOL_BLOQ.items() if st(k) == "1"], [v for k, v in SOL_AVISO.items() if st(k) == "1"]
    bloq = [v for k, v in GP_BLOQ.items() if str(d.get(k, "")).strip() == "1"]
    avis = [v for k, v in GP_AVISO.items() if str(d.get(k, "")).strip() == "1"]
    for k, nome in (("buy_tax", "compra"), ("sell_tax", "venda")):
        try:
            v = float(d.get(k)) * 100
        except (TypeError, ValueError):
            continue
        if v > TAXA_TOKEN_MAX:
            bloq.append(f"taxa de {nome} do token {v:.0f}% (máx. {TAXA_TOKEN_MAX:g}%)")
        elif v > 0.5:
            avis.append(f"o token cobra {v:.1f}% de taxa na {nome}")
    return bloq, avis


def window_pct(px_now: float | None, spark: list | None, h: int, buy_t: float, px_in: float | None, now: float) -> tuple[float | None, float | None]:
    """(variação %, preço de referência) da janela. Comprou dentro dela: conta só desde a compra, pelo preço pago."""
    if not px_now:
        return None, None
    ref = None
    if buy_t >= now - h * 3600:
        ref = px_in
    elif spark and len(spark) >= h * 0.95:           # sparkline da CoinGecko: um ponto por hora, o último é o mais recente
        ref = spark[max(0, len(spark) - 1 - h)]
    if not ref:
        return None, None
    return round((px_now / ref - 1) * 100, 2), ref


def holdings(rows: list[dict], watch, now: float, janelas=(1, 12, 24, 168), sells: list[dict] | None = None) -> dict:
    """Linhas do histórico e a carteira somada, nas janelas de 1 h, 12 h, 24 h, 7 dias e no total. As vendas confirmadas abatem as
    compras mais antigas do mesmo token: o que sobrou vale o preço de agora, o que foi vendido vale o que entrou de verdade."""
    itens, soma_agora, soma_custo, soma_rec = [], 0.0, 0.0, 0.0
    soma_ref: dict[int, list[float]] = {h: [0.0, 0.0] for h in janelas}
    baixa: dict[str, tuple[float, float]] = {}
    pool: dict[tuple, list] = {}
    for x in sorted([s for s in sells or [] if s.get("status") == "confirmada" and s.get("qty")], key=lambda s: _ts(s.get("em"))):
        pool.setdefault((x.get("rede"), x.get("token")), []).append([float(x["qty"]), float(x["usd_out"] or 0) - float(x.get("gas_usd") or 0), float(x["qty"])])
    for r in sorted([r for r in rows if r.get("status") == "confirmada" and r.get("qty")], key=lambda r: _ts(r.get("em"))):
        falta, vend, rec = float(r["qty"]), 0.0, 0.0
        for v in pool.get((r.get("rede"), r.get("token"))) or []:
            n = min(falta, v[0])
            if n > 0:
                vend += n
                rec += v[1] * n / v[2]
                v[0] -= n
                falta -= n
        baixa[r.get("id")] = (vend, rec)
    for r in rows:
        d = dict(r)
        d["t"] = _ts(r.get("em"))
        c = CHAINS.get(r.get("rede")) or {}
        d["rede_nome"], d["moeda"], d["expl"] = c.get("nome"), c.get("moeda"), c.get("expl")
        if r.get("status") == "confirmada" and r.get("qty"):
            row = watch.rows.get(r.get("cg")) or {}
            px = row.get("current_price")
            spk = [float(x) for x in ((row.get("sparkline_in_7d") or {}).get("price") or []) if x]
            custo = float(r.get("usd_in") or 0) + float(r.get("gas_usd") or 0)
            vend, rec = baixa.get(r.get("id"), (0.0, 0.0))
            resto = max(0.0, float(r["qty"]) - vend)
            if resto < float(r["qty"]) * 1e-9:     # sobra de arredondamento não é saldo
                resto = 0.0
            d["custo"], d["px_agora"], d["img"], d["vendido"], d["recebido"], d["resto"] = round(custo, 4), px, row.get("image"), vend, round(rec, 4), resto
            for h in janelas:
                pct, ref = window_pct(px, spk, h, d["t"], r.get("px_in"), now) if resto else (None, None)
                d[f"h{h}"] = pct
                if pct is not None:
                    soma_ref[h][0] += resto * px
                    soma_ref[h][1] += resto * ref
            if px or not resto:
                v = resto * (px or 0)
                d["valor"], d["ganho"], d["total"] = round(v, 4), round(v + rec - custo, 4), round(((v + rec) / custo - 1) * 100, 2) if custo else None
                soma_agora += v
                soma_custo += custo
                soma_rec += rec
        itens.append(d)
    res = {"investido": round(soma_custo, 2), "valor": round(soma_agora, 2), "recebido": round(soma_rec, 2), "ganho": round(soma_agora + soma_rec - soma_custo, 2),
           "total": round(((soma_agora + soma_rec) / soma_custo - 1) * 100, 2) if soma_custo else None}
    for h in janelas:
        a, b = soma_ref[h]
        res[f"h{h}"] = round((a / b - 1) * 100, 2) if b else None
    return {"itens": itens, "resumo": res, "leitura_t": watch.stat.get("leitura_t")}


def _ts(v) -> float:
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


class Buyer:
    """Uma instância por servidor. db = SupaREST; box = SecretBox; watch = DormantWatch."""

    def __init__(self, http, db, box, watch, allowed=None, sys_key=None):
        self.http, self.db, self.box, self.watch = http, db, box, watch
        self.allowed = allowed or (lambda: False)
        self.sys_key = sys_key or (lambda name: "")
        self.quotes: dict[str, dict] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._gp: dict[tuple, tuple] = {}
        self._px: dict[str, tuple] = {}
        self._jq = None

    def lock(self, uid: str) -> asyncio.Lock:
        return self._locks.setdefault(uid, asyncio.Lock())

    # ------------------------------------------------------------------ rede
    async def rpc(self, url: str, method: str, params: list):
        try:
            r = await self.http.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                                     headers={"User-Agent": "pump-fun-copy/1.0"}, timeout=20)
            js = r.json()
        except Exception as e:                     # só o tipo: o endereço do RPC pode levar chave de API
            raise BuyError(f"a rede não respondeu ({type(e).__name__})") from None
        if not isinstance(js, dict):
            raise BuyError("a rede respondeu sem dados")
        if js.get("error"):
            e = js["error"]
            raise BuyError(str(e.get("message") if isinstance(e, dict) else e)[:160])
        return js.get("result")

    async def native_usd(self, chain: str) -> float | None:
        cg = CHAINS[chain]["cg"]
        hit = self._px.get(cg)
        if hit and time.time() - hit[0] < 60:
            return hit[1]
        v = None
        try:
            d = await self.watch.get("/simple/price", {"ids": cg, "vs_currencies": "usd"})
            v = float(((d or {}).get(cg) or {}).get("usd") or 0) or None
        except Exception:
            v = None
        if not v:                                  # CoinGecko pediu para esperar: serve a leitura da lista, se recente
            row = self.watch.rows.get(cg) or {}
            lido = self.watch.stat.get("leitura_t") or 0
            v = row.get("current_price") if time.time() - lido < 3600 else None
        if v:
            self._px[cg] = (time.time(), float(v))
        return float(v) if v else None

    async def goplus(self, chain: str, token: str) -> dict | None:
        k = (chain, token)
        hit = self._gp.get(k)
        if hit and time.time() - hit[0] < 300:
            return hit[1]
        c = CHAINS[chain]
        url = ("https://api.gopluslabs.io/api/v1/solana/token_security?contract_addresses=" + token if c["tipo"] == "solana"
               else f"https://api.gopluslabs.io/api/v1/token_security/{c['id']}?contract_addresses={token}")
        try:
            js = (await self.http.get(url, timeout=10)).json()
            res = (js or {}).get("result") or {}
            d = res.get(token) or res.get(token.lower()) or {}
        except Exception:
            return None
        self._gp[k] = (time.time(), d)
        if len(self._gp) > 500:
            self._gp.clear()
        return d

    # ------------------------------------------------------------------ 0.32.245: saldo e máximo de compra, antes de digitar o valor
    async def limit_info(self, uid: str, chain: str) -> dict:
        c = CHAINS.get(chain)
        if not c:
            raise BuyError("rede inválida")
        cfg = await self.cfg(uid)
        wal = await self.wallet_row(uid, chain)
        usd_n = await self.native_usd(chain)
        gasto = await self.spent_today(uid)
        resta = max(0.0, cfg["dia_usd"] - gasto)
        saldo, reserva = None, 0.0
        if wal:
            try:
                if c["tipo"] == "solana":
                    saldo, reserva = (await self.rpc(self.sol_rpc(), "getBalance", [wal["endereco"]]))["value"] / 1e9, c["reserva"]
                else:
                    saldo = int(await self.rpc(c["rpc"], "eth_getBalance", [wal["endereco"], "latest"]) or "0x0", 16) / 1e18
                    reserva = int(await self.rpc(c["rpc"], "eth_gasPrice", []) or "0x0", 16) * 1.1 * 300000 * 1.3 / 1e18   # o gás da própria compra
            except (BuyError, KeyError, TypeError, ValueError):
                saldo = None
        out = {"moeda": c["moeda"], "usd_n": usd_n, "tem_carteira": bool(wal), "saldo": saldo, "saldo_usd": saldo * usd_n if saldo is not None and usd_n else None, "reserva_gas": reserva,
               "limite_compra_usd": cfg["max_usd"], "limite_dia_usd": cfg["dia_usd"], "gasto_dia_usd": gasto, "resta_dia_usd": round(resta, 2), "ligado": cfg["on"], "max_nativo": None, "max_usd": None, "limitado_por": None}
        if usd_n:
            caps = [(cfg["max_usd"], "seu limite por compra"), (resta, "o que sobra do seu limite de 24 h")]
            if saldo is not None:
                caps.append((max(0.0, saldo - reserva) * usd_n, "o saldo da carteira (fica o gás da compra)"))
            m, por = min(caps, key=lambda x: x[0])
            out.update(max_nativo=math.floor(m / usd_n * 1e8) / 1e8, max_usd=round(m, 2), limitado_por=por)
        return out

    # ------------------------------------------------------------------ cotação EVM
    async def _call(self, c: dict, to: str, data: str) -> str | None:
        try:
            return await self.rpc(c["rpc"], "eth_call", [{"to": to, "data": data}, "latest"])
        except BuyError:
            return None                            # rota sem pool responde erro: é só "não há esta rota"

    async def _v2_out(self, c: dict, value: int, path: list) -> int:
        w = evm.words(await self._call(c, c["router"], evm.call_data(SEL_AMOUNTS, value, path)) or "0x")
        return w[-1] if len(w) >= 2 + len(path) else 0

    async def _v3_out(self, c: dict, value: int, token: str, fee: int) -> int:
        data = SEL_V3_QUOTE + evm.w_addr(c["wrapped"]) + evm.w_addr(token) + evm.w_int(value) + evm.w_int(fee) + evm.w_int(0)
        w = evm.words(await self._call(c, V3_QUOTER, data) or "0x")
        return w[0] if w else 0

    async def _route_out(self, c: dict, rt: dict, value: int, token: str) -> int:
        return await (self._v3_out(c, value, token, rt["fee"]) if rt["tipo"] == "v3" else self._v2_out(c, value, rt["path"]))

    async def evm_best(self, chain: str, token: str, value: int) -> dict | None:
        c = CHAINS[chain]
        cands = [{"tipo": "v2", "path": [c["wrapped"], token], "dex": c["dex"].split(" e ")[0], "rota": "direta"}]
        if c.get("ponte") and token != c["ponte"]:
            cands.append({"tipo": "v2", "path": [c["wrapped"], c["ponte"], token], "dex": c["dex"].split(" e ")[0], "rota": "passando por dólar"})
        if c.get("v3"):
            cands += [{"tipo": "v3", "fee": f, "dex": "Uniswap V3", "rota": f"pool de {f / 10000:g}%"} for f in V3_FEES]
        outs = await asyncio.gather(*[self._route_out(c, rt, value, token) for rt in cands])
        best, out = None, 0
        for rt, o in zip(cands, outs):
            if o > out:
                best, out = rt, o
        return {**best, "out": out} if best else None

    # ------------------------------------------------------------------ cotação
    async def preview(self, uid: str, key: str, chain: str, amount) -> dict:
        """Mostra tudo antes da compra. Só devolve quote_id se nada bloquear; quem compra não manda preço nenhum."""
        w = self.watch
        m = next((x for x in w.todas() if x["cmc"] == key), None)
        if m is None:
            raise BuyError("esta moeda não está na lista")
        it = w.item(m)
        cid = it.get("cg")
        if chain not in buyable(w, cid):
            raise BuyError("esta moeda não pode ser comprada nesta rede por aqui")
        c = CHAINS[chain]
        token = w.addr[cid][chain]
        token = token if c["tipo"] == "solana" else token.lower()
        try:
            amt = float(amount)
        except (TypeError, ValueError):
            raise BuyError("valor inválido") from None
        if not math.isfinite(amt) or amt <= 0:
            raise BuyError("valor inválido")
        value = int(amt * 10 ** c["dec"])
        if value <= 0:
            raise BuyError("valor pequeno demais")
        cfg = await self.cfg(uid)
        wal = await self.wallet_row(uid, chain)
        bloq: list[str] = []
        avisos: list[str] = []
        if not self.allowed():
            bloq.append("a trava geral do servidor (PUMP_REAL_ALLOWED) está fechada")
        if not cfg["on"]:
            bloq.append("as compras estão desligadas em Carteiras e compra")
        if not wal:
            bloq.append(f"cadastre a carteira da rede {c['nome']} em Carteiras e compra")
        usd_n = await self.native_usd(chain)
        usd_in = amt * usd_n if usd_n else None
        if usd_in is None:
            bloq.append(f"sem a cotação de {c['moeda']} em dólar: sem ela os limites não valem")
        else:
            if usd_in > cfg["max_usd"]:
                bloq.append(f"passa do seu limite por compra (${cfg['max_usd']:g})")
            gasto = await self.spent_today(uid)
            if gasto + usd_in > cfg["dia_usd"]:
                bloq.append(f"passa do seu limite por dia (${cfg['dia_usd']:g}; já foram ${gasto:.2f} nas últimas 24 h)")
        if await self.pending_on(uid, chain):
            bloq.append("há uma compra sem confirmação nesta rede: espere ela terminar (veja Minhas compras)")
        gb, ga = judge_goplus(chain, await self.goplus(chain, token))
        bloq += gb
        avisos += ga
        q = {"uid": uid, "key": key, "cg": cid, "rede": chain, "token": token, "value": value, "amt": amt, "usd_n": usd_n, "usd_in": usd_in,
             "nome": it.get("nome"), "simbolo": it.get("simbolo"), "t": time.time(), "slip": cfg["slip_pct"], "end": (wal or {}).get("endereco")}
        if c["tipo"] == "solana":
            det = await self._preview_sol(q, wal, bloq, avisos)
        else:
            det = await self._preview_evm(q, wal, bloq, avisos)
        px_cg = it.get("preco")
        if usd_in and det.get("qty") and px_cg:
            pago = usd_in / det["qty"]
            dif = (pago / px_cg - 1) * 100
            det["px_pago"], det["px_cg"], det["dif_cg"] = pago, px_cg, round(dif, 2)
            if dif > PRECO_BLOQ:
                bloq.append(f"o preço na DEX está {dif:.0f}% acima da CoinGecko: pool errado, manipulado ou sem dinheiro")
            elif dif > PRECO_AVISO:
                avisos.append(f"o preço na DEX está {dif:.0f}% acima da CoinGecko (lida a cada 20 min)")
        elif det.get("qty"):
            avisos.append("sem preço da CoinGecko para comparar")
        imp = det.get("impacto")
        if imp is not None:
            if imp > IMPACTO_BLOQ:
                bloq.append(f"esta compra moveria o preço em {imp:.0f}%: pool pequeno para este valor")
            elif imp > IMPACTO_AVISO:
                avisos.append(f"esta compra move o preço em {imp:.0f}%: pool pequeno para este valor")
        out = {"moeda": {"nome": q["nome"], "simbolo": q["simbolo"], "img": it.get("img")}, "rede": chain, "rede_nome": c["nome"], "token": token,
               "moeda_rede": c["moeda"], "valor": amt, "usd": usd_in, "carteira": q["end"], "slip": cfg["slip_pct"], "bloqueia": bloq, "avisos": avisos, **det}
        if not bloq:
            self._prune()
            qid = uuid.uuid4().hex
            self.quotes[qid] = q
            out.update(quote_id=qid, validade_s=QUOTE_TTL_S)
        return out

    async def _preview_evm(self, q: dict, wal: dict | None, bloq: list, avisos: list) -> dict:
        c = CHAINS[q["rede"]]
        rt = await self.evm_best(q["rede"], q["token"], q["value"])
        if not rt:
            bloq.append(f"nenhum pool com a moeda da rede em {c['dex']} para este token")
            return {"dex": c["dex"]}
        w = evm.words(await self._call(c, q["token"], SEL_DECIMALS) or "0x")
        dec = w[0] if w else None
        if dec is None or dec > 36:
            bloq.append("o contrato do token não informa as casas decimais")
            return {"dex": rt["dex"], "rota": rt["rota"]}
        min_out = rt["out"] * (10000 - int(q["slip"] * 100)) // 10000
        q.update(route={k: v for k, v in rt.items() if k != "out"}, min_out=min_out, dec=dec)
        small = await self._route_out(c, rt, max(q["value"] // 50, 1), q["token"])
        impacto = round(max(0.0, (1 - rt["out"] / (small * 50)) * 100), 2) if small else None
        gp = int(await self.rpc(c["rpc"], "eth_gasPrice", []) or "0x0", 16)
        q["gp"] = gp
        gas, gas_nat = 300000, None
        if wal:
            bal = int(await self.rpc(c["rpc"], "eth_getBalance", [wal["endereco"], "latest"]) or "0x0", 16)
            if bal < q["value"]:
                bloq.append(f"saldo insuficiente: a carteira tem {bal / 1e18:.6f} {c['moeda']}")
            else:
                try:
                    to, data = self._evm_tx(q, min_out, wal["endereco"])
                    gas = int(await self.rpc(c["rpc"], "eth_estimateGas", [{"from": wal["endereco"], "to": to, "data": data, "value": hex(q["value"])}]), 16)
                except BuyError as e:
                    bloq.append("a rede recusou na simulação: " + str(e))
            gas_nat = gas * gp / 1e18
            if bal < q["value"] + int(gas * 1.3) * gp and bal >= q["value"]:
                bloq.append(f"falta {c['moeda']} para pagar o gás: use Abastecer em Carteiras e compra")
        gas_usd = (gas_nat if gas_nat is not None else gas * gp / 1e18) * (q["usd_n"] or 0)
        if q["usd_in"] and gas_usd > q["usd_in"] * 0.25:
            avisos.append(f"o gás (${gas_usd:.2f}) passa de 25% do valor da compra")
        return {"dex": rt["dex"], "rota": rt["rota"], "recebe": rt["out"] / 10 ** dec, "qty": rt["out"] / 10 ** dec, "minimo": min_out / 10 ** dec,
                "impacto": impacto, "gas_usd": round(gas_usd, 4)}

    def _evm_tx(self, q: dict, min_out: int, addr: str) -> tuple[str, str]:
        """Destino e dados: sempre o roteador fixo daqui, recebedor sempre a própria carteira."""
        c, rt = CHAINS[q["rede"]], q["route"]
        dl = int(time.time()) + 300
        if rt["tipo"] == "v3":
            return V3_ROUTER, v3_data(c["wrapped"], q["token"], rt["fee"], addr, dl, q["value"], min_out)
        return c["router"], v2_data(c, min_out, rt["path"], addr, dl)

    # ------------------------------------------------------------------ cotação Solana
    def jup(self):
        from .jupiter import JupiterQuoter
        if self._jq is None or self._jq[0] != self.sys_key("jupiter_api_key"):
            k = self.sys_key("jupiter_api_key")
            self._jq = (k, JupiterQuoter(self.http, k))
        return self._jq[1]

    def sol_rpc(self) -> str:
        from .solana_wallet import PUBLIC_RPC, check_rpc_url
        u = self.sys_key("rpc_url")
        if u:
            try:
                return check_rpc_url(u)
            except ValueError:
                pass
        return PUBLIC_RPC

    async def _jup_quote(self, q: dict, inp: str = WSOL, out: str | None = None, amount: int | None = None) -> dict | None:
        jq = self.jup()
        await jq._jup_wait()
        try:
            r = await self.http.get(f"{jq.jup_base}/swap/v1/quote", headers=jq.jup_headers, timeout=10,
                                    params={"inputMint": inp, "outputMint": out or q["token"], "amount": str(amount if amount is not None else q["value"]),
                                            "slippageBps": int(q["slip"] * 100), "restrictIntermediateTokens": "true"})
            return r.json() if r.status_code == 200 else None
        except Exception:
            return None

    async def _sol_decimals(self, mint: str) -> int | None:
        try:
            return int((await self.rpc(self.sol_rpc(), "getTokenSupply", [mint]))["value"]["decimals"])
        except Exception:
            return None

    async def _preview_sol(self, q: dict, wal: dict | None, bloq: list, avisos: list) -> dict:
        jq = await self._jup_quote(q)
        if not jq or not int(jq.get("outAmount") or 0):
            bloq.append("a Jupiter não achou rota para este token")
            return {"dex": "Jupiter"}
        dec = await self._sol_decimals(q["token"])
        if dec is None:
            bloq.append("não consegui ler as casas decimais do token")
            return {"dex": "Jupiter"}
        out, thr = int(jq["outAmount"]), int(jq.get("otherAmountThreshold") or 0)
        q.update(min_out=thr, dec=dec)
        if wal:
            try:
                bal = (await self.rpc(self.sol_rpc(), "getBalance", [wal["endereco"]]))["value"]
                if bal < q["value"] + int(CHAINS["solana"]["reserva"] * 1e9):
                    bloq.append(f"saldo insuficiente: a carteira tem {bal / 1e9:.4f} SOL (fica {CHAINS['solana']['reserva']:g} SOL para as taxas); use Abastecer em Carteiras e compra")
            except (BuyError, KeyError, TypeError):
                bloq.append("não consegui ler o saldo da carteira")
        labels = [((r.get("swapInfo") or {}).get("label") or "?") for r in (jq.get("routePlan") or [])]
        try:
            imp = round(float(jq.get("priceImpactPct") or 0) * 100, 2)
        except (TypeError, ValueError):
            imp = None
        usd = (q["usd_n"] or 0) * 0.0025
        return {"dex": "Jupiter", "rota": " → ".join(labels[:4]), "recebe": out / 10 ** dec, "qty": out / 10 ** dec, "minimo": thr / 10 ** dec,
                "impacto": imp, "gas_usd": round(usd, 4)}

    # ------------------------------------------------------------------ compra
    def _prune(self) -> None:
        now = time.time()
        for k in [k for k, v in self.quotes.items() if now - v["t"] > QUOTE_TTL_S]:
            del self.quotes[k]

    async def buy(self, uid: str, quote_id: str, senha: str, confirmar: str) -> dict:
        if confirmar != "COMPRAR":
            raise BuyError("digite COMPRAR para confirmar")
        async with self.lock(uid):                 # uma compra por vez por conta: sem compra dobrada nem nonce repetido
            self._prune()
            q = self.quotes.get(str(quote_id or ""))
            if not q or q["uid"] != uid or q.get("lado"):
                raise BuyError("esta cotação venceu: peça outra")
            cfg = await self.cfg(uid)
            if not self.allowed():
                raise BuyError("a trava geral do servidor (PUMP_REAL_ALLOWED) está fechada")
            if not cfg["on"]:
                raise BuyError("as compras estão desligadas em Carteiras e compra")
            wal = await self.wallet_row(uid, q["rede"])
            if not wal or wal["endereco"] != q["end"]:
                raise BuyError("a carteira desta rede mudou: peça outra cotação")
            secret = await self._open(uid, wal, senha)       # senha errada não gasta a cotação, mas conta tentativa
            self.quotes.pop(quote_id, None)                  # daqui em diante a cotação é de uso único
            gasto = await self.spent_today(uid)
            if q["usd_in"] > cfg["max_usd"] or gasto + q["usd_in"] > cfg["dia_usd"]:
                raise BuyError("passa dos seus limites em dólar")
            if await self.pending_on(uid, q["rede"]):
                raise BuyError("há uma compra sem confirmação nesta rede: espere ela terminar")
            if CHAINS[q["rede"]]["tipo"] == "solana":
                return await self._buy_sol(q, wal, secret)
            return await self._buy_evm(q, wal, secret)

    def _row(self, q: dict, wal: dict, tx: str | None, dex: str | None, rota: str | None) -> dict:
        return {"id": uuid.uuid4().hex, "user_id": q["uid"], "em": _iso(time.time()), "rede": q["rede"], "cmc": q["key"], "cg": q["cg"], "nome": q["nome"], "simbolo": q["simbolo"],
                "token": q["token"], "endereco": wal["endereco"], "dex": dex, "rota": rota, "nativo": q["amt"], "nativo_usd": q["usd_n"], "usd_in": q["usd_in"],
                "casas": q.get("dec"), "tx": tx, "status": "enviando"}

    async def _finish(self, row: dict, **v) -> dict:
        row.update(v)
        await self.db.update("dormant_buys", {"id": row["id"], "user_id": row["user_id"]}, v)
        return row

    async def _buy_evm(self, q: dict, wal: dict, secret: str) -> dict:
        c = CHAINS[q["rede"]]
        cid = int(await self.rpc(c["rpc"], "eth_chainId", []) or "0x0", 16)
        if cid != c["id"]:
            raise BuyError("o RPC respondeu de outra rede: nada foi enviado")
        addr = wal["endereco"]
        key = evm.parse_key(secret)
        if evm.address_of(key) != addr:
            raise BuyError("a chave não bate com o endereço da carteira: nada foi enviado")
        out = await self._route_out(c, q["route"], q["value"], q["token"])
        if out < q["min_out"]:
            raise BuyError("o preço piorou além da sua folga: nada foi enviado, peça outra cotação")
        to, data = self._evm_tx(q, q["min_out"], addr)
        est = int(await self.rpc(c["rpc"], "eth_estimateGas", [{"from": addr, "to": to, "data": data, "value": hex(q["value"])}]), 16)
        gp = int(await self.rpc(c["rpc"], "eth_gasPrice", []) or "0x0", 16)
        if q.get("gp") and gp > q["gp"] * 2:
            raise BuyError("o gás mais que dobrou desde a cotação: nada foi enviado, peça outra cotação")
        gp = int(gp * 1.1)
        gas = int(est * 1.3) + 20000
        bal = int(await self.rpc(c["rpc"], "eth_getBalance", [addr, "latest"]) or "0x0", 16)
        if bal < q["value"] + gas * gp:
            raise BuyError(f"falta {c['moeda']} para pagar a compra e o gás: nada foi enviado")
        nonce = int(await self.rpc(c["rpc"], "eth_getTransactionCount", [addr, "pending"]), 16)
        raw, h = evm.sign_tx(key, nonce, gp, gas, to, q["value"], data, c["id"])
        rt = q["route"]
        # grava ANTES de enviar: se o servidor cair aqui, a compra aparece e o limite do dia conta
        row = self._row(q, wal, h, rt["dex"], rt["rota"])
        await self.db.insert("dormant_buys", row)
        self.watch.held.add(q["cg"])
        sent, why = False, ""
        for url in dict.fromkeys([c.get("envio") or c["rpc"], c["rpc"]]):
            try:
                await self.rpc(url, "eth_sendRawTransaction", [raw])
                sent = True
                break
            except BuyError as e:
                why = str(e)
                if "known" in why.lower() or "already" in why.lower():
                    sent = True
                    break
        if not sent:
            await self._finish(row, status="falhou", motivo="envio recusado: " + why[:160])
            raise BuyError("a rede recusou o envio: " + why[:160])
        t0 = time.monotonic()
        while time.monotonic() - t0 < RECIBO_S:
            await asyncio.sleep(RECIBO_PASSO)
            try:
                rc = await self.rpc(c["rpc"], "eth_getTransactionReceipt", [h])
            except BuyError:
                rc = None
            if rc:
                return self._public(await self._apply_evm(row, rc, gp))
        await self._finish(row, status="pendente", motivo="sem confirmação em 90 s: confira em Minhas compras")
        return self._public(row)

    async def _apply_evm(self, row: dict, rc: dict, gp: int | None = None) -> dict:
        c = CHAINS[row["rede"]]
        gas = int(rc.get("gasUsed") or "0x0", 16) * int(rc.get("effectiveGasPrice") or hex(gp or 0), 16) / 1e18
        gas_usd = round(gas * float(row.get("nativo_usd") or 0), 4)
        if int(rc.get("status") or "0x0", 16) != 1:
            return await self._finish(row, status="falhou", motivo="a transação falhou na rede (só o gás foi gasto)", gas_usd=gas_usd)
        got = 0
        for lg in rc.get("logs") or []:
            tp = lg.get("topics") or []
            if (lg.get("address") or "").lower() == row["token"] and len(tp) >= 3 and tp[0] == T_TRANSFER and tp[2][-40:].lower() == row["endereco"][2:]:
                got += int(lg.get("data") or "0x0", 16)
        if got <= 0:
            return await self._finish(row, status="confira", motivo=f"confirmada, mas o token não apareceu no recibo: confira em {c['nome']}", gas_usd=gas_usd)
        qty = got / 10 ** int(row.get("casas") or 18)
        return await self._finish(row, status="confirmada", motivo=None, qty=qty, px_in=float(row["usd_in"]) / qty, gas_usd=gas_usd)

    async def _buy_sol(self, q: dict, wal: dict, secret: str) -> dict:
        from .jupiter import JupiterWallet
        from .solana_wallet import UserWallet
        from . import txguard
        jq = await self._jup_quote(q)
        if not jq or not int(jq.get("outAmount") or 0):
            raise BuyError("a Jupiter não achou rota agora: nada foi enviado")
        if int(jq.get("otherAmountThreshold") or 0) < q["min_out"] * 0.99:
            raise BuyError("o preço piorou além da sua folga: nada foi enviado, peça outra cotação")
        try:
            uw = UserWallet(secret, public_rpc=self.sol_rpc(), jupiter_api_key=self.sys_key("jupiter_api_key"))
        except ValueError:
            raise BuyError("a chave guardada não abriu") from None
        if uw.address != wal["endereco"]:
            raise BuyError("a chave não bate com o endereço da carteira: nada foi enviado")
        jw = JupiterWallet(self.http, uw, self.jup(), priority_sol=0.0001)
        try:
            raw, blockhash = await jw._swap_tx(jq, prio="high", amount=q["value"], out_mint=q["token"])
        except txguard.TxRejected as e:
            raise BuyError("a transação não passou na conferência: " + str(e)[:160] + ": nada foi enviado") from None
        except Exception as e:
            raise BuyError(f"não consegui montar a transação ({type(e).__name__}): nada foi enviado") from None
        from solders.transaction import VersionedTransaction
        sig = str(VersionedTransaction.from_bytes(base64.b64decode(raw)).signatures[0])
        labels = [((r.get("swapInfo") or {}).get("label") or "?") for r in (jq.get("routePlan") or [])]
        row = self._row(q, wal, sig, "Jupiter", " → ".join(labels[:4]))
        await self.db.insert("dormant_buys", row)
        self.watch.held.add(q["cg"])
        s, st, err = await jw._send_and_confirm(raw)
        if st == "pendente":
            st, err = await txguard.reconcile(jw._rpc, s or sig, blockhash)
        if st == "confirmada":
            return self._public(await self._apply_sol(row))
        if st == "pendente":
            await self._finish(row, status="pendente", motivo=(err or "")[:160])
            return self._public(row)
        await self._finish(row, status="falhou", motivo=(err or st)[:160])
        raise BuyError("a compra não entrou: " + (err or st)[:160])

    async def _apply_sol(self, row: dict) -> dict:
        tx = None
        for _ in range(5):
            try:
                tx = await self.rpc(self.sol_rpc(), "getTransaction", [row["tx"], {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1, "commitment": "confirmed"}])
            except BuyError:
                tx = None
            if tx:
                break
            await asyncio.sleep(2)
        if not tx or not tx.get("meta"):
            return await self._finish(row, status="confira", motivo="confirmada, mas não consegui ler a quantidade: confira no Solscan")
        meta = tx["meta"]
        if meta.get("err"):
            return await self._finish(row, status="falhou", motivo=str(meta["err"])[:160])

        def soma(lst):
            return sum(float((b.get("uiTokenAmount") or {}).get("uiAmountString") or 0) for b in lst or []
                       if b.get("mint") == row["token"] and b.get("owner") == row["endereco"])
        qty = soma(meta.get("postTokenBalances")) - soma(meta.get("preTokenBalances"))
        fee = float(meta.get("fee") or 0) / 1e9
        gas_usd = round(fee * float(row.get("nativo_usd") or 0), 4)
        if qty <= 0:
            return await self._finish(row, status="confira", motivo="confirmada, mas o token não apareceu na carteira: confira no Solscan", gas_usd=gas_usd)
        return await self._finish(row, status="confirmada", motivo=None, qty=qty, px_in=float(row["usd_in"]) / qty, gas_usd=gas_usd)

    @staticmethod
    def _public(r: dict) -> dict:
        c = CHAINS.get(r.get("rede")) or {}
        return {k: r.get(k) for k in ("id", "status", "motivo", "tx", "qty", "px_in", "usd_in", "gas_usd", "nome", "simbolo", "dex", "rota")} | {"expl": c.get("expl")}

    # ------------------------------------------------------------------ venda (0.32.243, pedido do dono em 06/11/2026)
    # Vender é sair: funciona com as compras desligadas e não conta nos limites em dólar, mas pede senha e VENDER como a compra.
    # A trava geral PUMP_REAL_ALLOWED continua valendo: com ela fechada o servidor não assina nada.
    async def _erc20_word(self, c: dict, token: str, data: str) -> int:
        w = evm.words(await self.rpc(c["rpc"], "eth_call", [{"to": token, "data": data}, "latest"]) or "0x")
        return w[0] if w else 0

    async def evm_sell_best(self, chain: str, token: str, amount: int) -> dict | None:
        c = CHAINS[chain]
        cands = [{"tipo": "v2", "path": [token, c["wrapped"]], "dex": c["dex"].split(" e ")[0], "rota": "direta"}]
        if c.get("ponte") and token != c["ponte"]:
            cands.append({"tipo": "v2", "path": [token, c["ponte"], c["wrapped"]], "dex": c["dex"].split(" e ")[0], "rota": "passando por dólar"})
        if c.get("v3"):
            cands += [{"tipo": "v3", "fee": f, "dex": "Uniswap V3", "rota": f"pool de {f / 10000:g}%"} for f in V3_FEES]
        outs = await asyncio.gather(*[self._sell_out(c, rt, amount, token) for rt in cands])
        best, out = None, 0
        for rt, o in zip(cands, outs):
            if o > out:
                best, out = rt, o
        return {**best, "out": out} if best else None

    async def _sell_out(self, c: dict, rt: dict, amount: int, token: str) -> int:
        if rt["tipo"] == "v2":
            return await self._v2_out(c, amount, rt["path"])
        data = SEL_V3_QUOTE + evm.w_addr(token) + evm.w_addr(c["wrapped"]) + evm.w_int(amount) + evm.w_int(rt["fee"]) + evm.w_int(0)
        w = evm.words(await self._call(c, V3_QUOTER, data) or "0x")
        return w[0] if w else 0

    def _sell_tx(self, q: dict, min_out: int, addr: str) -> tuple[str, str]:
        """Sempre o roteador fixo daqui; o dinheiro sempre para a própria carteira."""
        c, rt = CHAINS[q["rede"]], q["route"]
        dl = int(time.time()) + 300
        if rt["tipo"] == "v3":
            return V3_ROUTER, v3_sell_data(q["token"], c["wrapped"], rt["fee"], addr, dl, q["amount"], min_out)
        return c["router"], evm.call_data(c.get("sell_sel") or SEL_SELL_ETH, q["amount"], min_out, rt["path"], addr, dl)

    @staticmethod
    def _spender(q: dict) -> str:
        return V3_ROUTER if q["route"]["tipo"] == "v3" else CHAINS[q["rede"]]["router"]

    async def preview_sell(self, uid: str, compra_id: str, pct) -> dict:
        rows = await self.db.select("dormant_buys", {"id": str(compra_id or ""), "user_id": uid}, limit=1) or []
        if not rows or rows[0].get("status") != "confirmada":
            raise BuyError("compra não encontrada")
        r = rows[0]
        chain = r.get("rede")
        if chain not in CHAINS:
            raise BuyError("rede inválida")
        try:
            pct = int(pct)
        except (TypeError, ValueError):
            raise BuyError("porcentagem inválida") from None
        if not 1 <= pct <= 100:
            raise BuyError("porcentagem inválida")
        c, bloq, avisos = CHAINS[chain], [], []
        if not self.allowed():
            bloq.append("a trava geral do servidor (PUMP_REAL_ALLOWED) está fechada")
        wal = await self.wallet_row(uid, chain)
        if not wal:
            bloq.append(f"cadastre a carteira da rede {c['nome']} em Carteiras e compra")
        elif wal["endereco"] != r.get("endereco"):
            bloq.append("a carteira desta rede foi trocada depois da compra: o token está na carteira antiga")
        if await self.pending_on(uid, chain):
            bloq.append("há uma operação sem confirmação nesta rede: espere ela terminar (veja Minhas compras)")
        usd_n = await self.native_usd(chain)
        if not usd_n:
            bloq.append(f"sem a cotação de {c['moeda']} em dólar")
        gb, ga = judge_goplus(chain, await self.goplus(chain, r["token"]))
        avisos += gb + ga                          # na venda não bloqueia: se der para sair, a decisão é do dono; a simulação recusa se não der
        cfg = await self.cfg(uid)
        q = {"lado": "venda", "uid": uid, "compra": r["id"], "key": r.get("cmc"), "cg": r.get("cg"), "rede": chain, "token": r["token"], "pct": pct, "usd_n": usd_n,
             "nome": r.get("nome"), "simbolo": r.get("simbolo"), "t": time.time(), "slip": cfg["slip_pct"], "end": r.get("endereco")}
        det = await (self._sell_preview_sol(q, bloq, avisos) if c["tipo"] == "solana" else self._sell_preview_evm(q, bloq, avisos))
        row = self.watch.rows.get(r.get("cg")) or {}
        px = row.get("current_price")
        usd_out = det.get("recebe") * usd_n if det.get("recebe") and usd_n else None
        if usd_out and px and det.get("vende"):
            dif = (usd_out / (det["vende"] * px) - 1) * 100
            det["dif_cg"] = round(dif, 2)
            if dif < -VENDA_BLOQ:
                bloq.append(f"você receberia {-dif:.0f}% abaixo do preço da CoinGecko: pool errado, manipulado ou sem dinheiro")
            elif dif < -PRECO_AVISO:
                avisos.append(f"você recebe {-dif:.0f}% abaixo do preço da CoinGecko")
        imp = det.get("impacto")
        if imp is not None and imp > IMPACTO_AVISO:
            avisos.append(f"esta venda move o preço em {imp:.0f}%: pool pequeno para este valor")
        out = {"moeda": {"nome": q["nome"], "simbolo": q["simbolo"]}, "rede": chain, "rede_nome": c["nome"], "token": q["token"], "moeda_rede": c["moeda"], "carteira": q["end"],
               "slip": cfg["slip_pct"], "pct": pct, "usd": usd_out, "bloqueia": bloq, "avisos": avisos, **det}
        if not bloq:
            self._prune()
            qid = uuid.uuid4().hex
            self.quotes[qid] = q
            out.update(quote_id=qid, validade_s=QUOTE_TTL_S)
        return out

    async def _sell_preview_evm(self, q: dict, bloq: list, avisos: list) -> dict:
        c, addr = CHAINS[q["rede"]], q["end"]
        try:
            dec = await self._erc20_word(c, q["token"], SEL_DECIMALS)
            saldo = await self._erc20_word(c, q["token"], SEL_BALANCE + evm.w_addr(addr))
        except BuyError as e:
            bloq.append("não consegui ler o token: " + str(e))
            return {"dex": c["dex"]}
        if saldo <= 0:
            bloq.append("a carteira não tem este token")
            return {"dex": c["dex"], "saldo": 0}
        amount = saldo if q["pct"] == 100 else saldo * q["pct"] // 100
        rt = await self.evm_sell_best(q["rede"], q["token"], amount)
        if not rt:
            bloq.append(f"nenhum pool com a moeda da rede em {c['dex']} para este token")
            return {"dex": c["dex"], "saldo": saldo / 10 ** dec, "vende": amount / 10 ** dec}
        # token que cobra taxa na venda entrega menos que a cotação: sem isto a folga não bastaria e a transação falharia
        tax = 0.0
        try:
            tax = max(0.0, float(((await self.goplus(q["rede"], q["token"])) or {}).get("sell_tax") or 0))
        except (TypeError, ValueError):
            pass
        min_out = int(rt["out"] * (10000 - int(q["slip"] * 100)) / 10000 * (1 - min(tax, 0.5)))
        q.update(route={k: v for k, v in rt.items() if k != "out"}, amount=amount, min_out=min_out, dec=dec)
        small = await self._sell_out(c, rt, max(amount // 50, 1), q["token"])
        impacto = round(max(0.0, (1 - rt["out"] / (small * 50)) * 100), 2) if small else None
        gp = int(await self.rpc(c["rpc"], "eth_gasPrice", []) or "0x0", 16)
        q["gp"] = gp
        allow = await self._erc20_word(c, q["token"], SEL_ALLOW + evm.w_addr(addr) + evm.w_addr(self._spender(q)))
        aprovar = allow < amount
        gas = 300000 + (70000 if aprovar else 0)
        if not aprovar:
            try:
                to, data = self._sell_tx(q, min_out, addr)
                gas = int(await self.rpc(c["rpc"], "eth_estimateGas", [{"from": addr, "to": to, "data": data, "value": "0x0"}]), 16)
            except BuyError as e:
                bloq.append("a rede recusou na simulação: " + str(e))
        bal = int(await self.rpc(c["rpc"], "eth_getBalance", [addr, "latest"]) or "0x0", 16)
        if bal < int(gas * 1.3) * gp:
            bloq.append(f"falta {c['moeda']} para pagar o gás da venda: a carteira tem {bal / 1e18:.6f}; use Abastecer em Carteiras e compra")
        if aprovar:
            avisos.append("vai sair uma autorização antes da venda: só no valor exato desta venda, só para o roteador oficial (paga gás)")
        return {"dex": rt["dex"], "rota": rt["rota"], "saldo": saldo / 10 ** dec, "vende": amount / 10 ** dec, "recebe": rt["out"] / 1e18, "minimo": min_out / 1e18,
                "impacto": impacto, "gas_usd": round(gas * gp / 1e18 * (q["usd_n"] or 0), 4), "aprovar": aprovar}

    async def _sell_preview_sol(self, q: dict, bloq: list, avisos: list) -> dict:
        try:
            res = await self.rpc(self.sol_rpc(), "getTokenAccountsByOwner", [q["end"], {"mint": q["token"]}, {"encoding": "jsonParsed"}])
            infos = [a["account"]["data"]["parsed"]["info"]["tokenAmount"] for a in (res or {}).get("value") or []]
            saldo, dec = sum(int(i["amount"]) for i in infos), (int(infos[0]["decimals"]) if infos else 0)
            sol = (await self.rpc(self.sol_rpc(), "getBalance", [q["end"]]))["value"]
        except (BuyError, KeyError, TypeError, ValueError, IndexError):
            bloq.append("não consegui ler o saldo da carteira")
            return {"dex": "Jupiter"}
        if saldo <= 0:
            bloq.append("a carteira não tem este token")
            return {"dex": "Jupiter", "saldo": 0}
        if sol < 3_000_000:
            bloq.append(f"falta SOL para pagar a taxa da venda: a carteira tem {sol / 1e9:.5f}; use Abastecer em Carteiras e compra")
        amount = saldo if q["pct"] == 100 else saldo * q["pct"] // 100
        q.update(amount=amount, dec=dec)
        jq = await self._jup_quote(q, q["token"], WSOL, amount)
        if not jq or not int(jq.get("outAmount") or 0):
            bloq.append("a Jupiter não achou rota para este token")
            return {"dex": "Jupiter", "saldo": saldo / 10 ** dec, "vende": amount / 10 ** dec}
        q["min_out"] = int(jq.get("otherAmountThreshold") or 0)
        labels = [((x.get("swapInfo") or {}).get("label") or "?") for x in (jq.get("routePlan") or [])]
        try:
            imp = round(float(jq.get("priceImpactPct") or 0) * 100, 2)
        except (TypeError, ValueError):
            imp = None
        return {"dex": "Jupiter", "rota": " → ".join(labels[:4]), "saldo": saldo / 10 ** dec, "vende": amount / 10 ** dec, "recebe": int(jq["outAmount"]) / 1e9,
                "minimo": q["min_out"] / 1e9, "impacto": imp, "gas_usd": round((q["usd_n"] or 0) * 0.0001, 4), "aprovar": False}

    async def sell(self, uid: str, quote_id: str, senha: str, confirmar: str) -> dict:
        if confirmar != "VENDER":
            raise BuyError("digite VENDER para confirmar")
        async with self.lock(uid):
            self._prune()
            q = self.quotes.get(str(quote_id or ""))
            if not q or q["uid"] != uid or q.get("lado") != "venda":
                raise BuyError("esta cotação venceu: peça outra")
            if not self.allowed():
                raise BuyError("a trava geral do servidor (PUMP_REAL_ALLOWED) está fechada")
            wal = await self.wallet_row(uid, q["rede"])
            if not wal or wal["endereco"] != q["end"]:
                raise BuyError("a carteira desta rede mudou: peça outra cotação")
            secret = await self._open(uid, wal, senha)
            self.quotes.pop(quote_id, None)
            if await self.pending_on(uid, q["rede"]):
                raise BuyError("há uma operação sem confirmação nesta rede: espere ela terminar")
            if CHAINS[q["rede"]]["tipo"] == "solana":
                return await self._sell_sol(q, wal, secret)
            return await self._sell_evm(q, wal, secret)

    def _sell_row(self, q: dict, wal: dict, tx: str | None, dex: str | None, rota: str | None) -> dict:
        return {"id": uuid.uuid4().hex, "user_id": q["uid"], "em": _iso(time.time()), "rede": q["rede"], "compra": q["compra"], "cg": q["cg"], "nome": q["nome"], "simbolo": q["simbolo"],
                "token": q["token"], "endereco": wal["endereco"], "dex": dex, "rota": rota, "qty": q["amount"] / 10 ** int(q.get("dec") or 0), "casas": q.get("dec"), "nativo_usd": q["usd_n"], "tx": tx, "status": "enviando"}

    async def _sell_finish(self, row: dict, **v) -> dict:
        row.update(v)
        await self.db.update("dormant_sells", {"id": row["id"], "user_id": row["user_id"]}, v)
        return row

    async def _evm_receipt(self, c: dict, h: str) -> dict | None:
        t0 = time.monotonic()
        while time.monotonic() - t0 < RECIBO_S:
            await asyncio.sleep(RECIBO_PASSO)
            try:
                rc = await self.rpc(c["rpc"], "eth_getTransactionReceipt", [h])
            except BuyError:
                rc = None
            if rc:
                return rc
        return None

    async def _evm_approve(self, c: dict, key: int, addr: str, token: str, spender: str, amount: int, gp: int) -> None:
        """Autoriza SÓ o valor desta venda, SÓ para o roteador fixo. Não vai pelo envio privado: autorização não tem o que roubar."""
        data = SEL_APPROVE + evm.w_addr(spender) + evm.w_int(amount)
        est = int(await self.rpc(c["rpc"], "eth_estimateGas", [{"from": addr, "to": token, "data": data, "value": "0x0"}]), 16)
        nonce = int(await self.rpc(c["rpc"], "eth_getTransactionCount", [addr, "pending"]), 16)
        raw, h = evm.sign_tx(key, nonce, gp, int(est * 1.3) + 10000, token, 0, data, c["id"])
        await self.rpc(c["rpc"], "eth_sendRawTransaction", [raw])
        rc = await self._evm_receipt(c, h)
        if not rc or int(rc.get("status") or "0x0", 16) != 1:
            raise BuyError("a autorização não confirmou: a venda não foi enviada, tente de novo (" + h + ")")

    async def _sell_evm(self, q: dict, wal: dict, secret: str) -> dict:
        c = CHAINS[q["rede"]]
        cid = int(await self.rpc(c["rpc"], "eth_chainId", []) or "0x0", 16)
        if cid != c["id"]:
            raise BuyError("o RPC respondeu de outra rede: nada foi enviado")
        addr = wal["endereco"]
        key = evm.parse_key(secret)
        if evm.address_of(key) != addr:
            raise BuyError("a chave não bate com o endereço da carteira: nada foi enviado")
        if await self._erc20_word(c, q["token"], SEL_BALANCE + evm.w_addr(addr)) < q["amount"]:
            raise BuyError("o saldo do token mudou: nada foi enviado, peça outra cotação")
        out = await self._sell_out(c, q["route"], q["amount"], q["token"])
        if out < q["min_out"]:
            raise BuyError("o preço piorou além da sua folga: nada foi enviado, peça outra cotação")
        gp = int(await self.rpc(c["rpc"], "eth_gasPrice", []) or "0x0", 16)
        if q.get("gp") and gp > q["gp"] * 2:
            raise BuyError("o gás mais que dobrou desde a cotação: nada foi enviado, peça outra cotação")
        gp = int(gp * 1.1)
        spender = self._spender(q)
        allow = await self._erc20_word(c, q["token"], SEL_ALLOW + evm.w_addr(addr) + evm.w_addr(spender))
        if allow < q["amount"]:
            if allow > 0:                          # USDT e parecidos recusam trocar autorização que não está em zero
                await self._evm_approve(c, key, addr, q["token"], spender, 0, gp)
            await self._evm_approve(c, key, addr, q["token"], spender, q["amount"], gp)
            out = await self._sell_out(c, q["route"], q["amount"], q["token"])
            if out < q["min_out"]:                 # sobra autorização no roteador oficial, que só puxa de quem chama: nada a limpar
                raise BuyError("o preço piorou durante a autorização: a venda não foi enviada, peça outra cotação")
        to, data = self._sell_tx(q, q["min_out"], addr)
        est = int(await self.rpc(c["rpc"], "eth_estimateGas", [{"from": addr, "to": to, "data": data, "value": "0x0"}]), 16)
        gas = int(est * 1.3) + 20000
        bal = int(await self.rpc(c["rpc"], "eth_getBalance", [addr, "latest"]) or "0x0", 16)
        if bal < gas * gp:
            raise BuyError(f"falta {c['moeda']} para pagar o gás: a venda não foi enviada")
        nonce = int(await self.rpc(c["rpc"], "eth_getTransactionCount", [addr, "pending"]), 16)
        raw, h = evm.sign_tx(key, nonce, gp, gas, to, 0, data, c["id"])
        rt = q["route"]
        row = self._sell_row(q, wal, h, rt["dex"], rt["rota"])
        await self.db.insert("dormant_sells", row)      # grava ANTES de enviar, como na compra
        sent, why = False, ""
        for url in dict.fromkeys([c.get("envio") or c["rpc"], c["rpc"]]):
            try:
                await self.rpc(url, "eth_sendRawTransaction", [raw])
                sent = True
                break
            except BuyError as e:
                why = str(e)
                if "known" in why.lower() or "already" in why.lower():
                    sent = True
                    break
        if not sent:
            await self._sell_finish(row, status="falhou", motivo="envio recusado: " + why[:160])
            raise BuyError("a rede recusou o envio: " + why[:160])
        rc = await self._evm_receipt(c, h)
        if rc:
            return self._public_sell(await self._apply_sell_evm(row, rc, gp))
        await self._sell_finish(row, status="pendente", motivo="sem confirmação em 90 s: confira em Minhas compras")
        return self._public_sell(row)

    async def _apply_sell_evm(self, row: dict, rc: dict, gp: int | None = None) -> dict:
        c = CHAINS[row["rede"]]
        gas = int(rc.get("gasUsed") or "0x0", 16) * int(rc.get("effectiveGasPrice") or hex(gp or 0), 16) / 1e18
        usd_n = float(row.get("nativo_usd") or 0)
        gas_usd = round(gas * usd_n, 4)
        if int(rc.get("status") or "0x0", 16) != 1:
            return await self._sell_finish(row, status="falhou", motivo="a transação falhou na rede (só o gás foi gasto)", gas_usd=gas_usd)
        got, sold, end = 0, 0, row["endereco"][2:]
        for lg in rc.get("logs") or []:
            tp, adr = lg.get("topics") or [], (lg.get("address") or "").lower()
            if adr == c["wrapped"] and tp and tp[0] == T_WITHDRAW:
                got += int(lg.get("data") or "0x0", 16)
            elif adr == row["token"] and len(tp) >= 3 and tp[0] == T_TRANSFER and tp[1][-40:].lower() == end:
                sold += int(lg.get("data") or "0x0", 16)
        if got <= 0:
            return await self._sell_finish(row, status="confira", motivo=f"confirmada, mas o valor recebido não apareceu no recibo: confira em {c['nome']}", gas_usd=gas_usd)
        qty = sold / 10 ** int(row.get("casas") or 18) if sold else row.get("qty")
        return await self._sell_finish(row, status="confirmada", motivo=None, qty=qty, nativo_out=got / 1e18, usd_out=round(got / 1e18 * usd_n, 4), gas_usd=gas_usd)

    async def _sell_sol(self, q: dict, wal: dict, secret: str) -> dict:
        from .jupiter import JupiterWallet
        from .solana_wallet import UserWallet
        from . import txguard
        jq = await self._jup_quote(q, q["token"], WSOL, q["amount"])
        if not jq or not int(jq.get("outAmount") or 0):
            raise BuyError("a Jupiter não achou rota agora: nada foi enviado")
        if int(jq.get("otherAmountThreshold") or 0) < q["min_out"] * 0.99:
            raise BuyError("o preço piorou além da sua folga: nada foi enviado, peça outra cotação")
        try:
            uw = UserWallet(secret, public_rpc=self.sol_rpc(), jupiter_api_key=self.sys_key("jupiter_api_key"))
        except ValueError:
            raise BuyError("a chave guardada não abriu") from None
        if uw.address != wal["endereco"]:
            raise BuyError("a chave não bate com o endereço da carteira: nada foi enviado")
        jw = JupiterWallet(self.http, uw, self.jup(), priority_sol=0.0001)
        try:
            raw, blockhash = await jw._swap_tx(jq, prio="high", amount=q["amount"], out_mint=WSOL)
        except txguard.TxRejected as e:
            raise BuyError("a transação não passou na conferência: " + str(e)[:160] + ": nada foi enviado") from None
        except Exception as e:
            raise BuyError(f"não consegui montar a transação ({type(e).__name__}): nada foi enviado") from None
        from solders.transaction import VersionedTransaction
        sig = str(VersionedTransaction.from_bytes(base64.b64decode(raw)).signatures[0])
        labels = [((x.get("swapInfo") or {}).get("label") or "?") for x in (jq.get("routePlan") or [])]
        row = self._sell_row(q, wal, sig, "Jupiter", " → ".join(labels[:4]))
        await self.db.insert("dormant_sells", row)
        s, st, err = await jw._send_and_confirm(raw)
        if st == "pendente":
            st, err = await txguard.reconcile(jw._rpc, s or sig, blockhash)
        if st == "confirmada":
            return self._public_sell(await self._apply_sell_sol(row))
        if st == "pendente":
            await self._sell_finish(row, status="pendente", motivo=(err or "")[:160])
            return self._public_sell(row)
        await self._sell_finish(row, status="falhou", motivo=(err or st)[:160])
        raise BuyError("a venda não entrou: " + (err or st)[:160])

    async def _apply_sell_sol(self, row: dict) -> dict:
        tx = None
        for _ in range(5):
            try:
                tx = await self.rpc(self.sol_rpc(), "getTransaction", [row["tx"], {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1, "commitment": "confirmed"}])
            except BuyError:
                tx = None
            if tx:
                break
            await asyncio.sleep(2)
        if not tx or not tx.get("meta"):
            return await self._sell_finish(row, status="confira", motivo="confirmada, mas não consegui ler o valor recebido: confira no Solscan")
        meta = tx["meta"]
        if meta.get("err"):
            return await self._sell_finish(row, status="falhou", motivo=str(meta["err"])[:160])

        def soma(lst):
            return sum(float((b.get("uiTokenAmount") or {}).get("uiAmountString") or 0) for b in lst or []
                       if b.get("mint") == row["token"] and b.get("owner") == row["endereco"])
        qty = soma(meta.get("preTokenBalances")) - soma(meta.get("postTokenBalances"))
        fee = float(meta.get("fee") or 0)
        usd_n = float(row.get("nativo_usd") or 0)
        got = (float(meta["postBalances"][0]) - float(meta["preBalances"][0]) + fee) / 1e9
        if got <= 0 or qty <= 0:
            return await self._sell_finish(row, status="confira", motivo="confirmada, mas os valores não bateram: confira no Solscan", gas_usd=round(fee / 1e9 * usd_n, 4))
        return await self._sell_finish(row, status="confirmada", motivo=None, qty=qty, nativo_out=got, usd_out=round(got * usd_n, 4), gas_usd=round(fee / 1e9 * usd_n, 4))

    @staticmethod
    def _public_sell(r: dict) -> dict:
        c = CHAINS.get(r.get("rede")) or {}
        return {k: r.get(k) for k in ("id", "status", "motivo", "tx", "qty", "nativo_out", "usd_out", "gas_usd", "nome", "simbolo", "dex", "rota")} | {"expl": c.get("expl"), "moeda": c.get("moeda")}

    # ------------------------------------------------------------------ pendências
    async def resolve_pending(self, uid: str) -> None:
        now = time.time()
        vivas = ("enviando", "pendente")
        vendas = await self.db.select("dormant_sells", {"user_id": uid}, order="em.desc", limit=200) or []
        if not any(r.get("status") in vivas for r in vendas + await self._rows(uid, 200)):
            return
        async with self.lock(uid):                 # relê aqui dentro: uma compra em andamento pode ter acabado de terminar
            for r in [x for x in await self._rows(uid, 200) if x.get("status") in vivas]:
                if now - _ts(r.get("em")) < 20:
                    continue
                try:
                    if CHAINS.get(r["rede"], {}).get("tipo") == "evm":
                        rc = await self.rpc(CHAINS[r["rede"]]["rpc"], "eth_getTransactionReceipt", [r["tx"]])
                        if rc:
                            await self._apply_evm(r, rc)
                            continue
                    elif r.get("tx"):
                        st = (await self.rpc(self.sol_rpc(), "getSignatureStatuses", [[r["tx"]], {"searchTransactionHistory": True}]))["value"][0]
                        if st and st.get("err"):
                            await self._finish(r, status="falhou", motivo=str(st["err"])[:160])
                            continue
                        if st and st.get("confirmationStatus") in ("confirmed", "finalized"):
                            await self._apply_sol(r)
                            continue
                except (BuyError, KeyError, TypeError, IndexError):
                    continue
                if now - _ts(r.get("em")) > EXPIRA_S:
                    await self._finish(r, status="expirada", motivo="não entrou na blockchain")
            for r in [x for x in await self.db.select("dormant_sells", {"user_id": uid}, order="em.desc", limit=200) or [] if x.get("status") in vivas]:
                if now - _ts(r.get("em")) < 20:
                    continue
                try:
                    if CHAINS.get(r["rede"], {}).get("tipo") == "evm":
                        rc = await self.rpc(CHAINS[r["rede"]]["rpc"], "eth_getTransactionReceipt", [r["tx"]])
                        if rc:
                            await self._apply_sell_evm(r, rc)
                            continue
                    elif r.get("tx"):
                        st = (await self.rpc(self.sol_rpc(), "getSignatureStatuses", [[r["tx"]], {"searchTransactionHistory": True}]))["value"][0]
                        if st and st.get("err"):
                            await self._sell_finish(r, status="falhou", motivo=str(st["err"])[:160])
                            continue
                        if st and st.get("confirmationStatus") in ("confirmed", "finalized"):
                            await self._apply_sell_sol(r)
                            continue
                except (BuyError, KeyError, TypeError, IndexError):
                    continue
                if now - _ts(r.get("em")) > EXPIRA_S:
                    await self._sell_finish(r, status="expirada", motivo="não entrou na blockchain")

    # ------------------------------------------------------------------ banco
    async def _rows(self, uid: str, limit: int = 500) -> list[dict]:
        return await self.db.select("dormant_buys", {"user_id": uid}, order="em.desc", limit=limit) or []

    async def spent_today(self, uid: str) -> float:
        since = _iso(time.time() - 86400)
        rows = await self.db.select("dormant_buys", {"user_id": uid}, gte={"em": since}, columns="usd_in,status") or []
        return round(sum(float(r.get("usd_in") or 0) for r in rows if r.get("status") not in ("falhou", "expirada")), 4)

    async def gas_spent_today(self, uid: str) -> float:
        since = _iso(time.time() - 86400)
        rows = await self.db.select("dormant_gas", {"user_id": uid}, gte={"em": since}, columns="usd_in,status") or []
        return round(sum(float(r.get("usd_in") or 0) for r in rows if r.get("status") not in ("falhou", "expirada", "devolvida")), 4)

    async def pending_on(self, uid: str, chain: str) -> bool:
        since = _iso(time.time() - PENDENTE_S)
        rows = await self.db.select("dormant_buys", {"user_id": uid, "rede": chain}, gte={"em": since}, columns="status") or []
        rows += await self.db.select("dormant_sells", {"user_id": uid, "rede": chain}, gte={"em": since}, columns="status") or []
        rows += await self.db.select("dormant_gas", {"user_id": uid, "rede": chain}, gte={"em": since}, columns="status") or []
        return any(r.get("status") in ("enviando", "pendente") for r in rows)

    async def wallet_row(self, uid: str, chain: str) -> dict | None:
        rows = await self.db.select("dormant_wallets", {"user_id": uid, "rede": chain}, limit=1) or []
        return rows[0] if rows else None

    async def _cfg_row(self, uid: str) -> dict:
        rows = await self.db.select("dormant_buy_cfg", {"user_id": uid}, limit=1) or []
        return rows[0] if rows else {"user_id": uid, "cfg": {}, "erros": 0, "trava_ate": None}

    async def cfg(self, uid: str) -> dict:
        return clean_cfg(None, (await self._cfg_row(uid)).get("cfg") or {})

    async def _put_cfg(self, row: dict) -> None:
        await self.db.insert("dormant_buy_cfg", {"user_id": row["user_id"], "cfg": row.get("cfg") or {}, "erros": int(row.get("erros") or 0),
                                                 "trava_ate": row.get("trava_ate"), "em": _iso(time.time())}, upsert=True, on_conflict="user_id")

    # ------------------------------------------------------------------ senha de compra
    async def _open(self, uid: str, wal: dict, senha: str) -> str:
        """Abre a chave com a senha, contando as erradas. A trava fica no banco: reiniciar o servidor não zera."""
        row = await self._cfg_row(uid)
        ate = _ts(row.get("trava_ate")) if row.get("trava_ate") else 0
        if ate > time.time():
            raise BuyError(f"senha errada demais: travado por mais {max(1, round((ate - time.time()) / 60))} min")
        if not isinstance(senha, str) or not senha or len(senha) > vault.SENHA_MAX:
            raise BuyError("digite a senha de compra")
        try:
            secret = await asyncio.to_thread(vault.unseal, self.box, uid, wal["rede"], wal["endereco"], wal["cifra"], senha)
        except vault.WrongPassword:
            row["erros"] = int(row.get("erros") or 0) + 1
            left = MAX_TRIES - row["erros"]
            if left <= 0:
                row["erros"], row["trava_ate"] = 0, _iso(time.time() + LOCK_S)
            await self._put_cfg(row)
            raise BuyError("senha de compra errada" + (f" (mais {left} tentativas)" if left > 0 else f": travado por {LOCK_S // 60} min")) from None
        except CryptoError:
            raise BuyError("a chave guardada não abre (a chave mestra do servidor mudou?): tire a carteira e cadastre de novo") from None
        if row.get("erros") or row.get("trava_ate"):
            row["erros"], row["trava_ate"] = 0, None
            await self._put_cfg(row)
        return secret

    async def _check_senha(self, uid: str, senha: str) -> None:
        """Confere a senha contra uma carteira já guardada. Sem carteira ainda: a senha nova vale como a primeira."""
        rows = await self.db.select("dormant_wallets", {"user_id": uid}, limit=1) or []
        if rows:
            await self._open(uid, rows[0], senha)
        else:
            why = vault.check_new_password(senha)
            if why:
                raise BuyError(why)

    # ------------------------------------------------------------------ carteiras
    async def wallets(self, uid: str) -> dict:
        rows = {r["rede"]: r for r in await self.db.select("dormant_wallets", {"user_id": uid}, columns="rede,endereco,em") or []}
        row = await self._cfg_row(uid)
        ate = _ts(row.get("trava_ate")) if row.get("trava_ate") else 0
        return {"redes": [{"rede": k, "nome": c["nome"], "tipo": c["tipo"], "moeda": c["moeda"], "dex": c["dex"], "endereco": (rows.get(k) or {}).get("endereco"),
                           "em": _ts((rows.get(k) or {}).get("em")) or None} for k, c in CHAINS.items()],
                "cfg": clean_cfg(None, row.get("cfg") or {}), "limites": CFG_LIMITS, "tem_senha": bool(rows), "trava_s": max(0, round(ate - time.time())),
                "trava_geral": bool(self.allowed()), "senha_min": vault.SENHA_MIN}

    async def save_wallet(self, uid: str, chain: str, secret: str, senha: str, todas_evm: bool = False) -> dict:
        if chain not in CHAINS:
            raise BuyError("rede inválida")
        if not isinstance(secret, str) or not 40 <= len(secret.strip()) <= 800:
            raise BuyError("isso não parece uma chave privada")
        secret = secret.strip()
        try:
            addr = key_address(chain, secret)
        except ValueError as e:
            raise BuyError(str(e)) from None
        except Exception:
            raise BuyError("isso não parece uma chave privada") from None
        async with self.lock(uid):
            await self._check_senha(uid, senha)
            alvo = EVM_CHAINS if todas_evm and CHAINS[chain]["tipo"] == "evm" else [chain]
            for k in alvo:
                cifra = await asyncio.to_thread(vault.seal, self.box, uid, k, addr, secret, senha)
                await self.db.insert("dormant_wallets", {"user_id": uid, "rede": k, "endereco": addr, "cifra": cifra, "em": _iso(time.time())},
                                     upsert=True, on_conflict="user_id,rede")
        return {"endereco": addr, "redes": alvo}

    async def remove_wallet(self, uid: str, chain: str) -> None:
        # sem senha, de propósito: quem esqueceu a senha precisa conseguir tirar a chave. Só apaga; não dá acesso a nada.
        if chain not in CHAINS:
            raise BuyError("rede inválida")
        await self.db.delete("dormant_wallets", {"user_id": uid, "rede": chain})

    async def change_password(self, uid: str, atual: str, nova: str) -> int:
        why = vault.check_new_password(nova)
        if why:
            raise BuyError(why)
        async with self.lock(uid):
            rows = await self.db.select("dormant_wallets", {"user_id": uid}) or []
            if not rows:
                raise BuyError("ainda não há carteira cadastrada")
            novas = []
            for r in rows:                         # abre tudo antes de gravar qualquer coisa: ou troca todas, ou nenhuma
                secret = await self._open(uid, r, atual)
                novas.append({"user_id": uid, "rede": r["rede"], "endereco": r["endereco"], "em": r.get("em") or _iso(time.time()),
                              "cifra": await asyncio.to_thread(vault.seal, self.box, uid, r["rede"], r["endereco"], secret, nova)})
            await self.db.insert("dormant_wallets", novas, upsert=True, on_conflict="user_id,rede")
        return len(novas)

    # ------------------------------------------------------------------ ligar e limites
    async def set_on(self, uid: str, on: bool, senha: str = "", confirmar: str = "") -> dict:
        row = await self._cfg_row(uid)
        c = clean_cfg(None, row.get("cfg") or {})
        if on:
            if confirmar != "LIGAR":
                raise BuyError("digite LIGAR para confirmar")
            rows = await self.db.select("dormant_wallets", {"user_id": uid}, limit=1) or []
            if not rows:
                raise BuyError("cadastre uma carteira antes")
            async with self.lock(uid):
                await self._open(uid, rows[0], senha)
            row = await self._cfg_row(uid)
        c["on"] = bool(on)                         # desligar não pede nada: tem que ser fácil
        row["cfg"] = c
        await self._put_cfg(row)
        return c

    async def save_limits(self, uid: str, raw: dict, senha: str) -> dict:
        rows = await self.db.select("dormant_wallets", {"user_id": uid}, limit=1) or []
        row = await self._cfg_row(uid)
        base = clean_cfg(None, row.get("cfg") or {})
        novo = clean_cfg(raw, base)
        if rows and any(novo[k] > base[k] for k in CFG_LIMITS):   # só subir limite pede a senha; baixar é sempre livre
            async with self.lock(uid):
                await self._open(uid, rows[0], senha)
            row = await self._cfg_row(uid)
        row["cfg"] = novo
        await self._put_cfg(row)
        return novo

    # ------------------------------------------------------------------ histórico
    async def history(self, uid: str) -> dict:
        await self.resolve_pending(uid)
        rows = await self._rows(uid)
        sells = await self.db.select("dormant_sells", {"user_id": uid}, order="em.desc", limit=500) or []
        self.watch.held.update(r["cg"] for r in rows if r.get("cg") and r.get("status") == "confirmada")
        out = holdings(rows, self.watch, time.time(), sells=sells)
        out["vendas"] = [{**s, "t": _ts(s.get("em")), "rede_nome": (CHAINS.get(s.get("rede")) or {}).get("nome"), "moeda": (CHAINS.get(s.get("rede")) or {}).get("moeda"),
                          "expl": (CHAINS.get(s.get("rede")) or {}).get("expl")} for s in sells]
        return out
