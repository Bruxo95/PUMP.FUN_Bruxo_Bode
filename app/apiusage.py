"""Medidor de uso das APIs externas (0.31.76, pedido do dono em 2026-10-27).

Conta cada chamada HTTP que o servidor faz (gancho de requisição do httpx em app/main.py), por API e, na Solana Tracker,
por chave (só um apelido feito com hash — a chave nunca é guardada nem mostrada). Guarda o total do mês e o pico por
minuto do dia, para mostrar o quanto do limite grátis de cada API está sendo usado.

Limites do plano grátis (conferidos nas páginas oficiais em 27/10/2026; o resto é marcado "não confirmado"):
- Solana Tracker Data API: 10.000 consultas/mês, 3 por segundo (docs.solanatracker.io/pricing).
- DexScreener: 300 por minuto nos endpoints de pares/tokens (docs.dexscreener.com/api/reference).
- RPC público da Solana: 100 por 10 s por IP (= 600/min) (solana.com/docs/references/clusters).
- Jupiter (sem chave paga): limite por minuto — não confirmado; PumpPortal: sem limite publicado para o trade-local.
"""
from __future__ import annotations

import hashlib
import time
from collections import deque
from datetime import datetime, timezone

APIS = [  # (host termina com, nome, limite mensal, limite por minuto)
    ("solanatracker.io", "Solana Tracker", 10_000, 180),
    ("dexscreener.com", "DexScreener", None, 300),
    ("api.mainnet-beta.solana.com", "RPC público da Solana", None, 600),
    ("jup.ag", "Jupiter", None, None),
    ("pumpportal.fun", "PumpPortal", None, None),
]
SKIP = ("supabase.co", "supabase.in", "api.telegram.org", "github.com")


def key_tag(key: str | None) -> str | None:
    return hashlib.sha256(key.encode()).hexdigest()[:8] if key else None


def classify(host: str) -> str | None:
    host = (host or "").lower()
    if any(host.endswith(s) for s in SKIP):
        return None
    for suf, nome, _m, _r in APIS:
        if host.endswith(suf):
            return nome
    return "RPC próprio / outros (" + host + ")"


class Usage:
    def __init__(self):
        self.month: dict[tuple, int] = {}           # (mes, api, chave) -> chamadas
        self.recent: dict[str, deque] = {}           # api -> horários do último minuto
        self.peak: dict[tuple, int] = {}             # (dia, api) -> pico por minuto
        self.dirty = False

    def count(self, host: str, key: str | None = None, now: float | None = None) -> None:
        api = classify(host)
        if api is None:
            return
        now = time.time() if now is None else now
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
            self.count(request.url.host, request.headers.get("x-api-key"))
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
            if m != mes:
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

    def dump(self) -> list[dict]:
        return [{"mes": m, "api": a, "chave": c or "", "n": n} for (m, a, c), n in self.month.items()]

    def load(self, rows: list[dict]) -> None:
        for r in rows or []:
            k = (r.get("mes"), r.get("api"), r.get("chave") or None)
            self.month[k] = max(self.month.get(k, 0), int(r.get("n") or 0))
