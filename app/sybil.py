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
- Carteira com 1.000+ transações: a origem do dinheiro não é procurada (seria caro) e ela fica como "antiga".
- "Mesma origem" pode ser uma corretora (muita gente saca da mesma carteira quente da Binance, por exemplo). Por isso a origem
  comum SEM ligação com o DEV só aparece como informação ("mesma origem"); o alerta usa o grupo do DEV e o bundle.
- Só mede e avisa. A trava (barrar a compra) existe na tela, mas está desligada nesta versão.
"""
from __future__ import annotations

import asyncio
import time

SYSTEM_PROGRAM = "11111111111111111111111111111111"
LAUNCH_SLOTS = 2                    # recebeu o token até 2 blocos depois do lançamento = comprou junto (bundle)
SIG_LIMIT = 1000
PARALLEL = 5                        # pedidos simultâneos à Alchemy
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
    def __init__(self, http, url: str):
        self.http, self.url, self.n = http, url, 0
        self.sem = asyncio.Semaphore(PARALLEL)

    async def call(self, method: str, params: list):
        async with self.sem:
            self.n += 1
            r = await self.http.post(self.url, timeout=15, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
            if r.status_code == 429:
                raise RpcError("Alchemy: limite de pedidos (429)")
            if r.status_code in (401, 403):
                raise RpcError(f"Alchemy recusou a chave (HTTP {r.status_code})")
            j = r.json()
            if j.get("error"):
                raise RpcError(f"Alchemy {method}: {str((j['error'] or {}).get('message'))[:120]}")
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
                      "idade_h": round(h["age_s"] / 3600, 1) if h.get("age_s") is not None else None, "antiga": bool(h.get("old"))})
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
                                  "funder_max_pct", "funder_max_n", "novas_n", "erro")}


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


async def analyze(rpc: Rpc, mint: str, creator: str | None, top_n: int = 15, alert_pct: float = 20.0, bundle_lim: float = 25.0,
                  now: float | None = None) -> dict:
    now = now or time.time()
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
    # conta de token do DEV: primeiro bloco = lançamento; saldo dele (mesmo fora dos maiores)
    launch_slot, creator_pct, creator_funder = None, 0.0, None
    if creator:
        ca = ((await rpc.call("getTokenAccountsByOwner", [creator, {"mint": mint}, {"encoding": "jsonParsed"}])) or {}).get("value") or []
        for a in ca:
            amt = (((((a.get("account") or {}).get("data") or {}).get("parsed") or {}).get("info") or {}).get("tokenAmount") or {})
            creator_pct += float(amt.get("uiAmountString") or 0) / supply * 100
        if ca:
            f, _ = await _first(rpc, ca[0]["pubkey"])
            launch_slot = (f or {}).get("slot")
    people = [r for r in rows if r["kind"] == "carteira"]

    async def one(r):
        try:
            f, full = await _first(rpc, r["ata"])
            r["first_slot"] = None if full else (f or {}).get("slot")
            r.update(await _funder(rpc, r["wallet"], now))
        except RpcError:
            raise
        except Exception:
            pass
    await asyncio.gather(*(one(r) for r in people))
    if creator:
        try:
            creator_funder = (await _funder(rpc, creator, now)).get("funder")
        except RpcError:
            raise
        except Exception:
            creator_funder = None
    if launch_slot is None:
        slots = [r["first_slot"] for r in people if r.get("first_slot") is not None]
        launch_slot = min(slots) if slots else None
    out = build(mint, creator, rows, launch_slot, creator_funder, creator_pct, alert_pct, bundle_lim, now)
    out["creator_funder"] = creator_funder
    out["chamadas"] = rpc.n
    return out
