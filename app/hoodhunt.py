"""Caçador de explosões da Robinhood (0.32.484), SÓ EM SOMBRA: nunca compra nada, nem na FICTÍCIA.

Pedido do dono em 27/11/2026 (caso Super Iguana, SI 0xba1a…2843): "de vez em quando aparecem moedas com explosão de 1.000% a
1 milhão % por dia; entender de onde vêm e, se der, investir alguns centavos automático para não perder o pump".

O que foi conferido na rede no caso SI: o token já existia (pools minúsculos de USDG desde 04/10). Em 26/11 18:34 UTC uma carteira pôs
55% das moedas sozinha num pool novo SI/ETH da Uniswap V4 começando em US$ 0,000002 (uns US$ 2 mil de valor total) e o preço subiu
~25.000× em 17 h. A venda funcionava; o risco era a posição de liquidez ter ficado com a própria carteira (pode tirar o ETH na hora).

Como mede (sem gastar nada): todo pool novo da V4 pago em ETH (evento Initialize, lido na mesma consulta da /hood) entra em observação.
Duas entradas de mentira de US$ 0,10 (ENTRY_USD):
  A · cega: na primeira compra que aparece no pool (até ENTRY_WINDOW_S da criação);
  B · com sinais: quando o pool junta MIN_BUYERS compradores diferentes e MIN_ETH em compras, sem trava acesa;
  C · sinais sem travas: o mesmo sinal da B sem olhar as travas (mostra se as travas ajudam ou só tiram as explosões).
Para cada entrada: preço 1 h, 6 h e 24 h depois e o pico até 24 h. Saídas medidas: segurar 1/6/24 h e vender no alvo 2×/5×/10×/100×
(se o pico passou do alvo; senão vale o preço das 24 h). Liquidez tirada (ModifyLiquidity negativo ≥ RUG_FRAC do que entrou) antes da
marca = vale zero. Venda travada na conferência de golpe (hoodsafe) = vale zero. Taxa do pool na compra e na venda + gás de 2 transações.

Travas anotadas (não bloqueiam nada, só aparecem e entram na conta da entrada B): quem ficou com a liquidez (NFT da posição na mão de uma
carteira = pode tirar), token que já existia antes do pool (relançado), hook que pode mexer no valor da troca (bits ReturnDelta) e
funções perigosas no código do token (mint, pause, blacklist, setFee). Guardado no arquivo da VPS (tabela hood_cacador, dados públicos).
"""
from __future__ import annotations

import asyncio
import logging
import time

from .hood import PM, WETH, ZERO, _hex

log = logging.getLogger("hood")

ARQ = {"tabela": "hood_cacador", "pk": "id", "t": "t", "tipo": "epoch"}
ENTRY_USD = 0.10
ENTRY_WINDOW_S = 1800          # entrada só até 30 min depois de o pool nascer
MIN_BUYERS = 5
MIN_ETH = 0.05
MARKS_H = (1, 6, 24)
TARGETS = (2, 5, 10, 100)
# 0.32.489 (pedido do Bruxo, áudio de 27/11: "parâmetros de porcentagem para saber a melhor porcentagem de entrada e saída"):
# cada entrada guarda a hora em que o preço tocou pela 1ª vez cada alvo (+%) e cada stop (−%), nas primeiras 24 h. A grade junta
# entrada (até quantos % acima do preço inicial do pool) × alvo × stop e diz qual combinação teria dado mais.
GRID_UP = (25, 50, 100, 200, 500, 1000)
GRID_DN = (20, 30, 50, 70)
GRID_IN = (0, 50, 100, 300, 1000)          # 0 = sem limite (entra em qualquer altura)
GAS_ETH = 0.000008             # mesmo gás por transação da cópia da Robinhood (hoodcopy cfg gas_eth)
RUG_FRAC = 0.5
NO_TRADE_DROP_S = 2 * 3600     # pool sem nenhuma troca em 2 h sai da observação
LIVE_MAX = 4000
DONE_MAX = 30000
KEEP_DAYS = 30
CHECKS_PER_TICK = 3
HP_PER_TICK = 2
DEAD = {ZERO, "0x000000000000000000000000000000000000dead"}
# seletores procurados no código do token (só indício: código grande pode ter o texto sem a função)
BAD_SELECTORS = {"40c10f19": "mint", "8456cb59": "pause", "f9f92be4": "blacklist", "44337ea1": "addBlacklist",
                 "69fe0e2d": "setFee", "c0246668": "excludeFromFees", "8f70ccf7": "setTrading"}
