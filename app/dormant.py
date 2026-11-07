"""Dormant (0.32.227, pedido do dono em 05/11/2026): vigia uma lista de moedas (a watchlist da CoinMarketCap do dono) e
diz quais estão dormindo, acordando, num pump ou num dump. Este laço só observa; a compra à mão fica em dormant_buy.py (0.32.242).

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

from .dormant_buy import CHAINS, buyable

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
INFO_EVERY_S = 20                      # 0.32.228: categoria e blockchain principal, 1 moeda a cada 20 s (≈ 3 h a lista toda)…
INFO_KEEP_S = 30 * 86400               # …refeita uma vez por mês (≈ 700 consultas por mês)
PROPRIA = "propria"                    # moeda da própria blockchain (Bitcoin, Solana, Dogecoin…)
CHAIN_NAMES = {PROPRIA: "Blockchain própria", "ethereum": "Ethereum", "binance-smart-chain": "BNB Chain", "solana": "Solana",
               "polygon-pos": "Polygon", "arbitrum-one": "Arbitrum", "base": "Base", "avalanche": "Avalanche", "tron": "TRON",
               "optimistic-ethereum": "Optimism", "fantom": "Fantom", "cronos": "Cronos", "klay-token": "Kaia", "near-protocol": "NEAR",
               "cosmos": "Cosmos", "osmosis": "Osmosis", "xdai": "Gnosis", "harmony-shard-0": "Harmony", "moonriver": "Moonriver",
               "moonbeam": "Moonbeam", "huobi-token": "HECO", "okex-chain": "OKC", "aurora": "Aurora", "energi": "Energi", "sora": "SORA",
               "polkadot": "Polkadot", "kusama": "Kusama", "stellar": "Stellar", "waves": "Waves", "algorand": "Algorand",
               "hedera-hashgraph": "Hedera", "the-open-network": "TON", "sui": "Sui", "aptos": "Aptos", "robinhood": "Robinhood Chain",
               "hyperevm": "HyperEVM", "sonic": "Sonic", "cardano": "Cardano", "zksync": "zkSync", "linea": "Linea", "mantle": "Mantle",
               "world-chain": "World Chain", "unichain": "Unichain"}
# 0.32.229 (áudio do Bruxo, 05/11: "a CoinGecko só serve para saber a blockchain; tem que entrar na blockchain e ver as
# últimas 3 ações"): as negociações vêm da GeckoTerminal, que lê os pools direto de cada blockchain (grátis, sem chave,
# 30 consultas por minuto; conferido em 05/11/2026 com o PEPE na Ethereum). Rede da CoinGecko → rede da GeckoTerminal:
GT = "https://api.geckoterminal.com/api/v2"
GT_NET = {"ethereum": "eth", "binance-smart-chain": "bsc", "solana": "solana", "base": "base", "arbitrum-one": "arbitrum",
          "polygon-pos": "polygon_pos", "avalanche": "avax", "tron": "tron", "optimistic-ethereum": "optimism",
          "the-open-network": "ton", "sui": "sui-network", "cronos": "cro", "fantom": "ftm", "sonic": "sonic", "mantle": "mantle",
          "linea": "linea", "robinhood": "robinhood", "chiliz": "chiliz-chain", "klay-token": "kaia", "xdai": "xdai",
          "near-protocol": "near", "hyperevm": "hyperevm", "energi": "nrg", "harmony-shard-0": "one", "moonbeam": "glmr",
          "moonriver": "movr", "aurora": "aurora", "celo": "celo", "kava": "kava", "stellar": "stellar", "cardano": "cardano",
          "aptos": "aptos", "world-chain": "world-chain", "unichain": "unichain", "zksync": "zksync"}   # 0.32.256: as 3 conferidas na GeckoTerminal
GT_EVERY_S = 6.0                       # 10 por minuto: o limite grátis anunciado é 30, mas em 05/11 já pediu para esperar antes disso
GT_AGAIN_S = 30 * 60                   # cada moeda é olhada de novo a cada ~30 min
POOL_KEEP_S = 7 * 86400                # o pool principal do token é procurado de novo toda semana
GT_PAUSE_S = 120
ACORDOU_GAP_S = 6 * 3600               # acordou na blockchain: negociou agora depois de 6 h ou mais parada
# 0.32.248 (pedido do dono): quanto movimentou em cada período. Conferido em 07/11/2026: a CoinGecko só dá 24 h (todas as corretoras); a
# GeckoTerminal dá 1 h, 6 h e 24 h do pool, sem 12 h, e lê vários pools numa consulta. 12 h = 6 h de agora + 6 h de 6 h atrás. 7 e 30 dias = volume de 24 h
# de cada dia (market_chart da CoinGecko, uma vez por moeda; depois a leitura de 20 min mantém o dia de hoje). Volume é compra + venda: não é dinheiro novo.
PV_EVERY_S = 30                        # 1 consulta de lote a cada 30 s…
PV_AGAIN_S = 600                       # …cada pool lido de novo a cada 10 min
PV_LOTE = 20
VD_EVERY_S = 30                        # histórico de 30 dias: 1 moeda a cada 30 s, uma vez só (≈ 660 consultas no total)
VD_DIAS = 31
CG_URL = re.compile(r"coingecko\.com/(?:[a-z-]+/)?coins/([a-z0-9-]+)", re.I)


def chain_name(k: str | None) -> str:
    if not k:
        return "?"
    return CHAIN_NAMES.get(k) or k.replace("-", " ").title()


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
        return "parada", [f"negociou só ${vol:.0f} em 24 h"]
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
        self.extras: list[dict] = []                 # 0.32.228: moedas que um admin adicionou na tela ({cg, nome, simbolo, por, t})
        self.plat: dict[str, list[str]] = {}         # id → blockchains onde o token existe (da lista da CoinGecko)
        self.info: dict[str, dict] = {}              # id → {"cats": categorias, "plat": blockchain principal, "t": quando}
        self.cgnames: dict[str, tuple] = {}          # última lista da CoinGecko (só memória, para a busca)
        self.addr: dict[str, dict] = {}              # 0.32.229: id → {blockchain: contrato}
        self.gtpool: dict[str, dict] = {}            # id → {"net", "pool", "t"} (pool principal na GeckoTerminal)
        self.chain: dict[str, dict] = {}             # id → últimas ações na blockchain ({"last3", "n24", "ultima_t", "t", …})
        self.gstat = {"consultas": 0, "erros": 0, "ultimo_erro": None, "ultimo_erro_t": None, "limite_429": 0, "ultima_t": None}
        self._gt_pause = 0.0
        self._gt_n = 0
        self._info_at = 0.0
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
        self.held: set[str] = set()                  # 0.32.242: moedas compradas continuam com preço mesmo se saírem da lista
        self.pvol: dict[str, dict] = {}              # 0.32.248: id → volume do pool principal (1 h, 6 h, 24 h, negócios, fotos de 6 h)
        self.voldays: dict[str, dict] = {}           # id → {dia: volume de 24 h}
        self.volback: set[str] = set()               # moedas que já buscaram os 30 dias
        self._pv_at = self._vd_at = 0.0
        self._pv_n = self._vd_n = 0

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

    def todas(self) -> list[dict]:
        """A watchlist + as moedas adicionadas na tela (chave "cg:<id>")."""
        return self.lista + [{"cmc": "cg:" + e["cg"], "nome": e.get("nome") or e["cg"], "simbolo": e.get("simbolo") or "",
                              "morta_cmc": False, "extra": e} for e in self.extras]

    async def _cglist(self) -> list[dict]:
        cg = await self.get("/coins/list", {"include_platform": "true"})
        if not isinstance(cg, list) or not cg:
            raise RuntimeError("lista da CoinGecko veio vazia")
        self.cgnames = {c["id"]: (c.get("name") or "", c.get("symbol") or "", [k for k in (c.get("platforms") or {}) if k],
                                  {k: v for k, v in (c.get("platforms") or {}).items() if k and v})
                        for c in cg if c.get("id")}
        return cg

    async def refresh_map(self) -> None:
        cg = await self._cglist()
        self.map = match(self.lista, cg)
        for e in self.extras:
            self.map["cg:" + e["cg"]] = [e["cg"]]
        self.plat = {i: list(self.cgnames.get(i, ("", "", []))[2]) for c in self.map.values() for i in c}
        self.addr = {i: dict(self.cgnames.get(i, ("", "", [], {}))[3]) for c in self.map.values() for i in c}
        await self._put("addr", {"a": self.addr})
        self.map_t = time.time()
        self.stat["mapa_t"] = self.map_t
        await self._put("map", {"t": self.map_t, "m": self.map})
        await self._put("plat", {"p": self.plat})

    # ------------------------------------------------------------------ blockchain e categoria (0.32.228)
    def chain_of(self, cid: str | None) -> str | None:
        inf = self.info.get(cid or "")
        if inf and "plat" in inf:
            return inf["plat"] or PROPRIA
        if cid in self.plat:
            return (self.plat[cid] or [PROPRIA])[0]
        return None

    async def info_step(self, now: float) -> None:
        """Uma moeda por vez: categorias e blockchain principal (/coins/{id}). Nunca atrapalha a leitura dos preços."""
        if now - self._info_at < INFO_EVERY_S:
            return
        falta = [c for c in dict.fromkeys(self.pick.values()) if now - float((self.info.get(c) or {}).get("t") or 0) > INFO_KEEP_S]
        if not falta:
            return
        self._info_at = now
        cid = falta[0]
        try:
            r = await self.get("/coins/" + cid, {"localization": "false", "tickers": "false", "market_data": "false",
                                                 "community_data": "false", "developer_data": "false", "sparkline": "false"})
            self.info[cid] = {"cats": [c for c in (r.get("categories") or []) if c][:8], "plat": r.get("asset_platform_id") or None, "t": now}
        except RuntimeError:
            raise
        except Exception as e:
            self.info[cid] = {"cats": [], "t": now - INFO_KEEP_S + 86400, "erro": str(e)[:80]}   # tenta de novo amanhã
        self._info_n = getattr(self, "_info_n", 0) + 1
        if len(falta) == 1 or self._info_n % 10 == 0:                # grava a cada 10 moedas (e na última)
            await self._put("info", {"i": self.info})

    # ------------------------------------------------------------------ adicionar moedas (0.32.228)
    async def search(self, q: str) -> list[dict]:
        q = (q or "").strip()
        if not q:
            return []
        if not self.cgnames:
            await self._cglist()
        m = CG_URL.search(q)
        if m:
            ids = [m.group(1).lower()] if m.group(1).lower() in self.cgnames else []
        else:
            n, ql = norm(q), q.lower()
            score = []
            for cid, (name, sym, *_) in self.cgnames.items():
                s = 0 if cid == ql else 1 if sym.lower() == ql or norm(name) == n else 2 if norm(name).startswith(n) else 3 if n and n in norm(name) else None
                if s is not None:
                    score.append((s, len(name), cid))
            ids = [c for _, _, c in sorted(score)[:12]]
        if not ids:
            return []
        rows = {}
        try:
            for r in await self.get("/coins/markets", {"vs_currency": "usd", "ids": ",".join(ids), "per_page": 50, "page": 1}) or []:
                rows[r["id"]] = r
        except RuntimeError:
            pass
        have = {e["cg"] for e in self.extras} | set(self.pick.values())
        out = []
        for cid in ids:
            name, sym, plats = self.cgnames.get(cid, ("", "", [], {}))[:3]
            r = rows.get(cid) or {}
            out.append({"id": cid, "nome": name, "simbolo": sym.upper(), "blockchains": [chain_name(p) for p in plats[:4]] or [chain_name(PROPRIA)],
                        "preco": r.get("current_price"), "mcap": r.get("market_cap"), "vol": r.get("total_volume"), "img": r.get("image"),
                        "ja_tem": cid in have})
        out.sort(key=lambda x: -(x["mcap"] or 0))
        return out

    async def add(self, cid: str, por: str, por_id: str) -> dict:
        cid = (cid or "").strip().lower()
        if not re.fullmatch(r"[a-z0-9-]{1,100}", cid):
            raise ValueError("id da CoinGecko inválido")
        if not self.cgnames:
            await self._cglist()
        if cid not in self.cgnames:
            raise ValueError("não achei essa moeda na CoinGecko")
        if cid in {e["cg"] for e in self.extras} or cid in set(self.pick.values()):
            raise ValueError("essa moeda já está na lista")
        name, sym, plats, adr = self.cgnames[cid]
        e = {"cg": cid, "nome": name, "simbolo": sym.upper(), "por": por or "admin", "por_id": por_id, "t": time.time()}
        self.extras.append(e)
        self.map["cg:" + cid] = [cid]
        self.plat[cid] = list(plats)
        self.addr[cid] = dict(adr)
        await self._put("extras", {"e": self.extras})
        self.refresh_now()
        return e

    async def remove(self, key: str) -> bool:
        cid = key[3:] if key.startswith("cg:") else key
        before = len(self.extras)
        self.extras = [e for e in self.extras if e["cg"] != cid]
        if len(self.extras) == before:
            return False
        self.map.pop("cg:" + cid, None)
        self.pick.pop("cg:" + cid, None)
        self.status.pop("cg:" + cid, None)
        await self._put("extras", {"e": self.extras})
        return True

    async def refresh_markets(self) -> None:
        ids = sorted({i for c in self.map.values() for i in c} | self.held | {c["cg"] for c in CHAINS.values()})   # 0.32.242: a moeda de cada rede, para os limites em dólar
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
        dia = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d")
        for cid, r in got.items():
            if r.get("total_volume") is not None:
                self.voldays.setdefault(cid, {})[dia] = r["total_volume"]
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
                                        "vol24": row.get("total_volume"), "v1": (self.pvol.get(cid) or {}).get("h1"),
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
                    elif r.get("k") == "extras":
                        self.extras = [e for e in (v.get("e") or []) if isinstance(e, dict) and e.get("cg")]
                    elif r.get("k") == "plat":
                        self.plat = dict(v.get("p") or {})
                    elif r.get("k") == "info":
                        self.info = dict(v.get("i") or {})
                    elif r.get("k") == "addr":
                        self.addr = dict(v.get("a") or {})
                    elif r.get("k") == "gtpool":
                        self.gtpool = dict(v.get("p") or {})
                    elif r.get("k") == "chain":
                        self.chain = dict(v.get("c") or {})
                    elif r.get("k") == "pvol":
                        self.pvol = dict(v.get("p") or {})
                    elif r.get("k") == "voldays":
                        self.voldays, self.volback = dict(v.get("d") or {}), set(v.get("b") or [])
                since = datetime.fromtimestamp(time.time() - 8 * 86400, timezone.utc).isoformat()
                rows = await self.db.select("dormant_snap", None, order="t.asc", limit=24 * 8 + 5, gte={"t": since}) or []
                self.snaps = [{"t": int(datetime.fromisoformat(str(r["t"]).replace("Z", "+00:00")).timestamp()), "d": r.get("dados") or {}} for r in rows]
                self.held = {r["cg"] for r in await self.db.select("dormant_buys", {"status": "confirmada"}, columns="cg", limit=2000) or [] if r.get("cg")}
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
        if not self.map or now - self.map_t > MAP_EVERY_S or (self.map and not self.addr):   # 0.32.229: precisa dos contratos
            await self.refresh_map()
        if now >= self._next:
            await self.refresh_markets()
            self._next = now + EVERY_S
        else:
            await self.info_step(now)
            await self.vol_step(now)

    # ------------------------------------------------------------------ volume por período (0.32.248)
    async def vol_step(self, now: float) -> None:
        """Uma moeda por vez: volume de cada um dos últimos 30 dias, só na primeira vez."""
        if now - self._vd_at < VD_EVERY_S:
            return
        cid = next((c for c in dict.fromkeys(self.pick.values()) if c not in self.volback), None)
        if not cid:
            return
        self._vd_at = now
        try:
            r = await self.get(f"/coins/{cid}/market_chart", {"vs_currency": "usd", "days": "30"})
        except RuntimeError:
            raise                                  # pediu para esperar: tenta de novo depois, sem marcar
        except Exception:
            r = {}
        d = self.voldays.setdefault(cid, {})
        hoje = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d")
        for p in (r.get("total_volumes") or []) if isinstance(r, dict) else []:
            if p and p[1] is not None:
                dia = datetime.fromtimestamp(p[0] / 1000, timezone.utc).strftime("%Y-%m-%d")
                if dia != hoje or dia not in d:    # o mais novo de cada dia ganha; o de hoje é o da leitura de 20 min
                    d[dia] = p[1]
        for k in sorted(d)[:-VD_DIAS]:
            del d[k]
        self.volback.add(cid)
        self._vd_n += 1
        if self._vd_n % 20 == 0:
            await self._put("voldays", {"d": self.voldays, "b": sorted(self.volback)})

    async def pool_vol_step(self, now: float | None = None) -> int:
        """Um lote de pools de uma rede. Devolve quantos leu."""
        now = now or time.time()
        if now < self._gt_pause:
            return 0
        due = [(float((self.pvol.get(c) or {}).get("t") or 0), c, g) for c, g in self.gtpool.items()
               if g.get("pool") and now - float((self.pvol.get(c) or {}).get("t") or 0) >= PV_AGAIN_S]
        if not due:
            return 0
        due.sort(key=lambda x: x[0])
        net = due[0][2]["net"]
        lote = [(c, g["pool"]) for _, c, g in due if g["net"] == net][:PV_LOTE]
        r = await self.gt_get(f"/networks/{net}/pools/multi/" + ",".join(p for _, p in lote))
        por = {}
        for x in (r or {}).get("data") or []:
            a = x.get("attributes") or {}
            if a.get("address"):
                por[str(a["address"]).lower()] = a

        def num(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
        for cid, pool in lote:
            a = por.get(str(pool).lower())
            old = self.pvol.get(cid) or {}
            if not a:
                self.pvol[cid] = {**old, "t": now}  # sem resposta: não insiste antes da próxima volta
                continue
            v, tx = a.get("volume_usd") or {}, a.get("transactions") or {}
            fotos = [f for f in old.get("s6") or [] if now - f[0] <= 7 * 3600]
            h6 = num(v.get("h6"))
            if h6 is not None and (not fotos or now - fotos[-1][0] >= 3600):
                fotos.append([now, h6])
            self.pvol[cid] = {"t": now, "h1": num(v.get("h1")), "h6": h6, "h24": num(v.get("h24")), "s6": fotos, "liq": num(a.get("reserve_in_usd")),
                              "tx1": [(tx.get("h1") or {}).get("buys"), (tx.get("h1") or {}).get("sells")], "tx24": [(tx.get("h24") or {}).get("buys"), (tx.get("h24") or {}).get("sells")]}
        self._pv_n += 1
        if self._pv_n % 60 == 0:                   # ~30 min
            await self._put("pvol", {"p": self.pvol})
        return len(lote)

    @staticmethod
    def v12(p: dict, now: float) -> float | None:
        """12 h = 6 h de agora + a foto de 6 h tirada há cerca de 6 h (entre 5 h 20 e 6 h 40). Sem essa foto ainda, não inventa."""
        if p.get("h6") is None:
            return None
        velhas = [f for f in p.get("s6") or [] if 19200 <= now - f[0] <= 24000]
        if not velhas:
            return None
        return p["h6"] + min(velhas, key=lambda f: abs(now - f[0] - 21600))[1]

    def vols(self, cid: str | None, now: float) -> dict:
        p, d = self.pvol.get(cid) or {}, self.voldays.get(cid) or {}
        dias = [d[k] for k in sorted(d)]
        return {"v1": p.get("h1"), "v6": p.get("h6"), "v12": self.v12(p, now), "pv24": p.get("h24"), "tx1": p.get("tx1"), "tx24": p.get("tx24"), "liq": p.get("liq"), "pv_t": p.get("t"),
                "v7d": round(sum(dias[-7:]), 2) if len(dias) >= 7 else None, "v30d": round(sum(dias[-30:]), 2) if len(dias) >= 25 else None}

    # ------------------------------------------------------------------ últimas ações na blockchain (0.32.229)
    def target(self, cid: str) -> tuple[str, str, str] | None:
        """(blockchain da CoinGecko, rede da GeckoTerminal, contrato) da moeda; None = rede própria ou sem contrato."""
        ch = self.chain_of(cid)
        adr = self.addr.get(cid) or {}
        if not ch or ch == PROPRIA:
            return None
        if ch in GT_NET and adr.get(ch):
            return ch, GT_NET[ch], adr[ch]
        for k, v in adr.items():                    # a principal sem pool conhecido: tenta outra rede onde ele existe
            if k in GT_NET and v:
                return k, GT_NET[k], v
        return None

    async def gt_get(self, path: str):
        self.gstat["consultas"] += 1
        r = await self.http.get(GT + path, headers={"accept": "application/json", "User-Agent": "pump-fun-copy/1.0"}, timeout=30)
        if r.status_code == 429:
            self.gstat["limite_429"] += 1
            self._gt_pause = time.time() + GT_PAUSE_S
            raise RuntimeError("a GeckoTerminal pediu para esperar")
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise RuntimeError(f"GeckoTerminal respondeu HTTP {r.status_code}")
        return r.json()

    def gt_next(self, now: float) -> str | None:
        ids = [c for c in dict.fromkeys(self.pick.values()) if self.target(c)]
        due = [c for c in ids if now - float((self.chain.get(c) or {}).get("t") or 0) >= GT_AGAIN_S]
        return min(due, key=lambda c: float((self.chain.get(c) or {}).get("t") or 0)) if due else None

    @staticmethod
    def _ts(s) -> float | None:
        try:
            return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
        except Exception:
            return None

    async def gt_step(self, now: float | None = None) -> str | None:
        now = now or time.time()
        if now < self._gt_pause:
            return None
        cid = self.gt_next(now)
        if not cid:
            return None
        ch, net, adr = self.target(cid)
        old = self.chain.get(cid) or {}
        pool = self.gtpool.get(cid) or {}
        if not pool or pool.get("net") != net or now - float(pool.get("t") or 0) > POOL_KEEP_S:
            r = await self.gt_get(f"/networks/{net}/tokens/{adr}/pools?page=1")
            ps = (r or {}).get("data") or []
            pool = {"net": net, "pool": ((ps[0].get("attributes") or {}).get("address") if ps else None), "t": now,
                    "nome": ((ps[0].get("attributes") or {}).get("name") if ps else None)}
            self.gtpool[cid] = pool
            await self._put("gtpool", {"p": self.gtpool})
            if not pool["pool"]:
                self.chain[cid] = {"t": now, "net": net, "sem_pool": True}
                return cid
            await asyncio.sleep(GT_EVERY_S)
        r = await self.gt_get(f"/networks/{net}/pools/{pool['pool']}/trades")
        tr = []
        for t in (r or {}).get("data") or []:
            a = t.get("attributes") or {}
            ts = self._ts(a.get("block_timestamp"))
            if ts:
                tr.append({"t": ts, "kind": "compra" if a.get("kind") == "buy" else "venda",
                           "usd": round(float(a.get("volume_in_usd") or 0), 2), "wallet": a.get("tx_from_address"), "tx": a.get("tx_hash")})
        tr.sort(key=lambda x: -x["t"])
        dia = [x for x in tr if x["t"] >= now - 86400]
        novo = {"t": now, "net": net, "rede": ch, "pool": pool["pool"], "pool_nome": pool.get("nome"), "last3": tr[:3],
                "n24": len(dia), "compras24": sum(1 for x in dia if x["kind"] == "compra"),
                "usd24": round(sum(x["usd"] for x in dia), 2), "ultima_t": tr[0]["t"] if tr else old.get("ultima_t")}
        # acordou: estava parado (sem negócio em 24 h, ou 6 h+ entre a última e a anterior) e negociou agora há pouco
        parado_antes = (old.get("t") and not old.get("n24")) or (len(tr) >= 2 and tr[0]["t"] - tr[1]["t"] >= ACORDOU_GAP_S)
        if tr and parado_antes and now - tr[0]["t"] <= 3600 and old.get("ultima_t") != tr[0]["t"]:
            gap = tr[0]["t"] - (tr[1]["t"] if len(tr) >= 2 else float(old.get("ultima_t") or 0))
            row = self.rows.get(cid) or {}
            cmc = next((k for k, v in self.pick.items() if v == cid), cid)
            self.alertas.insert(0, {"t": now, "cmc": cmc, "id": cid, "nome": row.get("name") or cid, "simbolo": (row.get("symbol") or "").upper(),
                                    "de": "parada_chain", "para": "acordou_chain", "chain": True,
                                    "por": [f"{tr[0]['kind']} de ${tr[0]['usd']:.0f} na {chain_name(ch)}" +
                                            (f" depois de {gap / 3600:.0f} h sem negócio" if gap and gap < 400 * 86400 else " depois de mais de 24 h sem negócio")],
                                    "preco": row.get("current_price"), "h1": row.get("price_change_percentage_1h_in_currency"),
                                    "h24": row.get("price_change_percentage_24h_in_currency"), "vol24": row.get("total_volume"), "v1": (self.pvol.get(cid) or {}).get("h1")})
            del self.alertas[300:]
            await self._put("alertas", {"a": self.alertas[:300]})
        self.chain[cid] = novo
        self.gstat["ultima_t"] = now
        self._gt_n += 1
        if self._gt_n % 20 == 0:
            await self._put("chain", {"c": self.chain})
        return cid

    async def gt_loop(self) -> None:
        while True:
            try:
                if time.time() - self._pv_at >= PV_EVERY_S:
                    self._pv_at = time.time()
                    await asyncio.wait_for(self.pool_vol_step(), 60)
                else:
                    await asyncio.wait_for(self.gt_step(), 90)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.gstat["erros"] += 1
                self.gstat["ultimo_erro"], self.gstat["ultimo_erro_t"] = str(e)[:200], time.time()
            await asyncio.sleep(GT_EVERY_S)

    async def run(self) -> None:
        await self.load()
        gt = asyncio.get_running_loop().create_task(self.gt_loop())   # mesma marca de uso (contextvar copiada)
        try:
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
        finally:
            gt.cancel()

    def refresh_now(self) -> None:
        self._next = 0.0

    # ------------------------------------------------------------------ tela
    def item(self, m: dict) -> dict:
        """Uma moeda como a tela mostra (lista e janela da moeda)."""
        if True:
            cid = self.pick.get(m["cmc"])
            row = self.rows.get(cid) if cid else None
            st, why = self.status.get(m["cmc"]) or (("sem_cg", []) if self.stat["leitura_t"] and not cid else ("", []))
            if not row and m.get("morta_cmc"):
                st = "morta"
            ch = self.chain_of(cid)
            ex = m.get("extra") or {}
            it = {"cmc": m["cmc"], "nome": m["nome"], "simbolo": m.get("simbolo") or "", "status": st, "por": why,
                  "morta_cmc": bool(m.get("morta_cmc")), "cg": cid, "chain": ch, "chain_nome": chain_name(ch) if ch else None,
                  "chains": [chain_name(p) for p in (self.plat.get(cid) or [])[:6]], "cats": (self.info.get(cid) or {}).get("cats") or [],
                  "add_por": ex.get("por") or "watchlist da CoinMarketCap", "add_t": ex.get("t"), "extra": bool(ex),
                  "bc": self.chain.get(cid) if cid else None, "bc_alvo": bool(cid and self.target(cid)), "rede_propria": ch == PROPRIA,
                  "comprar": buyable(self, cid), **self.vols(cid, time.time())}
            if row:
                it.update(nome=row.get("name") or m["nome"], simbolo=(row.get("symbol") or "").upper(), img=row.get("image"),
                          preco=row.get("current_price"), mcap=row.get("market_cap"), rank=row.get("market_cap_rank"),
                          vol=row.get("total_volume"), h1=row.get("price_change_percentage_1h_in_currency"),
                          h24=row.get("price_change_percentage_24h_in_currency"), d7=row.get("price_change_percentage_7d_in_currency"),
                          d30=row.get("price_change_percentage_30d_in_currency"), ath=row.get("ath"),
                          ath_pct=row.get("ath_change_percentage"), atl=row.get("atl"),
                          ath_t=self._ts(row.get("ath_date")), atl_t=self._ts(row.get("atl_date")), atl_pct=row.get("atl_change_percentage"), spark=spark((row.get("sparkline_in_7d") or {}).get("price")),
                          vol_x=round(row.get("total_volume") / v, 2) if (v := self.vol_med(cid)) and row.get("total_volume") else None)
            return it

    # 0.32.232 (pedido do dono): janela da moeda, com gráfico de 30 dias e as últimas negociações na blockchain (só quando abre)
    async def detail(self, key: str) -> dict | None:
        m = next((x for x in self.todas() if x["cmc"] == key), None)
        if m is None:
            return None
        it = self.item(m)
        cid, now = it.get("cg"), time.time()
        cache = self.__dict__.setdefault("_det", {})
        out = {"moeda": it, "contratos": [{"rede": chain_name(k), "endereco": v} for k, v in (self.addr.get(cid) or {}).items()][:8],
               "info": self.info.get(cid) or {}, "pool": self.gtpool.get(cid) or {}}
        if not cid:
            return out
        c = cache.get(("chart", cid))
        if not c or now - c[0] > 600:
            try:
                r = await self.get(f"/coins/{cid}/market_chart", {"vs_currency": "usd", "days": "30"})
                c = (now, {"precos": [[int(p[0] / 1000), p[1]] for p in (r.get("prices") or []) if p and p[1] is not None],
                           "volumes": [[int(p[0] / 1000), p[1]] for p in (r.get("total_volumes") or []) if p and p[1] is not None]})
                cache[("chart", cid)] = c
            except Exception as e:
                c = (now, {"erro": str(e)[:160]})
        tg = self.target(cid)
        # 0.32.234 (pedido do dono): o pool da DEX também quando a moeda ainda não foi lida (para o gráfico da DEX e os links)
        if tg and not (self.gtpool.get(cid) or {}).get("pool") and now - float((self.gtpool.get(cid) or {}).get("t") or 0) > 600:
            try:
                r = await self.gt_get(f"/networks/{tg[1]}/tokens/{tg[2]}/pools?page=1")
                ps = (r or {}).get("data") or []
                self.gtpool[cid] = {"net": tg[1], "pool": ((ps[0].get("attributes") or {}).get("address") if ps else None), "t": now,
                                    "nome": ((ps[0].get("attributes") or {}).get("name") if ps else None)}
                await self._put("gtpool", {"p": self.gtpool})
            except Exception:
                pass
        pool = (self.gtpool.get(cid) or {}).get("pool")
        out["pool"] = self.gtpool.get(cid) or {}
        out["alvo"] = {"rede": tg[0], "net": tg[1], "contrato": tg[2]} if tg else None
        # sem a CoinGecko (ex.: pediu para esperar), o gráfico vem do próprio pool da DEX (velas de 1 h, 30 dias)
        if "erro" in c[1] and tg and pool:
            dx = cache.get(("dexchart", cid))
            if not dx or now - dx[0] > 600:
                try:
                    r = await self.gt_get(f"/networks/{tg[1]}/pools/{pool}/ohlcv/hour?limit=720")
                    lst = sorted(((r or {}).get("data") or {}).get("attributes", {}).get("ohlcv_list") or [], key=lambda v: v[0])
                    dx = (now, {"precos": [[int(v[0]), v[4]] for v in lst if v and v[4] is not None],
                                "volumes": [[int(v[0]), v[5]] for v in lst if v and v[5] is not None], "fonte": "DEX (GeckoTerminal)",
                                "aviso": c[1]["erro"]})
                    cache[("dexchart", cid)] = dx
                except Exception as e:
                    dx = (now, {"erro": c[1]["erro"] + " · gráfico da DEX: " + str(e)[:80]})
            out["grafico"] = dx[1]
        else:
            out["grafico"] = c[1]
        if tg and pool:
            t = cache.get(("trades", cid))
            if not t or now - t[0] > 300:
                try:
                    r = await self.gt_get(f"/networks/{tg[1]}/pools/{pool}/trades")
                    lst = []
                    for x in (r or {}).get("data") or []:
                        a = x.get("attributes") or {}
                        ts = self._ts(a.get("block_timestamp"))
                        if ts:
                            lst.append({"t": ts, "kind": "compra" if a.get("kind") == "buy" else "venda", "usd": round(float(a.get("volume_in_usd") or 0), 2),
                                        "wallet": a.get("tx_from_address"), "tx": a.get("tx_hash")})
                    lst.sort(key=lambda z: -z["t"])
                    t = (now, {"lista": lst[:40], "n24": sum(1 for z in lst if z["t"] >= now - 86400), "net": tg[1]})
                    cache[("trades", cid)] = t
                except Exception as e:
                    t = (now, {"erro": str(e)[:160]})
            out["negocios"] = t[1]
        if len(cache) > 200:
            for k in sorted(cache, key=lambda k: cache[k][0])[:100]:
                del cache[k]
        return out

    def state(self) -> dict:
        moedas, cont = [], {k: 0 for k in STATUS}
        cont["morta"] = 0
        for m in self.todas():
            it = self.item(m)
            if it["status"]:
                cont[it["status"]] = cont.get(it["status"], 0) + 1
            moedas.append(it)
        return {"ligado": True, "carregado": self.loaded, "cfg": self.cfg, "padrao": CFG_DEFAULT, "nomes": STATUS,
                "grupos": grupos(moedas),
                "blockchain": {**self.gstat, "vigiadas": sum(1 for m in moedas if m.get("bc_alvo")),
                               "lidas": sum(1 for m in moedas if m.get("bc") and m["bc"].get("t")),
                               "paradas_24h": sum(1 for m in moedas if m.get("bc") and m["bc"].get("t") and not m["bc"].get("n24") and not m["bc"].get("sem_pool")),
                               "sem_pool": sum(1 for m in moedas if m.get("bc") and m["bc"].get("sem_pool")),
                               "pausa_s": max(0, round(self._gt_pause - time.time())), "a_cada_min": GT_AGAIN_S // 60},
                "status": {**self.stat, "moedas": len(self.lista) + len(self.extras), "achadas": len(self.pick), "fotos": len(self.snaps),
                           "com_info": sum(1 for c in set(self.pick.values()) if c in self.info),
                           "pausa_s": max(0, round(self._pause_until - time.time())), "proxima_s": max(0, round(self._next - time.time())),
                           "a_cada_min": EVERY_S // 60},
                "volume": {"pools": sum(1 for m in moedas if m.get("pv_t")), "dias_ok": sum(1 for m in moedas if m.get("v30d") is not None), "a_cada_min": PV_AGAIN_S // 60},
                "contagem": cont, "moedas": moedas, "alertas": self.alertas[:100]}


def grupos(moedas: list[dict]) -> dict:
    """0.32.228 (pedido do dono): as moedas por blockchain e por categoria, com a situação de cada grupo."""
    def agg(key):
        g: dict[str, dict] = {}
        for m in moedas:
            if m.get("preco") is None:
                continue
            for k in key(m):
                x = g.setdefault(k, {"nome": k, "n": 0, "st": {}, "h24": [], "d7": [], "top": None, "fundo": None})
                x["n"] += 1
                x["st"][m["status"]] = x["st"].get(m["status"], 0) + 1
                if m.get("h24") is not None and m["status"] != "parada":
                    x["h24"].append(m["h24"])
                    if x["top"] is None or m["h24"] > x["top"]["h24"]:
                        x["top"] = {"nome": m["nome"], "simbolo": m["simbolo"], "h24": m["h24"]}
                    if x["fundo"] is None or m["h24"] < x["fundo"]["h24"]:
                        x["fundo"] = {"nome": m["nome"], "simbolo": m["simbolo"], "h24": m["h24"]}
                if m.get("d7") is not None:
                    x["d7"].append(m["d7"])
        out = []
        for x in g.values():
            x["h24"] = round(statistics.median(x["h24"]), 2) if x["h24"] else None
            x["d7"] = round(statistics.median(x["d7"]), 2) if x["d7"] else None
            out.append(x)
        return sorted(out, key=lambda x: -x["n"])
    return {"blockchain": agg(lambda m: [m["chain_nome"]] if m.get("chain_nome") else ["?"]),
            "categoria": [x for x in agg(lambda m: m.get("cats") or []) if x["n"] >= 2][:40]}
