"""BNB · Four.Meme: segurança do token antes de comprar (0.32.177, pedido do dono em 04/11/2026).

"Não pegar token congelado, honeypot, nada que atrapalhe a venda depois da compra."

Duas conferências, nesta ordem, com o resultado guardado por token:
1. Na rede (vale para todo token ainda na curva): Helper3.tryBuy e trySell dizem quanto a Four.Meme cobra de taxa na compra e
   na venda. O normal é 1%. Taxa acima de MAX_FEE_PCT = modo anti-sniper (taxa alta nos primeiros blocos) ou token com
   taxa (Tax Mode da Four.Meme, até 10%): não compra. Se a rede não responde, não compra.
2. GoPlus (grátis, sem chave): honeypot, não deixa vender tudo, dono pode pausar transferências (congelar), lista negra,
   espera entre trades, dono pode mudar saldo ou taxa, taxa diferente por carteira, dono escondido, taxa de compra/venda
   acima do limite. Token na curva sem dados da GoPlus ainda (token de segundos) passa só com a conferência 1, porque os
   tokens da curva são do modelo da própria Four.Meme. Token que já foi para a PancakeSwap SEM dados da GoPlus não compra.

Vale para a FICTÍCIA e para a REAL (a fictícia tem que mostrar o que a real conseguiria). Nunca vende nada sozinho.
"""
from __future__ import annotations

import time
from collections import deque

GOPLUS = "https://api.gopluslabs.io/api/v1/token_security/56?contract_addresses="
MAX_FEE_PCT = 3.0            # taxa da Four.Meme na compra/venda (normal: 1%)
MAX_TAX_PCT = 3.0            # taxa do próprio token (GoPlus buy_tax/sell_tax)
TEST_BNB = 0.05              # valor usado na simulação (não envia nada)
OK_S = 600                   # token aprovado: confere de novo depois de 10 min
BAD_S = 6 * 3600             # token barrado: fica barrado 6 h
ERR_S = 60                   # falha da conferência: tenta de novo em 1 min
GP_PER_MIN = 20              # limite próprio de consultas à GoPlus

# campo da GoPlus → por que não compra ("1" = verdadeiro)
FLAGS = {
    "is_honeypot": "honeypot: não deixa vender",
    "cannot_sell_all": "não deixa vender tudo",
    "cannot_buy": "não deixa comprar",
    "transfer_pausable": "o dono pode pausar as transferências (congelar o token)",
    "is_blacklisted": "tem lista negra: o dono pode bloquear carteiras",
    "trading_cooldown": "espera obrigatória entre compra e venda",
    "owner_change_balance": "o dono pode mudar o saldo das carteiras",
    "slippage_modifiable": "o dono pode mudar a taxa de venda",
    "personal_slippage_modifiable": "taxa diferente para cada carteira",
    "hidden_owner": "dono escondido",
    "selfdestruct": "o contrato pode se autodestruir",
    "honeypot_with_same_creator": "o mesmo criador já fez honeypot",
}


