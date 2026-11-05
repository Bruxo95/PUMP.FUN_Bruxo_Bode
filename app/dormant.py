"""Dormant (0.32.227, pedido do dono em 05/11/2026): vigia uma lista de moedas (a watchlist da CoinMarketCap do dono) e
diz quais estão dormindo, acordando, num pump ou num dump. Só observa: não compra nem vende nada.

Isolado do resto (como a BNB e a Robinhood): laço próprio, tabelas `dormant_*`, rotas `/api/dormant*` e página `/dormant`.

Fonte: API da CoinGecko (plano Demo grátis: 10 mil consultas por mês e 100 por minuto, conferido em
coingecko.com/en/api/pricing em 05/11/2026; sem chave usa a API pública, mais lenta). Uma consulta `/coins/markets` traz
até 250 moedas com preço, volume, variação de 1 h/24 h/7 d/30 d e o gráfico de 7 dias; a lista inteira cabe em 3 consultas
a cada 20 min (≈ 6.500 por mês). A ligação "moeda da CoinMarketCap → moeda da CoinGecko" sai de `/coins/list`
(1 consulta por semana) pelo nome; quando há várias com o mesmo nome, vale a de maior valor de mercado."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import statistics
import time
from datetime import datetime, timezone

log = logging.getLogger("pump.dormant")

API = "https://api.coingecko.com/api/v3"
EVERY_S = 20 * 60                      # 3 consultas a cada 20 min ≈ 6.500/mês (o grátis dá 10 mil)
MAP_EVERY_S = 7 * 86400                # a lista de moedas da CoinGecko muda pouco
PAUSE_429_S = 120
SNAP_KEEP_S = 90 * 86400               # fotos de hora em hora guardadas por 90 dias
SPARK_POINTS = 42                      # gráfico de 7 dias em pontos de 4 h (o painel não precisa das 168 horas)
LISTA = os.path.join(os.path.dirname(__file__), "dormant_lista.json")

CFG_DEFAULT = {
    "pump_1h": 8.0, "pump_24h": 20.0,          # % de alta em 1 h ou 24 h = pump
    "dump_1h": -8.0, "dump_24h": -20.0,        # % de queda = dump
    "sono_faixa_7d": 10.0,                     # dormindo = preço preso numa faixa menor que isto (%) nos 7 dias…
    "sono_30d": 20.0,                          # …e o mês todo variou menos que isto (%)
    "acorda_rompe": 3.0,                       # acordando = passou o topo da faixa dos 6 dias anteriores em X%…
    "acorda_vol_x": 3.0,                       # …ou o volume de 24 h ficou X vezes a mediana dos 7 dias
    "acorda_24h": 5.0,                         # …com alta mínima de X% em 24 h
    "vol_min_usd": 1000.0,                     # menos que isso negociado em 24 h = parada (sem negócio)
}
STATUS = {"pump": "pump", "dump": "dump", "acordando": "acordando", "dormindo": "dormindo", "normal": "normal",
          "parada": "parada (sem negócio)", "sem_cg": "não achada na CoinGecko"}
ALERT_ON = ("pump", "dump", "acordando")


def norm(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[\[(](old|new|migrated[^\])]*)[\])]", " ", s)
    return re.sub(r"[^a-z0-9]+", "", s)


def clean_cfg(raw: dict | None) -> dict:
    out = dict(CFG_DEFAULT)
    for k, v in (raw or {}).items():
        if k in CFG_DEFAULT:
            try:
                out[k] = float(v)
            except (TypeError, ValueError):
                pass
    return out


# nomes diferentes nos dois sites (conferidos no /coins/list da CoinGecko em 05/11/2026)
ALIAS = {"mina": "mina-protocol", "sushiswap": "sushi", "xyo": "xyo-network", "casper": "casper-network", "phala-network": "pha",
         "orchid": "orchid-protocol", "htx-token": "huobi-token", "dydx-ethdydx": "dydx", "fox-token": "shapeshift-fox-token",
         "wirex-token": "wirex", "clover": "clover-finance", "cheqd": "cheqd-network", "safemoon-v2": "safemoon-2", "regen-network": "regen"}


def match(lista: list[dict], cg: list[dict]) -> dict:
    """Moeda da CoinMarketCap → candidatos na CoinGecko (ids). Pelo nome; depois id igual ao da CoinMarketCap."""
    by_name: dict[str, list[str]] = {}
    ids = set()
    for c in cg:
        cid = c.get("id")
        if not cid:
            continue
        ids.add(cid)
        by_name.setdefault(norm(c.get("name")), []).append(cid)
    out = {}
    for m in lista:
        cand = list(by_name.get(norm(m["nome"])) or [])
        if ALIAS.get(m["cmc"]) in ids:
            cand = [ALIAS[m["cmc"]]] + [c for c in cand if c != ALIAS[m["cmc"]]]
        else:
            if m["cmc"] in cand:                   # o mesmo id dos dois sites vem primeiro
                cand.remove(m["cmc"])
            if m["cmc"] in ids and (m["cmc"] in by_name.get(norm(m["nome"]), []) or not cand):
                cand.insert(0, m["cmc"])           # id igual com nome diferente só vale se não houver outro pelo nome
        out[m["cmc"]] = cand[:4]
    return out


def spark(prices: list | None) -> list[float]:
    p = [float(x) for x in (prices or []) if x]
    if len(p) <= SPARK_POINTS:
        return p
    step = len(p) / SPARK_POINTS
    return [p[min(len(p) - 1, int(i * step))] for i in range(SPARK_POINTS - 1)] + [p[-1]]


def classify(row: dict, cfg: dict, vol_med: float | None = None) -> tuple[str, list[str]]:
    """Situação da moeda e por quê. row = linha do /coins/markets da CoinGecko."""
    c = cfg
    px, vol = row.get("current_price"), row.get("total_volume") or 0
    h1 = row.get("price_change_percentage_1h_in_currency")
    h24 = row.get("price_change_percentage_24h_in_currency")
    d30 = row.get("price_change_percentage_30d_in_currency")
    if not px or vol < c["vol_min_usd"]:
        return "parada", [f"negociou só US$ {vol:,.0f} em 24 h".replace(",", ".")]
    if (h1 is not None and h1 >= c["pump_1h"]) or (h24 is not None and h24 >= c["pump_24h"]):
        return "pump", [f"subiu {h1:+.1f}% em 1 h" if h1 is not None and h1 >= c["pump_1h"] else f"subiu {h24:+.1f}% em 24 h"]
    if (h1 is not None and h1 <= c["dump_1h"]) or (h24 is not None and h24 <= c["dump_24h"]):
        return "dump", [f"caiu {h1:+.1f}% em 1 h" if h1 is not None and h1 <= c["dump_1h"] else f"caiu {h24:+.1f}% em 24 h"]
    p = [float(x) for x in ((row.get("sparkline_in_7d") or {}).get("price") or []) if x]
    if len(p) >= 48:
        antes, dia = p[:-24], p[-24:]
        lo, hi = min(antes), max(antes)
        faixa = (hi / lo - 1) * 100 if lo else None
        why = []
        rompeu = faixa is not None and faixa < c["sono_faixa_7d"] * 1.5 and max(dia) >= hi * (1 + c["acorda_rompe"] / 100)
        if rompeu:
            why.append(f"estava numa faixa de {faixa:.1f}% e passou o topo em {(max(dia) / hi - 1) * 100:.1f}%")
        vx = (vol / vol_med) if vol_med else None
        if vx and vx >= c["acorda_vol_x"]:
            why.append(f"volume {vx:.1f}× a mediana dos 7 dias")
        if why and (h24 or 0) >= c["acorda_24h"]:
            return "acordando", why
        faixa7 = (max(p) / min(p) - 1) * 100 if min(p) else None
        if faixa7 is not None and faixa7 < c["sono_faixa_7d"] and (d30 is None or abs(d30) < c["sono_30d"]):
            return "dormindo", [f"preço numa faixa de {faixa7:.1f}% em 7 dias" + (f", {d30:+.1f}% no mês" if d30 is not None else "")]
    return "normal", []


class DormantWatch:
    """Laço próprio do Dormant. db pode ser None (sem guardar)."""

    def __init__(self, http, db=None, key_fn=None):
        self.http, self.db = http, db
        self.key_fn = key_fn or (lambda: "")
        self.lista = self._lista()
        self.cfg = dict(CFG_DEFAULT)
        self.map: dict[str, list[str]] = {}
        self.map_t = 0.0
        self.pick: dict[str, str] = {}               # moeda da CMC → id escolhido na CoinGecko
        self.rows: dict[str, dict] = {}              # id da CoinGecko → última linha do /coins/markets
        self.status: dict[str, tuple[str, list[str]]] = {}
        self.alertas: list[dict] = []
        self.snaps: list[dict] = []                  # fotos de hora em hora: {"t": hora, "d": {id: [preço, volume, mcap]}}
        self.stat = {"consultas": 0, "erros": 0, "ultimo_erro": None, "ultimo_erro_t": None, "leitura_t": None,
                     "mapa_t": None, "desde": time.time(), "limite_429": 0, "com_chave": False}
        self._pause_until = 0.0
        self._next = 0.0
        self.loaded = False

    @staticmethod
    def _lista() -> list[dict]:
        try:
            with open(LISTA, encoding="utf-8") as f:
                return list(json.load(f).get("moedas") or [])
        except Exception as e:
            log.warning("Dormant: lista não abriu: %s", e)
            return []

    # ------------------------------------------------------------------ CoinGecko
    async def get(self, path: str, params: dict | None = None):
        key = (self.key_fn() or "").strip()
        self.stat["com_chave"] = bool(key)
        head = {"accept": "application/json", "User-Agent": "pump-fun-copy/1.0"}
        if key:
            head["x-cg-demo-api-key"] = key
        self.stat["consultas"] += 1
        r = await self.http.get(API + path, params=params or {}, headers=head, timeout=30)
        if r.status_code == 429:
            self.stat["limite_429"] += 1
            self._pause_until = time.time() + PAUSE_429_S
            raise RuntimeError("a CoinGecko pediu para esperar (limite de consultas)")
        if r.status_code in (401, 403):
            raise RuntimeError("a CoinGecko recusou a chave (confira a chave Demo em Configurações)")
        if r.status_code != 200:
            raise RuntimeError(f"CoinGecko respondeu HTTP {r.status_code}")
        return r.json()

    async def refresh_map(self) -> None:
        cg = await self.get("/coins/list")
        if not isinstance(cg, list) or not cg:
            raise RuntimeError("lista da CoinGecko veio vazia")
        self.map = match(self.lista, cg)
        self.map_t = time.time()
        self.stat["mapa_t"] = self.map_t
        await self._put("map", {"t": self.map_t, "m": self.map})

    async def refresh_markets(self) -> None:
        ids = sorted({i for c in self.map.values() for i in c})
        got: dict[str, dict] = {}
        for k in range(0, len(ids), 250):
            part = ids[k:k + 250]
            rows = await self.get("/coins/markets", {"vs_currency": "usd", "ids": ",".join(part), "per_page": 250, "page": 1,
                                                     "sparkline": "true", "price_change_percentage": "1h,24h,7d,30d"})
            for r in rows or []:
                if r.get("id"):
                    got[r["id"]] = r
            if k + 250 < len(ids):
                await asyncio.sleep(2)
        now = time.time()
        self.rows.update(got)
        self.pick = {}
        for cmc, cand in self.map.items():           # várias com o mesmo nome: vale a de maior valor de mercado
            ok = [c for c in cand if c in self.rows]
            if not ok:
                continue
            cap = lambda c: self.rows[c].get("market_cap") or 0          # noqa: E731
            best = max(ok, key=cap)
            first = cand[0] if cand[0] in ok else best
            self.pick[cmc] = best if cap(best) > cap(first) * 10 else first
        self._classify(now)
        self.stat["leitura_t"] = now
        await self._snap(now)

    def vol_med(self, cid: str) -> float | None:
        v = [s["d"][cid][1] for s in self.snaps[-24 * 7:] if cid in s.get("d", {}) and s["d"][cid][1]]
        return statistics.median(v) if len(v) >= 24 else None

    def _classify(self, now: float) -> None:
        for cmc, cid in self.pick.items():
            row = self.rows.get(cid)
            if not row:
                continue
            st, why = classify(row, self.cfg, self.vol_med(cid))
            old = (self.status.get(cmc) or ("", []))[0]
            self.status[cmc] = (st, why)
            if st in ALERT_ON and old and old != st:
                self.alertas.insert(0, {"t": now, "cmc": cmc, "id": cid, "nome": row.get("name"), "simbolo": (row.get("symbol") or "").upper(),
                                        "de": old, "para": st, "por": why, "preco": row.get("current_price"),
                                        "h1": row.get("price_change_percentage_1h_in_currency"),
                                        "h24": row.get("price_change_percentage_24h_in_currency")})
        del self.alertas[300:]

    async def _snap(self, now: float) -> None:
        hora = int(now // 3600) * 3600
        if self.snaps and self.snaps[-1]["t"] == hora:
            return
        d = {cid: [r.get("current_price"), r.get("total_volume"), r.get("market_cap")] for cid, r in self.rows.items()}
        self.snaps.append({"t": hora, "d": d})
        self.snaps = [s for s in self.snaps if s["t"] >= now - 8 * 86400]
        await self._put("alertas", {"a": self.alertas[:300]})
        if self.db is not None:
            try:
                await self.db.insert("dormant_snap", {"t": datetime.fromtimestamp(hora, timezone.utc).isoformat(), "dados": d},
                                     upsert=True, on_conflict="t")
                if int(now // 86400) != int((now - EVERY_S) // 86400) and hasattr(self.db, "_req"):   # uma vez por dia: tira o que passou de 90 dias
                    old = datetime.fromtimestamp(now - SNAP_KEEP_S, timezone.utc).isoformat()
                    await self.db._req("DELETE", "dormant_snap", {"t": f"lt.{old}"}, None, "return=minimal")
            except Exception as e:
                log.warning("Dormant: foto da hora não gravou: %s", str(e)[:160])

    # ------------------------------------------------------------------ banco
    async def _put(self, k: str, v: dict) -> None:
        if self.db is None:
            return
        try:
            await self.db.insert("dormant_state", {"k": k, "v": v}, upsert=True, on_conflict="k")
        except Exception as e:
            log.warning("Dormant: estado %s não gravou: %s", k, str(e)[:160])

    async def load(self) -> None:
        if self.db is not None:
            try:
                for r in await self.db.select("dormant_state", None) or []:
                    v = r.get("v") or {}
                    if r.get("k") == "cfg":
                        self.cfg = clean_cfg(v)
                    elif r.get("k") == "map" and isinstance(v.get("m"), dict):
                        self.map, self.map_t = v["m"], float(v.get("t") or 0)
                        self.stat["mapa_t"] = self.map_t
                    elif r.get("k") == "alertas":
                        self.alertas = list(v.get("a") or [])
                since = datetime.fromtimestamp(time.time() - 8 * 86400, timezone.utc).isoformat()
                rows = await self.db.select("dormant_snap", None, order="t.asc", limit=24 * 8 + 5, gte={"t": since}) or []
                self.snaps = [{"t": int(datetime.fromisoformat(str(r["t"]).replace("Z", "+00:00")).timestamp()), "d": r.get("dados") or {}} for r in rows]
            except Exception as e:
                log.warning("Dormant: estado guardado não carregou: %s", str(e)[:160])
        self.loaded = True

    async def save_cfg(self, raw: dict) -> dict:
        self.cfg = clean_cfg({**self.cfg, **(raw or {})})
        self._classify(time.time())
        await self._put("cfg", self.cfg)
        return self.cfg

    # ------------------------------------------------------------------ laço
    async def tick(self) -> None:
        now = time.time()
        if now < self._pause_until:
            return
        if not self.map or now - self.map_t > MAP_EVERY_S:
            await self.refresh_map()
        if now >= self._next:
            await self.refresh_markets()
            self._next = now + EVERY_S

    async def run(self) -> None:
        await self.load()
        while True:
            try:
                await asyncio.wait_for(self.tick(), 120)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.stat["erros"] += 1
                self.stat["ultimo_erro"], self.stat["ultimo_erro_t"] = str(e)[:200], time.time()
                self._next = time.time() + 120          # erro: tenta de novo em 2 min, não a cada volta
                log.info("Dormant: %s", str(e)[:200])
            await asyncio.sleep(20)

    def refresh_now(self) -> None:
        self._next = 0.0

    # ------------------------------------------------------------------ tela
    def state(self) -> dict:
        moedas, cont = [], {k: 0 for k in STATUS}
        cont["morta"] = 0
        for m in self.lista:
            cid = self.pick.get(m["cmc"])
            row = self.rows.get(cid) if cid else None
            st, why = self.status.get(m["cmc"]) or (("sem_cg", []) if self.stat["leitura_t"] and not cid else ("", []))
            if not row and m.get("morta_cmc"):
                st = "morta"
            if st:
                cont[st] = cont.get(st, 0) + 1
            it = {"cmc": m["cmc"], "nome": m["nome"], "simbolo": m.get("simbolo") or "", "status": st, "por": why,
                  "morta_cmc": bool(m.get("morta_cmc")), "cg": cid}
            if row:
                it.update(nome=row.get("name") or m["nome"], simbolo=(row.get("symbol") or "").upper(), img=row.get("image"),
                          preco=row.get("current_price"), mcap=row.get("market_cap"), rank=row.get("market_cap_rank"),
                          vol=row.get("total_volume"), h1=row.get("price_change_percentage_1h_in_currency"),
                          h24=row.get("price_change_percentage_24h_in_currency"), d7=row.get("price_change_percentage_7d_in_currency"),
                          d30=row.get("price_change_percentage_30d_in_currency"), ath=row.get("ath"),
                          ath_pct=row.get("ath_change_percentage"), atl=row.get("atl"), spark=spark((row.get("sparkline_in_7d") or {}).get("price")),
                          vol_x=round(row.get("total_volume") / v, 2) if (v := self.vol_med(cid)) and row.get("total_volume") else None)
            moedas.append(it)
        return {"ligado": True, "carregado": self.loaded, "cfg": self.cfg, "padrao": CFG_DEFAULT, "nomes": STATUS,
                "status": {**self.stat, "moedas": len(self.lista), "achadas": len(self.pick), "fotos": len(self.snaps),
                           "pausa_s": max(0, round(self._pause_until - time.time())), "proxima_s": max(0, round(self._next - time.time())),
                           "a_cada_min": EVERY_S // 60},
                "contagem": cont, "moedas": moedas, "alertas": self.alertas[:100]}
