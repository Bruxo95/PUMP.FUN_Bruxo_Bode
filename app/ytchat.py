"""0.32.349 (pedido do dono, 14/11/2026): o BOT LIVE comenta no chat da live do YouTube cada COMPRA que fizer, com o hash da
transação do trader copiado. Só compras (nada de vendas ou "não copiou").

Como funciona: o dono cria um "ID do cliente OAuth" (Aplicativo da Web) no Google Cloud com a YouTube Data API v3 ativa, cola o
Client ID e o Client Secret em /botlive (ficam no cofre criptografado, user_secrets) e clica em "Conectar YouTube" uma vez. O Google
devolve uma autorização permanente (refresh token), que também vai para o cofre. A cada compra a mensagem entra numa fila e sai no
chat da live que estiver no ar no canal (liveBroadcasts → liveChatId → POST liveChat/messages).

Nada daqui volta pela API: a tela só vê "configurada: sim/não". Cota grátis do YouTube: 10.000 por dia; cada mensagem gasta 20.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
import time
import urllib.parse

from .logsafe import add_secret

log = logging.getLogger("pump.ytchat")

AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/youtube/v3"
SCOPE = "https://www.googleapis.com/auth/youtube.force-ssl"
NAMES = ("youtube_client_id", "youtube_client_secret", "youtube_refresh_token")
GAP_S = 8            # no máximo 1 mensagem a cada 8 s por canal (não lota o chat)
QUEUE_MAX = 20       # fila de compras esperando para sair
DAY_MAX = 400        # 400 × 20 = 8.000 da cota de 10.000 por dia (sobra para achar a live)
CHAT_TTL = 300       # o id do chat da live é guardado por 5 min
NO_LIVE_TTL = 60     # sem live no ar: tenta achar de novo depois de 1 min
STATE_TTL = 600      # o "Conectar YouTube" vale por 10 min
MSG_MAX = 200        # limite do chat do YouTube


def short(w: str) -> str:
    w = str(w or "")
    return w[:6] + "…" + w[-4:] if len(w) > 12 else w


def buy_text(sym: str, wallet: str, tx: str | None, explorer: str) -> str:
    """Mensagem de uma compra: símbolo, trader copiado e o hash/link da transação dele."""
    sym = (str(sym or "").strip() or "token")[:20]
    t = f"🤖 BOT BUY ${sym} · copying trader {short(wallet)}"
    if tx:
        t += f" · tx {explorer.rstrip('/')}/tx/{tx}"
    return t[:MSG_MAX]


class YTChat:
    def __init__(self, http, vault=None, explorer: str = ""):
        self.http, self.vault, self.explorer = http, vault, explorer
        self.on: dict[str, bool] = {}                 # conta → comentar as compras (gravado no botlive_books pelo BotLive)
        self.q: dict[str, list[str]] = {}
        self.states: dict[str, tuple[str, float]] = {}
        self.tok: dict[str, tuple[str, float]] = {}
        self.chat: dict[str, tuple[str | None, float, str]] = {}
        self.sent_t: dict[str, float] = {}
        self.day: dict[tuple[str, str], int] = {}
        self.last: dict[str, dict] = {}
        self.task: asyncio.Task | None = None

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
        return out

    async def names(self, uid: str) -> set:
        if self.vault is None:
            return set()
        try:
            return set(await self.vault.names(uid)) & set(NAMES)
        except Exception:
            return set()

    # ------------------------------------------------------------------ conectar (OAuth)
    def auth_url(self, uid: str, client_id: str, redirect: str) -> str:
        now = time.time()
        for s, (_, t) in list(self.states.items()):
            if now - t > STATE_TTL:
                self.states.pop(s, None)
        state = secrets.token_urlsafe(24)
        self.states[state] = (uid, now)
        return AUTH + "?" + urllib.parse.urlencode({
            "client_id": client_id, "redirect_uri": redirect, "response_type": "code", "scope": SCOPE,
            "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true", "state": state})

    def take_state(self, state: str) -> str | None:
        v = self.states.pop(str(state or ""), None)
        if not v or time.time() - v[1] > STATE_TTL:
            return None
        return v[0]

    async def exchange(self, uid: str, code: str, redirect: str) -> None:
        k = await self.keys(uid)
        if not k.get("youtube_client_id") or not k.get("youtube_client_secret"):
            raise ValueError("salve o Client ID e o Client Secret antes de conectar")
        r = await self.http.post(TOKEN, data={"code": code, "client_id": k["youtube_client_id"],
                                              "client_secret": k["youtube_client_secret"], "redirect_uri": redirect,
                                              "grant_type": "authorization_code"}, timeout=15)
        j = _json(r)
        if r.status_code != 200:
            raise ValueError("o Google recusou: " + str(j.get("error_description") or j.get("error") or r.status_code))
        rt = j.get("refresh_token")
        if not rt:
            raise ValueError("o Google não mandou a autorização permanente: remova o acesso do app em "
                             "myaccount.google.com/permissions e conecte de novo")
        add_secret(rt)
        if j.get("access_token"):
            add_secret(j["access_token"])
            self.tok[uid] = (j["access_token"], time.time() + float(j.get("expires_in") or 3600) - 60)
        await self.vault.save(uid, "youtube_refresh_token", rt)
        self.chat.pop(uid, None)
        self.last[uid] = {"t": time.time(), "ok": True, "info": "YouTube conectado"}

    async def access(self, uid: str) -> str:
        a = self.tok.get(uid)
        if a and a[1] > time.time():
            return a[0]
        k = await self.keys(uid)
        if not all(k.get(n) for n in NAMES):
            raise ValueError("YouTube não conectado")
        r = await self.http.post(TOKEN, data={"client_id": k["youtube_client_id"], "client_secret": k["youtube_client_secret"],
                                              "refresh_token": k["youtube_refresh_token"], "grant_type": "refresh_token"}, timeout=15)
        j = _json(r)
        if r.status_code != 200 or not j.get("access_token"):
            raise ValueError("a autorização do YouTube não vale mais: clique em Conectar YouTube de novo ("
                             + str(j.get("error") or r.status_code) + ")")
        add_secret(j["access_token"])
        self.tok[uid] = (j["access_token"], time.time() + float(j.get("expires_in") or 3600) - 60)
        return j["access_token"]

    async def live_chat(self, uid: str, tok: str) -> tuple[str | None, str]:
        c = self.chat.get(uid)
        if c and time.time() - c[1] < (CHAT_TTL if c[0] else NO_LIVE_TTL):
            return c[0], c[2]
        r = await self.http.get(API + "/liveBroadcasts", params={"part": "snippet", "broadcastStatus": "active",
                                                                 "broadcastType": "all", "maxResults": 5},
                                headers={"Authorization": "Bearer " + tok}, timeout=15)
        j = _json(r)
        if r.status_code != 200:
            raise ValueError("YouTube recusou a busca da live: " + _err(j, r.status_code))
        cid, title = None, ""
        for it in j.get("items") or []:
            sn = it.get("snippet") or {}
            if sn.get("liveChatId"):
                cid, title = sn["liveChatId"], str(sn.get("title") or "")[:80]
                break
        self.chat[uid] = (cid, time.time(), title)
        return cid, title

    # ------------------------------------------------------------------ fila e envio
    def push(self, uid: str, text: str, force: bool = False) -> bool:
        if not force and not self.on.get(uid):
            return False
        q = self.q.setdefault(uid, [])
        if len(q) >= QUEUE_MAX:
            return False
        q.append(text[:MSG_MAX])
        try:
            if self.task is None or self.task.done():
                self.task = asyncio.get_running_loop().create_task(self.run())
        except RuntimeError:
            pass                                      # sem laço rodando (testes): a mensagem fica na fila
        return True

    async def run(self) -> None:
        while any(self.q.values()):
            for uid, q in list(self.q.items()):
                if q and time.time() - self.sent_t.get(uid, 0) >= GAP_S:
                    await self.send(uid, q.pop(0))
            await asyncio.sleep(1)

    async def send(self, uid: str, text: str) -> bool:
        dia = time.strftime("%Y-%m-%d", time.gmtime())
        if self.day.get((uid, dia), 0) >= DAY_MAX:
            self.last[uid] = {"t": time.time(), "ok": False, "erro": f"limite de {DAY_MAX} mensagens hoje (cota do YouTube)"}
            return False
        self.sent_t[uid] = time.time()
        try:
            tok = await self.access(uid)
            cid, _ = await self.live_chat(uid, tok)
            if not cid:
                self.last[uid] = {"t": time.time(), "ok": False, "erro": "nenhuma live no ar neste canal", "texto": text}
                return False
            # 0.32.350: o endereço certo é liveChat/messages (com "liveChatMessages" o YouTube responde 404)
            r = await self.http.post(API + "/liveChat/messages", params={"part": "snippet"},
                                     json={"snippet": {"liveChatId": cid, "type": "textMessageEvent",
                                                       "textMessageDetails": {"messageText": text}}},
                                     headers={"Authorization": "Bearer " + tok}, timeout=15)
            if r.status_code == 403 or r.status_code == 404:
                self.chat.pop(uid, None)              # a live acabou ou o chat fechou: procura de novo na próxima
            if r.status_code not in (200, 201):
                raise ValueError("YouTube recusou a mensagem: " + _err(_json(r), r.status_code))
            self.day[(uid, dia)] = self.day.get((uid, dia), 0) + 1
            self.last[uid] = {"t": time.time(), "ok": True, "texto": text}
            return True
        except Exception as e:
            self.last[uid] = {"t": time.time(), "ok": False, "erro": str(e)[:200], "texto": text}
            log.info("YouTube chat (conta %s…): %s", uid[:8], str(e)[:200])
            return False

    async def status(self, uid: str) -> dict:
        n = await self.names(uid)
        c = self.chat.get(uid)
        return {"client_id": "youtube_client_id" in n, "client_secret": "youtube_client_secret" in n,
                "conectado": "youtube_refresh_token" in n, "ligado": bool(self.on.get(uid)),
                "live": (c[2] or "live no ar") if c and c[0] else None,
                "enviadas_hoje": self.day.get((uid, time.strftime("%Y-%m-%d", time.gmtime())), 0), "limite_dia": DAY_MAX,
                "fila": len(self.q.get(uid) or []), "ultima": self.last.get(uid)}


def _json(r) -> dict:
    try:
        j = r.json()
        return j if isinstance(j, dict) else {}
    except Exception:
        return {}


def _err(j: dict, code) -> str:
    e = j.get("error")
    if isinstance(e, dict):
        rs = e.get("errors") or [{}]
        return str((rs[0] or {}).get("reason") or e.get("message") or code)
    return str(e or code)