T_TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def hook_flags(hook: str) -> list[str]:
    """Permissões do hook V4: ficam nos 14 bits finais do endereço. Só as que importam para quem compra."""
    try:
        a = int(hook, 16)
    except Exception:
        return []
    if not a:
        return []
    out = []
    if a >> 3 & 1:
        out.append("antes da troca muda o valor")
    if a >> 2 & 1:
        out.append("depois da troca muda o valor")
    if a >> 7 & 1:
        out.append("age antes de cada troca")
    if a >> 9 & 1:
        out.append("age na retirada de liquidez")
    return out


def parse_init(log_: dict, t: float) -> dict | None:
    """Initialize(id, currency0, currency1, fee, tickSpacing, hooks, sqrtPriceX96, tick) → pool pago em ETH. None = outro par."""
    tp = [str(x).lower() for x in (log_.get("topics") or [])]
    d = (log_.get("data") or "")[2:]
    if len(tp) < 4 or len(d) < 64 * 4:
        return None
    c0, c1 = "0x" + tp[2][-40:], "0x" + tp[3][-40:]
    if c0 in (ZERO, WETH):
        token, eth_is0 = c1, True
    elif c1 == WETH:
        token, eth_is0 = c0, False
    else:
        return None
    if token in (ZERO, WETH):
        return None
    w = [d[i:i + 64] for i in range(0, 64 * 4, 64)]
    fee, hook, sqrt = int(w[0], 16), "0x" + w[2][-40:], int(w[3], 16)
    px = None
    if sqrt:
        p = (sqrt / 2 ** 96) ** 2                        # moeda1 por moeda0 (as duas com 18 casas)
        px = (1 / p if eth_is0 else p) if p else None    # ETH por token
    return {"id": tp[1], "token": token, "t": round(t, 1), "block": _hex(log_.get("blockNumber")), "tx": log_.get("transactionHash"),
            "fee": fee, "hook": hook, "hook_flags": hook_flags(hook), "px_ini": px, "buys": 0, "sells": 0, "buy_eth": 0.0,
            "sell_eth": 0.0, "buyers": [], "first_t": None, "last_px": None, "last_t": None, "liq_add": 0, "liq_rem": 0,
            "rug_t": None, "checks": None, "hp": None, "a": None, "b": None, "c": None, "fechado": False}


def _fee(p: dict, swap_fee=None) -> float:
    f = p.get("fee")
    if isinstance(f, int) and not f & 0x800000 and 0 <= f < 1_000_000:
        return min(0.10, f / 1e6)
    if isinstance(swap_fee, int) and 0 <= swap_fee < 1_000_000:
        return min(0.10, swap_fee / 1e6)
    return 0.01


def traps(p: dict) -> list[str]:
    """Travas acesas (texto curto). Entram na decisão da entrada B; a A é cega de propósito."""
    out = []
    c = p.get("checks") or {}
    if c.get("lp") == "carteira":
        out.append("liquidez na mão de uma carteira")
    if c.get("relancado"):
        out.append("token já existia antes do pool")
    if c.get("ruins"):
        out.append("código com " + ", ".join(c["ruins"]))
    if any("muda o valor" in f for f in p.get("hook_flags") or []):
        out.append("hook pode cobrar nas trocas")
    if p.get("hp"):
        out.append("venda travada")
    if p.get("rug_t"):
        out.append("liquidez tirada")
    return out