def _f(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _br(v: float) -> str:
    return f"{v:.1f}".replace(".", ",")


def judge_goplus(d: dict | None, max_tax: float = MAX_TAX_PCT) -> list[str]:
    """Motivos para NÃO comprar, a partir da resposta da GoPlus para um token (vazio = nada contra)."""
    if not d:
        return []
    why = [txt for k, txt in FLAGS.items() if str(d.get(k, "")).strip() == "1"]
    for k, nome in (("buy_tax", "compra"), ("sell_tax", "venda")):
        v = _f(d.get(k))
        if v is not None and v * 100 > max_tax:
            why.append(f"taxa de {nome} do token {v * 100:.0f}% (máx. {max_tax:g}%)")
    return why


def curve_fees(w_buy: list[int], funds: int, w_sell: list[int] | None) -> tuple[float | None, float | None]:
    """Taxa % na compra (tryBuy: [gerenciador, moeda, quantidade, custo, taxa, …]) e na venda (trySell: [gerenciador,
    moeda, valor, taxa])."""
    buy = 100.0 * w_buy[4] / funds if len(w_buy) >= 5 and funds else None
    sell = 100.0 * w_sell[3] / w_sell[2] if w_sell and len(w_sell) >= 4 and w_sell[2] else None
    return buy, sell


class Safety:
    """Guarda o veredito por token. call(to, data) = eth_call; get(url) = GET JSON (httpx)."""

    def __init__(self, call, http):
        self.call, self.http = call, http
        self.cache: dict[str, dict] = {}
        self.barred: deque = deque(maxlen=200)
        self._gp_t: deque = deque()
        self.stat = {"conferidos": 0, "barrados": 0, "goplus": 0, "goplus_sem_dados": 0, "erros": 0}

    def cached(self, token: str, now: float | None = None) -> dict | None:
        v = self.cache.get(token)
        if not v:
            return None
        now = now or time.time()
        ttl = OK_S if v["ok"] else (ERR_S if v.get("erro") else BAD_S)
        return v if now - v["t"] < ttl else None

    def mark(self, token: str, ok: bool, why: str = "", **info) -> dict:
        v = {"token": token, "ok": ok, "why": why, "t": time.time(), **info}
        self.cache[token] = v
        if not ok and not info.get("erro"):
            self.stat["barrados"] += 1
            self.barred.appendleft(v)
        return v

    def _gp_allowed(self, now: float) -> bool:
        while self._gp_t and now - self._gp_t[0] > 60:
            self._gp_t.popleft()
        if len(self._gp_t) >= GP_PER_MIN:
            return False
        self._gp_t.append(now)
        return True

    async def goplus(self, token: str) -> dict | None:
        """Dados da GoPlus do token, {} se ela ainda não conhece o token, None se não deu para consultar."""
        if not self._gp_allowed(time.time()):
            return None
        try:
            r = await self.http.get(GOPLUS + token, timeout=8)
            js = r.json()
        except Exception:
            return None
        self.stat["goplus"] += 1
        res = (js or {}).get("result") or {}
        d = res.get(token) or res.get(token.lower()) or {}
        if not d:
            self.stat["goplus_sem_dados"] += 1
        return d

    async def check(self, token: str, graduated: bool, quote_stable: bool, bnb_usd: float | None,
                    try_buy, try_sell) -> dict:
        """Confere o token. try_buy(token, funds) e try_sell(token, amount) devolvem as palavras do eth_call."""
        hit = self.cached(token)
        if hit:
            return hit
        self.stat["conferidos"] += 1
        info: dict = {"graduou": graduated}
        if not graduated:
            try:
                funds = int(TEST_BNB * 1e18 * (bnb_usd if quote_stable else 1.0)) if (bnb_usd or not quote_stable) else 0
                if not funds:
                    return self.mark(token, False, "sem a cotação BNB/dólar para conferir a taxa", erro=True)
                wb = await try_buy(token, funds)
                ws = await try_sell(token, wb[2]) if len(wb) >= 3 and wb[2] else None
                fb, fs = curve_fees(wb, funds, ws)
            except Exception as e:
                self.stat["erros"] += 1
                return self.mark(token, False, "não deu para simular compra e venda na rede (" + type(e).__name__ + ")", erro=True)
            info.update(taxa_compra=None if fb is None else round(fb, 2), taxa_venda=None if fs is None else round(fs, 2))
            if fb is None or fs is None:
                return self.mark(token, False, "a simulação não devolveu a taxa da compra ou da venda", **info)
            if fb > MAX_FEE_PCT or fs > MAX_FEE_PCT:
                return self.mark(token, False, f"taxa da Four.Meme {_br(fb)}% na compra / {_br(fs)}% na venda "
                                 f"(normal 1%, máx. {MAX_FEE_PCT:g}%): modo anti-sniper ou token com taxa", **info)
        gp = await self.goplus(token)
        info["goplus"] = "sem consulta" if gp is None else ("sem dados" if not gp else "ok")
        if gp is None and graduated:
            return self.mark(token, False, "não deu para consultar a GoPlus agora", erro=True, **info)
        if gp == {} and graduated:
            return self.mark(token, False, "token na PancakeSwap sem dados de segurança da GoPlus", **info)
        why = judge_goplus(gp)
        if why:
            return self.mark(token, False, " · ".join(why), **info)
        return self.mark(token, True, "", **info)

    def summary(self, now: float | None = None) -> dict:
        now = now or time.time()
        return {"regras": {"max_taxa_curva_pct": MAX_FEE_PCT, "max_taxa_token_pct": MAX_TAX_PCT, "barrado_h": BAD_S / 3600},
                "stat": dict(self.stat),
                "barrados": [{"token": v["token"], "t": v["t"], "why": v["why"], "taxa_compra": v.get("taxa_compra"),
                              "taxa_venda": v.get("taxa_venda"), "goplus": v.get("goplus")}
                             for v in list(self.barred)[:50] if now - v["t"] < 86400]}
