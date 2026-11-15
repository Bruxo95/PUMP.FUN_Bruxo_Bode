"""0.32.370 (pedido do dono, 15/11/2026): conector do cTrader para o Projeto Forex (docs/FOREX.md, etapa 2).

O que faz
- O admin cadastra um aplicativo grátis em openapi.ctrader.com e cola o Client ID e o Client Secret no /forex (ficam no cofre,
  user_secrets, criptografados). "Conectar conta cTrader" abre o login da cTrader (OAuth2, escopo "accounts" = só leitura):
  nenhuma senha passa por aqui e nada consegue mandar ordem. O retorno grava o token, também no cofre.
- Para cada conta autorizada (real ou demo) abre o WebSocket JSON oficial (live/demo.ctraderapi.com:5036), lê o saldo, os
  ativos, as posições abertas e o histórico de negócios (até HIST_DIAS dias), monta os trades fechados e calcula a nota
  (app/forexmetrics.py). Cada conta vira um MESTRE do ranking ("ct:<id da conta>").
- Os eventos ao vivo (ProtoOAExecutionEvent) viram o evento normalizado do ForexCopier (abriu / modificou / fechou_parcial /
  fechou), que espelha na carteira FICTÍCIA de quem segue. Nenhuma ordem vai para corretora nesta etapa.
- Se o Postgres da VPS estiver ligado (FOREX_DB_URL + ARQUIVO_JWT_SECRET, banco pump_forex do deploy/forex.sql), grava os
  mestres, os trades, os eventos, a curva de saldo e as notas. Sem ele, tudo funciona igual e o histórico vem de novo do
  cTrader a cada reinício.

Números das mensagens conferidos no pacote oficial ctrader-open-api 0.9.2 (OpenApiModelMessages/OpenApiMessages).
Autorização e token: help.ctrader.com/open-api/account-authentication (código vale 1 min; token 30 dias; refresh sem prazo).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import time
import urllib.parse
from datetime import datetime, timezone

from . import forexmetrics as fm
from .forexcopy import base
from .logsafe import add_secret

log = logging.getLogger("ctrader")

AUTH = "https://id.ctrader.com/my/settings/openapi/grantingaccess/"
TOKEN = "https://openapi.ctrader.com/apps/token"
HOSTS = {"live": "wss://live.ctraderapi.com:5036", "demo": "wss://demo.ctraderapi.com:5036"}
SCOPE = "accounts"                  # só leitura: o cTrader não deixa este token mandar ordem
STATE_TTL = 600
NAMES = ("ctrader_client_id", "ctrader_client_secret", "ctrader_tokens")
HIST_DIAS = 365                     # histórico lido na conexão (janelas de 7 dias, 1 pedido a cada 0,35 s)
JANELA_S = 7 * 86400
HEARTBEAT_S = 10
SCORE_S = 15 * 60                   # nota recalculada a cada 15 min (e a cada posição fechada)
REFRESH_ANTES_S = 3 * 86400         # renova o token 3 dias antes de vencer
LOT_PADRAO = 10_000_000             # 1 lote de forex = 100.000 unidades; o cTrader conta o volume em centésimos

# tipos de mensagem (ProtoOAPayloadType / ProtoPayloadType)
PT = {"app_auth": 2100, "app_auth_res": 2101, "acc_auth": 2102, "acc_auth_res": 2103, "symbols": 2114, "symbols_res": 2115,
      "symbol_by_id": 2116, "symbol_by_id_res": 2117, "trader": 2121, "trader_res": 2122, "trader_update": 2123,
      "reconcile": 2124, "reconcile_res": 2125, "execution": 2126, "deals": 2133, "deals_res": 2134, "error": 2142,
      "token_invalid": 2147, "client_disconnect": 2148, "accounts": 2149, "accounts_res": 2150, "acc_disconnect": 2164,
      "heartbeat": 51, "common_error": 50}
EXEC = {"ORDER_ACCEPTED": 2, "ORDER_FILLED": 3, "ORDER_REPLACED": 4, "ORDER_CANCELLED": 5, "ORDER_EXPIRED": 6,
        "ORDER_REJECTED": 7, "ORDER_CANCEL_REJECTED": 8, "SWAP": 9, "DEPOSIT_WITHDRAW": 10, "ORDER_PARTIAL_FILL": 11}
SIDE = {"BUY": 1, "SELL": 2}
POS_CLOSED = 2
POS_NOMES = {"POSITION_STATUS_OPEN": 1, "POSITION_STATUS_CLOSED": 2, "POSITION_STATUS_CREATED": 3, "POSITION_STATUS_ERROR": 4}
DEAL_OK = (2, 3)                    # FILLED, PARTIALLY_FILLED
DEAL_NOMES = {"FILLED": 2, "PARTIALLY_FILLED": 3, "REJECTED": 4, "INTERNALLY_REJECTED": 5, "ERROR": 6, "MISSED": 7}


class CTraderError(Exception):
    def __init__(self, code: str, msg: str = ""):
        super().__init__(f"{code}: {msg}" if msg else code)
        self.code = code


# ------------------------------------------------------------------------------------------------------------------ conversões
def _enum(v, nomes: dict) -> int:
    """O JSON do cTrader manda enum como número; aceita também o nome, por segurança."""
    if isinstance(v, str) and not v.isdigit():
        return nomes.get(v, 0)
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _num(v, d: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def money(v, digits) -> float:
    """Dinheiro vem em inteiros com moneyDigits casas (2 = centavos)."""
    return _num(v) / (10 ** int(digits if digits is not None else 2))


def lotes(volume, lot_size) -> float:
    """Volume em centésimos de unidade ÷ lotSize (também em centésimos) = lotes."""
    ls = _num(lot_size) or LOT_PADRAO
    return round(_num(volume) / ls, 4)


def lado(trade_side) -> str:
    return "buy" if _enum(trade_side, SIDE) == 1 else "sell"


def _iso(t: float | None) -> str | None:
    return datetime.fromtimestamp(t, timezone.utc).isoformat() if t else None


def _net(cpd: dict, md) -> float:
    """Resultado líquido da parte fechada: bruto + swap + comissão (+ taxa de conversão), na moeda da conta."""
    d = cpd.get("moneyDigits", md)
    return round(money(cpd.get("grossProfit"), d) + money(cpd.get("swap"), d) + money(cpd.get("commission"), d)
                 - abs(money(cpd.get("pnlConversionFee"), d)), 2)


def historico(deals: list[dict], simbolos: dict, lot: dict, md=2) -> tuple[list[dict], float | None]:
    """Negócios do cTrader → trades FECHADOS por posição (formato do forexmetrics) e o saldo antes do 1º fechamento.

    Uma posição pode fechar em partes: soma as partes e só conta quando o volume fechado alcança o aberto. Posição que abriu
    antes da janela lida (sem o negócio de abertura) fica de fora. O stop (SL) não vem no negócio: o trade sai sem a chave
    "sl" (= desconhecido), e o motor de nota não conta como "sem stop"."""
    pos: dict[str, dict] = {}
    for d in sorted(deals or [], key=lambda x: _num(x.get("executionTimestamp"))):
        if _enum(d.get("dealStatus"), DEAL_NOMES) not in DEAL_OK:
            continue
        pid = str(d.get("positionId"))
        sid = d.get("symbolId")
        p = pos.setdefault(pid, {"abre": [], "fecha": [], "sid": sid})
        (p["fecha"] if d.get("closePositionDetail") else p["abre"]).append(d)
    trades, primeiro = [], None
    for pid, p in pos.items():
        if not p["abre"] or not p["fecha"]:
            continue
        ls = lot.get(p["sid"]) or lot.get(str(p["sid"]))
        aberto = sum(_num(d.get("filledVolume")) for d in p["abre"])
        fechado = sum(_num(d["closePositionDetail"].get("closedVolume") or d.get("filledVolume")) for d in p["fecha"])
        if fechado + 1e-9 < aberto:
            continue                                              # ainda aberta (ou fechou só uma parte)
        lucro = sum(_net(d["closePositionDetail"], d.get("moneyDigits", md)) for d in p["fecha"])
        ult = p["fecha"][-1]
        cpd0 = p["fecha"][0]["closePositionDetail"]
        t = {"ticket": pid, "simbolo": simbolos.get(p["sid"]) or simbolos.get(str(p["sid"])) or str(p["sid"]),
             "lado": lado(p["abre"][0].get("tradeSide")), "volume": lotes(aberto, ls),
             "abriu": _num(p["abre"][0].get("executionTimestamp")) / 1000, "fechou": _num(ult.get("executionTimestamp")) / 1000,
             "lucro": round(lucro, 2), "preco_entrada": _num(cpd0.get("entryPrice")), "preco_saida": _num(ult.get("executionPrice")),
             "comissao": round(sum(money(d["closePositionDetail"].get("commission"), d.get("moneyDigits", md)) for d in p["fecha"])
                               + sum(money(d.get("commission"), d.get("moneyDigits", md)) for d in p["abre"]), 2),
             "swap": round(sum(money(d["closePositionDetail"].get("swap"), d.get("moneyDigits", md)) for d in p["fecha"]), 2)}
        trades.append(t)
        f0 = p["fecha"][0]
        bal = f0["closePositionDetail"].get("balance")
        if bal is not None and (primeiro is None or _num(f0.get("executionTimestamp")) < primeiro[0]):
            d0 = f0["closePositionDetail"].get("moneyDigits", f0.get("moneyDigits", md))
            primeiro = (_num(f0.get("executionTimestamp")), money(bal, d0) - _net(f0["closePositionDetail"], md))
    trades.sort(key=lambda x: x["fechou"])
    return trades, (round(primeiro[1], 2) if primeiro else None)


def evento(p: dict, conta: dict) -> dict | None:
    """ProtoOAExecutionEvent (JSON) → evento normalizado do ForexCopier, ou None quando não muda posição.

    conta = {"simbolos": {id: nome}, "lot": {id: lotSize}, "posicoes": {positionId: {...}}, "md": moneyDigits}."""
    et = _enum(p.get("executionType"), EXEC)
    pos, deal = p.get("position") or {}, p.get("deal") or {}
    pid = str(pos.get("positionId") or deal.get("positionId") or "")
    if not pid:
        return None
    td = pos.get("tradeData") or {}
    sid = td.get("symbolId") or deal.get("symbolId")
    nome = conta["simbolos"].get(sid) or conta["simbolos"].get(str(sid)) or str(sid)
    ls = conta["lot"].get(sid) or conta["lot"].get(str(sid))
    conhecida = conta["posicoes"].get(pid)
    t = _num(deal.get("executionTimestamp") or pos.get("utcLastUpdateTimestamp")) / 1000 or time.time()
    base_ev = {"ticket": pid, "simbolo": nome, "t": t}
    if et in (EXEC["ORDER_FILLED"], EXEC["ORDER_PARTIAL_FILL"]) and deal:
        if _enum(deal.get("dealStatus"), DEAL_NOMES) not in DEAL_OK:
            return None
        cpd = deal.get("closePositionDetail")
        if cpd:
            vol = lotes(cpd.get("closedVolume") or deal.get("filledVolume"), ls)
            fechou_tudo = _enum(pos.get("positionStatus"), POS_NOMES) == POS_CLOSED or (conhecida and vol + 1e-9 >= conhecida.get("volume", 0))
            md = cpd.get("moneyDigits", deal.get("moneyDigits", conta.get("md", 2)))
            return {**base_ev, "evento": "fechou" if fechou_tudo else "fechou_parcial", "volume_fechado": vol,
                    "lucro": _net(cpd, md), "preco": _num(deal.get("executionPrice")),
                    "saldo": money(cpd.get("balance"), md) if cpd.get("balance") is not None else None,
                    "lado": (conhecida or {}).get("lado") or ("sell" if lado(deal.get("tradeSide")) == "buy" else "buy")}
        if conhecida:
            return {**base_ev, "evento": "aumentou", "volume": lotes(deal.get("filledVolume"), ls), "lado": conhecida.get("lado")}
        return {**base_ev, "evento": "abriu", "lado": lado(deal.get("tradeSide") or td.get("tradeSide")),
                "volume": lotes(deal.get("filledVolume") or td.get("volume"), ls), "preco": _num(deal.get("executionPrice") or pos.get("price")),
                "sl": pos.get("stopLoss"), "tp": pos.get("takeProfit")}
    if et == EXEC["ORDER_REPLACED"] and pos and conhecida:
        sl, tp = pos.get("stopLoss"), pos.get("takeProfit")
        if sl != conhecida.get("sl") or tp != conhecida.get("tp"):
            return {**base_ev, "evento": "modificou", "sl": sl, "tp": tp, "lado": conhecida.get("lado")}
    return None


# ------------------------------------------------------------------------------------------------------------------ conexão
class Link:
    """Uma conexão WebSocket JSON com um servidor do cTrader (live ou demo). Respostas casam pelo clientMsgId."""

    def __init__(self, url: str, connect, on_event):
        self.url, self.connect, self.on_event = url, connect, on_event
        self.ws = None
        self.pend: dict[str, asyncio.Future] = {}
        self.n = 0
        self.tasks: list[asyncio.Task] = []
        self.alive = False
        self.contas: set[int] = set()
        self.uid = ""

    async def open(self, client_id: str, client_secret: str) -> None:
        self.ws = await self.connect(self.url)
        self.alive = True
        self.tasks = [asyncio.create_task(self._ler()), asyncio.create_task(self._pulso())]
        await self.req(PT["app_auth"], {"clientId": client_id, "clientSecret": client_secret})

    async def req(self, pt: int, payload: dict, timeout: float = 20) -> dict:
        if not self.alive:
            raise ConnectionError("conexão com o cTrader caiu")
        self.n += 1
        mid = f"fx{self.n}"
        fut = asyncio.get_running_loop().create_future()
        self.pend[mid] = fut
        try:
            await self.ws.send(json.dumps({"clientMsgId": mid, "payloadType": pt, "payload": payload}))
            return await asyncio.wait_for(fut, timeout)
        finally:
            self.pend.pop(mid, None)

    async def _ler(self) -> None:
        try:
            while True:
                d = json.loads(await self.ws.recv())
                pt, pl, mid = d.get("payloadType"), d.get("payload") or {}, d.get("clientMsgId")
                f = self.pend.get(mid) if mid else None
                if f is not None and not f.done():
                    if pt in (PT["error"], PT["common_error"]):
                        f.set_exception(CTraderError(str(pl.get("errorCode") or "erro"), str(pl.get("description") or "")))
                    else:
                        f.set_result(pl)
                    continue
                if pt == PT["heartbeat"]:
                    continue
                try:
                    await self.on_event(self, pt, pl)
                except Exception:
                    log.exception("cTrader: evento %s não processado", pt)
        except Exception as e:
            self._fim(e)

    async def _pulso(self) -> None:
        try:
            while self.alive:
                await asyncio.sleep(HEARTBEAT_S)
                await self.ws.send(json.dumps({"payloadType": PT["heartbeat"], "payload": {}}))
        except Exception as e:
            self._fim(e)

    def _fim(self, e) -> None:
        self.alive = False
        for f in list(self.pend.values()):
            if not f.done():
                f.set_exception(ConnectionError(f"conexão com o cTrader caiu ({type(e).__name__})"))

    async def close(self) -> None:
        self.alive = False
        for t in self.tasks:
            t.cancel()
        try:
            if self.ws is not None:
                await self.ws.close()
        except Exception:
            pass


async def _ws_connect(url: str):
    import websockets
    return await websockets.connect(url, open_timeout=15, ping_interval=None, max_size=2 ** 24)


# ------------------------------------------------------------------------------------------------------------------ banco local
class ForexDB:
    """Banco pump_forex (deploy/forex.sql) pelo PostgREST da VPS (mesmo jeito do arquivo: token assinado, sem porta aberta)."""

    def __init__(self, url: str, secret: str, http):
        import jwt
        from .db import SupaREST
        self.rest = SupaREST(url, "-", http)
        self.rest.base = url.rstrip("/")
        tok = jwt.encode({"role": "pump_forex", "iss": "pump-fun-copy"}, secret, algorithm="HS256")
        self.rest._h = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
        self.ids: dict[str, int] = {}
        self.st = {"ligado": True, "ok": None, "ultimo_erro": None, "gravados": 0}

    @classmethod
    def from_env(cls, http) -> "ForexDB | None":
        url = os.environ.get("FOREX_DB_URL", "").strip()
        sec = (os.environ.get("FOREX_JWT_SECRET", "") or os.environ.get("ARQUIVO_JWT_SECRET", "")).strip()
        return cls(url, sec, http) if url and len(sec) >= 32 else None

    async def _ok(self, coro):
        try:
            r = await coro
            self.st.update(ok=True)
            return r
        except Exception as e:
            self.st.update(ok=False, ultimo_erro=f"{time.strftime('%d/%m %H:%M')} {type(e).__name__}: {str(e)[:160]}")
            return None

    async def trader_id(self, c: dict, uid: str) -> int | None:
        k = str(c["id"])
        if k in self.ids:
            return self.ids[k]
        rows = await self._ok(self.rest.select("traders_monitored", {"plataforma": "ctrader", "conta_login": k}, limit=1, columns="id"))
        if rows:
            self.ids[k] = int(rows[0]["id"])
        elif rows is not None:
            r = await self._ok(self.rest._req("POST", "traders_monitored", None, {
                "plataforma": "ctrader", "conta_login": k, "tipo_conta": "real" if c.get("live") else "demo", "apelido": c.get("apelido"),
                "adicionado_por": uid, "cred_ref": "user_secrets:ctrader_tokens", "status": "conectado",
                "conectado_em": _iso(time.time())}, "return=representation"))
            if r:
                self.ids[k] = int(r[0]["id"])
        return self.ids.get(k)

    async def trades(self, tid: int, trades: list[dict]) -> None:
        rows = [{"trader_id": tid, "ticket": t["ticket"], "simbolo": t["simbolo"], "simbolo_base": base(t["simbolo"]),
                 "lado": t["lado"], "volume": t["volume"], "volume_fechado": t["volume"], "abriu_em": _iso(t["abriu"]),
                 "preco_entrada": t.get("preco_entrada") or 0, "sl": t.get("sl"), "fechou_em": _iso(t["fechou"]),
                 "preco_saida": t.get("preco_saida"), "comissao": t.get("comissao", 0), "swap": t.get("swap", 0), "lucro": t["lucro"]}
                for t in trades]
        for i in range(0, len(rows), 500):
            await self._ok(self.rest.insert("trades_history", rows[i:i + 500], upsert=True, on_conflict="trader_id,ticket"))
        self.st["gravados"] += len(rows)

    async def evento(self, tid: int, ev: dict) -> None:
        if ev.get("evento") not in ("abriu", "modificou", "fechou_parcial", "fechou"):
            return
        await self._ok(self.rest.insert("order_events", {"trader_id": tid, "ticket": ev["ticket"], "evento": ev["evento"],
                                                         "ocorreu_em": _iso(ev["t"]), "dados": ev},
                                        upsert=True, on_conflict="trader_id,ticket,evento,ocorreu_em"))

    async def saldo(self, tid: int, t: float, saldo: float) -> None:
        await self._ok(self.rest.insert("equity_snapshots", {"trader_id": tid, "t": _iso(t), "saldo": saldo, "patrimonio": saldo},
                                        upsert=True, on_conflict="trader_id,t"))

    async def nota(self, tid: int, r: dict) -> None:
        await self._ok(self.rest.insert("trader_scores", {
            "trader_id": tid, "dias": r.get("dias", 0), "trades": r.get("trades", 0), "retorno_pct": r.get("retorno_pct"),
            "mdd_pct": r.get("mdd_pct"), "profit_factor": r.get("profit_factor"), "sharpe": r.get("sharpe"),
            "consistencia": r.get("consistencia"), "martingale": r.get("martingale"), "grade": r.get("grade"),
            "score": r.get("score", 0), "elegivel": bool(r.get("elegivel")), "motivos": list(r.get("motivos") or [])}))


# ------------------------------------------------------------------------------------------------------------------ gerente
class CTraderHub:
    """Contas cTrader autorizadas pelos admins → mestres do ranking + eventos ao vivo para o ForexCopier."""

    def __init__(self, http, copier, db=None, vault=None, connect=None, clock=time.time, sleep=asyncio.sleep, store=None):
        self.http, self.copier, self.db, self.vault = http, copier, db, vault
        self.connect = connect or _ws_connect
        self.clock, self.sleep, self.store = clock, sleep, store
        self.states: dict[str, tuple[str, float]] = {}
        self.users: dict[str, dict] = {}          # uid → {"contas": {id: conta}, "erro", "tok": {...}, "lista_t"}
        self.links: dict[tuple[str, str], Link] = {}
        self.ranking: list[dict] = []
        self.score_t = 0.0
        self.st = {"rodando": False, "volta": None, "erro": None}

    # ------------------------------------------------------------------ chaves (cofre)
    async def keys(self, uid: str) -> dict:
        if self.vault is None:
            return {}
        try:
            d = await self.vault.load(uid)
        except Exception:
            return {}
        out = {n: d.get(n) for n in NAMES}
        for v in out.values():
            if v:
                add_secret(v)
        if out.get("ctrader_tokens"):
            try:
                tk = json.loads(out["ctrader_tokens"])
                for v in (tk.get("a"), tk.get("r")):
                    if v:
                        add_secret(v)
            except ValueError:
                pass
        return out

    async def status(self, uid: str) -> dict:
        k = await self.keys(uid)
        u = self.users.get(uid) or {}
        return {"client_id": bool(k.get("ctrader_client_id")), "client_secret": bool(k.get("ctrader_client_secret")),
                "conectado": bool(k.get("ctrader_tokens")), "erro": u.get("erro"),
                "contas": [self._conta_out(c) for c in (u.get("contas") or {}).values()]}

    @staticmethod
    def _conta_out(c: dict) -> dict:
        return {"id": str(c["id"]), "login": c.get("login"), "corretora": c.get("corretora"), "real": bool(c.get("live")),
                "moeda_digitos": c.get("md"), "saldo": c.get("saldo"), "status": c.get("status"), "msg": c.get("msg"),
                "monitorar": not c.get("off"), "trades": len(c.get("trades") or []), "abertas": len(c.get("posicoes") or {}),
                "ultimo_evento": c.get("ultimo_evento"), "historico_dias": c.get("hist_dias"), "apelido": c.get("apelido")}

    # ------------------------------------------------------------------ OAuth
    def auth_url(self, uid: str, client_id: str, redirect: str) -> str:
        now = self.clock()
        for s, (_, t) in list(self.states.items()):
            if now - t > STATE_TTL:
                self.states.pop(s, None)
        state = secrets.token_urlsafe(24)
        self.states[state] = (uid, now)
        return AUTH + "?" + urllib.parse.urlencode({"client_id": client_id, "redirect_uri": redirect, "scope": SCOPE,
                                                    "product": "web", "state": state})

    def take_state(self, state: str) -> str | None:
        v = self.states.pop(str(state or ""), None)
        if not v or self.clock() - v[1] > STATE_TTL:
            return None
        return v[0]

    async def _token(self, params: dict) -> dict:
        r = await self.http.get(TOKEN, params=params, timeout=20)
        try:
            j = r.json()
        except ValueError:
            j = {}
        if r.status_code != 200 or not j.get("accessToken"):
            raise ValueError("o cTrader recusou: " + str(j.get("description") or j.get("errorCode") or r.status_code))
        for v in (j.get("accessToken"), j.get("refreshToken")):
            if v:
                add_secret(v)
        return {"a": j["accessToken"], "r": j.get("refreshToken") or params.get("refresh_token"),
                "exp": self.clock() + float(j.get("expiresIn") or 2628000)}

    async def exchange(self, uid: str, code: str, redirect: str) -> None:
        k = await self.keys(uid)
        if not k.get("ctrader_client_id") or not k.get("ctrader_client_secret"):
            raise ValueError("salve o Client ID e o Client Secret antes de conectar")
        tk = await self._token({"grant_type": "authorization_code", "code": code, "redirect_uri": redirect,
                                "client_id": k["ctrader_client_id"], "client_secret": k["ctrader_client_secret"]})
        await self.vault.save(uid, "ctrader_tokens", json.dumps(tk))
        await self._derruba(uid)
        self.users[uid] = {"contas": {}, "erro": None}

    async def _tokens(self, uid: str) -> tuple[dict, dict] | None:
        k = await self.keys(uid)
        if not (k.get("ctrader_client_id") and k.get("ctrader_client_secret") and k.get("ctrader_tokens")):
            return None
        try:
            tk = json.loads(k["ctrader_tokens"])
        except ValueError:
            return None
        if tk.get("r") and float(tk.get("exp") or 0) - self.clock() < REFRESH_ANTES_S:
            tk = await self._token({"grant_type": "refresh_token", "refresh_token": tk["r"], "client_id": k["ctrader_client_id"],
                                    "client_secret": k["ctrader_client_secret"]})
            await self.vault.save(uid, "ctrader_tokens", json.dumps(tk))
            await self._derruba(uid)            # token novo: as contas autorizam de novo
        return k, tk

    async def remove(self, uid: str) -> None:
        await self._derruba(uid)
        for n in NAMES:
            await self.vault.delete(uid, n)
        u = self.users.pop(uid, None) or {}
        for c in (u.get("contas") or {}).values():
            self.copier.mestres.pop("ct:" + str(c["id"]), None)
        self._ranking()

    async def _derruba(self, uid: str) -> None:
        for key in [k for k in self.links if k[0] == uid]:
            await self.links.pop(key).close()
        for c in ((self.users.get(uid) or {}).get("contas") or {}).values():
            c["pronta"] = False

    def set_off(self, uid: str, conta_id: str, off: bool) -> bool:
        c = ((self.users.get(uid) or {}).get("contas") or {}).get(str(conta_id))
        if c is None:
            return False
        c["off"] = bool(off)
        tid = "ct:" + str(c["id"])
        if off:
            self.copier.mestres.pop(tid, None)
            c["pronta"] = False
            c["status"] = "pausado"
        b = self.copier.livro(uid)
        offs = set(b.cfg.get("ct_off") or [])
        offs.add(str(conta_id)) if off else offs.discard(str(conta_id))
        b.cfg["ct_off"] = sorted(offs)
        b.sujo = True
        self._ranking()
        return True

    # ------------------------------------------------------------------ laço
    async def run(self) -> None:
        self.st["rodando"] = True
        while True:
            try:
                await self.volta()
                self.st.update(volta=self.clock(), erro=None)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.exception("cTrader: volta falhou")
                self.st["erro"] = f"{type(e).__name__}: {str(e)[:160]}"
            await self.sleep(30)

    async def _uids(self) -> list[str]:
        uids = set(self.users)
        if self.db is not None:
            try:
                for r in await self.db.select("user_secrets", {"nome": "ctrader_tokens"}, columns="user_id"):
                    uids.add(r["user_id"])
            except Exception:
                pass
        return sorted(uids)

    async def volta(self) -> None:
        for uid in await self._uids():
            u = self.users.setdefault(uid, {"contas": {}, "erro": None})
            try:
                kt = await self._tokens(uid)
                if kt is None:
                    continue
                k, tk = kt
                b = await self.copier.carregar(uid)
                offs = set(b.cfg.get("ct_off") or [])
                if not u["contas"] or self.clock() - u.get("lista_t", 0) > 6 * 3600:
                    await self._lista(uid, k, tk, offs)
                for c in u["contas"].values():
                    if c.get("off") or c.get("pronta"):
                        continue
                    await self._prepara(uid, k, tk, c)
                u["erro"] = None
            except Exception as e:
                u["erro"] = f"{type(e).__name__}: {str(e)[:200]}"
                log.warning("cTrader %s…: %s", uid[:8], u["erro"])
        if self.clock() - self.score_t > SCORE_S:
            await self.notas()
        try:
            await self.copier.flush()
        except Exception:
            pass

    async def _link(self, uid: str, host: str, k: dict) -> Link:
        lk = self.links.get((uid, host))
        if lk is not None and lk.alive:
            return lk
        if lk is not None:
            await lk.close()
            for c in ((self.users.get(uid) or {}).get("contas") or {}).values():
                if c.get("host") == host:
                    c["pronta"] = False
        lk = Link(HOSTS[host], self.connect, self._on_event)
        lk.uid = uid
        try:
            await lk.open(k["ctrader_client_id"], k["ctrader_client_secret"])
        except Exception:
            await lk.close()
            raise
        self.links[(uid, host)] = lk
        return lk

    async def _lista(self, uid: str, k: dict, tk: dict, offs: set) -> None:
        lk = await self._link(uid, "live", k)
        r = await lk.req(PT["accounts"], {"accessToken": tk["a"]})
        u = self.users[uid]
        for a in r.get("ctidTraderAccount") or []:
            cid = str(a.get("ctidTraderAccountId"))
            c = u["contas"].get(cid) or {"id": int(cid), "simbolos": {}, "lot": {}, "posicoes": {}, "trades": [], "eventos": [],
                                         "md": 2, "status": "pendente", "pronta": False}
            c.update(live=bool(a.get("isLive")), login=a.get("traderLogin"), host="live" if a.get("isLive") else "demo",
                     off=cid in offs)
            if c["off"]:
                c["status"] = "pausado"
            u["contas"][cid] = c
        u["lista_t"] = self.clock()

    async def _prepara(self, uid: str, k: dict, tk: dict, c: dict) -> None:
        c["status"], c["msg"] = "conectando", None
        try:
            lk = await self._link(uid, c["host"], k)
            aid = c["id"]
            await lk.req(PT["acc_auth"], {"ctidTraderAccountId": aid, "accessToken": tk["a"]})
            lk.contas.add(aid)
            tr = (await lk.req(PT["trader"], {"ctidTraderAccountId": aid})).get("trader") or {}
            c["md"] = int(tr.get("moneyDigits") or 2)
            c["saldo"] = money(tr.get("balance"), c["md"])
            c["corretora"] = tr.get("brokerName")
            c["login"] = tr.get("traderLogin") or c.get("login")
            c["apelido"] = f"{c.get('corretora') or 'cTrader'} #{c.get('login') or aid}"
            sy = await lk.req(PT["symbols"], {"ctidTraderAccountId": aid})
            c["simbolos"] = {int(s["symbolId"]): s.get("symbolName") or str(s["symbolId"]) for s in sy.get("symbol") or [] if "symbolId" in s}
            rc = await lk.req(PT["reconcile"], {"ctidTraderAccountId": aid})
            deals = await self._deals(lk, aid)
            ids = {int(d["symbolId"]) for d in deals if "symbolId" in d}
            ids |= {int((p.get("tradeData") or {}).get("symbolId")) for p in rc.get("position") or [] if (p.get("tradeData") or {}).get("symbolId")}
            await self._lots(lk, c, ids)
            c["posicoes"] = {}
            for p in rc.get("position") or []:
                td = p.get("tradeData") or {}
                sid = td.get("symbolId")
                c["posicoes"][str(p.get("positionId"))] = {
                    "simbolo": c["simbolos"].get(sid, str(sid)), "lado": lado(td.get("tradeSide")),
                    "volume": lotes(td.get("volume"), c["lot"].get(sid)), "preco": _num(p.get("price")),
                    "abriu": _num(td.get("openTimestamp")) / 1000 or self.clock(), "sl": p.get("stopLoss"), "tp": p.get("takeProfit")}
            c["trades"], c["saldo_inicial"] = historico(deals, c["simbolos"], c["lot"], c["md"])
            if not c["saldo_inicial"]:
                c["saldo_inicial"] = c.get("saldo") or 0
            c["hist_dias"] = HIST_DIAS
            c["pronta"], c["status"], c["msg"] = True, "conectado", None
            await self._grava_hist(uid, c)
            self._nota(c)
            self._ranking()
        except Exception as e:
            c["status"], c["msg"] = "erro", f"{type(e).__name__}: {str(e)[:200]}"
            raise

    async def _deals(self, lk: Link, aid: int) -> list[dict]:
        fim = int(self.clock() * 1000)
        ini = fim - HIST_DIAS * 86400 * 1000
        out, a = [], ini
        while a < fim:
            b = min(fim, a + JANELA_S * 1000)
            out += await self._janela(lk, aid, a, b, 0)
            a = b
            await self.sleep(0.35)                 # pedidos de histórico: no máximo 5 por segundo
        return out

    async def _janela(self, lk: Link, aid: int, a: int, b: int, prof: int) -> list[dict]:
        r = await lk.req(PT["deals"], {"ctidTraderAccountId": aid, "fromTimestamp": a, "toTimestamp": b})
        ds = list(r.get("deal") or [])
        if r.get("hasMore") and prof < 6 and b - a > 60_000:
            meio = (a + b) // 2
            await self.sleep(0.35)
            ds = await self._janela(lk, aid, a, meio, prof + 1)
            await self.sleep(0.35)
            ds += await self._janela(lk, aid, meio, b, prof + 1)
        return ds

    async def _lots(self, lk: Link, c: dict, ids: set) -> None:
        falta = sorted(i for i in ids if i not in c["lot"])
        for i in range(0, len(falta), 50):
            r = await lk.req(PT["symbol_by_id"], {"ctidTraderAccountId": c["id"], "symbolId": falta[i:i + 50]})
            for s in r.get("symbol") or []:
                c["lot"][int(s["symbolId"])] = _num(s.get("lotSize")) or LOT_PADRAO

    # ------------------------------------------------------------------ eventos ao vivo
    def _conta_de(self, lk: Link, aid) -> dict | None:
        u = self.users.get(getattr(lk, "uid", ""), {})
        return (u.get("contas") or {}).get(str(aid))

    async def _on_event(self, lk: Link, pt: int, pl: dict) -> None:
        if pt in (PT["token_invalid"], PT["client_disconnect"]):
            lk._fim(ConnectionError("cTrader encerrou a sessão"))
            u = self.users.get(getattr(lk, "uid", ""), {})
            u["erro"] = "o cTrader encerrou a sessão (" + str(pl.get("reason") or pt) + "): reconecta sozinho"
            return
        c = self._conta_de(lk, pl.get("ctidTraderAccountId"))
        if c is None:
            return
        if pt == PT["acc_disconnect"]:
            c["pronta"], c["status"] = False, "reconectando"
            return
        if pt == PT["trader_update"]:
            tr = pl.get("trader") or {}
            if tr.get("balance") is not None:
                c["saldo"] = money(tr.get("balance"), tr.get("moneyDigits", c["md"]))
            return
        if pt != PT["execution"] or not c.get("pronta") or c.get("off"):
            return
        dep = pl.get("depositWithdraw") or {}
        if dep.get("balance") is not None:
            c["saldo"] = money(dep.get("balance"), dep.get("moneyDigits", c["md"]))
        sid = ((pl.get("position") or {}).get("tradeData") or {}).get("symbolId") or (pl.get("deal") or {}).get("symbolId")
        if sid is not None and int(sid) not in c["lot"]:
            try:
                await self._lots(lk, c, {int(sid)})
            except Exception:
                pass
        ev = evento(pl, c)
        if ev is None:
            return
        await self.aplica(lk.uid, c, ev)

    async def aplica(self, uid: str, c: dict, ev: dict) -> None:
        """Atualiza a conta (posições, trades, saldo) e manda o evento para a cópia fictícia."""
        tid = "ct:" + str(c["id"])
        ev = {**ev, "trader_id": tid, "patrimonio_mestre": c.get("saldo") or None}
        c["ultimo_evento"] = self.clock()
        pid = ev["ticket"]
        if ev["evento"] == "abriu":
            c["posicoes"][pid] = {"simbolo": ev["simbolo"], "lado": ev["lado"], "volume": ev["volume"], "preco": ev.get("preco"),
                                  "abriu": ev["t"], "sl": ev.get("sl"), "tp": ev.get("tp")}
        elif ev["evento"] == "modificou" and pid in c["posicoes"]:
            c["posicoes"][pid].update(sl=ev.get("sl"), tp=ev.get("tp"))
        elif ev["evento"] in ("fechou", "fechou_parcial"):
            p = c["posicoes"].get(pid)
            if ev.get("saldo") is not None:
                c["saldo"] = ev["saldo"]
            if p is not None:
                p["lucro_acum"] = round(p.get("lucro_acum", 0) + ev.get("lucro", 0), 2)
                if ev["evento"] == "fechou":
                    c["posicoes"].pop(pid, None)
                    c["trades"].append({"ticket": pid, "simbolo": p["simbolo"], "lado": p["lado"], "volume": p["volume"],
                                        "abriu": p["abriu"], "fechou": ev["t"], "lucro": p["lucro_acum"], "sl": p.get("sl"),
                                        "preco_entrada": p.get("preco"), "preco_saida": ev.get("preco")})
                else:
                    p["volume"] = round(max(0.0, p["volume"] - ev.get("volume_fechado", 0)), 4)
        c["eventos"] = ([{"t": ev["t"], "evento": ev["evento"], "simbolo": ev.get("simbolo"), "lado": ev.get("lado"),
                          "volume": ev.get("volume") or ev.get("volume_fechado"), "lucro": ev.get("lucro")}] + c.get("eventos", []))[:100]
        if ev["evento"] != "aumentou":
            self.copier.on_event(ev)
        if self.store is not None:
            tdb = await self.store.trader_id(c, uid)
            if tdb:
                await self.store.evento(tdb, ev)
                if ev["evento"] == "fechou" and c["trades"]:
                    await self.store.trades(tdb, c["trades"][-1:])
                if ev.get("saldo") is not None:
                    await self.store.saldo(tdb, ev["t"], ev["saldo"])
        if ev["evento"] == "fechou":
            self._nota(c)
            self._ranking()

    # ------------------------------------------------------------------ nota e ranking
    def _nota(self, c: dict) -> dict:
        r = fm.avaliar(c.get("trades") or [], c.get("saldo_inicial") or c.get("saldo") or 0, conta_real=bool(c.get("live")),
                       agora=self.clock())
        c["nota"] = r
        self.copier.mestres["ct:" + str(c["id"])] = {
            "apelido": c.get("apelido"), "plataforma": "cTrader", "patrimonio": c.get("saldo"), "elegivel": r.get("elegivel"),
            "score": r.get("score"), "status": c.get("status"), "tipo_conta": "real" if c.get("live") else "demo"}
        return r

    def _ranking(self) -> None:
        out = []
        for u in self.users.values():
            for c in (u.get("contas") or {}).values():
                if c.get("off") or not c.get("nota"):
                    continue
                out.append({"id": "ct:" + str(c["id"]), "apelido": c.get("apelido"), "plataforma": "cTrader",
                            "tipo_conta": "real" if c.get("live") else "demo", **c["nota"]})
        out.sort(key=lambda r: (not r["elegivel"], -r["score"]))
        self.ranking = out

    async def notas(self) -> None:
        self.score_t = self.clock()
        for uid, u in self.users.items():
            for c in (u.get("contas") or {}).values():
                if c.get("pronta") and not c.get("off"):
                    r = self._nota(c)
                    if self.store is not None:
                        tdb = await self.store.trader_id(c, uid)
                        if tdb:
                            await self.store.nota(tdb, r)
        self._ranking()

    async def _grava_hist(self, uid: str, c: dict) -> None:
        if self.store is None:
            return
        tdb = await self.store.trader_id(c, uid)
        if tdb and c.get("trades"):
            await self.store.trades(tdb, c["trades"])
            if c.get("saldo") is not None:
                await self.store.saldo(tdb, self.clock(), c["saldo"])

    async def fechar(self) -> None:
        for key in list(self.links):
            await self.links.pop(key).close()

    # ------------------------------------------------------------------ telas
    def conector(self) -> dict:
        contas = [c for u in self.users.values() for c in (u.get("contas") or {}).values()]
        prontas = sum(1 for c in contas if c.get("pronta"))
        if not contas:
            st = "aguardando conexão"
        elif prontas:
            st = f"conectado ({prontas} de {len(contas)} contas)"
        else:
            st = "conectando"
        return {"plataforma": "cTrader", "status": st, "como": "Open API oficial (OAuth2 só leitura + WebSocket JSON)",
                "ok": bool(prontas), "erro": self.st.get("erro"),
                "banco_local": None if self.store is None else {"ok": self.store.st.get("ok"), "erro": self.store.st.get("ultimo_erro")}}

    def mestres_da(self, uid: str) -> list[dict]:
        u = self.users.get(uid) or {}
        out = []
        for c in (u.get("contas") or {}).values():
            o = self._conta_out(c)
            o["eventos"] = (c.get("eventos") or [])[:30]
            o["posicoes"] = [{"ticket": k, **v} for k, v in (c.get("posicoes") or {}).items()]
            out.append(o)
        return out