def entry(p: dict, px: float, t: float, fee: float) -> dict:
    return {"t": round(t, 1), "px": px, "fee": fee, "m": {}, "pk": px, "pk_t": round(t, 1), "x_ini": float(f"{px / p['px_ini']:.4g}") if p.get("px_ini") else None}


def on_trade(p: dict, tr: dict) -> None:
    """Uma troca do pool: contadores, preço e as duas entradas de mentira."""
    t, px = tr.get("t") or time.time(), (tr["eth"] / tr["amount"]) if tr.get("amount") else None
    if px is None or px <= 0:
        return
    side = tr.get("side")
    p["last_px"], p["last_t"] = px, t
    p["first_t"] = p.get("first_t") or t
    if side == "buy":
        p["buys"] += 1
        p["buy_eth"] = round(p["buy_eth"] + (tr.get("eth") or 0), 9)
        if tr.get("wallet") and tr["wallet"] not in p["buyers"] and len(p["buyers"]) < 200:
            p["buyers"].append(tr["wallet"])
    else:
        p["sells"] += 1
        p["sell_eth"] = round(p["sell_eth"] + (tr.get("eth") or 0), 9)
    for k in ("a", "b", "c"):
        e = p.get(k)
        if e and t <= e["t"] + 24 * 3600 and px > e["pk"]:
            e["pk"], e["pk_t"] = px, round(t, 1)
        if e and e.get("px") and t <= e["t"] + 24 * 3600:
            hits(e, px, t)
    young = t - p["t"] <= ENTRY_WINDOW_S
    fee = _fee(p, tr.get("fee"))
    if p["a"] is None and side == "buy" and young:
        p["a"] = entry(p, px, t, fee)
    sinal = side == "buy" and young and max(len(p["buyers"]), p.get("n_buyers") or 0) >= MIN_BUYERS and p["buy_eth"] >= MIN_ETH
    if p.get("c") is None and sinal:
        p["c"] = entry(p, px, t, fee)
    if p["b"] is None and sinal and p.get("checks") is not None and not traps(p):
        p["b"] = entry(p, px, t, fee)


def hits(e: dict, px: float, t: float) -> None:
    """0.32.489: 1ª vez que o preço tocou cada alvo e cada stop da grade (só entradas novas guardam)."""
    h = e.setdefault("h", {})
    r = px / e["px"]
    for u in GRID_UP:
        if "u%d" % u not in h and r >= 1 + u / 100:
            h["u%d" % u] = round(t, 1)
    for d in GRID_DN:
        if "d%d" % d not in h and r <= 1 - d / 100:
            h["d%d" % d] = round(t, 1)


def grid_result(p: dict, e: dict, up: int, dn: int, eth_usd: float) -> float | None:
    """Resultado em US$ de uma entrada de ENTRY_USD saindo no alvo +up% ou no stop −dn% (o que vier primeiro); nenhum dos dois em
    24 h = preço da marca de 24 h. Venda travada = zero; liquidez tirada antes da saída = zero. None = ainda aberta ou entrada antiga."""
    h = e.get("h")
    if h is None or not e.get("px"):
        return None
    tu, td = h.get("u%d" % up), h.get("d%d" % dn)
    if p.get("hp"):
        mult = 0.0
    elif tu is not None and (td is None or tu <= td):
        mult = 1 + up / 100
    elif td is not None:
        mult = 1 - dn / 100
    else:
        m24 = e["m"].get("24")
        if m24 is None:
            return None
        mult = m24 / e["px"]
    sai = tu if (tu is not None and (td is None or tu <= td)) else td
    if p.get("rug_t") and (sai is None or p["rug_t"] <= sai):
        mult = 0.0
    f = e.get("fee") if e.get("fee") is not None else 0.01
    return round(ENTRY_USD * mult * (1 - f) ** 2 - ENTRY_USD - 2 * GAS_ETH * (eth_usd or 0), 6)


