"""Jupiter (melhor rota entre as DEXs da Solana) — só o necessário para a pump.fun, tirado de
app/solana_dex.py e app/dexcex_exec.py do projeto original.

- `JupiterQuoter`: cotações (públicas). UMA instância para o servidor todo, com um limitador de consultas só,
  para os usuários não multiplicarem chamadas.
- `JupiterWallet`: monta, assina (carteira do usuário, só no servidor) e envia trocas; saldos; troca USDC→SOL.

Usado para: preço executável de tokens já graduados, cópia fora da pump.fun e o botão "Trocar USDC → SOL".
"""
from __future__ import annotations

import asyncio
import base64
import logging
import math
import time
from datetime import datetime, timezone

from . import txguard

log = logging.getLogger("jupiter")

USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
SOL = "So11111111111111111111111111111111111111112"
TOKEN_PROGRAMS = ("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb")
# Rótulos da Jupiter (program-id-to-label) agrupados por DEX
DEXES = {
    "Raydium": "Raydium,Raydium CLMM,Raydium CP",
    "Orca": "Whirlpool,Orca V2",
    "Meteora": "Meteora DLMM,Meteora,Meteora DAMM v2",
}
MAX_PRIORITY_SOL = 0.002          # teto da taxa de prioridade dinâmica da Jupiter


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class _Limiter:
    """Espaça as chamadas para respeitar o limite por minuto."""

    def __init__(self, per_min: float):
        self.gap = 60.0 / max(per_min, 1)
        self._next = 0.0
        self._lock: asyncio.Lock | None = None

    async def wait(self) -> None:
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            now = time.monotonic()
            if now < self._next:
                await asyncio.sleep(self._next - now)
            self._next = max(now, self._next) + self.gap


class JupiterQuoter:
    def __init__(self, http, api_key: str = "", per_min: float = 50):
        self.http = http
        self.jup_base = "https://api.jup.ag" if api_key else "https://lite-api.jup.ag"
        self.jup_headers = {"x-api-key": api_key} if api_key else {}
        self.jup_limit = _Limiter(per_min)
        self._jup_block_until = 0.0
        self._jup_backoff = 7.5
        self.status: dict = {}
        self.no_route = 0

    async def _jup_wait(self) -> None:
        if time.monotonic() < self._jup_block_until:
            await asyncio.sleep(self._jup_block_until - time.monotonic())
        await self.jup_limit.wait()

    async def _quote(self, inp: str, out: str, amount: int, dexes: str | None, direct: bool = True) -> dict | None:
        """Cotação na Jupiter. HTTP 400 não é queda da API: é "sem rota". Nesse caso tenta de novo permitindo passar
        por SOL — ainda só dentro da mesma DEX."""
        params = {"inputMint": inp, "outputMint": out, "amount": str(amount), "slippageBps": 50,
                  "restrictIntermediateTokens": "true"}
        if dexes:
            params["dexes"] = dexes
            if direct:
                params["onlyDirectRoutes"] = "true"
        await self._jup_wait()
        t0 = time.monotonic()
        try:
            r = await self.http.get(f"{self.jup_base}/swap/v1/quote", params=params, headers=self.jup_headers,
                                    timeout=8)
        except Exception as e:
            self.status = {"on": False, "latency_ms": None, "error": str(e)[:100], "at": now_iso()}
            return None
        ms = round((time.monotonic() - t0) * 1000)
        if r.status_code == 200:
            self.status = {"on": True, "latency_ms": ms, "error": None, "at": now_iso()}
            self._jup_backoff = 7.5
            return r.json()
        if r.status_code == 400:
            self.status = {"on": True, "latency_ms": ms, "error": None, "at": now_iso()}
            self.no_route += 1
            if dexes and direct:
                return await self._quote(inp, out, amount, dexes, direct=False)
            return None
        if r.status_code == 429:
            self._jup_backoff = min(120, self._jup_backoff * 2)
            self._jup_block_until = time.monotonic() + self._jup_backoff
        self.status = {"on": False, "latency_ms": ms, "at": now_iso(),
                       "error": f"HTTP {r.status_code}" + (f" (limite de consultas — pausa de {self._jup_backoff:.0f} s)"
                                                           if r.status_code == 429 else "")}
        return None

    async def best_quote(self, inp: str, out: str, amount: int):
        """Cota nas 3 DEXs (Raydium, Orca, Meteora — cada uma isolada) e na melhor rota da Jupiter e escolhe a que
        entrega MAIS. Devolve (cotação, nome da DEX, todas as cotações)."""
        cands = {}
        for name, labels in list(DEXES.items()) + [("Jupiter (rota)", None)]:
            try:
                q = await self._quote(inp, out, amount, labels, direct=labels is not None)
            except Exception:
                q = None
            if q and int(q.get("outAmount") or 0) > 0:
                cands[name] = q
        if not cands:
            return None, None, {}
        best = max(cands, key=lambda k: int(cands[k]["outAmount"]))
        return cands[best], best, {k: int(v["outAmount"]) for k, v in cands.items()}

    async def sol_price_usd(self) -> float | None:
        """Preço do SOL em US$ (cotação de 1 SOL → USDC pela melhor rota)."""
        q = await self._quote(SOL, USDC, 10 ** 9, None, direct=False)
        out = int((q or {}).get("outAmount") or 0) / 1e6
        return out or None


