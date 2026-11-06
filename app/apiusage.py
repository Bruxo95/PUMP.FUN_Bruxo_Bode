"""Medidor de uso das APIs externas (0.31.76, pedido do dono em 2026-10-27).

Conta cada chamada HTTP que o servidor faz (gancho de requisição do httpx em app/main.py), por API e, na Solana Tracker,
por chave (só um apelido feito com hash — a chave nunca é guardada nem mostrada). Guarda o total do mês e o pico por
minuto do dia, para mostrar o quanto do limite grátis de cada API está sendo usado.

Limites do plano grátis (conferidos nas páginas oficiais em 27/10/2026; o resto é marcado "não confirmado"):
- Solana Tracker Data API: 10.000 consultas/mês, 3 por segundo (docs.solanatracker.io/pricing).
- DexScreener: 300 por minuto nos endpoints de pares/tokens (docs.dexscreener.com/api/reference).
- RPC público da Solana: 100 por 10 s por IP (= 600/min) (solana.com/docs/references/clusters).
- Jupiter (sem chave paga): limite por minuto — não confirmado; PumpPortal: sem limite publicado para o trade-local.
- Helius, plano grátis (helius.dev/pricing, conferido em 04/11/2026): 1 milhão de CRÉDITOS por mês e 10 requisições por
  segundo; chamada comum = 1 crédito, getProgramAccounts = 10. Mensagem de WebSocket: preço não publicado (só contamos).

0.32.185 (pedido do dono): quanto cada serviço usou em 1, 6, 12 e 24 h, desde o início e no mês, também as mensagens
das conexões ao vivo (WebSocket do RPC da Solana e da PumpPortal), em `windows`.
"""
from __future__ import annotations

import contextvars
import hashlib
import time
from collections import deque
from datetime import datetime, timezone

APIS = [  # (host termina com, nome, limite mensal, limite por minuto)
    ("helius-rpc.com", "Helius (RPC da Solana)", 1_000_000, 600),     # limite mensal em CRÉDITOS (ver CREDITS)
    ("solanatracker.io", "Solana Tracker", 10_000, 180),
    ("dexscreener.com", "DexScreener", None, 300),
    ("api.mainnet-beta.solana.com", "RPC público da Solana", None, 600),
    ("jup.ag", "Jupiter", None, None),
    ("pumpportal.fun", "PumpPortal", None, None),
    ("coingecko.com", "CoinGecko", 10_000, 100),                       # 0.32.227: Dormant (plano Demo grátis)
    ("geckoterminal.com", "GeckoTerminal", None, 30),                   # 0.32.229: Dormant, últimas ações na blockchain
]
SKIP = ("supabase.co", "supabase.in", "api.telegram.org", "github.com")
MORE = [("publicnode.com", "RPC da BNB (publicnode)"), ("blockrazor.xyz", "RPC da BNB (blockrazor)"),
        ("nodereal.io", "NodeReal (BNB)"), ("typesafe.ai", "Jev (TypeSafe)"), ("gopluslabs.io", "GoPlus (segurança BNB)")]
CREDITS = {"Helius (RPC da Solana)": {"getProgramAccounts": 10}}      # o resto = 1 crédito por chamada
CRED = " · créditos"                                                   # sufixo da linha de créditos no mês (guardada no banco)
H_WIN = (1, 6, 12, 24)
# 0.32.188 (pedido do dono: "quanto gasta cada aba"): cada laço do servidor nasce marcado com a aba que ele serve
# (hub.bg e monitor.start); o pedido HTTP feito dentro dele herda a marca. Sem marca = clique numa tela do painel.
ORIGIN: contextvars.ContextVar = contextvars.ContextVar("pf_origem", default=None)
SEM_ORIGEM = "Telas do painel (cliques)"
# 0.32.189 (pedido do dono: "a BNB não tem nada a ver, foca só neste projeto"): o painel /bnb é outro projeto; o que ele pede
# não entra no uso do PUMP FUN COPY, e as linhas só dele (RPC da BNB, NodeReal, GoPlus) não aparecem.
BNB_ORIGEM = "BNB (Four.Meme)"
BNB_APIS = {"RPC da BNB (publicnode)", "RPC da BNB (blockrazor)", "NodeReal (BNB)", "GoPlus (segurança BNB)"}
# 0.32.208: a Robinhood Chain também é outro projeto: o que o laço dela pede não entra no uso do PUMP FUN COPY
HOOD_ORIGEM = "Robinhood Chain"
OUTROS = frozenset({BNB_ORIGEM, HOOD_ORIGEM})


