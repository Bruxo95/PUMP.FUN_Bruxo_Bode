"""0.32.338 (pedido do dono, 13/11/2026): motor do BOT LIVE. É a CÓPIA da Robinhood exatamente como estava na versão 0.32.308
(app/hoodcopy.py do commit 92c4840), separada da /hood: carteira simulada própria por conta (tabelas botlive_*), mesmas leituras da
rede (o HoodWatch entrega os mesmos trades aos dois motores). Nunca compra de verdade: sem cofre (vault) e real_allowed sempre False.
Não mexer na lógica daqui: o dono quer a estratégia da 0.32.308 no BOT LIVE.

Texto original:
Robinhood Chain, etapa 2 (0.32.279): cópia dos traders do ranking. Fictícia em ETH por conta de admin e REAL (desligada).

Pedido do dono em 10/11/2026 ("faz 1 a 4"): 1) cópia FICTÍCIA em ETH, 2) checagem de token golpe (hoodsafe), 3) preço das
posições abertas (stop e tempo máximo), 4) compra e venda REAL (hoodreal), que começa desligada e só liga com LIGAR.

Regra de cópia, igual à da BNB e ao Copiar igual da Solana: quando um trader que o ranking copiaria compra, a fictícia compra o
valor fixo; quando ele vende, vende a mesma parte. Sai também pelo tempo máximo e pelo stop opcional. A taxa do pool (lida no
evento Swap de cada troca) vale nos dois lados; gás e slippage configuráveis. Só pools da Uniswap V4 pagos em ETH: é o que a
REAL consegue comprar, então a fictícia mede a mesma coisa.

Preço das posições: o de cada troca do token lida na rede (ETH ÷ quantidade) e, para o token parado, a cotação de venda do
Quoter oficial da V4 a cada PRICE_S (uma consulta por token, no máximo PRICE_MAX por volta).
Isolado: memória e tabelas hood_* próprias; nada da Solana nem da BNB é usado ou alterado.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime

from . import evm
from . import botlive_real308 as hoodreal
from . import botlive_safe308 as hoodsafe
from .dormant_buy import T_V4_INIT, v4_key_from_log, v4_pool_id, v4_quote_data

log = logging.getLogger("botlive.copy")

HOOD_KEY_NAME = "hood_private_key"
ZERO = "0x" + "0" * 40
GT = "https://api.geckoterminal.com/api/v2/networks/robinhood/pools/"
FRESH_S = 90                 # só copia compra lida até 90 s depois de acontecer (a releitura depois de reiniciar não copia)
PRICE_S, PRICE_MAX = 30, 20
KEEP_TRADES = 3000
# 0.32.284 (pedido do dono, 10/11/2026: "botão aqui pra já clicar e começar a copiar"): cada conta escolhe traders à mão
# (manual, até MANUAL_MAX), copiados mesmo sem passar na regra do ranking; auto_top = copiar também o "Copiando agora".
MANUAL_MAX = 50
# 0.32.287 (pedido do dono: "3 botões: copiar REAL, copiar FICTÍCIA ou as 2"): modo por trader escolhido (sim, real, ambas)
MODOS = ("sim", "real", "ambas")
# 0.32.290 (pedido do dono, 11/11/2026: "sair quando o desenvolvedor sai da moeda ... stop móvel com as mesmas regras ... botão de
# ativar"): sair_trader / sair_dev (saldo do trader e do dev lidos na rede) e stop móvel igual ao da Solana (liga ao passar de
# trail_ativa_pct de lucro líquido; sai se cair trail_dist_pct pontos do pico, travando no mínimo TRAIL_MIN_LOCK).
# 0.32.302 (pedido do dono, 11/11: "um botão bloquear e uma aba dos honeypot"): carteiras que esta conta bloqueou; nunca são copiadas
BLOCK_MAX = 500
CFG_DEFAULT = {"on": True, "auto_top": True, "manual": [], "modo": {}, "bloqueados": [], "tokens_bloqueados": [], "eth_por_compra": 0.01, "max_abertas": 10, "max_hold_h": 6.0, "stop_pct": 0.0,
               "slip_pct": 2.0, "gas_eth": 0.00002, "saldo_inicial": 0.5, "um_por_token": True, "sair_trader": True, "trader_so_lucro": True, "sair_dev": True,
               "trail_on": True, "trail_ativa_pct": 20.0, "trail_dist_pct": 10.0}
CFG_LIMITS = {"eth_por_compra": (0.0005, 5), "max_abertas": (1, 100), "max_hold_h": (0.1, 168), "stop_pct": (0, 100),
              "slip_pct": (0, 50), "gas_eth": (0, 0.01), "saldo_inicial": (0.001, 1000), "trail_ativa_pct": (1, 10000),
              "trail_dist_pct": (1, 1000)}
CFG_BOOLS = ("on", "auto_top", "um_por_token", "sair_trader", "trader_so_lucro", "sair_dev", "trail_on")
TRAIL_MIN_LOCK = 2.0
# Acompanhar o trader e o dev: saldo do token na carteira deles (balanceOf) a cada FOLLOW_S, até FOLLOW_MAX tokens por volta.
FOLLOW_S, FOLLOW_MAX = 60, 25
TRADER_OUT = 0.05            # trader com 5% ou menos do maior saldo visto = saiu da moeda
DEV_OUT = 0.50               # dev que vendeu metade ou mais do maior saldo visto = saiu da moeda
OLD_POS_S = 600              # posição de antes desta regra (sem saldo lido): trader com saldo zero também conta como saída
# Preço reserva pela DexScreener (pedido do dono: "não está indo com a realidade do gráfico"): token sem preço novo há DEX_STALE
# (Quoter falhou, pool sem liquidez, golpe) usa o preço do par em ETH da DexScreener; o nome e o símbolo vêm junto.
DEX_URL = "https://api.dexscreener.com/tokens/v1/robinhood/"
EXPLORER = "https://robinhoodchain.blockscout.com"
DEX_S, DEX_STALE, DEX_BATCH = 60, 120, 30
ZERO_READS, ZERO_MIN_AGE_S = 3, 300
WETH = "0x0bd7d308f8e1639fab988df18a8011f41eacad73"
SEL_BAL = "0x70a08231"


def trail_hit(cfg: dict, best: float, pct: float, pre: str = "") -> str | None:
    """Stop móvel (mesma regra da Solana): ligado e o pico passou de ativa% → sai se cair dist pontos do pico (no mínimo +2%)."""
    if not cfg.get(pre + "trail_on"):
        return None
    ativa, dist = float(cfg.get(pre + "trail_ativa_pct") or 20), float(cfg.get(pre + "trail_dist_pct") or 10)
    if best < ativa:
        return None
    sai = max(best - dist, TRAIL_MIN_LOCK)
    if pct <= sai:
        return f"stop móvel: pico {best:+.0f}%, saiu em {pct:+.0f}%"
    return None


DYNAMIC_FEE = 0x800000      # Uniswap V4: marca de "taxa dinâmica" no campo fee da PoolKey (não é a taxa)
FEE_MAX = 0.10


def pool_fee(key: list | None, swap_fee=None) -> float:
    """Taxa do pool em fração (0,01 = 1%). 0.32.281 (caso PONS do dono, 10/11/2026: +543.649% de mentira): no pool de taxa
    dinâmica o campo fee da chave é a marca 0x800000, que lida como taxa dava 838%; a conta da posição ficou negativa × negativa
    e virou lucro. Agora: taxa fixa da chave; senão a taxa cobrada na troca do trader (evento Swap); senão 1%. Nunca acima de 10%."""
    f = key[2] if key and len(key) > 2 else None
    if isinstance(f, int) and not f & DYNAMIC_FEE and 0 <= f < 1_000_000:
        return min(FEE_MAX, f / 1e6)
    if isinstance(swap_fee, int) and 0 <= swap_fee < 1_000_000:
        return min(FEE_MAX, swap_fee / 1e6)
    return 0.01


def repair(p: dict) -> bool:
    """Posição gravada com a taxa errada (0.32.279/280): refaz a quantidade com a taxa certa e zera o pico. True se mexeu."""
    fee = p.get("fee")
    if isinstance(fee, (int, float)) and 0 <= fee <= FEE_MAX and (p.get("tokens") or 0) > 0:
        return False
    f = pool_fee(p.get("key"))
    old_t, old_l = p.get("tokens") or 0, p.get("tokens_left") or 0
    frac = old_l / old_t if old_t and old_l and (old_l > 0) == (old_t > 0) else 1.0
    tokens = max(0.0, (p["eth_in"] - p.get("fees_gas", 0.0)) * (1 - f) / p["px_in"]) if p.get("px_in") else 0.0
    p.update(fee=f, tokens=tokens, tokens_left=tokens * frac, best_pct=0.0, worst_pct=0.0, corrigido="taxa do pool refeita (0.32.281)")
    return True


def clean_cfg(raw: dict | None, base: dict | None = None) -> dict:
    out = dict(base or CFG_DEFAULT)
    out["manual"] = list(out.get("manual") or [])
    out["modo"] = dict(out.get("modo") or {})
    out["bloqueados"] = list(out.get("bloqueados") or [])
    out["tokens_bloqueados"] = list(out.get("tokens_bloqueados") or [])
    for k, v in (raw or {}).items():
        if k == "modo" and isinstance(v, dict):
            out["modo"] = {str(w).lower(): m for w, m in v.items() if m in MODOS}
        elif k in CFG_BOOLS:
            out[k] = bool(v)
        elif k in ("bloqueados", "tokens_bloqueados"):
            ws = [str(x).strip().lower() for x in (v if isinstance(v, list) else [])]
            out[k] = list(dict.fromkeys(x for x in ws if len(x) == 42 and x.startswith("0x")
                                                   and all(ch in "0123456789abcdef" for ch in x[2:])))[:BLOCK_MAX]
        elif k == "manual":
            ws = [str(x).strip().lower() for x in (v if isinstance(v, list) else [])]
            out["manual"] = list(dict.fromkeys(x for x in ws if len(x) == 42 and x.startswith("0x")
                                               and all(ch in "0123456789abcdef" for ch in x[2:])))[:MANUAL_MAX]
        elif k in CFG_LIMITS:
            try:
                val = float(v)
            except (TypeError, ValueError):
                continue
            if val != val:
                continue
            lo, hi = CFG_LIMITS[k]
            val = min(hi, max(lo, val))
            out[k] = int(val) if isinstance(CFG_DEFAULT[k], int) else round(val, 6)
    out["modo"] = {w: m for w, m in out["modo"].items() if w in out["manual"]}
    return out


class Book:
    """Carteira fictícia em ETH de uma conta."""

    def __init__(self, user_id: str, cfg: dict | None = None, cash: float | None = None):
        self.user_id = user_id
        self.cfg = clean_cfg(cfg)
        self.cash = self.cfg["saldo_inicial"] if cash is None else float(cash)
        self.pos: dict[str, dict] = {}
        self.trades: list[dict] = []
        self.events: list[dict] = []
        self.dirty_pos: set = set()
        self.closed_pos: set = set()
        self.new_trades: list[dict] = []
        self.dirty_book = False
        self.close_hook = None                     # 0.32.306: avisa a cópia quando a posição fecha (espelho da REAL)

    def ev(self, t: float, wallet: str, token: str, acao: str, motivo: str = "") -> None:
        self.events.insert(0, {"t": t, "wallet": wallet, "token": token, "acao": acao, "motivo": motivo})
        del self.events[200:]

    def mode_of(self, wallet: str, auto: bool) -> str | None:
        """Onde esta conta copia o trader: 'sim', 'real' ou 'ambas' (escolhido no botão; o Copiando agora vale nas duas) ou None."""
        if wallet in (self.cfg.get("bloqueados") or []):
            return None
        if wallet in (self.cfg.get("manual") or []):
            return (self.cfg.get("modo") or {}).get(wallet, "ambas")
        if auto and self.cfg.get("auto_top", True):
            return "ambas"
        return None

    def follows(self, wallet: str, auto: bool) -> str | None:
        """Por que a FICTÍCIA desta conta copia o trader: 'manual' (botão), 'top' (Copiando agora) ou None."""
        m = self.mode_of(wallet, auto)
        if m not in ("sim", "ambas"):
            return None
        return "manual" if wallet in (self.cfg.get("manual") or []) else "top"

    def real_follows(self, wallet: str, auto: bool) -> bool:
        return self.mode_of(wallet, auto) in ("real", "ambas")

    def value_now(self, p: dict) -> float:
        px = p.get("px_now") or p["px_in"]
        return p["tokens_left"] * px * (1 - (p.get("fee") or 0) - self.cfg["slip_pct"] / 100) - self.cfg["gas_eth"]

    def pnl_now(self, p: dict) -> tuple[float, float]:
        v = p["proceeds"] + max(0.0, self.value_now(p)) - p["eth_in"]
        return v, (100 * v / p["eth_in"] if p["eth_in"] else 0.0)

    def buy(self, tr: dict, px: float, t: float, key: list, origem: str = "top") -> dict | None:
        c = self.cfg
        why = None
        amt = c["eth_por_compra"]
        if tr["token"] in (c.get("tokens_bloqueados") or []):
            why = "moeda bloqueada por você (Dinheiro entrando → Honeypot e bloqueadas)"
        elif not c["on"] and origem != "botao":
            why = "cópia fictícia desligada nesta conta"
        elif not px or px <= 0:
            why = "sem preço do token"
        elif any(p["wallet"] == tr["wallet"] and p["token"] == tr["token"] for p in self.pos.values()):
            why = "já tem a posição deste trader neste token"
        elif c.get("um_por_token") and any(p["token"] == tr["token"] for p in self.pos.values()):
            # 0.32.301 (pedido do dono: "não entrar mais de 1 vez no mesmo contrato do token se já estiver na posição")
            why = "já tem posição neste token (de outro trader): uma entrada por token"
        elif len(self.pos) >= c["max_abertas"]:
            why = f"limite de {c['max_abertas']} posições abertas"
        elif self.cash < amt + c["gas_eth"]:
            why = "saldo fictício insuficiente"
        if why:
            self.ev(t, tr["wallet"], tr["token"], "não copiou", why)
            return None
        fee_r = pool_fee(key, tr.get("fee"))
        px_in = px * (1 + c["slip_pct"] / 100)
        fee = amt * fee_r
        tokens = (amt - fee) / px_in
        p = {"id": uuid.uuid4().hex[:16], "wallet": tr["wallet"], "token": tr["token"], "open_t": t, "px_in": px_in,
             "trader_px": px, "trader_eth": tr.get("eth"), "tokens": tokens, "tokens_left": tokens, "fee": fee_r,
             "eth_in": round(amt + c["gas_eth"], 9), "proceeds": 0.0, "fees": fee + c["gas_eth"], "px_now": px, "px_t": t,
             "best_pct": 0.0, "worst_pct": 0.0, "lag_s": round(max(0.0, t - tr["t"]), 1), "tx_in": tr.get("tx"), "aba": origem,
             "key": key}
        self.cash -= amt + c["gas_eth"]
        self.pos[p["id"]] = p
        self.dirty_pos.add(p["id"])
        self.dirty_book = True
        self.ev(t, tr["wallet"], tr["token"], "copiou compra", f"{amt:g} ETH, {p['lag_s']:.0f} s depois do trader")
        return p

    def sell(self, p: dict, frac: float, px: float | None, t: float, motivo: str) -> dict | None:
        """Vende a parte frac (0–1) da posição; 0,95 ou mais vende tudo. Devolve o trade quando fecha."""
        c = self.cfg
        px = px or p.get("px_now") or p["px_in"]
        frac = 1.0 if frac >= 0.95 else max(0.0, frac)
        q = p["tokens_left"] * frac
        if q <= 0:
            return None
        gross = q * px * (1 - c["slip_pct"] / 100)
        fee = gross * (p.get("fee") or 0)
        got = gross - fee - c["gas_eth"]
        p["tokens_left"] -= q
        p["proceeds"] += got
        p["fees"] += fee + c["gas_eth"]
        p["px_now"], p["px_t"] = px, t
        self.cash += got
        self.dirty_book = True
        if frac < 1.0:
            p.setdefault("vendas", []).append({"t": t, "frac": round(frac, 4), "eth": round(got, 6), "motivo": motivo})
            self.dirty_pos.add(p["id"])
            self.ev(t, p["wallet"], p["token"], "vendeu parte", f"{frac * 100:.0f}% · {motivo}")
            if self.close_hook:
                try:
                    self.close_hook(self.user_id, p, motivo, frac)
                except Exception as e:
                    log.warning("Robinhood: espelho da REAL falhou na venda parcial: %s", str(e)[:120])
            return None
        pnl = p["proceeds"] - p["eth_in"]
        tr = {**{k: p.get(k) for k in ("id", "wallet", "token", "open_t", "px_in", "trader_px", "eth_in", "fees",
                                        "best_pct", "worst_pct", "lag_s", "tx_in", "aba", "vendas", "nome", "simbolo", "px_src")},
              "close_t": t, "px_out": px, "eth_out": round(p["proceeds"], 9), "pnl_eth": round(pnl, 9),
              "pnl_pct": round(100 * pnl / p["eth_in"], 2) if p["eth_in"] else 0.0, "motivo": motivo,
              "taxas_eth": round(p.get("fees") or 0.0, 9)}
        self.pos.pop(p["id"], None)
        self.dirty_pos.discard(p["id"])
        self.closed_pos.add(p["id"])
        self.trades.insert(0, tr)
        del self.trades[KEEP_TRADES:]
        self.new_trades.append(tr)
        self.ev(t, p["wallet"], p["token"], "fechou", f"{motivo} · {pnl:+.5f} ETH")
        if self.close_hook:
            try:
                self.close_hook(self.user_id, p, motivo)
            except Exception as e:                 # o espelho nunca derruba o fechamento da fictícia
                log.warning("Robinhood: espelho da REAL falhou ao fechar: %s", str(e)[:120])
        return tr

    def trader_exit(self, p: dict, frac: float, px: float | None, t: float, motivo: str) -> dict | None:
        """Venda puxada pelo trader (vendeu ou saiu da moeda). 0.32.292 (pedido do dono: "sair somente se estiver positivo +
        taxas, se não aguarda ficar positivo"): com trader_so_lucro, no prejuízo (já com taxa do pool, folga e gás) não vende;
        guarda a parte em p["espera"] e vende quando o resultado passar de zero. Stop de perda e tempo máximo continuam valendo."""
        if px:
            p["px_now"], p["px_t"] = px, t
        if self.cfg.get("trader_so_lucro") and self.pnl_now(p)[1] <= 0:
            ant = (p.get("espera") or {}).get("frac") or 0.0
            p["espera"] = {"frac": round(1.0 if frac >= 0.95 else 1 - (1 - ant) * (1 - frac), 4), "motivo": motivo, "t": t}
            self.dirty_pos.add(p["id"])
            if not ant:
                self.ev(t, p["wallet"], p["token"], "segurando", f"{motivo} · no prejuízo, espera ficar positivo")
            return None
        if p.get("espera"):
            ant = p.pop("espera")["frac"]
            frac = 1.0 if frac >= 0.95 else 1 - (1 - ant) * (1 - frac)
        return self.sell(p, frac, px, t, motivo)

    def on_price(self, token: str, px: float, t: float) -> list[dict]:
        out = []
        for p in list(self.pos.values()):
            if p["token"] != token or px <= 0:
                continue
            p["px_now"], p["px_t"] = px, t
            _, pct = self.pnl_now(p)
            p["best_pct"], p["worst_pct"] = max(p["best_pct"], pct), min(p["worst_pct"], pct)
            self.dirty_pos.add(p["id"])
            why = f"stop de {self.cfg['stop_pct']:.0f}%" if self.cfg["stop_pct"] and pct <= -self.cfg["stop_pct"] else \
                trail_hit(self.cfg, p["best_pct"], pct)
            frac = 1.0
            if not why and p.get("espera") and (pct > 0 or not self.cfg.get("trader_so_lucro")):
                e = p.pop("espera")
                why, frac = f"{e['motivo']} · vendeu ao ficar positivo ({pct:+.1f}%)", e["frac"]
            if why:
                r = self.sell(p, frac, px, t, why)
                if r:
                    out.append(r)
        return out

    def timeouts(self, t: float) -> list[dict]:
        lim = self.cfg["max_hold_h"] * 3600
        return [r for p in list(self.pos.values()) if t - p["open_t"] >= lim
                for r in [self.sell(p, 1.0, None, t, f"tempo máximo de {self.cfg['max_hold_h']:g} h")] if r]

    def wallet(self, now: float) -> dict:
        open_val = sum(max(0.0, self.value_now(p)) for p in self.pos.values())
        total = self.cash + open_val
        ini = self.cfg["saldo_inicial"]
        closed = self.trades
        wins = [x for x in closed if x["pnl_eth"] > 0]
        return {"saldo": round(self.cash, 6), "em_posicoes": round(open_val, 6), "total": round(total, 6),
                "inicial": ini, "resultado": round(total - ini, 6), "resultado_pct": round(100 * (total - ini) / ini, 2) if ini else 0,
                "abertas": len(self.pos), "fechadas": len(closed), "acerto": round(100 * len(wins) / len(closed), 1) if closed else None,
                "realizado": round(sum(x["pnl_eth"] for x in closed), 6), "periodos": periods(closed, now),
                "taxas": round(sum(taxa(x) for x in closed) + sum(p.get("fees") or 0.0 for p in self.pos.values()), 6),
                "taxas_fechadas": round(sum(taxa(x) for x in closed), 6)}


def taxa(x: dict) -> float:
    """Taxas pagas num trade fechado (0.32.294, pedido do Bruxo): taxa do pool nos dois lados + gás. Trade antigo sem o campo usa `fees`."""
    v = x.get("taxas_eth")
    return float(v if v is not None else (x.get("fees") or 0.0))


def periods(trades: list[dict], now: float) -> list[dict]:
    out = []
    for h in (1, 6, 12, 24):
        xs = [x for x in trades if x["close_t"] >= now - h * 3600]
        out.append({"h": h, "n": len(xs), "ganhos": sum(1 for x in xs if x["pnl_eth"] > 0), "taxas": round(sum(taxa(x) for x in xs), 6),
                    "pnl": round(sum(x["pnl_eth"] for x in xs), 6), "investido": round(sum(x["eth_in"] for x in xs), 6),
                    "traders": len({x["wallet"] for x in xs})})
    return out


class Copier:
    """Cópia da Robinhood: carteiras fictícias, conferência do token, preço das posições e carteira REAL. watch = HoodWatch."""

    def __init__(self, watch, http, db=None):
        self.w, self.http, self.db = watch, http, db
        self.books: dict[str, Book] = {}
        self.real: dict[str, hoodreal.RealBook] = {}
        self.real_cfg: dict[str, dict] = {}
        self.vault = None
        self.real_allowed = False
        self._keys: dict[str, tuple] = {}
        # 0.32.283: a REAL envia e confere pelo RPC oficial da rede (a transação não passa por servidor de terceiros antes)
        self.chain = hoodreal.Chain(lambda m, p: watch.rpc(m, p, getattr(watch, "official", None)))
        self.safe = hoodsafe.Safety(self._call, http)
        from .hoodgas import HoodGas
        self.gas = HoodGas(self)                     # 0.32.286: saldo da carteira e abastecer de outra rede (Relay)
        self.keys: dict[str, list | None] = {}      # id do pool → chave conferida (None = procurado e não achado)
        self._key_at: dict[str, float] = {}
        self._px_at: dict[str, float] = {}
        self._checking: set = set()
        self._tasks: set = set()
        self._rbal_at = 0.0
        self.meta: dict[str, dict] = {}             # token → {"nome", "simbolo"} (DexScreener)
        self.dev: dict[str, str] = {}               # token → carteira de quem criou ("" = não achou)
        self._dev_at: dict[str, float] = {}
        self._px_ok: dict[str, float] = {}          # última vez que o Quoter deu preço
        self._dex_at = self._follow_at = 0.0
        self._follow_i = 0
        self.stat = {"compras_vistas": 0, "copiadas": 0, "barradas": 0, "sem_pool": 0, "pool_procurado": 0}

    # ------------------------------------------------------------------ util
    async def _call(self, to: str, data: str, frm: str | None = None) -> str:
        p = {"to": to, "data": data}
        if frm:
            p["from"] = frm
        return await self.w.rpc("eth_call", [p, "latest"]) or "0x"

    def _spawn(self, coro) -> None:
        t = asyncio.ensure_future(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    def book(self, uid: str) -> Book:
        b = self.books.get(uid)
        if b is None:
            b = self.books[uid] = Book(uid)
            b.dirty_book = True
        b.close_hook = self._sim_closed
        return b

    # ------------------------------------------------------------------ 0.32.306: REAL espelha a FICTÍCIA
    def mirrors(self, uid: str, wallet: str, auto: bool) -> bool:
        """Pedido do dono (11/11): "a carteira real tem que seguir 100% a fictícia nas entradas". Com real_espelho, a REAL compra
        quando (e só quando) a FICTÍCIA da conta abre posição de um trader copiado nas duas, e fecha quando ela fecha."""
        rc, b = self.real_cfg.get(uid) or {}, self.books.get(uid)
        return bool(rc.get("real_on") and rc.get("real_espelho") and b and b.cfg.get("on")
                    and b.follows(wallet, auto) and b.real_follows(wallet, auto))

    def mirrored(self, uid: str, rp: dict) -> bool:
        """0.32.308: posição REAL presa a uma da FICTÍCIA (sim_id) com o espelho ligado: só a FICTÍCIA decide a saída (as regras de
        saída da REAL — trader vendeu, stop, stop móvel, dev, tempo máximo — não agem nela; a REAL repete o que a fictícia fizer)."""
        return bool(rp.get("sim_id") and (self.real_cfg.get(uid) or {}).get("real_espelho"))

    def _sim_closed(self, uid: str, p: dict, motivo: str, frac: float = 1.0) -> None:
        rb = self.real.get(uid)
        pares = [x for x in (rb.pos.values() if rb else []) if x.get("sim_id") == p["id"]]
        if not pares:
            return
        if not (self.real_cfg.get(uid) or {}).get("real_espelho") or str(motivo).startswith("vendido por você"):
            for rp in pares:                         # venda à mão só na fictícia: a REAL se solta e volta às regras próprias
                rp.pop("sim_id", None)
                rp["solta"] = "fictícia vendida à mão"
                rb.dirty_pos.add(rp["id"])
            return
        for rp in pares:
            rp.pop("espera", None)
            if rp.get("selling"):                    # já está vendendo: a parte que faltar sai na nova tentativa
                rp["retry_frac"] = 1.0 if frac >= 0.95 else max(rp.get("retry_frac") or 0, frac)
                continue
            rp["retry_frac"] = frac
            self._spawn(self._real_sell(uid, rp, frac, ("fictícia fechou: " if frac >= 0.95 else "fictícia vendeu parte: ") + str(motivo)[:80]))

    def rbook(self, uid: str) -> hoodreal.RealBook:
        rb = self.real.get(uid)
        if rb is None:
            rb = self.real[uid] = hoodreal.RealBook(uid)
        return rb

    # 0.32.347: ganchos para o BOT LIVE guardar dados próprios na linha de botlive_books (link do OBS)
    def _book_extra(self, uid: str) -> dict:
        return {}

    def _book_loaded(self, row: dict) -> None:
        return None

    def rcfg(self, uid: str) -> dict:
        if uid not in self.real_cfg:
            self.real_cfg[uid] = hoodreal.clean(None)
        return self.real_cfg[uid]

    def held(self) -> set:
        return {p["token"] for b in self.books.values() for p in b.pos.values()} | \
            {p["token"] for rb in self.real.values() for p in rb.pos.values()}

    # ------------------------------------------------------------------ chave do pool
    def note_init(self, logs: list[dict]) -> None:
        """Eventos Initialize do PoolManager lidos junto com as trocas: guarda a chave dos pools novos (só os pagos em ETH)."""
        for lg in logs:
            k = v4_key_from_log(lg)
            if k and k[0] == ZERO:
                self.keys[v4_pool_id(k)] = k
        if len(self.keys) > 20000:
            for pid in list(self.keys)[:5000]:
                self.keys.pop(pid, None)

    async def pool_key(self, pid: str, token: str) -> list | None:
        """Chave do pool pelo id: a que a leitura já viu nascer, senão o Initialize procurado perto da data em que o pool
        nasceu (GeckoTerminal só dá a data; a chave vem da rede e só vale se o keccak dela for o id)."""
        pid = (pid or "").lower()
        if pid in self.keys and (self.keys[pid] or time.time() - self._key_at.get(pid, 0) < 1800):
            return self.keys[pid]
        self.stat["pool_procurado"] += 1
        self._key_at[pid] = time.time()
        key = None
        try:
            r = await self.http.get(GT + pid, headers={"accept": "application/json"}, timeout=10)
            created = (((r.json() or {}).get("data") or {}).get("attributes") or {}).get("pool_created_at")
            ts = datetime.fromisoformat(str(created).replace("Z", "+00:00")).timestamp() if created else None
        except Exception:
            ts = None
        head, head_t, bs = self.w.head, self.w.head_t, self.w.block_s or 0.1
        if head and head_t:
            spans = []
            if ts:
                est = int(head - max(0.0, head_t - ts) / bs)
                spans.append((max(0, est - 1_000_000), min(head, est + 1_000_000)))
            b = head                                          # sem a data (ou fora da estimativa): volta em trechos de 9 milhões
            for _ in range(3):
                spans.append((max(0, b - 9_000_000), b))
                b -= 9_000_000
            for a, z in spans:
                try:
                    logs = await self.w.rpc("eth_getLogs", [{"address": hoodreal.PM, "topics": [T_V4_INIT, pid],
                                                              "fromBlock": hex(a), "toBlock": hex(z)}]) or []
                except Exception:
                    continue
                for lg in logs:
                    k = v4_key_from_log(lg)
                    if k and v4_pool_id(k) == pid:
                        key = k
                        break
                if key:
                    break
                await asyncio.sleep(1.0)
        self.keys[pid] = key if key and key[0] == ZERO and key[1] == token else None
        return self.keys[pid]

    # ------------------------------------------------------------------ cópia
    def on_trade(self, tr: dict, before: float, copiaria: list) -> None:
        """Trade novo lido: atualiza o preço das posições; quem tem posição copiada vendeu → vende a mesma parte; o trader do
        ranking comprou → confere o token e compra na fictícia (e na REAL ligada)."""
        px = tr["eth"] / tr["amount"] if tr.get("amount") else None
        now = time.time()
        # 0.32.287 (pedido do dono): com REAL e FICTÍCIA ligadas a prioridade é da REAL: a venda REAL sai primeiro
        for uid, rb in self.real.items():
            if px:
                self._real_price(uid, rb, tr["token"], px, tr["t"])
            if tr["side"] == "sell":
                frac = min(1.0, tr["amount"] / before) if before > 0 else 1.0
                for p in [p for p in rb.pos.values() if p["wallet"] == tr["wallet"] and p["token"] == tr["token"] and not self.mirrored(uid, p)]:
                    self._real_trader_exit(uid, p, frac, f"trader vendeu {frac * 100:.0f}%", tr["t"])
        for b in self.books.values():
            if px:
                b.on_price(tr["token"], px, tr["t"])
            if tr["side"] == "sell":
                frac = min(1.0, tr["amount"] / before) if before > 0 else 1.0
                for p in [p for p in b.pos.values() if p["wallet"] == tr["wallet"] and p["token"] == tr["token"]]:
                    b.trader_exit(p, frac, px, now, f"trader vendeu {frac * 100:.0f}%")
        auto = tr["wallet"] in copiaria
        if tr["side"] == "buy" and hasattr(self.w, "danger_reason") and self.w.danger_reason(tr["wallet"]):
            self.stat["perigo_ignorados"] = self.stat.get("perigo_ignorados", 0) + 1     # 0.32.302: PERIGO não é copiado nem na FICTÍCIA
            return
        if tr["side"] == "buy" and now - tr["t"] <= FRESH_S and any(b.mode_of(tr["wallet"], auto) for b in self.books.values()):
            tr["_auto"] = auto
            self.stat["compras_vistas"] += 1
            self._spawn(self._prepare(tr, px))

    async def _prepare(self, tr: dict, px: float | None) -> None:
        tk = tr["token"]
        try:
            key = await self.pool_key(tr.get("pool") or "", tk)
            if not key:
                self.stat["sem_pool"] += 1
                v = {"ok": False, "why": "o pool deste trade não é da Uniswap V4 pago em ETH (ou não achei o pool na rede)"}
            else:
                v = self.safe.cached(tk)
                if v is None:
                    v = await self.safe.check(tk, key, tr["wallet"], int(tr["amount"] * 1e18), pool_fee(key, tr.get("fee")))
        except Exception as e:                                   # nunca compra sem conferir
            key, v = None, self.safe.mark(tk, False, "falha na conferência (" + type(e).__name__ + ")", erro=True)
        self._buy_all(tr, v, key, px)

    def _buy_all(self, tr: dict, v: dict, key: list | None, px: float | None) -> None:
        now = time.time()
        if not v["ok"] or not key:
            self.stat["barradas"] += 1
            why = "token barrado: " + (v.get("why") or "sem conferência")
            for b in self.books.values():
                if b.cfg.get("on") and b.follows(tr["wallet"], tr.get("_auto", True)):
                    b.ev(now, tr["wallet"], tr["token"], "não copiou", why)
            for uid, rc in list(self.real_cfg.items()):
                if rc.get("real_on") and self.book(uid).real_follows(tr["wallet"], tr.get("_auto", True)):
                    self.rbook(uid).ev(now, tr["wallet"], tr["token"], "REAL não copiou", why)
            return
        self.stat["copiadas"] += 1
        # 0.32.287: a REAL sai primeiro; a FICTÍCIA da mesma conta depois passa a usar o preço que a REAL pagou (_align)
        reais = 0
        perigo = self.w.danger_reason(tr["wallet"]) if hasattr(self.w, "danger_reason") else None
        auto = tr.get("_auto", True)
        espelho = {uid for uid in list(self.real_cfg) if self.mirrors(uid, tr["wallet"], auto)}
        for uid, rc in list(self.real_cfg.items()):
            if uid in espelho or (rc.get("real_espelho") and (self.books.get(uid) and self.books[uid].cfg.get("on"))):
                continue                            # 0.32.306/307: com o espelho a REAL só entra depois da FICTÍCIA, nunca sozinha
            if rc.get("real_on") and self.book(uid).real_follows(tr["wallet"], tr.get("_auto", True)):
                if tr["token"] in (self.book(uid).cfg.get("tokens_bloqueados") or []):
                    self.rbook(uid).ev(now, tr["wallet"], tr["token"], "REAL não copiou", "moeda bloqueada por você")
                    continue
                if perigo:                          # 0.32.295: trader PERIGO nunca compra na REAL, mesmo se já estava sendo copiado
                    self.rbook(uid).ev(now, tr["wallet"], tr["token"], "REAL não copiou", "trader marcado PERIGO: " + perigo)
                    continue
                self._spawn(self._real_buy(uid, tr, px, key))
                reais += 1

        def sim() -> None:
            for uid, b in list(self.books.items()):
                why = b.follows(tr["wallet"], tr.get("_auto", True))
                if why:
                    p = b.buy(tr, px, now, key, why)
                    if p and uid in espelho:
                        if perigo:
                            self.rbook(uid).ev(now, tr["wallet"], tr["token"], "REAL não copiou", "trader marcado PERIGO: " + perigo)
                            continue
                        self._spawn(self._real_buy(uid, {**tr, "_sim_id": p["id"]}, px, key))
        if reais:                                  # a FICTÍCIA entra na fila depois das compras REAL (elas começam primeiro)
            asyncio.get_running_loop().call_soon(sim)
        else:
            sim()

    # ------------------------------------------------------------------ carteira REAL
    async def get_key(self, uid: str):
        """(chave, endereço) da carteira da Robinhood da conta, ou (None, None). A chave nunca sai da memória do servidor."""
        k = self._keys.get(uid)
        if k and time.time() - k[2] < 300:
            return k[0], k[1]
        if self.vault is None:
            return None, None
        try:
            v = (await self.vault.load(uid)).get(HOOD_KEY_NAME)
            key = evm.parse_key(v) if v else None
        except Exception:
            key = None
        addr = evm.address_of(key) if key else None
        self._keys[uid] = (key, addr, time.time())
        if addr:
            self.rbook(uid).address = addr
        return key, addr

    def real_status(self, uid: str) -> dict:
        rc, rb = self.real_cfg.get(uid) or hoodreal.clean(None), self.real.get(uid)
        k = self._keys.get(uid)
        return {"permitido": self.real_allowed, "chave": bool(k and k[0]),
                "endereco": (k[1] if k else None) or (rb.address if rb else None),
                "ligada": bool(rc.get("real_on")), "desde": rc.get("on_since"), "saldo": rb.balance if rb else None}

    def _real_price(self, uid: str, rb, token: str, px: float, t: float) -> None:
        rc = self.rcfg(uid)
        for p in list(rb.pos.values()):
            if p["token"] != token or px <= 0:
                continue
            p["px_now"], p["px_t"] = px, t
            _, pct = rb.pnl_now(p, rc["real_slip_pct"])
            p["best_pct"], p["worst_pct"] = max(p.get("best_pct", 0), pct), min(p.get("worst_pct", 0), pct)
            rb.dirty_pos.add(p["id"])
            if self.mirrored(uid, p):
                continue
            why = f"stop de {rc['real_stop_pct']:g}%" if rc["real_stop_pct"] and pct <= -rc["real_stop_pct"] else \
                trail_hit(rc, p["best_pct"], pct, "real_")
            frac = 1.0
            if not why and p.get("espera") and (pct > 0 or not rc.get("real_trader_so_lucro")):
                why, frac = f"{p['espera']['motivo']} · vendeu ao ficar positivo ({pct:+.1f}%)", p["espera"]["frac"]
            if why and not p.get("selling") and (p.get("sell_retry_at") or 0) <= time.time():
                p.pop("espera", None)
                p["retry_frac"] = frac
                self._spawn(self._real_sell(uid, p, frac, why))

    def real_why_not(self, uid: str, tr: dict, rb, rc: dict) -> str | None:
        if not self.real_allowed:
            return "trava geral do servidor fechada (PUMP_REAL_ALLOWED)"
        if any(p["wallet"] == tr["wallet"] and p["token"] == tr["token"] for p in rb.pos.values()) or (tr["wallet"], tr["token"]) in rb.busy:
            return "já tem a posição REAL deste trader neste token"
        if rc.get("real_um_por_token") and (any(p["token"] == tr["token"] for p in rb.pos.values()) or any(t == tr["token"] for _, t in rb.busy)):
            return "já tem posição REAL neste token (de outro trader): uma entrada por token"
        if len(rb.pos) + len(rb.busy) >= rc["real_max_abertas"]:
            return f"limite de {rc['real_max_abertas']} posições REAL abertas"
        lost = rb.lost_today(time.time())
        if lost >= rc["real_perda_dia"]:
            return f"perda do dia ({lost:.5f} ETH) chegou ao limite de {rc['real_perda_dia']:g} ETH: volta amanhã (00:00 UTC)"
        if rb.balance is not None and rb.balance < rc["real_eth_por_compra"] + hoodreal.GAS_RESERVE:
            return f"saldo da carteira ({rb.balance:.5f} ETH) menor que a compra + {hoodreal.GAS_RESERVE} ETH de gás"
        return None

    async def _real_buy(self, uid: str, tr: dict, px: float | None, pkey: list) -> None:
        rb, rc = self.rbook(uid), self.rcfg(uid)
        now = time.time()
        key, addr = await self.get_key(uid)
        why = "sem a chave da carteira da Robinhood" if not key else self.real_why_not(uid, tr, rb, rc)
        sv = self.safe.cached(tr["token"])
        if not why and not (sv and sv["ok"]):                    # a REAL nunca compra token sem conferência boa
            why = "token sem conferência de segurança aprovada"
        if why:
            rb.ev(now, tr["wallet"], tr["token"], "REAL não copiou", why)
            return
        k = (tr["wallet"], tr["token"])
        rb.busy.add(k)
        try:
            async with rb.lock:
                if rb.balance is None or time.time() - rb.balance_t > 30:
                    rb.balance, rb.balance_t = await self.chain.balance(addr) / 1e18, time.time()
                if rb.balance < rc["real_eth_por_compra"] + hoodreal.GAS_RESERVE:
                    rb.ev(now, tr["wallet"], tr["token"], "REAL não copiou", f"saldo da carteira ({rb.balance:.5f} ETH) menor que a compra + gás")
                    return
                until = time.time() + rc["real_max_hold_h"] * 3600 + 86400
                res = await self.chain.buy(key, addr, tr["token"], pkey, rc["real_eth_por_compra"], rc["real_slip_pct"], until)
            t = time.time()
            p = hoodreal.new_position(tr, res, t, px, pkey)
            if tr.get("_sim_id"):
                p["sim_id"] = tr["_sim_id"]
            rb.pos[p["id"]] = p
            bk = self.books.get(uid)
            sp = bk.pos.get(p["sim_id"]) if p.get("sim_id") and bk is not None else None
            if sp and sp.get("tokens") and sp["tokens_left"] < sp["tokens"] * 0.999:
                fr = 1 - sp["tokens_left"] / sp["tokens"]     # a fictícia vendeu parte enquanto a REAL comprava: repete
                p["retry_frac"] = fr
                self._spawn(self._real_sell(uid, p, fr, f"fictícia já tinha vendido {fr * 100:.0f}%"))
            rb.dirty_pos.add(p["id"])
            rb.balance_t = 0
            rb.ev(t, tr["wallet"], tr["token"], "REAL comprou", f"{rc['real_eth_por_compra']:g} ETH, {t - tr['t']:.0f} s depois do trader", res["tx"])
            self._align(uid, p)
            log.info("Robinhood REAL: comprou %s… %.5f ETH (conta %s…)", tr["token"][:10], res["eth"], uid[:8])
        except Exception as e:
            rb.ev(time.time(), tr["wallet"], tr["token"], "REAL falhou", str(e)[:200])
            log.warning("Robinhood REAL: compra falhou (%s…): %s", tr["token"][:10], str(e)[:160])
        finally:
            rb.busy.discard(k)
            await self.flush()

    def _align(self, uid: str, rp: dict) -> None:
        """0.32.287 (pedido do dono: prioridade da REAL): a posição FICTÍCIA do mesmo trader e token passa a usar o preço de entrada que a
        REAL pagou de verdade (mesma quantidade em ETH; muda só quantos tokens isso compra), para as duas mostrarem o mesmo resultado."""
        b = self.books.get(uid)
        if not b or not rp.get("px_in"):
            return
        for p in b.pos.values():
            if p["wallet"] == rp["wallet"] and p["token"] == rp["token"] and not p.get("vendas") and abs(p["open_t"] - rp["open_t"]) < 600 and p.get("px_in"):
                k = p["px_in"] / rp["px_in"]
                p.update(tokens=p["tokens"] * k, tokens_left=p["tokens_left"] * k, px_in_ficticio=p["px_in"], px_in=rp["px_in"], alinhado_real=True)
                b.dirty_pos.add(p["id"])

    async def _real_sell(self, uid: str, p: dict, frac: float, motivo: str, manual: bool = False) -> dict | None:
        rb, rc = self.rbook(uid), self.rcfg(uid)
        if p.get("selling") or p["id"] not in rb.pos:
            return None
        if not manual and (p.get("sell_retry_at") or 0) > time.time():
            return None
        p["selling"] = True
        frac = 1.0 if frac >= 0.95 else max(0.0, frac)
        try:
            key, addr = await self.get_key(uid)
            if not key:
                raise hoodreal.ChainError("sem a chave da carteira: cole a chave em Carteira para vender")
            left = int(p["raw_left"])
            raw = left if frac >= 1 else int(left * frac)
            async with rb.lock:
                try:
                    res = await self.chain.sell(key, addr, p["token"], p["key"], raw, rc["real_slip_pct"])
                except hoodreal.ChainError as e:
                    # 0.32.307 (caso 4Robinhood, 11/11 11:55 UTC: comprou e 24 s depois fechou em -100% por uma leitura de saldo
                    # zero): só fecha com saldo zero lido 3 vezes, com 1 min entre elas e a posição aberta há 5 min ou mais
                    if "não tem mais" in str(e) and (int(p.get("zero_reads") or 0) < ZERO_READS - 1 or time.time() - p["open_t"] < ZERO_MIN_AGE_S):
                        p["zero_reads"] = int(p.get("zero_reads") or 0) + 1
                        raise hoodreal.ChainError(f"a carteira aparece sem o token (leitura {p['zero_reads']} de {ZERO_READS}); confere de novo em 1 min")
                    if "não tem mais" in str(e):
                        p["tokens_left"], p["raw_left"] = 0.0, "0"
                        tr = rb.close(p, time.time(), "a carteira não tem mais o token (vendido fora do sistema?)", p.get("px_now"))
                        rb.ev(time.time(), p["wallet"], p["token"], "REAL fechou", tr["motivo"])
                        return tr
                    raise
            t = time.time()
            p["raw_left"] = str(max(0, left - res["raw"]))
            p["tokens_left"] = max(0.0, p["tokens_left"] - res["raw"] / 1e18)
            p["proceeds"] += res["eth"]
            p["fees"] = p.get("fees", 0) + res.get("gas", 0)
            p["tx_last"] = res["tx"]
            for k in ("sell_error", "sell_retry_at", "retry_frac", "zero_reads"):
                p.pop(k, None)
            rb.balance_t = 0
            if int(p["raw_left"]) > 0 and frac < 1:
                p.setdefault("vendas", []).append({"t": t, "frac": round(frac, 4), "eth": round(res["eth"], 6), "motivo": motivo, "tx": res["tx"]})
                rb.dirty_pos.add(p["id"])
                rb.ev(t, p["wallet"], p["token"], "REAL vendeu parte", f"{frac * 100:.0f}% · {motivo}", res["tx"])
                return None
            tr = rb.close(p, t, motivo, p.get("px_now"))
            rb.ev(t, p["wallet"], p["token"], "REAL fechou", f"{motivo} · {tr['pnl_eth']:+.5f} ETH", res["tx"])
            return tr
        except Exception as e:
            p["sell_error"] = str(e)[:200]
            p["sell_retry_at"] = time.time() + (60 if p.get("zero_reads") else hoodreal.RETRY_S)
            p.setdefault("retry_frac", frac)
            rb.dirty_pos.add(p["id"])
            rb.ev(time.time(), p["wallet"], p["token"], "REAL falhou ao vender", str(e)[:200])
            log.warning("Robinhood REAL: venda falhou (%s…): %s", p["token"][:10], str(e)[:160])
            if manual:
                raise
            return None
        finally:
            p["selling"] = False
            await self.flush()

    # ------------------------------------------------------------------ laço (chamado pela leitura a cada volta)
    async def tick(self) -> None:
        now = time.time()
        for b in self.books.values():
            b.timeouts(now)
        bal = now - self._rbal_at > 30
        if bal:
            self._rbal_at = now
        for uid, rb in list(self.real.items()):
            cf = self.rcfg(uid)
            bk = self.books.get(uid)
            for p in list(rb.pos.values()):
                if self.mirrored(uid, p):
                    if bk is not None and p["sim_id"] not in bk.pos and not p.get("selling") and now - p["open_t"] > 20 \
                            and (p.get("sell_retry_at") or 0) <= now:
                        p["retry_frac"] = 1.0                  # a fictícia já fechou (ex.: fechou enquanto a REAL comprava)
                        self._spawn(self._real_sell(uid, p, 1.0, "fictícia já fechou esta posição"))
                    elif p.get("sell_error") and (p.get("sell_retry_at") or 0) <= now and p.get("retry_frac"):
                        self._spawn(self._real_sell(uid, p, p["retry_frac"], "nova tentativa de venda"))
                    continue
                if now - p["open_t"] >= cf["real_max_hold_h"] * 3600:
                    p["retry_frac"] = 1.0
                    self._spawn(self._real_sell(uid, p, 1.0, f"tempo máximo de {cf['real_max_hold_h']:g} h"))
                elif p.get("sell_error") and (p.get("sell_retry_at") or 0) <= now and p.get("retry_frac"):
                    self._spawn(self._real_sell(uid, p, p["retry_frac"], "nova tentativa de venda"))
            if bal and (rb.address or self.rcfg(uid).get("real_on")):
                _, addr = await self.get_key(uid)
                if addr:
                    try:
                        rb.balance, rb.balance_t = await self.chain.balance(addr) / 1e18, now
                    except Exception:
                        pass
        await self.price_tick(now)
        if now - self._dex_at >= DEX_S:
            self._dex_at = now
            await self.dex_tick(now)
        if now - self._follow_at >= FOLLOW_S:
            self._follow_at = now
            await self.follow_tick(now)
        await self.flush()

    async def price_tick(self, now: float) -> None:
        """Token aberto sem troca lida há PRICE_S: preço pela cotação de venda do Quoter (o que a posição receberia)."""
        n = 0
        for tk in self.held():
            last = max(self.w.px.get(tk, (0, 0))[1], self._px_at.get(tk, 0))
            if now - last < PRICE_S or n >= PRICE_MAX:
                continue
            pos = [p for b in self.books.values() for p in b.pos.values() if p["token"] == tk] + \
                  [p for rb in self.real.values() for p in rb.pos.values() if p["token"] == tk]
            key = next((p.get("key") for p in pos if p.get("key")), None)
            if not key:
                continue
            n += 1
            self._px_at[tk] = now
            try:                                              # 10% da menor posição: pouco impacto no preço do pool
                amt = max(10 ** 12, int(min(p["tokens_left"] for p in pos) * 1e17))
                w = evm.words(await self._call(hoodsafe.QUOTER, v4_quote_data(key, amt, False)))
            except Exception:
                continue
            if not w or not w[0]:
                continue
            fee = next((p["fee"] for p in pos if isinstance(p.get("fee"), (int, float)) and 0 <= p["fee"] <= FEE_MAX), pool_fee(key))
            px = w[0] / amt / (1 - fee)                       # o Quoter já tira a taxa do pool: volta ao preço sem ela
            self.w.px[tk] = (px, now)
            self._px_ok[tk] = now
            self._set_src(tk, "rede")
            for b in self.books.values():
                b.on_price(tk, px, now)
            for uid, rb in list(self.real.items()):
                self._real_price(uid, rb, tk, px, now)

    # ------------------------------------------------------------------ preço reserva, nome e saída do trader / dev (0.32.290)
    def _positions(self, tk: str) -> list[tuple]:
        """(uid, posição, é_real) de todas as contas abertas no token."""
        return [(uid, p, False) for uid, b in self.books.items() for p in b.pos.values() if p["token"] == tk] + \
               [(uid, p, True) for uid, rb in self.real.items() for p in rb.pos.values() if p["token"] == tk]

    def _set_src(self, tk: str, src: str) -> None:
        for _, p, _ in self._positions(tk):
            p["px_src"] = src

    async def dex_tick(self, now: float) -> None:
        """Nome e símbolo dos tokens abertos e, para o token sem preço novo há DEX_STALE (Quoter falhou, pool sem liquidez),
        o preço do par em ETH da DexScreener (o mesmo do gráfico). Uma consulta para até DEX_BATCH tokens."""
        tks = sorted(self.held())
        stale = [tk for tk in tks if now - max(self.w.px.get(tk, (0, 0))[1], self._px_ok.get(tk, 0)) >= DEX_STALE]
        need = list(dict.fromkeys(stale + [tk for tk in tks if tk not in self.meta]))[:DEX_BATCH]
        if not need:
            return
        try:
            js = (await self.http.get(DEX_URL + ",".join(need), timeout=10)).json()
        except Exception as e:
            log.info("Robinhood: DexScreener não respondeu: %s", str(e)[:120])
            return
        best: dict[str, tuple] = {}
        for pr in js if isinstance(js, list) else []:
            base = pr.get("baseToken") or {}
            tk = (base.get("address") or "").lower()
            if tk not in need:
                continue
            if base.get("symbol") or base.get("name"):
                if len(self.meta) > 5000:
                    for k in list(self.meta)[:1000]:
                        self.meta.pop(k, None)
                self.meta[tk] = {"nome": str(base.get("name") or "")[:40], "simbolo": str(base.get("symbol") or "")[:20]}
            q = ((pr.get("quoteToken") or {}).get("address") or "").lower()
            try:
                px, liq = float(pr.get("priceNative") or 0), float((pr.get("liquidity") or {}).get("usd") or 0)
            except (TypeError, ValueError):
                continue
            if q in (WETH, ZERO) and px > 0 and (tk not in best or liq > best[tk][1]):
                best[tk] = (px, liq)
        for tk in tks:
            m = self.meta.get(tk)
            if m:
                for _, p, _ in self._positions(tk):
                    if p.get("nome") != m["nome"] or p.get("simbolo") != m["simbolo"]:
                        p.update(m)
        for tk in stale:
            if tk not in best:
                continue
            px = best[tk][0]
            self.w.px[tk] = (px, now)
            for b in self.books.values():
                b.on_price(tk, px, now)
            for uid, rb in list(self.real.items()):
                self._real_price(uid, rb, tk, px, now)
            self._set_src(tk, "dexscreener")

    async def _balance(self, tk: str, who: str) -> int | None:
        try:
            w = evm.words(await self._call(tk, SEL_BAL + "0" * 24 + who.lower()[2:]))
            return int(w[0]) if w else None
        except Exception:
            return None

    async def _dev_of(self, tk: str, now: float) -> str:
        """Quem criou o token: remetente da transação que criou o contrato (Blockscout). Guarda; tenta de novo em 30 min."""
        if tk in self.dev and (self.dev[tk] or now - self._dev_at.get(tk, 0) < 1800):
            return self.dev[tk]
        self._dev_at[tk] = now
        dev = ""
        try:
            a = (await self.http.get(f"{EXPLORER}/api/v2/addresses/{tk}", timeout=10)).json() or {}
            h = a.get("creation_transaction_hash") or a.get("creation_tx_hash")
            if h:
                tx = (await self.http.get(f"{EXPLORER}/api/v2/transactions/{h}", timeout=10)).json() or {}
                dev = ((tx.get("from") or {}).get("hash") or "").lower()
            if not dev:
                dev = (a.get("creator_address_hash") or "").lower()
        except Exception as e:
            log.info("Robinhood: criador do token %s não veio: %s", tk[:10], str(e)[:100])
        self.dev[tk] = dev if len(dev) == 42 else ""
        if len(self.dev) > 5000:
            for k in list(self.dev)[:1000]:
                self.dev.pop(k, None)
        return self.dev[tk]

    def _real_trader_exit(self, uid: str, p: dict, frac: float, motivo: str, now: float) -> None:
        """Venda da REAL puxada pelo trader: igual à da fictícia (trader_exit), com real_trader_so_lucro."""
        rc, rb = self.rcfg(uid), self.rbook(uid)
        if rc.get("real_trader_so_lucro") and rb.pnl_now(p, rc["real_slip_pct"])[1] <= 0:
            ant = (p.get("espera") or {}).get("frac") or 0.0
            p["espera"] = {"frac": round(1.0 if frac >= 0.95 else 1 - (1 - ant) * (1 - frac), 4), "motivo": motivo, "t": now}
            rb.dirty_pos.add(p["id"])
            if not ant:
                rb.ev(now, p["wallet"], p["token"], "segurando", f"{motivo} · no prejuízo, espera ficar positivo")
            return
        if p.get("espera"):
            ant = p.pop("espera")["frac"]
            frac = 1.0 if frac >= 0.95 else 1 - (1 - ant) * (1 - frac)
        if p.get("selling") or (p.get("sell_retry_at") or 0) > now:
            return
        p["retry_frac"] = frac
        self._spawn(self._real_sell(uid, p, frac, motivo))

    def _exit(self, uid: str, p: dict, real: bool, regra: str, motivo: str, now: float) -> None:
        so_trader = regra == "sair_trader"
        if real:
            if self.mirrored(uid, p):
                return
            if self.rcfg(uid).get("real_" + regra):
                if so_trader:
                    self._real_trader_exit(uid, p, 1.0, motivo, now)
                elif not p.get("selling") and (p.get("sell_retry_at") or 0) <= now:
                    p["retry_frac"] = 1.0
                    self._spawn(self._real_sell(uid, p, 1.0, motivo))
        else:
            b = self.books.get(uid)
            if b and b.cfg.get(regra) and p["id"] in b.pos:
                (b.trader_exit if so_trader else b.sell)(p, 1.0, None, now, motivo)

    async def follow_tick(self, now: float) -> None:
        """Acompanha o trader copiado e o dev de cada token aberto pelo saldo na rede (pega também a venda que a leitura das
        trocas não viu, como a feita por outra rota). Trader com ≤5% do maior saldo visto saiu; dev com metade ou menos saiu."""
        tks = sorted(self.held())
        if not tks:
            return
        i = self._follow_i % len(tks)
        tks = (tks[i:] + tks[:i])[:FOLLOW_MAX]
        self._follow_i = i + len(tks)
        for tk in tks:
            pos = self._positions(tk)
            for who in sorted({p["wallet"] for _, p, _ in pos}):
                bal = await self._balance(tk, who)
                if bal is None:
                    continue
                for uid, p, real in [x for x in pos if x[1]["wallet"] == who]:
                    first = "trader_max" not in p
                    top = max(int(p.get("trader_max") or 0), bal)
                    p["trader_max"], p["trader_bal"] = str(top), str(bal)
                    (self.rbook(uid) if real else self.book(uid)).dirty_pos.add(p["id"])
                    if top > 0 and bal <= top * TRADER_OUT:
                        self._exit(uid, p, real, "sair_trader", "trader saiu da moeda", now)
                    elif first and bal == 0 and now - p["open_t"] >= OLD_POS_S:
                        self._exit(uid, p, real, "sair_trader", "trader saiu da moeda (saldo zero)", now)
            dev = await self._dev_of(tk, now)
            if not dev:
                continue
            bal = await self._balance(tk, dev)
            if bal is None:
                continue
            for uid, p, real in self._positions(tk):
                top = max(int(p.get("dev_max") or 0), bal)
                p["dev"], p["dev_max"], p["dev_bal"] = dev, str(top), str(bal)
                if top > 0 and bal <= top * DEV_OUT:
                    caiu = 100 * (1 - bal / top)
                    self._exit(uid, p, real, "sair_dev", f"dev vendeu {caiu:.0f}% da moeda" if bal else "dev saiu da moeda", now)

    # ------------------------------------------------------------------ chave, liga/desliga, valores
    async def set_key(self, uid: str, value: str) -> str:
        key = evm.parse_key(value)
        await self.vault.save(uid, HOOD_KEY_NAME, value.strip())
        self._keys.pop(uid, None)
        _, addr = await self.get_key(uid)
        return addr or evm.address_of(key)

    async def remove_key(self, uid: str) -> None:
        self.rcfg(uid)["real_on"] = False
        await self.vault.delete(uid, HOOD_KEY_NAME)
        self._keys.pop(uid, None)
        rb = self.real.get(uid)
        if rb:
            rb.address, rb.balance = None, None
        self.book(uid).dirty_book = True
        await self.flush()

    async def set_real(self, uid: str, on: bool) -> dict:
        rc = self.rcfg(uid)
        if on:
            if not self.real_allowed:
                raise ValueError("a trava geral do servidor está fechada (PUMP_REAL_ALLOWED=false): nada é enviado")
            key, _ = await self.get_key(uid)
            if not key:
                raise ValueError("cole antes a chave privada da carteira da Robinhood em Carteira")
            rc["real_on"], rc["on_since"] = True, time.time()
        else:
            rc["real_on"] = False
        self.book(uid).dirty_book = True
        await self.flush()
        return self.real_status(uid)

    async def save_real_cfg(self, uid: str, raw: dict) -> dict:
        rc = self.rcfg(uid)
        keep = {k: rc[k] for k in ("real_on", "on_since") if k in rc}
        self.real_cfg[uid] = {**hoodreal.clean(raw, rc), **keep}
        self.book(uid).dirty_book = True
        await self.flush()
        return self.real_cfg[uid]

    async def save_book_cfg(self, uid: str, raw: dict) -> dict:
        b = self.book(uid)
        old = b.cfg["saldo_inicial"]
        b.cfg = clean_cfg(raw, b.cfg)
        b.cash += b.cfg["saldo_inicial"] - old             # mudar o saldo inicial soma/tira a diferença do saldo
        b.dirty_book = True
        await self.flush()
        return b.cfg

    async def block_token(self, uid: str, token: str, on: bool) -> list:
        """0.32.303 (pedido do dono): moeda bloqueada nunca é comprada nesta conta (cópia nem botão Comprar)."""
        b = self.book(uid)
        tk = (token or "").strip().lower()
        bl = [x for x in (b.cfg.get("tokens_bloqueados") or []) if x != tk]
        if on:
            if len(bl) >= BLOCK_MAX:
                raise ValueError(f"no máximo {BLOCK_MAX} moedas bloqueadas")
            bl.append(tk)
        b.cfg = clean_cfg({"tokens_bloqueados": bl}, b.cfg)
        if on and tk not in b.cfg["tokens_bloqueados"]:
            raise ValueError("moeda inválida")
        b.dirty_book = True
        await self.flush()
        return b.cfg["tokens_bloqueados"]

    async def token_key(self, token: str) -> list | None:
        """Chave do pool V4 pago em ETH de um token, a partir das trocas vistas (a mais recente primeiro)."""
        tk = token.lower()
        tried = set()
        for t in reversed(self.w.trades):
            if t["token"] != tk or t.get("quote") != "ETH" or t.get("pool") in tried:
                continue
            tried.add(t.get("pool"))
            k = await self.pool_key(t.get("pool") or "", tk)
            if k:
                return k
            if len(tried) >= 3:
                break
        return None

    async def check_token(self, token: str) -> dict:
        """Conferência de golpe de uma moeda, sem esperar a cópia (Dinheiro entrando e botão Comprar)."""
        tk = token.lower()
        v = self.safe.cached(tk)
        if v is not None:
            return v
        key = await self.token_key(tk)
        if not key:
            return self.safe.mark(tk, False, "sem pool da Uniswap V4 pago em ETH: a cópia não consegue comprar esta moeda", sem_pool=True)
        trader = next((t["wallet"] for t in reversed(self.w.trades) if t["token"] == tk and t["side"] == "buy"), None)
        amt = next((t["amount"] for t in reversed(self.w.trades) if t["token"] == tk and t["side"] == "buy"), 0)
        return await self.safe.check(tk, key, trader, int(amt * 1e18), pool_fee(key))

    async def buy_token(self, uid: str, token: str, modo: str) -> dict:
        """0.32.303 (pedido do dono: "um botão de começar a copiar a moeda e já entramos no trade"): compra a moeda agora, na FICTÍCIA,
        na REAL ou nas 2, com o valor por compra de cada carteira. Só com a conferência de golpe aprovada; sai pelas regras da carteira
        (stop, stop móvel, tempo máximo), porque não há trader para seguir a venda."""
        tk = (token or "").strip().lower()
        if modo not in MODOS:
            raise ValueError("modo inválido")
        b = self.book(uid)
        if tk in (b.cfg.get("tokens_bloqueados") or []):
            raise ValueError("moeda bloqueada por você: desbloqueie em Honeypot e bloqueadas")
        v = await self.check_token(tk)
        if not v.get("ok"):
            raise ValueError("a conferência de golpe barrou esta moeda: " + (v.get("why") or "sem conferência"))
        key = await self.token_key(tk)
        if not key:
            raise ValueError("não achei o pool desta moeda em ETH")
        now = time.time()
        px = (self.w.px.get(tk) or (None, 0))[0]
        if not px:
            w = evm.words(await self._call(hoodsafe.QUOTER, v4_quote_data(key, 10 ** 15, True)))
            px = 1e15 / w[0] if w and w[0] else None
        if not px:
            raise ValueError("sem preço desta moeda agora")
        tr = {"wallet": "botao", "token": tk, "t": now, "tx": None, "eth": None, "amount": 0, "_auto": False}
        out = {"ficticia": None, "real": None}
        sp = None
        if modo in ("sim", "ambas"):                 # 0.32.308: a FICTÍCIA primeiro; a REAL fica presa a ela (espelho)
            sp = b.buy(tr, px, now, key, "botao")
            out["ficticia"] = "comprou" if sp else (b.events[0]["motivo"] if b.events else "não comprou")
        if modo in ("real", "ambas"):
            rc = self.rcfg(uid)
            if not rc.get("real_on"):
                out["real"] = "a carteira REAL está desligada (ligue em Carteira)"
            else:
                self._spawn(self._real_buy(uid, {**tr, "_sim_id": sp["id"]} if sp and rc.get("real_espelho") else tr, px, key))
                out["real"] = "enviando a compra REAL"
        await self.flush()
        return out

    async def block(self, uid: str, wallet: str, on: bool) -> list:
        """Bloqueia (para de copiar e nunca mais copia nesta conta) ou desbloqueia um trader. 0.32.302, pedido do dono."""
        b = self.book(uid)
        w = (wallet or "").strip().lower()
        bl = [x for x in (b.cfg.get("bloqueados") or []) if x != w]
        if on:
            if len(bl) >= BLOCK_MAX:
                raise ValueError(f"no máximo {BLOCK_MAX} traders bloqueados")
            bl.append(w)
            b.cfg = clean_cfg({"manual": [x for x in (b.cfg.get("manual") or []) if x != w]}, b.cfg)
        b.cfg = clean_cfg({"bloqueados": bl}, b.cfg)
        if on and w not in b.cfg["bloqueados"]:
            raise ValueError("carteira inválida")
        b.dirty_book = True
        await self.flush()
        return b.cfg["bloqueados"]

    async def follow(self, uid: str, wallet: str, on: bool, modo: str = "ambas") -> list:
        """Liga (no modo sim, real ou ambas) ou desliga a cópia de um trader nesta conta (botões do ranking)."""
        b = self.book(uid)
        cur = list(b.cfg.get("manual") or [])
        modos = dict(b.cfg.get("modo") or {})
        w = (wallet or "").strip().lower()
        if on and modo not in MODOS:
            raise ValueError("modo inválido")
        if on and w in (b.cfg.get("bloqueados") or []):
            raise ValueError("este trader está bloqueado: desbloqueie em Top traders → Bloqueados para copiar")
        perigo = self.w.danger_reason(w) if on and hasattr(self.w, "danger_reason") else None
        if perigo:                                  # 0.32.295 (pedido do dono): botão travado também no servidor
            raise ValueError("trader marcado PERIGO, não dá para copiar: " + perigo)
        if on and w not in cur:
            if len(cur) >= MANUAL_MAX:
                raise ValueError(f"no máximo {MANUAL_MAX} traders copiados à mão")
            cur.append(w)
        elif not on:
            cur = [x for x in cur if x != w]
        if on:
            modos[w] = modo
        b.cfg = clean_cfg({"manual": cur}, b.cfg)
        b.cfg = clean_cfg({"modo": modos}, b.cfg)
        if on and w not in b.cfg["manual"]:
            raise ValueError("carteira inválida")
        b.dirty_book = True
        await self.flush()
        return b.cfg["manual"]

    def user_summary(self, uid: str, now: float | None = None) -> dict:
        """0.32.294 (pedido do dono): uma linha por conta em Administração. Não cria carteira para quem nunca abriu o /hood."""
        now = now or time.time()
        b, rb, rc = self.books.get(uid), self.real.get(uid), self.real_cfg.get(uid) or {}
        f = None
        if b is not None:
            w = b.wallet(now)
            f = {"ligada": bool(b.cfg.get("on")), "resultado": w["resultado"], "abertas": w["abertas"], "fechadas": w["fechadas"],
                 "acerto": w["acerto"], "taxas": w["taxas"], "traders": len(b.cfg.get("manual") or [])}
        k = self._keys.get(uid)
        r = {"ligada": bool(rc.get("real_on")), "chave": bool(k and k[0]) or bool(rb and rb.address),
             "endereco": (k[1] if k else None) or (rb.address if rb else None), "abertas": len(rb.pos) if rb else 0,
             "fechadas": len(rb.trades) if rb else 0, "resultado": round(sum(x["pnl_eth"] for x in rb.trades), 6) if rb else 0.0,
             "saldo": rb.balance if rb else None}
        return {"ficticia": f, "real": r}

    async def reset_sim(self, uid: str) -> dict:
        """0.32.298 (pedido do dono: "botão na carteira fictícia para zerar e começar do zero, limpando o histórico"): apaga as
        posições abertas, os trades fechados e os eventos SÓ da FICTÍCIA desta conta e volta o saldo para o saldo inicial.
        Valores da cópia, traders seguidos e tudo da REAL ficam como estão."""
        b = self.book(uid)
        n_pos, n_tr = len(b.pos), len(b.trades)
        rb = self.real.get(uid)
        for rp in (rb.pos.values() if rb else []):  # a REAL não é vendida: as posições presas à fictícia se soltam
            if rp.pop("sim_id", None):
                rp["solta"] = "fictícia zerada"
                rb.dirty_pos.add(rp["id"])
        b.closed_pos |= set(b.pos)
        b.pos.clear()
        b.trades.clear()
        b.new_trades.clear()
        b.dirty_pos.clear()
        b.events.clear()
        b.cash = b.cfg["saldo_inicial"]
        b.dirty_book = True
        b.ev(time.time(), "", "", "zerou", f"carteira fictícia zerada: {n_pos} abertas e {n_tr} fechadas apagadas")
        if self.db is not None and hasattr(self.db, "_req"):
            try:                                   # trade da fictícia não tem "real" no data; o da REAL tem real=true
                await self.db._req("DELETE", "botlive_trades", {"user_id": f"eq.{uid}", "data->>real": "is.null"}, None, "return=minimal")
            except Exception as e:
                log.warning("Robinhood: histórico fictício não foi apagado no banco: %s", str(e)[:160])
        await self.flush()
        return {"abertas": n_pos, "fechadas": n_tr, "saldo": b.cash}

    def close_manual(self, uid: str, pid: str) -> dict | None:
        b = self.book(uid)
        p = b.pos.get(pid)
        return b.sell(p, 1.0, None, time.time(), "vendido por você") if p else None

    async def close_real(self, uid: str, pid: str) -> dict | None:
        p = self.rbook(uid).pos.get(pid)
        return await self._real_sell(uid, p, 1.0, "vendido por você", manual=True) if p else None

    async def close_all(self, uid: str, real: bool) -> dict:
        if not real:
            b = self.book(uid)
            out = [b.sell(p, 1.0, None, time.time(), "vendido por você (vender todas)") for p in list(b.pos.values())]
            await self.flush()
            return {"vendidas": len([x for x in out if x]), "falhas": 0}
        ok = bad = 0
        for p in list(self.rbook(uid).pos.values()):
            try:
                if await self._real_sell(uid, p, 1.0, "vendido por você (vender todas)", manual=True):
                    ok += 1
            except Exception:
                bad += 1
        return {"vendidas": ok, "falhas": bad}

    # ------------------------------------------------------------------ telas
    def mirror_report(self, uid: str, now: float) -> dict:
        """0.32.308 (pedido do dono: "verificação completa: a REAL tem que seguir 100% a fictícia"): cada posição aberta da FICTÍCIA
        com o par na REAL (ou o motivo de não ter), e as posições REAL que não estão presas a nenhuma da fictícia."""
        b, rb, rc = self.book(uid), self.rbook(uid), self.rcfg(uid)
        par = {p.get("sim_id"): p for p in rb.pos.values() if p.get("sim_id")}
        linhas = []
        for p in sorted(b.pos.values(), key=lambda x: x["open_t"], reverse=True):
            rp = par.get(p["id"])
            why = None
            if not rp:
                ev = next((e for e in rb.events if e.get("token") == p["token"] and e["t"] >= p["open_t"] - 5
                           and e.get("acao") in ("REAL não copiou", "REAL falhou")), None)
                why = (ev["acao"] + ": " + (ev.get("motivo") or "")) if ev else (
                    "a REAL estava desligada" if not rc.get("real_on") else "o espelho estava desligado" if not rc.get("real_espelho")
                    else "compra REAL ainda saindo" if any(t == p["token"] for _, t in rb.busy)
                    else "posição de antes do espelho (0.32.306) ou de trader copiado só na FICTÍCIA")
            linhas.append({"token": p["token"], "nome": p.get("nome"), "simbolo": p.get("simbolo"), "wallet": p["wallet"], "open_t": p["open_t"],
                           "real": bool(rp), "real_open_t": rp["open_t"] if rp else None, "motivo": why})
        soltas = [{"token": p["token"], "nome": p.get("nome"), "simbolo": p.get("simbolo"), "wallet": p["wallet"], "open_t": p["open_t"],
                   "motivo": p.get("solta") or "comprada antes do espelho ou fora da fictícia: segue as regras da REAL"}
                  for p in rb.pos.values() if not p.get("sim_id")]
        n = len(linhas)
        return {"ligado": bool(rc.get("real_espelho")), "ficticia": n, "com_real": sum(1 for x in linhas if x["real"]),
                "linhas": linhas, "soltas": soltas}

    def _names(self, evs: list[dict]) -> dict:
        """Nome e símbolo dos tokens citados nos eventos (as posições e os trades já levam o seu)."""
        return {e["token"]: self.meta[e["token"]] for e in evs if e.get("token") in self.meta}

    def painel(self, uid: str, now: float | None = None, real: bool = False) -> dict:
        now = now or time.time()
        b = self.book(uid)
        rc = self.rcfg(uid)
        base = {"cfg_sim": b.cfg, "padrao": CFG_DEFAULT, "real_cfg": rc, "real_padrao": hoodreal.REAL_DEFAULT,
                "real_status": self.real_status(uid), "seguranca": {**self.safe.summary(now), "copia": self.stat},
                "copiaria": self.w.ranking(now)["copiaria"], "explorer": EXPLORER,
                "eth_usd": getattr(self.w, "eth_usd", None)}
        if real:
            rb = self.rbook(uid)
            base["espelho"] = self.mirror_report(uid, now)
            pos = []
            for p in sorted(rb.pos.values(), key=lambda x: x["open_t"], reverse=True):
                v, pct = rb.pnl_now(p, rc["real_slip_pct"])
                pos.append({**{k: p.get(k) for k in ("id", "wallet", "token", "open_t", "px_in", "px_now", "px_t", "eth_in", "proceeds",
                                                      "best_pct", "worst_pct", "lag_s", "tx_in", "vendas", "sell_error", "selling",
                                                      "nome", "simbolo", "px_src", "dev", "espera", "sim_id", "solta")},
                            "pnl_eth": round(v, 6), "pnl_pct": round(pct, 2), "fecha_em": p["open_t"] + rc["real_max_hold_h"] * 3600, "real": True})
            return {**base, "real": True, "carteira": rb.wallet(now, rc["real_slip_pct"], periods), "posicoes": pos,
                    "trades": rb.trades[:500], "eventos": rb.events[:100], "nomes": self._names(rb.events[:100])}
        pos = []
        for p in sorted(b.pos.values(), key=lambda x: x["open_t"], reverse=True):
            v, pct = b.pnl_now(p)
            pos.append({**{k: p.get(k) for k in ("id", "wallet", "token", "open_t", "px_in", "px_now", "px_t", "eth_in", "proceeds",
                                                  "best_pct", "worst_pct", "lag_s", "tx_in", "vendas", "nome", "simbolo",
                                                  "px_src", "dev", "espera")},
                        "pnl_eth": round(v, 6), "pnl_pct": round(pct, 2), "fecha_em": p["open_t"] + b.cfg["max_hold_h"] * 3600})
        return {**base, "real": False, "carteira": b.wallet(now), "posicoes": pos, "trades": b.trades[:500], "eventos": b.events[:100],
                "nomes": self._names(b.events[:100])}

    # ------------------------------------------------------------------ banco (hood_books, hood_positions, hood_trades)
    async def flush(self) -> None:
        if self.db is None:
            for b in list(self.books.values()) + list(self.real.values()):
                b.dirty_pos.clear()
                b.closed_pos.clear()
                b.new_trades.clear()
                if hasattr(b, "dirty_book"):
                    b.dirty_book = False
            return
        for b in list(self.books.values()):
            try:
                if b.dirty_book:
                    await self.db.insert("botlive_books", {"user_id": b.user_id, "cfg": {**b.cfg, "real": self.rcfg(b.user_id), **self._book_extra(b.user_id)}, "cash": b.cash},
                                         upsert=True, on_conflict="user_id")
                    b.dirty_book = False
                if b.new_trades:
                    rows = [{"id": x["id"], "user_id": b.user_id, "t": x["close_t"], "data": x} for x in b.new_trades]
                    await self.db.insert("botlive_trades", rows, upsert=True, on_conflict="id")
                    b.new_trades.clear()
                for pid in list(b.closed_pos):
                    await self.db.delete("botlive_positions", {"id": pid, "user_id": b.user_id})
                    b.closed_pos.discard(pid)
                ids = set(b.dirty_pos)
                rows = [{"id": pid, "user_id": b.user_id, "data": b.pos[pid]} for pid in ids if pid in b.pos]
                if rows:
                    await self.db.insert("botlive_positions", rows, upsert=True, on_conflict="id")
                b.dirty_pos -= ids
            except Exception as e:
                log.warning("Robinhood: carteira fictícia não gravou: %s", str(e)[:160])
        for rb in list(self.real.values()):
            try:
                if rb.new_trades:
                    rows = [{"id": x["id"], "user_id": rb.user_id, "t": x["close_t"], "data": x} for x in rb.new_trades]
                    await self.db.insert("botlive_trades", rows, upsert=True, on_conflict="id")
                    rb.new_trades.clear()
                for pid in list(rb.closed_pos):
                    await self.db.delete("botlive_positions", {"id": pid, "user_id": rb.user_id})
                    rb.closed_pos.discard(pid)
                ids = set(rb.dirty_pos)
                rows = [{"id": pid, "user_id": rb.user_id, "data": {k: v for k, v in rb.pos[pid].items() if k != "selling"}}
                        for pid in ids if pid in rb.pos]
                if rows:
                    await self.db.insert("botlive_positions", rows, upsert=True, on_conflict="id")
                rb.dirty_pos -= ids
            except Exception as e:
                log.warning("Robinhood: carteira REAL não gravou: %s", str(e)[:160])

    async def load(self) -> None:
        if self.db is None:
            return
        for r in await self.db.select("botlive_books", None) or []:
            b = self.books[r["user_id"]] = Book(r["user_id"], r.get("cfg"), r.get("cash"))
            b.close_hook = self._sim_closed
            b.dirty_book = False
            self._book_loaded(r)
            rc = (r.get("cfg") or {}).get("real")
            if isinstance(rc, dict):
                self.real_cfg[r["user_id"]] = {**hoodreal.clean(rc, rc), **{k: rc[k] for k in ("real_on", "on_since") if k in rc}}
        for r in await self.db.select("botlive_positions", None) or []:
            d = r.get("data")
            if not isinstance(d, dict) or not r.get("user_id"):
                continue
            if repair(d):
                log.warning("Robinhood: posição %s com a taxa do pool errada, refeita", r["id"])
            if d.get("nome") or d.get("simbolo"):
                self.meta[d["token"]] = {"nome": d.get("nome") or "", "simbolo": d.get("simbolo") or ""}
            if d.get("real"):
                self.rbook(r["user_id"]).pos[r["id"]] = d
                if d.get("corrigido"):
                    self.real[r["user_id"]].dirty_pos.add(r["id"])
            elif r["user_id"] in self.books:
                self.books[r["user_id"]].pos[r["id"]] = d
                if d.get("corrigido"):
                    self.books[r["user_id"]].dirty_pos.add(r["id"])
        for r in await self.db.select("botlive_trades", None, order="t.desc", limit=20000) or []:
            d = r.get("data")
            if not isinstance(d, dict):
                continue
            b = self.rbook(r["user_id"]) if d.get("real") and r.get("user_id") else self.books.get(r.get("user_id"))
            if b is not None and len(b.trades) < KEEP_TRADES:
                b.trades.append(d)