def grid(pools: list[dict], now: float, dias: float, eth_usd: float, kind: str = "b") -> dict:
    """0.32.489: entrada × alvo × stop da entrada `kind`. Devolve as 10 melhores combinações e a tabela alvo × stop da melhor entrada."""
    since = now - dias * 86400
    es = [(p, p[kind]) for p in pools if p.get("t", 0) >= since and p.get(kind) and p[kind].get("h") is not None]
    combos = []
    for lim in GRID_IN:
        sel = [(p, e) for p, e in es if not lim or (e.get("x_ini") is not None and (e["x_ini"] - 1) * 100 <= lim)]
        for up in GRID_UP:
            for dn in GRID_DN:
                vals = [v for v in (grid_result(p, e, up, dn, eth_usd) for p, e in sel) if v is not None]
                if not vals:
                    continue
                combos.append({"entrada_max_pct": lim, "alvo_pct": up, "stop_pct": dn, "n": len(vals),
                               "resultado_usd": round(sum(vals), 4), "por_entrada_usd": round(sum(vals) / len(vals), 5),
                               "acerto": round(100 * sum(1 for v in vals if v > 0) / len(vals), 1)})
    combos.sort(key=lambda c: (-c["resultado_usd"], -c["n"]))
    best_in = combos[0]["entrada_max_pct"] if combos else 0
    tab = {"entrada_max_pct": best_in, "alvos": list(GRID_UP), "stops": list(GRID_DN),
           "linhas": [[next((c for c in combos if c["entrada_max_pct"] == best_in and c["alvo_pct"] == up and c["stop_pct"] == dn), None)
                       for dn in GRID_DN] for up in GRID_UP]}
    return {"entrada": kind, "entradas": len(es), "melhores": combos[:10], "tabela": tab, "valor_usd": ENTRY_USD,
            "entradas_grade": list(GRID_IN)}


def marks(p: dict, now: float) -> bool:
    """Fecha as marcas 1/6/24 h de cada entrada (preço da última troca até a marca; liquidez tirada antes = 0). True se mudou."""
    ch = False
    for k in ("a", "b", "c"):
        e = p.get(k)
        if not e:
            continue
        for h in MARKS_H:
            mt = e["t"] + h * 3600
            if str(h) in e["m"] or now < mt:
                continue
            rug = p.get("rug_t") and p["rug_t"] <= mt
            e["m"][str(h)] = 0.0 if rug or p.get("hp") else (p.get("last_px") or 0.0)
            ch = True
    if not p["fechado"] and now > p["t"] + ENTRY_WINDOW_S + 24 * 3600 + 120:
        p["fechado"] = True
        ch = True
    return ch


def result(e: dict, exit_: str, eth_usd: float, hp: bool = False) -> float | None:
    """Resultado em US$ de uma entrada de ENTRY_USD com a saída pedida ('1','6','24' horas ou 'x2','x5'…). None = marca ainda aberta."""
    if not e or not e.get("px"):
        return None
    m24 = e["m"].get("24")
    if exit_.startswith("x"):
        tgt = float(exit_[1:])
        if not hp and e.get("pk") and e["pk"] >= tgt * e["px"] * (1 - 1e-9) and (e.get("pk_t") or 0) <= e["t"] + 24 * 3600:
            mult = tgt
        elif m24 is None:
            return None
        else:
            mult = m24 / e["px"]
    else:
        v = e["m"].get(exit_)
        if v is None:
            return None
        mult = 0.0 if hp else v / e["px"]
    f = e.get("fee") if e.get("fee") is not None else 0.01
    gas_usd = 2 * GAS_ETH * (eth_usd or 0)
    return round(ENTRY_USD * mult * (1 - f) ** 2 - ENTRY_USD - gas_usd, 6)