class JupiterWallet:
    """Trocas pela Jupiter com a carteira do bot de UM usuário (assinatura só no servidor)."""

    def __init__(self, http, wallet, quoter: JupiterQuoter, priority_sol: float = 0.0001):
        self.http, self.wallet = http, wallet
        key = getattr(wallet, "jupiter_api_key", "") if wallet is not None else ""
        self.dex = JupiterQuoter(http, key) if key else quoter       # chave própria = limite maior
        self.priority_sol = priority_sol
        self._sol_bal: dict | None = None
        self._sol_bal_at = 0.0

    async def _rpc(self, method: str, params: list):
        r = await self.http.post(await self.wallet.safe_rpc_url(),
                                 json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=15)
        js = r.json()
        if "error" in js:
            raise RuntimeError(str(js["error"].get("message") if isinstance(js["error"], dict) else js["error"])[:200])
        return js["result"]

    async def sol_balances(self, force: bool = False) -> dict:
        """SOL + todos os tokens SPL e Token-2022 da carteira do bot (2 consultas) → {mint: quantidade}."""
        if self.wallet is None or not self.wallet.keypair:
            return {"configured": False}
        if not force and self._sol_bal and time.time() - self._sol_bal_at < 20:
            return self._sol_bal
        addr = self.wallet.address
        out = {"configured": True, "address": addr, "sol": None, "tokens": {}, "raw": {}, "error": None, "at": time.time()}
        try:
            out["sol"] = (await self._rpc("getBalance", [addr]))["value"] / 1e9
            for prog in TOKEN_PROGRAMS:
                res = await self._rpc("getTokenAccountsByOwner", [addr, {"programId": prog}, {"encoding": "jsonParsed"}])
                for a in res.get("value") or []:
                    info = a["account"]["data"]["parsed"]["info"]
                    ta = info["tokenAmount"]
                    amt = float(ta.get("uiAmountString") or ta.get("uiAmount") or 0)
                    out["tokens"][info["mint"]] = out["tokens"].get(info["mint"], 0.0) + amt
                    out["raw"][info["mint"]] = out["raw"].get(info["mint"], 0) + int(ta.get("amount") or 0)
        except Exception as e:
            out["error"] = f"{type(e).__name__}: {str(e)[:120]}"
        self._sol_bal, self._sol_bal_at = out, time.time()
        return out

    async def best_quote(self, inp: str, out: str, amount: int):
        return await self.dex.best_quote(inp, out, amount)

    async def _swap_tx(self, quote: dict, prio: str | None = None, amount: int | None = None) -> tuple[str, str]:
        """prio: None = taxa de prioridade fixa; 'high'/'veryHigh' = taxa dinâmica da Jupiter, com teto.
        Devolve (transação assinada em base64, blockhash). amount: entrada máxima pedida (padrão: a da cotação)."""
        if prio:
            fee = {"priorityLevelWithMaxLamports": {"maxLamports": int(MAX_PRIORITY_SOL * 1e9), "priorityLevel": prio}}
        else:
            fee = int(self.priority_sol * 1e9)
        body = {"quoteResponse": quote, "userPublicKey": self.wallet.address, "wrapAndUnwrapSol": True,
                "dynamicComputeUnitLimit": True, "prioritizationFeeLamports": fee}
        await self.dex._jup_wait()
        r = await self.http.post(f"{self.dex.jup_base}/swap/v1/swap", json=body, headers=self.dex.jup_headers,
                                 timeout=15)
        js = r.json()
        if r.status_code != 200 or "swapTransaction" not in js:
            raise RuntimeError(f"Jupiter swap HTTP {r.status_code}: {str(js)[:160]}")
        from solders.transaction import VersionedTransaction
        tx = VersionedTransaction.from_bytes(base64.b64decode(js["swapTransaction"]))
        # SEC-01 (auditoria 2026-10-25): só assina a rota que usa no máximo o valor e o slippage pedidos
        txguard.check(tx.message, self.wallet.address, max_spend_lamports=0, max_fee_lamports=0,
                      jupiter={"amount": int(amount if amount is not None else quote["inAmount"]),
                               "slip_bps": int(quote.get("slippageBps") or 0)},
                      max_priority_lamports=int(max(MAX_PRIORITY_SOL, self.priority_sol) * 1.5 * 1e9))
        signed = VersionedTransaction(tx.message, [self.wallet.keypair])
        return base64.b64encode(bytes(signed)).decode(), str(tx.message.recent_blockhash)

    async def _send_and_confirm(self, raw: str) -> tuple[str | None, str, str | None]:
        """(assinatura, status, erro). Simulação prévia ligada: se o preço mínimo não der, nada é enviado.
        Reenvia a MESMA transação a cada ~2 s até confirmar (não duplica: mesma assinatura)."""
        try:
            sig = await self._rpc("sendTransaction", [raw, {"encoding": "base64", "skipPreflight": False,
                                                            "preflightCommitment": "processed", "maxRetries": 3}])
        except Exception as e:
            return None, "recusada", str(e)[:160]
        for i in range(80):                           # até ~60 s (validade do blockhash)
            await asyncio.sleep(0.75)
            if i % 3 == 2:
                try:
                    await self._rpc("sendTransaction", [raw, {"encoding": "base64", "skipPreflight": True, "maxRetries": 0}])
                except Exception:
                    pass
            try:
                st = (await self._rpc("getSignatureStatuses", [[sig]]))["value"][0]
            except Exception:
                continue
            if st and st.get("err"):
                return sig, "falhou", str(st["err"])[:120]
            if st and st.get("confirmationStatus") in ("confirmed", "finalized"):
                return sig, "confirmada", None
        return sig, "pendente", "sem confirmação em 60 s (rede congestionada / transação expirou)"

    async def _dex_swap(self, inp: str, out: str, amount: int, slip_bps: int = 100, prio: str | None = "high") -> dict:
        q, venue, allq = await self.best_quote(inp, out, amount)
        if not q:
            return {"ok": False, "reason": "sem cotação em nenhuma DEX"}
        try:
            raw, blockhash = await self._swap_tx(dict(q, slippageBps=slip_bps), prio=prio, amount=amount)
        except Exception as e:
            return {"ok": False, "reason": f"erro ao montar a transação ({str(e)[:100]})"}
        sig, st, err = await self._send_and_confirm(raw)
        if st == "pendente":                     # SEC-04: não deixa quem chamou montar outra antes de saber
            st, err = await txguard.reconcile(self._rpc, sig, blockhash)
        return {"ok": st == "confirmada", "signature": sig, "status": st, "reason": err,
                "out": int(q.get("outAmount") or 0), "venue": venue, "quotes": allq}

    async def usdc_to_sol(self, usdc: float, preview: bool = False) -> dict:
        """Troca USDC por SOL na carteira do bot (melhor rota/DEX). preview=True só cota, não troca."""
        if self.wallet is None or not self.wallet.keypair:
            return {"error": "carteira Solana do bot não configurada"}
        if not math.isfinite(usdc) or usdc <= 0:            # NaN/infinito passavam e davam HTTP 500 (SEC-11)
            return {"error": "valor inválido"}
        sb = await self.sol_balances(force=True)
        have = (sb.get("tokens") or {}).get(USDC, 0.0)
        if usdc > have + 1e-9:
            return {"error": f"saldo insuficiente: a carteira tem {have:.2f} USDC"}
        if (sb.get("sol") or 0) < 0.003:
            return {"error": f"a carteira precisa de um pouco de SOL para pagar a taxa da troca (tem {sb.get('sol') or 0:.4f}; "
                             "mande pelo menos 0,005 SOL)"}
        amount = int(usdc * 1e6) if usdc < have else int(round(((sb.get("raw") or {}).get(USDC) or have * 1e6)))
        q, venue, allq = await self.best_quote(USDC, SOL, amount)
        if not q:
            return {"error": "sem cotação em nenhuma DEX agora"}
        out = int(q.get("outAmount") or 0) / 1e9
        res = {"usdc": amount / 1e6, "sol_out": out, "venue": venue, "price": (amount / 1e6) / out if out else None,
               "impact_pct": round(float(q.get("priceImpactPct") or 0) * 100, 4)}
        if preview:
            return res
        sol0 = sb.get("sol") or 0.0
        r = await self._dex_swap(USDC, SOL, amount, slip_bps=50, prio="high")
        if r.get("status") == "pendente":
            await asyncio.sleep(3)
        sb2 = await self.sol_balances(force=True)
        got = (sb2.get("sol") or 0.0) - sol0
        ok = r.get("ok") or got > out * 0.5
        log.info("Troca USDC→SOL: %.2f USDC → %.4f SOL (%s)", amount / 1e6, got, "ok" if ok else r.get("reason"))
        return {**res, "ok": bool(ok), "sol_received": round(got, 6), "signature": r.get("signature"),
                "status": r.get("status"), "reason": None if ok else r.get("reason"),
                "sol_balance": sb2.get("sol"), "usdc_balance": (sb2.get("tokens") or {}).get(USDC, 0.0)}
