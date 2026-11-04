"""BNB · Four.Meme: histórico dos traders pela NodeReal (0.32.179, pedido do dono em 04/11/2026).

O RPC grátis do dia a dia só serve para os blocos recentes, então o ranking só via o que aconteceu desde que a leitura foi
ligada (02/11). Com a chave grátis da NodeReal (MegaNode, com dados de arquivo), o servidor busca para trás os últimos
DAYS dias:
1. fase "curva": compras e vendas da Four.Meme (TokenManager2), a moeda e a graduação de cada token novo (getTokenInfo) e o
   par da PancakeSwap dos que graduaram;
2. fase "pancake": compras e vendas nesses pares (bnbpancake.decode), no mesmo período.
Os trades entram na memória (em ordem de hora) e no banco como os do dia a dia; não disparam cópia nem mexem no que cada
trader segura agora (`hold`). A NodeReal NÃO é usada na leitura ao vivo (gastaria a cota do mês); só aqui, com limite de
chamadas por dia. A chave fica no cofre (Chaves do sistema) e nunca aparece em log, erro ou tela: o endereço dela é
"nodereal".
"""
from __future__ import annotations

import asyncio
import logging
import re
import time

from . import bnbpancake

log = logging.getLogger("bnb.hist")

URL = "https://bsc-mainnet.nodereal.io/v1/"
DAYS = 14                    # o banco guarda 14 dias (bnb_trim); 30 dias pediria ~2× o espaço
SPAN0 = 5000                 # blocos por consulta (diminui sozinho se a NodeReal recusar)
SPAN_MIN = 200
PAUSE_S = 0.25               # entre consultas
DAY_CALLS = 40_000           # limite próprio de consultas por dia
MERGE_EVERY = 20_000         # junta na memória a cada N trades
PAIRS_PER_CALL = 100
PANCAKE_MAX = 200_000        # trava de espaço no banco: para a fase da PancakeSwap depois de tantos trades
KEY_RE = re.compile(r"^[A-Za-z0-9_-]{16,80}$")


def clean_key(value: str) -> str:
    """Aceita a chave ou o endereço inteiro (https://bsc-mainnet.nodereal.io/v1/<chave>)."""
    v = (value or "").strip()
    if v.startswith("http"):
        v = v.rstrip("/").split("/")[-1]
    if not KEY_RE.match(v):
        raise ValueError("chave da NodeReal inválida: cole a API key (ou o endereço https://bsc-mainnet.nodereal.io/v1/…)")
    return v


class HistError(Exception):
    pass


