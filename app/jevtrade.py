"""Jev Trade (0.32.87, áudio do Bruxo de 30/10): o Jev faz o trade inteiro, só em SIMULAÇÃO.

Todo token novo vivo é conferido aos 5 min. Com 40+ detentores ele entra na observação: a cada minuto o robô lê detentores,
preço e volume e pergunta ao Jev se entra. Depois da entrada, o Jev escolhe o stop e, minuto a minuto, se segura, vende
parte ou sai. Ele só pode SUBIR o stop, nunca baixar: "tudo para garantir o lucro".

Regra fixa do Bruxo que vale mesmo sem o Jev pedir: detentores caíram 30% do pico = sai tudo.
Sem resposta do Jev a posição fica no último stop e fecha em 60 min. Para medir se o Jev ajuda, as mesmas entradas rodam
também numa régua fixa (stop de 30%, saída aos 25 min), e a mesma régua roda em todo token com 40+ detentores.

Nada aqui passa pelo motor dos usuários: não abre posição, não mexe em carteira e não existe caminho para a execução real.
"""
from __future__ import annotations

import time

from .auto_trades import SUSPECT_PCT
from .jev import FEE_PCT, JEV_MODEL, JEV_URL, TIMEOUT_S

MIN_HOLDERS = 40
SCAN_MIN_AGE_MIN, SCAN_MAX_AGE_MIN = 5.0, 8.0     # "a partir dos cinco minutos"
ALIVE_GAIN = 1.05         # abaixo disso o token não negociou desde a criação: não gasta leitura de detentores
SCAN_HOUR = 60            # conferências de token novo por hora
READS_DAY = 2500          # leituras de detentores por dia (Helius: 10 créditos cada = cerca de 750 mil por mês)
SCAN_SHARE, WATCH_SHARE = 0.7, 0.9                # acima dessa fatia das leituras do dia, para de conferir / de observar
JEV_DAY = 6000            # perguntas por dia (separadas das 3.000 da aba JEV)
READ_S = 60
MAX_WATCH, MAX_OPEN = 15, 10
WATCH_MAX_MIN = 7         # 0.32.91 (Bruxo, 30/10): entra no máximo 7 min depois da 1ª análise; senão a observação acaba
MAX_HOLD_MIN = 60
HOLD_DROP_PCT = 30.0      # queda de detentores desde o pico que tira da moeda
SOL = 0.1
BASE_STOP, BASE_EXIT_MIN = 30.0, 25
HIST_MAX = 120

# 0.32.91 — estratégia do Bruxo (áudio/chat de 30/10 20:17): token com 40+ detentores vai para a lista e é lido a cada
# minuto; se os detentores sobem 20%+ em até 2 min E o preço também sobe, entra (no máximo 7 min depois da 1ª análise).
# O Jev continua opinando (fica registrado e escolhe o stop), mas não pode mais descartar o token antes da regra.
# Saída "antes do dump": stop inicial, metade vendida em +100%, stop no empate depois de +50%, stop móvel de 25% do pico
# depois de +30% e saída total quando os detentores começam a sair (15% abaixo do pico depois da entrada).
STRAT = {"cresc_pct": 20.0, "janela_min": 2.0, "prazo_min": WATCH_MAX_MIN, "stop_pct": 25.0, "empate_apos": 50.0,
         "parcial_em": 100.0, "parcial_frac": 0.5, "trail_apos": 30.0, "trail_pct": 25.0, "saida_detentores_pct": 15.0}
KEEP_S = 7 * 86400

STOPS_IN = {"perda_15": -15.0, "perda_20": -20.0, "perda_30": -30.0, "perda_40": -40.0, "perda_50": -50.0}
STOPS_OUT = {"empate": 0.0, "lucro_20": 20.0, "lucro_50": 50.0, "lucro_100": 100.0}
SELLS = {"vender_25": 0.25, "vender_50": 0.5, "vender_tudo": 1.0}

Q_IN = {
    "acao": {
        "type": "choice",
        "instructions": (
            "`token` is a pump.fun memecoin (Solana) at least 5 minutes old with 40+ holders. `holders` and `market` show its "
            "evolution minute by minute. Tokens with real demand keep gaining holders; when holders stall the token usually "
            "dies. Most such tokens collapse within 25 minutes. You run a simulated trade and decide alone. "
            "Should we BUY right now?"),
        "criteria": {"entrar": "Buy now: holders and price keep rising with real demand.",
                     "esperar": "Not yet: look again in one minute.",
                     "desistir": "Forget this token: holders stalled or falling, or it looks like a trap."},
    },
    "stop": {
        "type": "choice",
        "instructions": "If we buy, which stop loss from the entry price gives this token room without losing too much?",
        "criteria": {"perda_15": "Sell at -15%.", "perda_20": "Sell at -20%.", "perda_30": "Sell at -30%.",
                     "perda_40": "Sell at -40%.", "perda_50": "Sell at -50%."},
    },
    "qualidade": {
        "type": "score",
        "instructions": "How good is this entry, using only the data given?",
        "criteria": ["Terrible: almost sure to dump", "Weak", "Average", "Good", "Excellent: strong demand and healthy holders"],
    },
    "armadilha": {
        "type": "noul",
        "instructions": "Is this token likely a trap (bundle, insiders, serial launcher, wash trading)?",
        "criteria": {"true": "Likely a trap", "false": "No clear sign of a trap"},
    },
}