# 0.32.220 (pedido do dono: "quantas requisições essa posição gasta e de qual API"): o pedido feito para um grupo de
# moedas (preço da curva, DexScreener, Jupiter, compra e venda REAL) é dividido igualmente entre elas. Ex.: 1 consulta da
# curva para 40 moedas = 1/40 para cada. Só na memória: zera quando o servidor reinicia (BOOT muda).
MINTS: contextvars.ContextVar = contextvars.ContextVar("pf_mints", default=None)
MINT_USE: dict[str, dict] = {}                       # moeda -> {"t": último uso, "u": {(api, tipo): n}}
BOOT = int(time.time())
MINT_MAX = 6000


def _mint_add(api: str, tipo: str, n: float, now: float) -> None:
    ms = MINTS.get()
    if not ms:
        return
    share = n / len(ms)
    for m in ms:
        d = MINT_USE.get(m)
        if d is None:
            if len(MINT_USE) >= MINT_MAX:              # tira as que não foram usadas há mais tempo
                for old in sorted(MINT_USE, key=lambda k: MINT_USE[k]["t"])[:MINT_MAX // 5]:
                    del MINT_USE[old]
            d = MINT_USE[m] = {"t": now, "u": {}}
        d["t"] = now
        k = api + "|" + tipo
        d["u"][k] = d["u"].get(k, 0.0) + share


def mint_snapshot(mint: str) -> dict:
    return dict((MINT_USE.get(mint) or {}).get("u") or {})


def mint_used(mint: str, base: dict | None, base_boot: int | None) -> dict:
    """Gasto desta moeda desde `base` (foto tirada quando a posição abriu). Se o servidor reiniciou depois, conta só
    desde o reinício e marca `parcial`. Devolve {"apis": [{api, requisicoes, creditos}], "parcial": bool}."""
    now = mint_snapshot(mint)
    parcial = bool(base_boot) and base_boot != BOOT
    b = {} if parcial else (base or {})
    by: dict[str, dict] = {}
    for k, v in now.items():
        api, tipo = k.split("|", 1)
        x = max(0.0, v - float(b.get(k) or 0))
        if x <= 0:
            continue
        r = by.setdefault(api, {"api": api, "requisicoes": 0.0, "creditos": 0.0})
        r["requisicoes" if tipo == "requisições" else "creditos"] += x
    out = sorted(by.values(), key=lambda r: -r["requisicoes"])
    for r in out:
        r["requisicoes"], r["creditos"] = round(r["requisicoes"], 2), round(r["creditos"], 2)
    return {"apis": out, "parcial": parcial or base is None}


def for_mints(mints, coro):
    """Roda `coro` com o gasto das APIs dividido entre `mints`."""
    async def run():
        tok = MINTS.set(tuple(dict.fromkeys(m for m in mints if m)) or None)
        try:
            return await coro
        finally:
            MINTS.reset(tok)
    return run()


def run_as(nome: str, coro):
    """Tarefa em segundo plano com a marca da aba (os pedidos dela contam para essa aba)."""
    import asyncio
    ctx = contextvars.copy_context()
    ctx.run(ORIGIN.set, nome)
    return asyncio.get_running_loop().create_task(coro, context=ctx)


PP_PAID = "trades das copiadas"                                        # PumpPortal: 0,01 SOL a cada 10 mil mensagens destas


def key_tag(key: str | None) -> str | None:
    return hashlib.sha256(key.encode()).hexdigest()[:8] if key else None


def classify(host: str) -> str | None:
    host = (host or "").lower()
    if any(host.endswith(s) for s in SKIP):
        return None
    for suf, nome, _m, _r in APIS:
        if host.endswith(suf):
            return nome
    for suf, nome in MORE:
        if host.endswith(suf):
            return nome
    return "RPC próprio / outros (" + host + ")"


def credits_of(api: str, body: bytes | str | None) -> int:
    """Créditos de uma chamada JSON-RPC (lote = soma). Sem tabela para a API: 0 (não conta créditos)."""
    tab = CREDITS.get(api)
    if tab is None:
        return 0
    try:
        import json
        js = json.loads(body or b"{}")
    except Exception:
        return 1
    calls = js if isinstance(js, list) else [js]
    return sum(tab.get((c or {}).get("method"), 1) for c in calls) or 1


class Usage:
    def __init__(self):
        self.month: dict[tuple, int] = {}           # (mes, api, chave) -> chamadas
        self.recent: dict[str, deque] = {}           # api -> horários do último minuto
        self.peak: dict[tuple, int] = {}             # (dia, api) -> pico por minuto
        self.dirty = False
        self.started = time.time()
        self.win: dict[tuple, dict] = {}             # (api, tipo) -> {minuto: n} das últimas 24 h
        self.total: dict[tuple, int] = {}            # (api, tipo) -> desde que o servidor subiu
        self.owin: dict[tuple, dict] = {}            # (aba, api, tipo) -> {minuto: n} das últimas 24 h (0.32.188)
        self.ototal: dict[tuple, int] = {}
        self.st_tags = None                          # 0.32.237: função → marcas das chaves da Solana Tracker em uso

    def _tick(self, api: str, tipo: str, n: int, now: float) -> None:
        if ORIGIN.get() in OUTROS:
            return
        k = (api, tipo)
        b = self.win.setdefault(k, {})
        m = int(now // 60)
        b[m] = b.get(m, 0) + n
        if len(b) > 1450:
            for old in [x for x in b if x <= m - 1440]:
                del b[old]
        self.total[k] = self.total.get(k, 0) + n
        o = (ORIGIN.get() or SEM_ORIGEM, api, tipo)
        ob = self.owin.setdefault(o, {})
        ob[m] = ob.get(m, 0) + n
        if len(ob) > 1450:
            for old in [x for x in ob if x <= m - 1440]:
                del ob[old]
        self.ototal[o] = self.ototal.get(o, 0) + n
        _mint_add(api, tipo, n, now)

    def ws(self, api: str, tipo: str, n: int = 1, now: float | None = None) -> None:
        """Mensagem de uma conexão ao vivo (WebSocket). Nunca falha."""
        try:
            self._tick(api, tipo, n, time.time() if now is None else now)
        except Exception:
            pass

    def count(self, host: str, key: str | None = None, now: float | None = None, body=None) -> None:
        api = classify(host)
        if api is None or ORIGIN.get() in OUTROS:
            return
        now = time.time() if now is None else now
        self._tick(api, "requisições", 1, now)
        cr = credits_of(api, body)
        if cr:
            self._tick(api, "créditos", cr, now)
            ck = (datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m"), api + CRED, None)
            self.month[ck] = self.month.get(ck, 0) + cr
        d = datetime.fromtimestamp(now, timezone.utc)
        k = (d.strftime("%Y-%m"), api, key_tag(key) if api == "Solana Tracker" else None)
        if api in BNB_APIS:
            return
        self.month[k] = self.month.get(k, 0) + 1
        q = self.recent.setdefault(api, deque())
        q.append(now)
        while q and now - q[0] > 60:
            q.popleft()
        pk = (d.strftime("%Y-%m-%d"), api)
        self.peak[pk] = max(self.peak.get(pk, 0), len(q))
        self.dirty = True

    async def hook(self, request) -> None:
        """Gancho do httpx: conta a requisição (nunca bloqueia nem falha a chamada)."""
        try:
            host = request.url.host
            body = request.content if any(host.endswith(s) for s in ("helius-rpc.com",)) else None
            self.count(host, request.headers.get("x-api-key"), body=body)
        except Exception:
            pass

    async def resp_hook(self, response) -> None:
        """0.32.71: resposta "Insufficient credits" da Solana Tracker deixa aquela chave de fora por 1 h (todas as partes
        do robô passam a usar a próxima). Nunca falha a chamada."""
        try:
            if "solanatracker" not in response.request.url.host or response.status_code < 400:
                return
            await response.aread()
            from . import stkeys
            if stkeys.no_credits(response.text):
                stkeys.mark_dead(response.request.headers.get("x-api-key") or "")
        except Exception:
            pass

    def view(self, labels: dict | None = None, now: float | None = None) -> list[dict]:
        """Uma linha por API (e por chave na Solana Tracker), com % do limite grátis do mês e do minuto."""
        now = time.time() if now is None else now
        d = datetime.fromtimestamp(now, timezone.utc)
        mes, dia = d.strftime("%Y-%m"), d.strftime("%Y-%m-%d")
        days_in = (datetime(d.year + (d.month == 12), d.month % 12 + 1, 1, tzinfo=timezone.utc)
                   - datetime(d.year, d.month, 1, tzinfo=timezone.utc)).days
        frac = (d.day - 1 + d.hour / 24) / days_in or 1 / days_in
        out = []
        lim = {nome: (m, r) for _s, nome, m, r in APIS}
        for (m, api, chave), n in sorted(self.month.items(), key=lambda kv: (kv[0][1], -kv[1])):
            if m != mes or api.endswith(CRED):
                continue
            mm, rr = lim.get(api, (None, None))
            proj = round(n / frac) if frac else n
            pk = self.peak.get((dia, api), 0)
            out.append({"api": api, "chave": (labels or {}).get(chave) or (f"chave {chave}" if chave else None),
                        "mes": n, "limite_mes": mm, "pct_mes": round(n / mm * 100, 1) if mm else None,
                        "projecao_mes": proj, "pct_projecao": round(proj / mm * 100, 1) if mm else None,
                        "pico_min": pk, "limite_min": rr, "pct_min": round(pk / rr * 100, 1) if rr else None,
                        "ultimo_min": len(self.recent.get(api) or [])})
        return out

    def windows(self, now: float | None = None) -> list[dict]:
        """0.32.185: uma linha por serviço e tipo (requisições, créditos, mensagens ao vivo) com 1/6/12/24 h, desde o início
        e no mês. % = parte do limite do mês (quando há limite mensal) ou uso médio do limite por minuto no período."""
        now = time.time() if now is None else now
        m_now = int(now // 60)
        mes = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m")
        lim = {nome: (mm, rr) for _s, nome, mm, rr in APIS}
        up_min = max(1.0, (now - self.started) / 60)
        out = []
        for k in self.SERVICOS:
            self.win.setdefault(k, {})
        for (api, tipo), b in sorted(self.win.items()):
            if api in BNB_APIS:
                continue
            mm, rr = lim.get(api, (None, None))
            if tipo == "requisições" and api in CREDITS:
                mm = None                                # no Helius o limite do mês é em créditos (linha própria)
            if tipo not in ("requisições", "créditos"):
                mm = rr = None                           # mensagens de WebSocket: sem limite publicado
            per = {}
            # 0.32.235: as janelas voltam do banco depois do reinício (load_win); dividir pelo tempo desde o reinício dava
            # 172% em 24 h com uso real de 51%. A média por minuto usa os minutos que a janela realmente cobre.
            first = min((k for k, v in b.items() if v), default=m_now)
            cob = max(1.0, m_now - first + 1, min(up_min, 24 * 60))
            for h in H_WIN:
                n = sum(v for k, v in b.items() if k > m_now - h * 60)
                if mm:
                    pct = round(n / mm * 100, 3)
                elif rr:
                    pct = round(n / (min(h * 60, cob) * rr) * 100, 2)
                else:
                    pct = None
                per[str(h)] = {"n": n, "pct": pct}
            minimo = False
            if tipo == "créditos":
                # 0.32.187: antes de 04/11 os créditos não eram separados; cada requisição gasta pelo menos 1 crédito
                cred = self.month.get((mes, api + CRED, None)) or 0
                req = sum(n for (m, a, _c), n in self.month.items() if m == mes and a == api)
                mes_n, minimo = max(cred, req) or None, req > cred
            elif tipo == "requisições" and api == "Solana Tracker" and self.st_tags is not None:
                # 0.32.237 (dono: "troquei a chave da Solana Tracker e continua estourou"): o limite de 10 mil é POR CHAVE.
                # O mês mostra a chave em uso que mais gastou; chave trocada/removida deixa de contar.
                try:
                    tags = set(self.st_tags())
                except Exception:
                    tags = set()
                por = {c: n for (m, a, c), n in self.month.items() if m == mes and a == api and c in tags}
                mes_n = max(por.values(), default=0) or None
            elif tipo == "requisições":
                mes_n = sum(n for (m, a, _c), n in self.month.items() if m == mes and a == api) or None
            else:
                mes_n = None
            row = {"api": api, "tipo": tipo, "janelas": per, "desde_inicio": self.total.get((api, tipo), 0),
                   "mes": mes_n, "limite_mes": mm, "limite_min": rr,
                   "pct_mes": round(mes_n / mm * 100, 3) if mm and mes_n else None, "mes_minimo": minimo}
            if api == "PumpPortal" and tipo == PP_PAID:
                row["custo_sol"] = {h: round(per[h]["n"] / 10_000 * 0.01, 5) for h in per}
            out.append(row)
        return out

    def zerar(self, api: str, chave: str | None = None) -> None:
        """0.32.236 (pedido do dono: "quando troco as chaves, zerar a contagem de uso"): apaga a contagem daquela API (mês,
        créditos, janelas de 1–24 h, desde o início, por aba e picos). Com `chave` (Solana Tracker), só o mês daquela chave."""
        tag = key_tag(chave) if chave else None
        for k in list(self.month):
            if k[1] in (api, api + CRED) and (tag is None or k[2] == tag):
                self.month[k] = 0
        if True:                                     # 0.32.237: as janelas de 1–24 h também recomeçam
            for d in (self.win, self.total):
                for k in [k for k in d if k[0] == api]:
                    d.pop(k, None)
            for d in (self.owin, self.ototal):
                for k in [k for k in d if k[1] == api]:
                    d.pop(k, None)
            for k in [k for k in self.peak if k[1] == api]:
                self.peak.pop(k, None)
            self.recent.pop(api, None)
        self.dirty = True

    def estourou(self, now: float | None = None) -> dict:
        """0.32.235 (pedido do dono: "o RPC estourou e o status ficou ok"): serviços que passaram do limite grátis, pelo mesmo
        cálculo da tabela "Uso de cada serviço": {api: {"tipo", "pct", "mes", "limite_mes"}} com a pior % de cada um."""
        out: dict[str, dict] = {}
        for r in self.windows(now):
            if not (r.get("limite_mes") or r.get("limite_min")):
                continue
            pior = max([r.get("pct_mes") or 0] + [(r["janelas"].get(h) or {}).get("pct") or 0 for h in ("1", "6", "12", "24")])
            if pior >= 100 and pior > (out.get(r["api"]) or {}).get("pct", 0):
                out[r["api"]] = {"tipo": r["tipo"], "pct": round(pior, 1), "mes": r.get("mes"), "limite_mes": r.get("limite_mes"),
                                 "limite_min": r.get("limite_min")}
        return out

    def por_aba(self, now: float | None = None) -> list[dict]:
        """0.32.188: quanto cada aba (laço do servidor) gastou de cada serviço em 1/6/12/24 h e desde o início."""
        now = time.time() if now is None else now
        m_now = int(now // 60)
        g: dict[str, list] = {}
        for (o, api, tipo), b in self.owin.items():
            if o in OUTROS or api in BNB_APIS:
                continue
            per = {str(h): sum(v for k, v in b.items() if k > m_now - h * 60) for h in H_WIN}
            g.setdefault(o, []).append({"api": api, "tipo": tipo, "janelas": per, "desde_inicio": self.ototal.get((o, api, tipo), 0)})
        out = []
        for o, L in g.items():
            L.sort(key=lambda x: (-x["janelas"]["24"], x["api"], x["tipo"]))
            req = {h: sum(x["janelas"][h] for x in L if x["tipo"] in ("requisições", "trades das copiadas") or x["tipo"].startswith("WebSocket")) for h in ("1", "6", "12", "24")}
            out.append({"aba": o, "servicos": L, "total": req})
        return sorted(out, key=lambda x: -x["total"]["24"])

    # 0.32.190 (pedido do dono): as janelas de 24 h sobrevivem à atualização do sistema (blocos de 10 min no banco)
    SERVICOS = (("Helius (RPC da Solana)", "requisições"), ("Helius (RPC da Solana)", "créditos"), ("Solana Tracker", "requisições"),
                ("DexScreener", "requisições"), ("Jupiter", "requisições"), ("PumpPortal", "requisições"),
                ("Helius (RPC da Solana)", "WebSocket: mensagens recebidas"), ("PumpPortal", "WebSocket: tokens novos e outros"),
                ("PumpPortal", PP_PAID))

    def dump_win(self, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        lim = int(now // 60) - 1440

        def pack(b):
            out: dict[str, int] = {}
            for m, n in b.items():
                if m > lim:
                    k = str(m // 10 * 10)
                    out[k] = out.get(k, 0) + n
            return out
        return {"win": {f"{api}|{tipo}": pack(b) for (api, tipo), b in self.win.items()},
                "owin": {f"{o}|{api}|{tipo}": pack(b) for (o, api, tipo), b in self.owin.items()}}

    def load_win(self, d: dict | None, now: float | None = None) -> None:
        now = time.time() if now is None else now
        lim = int(now // 60) - 1440
        for k, b in ((d or {}).get("win") or {}).items():
            api, _, tipo = k.partition("|")
            t = self.win.setdefault((api, tipo), {})
            for m, n in (b or {}).items():
                if int(m) > lim:
                    t[int(m)] = t.get(int(m), 0) + int(n)
        for k, b in ((d or {}).get("owin") or {}).items():
            parts = k.split("|")
            if len(parts) != 3:
                continue
            t = self.owin.setdefault(tuple(parts), {})
            for m, n in (b or {}).items():
                if int(m) > lim:
                    t[int(m)] = t.get(int(m), 0) + int(n)

    def dump(self) -> list[dict]:
        return [{"mes": m, "api": a, "chave": c or "", "n": n} for (m, a, c), n in self.month.items()]

    def load(self, rows: list[dict]) -> None:
        for r in rows or []:
            api = r.get("api") or ""
            if api.startswith("RPC próprio / outros (") and api.endswith(")"):
                api = classify(api[len("RPC próprio / outros ("):-1]) or api   # 0.32.185: nomes novos (Helius, BNB…)
            k = (r.get("mes"), api, r.get("chave") or None)
            self.month[k] = max(self.month.get(k, 0), int(r.get("n") or 0))
