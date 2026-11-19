"""0.32.382 (pedido do dono, 19/11/2026): carteiras ligadas ao DEV nos tokens do BOOST — Wallet Clustering e Sybil Detection.

O objetivo é achar o "Multi-Wallet Bundling": o DEV espalha o token em várias carteiras (financiadas pela mesma origem, ou que
compraram no mesmo bloco da criação) para esconder quanto realmente tem e depois despejar tudo junto (rug pull).

Usa uma API SEPARADA, só para isto: Alchemy (Solana), chave do sistema `alchemy_api_key` (Administração → Chaves do sistema).
Sem a chave, nada roda.

Como funciona (um token por vez, uma vez por token, logo depois da migração)
1. Os maiores detentores do token (getTokenLargestAccounts) e o dono de cada conta de token. Conta cujo dono é um programa
   (pool da PumpSwap, curva, PDA) fica de fora: só carteiras de pessoas entram na conta.
2. Bloco de lançamento: a primeira transação da conta de token do DEV (criação + compra do DEV). Sem conta do DEV, o bloco mais
   antigo entre os detentores.
3. Para cada carteira: em que bloco recebeu o token pela primeira vez (primeira transação da conta de token) e QUEM mandou o
   primeiro SOL para ela (a transação mais antiga da carteira → a transferência de SOL que chegou nela).
4. Grupo do DEV = o DEV + carteiras que o DEV financiou + carteiras financiadas pela mesma origem que financiou o DEV + quem
   financiou o DEV + carteiras financiadas por alguém do grupo (repete até não crescer).
   Bundle = carteiras que receberam o token até LAUNCH_SLOTS blocos depois do lançamento.
5. Concentração real do DEV = % do total nas carteiras do grupo do DEV + bundle. Nível: alto / médio / baixo.

Limites honestos
- Só os N maiores detentores (padrão 15). Carteiras pequenas de um bundle grande ficam de fora.
- Carteira com 200+ transações: a origem do dinheiro não é procurada (seria caro) e ela fica como "antiga".
- "Mesma origem" pode ser uma corretora (muita gente saca da mesma carteira quente da Binance, por exemplo). Por isso a origem
  comum SEM ligação com o DEV só aparece como informação ("mesma origem"); o alerta usa o grupo do DEV e o bundle.
- Só mede e avisa. A trava (barrar a compra) existe na tela, mas está desligada nesta versão.
"""
from __future__ import annotations

import asyncio
import time

SYSTEM_PROGRAM = "11111111111111111111111111111111"
LAUNCH_SLOTS = 2                    # recebeu o token até 2 blocos depois do lançamento = comprou junto (bundle)
SIG_LIMIT = 200                     # 0.32.385: 1.000 pesava demais no plano grátis; carteira com 200+ transações = antiga
PARALLEL = 1                        # 0.32.385: um pedido por vez (com 3 a Alchemy seguia respondendo 429)
MIN_GAP_S, MAX_GAP_S = 0.15, 2.0    # 0.32.385: ritmo que se ajusta sozinho: 429 → mais devagar (×1,5); sucesso → mais rápido (×0,97)
START_GAP_S = 0.3
RETRY_429 = 4                       # 0.32.384: em 429 espera e tenta de novo (1, 2, 3, 4 s)
NEW_WALLET_S = 86400                # carteira com menos de 1 dia = nova


def _p(x: float) -> str:
    return f"{x:.1f}".replace(".", ",") + "%"


def alchemy_url(key: str) -> str:
    """Aceita a chave ou o endereço inteiro que a Alchemy mostra (https://solana-mainnet.g.alchemy.com/v2/<chave>)."""
    k = (key or "").strip()
    if k.startswith("https://"):
        return k
    return "https://solana-mainnet.g.alchemy.com/v2/" + k


def key_of(value: str) -> str:
    """Valida o que foi colado no painel e devolve só a chave (nunca guarda outro endereço)."""
    v = (value or "").strip()
    if v.startswith("http"):
        if not v.startswith("https://solana-mainnet.g.alchemy.com/v2/"):
            raise ValueError("cole a chave da Alchemy ou o endereço https://solana-mainnet.g.alchemy.com/v2/…")
        v = v.rsplit("/", 1)[-1]
    if not (16 <= len(v) <= 80) or not all(ch.isalnum() or ch in "-_" for ch in v):
        raise ValueError("chave da Alchemy inválida")
    return v