Q_OUT = {
    "acao": {
        "type": "choice",
        "instructions": (
            "We hold a simulated position in this pump.fun token. `position` has the current result, the peak and the stop; "
            "`holders` and `market` show the evolution minute by minute. Falling holders mean people are leaving: sell before "
            "them. Partial sales lock profit and keep upside. What do we do with the position right now?"),
        "criteria": {"segurar": "Keep the whole position: holders and demand still healthy.",
                     "vender_25": "Sell 25% of what is left to lock some profit.",
                     "vender_50": "Sell 50% of what is left to lock profit.",
                     "vender_tudo": "Sell everything now: demand is gone or the risk is too high."},
    },
    "stop": {
        "type": "choice",
        "instructions": "Should the stop be raised to protect the result? It can only go up, never down.",
        "criteria": {"manter": "Keep the stop where it is.", "empate": "Raise the stop to the entry price.",
                     "lucro_20": "Raise the stop to +20%.", "lucro_50": "Raise the stop to +50%.",
                     "lucro_100": "Raise the stop to +100%."},
    },
}


def parse_answers(js: dict) -> dict:
    a = (js or {}).get("answers") or {}
    ac, st = a.get("acao") or {}, a.get("stop") or {}
    u = (js or {}).get("usage") or {}
    return {"acao": ac.get("choice"), "stop": st.get("choice"), "conf": ac.get("confidence"),
            "qualidade": (a.get("qualidade") or {}).get("score"), "armadilha": (a.get("armadilha") or {}).get("noul"),
            "tokens_in": int(u.get("input_tokens") or 0)}