EXITS = [("1", "segurar 1 h"), ("6", "segurar 6 h"), ("24", "segurar 24 h"), ("x2", "vender em 2×"), ("x5", "vender em 5×"),
         ("x10", "vender em 10×"), ("x100", "vender em 100×")]


def study(pools: list[dict], now: float, dias: float, eth_usd: float) -> dict:
    """Conta das duas entradas de mentira no período (pela criação do pool)."""
    since = now - dias * 86400
    ps = [p for p in pools if p.get("t", 0) >= since]
    out = {"dias": dias, "valor_usd": ENTRY_USD, "pools": len(ps), "com_troca": sum(1 for p in ps if p.get("first_t")),
           "explosoes": [], "estrategias": {}}
    for k, nome in (("a", "A · cega (1ª compra)"), ("b", "B · com sinais e sem travas"), ("c", "C · com sinais, ignorando as travas")):
        es = [(p, p[k]) for p in ps if p.get(k)]
        rows = []
        for code, label in EXITS:
            vals = [result(e, code, eth_usd, bool(p.get("hp"))) for p, e in es]
            vals = [v for v in vals if v is not None]
            ganhou = [v for v in vals if v > 0]
            rows.append({"saida": code, "nome": label, "n": len(vals), "investido_usd": round(len(vals) * ENTRY_USD, 2),
                         "resultado_usd": round(sum(vals), 4), "acerto": round(100 * len(ganhou) / len(vals), 1) if vals else None,
                         "melhor_usd": round(max(vals), 4) if vals else None})
        pk = [e["pk"] / e["px"] for _, e in es if e.get("px")]
        out["estrategias"][k] = {"nome": nome, "entradas": len(es), "saidas": rows,
                                 "x10": sum(1 for m in pk if m >= 10), "x100": sum(1 for m in pk if m >= 100),
                                 "liquidez_tirada": sum(1 for p, _ in es if p.get("rug_t")), "venda_travada": sum(1 for p, _ in es if p.get("hp"))}
    for p in ps:
        if p.get("px_ini") and p.get("a") and p["a"].get("pk"):
            x = p["a"]["pk"] / p["px_ini"]
            if x >= 100:
                out["explosoes"].append({"id": p["id"], "token": p["token"], "nome": p.get("nome"), "simbolo": p.get("simbolo"), "t": p["t"],
                                         "x_pico": round(x, 1), "b_entrou": bool(p.get("b")),
                                         "b_x_ini": (p.get("b") or {}).get("x_ini"), "travas": traps(p)})
    out["explosoes"].sort(key=lambda r: -r["x_pico"])
    out["explosoes"] = out["explosoes"][:30]
    return out


def row(p: dict, eth_usd: float) -> dict:
    """Linha da tela: um pool."""
    def ent(e):
        if not e:
            return None
        return {"t": e["t"], "x_ini": e.get("x_ini"), "x_pico": round(e["pk"] / e["px"], 2) if e.get("px") else None,
                "x_agora": round((0.0 if p.get("rug_t") or p.get("hp") else (p.get("last_px") or 0)) / e["px"], 3) if e.get("px") else None,
                "r24": result(e, "24", eth_usd, bool(p.get("hp"))), "rx10": result(e, "x10", eth_usd, bool(p.get("hp")))}
    mc = None
    sup = (p.get("checks") or {}).get("supply")
    if sup and p.get("last_px") and eth_usd:
        mc = round(sup * p["last_px"] * eth_usd, 0)
    return {"id": p["id"], "token": p["token"], "nome": p.get("nome"), "simbolo": p.get("simbolo"), "t": p["t"], "tx": p.get("tx"),
            "compras": p["buys"], "vendas": p["sells"], "compradores": max(len(p["buyers"]), p.get("n_buyers") or 0), "entrou_eth": round(p["buy_eth"], 5),
            "saiu_eth": round(p["sell_eth"], 5), "x_agora": round(p["last_px"] / p["px_ini"], 2) if p.get("px_ini") and p.get("last_px") else None,
            "valor_usd": mc, "ultimo_t": p.get("last_t"), "travas": traps(p), "checks": p.get("checks"), "hook_flags": p.get("hook_flags"),
            "a": ent(p.get("a")), "b": ent(p.get("b")), "c": ent(p.get("c")), "fechado": p.get("fechado")}


