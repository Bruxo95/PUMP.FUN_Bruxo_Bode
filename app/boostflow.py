"""Compras e vendas do BOOST ao vivo pela blockchain (0.32.458, pedido do dono: "está demorando muito para mostrar os comprados;
quando a análise começa já deve buscar os compradores").

Antes a contagem de compras × vendas vinha só da DexScreener (txns m5). Ela demora para indexar o par novo da PumpSwap: o
token chegava a 12% do BOOST com "0 de 80 compras" e as colunas vazias. Agora, no instante em que o token entra no BOOST, o
servidor assina os logs da blockchain que citam o token (`logsSubscribe` com `mentions`, no RPC do sistema) e conta cada
transação com `Instruction: Buy…` ou `Instruction: Sell…` dos programas da pump.fun (curva) e da PumpSwap. A janela é a
mesma da DexScreener (últimos 5 min). A DexScreener continua como reserva: vale o MAIOR dos dois números, porque a assinatura
pode ter começado alguns segundos depois da migração.

A assinatura fica só enquanto o token está em análise (janela do BOOST aberta e alguém ainda decidindo ou com posição) e
sai quando todos descartam, o DEV é scam, a venda está travada ou o BOOST acaba. No máximo `MAX_SUBS` tokens juntos.
Custo: no Helius o WebSocket padrão cobra pelos dados recebidos (2 créditos a cada 0,1 MB, helius.dev/docs/billing/credits,
conferido em 25/11/2026); cada transação de compra/venda chega com o log inteiro (alguns KB)."""
from __future__ import annotations

import re
import time

PROGS = ("6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",     # pump.fun (curva)
         "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA")     # PumpSwap
WIN_S = 300.0                  # mesma janela da DexScreener (m5)
MAX_SUBS = 25                  # tokens assinados ao mesmo tempo
KEEP_S = 30 * 60               # contagens guardadas por 30 min depois da migração
SIGS_MAX = 5000                # assinaturas lembradas por token (para não contar duas vezes)

_INV = re.compile(r"^Program (\w+) invoke \[\d+\]")
_END = re.compile(r"^Program (\w+) (success|failed)")
_INS = re.compile(r"^Program log: Instruction: (Buy|Sell)", re.I)


def parse_logs(logs) -> tuple[int, int]:
    """(compras, vendas) de UMA transação: 1 se tem alguma instrução Buy/Sell dos programas da pump.fun ou da PumpSwap."""
    stack, buy, sell = [], 0, 0
    for ln in logs or []:
        ln = str(ln)
        m = _INV.match(ln)
        if m:
            stack.append(m.group(1))
            continue
        m = _END.match(ln)
        if m:
            if stack:
                stack.pop()
            continue
        m = _INS.match(ln)
        if m and stack and stack[-1] in PROGS:
            if m.group(1).lower() == "buy":
                buy = 1
            else:
                sell = 1
    return buy, sell


class Flow:
    """Contagem por token: horários das compras e vendas vistas e desde quando o token está assinado."""

    def __init__(self, clock=time.time):
        self.clock = clock
        self.d: dict[str, dict] = {}
        self.st = {"assinados": 0, "msgs": 0, "trades": 0, "erro": None, "fonte": None, "on": False}

    def start(self, mint: str, now: float | None = None) -> None:
        now = self.clock() if now is None else now
        x = self.d.setdefault(mint, {"buys": [], "sells": [], "sigs": set(), "since": now})
        x.setdefault("since", now)

    def note(self, mint: str, sig: str | None, logs, err=None, now: float | None = None) -> tuple[int, int]:
        if err:
            return 0, 0
        x = self.d.get(mint)
        if x is None:
            return 0, 0
        if sig:
            if sig in x["sigs"]:
                return 0, 0
            if len(x["sigs"]) >= SIGS_MAX:
                x["sigs"].clear()
            x["sigs"].add(sig)
        b, s = parse_logs(logs)
        now = self.clock() if now is None else now
        if b:
            x["buys"].append(now)
        if s:
            x["sells"].append(now)
        if b or s:
            self.st["trades"] += 1
            x["last"] = now
        return b, s

    def count(self, mint: str, now: float | None = None) -> dict | None:
        """Compras e vendas dos últimos 5 min; None = token nunca assinado. `cobre` = segundos da janela que a assinatura viu."""
        x = self.d.get(mint)
        if x is None:
            return None
        now = self.clock() if now is None else now
        lo = now - WIN_S
        for k in ("buys", "sells"):
            while x[k] and x[k][0] < lo:
                x[k].pop(0)
        return {"buys": len(x["buys"]), "sells": len(x["sells"]), "cobre_s": round(min(WIN_S, now - x["since"])), "since": x["since"],
                "last": x.get("last")}

    def prune(self, now: float | None = None) -> None:
        now = self.clock() if now is None else now
        for m in [m for m, x in self.d.items() if now - x["since"] > KEEP_S]:
            del self.d[m]


def merge(flow_c: dict | None, dex: dict | None) -> tuple[int | None, int | None, str | None]:
    """Compras e vendas que valem: o maior entre a contagem da blockchain e a da DexScreener (cada uma pode ter começado
    atrasada: a assinatura alguns segundos depois da migração, a DexScreener minutos depois)."""
    fb = fs = db = ds = None
    if flow_c is not None:
        fb, fs = int(flow_c["buys"]), int(flow_c["sells"])
    if dex and dex.get("buys_m5") is not None:
        db, ds = int(dex.get("buys_m5") or 0), int(dex.get("sells_m5") or 0)
    if fb is None and db is None:
        return None, None, None
    if db is None or (fb is not None and fb >= db):
        return fb, max(fs or 0, ds or 0) if ds is not None else fs, "blockchain"
    return db, max(ds or 0, fs or 0) if fs is not None else ds, "DexScreener"