class RpcError(Exception):
    pass


class Rpc:
    """Um por chave no servidor (hub.alchemy_rpc): o ritmo vale para a análise das carteiras e para a reserva do BOOST juntos."""
    def __init__(self, http, url: str, sleep=asyncio.sleep, clock=time.monotonic):
        self.http, self.url, self.n, self.limit_n = http, url, 0, 0
        self.sem = asyncio.Semaphore(PARALLEL)
        self.lock = asyncio.Lock()
        self.sleep, self.clock, self.last, self.gap = sleep, clock, 0.0, START_GAP_S

    async def _pace(self) -> None:
        async with self.lock:
            wait = self.last + self.gap - self.clock()
            if wait > 0:
                await self.sleep(wait)
            self.last = self.clock()

    async def call(self, method: str, params: list):
        async with self.sem:
            for tent in range(RETRY_429 + 1):
                await self._pace()
                self.n += 1
                r = await self.http.post(self.url, timeout=15, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
                if r.status_code in (401, 403):
                    raise RpcError(f"Alchemy recusou a chave (HTTP {r.status_code})")
                j = r.json() if r.status_code != 429 else {"error": {"code": 429}}
                err = j.get("error")
                if r.status_code == 429 or (err and (err.get("code") == 429 or "rate" in str(err.get("message")).lower()
                                                     or "compute units" in str(err.get("message")).lower())):
                    self.limit_n += 1
                    self.gap = min(MAX_GAP_S, self.gap * 1.5)
                    self.last_429 = (str((err or {}).get("message") or "") or r.text or "")[:160]
                    if tent < RETRY_429:
                        await self.sleep(1.0 * (2 ** tent))         # 1, 2, 4, 8 s
                        continue
                    raise RpcError("Alchemy: limite de pedidos (429) mesmo esperando · " + self.last_429)
                if err:
                    raise RpcError(f"Alchemy {method}: {str(err.get('message'))[:120]}")
                self.gap = max(MIN_GAP_S, self.gap * 0.97)
                return j.get("result")


def funder_of(tx: dict | None, wallet: str) -> str | None:
    """Quem mandou SOL para `wallet` nesta transação: a maior transferência de SOL (instruções e instruções internas) que chegou
    nela; se não houver instrução legível, a conta que mais perdeu SOL enquanto a carteira ganhou."""
    if not tx:
        return None
    msg = (tx.get("transaction") or {}).get("message") or {}
    meta = tx.get("meta") or {}
    ins = list(msg.get("instructions") or [])
    for g in meta.get("innerInstructions") or []:
        ins += list(g.get("instructions") or [])
    best = None
    for i in ins:
        p = i.get("parsed") if isinstance(i, dict) else None
        if not isinstance(p, dict) or p.get("type") not in ("transfer", "transferWithSeed", "createAccount", "createAccountWithSeed"):
            continue
        info = p.get("info") or {}
        dst, src = info.get("destination") or info.get("newAccount"), info.get("source")
        lam = int(info.get("lamports") or 0)
        if dst == wallet and src and src != wallet and lam > 0 and (best is None or lam > best[1]):
            best = (src, lam)
    if best:
        return best[0]
    keys = [k.get("pubkey") if isinstance(k, dict) else k for k in msg.get("accountKeys") or []]
    pre, post = meta.get("preBalances") or [], meta.get("postBalances") or []
    if wallet not in keys or not pre or len(pre) != len(post):
        return None
    d = [post[i] - pre[i] for i in range(len(pre))]
    wi = keys.index(wallet)
    if d[wi] <= 0:
        return None
    j = min(range(len(d)), key=lambda i: d[i])
    return keys[j] if d[j] < 0 and keys[j] != wallet else None


def build(mint: str, creator: str | None, holders: list[dict], launch_slot: int | None, creator_funder: str | None,
          creator_pct: float = 0.0, alert_pct: float = 20.0, bundle_lim: float = 25.0, now: float | None = None) -> dict:
    """Parte só de contas (testável sem rede). holders: [{wallet, pct, kind, first_slot, funder, age_s, old}]."""
    now = now or time.time()
    ws = [h for h in holders if h.get("kind") == "carteira"]
    progs = [h for h in holders if h.get("kind") != "carteira"]
    dev = set([creator]) if creator else set()
    roots = set([creator_funder]) if creator_funder else set()
    grow = True
    while grow:                                   # grupo do DEV: repete até não crescer
        grow = False
        for h in ws:
            w, f = h["wallet"], h.get("funder")
            if w in dev:
                continue
            if (f and (f in dev or f in roots)) or w in roots:
                dev.add(w)
                grow = True
    bundle = set()
    if launch_slot is not None:
        for h in ws:
            if h.get("first_slot") is not None and 0 <= h["first_slot"] - launch_slot <= LAUNCH_SLOTS and h["wallet"] != creator:
                bundle.add(h["wallet"])
    groups: dict[str, list] = {}
    for h in ws:
        if h.get("funder"):
            groups.setdefault(h["funder"], []).append(h)
    grupos = sorted([{"funder": f, "n": len(g), "pct": round(sum(x["pct"] for x in g), 2), "dev": f in dev or f in roots}
                     for f, g in groups.items() if len(g) >= 2], key=lambda x: -x["pct"])
    pct = lambda s: round(sum(h["pct"] for h in ws if h["wallet"] in s), 2)                # noqa: E731
    dev_in_top = any(h["wallet"] == creator for h in ws)
    cluster_pct = pct(dev) + (0.0 if dev_in_top else round(creator_pct, 2))
    bundle_pct = pct(bundle)
    real = pct(dev | bundle) + (0.0 if dev_in_top else round(creator_pct, 2))
    fmax = grupos[0] if grupos else None
    tem = [h for h in ws if h.get("first_slot") is not None or h.get("funder") or h.get("old")]
    if not ws:
        nivel, motivo = "sem dados", "nenhuma carteira de pessoa entre os maiores detentores"
    elif not tem:
        nivel, motivo = "sem dados", "não deu para ler as carteiras"
    elif real >= alert_pct or bundle_pct >= bundle_lim:
        nivel = "alto"
        motivo = (f"DEV + carteiras ligadas com {_p(real)} do total" if real >= alert_pct else f"bundle com {_p(bundle_pct)} do total")
    elif real >= alert_pct / 2 or (fmax and fmax["pct"] >= alert_pct):
        nivel = "médio"
        motivo = (f"DEV + carteiras ligadas com {_p(real)}" if real >= alert_pct / 2
                  else f"{fmax['n']} carteiras com a mesma origem têm {_p(fmax['pct'])} (pode ser corretora)")
    else:
        nivel, motivo = "baixo", f"DEV + carteiras ligadas com {_p(real)}"
    out_w = []
    for h in sorted(ws, key=lambda x: -x["pct"]):
        tags = []
        if h["wallet"] == creator:
            tags.append("dev")
        elif h["wallet"] in dev:
            tags.append("ligada ao dev")
        if h["wallet"] in bundle:
            tags.append("bundle")
        if h.get("funder") and len(groups.get(h["funder"]) or []) >= 2 and "ligada ao dev" not in tags:
            tags.append("mesma origem")
        if h.get("age_s") is not None and h["age_s"] < NEW_WALLET_S:
            tags.append("nova")
        out_w.append({"w": h["wallet"], "pct": round(h["pct"], 2), "tags": tags, "funder": h.get("funder"),
                      "bloco": (h["first_slot"] - launch_slot) if (h.get("first_slot") is not None and launch_slot is not None) else None,
                      "idade_h": round(h["age_s"] / 3600, 1) if h.get("age_s") is not None else None, "antiga": bool(h.get("old")),
                      "pend": bool(h.get("pend"))})
    return {"t": round(now), "nivel": nivel, "motivo": motivo, "real_dev_pct": real, "dev_pct": round(creator_pct, 2),
            "cluster_pct": cluster_pct, "cluster_n": len(dev - {creator}), "bundle_pct": bundle_pct, "bundle_n": len(bundle),
            "funder_max_pct": fmax["pct"] if fmax else 0.0, "funder_max_n": fmax["n"] if fmax else 0,
            "novas_n": sum(1 for h in ws if h.get("age_s") is not None and h["age_s"] < NEW_WALLET_S),
            "programas_pct": round(sum(h["pct"] for h in progs), 2), "carteiras_n": len(ws), "launch_slot": launch_slot,
            "grupos": grupos[:6], "carteiras": out_w}


def compact(s: dict | None) -> dict | None:
    """O que vai na lista de tokens e no relatório (sem a lista de carteiras)."""
    if not s:
        return None
    return {k: s.get(k) for k in ("t", "nivel", "motivo", "real_dev_pct", "dev_pct", "cluster_pct", "cluster_n", "bundle_pct", "bundle_n",
                                  "funder_max_pct", "funder_max_n", "novas_n", "erro", "parcial", "chamadas")}


async def _first(rpc: Rpc, addr: str) -> tuple[dict | None, bool]:
    """Transação mais antiga de um endereço (até SIG_LIMIT). (assinatura, tem mais que o limite?)"""
    sigs = await rpc.call("getSignaturesForAddress", [addr, {"limit": SIG_LIMIT, "commitment": "confirmed"}]) or []
    return (sigs[-1] if sigs else None), len(sigs) >= SIG_LIMIT


async def _funder(rpc: Rpc, wallet: str, now: float) -> dict:
    first, full = await _first(rpc, wallet)
    if full:
        return {"old": True}
    if not first:
        return {}
    tx = await rpc.call("getTransaction", [first["signature"], {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0,
                                                               "commitment": "confirmed"}])
    bt = first.get("blockTime") or (tx or {}).get("blockTime")
    return {"funder": funder_of(tx, wallet), "age_s": (now - bt) if bt else None}


DEADLINE_S = 20.0                   # 0.32.385 (pedido do dono): o primeiro resultado sai em até 20 s; o resto fica para depois


async def stage_a(rpc: Rpc, mint: str, creator: str | None, top_n: int = 15, now: float | None = None,
                  curve_pda: str | None = None, deadline: float | None = None, clock=time.monotonic) -> dict:
    """0.32.385: parte rápida (até DEADLINE_S): maiores detentores, donos, DEV, bloco de cada um (bundle) e quem financiou o DEV e
    as maiores carteiras enquanto der tempo. O que não coube fica em `pend` e termina depois (stage_b), sempre atrás dos tokens novos."""
    now = now or time.time()
    deadline = deadline if deadline is not None else clock() + DEADLINE_S
    st = {"mint": mint, "creator": creator, "creator_src": "boost" if creator else None, "now": now, "n0": rpc.n,
          "launch_slot": None, "creator_pct": 0.0, "creator_funder": None, "creator_done": not creator, "rows": [], "pend": []}
    if not creator and curve_pda:        # 0.32.383: o BOOST ainda não leu o DEV → lê aqui, na conta da curva (pela Alchemy)
        try:
            import base64
            from .boostmig import creator_of
            acc = ((await rpc.call("getAccountInfo", [curve_pda, {"encoding": "base64"}])) or {}).get("value")
            c = creator_of(base64.b64decode(acc["data"][0])) if acc else None
            if c:
                st.update(creator=c, creator_src="alchemy", creator_done=False)
        except RpcError:
            raise
        except Exception:
            pass
    creator = st["creator"]
    sup = await rpc.call("getTokenSupply", [mint])
    supply = float(((sup or {}).get("value") or {}).get("uiAmountString") or 0)
    if supply <= 0:
        raise RpcError("não li o total do token")
    la = ((await rpc.call("getTokenLargestAccounts", [mint, {"commitment": "confirmed"}])) or {}).get("value") or []
    la = la[:max(1, int(top_n))]
    atas = [x["address"] for x in la]
    infos = ((await rpc.call("getMultipleAccounts", [atas, {"encoding": "jsonParsed"}])) or {}).get("value") or []
    rows = []
    for x, inf in zip(la, infos):
        own = ((((inf or {}).get("data") or {}).get("parsed") or {}).get("info") or {}).get("owner")
        if own:
            rows.append({"ata": x["address"], "wallet": own, "pct": float(x.get("uiAmountString") or x.get("uiAmount") or 0) / supply * 100})
    owners = list({r["wallet"] for r in rows})
    oinf = ((await rpc.call("getMultipleAccounts", [owners, {"encoding": "base64", "dataSlice": {"offset": 0, "length": 0}}])) or {}).get("value") or []
    prog = {w: (i or {}).get("owner") for w, i in zip(owners, oinf)}
    for r in rows:                      # dono = programa (pool, curva, PDA) → fora da conta das pessoas
        r["kind"] = "carteira" if prog.get(r["wallet"]) in (None, SYSTEM_PROGRAM) else "programa"
    st["rows"] = rows
    if creator:                         # conta de token do DEV: primeiro bloco = lançamento; saldo dele (mesmo fora dos maiores)
        ca = ((await rpc.call("getTokenAccountsByOwner", [creator, {"mint": mint}, {"encoding": "jsonParsed"}])) or {}).get("value") or []
        for a in ca:
            amt = (((((a.get("account") or {}).get("data") or {}).get("parsed") or {}).get("info") or {}).get("tokenAmount") or {})
            st["creator_pct"] += float(amt.get("uiAmountString") or 0) / supply * 100
        if ca:
            f, _ = await _first(rpc, ca[0]["pubkey"])
            st["launch_slot"] = (f or {}).get("slot")
    people = sorted([r for r in rows if r["kind"] == "carteira"], key=lambda r: -r["pct"])
    for r in people:                    # bloco de cada carteira (bundle): 1 pedido cada
        if clock() > deadline:
            break
        try:
            f, full = await _first(rpc, r["ata"])
            r["first_slot"] = None if full else (f or {}).get("slot")
            r["slot_ok"] = True
        except RpcError:
            break
    if st["launch_slot"] is None:
        slots = [r["first_slot"] for r in people if r.get("first_slot") is not None]
        st["launch_slot"] = min(slots) if slots else None
    st["pend"] = (["__dev__"] if not st["creator_done"] else []) + [r["wallet"] for r in people]
    for r in people:
        r["pend"] = True
    await stage_b(rpc, st, should_stop=lambda: clock() > deadline)
    return st


async def stage_b(rpc: Rpc, st: dict, should_stop=lambda: False) -> int:
    """0.32.385: termina o que ficou pendente (quem financiou cada carteira e o bloco que faltou), uma carteira por vez, parando
    quando `should_stop()` disser que há token novo esperando. Devolve quantas carteiras terminou."""
    by = {r["wallet"]: r for r in st["rows"]}
    feitos = 0
    while st["pend"] and not should_stop():
        w = st["pend"][0]
        try:
            if w == "__dev__":
                st["creator_funder"] = (await _funder(rpc, st["creator"], st["now"])).get("funder")
                st["creator_done"] = True
            else:
                r = by.get(w) or {}
                if not r.get("slot_ok"):
                    f, full = await _first(rpc, r["ata"])
                    r["first_slot"] = None if full else (f or {}).get("slot")
                    r["slot_ok"] = True
                r.update(await _funder(rpc, w, st["now"]))
                r["pend"] = False
        except RpcError:
            return feitos                  # limite da Alchemy: tenta de novo na próxima volta
        except Exception:
            if w != "__dev__":
                (by.get(w) or {})["pend"] = False
            else:
                st["creator_done"] = True
        st["pend"].pop(0)
        feitos += 1
    return feitos


def result(st: dict, alert_pct: float = 20.0, bundle_lim: float = 25.0, rpc_n: int | None = None) -> dict:
    out = build(st["mint"], st["creator"], st["rows"], st["launch_slot"], st["creator_funder"], st["creator_pct"], alert_pct, bundle_lim, st["now"])
    out["creator_funder"] = st["creator_funder"]
    out["creator"], out["creator_src"] = st["creator"], st["creator_src"]
    out["parcial"] = len(st["pend"])
    if rpc_n is not None:
        out["chamadas"] = rpc_n - st["n0"]
    return out


async def analyze(rpc: Rpc, mint: str, creator: str | None, top_n: int = 15, alert_pct: float = 20.0, bundle_lim: float = 25.0,
                  now: float | None = None, curve_pda: str | None = None) -> dict:
    """Análise inteira de uma vez (sem prazo) — usada nos testes e como referência."""
    st = await stage_a(rpc, mint, creator, top_n, now, curve_pda, deadline=float("inf"))
    return result(st, alert_pct, bundle_lim, rpc.n)