async def ask(http, key: str, state: dict, questions: dict, url: str = JEV_URL, model: str = JEV_MODEL) -> dict:
    t0 = time.monotonic()
    r = await http.post(url, json={"state": state, "model": model, "questions": questions}, timeout=TIMEOUT_S,
                        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    ms = round((time.monotonic() - t0) * 1000)
    if r.status_code != 200:
        txt = r.text[:120].replace(key, "***") if key else r.text[:120]
        raise RuntimeError(f"HTTP {r.status_code}: {txt}")
    return parse_answers(r.json()) | {"ms": ms}


def pct_of(it: dict, px: float) -> float:
    return (px / it["entrada"]["px"] - 1) * 100


def state_for(it: dict, tk: dict, now: float) -> dict:
    """Só números já medidos até agora; nada do futuro, de chave ou de carteira nossa."""
    H = [x for x in it["hist"] if x.get("h") is not None]
    M = [x for x in it["hist"] if x.get("mc") is not None]
    h, mc = [x["h"] for x in H], [x["mc"] for x in M]
    v = tk.get("vol") or {}
    c = it.get("criador") or {}
    st = {"token": {"symbol": it.get("symbol"), "age_min": round((now - it["created_t"]) / 60, 1), "graduated": tk.get("pool") in ("pumpswap", "pump-amm")},
          "holders": {"now": h[-1] if h else None, "one_min_ago": h[-2] if len(h) > 1 else None, "at_first_read": h[0] if h else None,
                      "peak": max(h) if h else None, "by_minute": h[-8:]},
          "market": {"market_cap_sol": mc[-1] if mc else None, "market_cap_at_launch_sol": it.get("mcap0"), "market_cap_by_minute": mc[-8:],
                     "volume_5m_usd": v.get("m5"), "buys_5m": v.get("buys_m5"), "sells_5m": v.get("sells_m5")},
          "risk": {"top10_pct": tk.get("top10_pct"), "creator_buy_sol": it.get("dev_buy"), "creator_tokens": c.get("tokens"),
                   "creator_rugs": c.get("rugs"), "creator_sold": bool(tk.get("dev_sold_t"))}}
    if it["estado"] == "aberta":
        e = it["entrada"]
        px = tk.get("price")
        st["position"] = {"result_pct": round(pct_of(it, px), 1) if px else None, "peak_pct": it.get("peak"), "stop_pct": it.get("stop"),
                          "held_min": round((now - e["t"]) / 60, 1), "left_pct": round(it["left"] * 100),
                          "holders_at_entry": e.get("h")}
    return st


def _base_new(px: float, t: float) -> dict:
    return {"px": px, "t": t, "res": None}


def _base_step(b: dict | None, px: float, now: float) -> None:
    """Régua fixa: stop de 30% e saída aos 25 min, no preço visto (o stop pode passar do limite entre duas leituras)."""
    if not b or b["res"] is not None:
        return
    p = (px / b["px"] - 1) * 100
    if p <= -BASE_STOP or now - b["t"] >= BASE_EXIT_MIN * 60:
        b["res"] = round(p - FEE_PCT, 2)


class JevTrade:
    def __init__(self):
        self.items: dict[str, dict] = {}
        self.dirty: set[str] = set()
        self.stats: dict = {}
        self.hour = (0, 0)
        self.ignorados: list[dict] = []
        self.rpc_off_until = 0.0
        self.on_event = None      # 0.32.93: o hub manda cada entrada e venda para a carteira fictícia de quem ligou

    # ------------------------------------------------------------------ orçamento do dia
    def day(self, now: float) -> dict:
        d = time.strftime("%Y-%m-%d", time.gmtime(now))
        if self.stats.get("dia") != d:
            self.stats = {"dia": d, "calls": 0, "erros": 0, "ms": 0, "tokens_in": 0, "ultimo_erro": None, "leituras": 0, "conferidos": 0,
                          "parados": 0, "abaixo": 0, "com_40": 0, "sem_leitura": 0}
        return self.stats

    def can_scan(self, now: float) -> bool:
        h = int(now // 3600)
        used = self.hour[1] if self.hour[0] == h else 0
        return now >= self.rpc_off_until and used < SCAN_HOUR and self.day(now)["leituras"] < READS_DAY * SCAN_SHARE

    def note_scan(self, now: float) -> None:
        h = int(now // 3600)
        self.hour = (h, self.hour[1] + 1 if self.hour[0] == h else 1)
        d = self.day(now)
        d["conferidos"] += 1
        d["leituras"] += 1

    def jev_left(self, now: float) -> int:
        return JEV_DAY - self.day(now)["calls"]

    # ------------------------------------------------------------------ escolha dos tokens
    def candidates(self, live: dict, blacklist, now: float) -> list[dict]:
        """Tokens vivos da Base entre 5 e 8 min que ainda não foram conferidos; os que mais subiram primeiro."""
        out = []
        for mint, r in list(live.items()):
            age = (now - float(r.get("t0") or now)) / 60
            mc, m0 = (r.get("snaps") or {}).get("5"), r.get("mcap0")
            if mint in self.items or r.get("_jt") or not (SCAN_MIN_AGE_MIN <= age <= SCAN_MAX_AGE_MIN) or not mc or not m0:
                continue
            if mc >= 300 or (r.get("creator") and r["creator"] in (blacklist or {})):
                continue                       # curva quase cheia em 5 min = bundle (mesma regra da Base)
            if mc < m0 * ALIVE_GAIN:
                r["_jt"] = True
                self.day(now)["parados"] += 1
                continue
            out.append(r)
        return sorted(out, key=lambda r: -(r["snaps"]["5"] / r["mcap0"]))

    def on_checked(self, r: dict, h: int | None, now: float, cstats: dict | None = None) -> dict | None:
        """Resultado da 1ª contagem: 40+ detentores abre a observação."""
        r["_jt"] = True
        d = self.day(now)
        mint = r["mint"]
        if h is None:
            d["sem_leitura"] += 1
            self.rpc_off_until = now + 300     # RPC público não conta detentores: não insiste a cada volta
            return None
        if h < MIN_HOLDERS:
            d["abaixo"] += 1
            self.ignorados = ([{"t": now, "mint": mint, "symbol": r.get("symbol"), "h": h}] + self.ignorados)[:30]
            return None
        if len(self.watching()) >= MAX_WATCH:
            return None
        d["com_40"] += 1
        it = {"id": mint, "mint": mint, "symbol": r.get("symbol"), "creator": r.get("creator"), "t": now, "created_t": float(r["t0"]),
              "em": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(now)), "estado": "olhando", "mcap0": r.get("mcap0"),
              "dev_buy": r.get("dev_buy"), "criador": {k: (cstats or {}).get(k) for k in ("tokens", "rugs", "x2", "bundles")},
              "hist": [], "decisoes": [], "left": 1.0, "realizado": 0.0, "vendas": [], "h_peak": h, "last_read": 0.0}
        self.items[mint] = it
        self.dirty.add(mint)
        return it

    def watching(self) -> list[dict]:
        return [x for x in self.items.values() if x["estado"] == "olhando"]

    def open(self) -> list[dict]:
        return [x for x in self.items.values() if x["estado"] == "aberta"]

    def active(self) -> list[dict]:
        """Tudo que ainda precisa de preço, inclusive a régua fixa depois de o Jev já ter saído."""
        return [x for x in self.items.values() if x["estado"] in ("olhando", "aberta")
                or any(b and b["res"] is None for b in (x.get("base_todos"), x.get("base_igual")))]

    def read_due(self, now: float) -> list[dict]:
        L = sorted(self.watching() + self.open(), key=lambda x: x["estado"] != "aberta")
        return [x for x in L if now - x["last_read"] >= READ_S - 2]

    def add_read(self, it: dict, h: int | None, px: float | None, mc: float | None, now: float) -> None:
        it["hist"] = (it["hist"] + [{"m": round((now - it["created_t"]) / 60, 1), "h": h, "px": px, "mc": None if mc is None else round(mc, 2)}])[-HIST_MAX:]
        it["last_read"] = now
        if h is not None:
            it["h_peak"] = max(it["h_peak"], h)
        if px and "base_todos" not in it:
            it["base_todos"] = _base_new(px, now)
        self.dirty.add(it["id"])

    def holders_fell(self, it: dict) -> bool:
        h = next((x["h"] for x in reversed(it["hist"]) if x.get("h") is not None), None)
        return h is not None and h <= it["h_peak"] * (1 - HOLD_DROP_PCT / 100)

    # ------------------------------------------------------------------ 0.32.91: regra do Bruxo
    @staticmethod
    def rule_check(hist: list[dict], cfg: dict | None = None) -> dict:
        """Regra do Bruxo (0.32.93): nas leituras dos últimos ~2 min os detentores têm que SÓ SUBIR (cada leitura maior que a
        anterior: parado ou caindo não vale) e somar +20% ou mais; o preço só precisa estar POSITIVO no mesmo período (qualquer
        alta — confirmado pelo dono em 30/10 21:30: os 20% são só dos detentores). Devolve {ok, cresc, px_pct, motivo}."""
        S = cfg or STRAT
        H = [x for x in hist if x.get("h") is not None and x.get("px")]
        if len(H) < 2:
            return {"ok": False, "cresc": None, "px_pct": None, "subindo": None, "motivo": "esperando a 2ª leitura"}
        cur = H[-1]
        W = [x for x in H if cur["m"] - x["m"] <= S["janela_min"] + 0.3]
        if len(W) < 2:
            W = H[-2:]
        ref = W[0]
        subindo = all(b["h"] > a["h"] for a, b in zip(W, W[1:]))
        cresc = round((cur["h"] / ref["h"] - 1) * 100, 1) if ref["h"] else None
        pxp = round((cur["px"] / ref["px"] - 1) * 100, 1)
        ok = subindo and cresc is not None and cresc >= S["cresc_pct"] and pxp > 0
        seq = " → ".join(str(x["h"]) for x in W)
        why = (f"detentores {seq} ({cresc:+.0f}%{'' if subindo else ', parou ou caiu no meio'}) e preço {pxp:+.0f}% em {cur['m'] - ref['m']:.1f} min"
               if cresc is not None else "sem contagem")
        return {"ok": ok, "cresc": cresc, "px_pct": pxp, "subindo": subindo, "ref_m": ref["m"], "motivo": why}

    @staticmethod
    def market_positive(hist: list[dict], px: float | None) -> dict:
        """Fechamento dos 7 min (0.32.93): mercado positivo = preço acima da 1ª leitura E detentores acima da 1ª leitura."""
        H = [x for x in hist if x.get("h") is not None and x.get("px")]
        if not H or not px:
            return {"ok": False, "motivo": "sem leituras"}
        h_now = H[-1]["h"]
        pxp = round((px / H[0]["px"] - 1) * 100, 1)
        hp = round((h_now / H[0]["h"] - 1) * 100, 1) if H[0]["h"] else 0.0
        return {"ok": pxp > 0 and h_now > H[0]["h"], "px_pct": pxp, "h_pct": hp,
                "motivo": f"fechamento dos {WATCH_MAX_MIN} min: preço {pxp:+.0f}% e detentores {H[0]['h']} → {h_now} ({hp:+.0f}%) desde a 1ª leitura"}

    def _enter(self, it: dict, px: float, now: float, por: str, st: float, out: dict | None = None) -> str:
        if len(self.open()) >= MAX_OPEN:
            return "sem vaga"
        out = out or {}
        h = next((x["h"] for x in reversed(it["hist"]) if x.get("h") is not None), None)
        it["entrada"] = {"t": now, "px": px, "h": h, "m": round((now - it["created_t"]) / 60, 1), "stop": st, "por": por,
                         "jev": out.get("acao"), "qualidade": out.get("qualidade"), "armadilha": out.get("armadilha")}
        it.update(estado="aberta", stop=st, peak=0.0, base_igual=_base_new(px, now), last_read=now, h_peak_in=h or 0)
        self.dirty.add(it["id"])
        if self.on_event:
            try:
                self.on_event("abriu", it, px, now, 1.0, por)
            except Exception:
                pass
        return "entrar"

    def bruxo_entry(self, it: dict, out: dict | None, px: float | None, now: float) -> str:
        """Entrada pela regra do Bruxo. O Jev só opina (fica guardado e escolhe o stop); "desistir" não descarta mais."""
        out = out or {}
        rc = self.rule_check(it["hist"])
        it["regra"] = rc
        it["decisoes"] = (it["decisoes"] + [{"m": round((now - it["created_t"]) / 60, 1), "fase": "entrada", "regra": rc["ok"],
                                             **{k: out.get(k) for k in ("acao", "stop", "conf", "qualidade", "armadilha")}}])[-HIST_MAX:]
        self.dirty.add(it["id"])
        if not rc["ok"] or not px:
            return "esperando a regra"
        st = STOPS_IN.get(out.get("stop") or "", -STRAT["stop_pct"])
        it["jev_stop"] = st
        return self._enter(it, px, now, "regra do Bruxo: " + rc["motivo"], st, out)

    def guard_exit(self, it: dict, px: float, now: float) -> bool:
        """Saída antes do dump, só com o preço: parcial em +100%, empate depois de +50%, stop móvel depois de +30%."""
        S = STRAT
        pct = pct_of(it, px)
        if it["peak"] >= S["empate_apos"] and it["stop"] < 0:
            it["stop"] = 0.0
        if it["peak"] >= S["parcial_em"] and not it.get("parcial_feita") and it["left"] > 0.5:
            it["parcial_feita"] = True
            self.sell(it, S["parcial_frac"], px, now, f"vendeu metade em +{S['parcial_em']:g}% (garante o lucro)")
            if it["estado"] != "aberta":
                return True
        if it["peak"] >= S["trail_apos"] and (1 + pct / 100) <= (1 + it["peak"] / 100) * (1 - S["trail_pct"] / 100):
            self.sell(it, 1.0, px, now, f"caiu {S['trail_pct']:g}% do pico (+{it['peak']:g}%): saiu antes do dump")
            return True
        return False

    def holders_leaving(self, it: dict) -> bool:
        """Depois da entrada: detentores 15% abaixo do maior número visto desde a entrada = começaram a sair."""
        H = [x["h"] for x in it["hist"] if x.get("h") is not None and x["m"] >= (it.get("entrada") or {}).get("m", 0)]
        return len(H) >= 2 and H[-1] <= max(H) * (1 - STRAT["saida_detentores_pct"] / 100)

    def discard(self, it: dict, motivo: str, now: float) -> None:
        it["estado"], it["motivo"], it["fechou_t"] = "descartada", motivo, now
        self.dirty.add(it["id"])

    # ------------------------------------------------------------------ decisões do Jev
    def on_entry(self, it: dict, out: dict, px: float | None, now: float) -> str:
        it["decisoes"] = (it["decisoes"] + [{"m": round((now - it["created_t"]) / 60, 1), "fase": "entrada",
                                             **{k: out.get(k) for k in ("acao", "stop", "conf", "qualidade", "armadilha")}}])[-HIST_MAX:]
        self.dirty.add(it["id"])
        a = out.get("acao")
        if a == "desistir":
            self.discard(it, "o Jev desistiu", now)
        elif a == "entrar" and px:
            if len(self.open()) >= MAX_OPEN:
                return "sem vaga"
            st = STOPS_IN.get(out.get("stop") or "", -BASE_STOP)
            h = next((x["h"] for x in reversed(it["hist"]) if x.get("h") is not None), None)
            it["entrada"] = {"t": now, "px": px, "h": h, "m": round((now - it["created_t"]) / 60, 1), "stop": st,
                             "qualidade": out.get("qualidade"), "armadilha": out.get("armadilha")}
            it.update(estado="aberta", stop=st, peak=0.0, base_igual=_base_new(px, now), last_read=now)
        return a or "sem resposta"

    def on_exit(self, it: dict, out: dict, px: float | None, now: float) -> str:
        a, novo = out.get("acao"), STOPS_OUT.get(out.get("stop") or "")
        pct = pct_of(it, px) if px else None
        dec = {"m": round((now - it["created_t"]) / 60, 1), "fase": "saida", "acao": a, "stop": out.get("stop"), "conf": out.get("conf"), "pct": None if pct is None else round(pct, 1)}
        it["decisoes"] = (it["decisoes"] + [dec])[-HIST_MAX:]
        self.dirty.add(it["id"])
        if novo is not None and pct is not None and it["stop"] < novo < pct:      # só sobe, e nunca acima do preço de agora
            it["stop"] = novo
            dec["stop_novo"] = novo
        if a in SELLS and px:
            self.sell(it, SELLS[a], px, now, "o Jev mandou vender" + (" tudo" if SELLS[a] == 1.0 else " parte"))
        return a or "sem resposta"

    def sell(self, it: dict, frac_left: float, px: float, now: float, motivo: str) -> None:
        pct = pct_of(it, px)
        frac = it["left"] * frac_left
        it["realizado"] += frac * pct
        it["left"] = round(it["left"] - frac, 4)
        it["vendas"].append({"t": now, "frac": round(frac, 3), "pct": round(pct, 1), "motivo": motivo})
        if self.on_event:
            try:
                self.on_event("vendeu", it, px, now, frac_left, motivo)
            except Exception:
                pass
        if it["left"] < 0.02:
            it["left"] = 0.0
            self._close(it, motivo, now)
        self.dirty.add(it["id"])

    def _close(self, it: dict, motivo: str, now: float) -> None:
        it.update(estado="fechada", motivo=motivo, fechou_t=now, res=round(it["realizado"] - FEE_PCT, 2),
                  suspeito=(it.get("peak") or 0) >= SUSPECT_PCT)

    def on_price(self, it: dict, px: float | None, now: float) -> None:
        """A cada volta (20 s): régua fixa, stop e tempo. Depende só do preço; continua sem o Jev."""
        if px:
            _base_step(it.get("base_todos"), px, now)
            _base_step(it.get("base_igual"), px, now)
        if it["estado"] == "olhando" and now - it["t"] >= WATCH_MAX_MIN * 60:
            mp = self.market_positive(it["hist"], px)       # 0.32.93: no fechamento dos 7 min, mercado positivo = entra
            it["fechamento"] = mp
            if not (mp["ok"] and self._enter(it, px, now, mp["motivo"], it.get("jev_stop") or -STRAT["stop_pct"]) == "entrar"):
                self.discard(it, f"não entrou em {WATCH_MAX_MIN} min (" + ("mercado positivo, mas sem vaga" if mp["ok"] else "mercado não ficou positivo") + ")", now)
        elif it["estado"] == "aberta":
            if px:
                pct = pct_of(it, px)
                it["peak"] = max(it["peak"], round(pct, 1))
                if self.guard_exit(it, px, now):
                    pass
                elif pct <= it["stop"]:
                    self.sell(it, 1.0, px, now, f"stop de {it['stop']:+g}%")
                elif now - it["entrada"]["t"] >= MAX_HOLD_MIN * 60:
                    self.sell(it, 1.0, px, now, f"tempo máximo de {MAX_HOLD_MIN} min")
            elif now - it["entrada"]["t"] >= (MAX_HOLD_MIN + 10) * 60:
                it.update(estado="sem preço", motivo="ficou sem preço", fechou_t=now, res=None)
        if not px and now - it["t"] >= 2 * 3600:           # sem preço: a régua fixa não fecha nunca
            for k in ("base_todos", "base_igual"):
                if it.get(k) and it[k]["res"] is None:
                    it[k] = None
        self.dirty.add(it["id"])

    # ------------------------------------------------------------------ estudo e memória
    def study(self, hours: float, now: float) -> dict:
        since = now - hours * 3600 if hours else 0
        L = sorted((x for x in self.items.values() if x["t"] >= since), key=lambda x: x.get("fechou_t") or x["t"])
        F = [x for x in L if x["estado"] == "fechada" and not x.get("suspeito")]
        res = [x["res"] for x in F]
        win, lose = sum(r for r in res if r > 0), -sum(r for r in res if r < 0)
        igual = [x["base_igual"]["res"] for x in F if (x.get("base_igual") or {}).get("res") is not None]
        comp = [x["res"] for x in F if (x.get("base_igual") or {}).get("res") is not None]
        todos = [x["base_todos"]["res"] for x in L if (x.get("base_todos") or {}).get("res") is not None]
        curva: dict[str, list] = {"jev": [], "igual": []}
        acc = {"jev": 0.0, "igual": 0.0}
        motivos: dict[str, dict] = {}
        for x in F:
            acc["jev"] += SOL * x["res"] / 100
            curva["jev"].append([x["fechou_t"], round(acc["jev"], 5)])
            bi = (x.get("base_igual") or {}).get("res")
            if bi is not None:
                acc["igual"] += SOL * bi / 100
                curva["igual"].append([x["fechou_t"], round(acc["igual"], 5)])
            g = motivos.setdefault(x.get("motivo") or "–", {"motivo": x.get("motivo") or "–", "n": 0, "soma": 0.0})
            g["n"] += 1
            g["soma"] += x["res"]
        for g in motivos.values():
            g["media_pct"] = round(g.pop("soma") / g["n"], 2)
        media = lambda v: round(sum(v) / len(v), 2) if v else None
        if len(comp) < 20:
            leitura = f"poucos dados: {len(comp)} entradas fechadas com a comparação pronta; vale a partir de 20"
        elif media(comp) > media(igual):
            leitura = f"o Jev está melhor: média {media(comp):+.1f}% contra {media(igual):+.1f}% da régua fixa nas mesmas entradas"
        else:
            leitura = f"o Jev não está ajudando: média {media(comp):+.1f}% contra {media(igual):+.1f}% da régua fixa nas mesmas entradas"
        return {"olhados": len(L), "entradas": sum(1 for x in L if x.get("entrada")), "fechadas": len(F), "suspeitos": sum(1 for x in L if x.get("suspeito")),
                "acerto": round(sum(r > 0 for r in res) / len(res) * 100) if res else None, "media_pct": media(res),
                "sol": round(sum(res) * SOL / 100, 5), "fator": round(win / lose, 2) if lose else None,
                "igual": {"n": len(igual), "media_pct": media(igual), "sol": round(sum(igual) * SOL / 100, 5), "jev_mesmas_pct": media(comp)},
                "todos": {"n": len(todos), "media_pct": media(todos), "sol": round(sum(todos) * SOL / 100, 5)},
                "curva": curva, "motivos": sorted(motivos.values(), key=lambda g: -g["n"]), "leitura": leitura}

    @staticmethod
    def row(x: dict, px: float | None = None, now: float | None = None) -> dict:
        e = x.get("entrada") or {}
        H = [a["h"] for a in x["hist"] if a.get("h") is not None]
        agora = pct_of(x, px) if px and e else None
        lucro = None if agora is None else x["realizado"] + x["left"] * agora - FEE_PCT
        return {"mint": x["mint"], "symbol": x.get("symbol"), "t": x["t"], "created_t": x.get("created_t"), "estado": x["estado"], "h0": H[0] if H else None, "h": H[-1] if H else None,
                "h_peak": x.get("h_peak"), "evol": H[-8:], "decisao": (x["decisoes"][-1] if x["decisoes"] else None), "entrada": e or None,
                "stop": x.get("stop"), "left": x.get("left"), "peak": x.get("peak"), "agora_pct": None if lucro is None else round(lucro, 1),
                "res": x.get("res"), "motivo": x.get("motivo"), "fechou_t": x.get("fechou_t"), "vendas": len(x.get("vendas") or []), "suspeito": x.get("suspeito"),
                "regua": (x.get("base_igual") or {}).get("res"), "regua_todos": (x.get("base_todos") or {}).get("res"),
                "regra": x.get("regra") or (JevTrade.rule_check(x["hist"]) if x["estado"] == "olhando" else None),
                "por": e.get("por"), "jev_entrada": e.get("jev"), "leituras": len(x["hist"]),
                "obs_s": None if now is None else round(now - x["t"]), "ultima_s": None if now is None or not x.get("last_read") else round(now - x["last_read"]),
                "prox_s": None if now is None or not x.get("last_read") else max(0, round(READ_S - (now - x["last_read"]))),
                "prazo_s": None if now is None or x["estado"] != "olhando" else max(0, round(WATCH_MAX_MIN * 60 - (now - x["t"])))}

    def load(self, rows: list[dict], now: float) -> None:
        for r in rows or []:
            d = r.get("data")
            if isinstance(d, dict) and d.get("mint"):
                self.items[d["id"]] = d
        day = time.strftime("%Y-%m-%d", time.gmtime(now))
        s = self.day(now)
        s["leituras"] = sum(len(x["hist"]) for x in self.items.values() if x.get("em", "")[:10] == day)

    def trim(self, now: float) -> None:
        for k in [k for k, x in self.items.items() if now - x["t"] > KEEP_S and x["estado"] not in ("olhando", "aberta")]:
            self.items.pop(k, None)


def backtest_rule(items: list[dict]) -> dict:
    """0.32.91 ("já ir para o resultado"): a regra nova aplicada às leituras guardadas dos tokens já observados.
    Entra na leitura em que a regra ligaria (até 7 min da 1ª leitura); a saída usa as leituras seguintes com as mesmas
    proteções (stop, parcial, empate, stop móvel, detentores saindo). Se as leituras acabam antes da saída, usa o preço
    final da régua fixa (25 min) — por isso é ESTIMATIVA."""
    S = STRAT
    out, sem = [], 0
    for it in items:
        H = [x for x in it.get("hist") or [] if x.get("px")]
        if len([x for x in H if x.get("h") is not None]) < 2:
            sem += 1
            continue
        m0 = H[0]["m"]
        k = None
        for i in range(1, len(H)):
            if H[i]["m"] - m0 > S["prazo_min"] + 0.3:
                break
            if JevTrade.rule_check(H[: i + 1])["ok"]:
                k = i
                break
        if k is None:                                   # 0.32.93: fechamento dos 7 min com mercado positivo também entra
            W = [i for i in range(len(H)) if H[i]["m"] - m0 <= S["prazo_min"] + 0.3]
            j = W[-1] if W else None
            if j and JevTrade.market_positive(H[: j + 1], H[j]["px"])["ok"] and H[j]["m"] - m0 >= S["prazo_min"] - 1.5:
                k = j
        if k is None:
            out.append({"mint": it.get("mint"), "symbol": it.get("symbol"), "t": it.get("t"), "entrou": False, "fonte": it.get("fonte")})
            continue
        e = H[k]
        px0, stop, peak, left, real, partial, why = e["px"], -S["stop_pct"], 0.0, 1.0, 0.0, False, None
        hmax = e.get("h") or 0
        for x in H[k + 1:]:
            pct = (x["px"] / px0 - 1) * 100
            peak = max(peak, pct)
            if x.get("h") is not None:
                hmax = max(hmax, x["h"])
                if x["h"] <= hmax * (1 - S["saida_detentores_pct"] / 100):
                    why = "detentores saindo"
            if peak >= S["empate_apos"]:
                stop = max(stop, 0.0)
            if not why and peak >= S["parcial_em"] and not partial:
                partial, real, left = True, real + 0.5 * pct, 0.5
            if not why and peak >= S["trail_apos"] and (1 + pct / 100) <= (1 + peak / 100) * (1 - S["trail_pct"] / 100):
                why = "stop móvel"
            if not why and pct <= stop:
                why = "stop"
            if why:
                real += left * pct
                left = 0
                break
        if left:
            b = it.get("base_todos") or {}
            if b.get("res") is not None and b.get("px"):
                fpx = b["px"] * (1 + (b["res"] + FEE_PCT) / 100)
                real += left * max((fpx / px0 - 1) * 100, stop if stop > -100 else -100)
                why = "estimado pelo preço aos 25 min"
            else:
                out.append({"mint": it.get("mint"), "symbol": it.get("symbol"), "t": it.get("t"), "entrou": True, "res": None, "motivo": "sem preço final", "fonte": it.get("fonte")})
                continue
        out.append({"mint": it.get("mint"), "symbol": it.get("symbol"), "t": it.get("t"), "entrou": True, "m": e["m"], "res": round(real - FEE_PCT, 1),
                    "pico": round(peak, 1), "motivo": why, "fonte": it.get("fonte")})
    R = [x["res"] for x in out if x.get("entrou") and x.get("res") is not None]
    return {"analisados": len(out), "sem_leituras": sem, "entradas": sum(1 for x in out if x.get("entrou")), "medidas": len(R),
            "acerto": round(sum(r > 0 for r in R) / len(R) * 100) if R else None, "media_pct": round(sum(R) / len(R), 1) if R else None,
            "sol": round(sum(R) * SOL / 100, 5), "itens": sorted([x for x in out if x.get("entrou")], key=lambda x: -(x.get("t") or 0))[:100]}


def from_bruxo_signal(s: dict) -> dict | None:
    """Sinal da Aba do Bruxo com detentores e preço minuto a minuto (desde a 0.32.86) no formato das leituras do Jev Trade.
    Só entra quem tinha 40+ detentores na 1ª leitura (a mesma porta do Jev Trade). Preço relativo ao do sinal (1,0)."""
    H, P = s.get("holders") or {}, s.get("hpx") or {}
    ks = sorted((int(k) for k in H if H.get(k) is not None and (k in P or k == "0")), key=int)
    if len(ks) < 2 or (H.get(str(ks[0])) or 0) < MIN_HOLDERS:
        return None
    hist = [{"m": k, "h": H[str(k)], "px": 1 + float(P.get(str(k), 0) or 0) / 100} for k in ks]
    m25 = (s.get("marks") or {}).get("25")
    return {"mint": s.get("mint"), "symbol": s.get("symbol"), "t": s.get("t"), "hist": hist, "fonte": "Aba do Bruxo",
            "base_todos": {"px": 1.0, "res": None if m25 is None else m25 - FEE_PCT}}