def _compact(p: dict) -> dict:
    d = dict(p)
    d["buyers"] = d["buyers"][:MIN_BUYERS]          # para o sinal só precisa saber se chegou a MIN_BUYERS
    d["n_buyers"] = max(len(p["buyers"]), p.get("n_buyers") or 0)
    return d


class Hunter:
    """Liga no HoodWatch como os outros motores extras (watch.extra): recebe pools novos, trocas e retiradas de liquidez."""

    def __init__(self, watch):
        self.w = watch
        self.pools: dict[str, dict] = {}            # observação: id do pool → estado
        self.done: list[dict] = []                  # fechados (24 h passadas), para o estudo
        self.by_token: dict[str, float] = {}
        self._dirty: set[str] = set()
        self._save_at = 0.0
        self._checking = False
        self.stat = {"vistos": 0, "eth": 0, "carregados": 0, "erro": None, "desde": time.time()}

    # ------------------------------------------------------------------ eventos da leitura
    def _block_t(self, block: int) -> float:
        w = self.w
        if w.head and w.head_t:
            return w.head_t - (w.head - block) * w.block_s
        return time.time()

    def note_init(self, inits: list[dict]) -> None:
        for lg in inits:
            self.stat["vistos"] += 1
            p = parse_init(lg, self._block_t(_hex(lg.get("blockNumber"))))
            if not p or p["id"] in self.pools:
                continue
            self.stat["eth"] += 1
            self.pools[p["id"]] = p
        if len(self.pools) > LIVE_MAX:
            for k in sorted(self.pools, key=lambda k: (bool(self.pools[k].get("first_t")), self.pools[k]["t"]))[:len(self.pools) - LIVE_MAX]:
                self.pools.pop(k, None)

    def note_liq(self, mls: list[dict]) -> None:
        """ModifyLiquidity(id, sender, tickLower, tickUpper, liquidityDelta, salt): soma o que entrou e o que saiu de cada pool."""
        for lg in mls:
            tp = lg.get("topics") or []
            p = self.pools.get(str(tp[1]).lower()) if len(tp) > 1 else None
            d = (lg.get("data") or "")[2:]
            if not p or len(d) < 64 * 3:
                continue
            v = int(d[128:192], 16)
            if v >= 2 ** 255:
                v -= 2 ** 256
            if v > 0:
                p["liq_add"] += v
            elif v < 0:
                p["liq_rem"] += -v
                if not p.get("rug_t") and p["liq_add"] and p["liq_rem"] >= RUG_FRAC * p["liq_add"]:
                    p["rug_t"] = round(self._block_t(_hex(lg.get("blockNumber"))), 1)
            self._dirty.add(p["id"])

    def on_trade(self, tr: dict, before=None, cop=None) -> None:
        p = self.pools.get(str(tr.get("pool") or "").lower())
        if not p or p["fechado"] or tr.get("quote") == "USD":
            return
        antes = {k: p.get(k) is None for k in ("a", "b", "c")}
        on_trade(p, tr)
        if p.get("first_t"):
            self._dirty.add(p["id"])
        cop = getattr(self.w, "copier", None)
        for k, era in antes.items():                  # 0.32.489: entrada nova → compra FICTÍCIA nas contas com o Caçador ligado
            if era and p.get(k) and cop is not None and hasattr(cop, "cz_entry"):
                try:
                    cop.cz_entry(p, k)
                except Exception as e:
                    log.warning("Robinhood: compra fictícia do caçador falhou: %s", str(e)[:160])

    def held(self) -> set:
        return {p["token"] for p in self.pools.values() if p.get("first_t") and not p["fechado"]}

    # ------------------------------------------------------------------ conferências (poucas por volta)
    async def _check(self, p: dict) -> None:
        w, tk = self.w, p["token"]
        c = {"ruins": [], "lp": None, "lp_dono": None, "relancado": None, "supply": None}
        code = await w.rpc("eth_getCode", [tk, "latest"]) or "0x"
        c["bytes"] = max(0, len(code) // 2 - 1)
        c["ruins"] = [n for s, n in BAD_SELECTORS.items() if s in code]
        try:
            old = await w.rpc("eth_getCode", [tk, hex(max(0, p["block"] - 1))]) or "0x"
            c["relancado"] = len(old) > 2
        except Exception:
            c["relancado"] = None                     # RPC sem histórico: fica desconhecido
        try:
            s = await w.rpc("eth_call", [{"to": tk, "data": "0x18160ddd"}, "latest"])
            c["supply"] = int(s, 16) / 1e18 if s and s != "0x" else None
        except Exception:
            pass
        try:                                          # quem recebeu a posição de liquidez (NFT) na transação que criou o pool
            rc = await w.rpc("eth_getTransactionReceipt", [p["tx"]]) or {}
            nft = [lg for lg in rc.get("logs") or [] if len(lg.get("topics") or []) == 4 and str(lg["topics"][0]).lower() == T_TRANSFER
                   and str(lg["topics"][1]).endswith("0" * 40)]
            if nft:
                dono = "0x" + str(nft[-1]["topics"][2])[-40:].lower()
                c["lp_dono"] = dono
                if dono in DEAD:
                    c["lp"] = "queimada"
                else:
                    dc = await w.rpc("eth_getCode", [dono, "latest"]) or "0x"
                    # EIP-7702 (0xef0100…) é carteira comum com código delegado
                    c["lp"] = "contrato" if len(dc) > 2 and not dc.lower().startswith("0xef0100") else "carteira"
            else:
                c["lp"] = "sem posição na criação"
        except Exception:
            pass
        p["checks"] = c
        self._dirty.add(p["id"])

    async def _checks(self) -> None:
        if self._checking:
            return
        self._checking = True
        try:
            todo = [p for p in self.pools.values() if p.get("first_t") and p.get("checks") is None and not p["fechado"]]
            todo.sort(key=lambda p: -p["t"])
            for p in todo[:CHECKS_PER_TICK]:
                try:
                    await asyncio.wait_for(self._check(p), 15)
                except Exception as e:
                    p["checks"] = {"erro": str(e)[:80]}
            hp = [p for p in self.pools.values() if p.get("a") and p.get("hp") is None and not p["fechado"]]
            hp.sort(key=lambda p: (not p.get("b"), -p["t"]))
            for p in hp[:HP_PER_TICK]:                # conferência de golpe da /hood (compra e venda simuladas no pool)
                try:
                    v = await asyncio.wait_for(self.w.copier.check_token(p["token"]), 30)
                    p["hp"] = bool(v.get("venda_travada"))
                    p["seguranca"] = {k: v.get(k) for k in ("ok", "why", "venda_travada", "lp_livre", "ida_volta_pct")}
                except Exception:
                    p["hp"] = False
                self._dirty.add(p["id"])
        finally:
            self._checking = False

    # ------------------------------------------------------------------ volta, banco e estudo
    async def tick(self) -> None:
        now = time.time()
        for k, p in list(self.pools.items()):
            if not p.get("first_t") and now - p["t"] > NO_TRADE_DROP_S:
                self.pools.pop(k, None)
                continue
            if marks(p, now):
                self._dirty.add(k)
            if p["fechado"]:
                self.pools.pop(k, None)
                if p.get("a"):
                    self._add_done(p)
        meta = getattr(self.w.copier, "meta", {}) or {}
        for p in self.pools.values():
            m = meta.get(p["token"])
            if m and not p.get("simbolo"):
                p["nome"], p["simbolo"] = m.get("nome"), m.get("simbolo")
        if not self._checking:                       # conferências em tarefa própria: a volta da /hood espera no máx. 40 s
            self._task = asyncio.create_task(self._checks())
        try:
            names = [p["token"] for p in self.pools.values() if p.get("first_t") and not p.get("simbolo")][:30]
            if names:
                await self.w.fill_names(names)
        except Exception as e:
            self.stat["erro"] = str(e)[:160]
        if now - self._save_at > 60:
            self._save_at = now
            await self.save()

    def _add_done(self, p: dict) -> None:
        self.done.append(_compact(p))
        lim = time.time() - KEEP_DAYS * 86400
        if len(self.done) > DONE_MAX or (self.done and self.done[0]["t"] < lim):
            self.done = [d for d in self.done if d["t"] >= lim][-DONE_MAX:]

    async def save(self) -> None:
        arq = getattr(self.w, "arquivo", None)
        if arq is None or not self._dirty:
            return
        ids, self._dirty = list(self._dirty), set()
        rows = [_compact(p) for k in ids for p in [self.pools.get(k) or next((d for d in self.done[-500:] if d["id"] == k), None)]
                if p and p.get("first_t")]
        try:
            for i in range(0, len(rows), 200):
                await arq.put(ARQ, rows[i:i + 200])
            self.stat["erro"] = None
        except Exception as e:
            self._dirty |= set(ids)
            self.stat["erro"] = "gravação: " + str(e)[:140]
            log.warning("Robinhood: caçador não gravou no arquivo: %s", str(e)[:160])

    async def load(self) -> None:
        arq = getattr(self.w, "arquivo", None)
        if arq is None:
            return
        now, n = time.time(), 0
        try:
            async for rows in arq.pages(ARQ["tabela"], now - KEEP_DAYS * 86400):
                for d in rows:
                    if not d.get("id") or not d.get("t"):
                        continue
                    d.setdefault("buyers", [])
                    if d.get("fechado") or now > d["t"] + ENTRY_WINDOW_S + 24 * 3600 + 120:
                        d["fechado"] = True
                        self.done.append(d)
                    else:
                        self.pools[d["id"]] = d
                    n += 1
            self.done.sort(key=lambda d: d["t"])
            self.stat["carregados"] = n
        except Exception as e:
            self.stat["erro"] = "leitura: " + str(e)[:140]
            log.warning("Robinhood: caçador não carregou do arquivo: %s", str(e)[:160])

    def state(self, dias: float = 7.0, now: float | None = None) -> dict:
        now = now or time.time()
        eth_usd = self.w.eth_usd or 0.0
        allp = self.done + list(self.pools.values())
        live = sorted((p for p in self.pools.values() if p.get("first_t")), key=lambda p: -p["t"])[:80]
        return {"ligado": True, "sombra": True, "regra": {"valor_usd": ENTRY_USD, "janela_min": ENTRY_WINDOW_S // 60, "min_compradores": MIN_BUYERS,
                                                          "min_eth": MIN_ETH, "marcas_h": list(MARKS_H), "alvos": list(TARGETS), "gas_eth": GAS_ETH},
                "status": {**self.stat, "observando": len(self.pools), "com_troca": sum(1 for p in self.pools.values() if p.get("first_t")),
                           "fechados": len(self.done), "arquivo": getattr(self.w, "arquivo", None) is not None},
                "estudo": study(allp, now, dias, eth_usd), "agora": [row(p, eth_usd) for p in live], "eth_usd": eth_usd,
                "grade": {k: grid(allp, now, dias, eth_usd, k) for k in ("a", "b", "c")}}