class Backfill:
    def __init__(self, watch, key_fn):
        self.w, self.key_fn = watch, key_fn
        self.st = {"fase": "esperando a chave", "dias": DAYS, "de_bloco": None, "ate_bloco": None, "bloco": None,
                   "pct": 0.0, "trades_curva": 0, "trades_pancake": 0, "tokens_conferidos": 0, "pares": 0,
                   "chamadas": 0, "chamadas_hoje": 0, "erros": 0, "ultimo_erro": None, "inicio": None, "fim": None}
        self._day = int(time.time() // 86400)
        self._buf: list[dict] = []
        self._ts: dict[int, int] = {}
        self.span = SPAN0
        self._checked: set = set()

    # ------------------------------------------------------------------ RPC da NodeReal (a chave nunca sai daqui)
    async def rpc(self, method: str, params: list):
        key = self.key_fn() or ""
        if not key:
            raise HistError("sem a chave da NodeReal")
        d = int(time.time() // 86400)
        if d != self._day:
            self._day, self.st["chamadas_hoje"] = d, 0
        if self.st["chamadas_hoje"] >= DAY_CALLS:
            raise HistError(f"limite próprio de {DAY_CALLS} consultas por dia; continua amanhã")
        self.st["chamadas"] += 1
        self.st["chamadas_hoje"] += 1
        try:
            r = await self.w.http.post(URL + key, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                                       timeout=30)
            js = r.json()
        except Exception as e:
            raise HistError(f"nodereal: {type(e).__name__}") from None
        if js.get("error"):
            msg = str(js["error"].get("message") or js["error"])[:160].replace(key, "…")
            raise HistError("nodereal: " + msg)
        return js.get("result")

    async def call(self, to: str, data: str) -> str:
        return await self.rpc("eth_call", [{"to": to, "data": data}, "latest"]) or "0x"

    async def block_ts(self, n: int) -> int:
        if n not in self._ts:
            b = await self.rpc("eth_getBlockByNumber", [hex(n), False])
            self._ts[n] = int(b["timestamp"], 16) if b else 0
            if len(self._ts) > 5000:
                self._ts.clear()
        return self._ts[n]

    async def _logs(self, flt: dict, a: int, b: int) -> list[dict]:
        """eth_getLogs no trecho [a, b]; se a NodeReal recusar por tamanho, divide o trecho."""
        try:
            return await self.rpc("eth_getLogs", [{**flt, "fromBlock": hex(a), "toBlock": hex(b)}]) or []
        except HistError as e:
            low = str(e).lower()
            if b > a and any(x in low for x in ("range", "limit", "exceed", "too many", "too large", "10000")):
                self.span = max(SPAN_MIN, self.span // 2)
                m = (a + b) // 2
                return await self._logs(flt, a, m) + await self._logs(flt, m + 1, b)
            raise

    # ------------------------------------------------------------------ estado guardado (bnb_state k = "hist")
    def dump(self) -> dict:
        return {k: self.st[k] for k in ("fase", "dias", "de_bloco", "ate_bloco", "bloco", "trades_curva", "trades_pancake",
                                         "tokens_conferidos", "inicio", "fim")}

    def restore(self, v: dict) -> None:
        if isinstance(v, dict):
            self.st.update({k: v.get(k) for k in self.dump() if k in v})

    async def save(self) -> None:
        if self.w.db is not None:
            try:
                await self.w.db.insert("bnb_state", {"k": "hist", "v": self.dump()}, upsert=True, on_conflict="k")
            except Exception as e:
                log.warning("BNB histórico: não gravou o progresso: %s", str(e)[:120])

    # ------------------------------------------------------------------ trabalho
    def _merge(self) -> None:
        if self._buf:
            self.w.add_old(self._buf)
            self._buf = []

    def _keep(self, tr: dict) -> None:
        if tr["id"] not in self.w.seen:
            self._buf.append(tr)
            if len(self._buf) >= MERGE_EVERY:
                self._merge()

    async def _time(self, trs: list[dict], a: int, b: int) -> None:
        ta, tb = await self.block_ts(a), await self.block_ts(b)
        bs = (tb - ta) / (b - a) if b > a and tb > ta else self.w.block_s
        for t in trs:
            t["t"] = round(ta + (t["block"] - a) * bs, 1)

    async def _token(self, tk: str) -> None:
        """Moeda e graduação de um token visto no histórico; se graduou, o par da PancakeSwap."""
        w = self.w
        if tk not in self._checked and tk not in w.graduated:      # moeda e graduação: uma vez por token no histórico
            self._checked.add(tk)
            await w.token_info(tk, call=self.call)
            self.st["tokens_conferidos"] += 1
        if tk in w.graduated and tk not in w.pairs:
            pair = await bnbpancake.find_pair(self.call, tk, w.quotes.get(tk) or bnbpancake.ZERO)
            if pair:
                w.pairs[tk] = {**bnbpancake.pair_info(tk, w.quotes.get(tk) or bnbpancake.ZERO, pair), "t": None}
                w._pairs_dirty = True

    async def setup(self) -> bool:
        """Primeira vez: do bloco mais antigo que a leitura já tem até DAYS dias atrás."""
        if self.st.get("de_bloco"):
            return True
        head = int(await self.rpc("eth_blockNumber", []), 16)
        back = 200_000
        th, tp = await self.block_ts(head), await self.block_ts(head - back)
        bs = (th - tp) / back if th > tp else self.w.block_s
        first = min((t["block"] for t in self.w.trades if t.get("block")), default=None) or self.w.cursor or head
        self.st.update(de_bloco=max(1, int(head - DAYS * 86400 / bs)), ate_bloco=int(first) - 1, bloco=int(first) - 1,
                       fase="curva", inicio=time.time())
        await self.save()
        return True

    async def step(self) -> bool:
        """Um trecho de blocos. Devolve False quando não há nada a fazer."""
        st = self.st
        if st["fase"] not in ("curva", "pancake"):
            return False
        lo_end, hi = st["de_bloco"], st["bloco"]
        if hi < lo_end:
            self._merge()
            if st["fase"] == "curva":
                st.update(fase="pancake", bloco=st["ate_bloco"])
            else:
                st.update(fase="pronto", fim=time.time(), pct=100.0)
            await self.save()
            return st["fase"] != "pronto"
        if st["fase"] == "pancake" and st["trades_pancake"] >= PANCAKE_MAX:
            st["bloco"] = lo_end - 1                                # chegou na trava: encerra
            st["ultimo_erro"] = f"parou a PancakeSwap em {PANCAKE_MAX} trades (espaço no banco)"
            return True
        a = max(lo_end, hi - self.span + 1)
        if st["fase"] == "curva":
            from . import bnb as B                                 # import aqui: bnb.py importa este módulo
            logs = await self._logs({"address": B.TM2, "topics": [[B.T_BUY, B.T_SELL]]}, a, hi)
            trs = [t for t in (B.decode(lg) for lg in logs) if t]
            if trs:
                await self._time(trs, a, hi)
            for tk in {t["token"] for t in trs}:
                try:
                    await self._token(tk)
                except Exception:
                    pass                                         # fica sem moeda: o ranking deixa de fora
            for t in trs:
                t["quote"] = self.w.quotes.get(t["token"])
                self._keep(t)
            st["trades_curva"] += len(trs)
        else:
            pairs = {p["pair"]: p for p in self.w.pairs.values()}
            st["pares"] = len(pairs)
            keys = list(pairs)
            for i in range(0, len(keys), PAIRS_PER_CALL):
                grp = {k: pairs[k] for k in keys[i:i + PAIRS_PER_CALL]}
                pt = [bnbpancake.topic_addr(x) for x in grp]
                toks = list({p["token"] for p in grp.values()})
                swaps = await self._logs({"address": list(grp), "topics": [bnbpancake.T_SWAP]}, a, hi)
                if not swaps:
                    continue
                tin = await self._logs({"address": toks, "topics": [bnbpancake.T_TRANSFER, None, pt]}, a, hi)
                tout = await self._logs({"address": toks, "topics": [bnbpancake.T_TRANSFER, pt]}, a, hi)
                trs = bnbpancake.decode(swaps, tin + tout, grp)
                if trs:
                    await self._time(trs, a, hi)
                for t in trs:
                    self._keep(t)
                st["trades_pancake"] += len(trs)
        st["bloco"] = a - 1
        tot = max(1, st["ate_bloco"] - lo_end + 1)
        done = st["ate_bloco"] - st["bloco"]
        st["pct"] = round((50 if st["fase"] == "pancake" else 0) + 50 * min(1.0, done / tot), 1)
        if self.span < SPAN0:
            self.span = min(SPAN0, self.span * 2)
        return True

    async def run(self) -> None:
        while not self.w.loaded:
            await asyncio.sleep(5)
        n = 0
        while True:
            try:
                if not self.key_fn():
                    if not self.st.get("de_bloco"):
                        self.st["fase"] = "esperando a chave"
                    await asyncio.sleep(30)
                    continue
                await self.setup()
                if not await self.step():
                    await asyncio.sleep(600)
                    continue
                n += 1
                if n % 20 == 0:
                    self._merge()
                    await self.save()
                await asyncio.sleep(PAUSE_S)
            except asyncio.CancelledError:
                raise
            except HistError as e:
                self.st["erros"] += 1
                self.st["ultimo_erro"] = str(e)[:160]
                await asyncio.sleep(60 if "limite próprio" not in str(e) else 3600)
            except Exception as e:
                self.st["erros"] += 1
                self.st["ultimo_erro"] = type(e).__name__
                await asyncio.sleep(30)

    def status(self) -> dict:
        return {**self.st, "chave": bool(self.key_fn()), "na_memoria": len(self._buf), "limite_dia": DAY_CALLS}
