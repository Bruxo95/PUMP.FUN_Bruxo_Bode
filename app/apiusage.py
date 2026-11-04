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
]
SKIP = ("supabase.co", "supabase.in", "api.telegram.org", "github.com")
MORE = [("publicnode.com", "RPC da BNB (publicnode)"), ("blockrazor.xyz", "RPC da BNB (blockrazor)"),
        ("nodereal.io", "NodeReal (BNB)"), ("typesafe.ai", "Jev (TypeSafe)"), ("gopluslabs.io", "GoPlus (segurança BNB)")]
CREDITS = {"Helius (RPC da Solana)": {"getProgramAccounts": 10}}      # o resto = 1 crédito por chamada
CRED = " · créditos"                                                   # sufixo da linha de créditos no mês (guardada no banco)
H_WIN = (1, 6, 12, 24)
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

    def _tick(self, api: str, tipo: str, n: int, now: float) -> None:
        k = (api, tipo)
        b = self.win.setdefault(k, {})
        m = int(now // 60)
        b[m] = b.get(m, 0) + n
        if len(b) > 1450:
            for old in [x for x in b if x <= m - 1440]:
                del b[old]
        self.total[k] = self.total.get(k, 0) + n

    def ws(self, api: str, tipo: str, n: int = 1, now: float | None = None) -> None:
        """Mensagem de uma conexão ao vivo (WebSocket). Nunca falha."""
        try:
            self._tick(api, tipo, n, time.time() if now is None else now)
        except Exception:
            pass

    def count(self, host: str, key: str | None = None, now: float | None = None, body=None) -> None:
        api = classify(host)
        if api is None:
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
        for (api, tipo), b in sorted(self.win.items()):
            mm, rr = lim.get(api, (None, None))
            if tipo == "requisições" and api in CREDITS:
                mm = None                                # no Helius o limite do mês é em créditos (linha própria)
            if tipo not in ("requisições", "créditos"):
                mm = rr = None                           # mensagens de WebSocket: sem limite publicado
            per = {}
            for h in H_WIN:
                n = sum(v for k, v in b.items() if k > m_now - h * 60)
                if mm:
                    pct = round(n / mm * 100, 3)
                elif rr:
                    pct = round(n / (min(h * 60, up_min) * rr) * 100, 2)
                else:
                    pct = None
                per[str(h)] = {"n": n, "pct": pct}
            if tipo == "créditos":
                mes_n = self.month.get((mes, api + CRED, None))
            elif tipo == "requisições":
                mes_n = sum(n for (m, a, _c), n in self.month.items() if m == mes and a == api) or None
            else:
                mes_n = None
            row = {"api": api, "tipo": tipo, "janelas": per, "desde_inicio": self.total.get((api, tipo), 0),
                   "mes": mes_n, "limite_mes": mm, "limite_min": rr,
                   "pct_mes": round(mes_n / mm * 100, 3) if mm and mes_n else None}
            if api == "PumpPortal" and tipo == PP_PAID:
                row["custo_sol"] = {h: round(per[h]["n"] / 10_000 * 0.01, 5) for h in per}
            out.append(row)
        return out

    def dump(self) -> list[dict]:
        return [{"mes": m, "api": a, "chave": c or "", "n": n} for (m, a, c), n in self.month.items()]

    def load(self, rows: list[dict]) -> None:
        for r in rows or []:
            api = r.get("api") or ""
            if api.startswith("RPC próprio / outros (") and api.endswith(")"):
                api = classify(api[len("RPC próprio / outros ("):-1]) or api   # 0.32.185: nomes novos (Helius, BNB…)
            k = (r.get("mes"), api, r.get("chave") or None)
            self.month[k] = max(self.month.get(k, 0), int(r.get("n") or 0))
