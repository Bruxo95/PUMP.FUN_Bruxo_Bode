"""0.32.373 (pedido do dono, 18/11/2026): BOOST da migração, trazido do hermes-jev-trader (guia "BOOST da pump.fun", versão de
referência 2026-11-18.15) e adaptado para cá (vários usuários, Supabase, carteira fictícia de cada um).

A estratégia
- Quando um token da pump.fun completa a curva, ele migra para a PumpSwap. Nos ~5 min seguintes ("BOOST") costuma haver
  pressão de compra. Entra no começo (até X% da janela), depois dos filtros anti-golpe, e sai antes do fim (Y% da janela).
- O progresso é ESTIMADO pelo tempo desde a migração: progresso = (agora − t0) ÷ JANELA_S × 100. Não existe API que diga
  "o BOOST acabou".

Divisão (diferente do original, que era de um usuário só)
- Parte COMPARTILHADA (esta classe, uma para o servidor): ouve a migração (PumpPortal subscribeMigration), lê o DEV na conta da
  curva, confere a trava de venda, observa o preço a cada volta, acompanha topo e dump por 30 min e mantém as listas de DEV scam
  e DEV VIP. Guardada no Supabase (boost_tokens 24 h, boost_devs).
- Parte de CADA USUÁRIO (decide()): os limites de entrada são do usuário (opções pump_bm_*); quem passa compra pelo mesmo
  caminho das outras abas (manual_buy, origem "boostmig"), com as regras de saída gravadas na posição. FICTÍCIA por padrão;
  REAL só com a chave "Também na REAL" da aba E a execução real ligada (começa desligada).
"""
from __future__ import annotations

import base64
import time

JANELA_S = 300                     # duração estimada do BOOST
BUYS_HIST_MAX = 130                # 0.32.380: leituras das compras guardadas por token (~30 min a cada 15 s)
TRACK_S = 30 * 60                  # acompanha topo e dump de todo token por 30 min (entrando ou não)
TRACK_EVERY_S = 15
KEEP_S = 86400                     # histórico de 24 h
OBS_MAX_PCT = 60                   # amostra o preço até 60% da janela (o limite de entrada do usuário vai até 60)
SCAM_DUMP_PCT, SCAM_DUMP_MIN = 70.0, 10.0
TWIN_MIN = 10.0
SCAM_KEEP_S = 7 * 86400
VIP_KEEP_S = 30 * 86400

# 0.32.375 (pedido do dono: "as regras do BOOST não têm as mesmas opções"): regras do DEV scam/VIP editáveis na tela, como no
# original. A lista de DEVs é uma só para o servidor, então vale o último valor que um admin salvou (hub.bm_cfg).
CFG_KEYS = {"pump_bm_hist_min": ("HIST_MIN", 1.0), "pump_bm_scam_dump_pct": ("SCAM_DUMP_PCT", 1.0), "pump_bm_scam_dump_min": ("SCAM_DUMP_MIN", 1.0),
            "pump_bm_twin_min": ("TWIN_MIN", 1.0), "pump_bm_scam_keep_d": ("SCAM_KEEP_S", 86400.0),
            "pump_bm_vip_keep_d": ("VIP_KEEP_S", 86400.0),
            # 0.32.382: carteiras ligadas ao DEV (Alchemy) — uma análise por token para o servidor todo
            "pump_bm_sybil_on": ("SYBIL_ON", 1.0), "pump_bm_sybil_top": ("SYBIL_TOP", 1.0), "pump_bm_sybil_max_h": ("SYBIL_MAX_H", 1.0),
            "pump_bm_sybil_alert_pct": ("SYBIL_ALERT_PCT", 1.0), "pump_bm_sybil_bundle_pct": ("SYBIL_BUNDLE_PCT", 1.0)}
SYBIL_ON, SYBIL_TOP, SYBIL_MAX_H, SYBIL_ALERT_PCT, SYBIL_BUNDLE_PCT = 1.0, 15.0, 30.0, 20.0, 25.0
CFG_KEYS["pump_bm_alchemy_backup"] = ("ALCHEMY_BACKUP", 1.0)
ALCHEMY_BACKUP = 1.0                # 0.32.384: Alchemy como reserva da leitura do DEV e da trava quando o RPC do sistema não responde
DEV_WAIT_S = 30.0                   # 0.32.384: sem DEV lido depois disso, segue sem o filtro de DEV scam (antes esperava para sempre)
SAFETY_WAIT_S = 45.0                # 0.32.384: sem trava lida depois disso, vale como "não deu para conferir"


def apply_cfg(cfg: dict) -> dict:
    """{opção pump_bm_*: valor} → constantes do módulo (dias viram segundos). Devolve o que ficou valendo, nas unidades da tela."""
    g = globals()
    out = {}
    for key, (name, mul) in CFG_KEYS.items():
        v = cfg.get(key)
        if v is not None:
            try:
                g[name] = float(v) * mul
            except (TypeError, ValueError):
                pass
        out[key] = round(g[name] / mul, 2)
    return out
SAFETY_TTL_S = 600

# 0.32.378 (pedido do dono, 19/11): todo token que migra (entrando ou não) é analisado HIST_MIN minutos depois da migração e
# guardado para sempre em boost_history: série de preço, preço em cada minuto (MARKS), topo, dump, compras/vendas, DEV, trava e
# o nosso resultado. É a base para medir o tempo de cada token (quando sobe, quando despeja) e ajustar o BOOST.
HIST_MIN = 20.0
MARKS = (1, 2, 3, 4, 5, 7, 10, 15, 20)
CUSTO_PCT = 1.5                     # custo de ida e volta na PumpSwap usado nas contas do histórico (0,3% por lado + rede/slippage)
SERIE_MAX = 200
SAFETY_TRIES = 4
SOL_MINT = "So11111111111111111111111111111111111111112"
QUOTE_LAMPORTS = 10_000_000        # 0,01 SOL: cotação de compra da observação (como no original)


def finite(x):
    """Troca infinito/NaN por None em toda a resposta (o JSON da API não aceita esses números)."""
    if isinstance(x, float):
        return x if x == x and x not in (float("inf"), float("-inf")) else None
    if isinstance(x, dict):
        return {k: finite(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [finite(v) for v in x]
    return x


def norm(v) -> str:
    return "".join(ch for ch in str(v or "").lower() if ch.isalnum())


def short(m: str) -> str:
    return (m[:4] + "…" + m[-4:]) if m and len(m) > 10 else (m or "?")


def med(xs: list) -> float:
    s = sorted(xs)
    return s[len(s) // 2]


def track_point(b: dict, px: float | None, now: float) -> None:
    """Topo e fundo do token (entrando ou não), em % do 1º preço visto e segundos desde a migração. "Full dump" = o menor
    preço DEPOIS do topo: quanto caiu do topo e quando."""
    if not px or px <= 0:
        return
    t = round(now - b["t0"])
    tr = b.setdefault("trk", {"p0": px, "t0": t, "hi": px, "hi_t": t, "lo": px, "lo_t": t, "dd": px, "dd_t": t, "n": 0})
    tr["n"] += 1
    se = b.setdefault("serie", [])                                           # 0.32.378: série para o histórico
    if len(se) < SERIE_MAX:
        se.append([t, px])
    if px > tr["hi"]:
        tr["hi"], tr["hi_t"] = px, t
        tr["dd"], tr["dd_t"] = px, t
    if px < tr["dd"]:
        tr["dd"], tr["dd_t"] = px, t
    if px < tr["lo"]:
        tr["lo"], tr["lo_t"] = px, t
    p0 = tr["p0"]
    b["track"] = {"top_pct": round((tr["hi"] / p0 - 1) * 100, 1), "top_s": tr["hi_t"],
                  "bottom_pct": round((tr["lo"] / p0 - 1) * 100, 1), "bottom_s": tr["lo_t"],
                  "dump_pct": round((tr["dd"] / tr["hi"] - 1) * 100, 1), "dump_s": tr["dd_t"],
                  "dump_dur_s": max(0, tr["dd_t"] - tr["hi_t"]), "now_pct": round((px / p0 - 1) * 100, 1),
                  "watched_s": t, "n": tr["n"]}


def safety_of(acc: dict | None) -> dict:
    """Trava de venda pela conta do mint (jsonParsed): freeze/mint authority e extensões Token-2022 perigosas."""
    res = {"ok": None, "why": None}
    try:
        info = acc["data"]["parsed"]["info"]
    except Exception:
        res["why"] = "não deu para conferir o token"
        return res
    bad = []
    if info.get("freezeAuthority"):
        bad.append("freeze authority ativa (pode congelar e travar a venda)")
    if info.get("mintAuthority"):
        bad.append("mint authority ativa (pode criar tokens sem limite)")
    for e in info.get("extensions") or []:
        name, st = e.get("extension"), e.get("state") or {}
        if name == "transferHook" and st.get("programId"):
            bad.append("transfer hook (programa pode bloquear a venda)")
        elif name == "permanentDelegate" and st.get("delegate"):
            bad.append("delegado permanente (pode tirar tokens da sua carteira)")
        elif name == "nonTransferable":
            bad.append("token não transferível")
        elif name == "defaultAccountState" and str(st.get("accountState")).lower() == "frozen":
            bad.append("contas nascem congeladas")
        elif name == "pausableConfig" and st.get("paused"):
            bad.append("token pausado")
        elif name == "transferFeeConfig":
            fee = (st.get("newerTransferFee") or {}).get("transferFeeBasisPoints") or 0
            if fee and int(fee) > 100:
                bad.append(f"taxa de transferência {int(fee) / 100:.1f}%")
    res["ok"], res["why"] = not bad, "; ".join(bad) or None
    return res


def creator_of(raw: bytes) -> str | None:
    """DEV = bytes 49..81 da conta da curva da pump.fun (PDA "bonding-curve")."""
    if len(raw) < 81 or not any(raw[49:81]):
        return None
    try:
        from solders.pubkey import Pubkey
        return str(Pubkey.from_bytes(raw[49:81]))
    except Exception:
        return None


def price_at(serie: list, sec: float, tol: float = 45.0):
    """Preço da série no segundo `sec` desde a migração: o último ponto até lá (ou o primeiro depois, se estiver a até `tol` s)."""
    antes = [p for p in serie if p[0] <= sec]
    if antes and sec - antes[-1][0] <= max(tol, 90):
        return antes[-1][1]
    depois = [p for p in serie if p[0] > sec]
    return depois[0][1] if depois and depois[0][0] - sec <= tol else None


def classe(top: float | None, dump: float | None, dump_s: float | None, fim: float | None) -> str:
    if dump is not None and dump <= -SCAM_DUMP_PCT and (dump_s or 1e9) <= HIST_MIN * 60:
        return "despejou"
    if fim is not None and fim >= 20:
        return "subiu"
    if fim is not None and fim <= -30:
        return "caiu"
    if top is None:
        return "sem preço"
    return "lateral"


def history_row(b: dict, now: float, scam: dict | None = None) -> dict:
    """Registro permanente do token aos HIST_MIN min (entrando ou não)."""
    se = [p for p in (b.get("serie") or []) if p[0] <= HIST_MIN * 60 + 30]
    p0 = se[0][1] if se else None
    pts = [p for p in se if p[1] and p[1] > 0]
    hi = max(pts, key=lambda p: p[1]) if pts else None
    dd = min([p for p in pts if hi and p[0] >= hi[0]], key=lambda p: p[1]) if hi else None
    lo = min(pts, key=lambda p: p[1]) if pts else None
    pct = lambda x: round((x / p0 - 1) * 100, 1) if (x and p0) else None               # noqa: E731
    marks = {str(m): pct(price_at(se, m * 60)) for m in MARKS if m <= HIST_MIN}
    fim = pct(pts[-1][1]) if pts else None
    users = b.get("users") or {}
    entrou = [u for u in users.values() if u.get("estado") == "entrou"]
    fora = [u.get("motivo") for u in users.values() if u.get("estado") == "fora" and u.get("motivo")]
    res = b.get("result") or {}
    top, dump = pct(hi[1]) if hi else None, (round((dd[1] / hi[1] - 1) * 100, 1) if (hi and dd) else None)
    row = {"mint": b["mint"], "creator": b.get("creator"), "symbol": b.get("symbol"), "name": b.get("name"),
           "t0": b["t0"], "analisado_t": now, "minutos": HIST_MIN,
           "top_pct": top, "top_s": hi[0] if hi else None, "dump_pct": dump, "dump_s": dd[0] if dd else None,
           "dump_dur_s": (dd[0] - hi[0]) if (hi and dd) else None, "fundo_pct": pct(lo[1]) if lo else None, "fundo_s": lo[0] if lo else None,
           "fim_pct": fim, "marks": marks, "classe": classe(top, dump, dd[0] if dd else None, fim),
           "p0": p0, "p0_s": se[0][0] if se else None, "pontos": len(pts),
           "buys_m5": b.get("buys_m5"), "sells_m5": b.get("sells_m5"), "mcap_sol": b.get("mcap_sol"), "top10_pct": b.get("top10_pct"),
           "safety_ok": b.get("safety_ok"), "safety_why": b.get("safety_why"), "dev_n": b.get("dev_n"),
           "scam": bool(scam), "scam_why": (scam or {}).get("why"), "trend_pct": b.get("trend_pct"), "drawdown_pct": b.get("drawdown_pct"),
           "entry": b.get("entry"), "sybil": b.get("sybil"), "entrou": len(entrou), "fora_motivo": fora[0] if fora else None,
           "pnl_sol": res.get("pnl_sol"), "pnl_pct": res.get("pnl_pct"), "saida": res.get("why"),
           "serie": [[int(p[0]), p[1]] for p in se]}
    return row


def _q(xs: list, q: float):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    return round(xs[min(len(xs) - 1, int(q * (len(xs) - 1) + 0.5))], 1)


def hist_study(rows: list[dict]) -> dict:
    """Métricas do histórico: curva por minuto, quando o dump acontece, entrar no minuto X e sair no Y, comparação por grupo."""
    rs = [r for r in rows if r.get("p0")]
    n = len(rs)
    out = {"n": len(rows), "com_preco": n, "custo_pct": CUSTO_PCT}
    if not n:
        return out
    cls = {}
    for r in rows:
        cls[r.get("classe") or "?"] = cls.get(r.get("classe") or "?", 0) + 1
    out["classes"] = cls
    out["kpi"] = {"top_med": _q([r.get("top_pct") for r in rs], .5), "top_s_med": _q([r.get("top_s") for r in rs], .5),
                  "dump_med": _q([r.get("dump_pct") for r in rs], .5), "dump_s_med": _q([r.get("dump_s") for r in rs if (r.get("dump_pct") or 0) <= -30], .5),
                  "fim_med": _q([r.get("fim_pct") for r in rs], .5), "fim_pos": round(sum(1 for r in rs if (r.get("fim_pct") or 0) > 0) / n * 100),
                  "despejou": round(cls.get("despejou", 0) / len(rows) * 100)}
    curva = []
    for m in MARKS:
        v = [(r.get("marks") or {}).get(str(m)) for r in rs]
        v = [x for x in v if x is not None]
        if v:
            curva.append({"min": m, "n": len(v), "p25": _q(v, .25), "med": _q(v, .5), "p75": _q(v, .75), "pos": round(sum(1 for x in v if x > 0) / len(v) * 100)})
    out["curva"] = curva
    faixas = [(0, 60, "até 1 min"), (60, 120, "1–2 min"), (120, 300, "2–5 min"), (300, 600, "5–10 min"), (600, 1200, "10–20 min"), (1200, 1e9, "depois")]
    dumps = [r for r in rs if (r.get("dump_pct") or 0) <= -30 and r.get("dump_s") is not None]
    out["quando_dump"] = [{"faixa": nome, "n": sum(1 for r in dumps if a <= r["dump_s"] < b_), "pct": round(sum(1 for r in dumps if a <= r["dump_s"] < b_) / len(dumps) * 100) if dumps else 0}
                          for a, b_, nome in faixas]
    out["quando_topo"] = [{"faixa": nome, "n": sum(1 for r in rs if r.get("top_s") is not None and a <= r["top_s"] < b_)} for a, b_, nome in faixas]
    mat = []
    for e in (1, 2, 3):
        linha = {"entra": e, "sai": {}}
        for x in (3, 4, 5, 7, 10, 15, 20):
            if x <= e:
                continue
            v = []
            for r in rs:
                pe, px = (r.get("marks") or {}).get(str(e)), (r.get("marks") or {}).get(str(x))
                if pe is not None and px is not None:
                    v.append(((1 + px / 100) / (1 + pe / 100) - 1) * 100 - CUSTO_PCT)
            if v:
                linha["sai"][str(x)] = {"n": len(v), "media": round(sum(v) / len(v), 1), "med": _q(v, .5), "pos": round(sum(1 for y in v if y > 0) / len(v) * 100)}
        mat.append(linha)
    out["entra_sai"] = mat

    def grupo(nome, f):
        g = [r for r in rs if f(r)]
        if not g:
            return None
        return {"grupo": nome, "n": len(g), "top_med": _q([r.get("top_pct") for r in g], .5), "fim_med": _q([r.get("fim_pct") for r in g], .5),
                "despejou": round(sum(1 for r in g if r.get("classe") == "despejou") / len(g) * 100),
                "fim_pos": round(sum(1 for r in g if (r.get("fim_pct") or 0) > 0) / len(g) * 100)}
    gs = [grupo("Todos", lambda r: True), grupo("DEV scam", lambda r: r.get("scam")), grupo("Sem marca de scam", lambda r: not r.get("scam")),
          grupo("Com trava de venda", lambda r: r.get("safety_ok") is False), grupo("Sem trava (conferido)", lambda r: r.get("safety_ok") is True),
          grupo("100+ compras em 5 min", lambda r: (r.get("buys_m5") or 0) >= 100), grupo("Menos de 100 compras", lambda r: (r.get("buys_m5") or 0) < 100),
          grupo("Compras ≥ vendas × 1,2", lambda r: (r.get("buys_m5") or 0) >= (r.get("sells_m5") or 0) * 1.2),
          grupo("DEV com 2+ tokens em 24 h", lambda r: (r.get("dev_n") or 1) >= 2), grupo("Alguém entrou", lambda r: (r.get("entrou") or 0) > 0),
          # 0.32.382: carteiras ligadas ao DEV (Alchemy)
          grupo("Carteiras: alerta alto", lambda r: (r.get("sybil") or {}).get("nivel") == "alto"),
          grupo("Carteiras: alerta médio", lambda r: (r.get("sybil") or {}).get("nivel") == "médio"),
          grupo("Carteiras: sem alerta", lambda r: (r.get("sybil") or {}).get("nivel") == "baixo"),
          grupo("Bundle 10%+ do total", lambda r: ((r.get("sybil") or {}).get("bundle_pct") or 0) >= 10)]
    out["grupos"] = [g for g in gs if g]
    devs = {}
    for r in rows:
        if r.get("creator"):
            d = devs.setdefault(r["creator"], {"creator": r["creator"], "n": 0, "despejou": 0, "tops": [], "fims": [], "ult": 0, "symbols": []})
            d["n"] += 1
            d["despejou"] += 1 if r.get("classe") == "despejou" else 0
            d["tops"].append(r.get("top_pct"))
            d["fims"].append(r.get("fim_pct"))
            d["ult"] = max(d["ult"], r.get("t0") or 0)
            d["symbols"].append(r.get("symbol"))
    out["devs"] = sorted([{"creator": d["creator"], "n": d["n"], "despejou_pct": round(d["despejou"] / d["n"] * 100), "top_med": _q(d["tops"], .5),
                           "fim_med": _q(d["fims"], .5), "ult": d["ult"], "symbols": [x for x in d["symbols"] if x][-5:]} for d in devs.values() if d["n"] >= 2],
                         key=lambda x: (-x["n"], x["despejou_pct"]))[:100]
    return out


class BoostMig:
    def __init__(self, svc=None, clock=time.time):
        self.svc = svc                         # PumpFun de serviço do monitor (tokens, RPC, DexScreener e cotação compartilhados)
        self.clock = clock
        self.items: dict[str, dict] = {}
        self.scam_devs: dict[str, dict] = {}
        self.dev_book: dict[str, dict] = {}
        self.dirty: set[str] = set()
        self.dirty_devs: set[str] = set()
        self.st = {"migracoes": 0, "ultima": None, "erro": None, "rpc_falhou": 0, "cotacoes": 0, "sem_cotacao": 0}
        self.rpc_multi = None                  # 0.32.376: o hub põe aqui o RPC do sistema (Helius) na frente do público
        self.rpc_backup = None                 # 0.32.384: reserva pela Alchemy (só quando o do sistema não responde)

    # ------------------------------------------------------------------ eventos
    @property
    def tokens(self) -> dict:
        return getattr(self.svc, "tokens", None) or {}

    def on_migration(self, ev: dict, t: float | None = None) -> dict | None:
        mint = str(ev.get("mint") or "")
        if not mint or mint in self.items:
            return None
        t = t or self.clock()
        tk = self.tokens.get(mint) or {}
        b = {"mint": mint, "t0": t, "pool": ev.get("pool"), "signature": ev.get("signature"), "status": "BOOST ativo",
             "symbol": tk.get("symbol") or ev.get("symbol"), "name": tk.get("name") or ev.get("name"), "users": {}}
        self.items[mint] = b
        if self.svc is not None:
            tkm = self.svc.tokens.setdefault(mint, {"created_t": t})
            tkm["pool"] = "pumpswap"
        self.st["migracoes"] += 1
        self.st["ultima"] = t
        self.dirty.add(mint)
        return b

    def progress(self, b: dict, now: float | None = None) -> float:
        return max(0.0, min(100.0, ((now or self.clock()) - b["t0"]) / JANELA_S * 100))

    # ------------------------------------------------------------------ nomes, cópias, DEV
    def name_keys(self, mint: str, b: dict | None = None) -> set:
        b = b or self.items.get(mint) or {}
        tk = self.tokens.get(mint) or {}
        return {norm(x) for x in (b.get("symbol"), b.get("name"), tk.get("symbol"), tk.get("name")) if norm(x)}

    def twins(self, mint: str, b: dict) -> list[str]:
        """Outros tokens com o MESMO nome que migraram a menos de 10 min deste (cópias lançadas juntas = golpe)."""
        keys = self.name_keys(mint, b)
        if not keys:
            return []
        return [m2 for m2, b2 in self.items.items()
                if m2 != mint and abs(b2["t0"] - b["t0"]) <= TWIN_MIN * 60 and keys & self.name_keys(m2, b2)]

    def repeat(self, mint: str, b: dict) -> dict | None:
        """O mesmo nome/ticker migrou ANTES nas últimas 24 h (ou alguém já entrou nele)?"""
        keys = self.name_keys(mint, b)
        if not keys:
            return None
        n = 0
        for m2, b2 in self.items.items():
            if m2 == mint or abs(b["t0"] - b2["t0"]) > KEEP_S:
                continue
            if b2["t0"] >= b["t0"] and not any(u.get("estado") == "entrou" for u in (b2.get("users") or {}).values()):
                continue
            if keys & self.name_keys(m2, b2):
                n += 1
        return {"n": n, "name": b.get("symbol") or b.get("name")} if n else None

    def scam_of(self, mint: str, b: dict) -> dict | None:
        d = self.scam_devs.get(b.get("creator") or "")
        if not d:
            return None
        other = {m: x for m, x in (d.get("mints") or {}).items() if m != mint}
        return next(iter(other.values()), None) if other else None

    def dev_stats(self, cr: str | None) -> dict | None:
        d = self.dev_book.get(cr or "")
        if not d:
            return None
        ms = list((d.get("mints") or {}).values())
        w = sum(1 for x in ms if (x.get("pnl_sol") or 0) > 0)
        pnl = sum(float(x.get("pnl_sol") or 0) for x in ms)
        return {"n": len(ms), "wins": w, "losses": len(ms) - w, "pnl_sol": round(pnl, 6),
                "vip": w >= 1 and pnl > 0 and cr not in self.scam_devs, "symbols": [x.get("symbol") for x in ms][-6:], "t": d.get("t")}

    def scam_mark(self, now: float) -> None:
        """DEV scam: trava de venda, full dump rápido (−70% do topo até 10 min depois da migração) ou cópias com o mesmo nome
        migrando juntas. Lançar muitos tokens NÃO marca ninguém."""
        tw = {}
        for m, b in self.items.items():
            x = self.twins(m, b)
            if x:
                gap = max(abs(self.items[y]["t0"] - b["t0"]) for y in x)
                tw[m] = f"cópias: {len(x) + 1} tokens {b.get('symbol') or '?'} migraram em {gap / 60:.0f} min"
        for m, b in self.items.items():
            cr = b.get("creator")
            if not cr or (self.scam_devs.get(cr) or {}).get("mints", {}).get(m):
                continue
            why = tw.get(m)
            if b.get("safety_ok") is False:
                why = "trava de venda" + (f" ({b.get('safety_why')})" if b.get("safety_why") else "")
            k = b.get("track") or {}
            if not why and k.get("n", 0) > 1 and k.get("dump_pct", 0) <= -SCAM_DUMP_PCT and k.get("dump_s", 1e9) <= SCAM_DUMP_MIN * 60:
                why = f"full dump {k['dump_pct']:.0f}% aos {k['dump_s'] // 60:.0f} min {k['dump_s'] % 60:.0f} s"
            if why:
                d = self.scam_devs.setdefault(cr, {"t": now, "mints": {}})
                d["t"] = now
                d["mints"][m] = {"symbol": b.get("symbol"), "why": why, "t": now}
                d["why"], d["symbol"] = why, b.get("symbol")
                self.dirty_devs.add(cr)
        for cr in [c for c, d in self.scam_devs.items() if now - d.get("t", 0) > SCAM_KEEP_S]:
            del self.scam_devs[cr]
            self.dirty_devs.add(cr)
        for cr, d in list(self.dev_book.items()):                          # livro do VIP: resultado guardado por VIP_KEEP_S
            ms = {m: x for m, x in (d.get("mints") or {}).items() if now - float(x.get("t") or now) <= VIP_KEEP_S}
            if len(ms) != len(d.get("mints") or {}):
                self.dirty_devs.add(cr)
                if ms:
                    d["mints"] = ms
                else:
                    del self.dev_book[cr]

    def vip_note(self, mint: str, pnl_sol: float, pnl_pct: float | None, real: bool, now: float) -> None:
        """Resultado de um BOOST fechado (de qualquer conta) vai para o livro do DEV. VIP = 1+ ganho e saldo > 0."""
        b = self.items.get(mint) or {}
        cr = b.get("creator")
        if not cr or (self.dev_book.get(cr) or {}).get("mints", {}).get(mint):
            return
        d = self.dev_book.setdefault(cr, {"mints": {}})
        d["mints"][mint] = {"symbol": b.get("symbol"), "pnl_sol": round(pnl_sol, 6), "pnl_pct": pnl_pct, "real": real, "t": now}
        d["t"] = now
        self.dirty_devs.add(cr)

    def dev_hist(self, now: float) -> None:
        by: dict = {}
        for m, b in self.items.items():
            if b.get("creator"):
                by.setdefault(b["creator"], []).append((m, b))
        for m, b in self.items.items():
            cr = b.get("creator")
            if not cr:
                continue
            others = sorted([(m2, b2) for m2, b2 in by.get(cr, []) if m2 != m], key=lambda x: -x[1]["t0"])
            b["dev_n"] = len(others) + 1
            b["dev_hist"] = [{"symbol": b2.get("symbol") or short(m2), "ago_s": round(now - b2["t0"]),
                              "top_pct": (b2.get("track") or {}).get("top_pct"), "dump_pct": (b2.get("track") or {}).get("dump_pct"),
                              "dump_s": (b2.get("track") or {}).get("dump_s"), "lock": b2.get("safety_ok") is False,
                              "pnl_pct": (b2.get("result") or {}).get("pnl_pct")} for m2, b2 in others[:8]]
            sd = self.scam_devs.get(cr)
            b["dev_scam"] = {"why": sd.get("why"), "symbol": sd.get("symbol"), "n": len(sd.get("mints") or {})} if sd else None
            b["dev_rec"] = self.dev_stats(cr)

    def dev_action(self, creator: str, action: str) -> bool:
        if action == "unscam" and creator in self.scam_devs:
            del self.scam_devs[creator]
        elif action == "unvip" and creator in self.dev_book:
            del self.dev_book[creator]
        else:
            return False
        self.dirty_devs.add(creator)
        return True

    # ------------------------------------------------------------------ volta (a cada ~3 s)
    async def tick(self, now: float | None = None) -> None:
        now = now or self.clock()
        for m in [m for m, b in self.items.items() if now - b["t0"] > KEEP_S]:
            self.items.pop(m, None)
        if self.svc is None:
            return
        for fn in (self._creators, self._track, self._safety, self._samples):
            try:
                await fn(now)
            except Exception as e:
                self.st["erro"] = f"{fn.__name__}: {type(e).__name__}: {str(e)[:120]}"
        self.scam_mark(now)
        self.dev_hist(now)
        for m, b in self.items.items():
            b["progress"] = round(self.progress(b, now), 1)
            tk = self.tokens.get(m) or {}
            b["symbol"] = b.get("symbol") or tk.get("symbol")
            b["name"] = b.get("name") or tk.get("name")
            b["mcap_sol"] = tk.get("mcap_sol") or b.get("mcap_sol")
            v = tk.get("vol") or {}
            if v:
                b["buys_m5"], b["sells_m5"] = int(v.get("buys_m5") or 0), int(v.get("sells_m5") or 0)
            if tk.get("top10_pct") is not None:
                b["top10_pct"] = tk["top10_pct"]
            b["status"] = self._status(m, b, now)

    def _status(self, m: str, b: dict, now: float) -> str:
        p = b["progress"]
        if b.get("safety_ok") is False:
            return "trava de venda: " + str(b.get("safety_why") or "")
        sc = self.scam_of(m, b)
        if sc:
            return f"DEV scam — já fez {sc.get('symbol') or 'outro token'} com {sc.get('why')}"
        if self.twins(m, b):
            return "DEV scam — cópias com o mesmo nome migrando juntas"
        if p >= 100:
            return "BOOST terminou"
        return f"BOOST ativo ({p:.0f}%)"

    async def _rpc(self, keys: list, enc: str):
        """0.32.376: RPC do sistema primeiro (o público responde 429 com frequência e a leitura do DEV e da trava se perdia)."""
        if self.rpc_multi is not None:
            vals = await self.rpc_multi(keys, enc)
            if vals is not None:
                return vals
        if self.rpc_backup is not None and ALCHEMY_BACKUP:          # 0.32.384: reserva pela Alchemy
            vals = await self.rpc_backup(keys, enc)
            if vals is not None:
                self.st["reserva"] = self.st.get("reserva", 0) + 1
                return vals
        return await self.svc._rpc_multi(keys, enc, True)

    async def _creators(self, now: float) -> None:
        need = [m for m, b in self.items.items() if not b.get("creator") and b.get("creator_tries", 0) < 3 and now - b["t0"] < 3600]
        if not need:
            return
        pdas = {m: self.svc.curve_pda(m) for m in need[:100]}
        keys = [v for v in pdas.values() if v]
        vals = await self._rpc(keys, "base64") if keys else None
        if keys and vals is None:                  # RPC não respondeu: não gasta tentativa (antes 3 voltas de 429 = DEV nunca lido)
            self.st["rpc_falhou"] += 1
            return
        by = dict(zip(keys, vals or []))
        for m, pda in pdas.items():
            b = self.items[m]
            b["creator_tries"] = b.get("creator_tries", 0) + 1
            cr = (self.tokens.get(m) or {}).get("creator")
            try:
                raw = base64.b64decode(by[pda]["data"][0]) if by.get(pda) else b""
                cr = creator_of(raw) or cr
            except Exception:
                pass
            if cr:
                b["creator"] = cr
                self.dirty.add(m)

    async def _track(self, now: float) -> None:
        trk = [m for m, b in self.items.items() if now - b["t0"] <= TRACK_S and now - b.get("trk_at", 0) >= TRACK_EVERY_S]
        if not trk:
            return
        for m in trk:
            self.items[m]["trk_at"] = now
        await self.svc._fetch_prices(trk, set_price=False)
        for m in trk:
            tk = self.tokens.get(m) or {}
            px = tk.get("mkt_px") if now - float(tk.get("mkt_t") or 0) < 60 else None
            track_point(self.items[m], px, now)
            v = tk.get("vol") or {}
            if v and v.get("buys_m5") is not None:            # 0.32.380: compras dos últimos 5 min a cada 15 s (crescimento)
                bh = self.items[m].setdefault("buys_hist", [])
                bh.append([round(now), int(v.get("buys_m5") or 0), int(v.get("sells_m5") or 0)])
                del bh[:-BUYS_HIST_MAX]
            self.dirty.add(m)

    @staticmethod
    def buy_growth(b: dict | None, now: float) -> float | None:
        """0.32.380: crescimento das compras (contagem dos últimos 5 min da DexScreener) no último minuto, em %. None = sem
        dados recentes (leitura com mais de 90 s ou nenhuma de 1–3 min atrás)."""
        bh = (b or {}).get("buys_hist") or []
        if not bh or now - bh[-1][0] > 90:
            return None
        old = [x for x in bh if now - 180 <= x[0] <= now - 50]
        if not old:
            return None
        o, c = old[-1][1], bh[-1][1]
        return round((c - o) / max(o, 1) * 100, 1)

    async def _safety(self, now: float) -> None:
        need = [m for m, b in self.items.items() if b.get("safety_ok") is None and b.get("safety_tries", 0) < SAFETY_TRIES
                and self.progress(b, now) <= OBS_MAX_PCT and now - b.get("safety_t", 0) > 10]
        if not need:
            return
        vals = await self._rpc(need[:50], "jsonParsed")
        if vals is None:                            # 0.32.376: RPC não respondeu: tenta de novo sem gastar tentativa
            self.st["rpc_falhou"] += 1
            for m in need[:50]:
                self.items[m]["safety_t"] = now
            return
        for m, acc in zip(need[:50], vals):
            b = self.items[m]
            b["safety_tries"] = b.get("safety_tries", 0) + 1
            b["safety_t"] = now
            r = safety_of(acc)
            b["safety_ok"], b["safety_why"] = r["ok"], r["why"]
            self.dirty.add(m)

    async def _samples(self, now: float) -> None:
        """Preço de cada token nos primeiros 60% da janela, para a observação. 0.32.376: cotação de COMPRA de 0,01 SOL na Jupiter a
        cada volta, como no original. Antes usava o preço guardado do token, que a Jupiter só atualiza para quem tem o token na
        carteira: as primeiras leituras vinham do preço congelado da curva (~4e-7 → salto falso) e havia buracos de 2 min."""
        jup = getattr(getattr(self.svc, "market", None), "jup", None)
        obs = [m for m, b in self.items.items() if self.progress(b, now) <= OBS_MAX_PCT and b.get("safety_ok") is not False]
        if not obs or jup is None:
            return
        for m in sorted(obs, key=lambda x: -self.items[x]["t0"])[:8]:
            b = self.items[m]
            dec = await self.svc.token_decimals(m)
            if dec is None:
                continue
            try:
                q = await jup._quote(SOL_MINT, m, QUOTE_LAMPORTS, None, direct=False)
            except Exception:
                q = None
            out = int((q or {}).get("outAmount") or 0) / (10 ** dec)
            if out <= 0:
                self.st["sem_cotacao"] += 1
                continue
            self.st["cotacoes"] += 1
            px = QUOTE_LAMPORTS / 1e9 / out
            sm = b.setdefault("samples", [])
            sm.append([round(now, 1), px])
            del sm[:-60]
            tk = self.tokens.setdefault(m, {"created_t": now})
            tk["bm_px"], tk["bm_px_t"] = px, now

    # ------------------------------------------------------------------ decisão de cada usuário
    def decide(self, c, b: dict, now: float, abertas_nomes: set, ja_aberto: int) -> tuple[str, str]:
        """Os filtros do guia, na ordem, com os limites DESTE usuário. Devolve (estado, motivo):
        "entrar", "esperar" (volta a olhar na próxima volta) ou "fora" (descartado de vez)."""
        g = lambda k, d: getattr(c, k, d)                                    # noqa: E731
        m = b["mint"]
        prog = self.progress(b, now)
        enter_max = float(g("pump_bm_enter_max_pct", 40))
        if prog > enter_max:
            return "fora", f"passou de {enter_max:.0f}% do BOOST sem confirmar"
        if g("pump_bm_block_repeat", True) and not self.name_keys(m, b):
            return "esperar", "aguardando o nome do token (para conferir nome repetido)"
        if g("pump_bm_block_scam", True):
            if not b.get("creator") and b.get("creator_tries", 0) < 3 and now - b["t0"] < DEV_WAIT_S:
                return "esperar", "aguardando o DEV do token"
            sc = self.scam_of(m, b)
            if sc:
                return "fora", f"DEV scam — {short(b.get('creator'))} já fez {sc.get('symbol') or 'outro token'} com {sc.get('why')}"
        tw = self.twins(m, b)
        if tw:
            return "fora", f"DEV scam — {len(tw) + 1} tokens {b.get('symbol') or ''} migraram juntos (cópias)"
        keys = self.name_keys(m, b)
        if keys & abertas_nomes:
            return "fora", "já tem posição do BOOST aberta em outro token com o mesmo nome"
        rep = self.repeat(m, b) if g("pump_bm_block_repeat", True) else None
        if rep and g("pump_bm_vip_skip_repeat", True) and (self.dev_stats(b.get("creator")) or {}).get("vip"):
            rep = None
        if rep:
            return "fora", f"nome repetido — {rep['name']} já migrou {rep['n']}x nas últimas 24 h"
        if b.get("safety_ok") is False:
            return "fora", "trava de venda — " + str(b.get("safety_why"))
        if b.get("safety_ok") is None:
            if b.get("safety_tries", 0) < SAFETY_TRIES and now - b["t0"] < SAFETY_WAIT_S:
                return "esperar", "conferindo a trava de venda"
            if g("pump_bm_require_safety", True):
                return "fora", "não deu para conferir a trava de venda"
        watch = float(g("pump_bm_watch_s", 60))
        sm = b.get("samples") or []
        if watch > 0:
            if not sm or now - sm[0][0] < watch:
                return "esperar", (f"observando {now - sm[0][0]:.0f}/{watch:.0f} s" if sm else "aguardando cotação (pool novo)")
            if len(sm) < 3:
                return "esperar", f"observando ({len(sm)} leituras)"
            p0, p1 = med([x[1] for x in sm[:3]]), med([x[1] for x in sm[-3:]])
            trend, dd = (p1 / p0 - 1) * 100, (p1 / max(x[1] for x in sm) - 1) * 100
            b["trend_pct"], b["drawdown_pct"] = round(trend, 1), round(dd, 1)
            if trend < float(g("pump_bm_min_trend_pct", -3)):
                return "fora", f"preço {trend:+.1f}% na observação (mínimo {float(g('pump_bm_min_trend_pct', -3)):+.0f}%)"
            mdd = float(g("pump_bm_max_dd_pct", 15))
            if mdd and dd < -mdd:
                return "fora", f"está {dd:.1f}% abaixo do topo da observação"
            bm, sm5 = int(b.get("buys_m5") or 0), int(b.get("sells_m5") or 0)
            ratio = float(g("pump_bm_min_buy_ratio", 1.2))
            if ratio and bm + sm5 >= 10 and bm < sm5 * ratio:
                return "fora", f"pouca pressão de compra ({bm} compras × {sm5} vendas em 5 min)"
        mb = int(g("pump_bm_min_buys", 100))
        if mb > 0 and int(b.get("buys_m5") or 0) < mb:
            return "esperar", f"aguardando compras: {int(b.get('buys_m5') or 0)} de {mb} nos últimos 5 min"
        mx = float(g("pump_bm_max_top10", 35))
        if mx and b.get("top10_pct") is not None and b["top10_pct"] > mx:
            return "esperar", f"10 maiores com {b['top10_pct']:.0f}% (máximo {mx:.0f}%)"
        if ja_aberto >= int(g("pump_bm_max_open", 3)):
            return "esperar", f"limite de {int(g('pump_bm_max_open', 3))} posições do BOOST"
        return "entrar", f"passou nos filtros em {prog:.0f}% do BOOST"

    @staticmethod
    def rules(c, b: dict, now: float) -> dict:
        """Regras de saída gravadas na posição (o motor executa a cada ~1 s): venda em partes, stop móvel, saída ao chegar a Y%
        do BOOST (prioridade sobre o stop) e stop de perda (0 = pausado até a saída do BOOST)."""
        g = lambda k, d: getattr(c, k, d)                                    # noqa: E731
        ex = float(g("pump_bm_exit_pct", 80))
        end_t = b["t0"] + JANELA_S * ex / 100
        hold = max(5.0, end_t - now)
        out = {"stop_pct": 0.0 if g("pump_bm_no_stop", False) else float(g("pump_bm_stop_pct", 40)), "tp_pct": 0.0, "boost_tp": None,
                "smart": False, "trail_on": True, "trail_start": float(g("pump_bm_trail_start", 10)),
                "trail_dist": float(g("pump_bm_trail_dist", 5)),
                "tp1_pct": float(g("pump_bm_partial_at", 15)) if g("pump_bm_partial_on", True) else None,
                "tp1_frac": float(g("pump_bm_partial_frac", 50)), "max_hold_s": round(hold, 1),
                "hold_why": f"BOOST {ex:.0f}% (saída em {ex:.0f}%)", "bm_t0": b["t0"], "bm_sg_after": bool(g("pump_bm_sg_after", True))}
        if isinstance(c, RealCfg):
            out["bm_own"] = True                       # 0.32.394: REAL com regras próprias — não segue a fictícia
        # 0.32.380 (pedido do dono): no fim do BOOST, fica se as compras estão crescendo e/ou até ficar +X%; enquanto fica,
        # a perda máxima é a da opção (padrão 25%) e há um tempo extra máximo
        grow_on, prof_on = bool(g("pump_bm_ext_on", True)), bool(g("pump_bm_hold_profit_on", False))
        sg_after = bool(g("pump_bm_sg_after", True))       # 0.32.386: precisa da conferência do fim do BOOST para armar o autônomo
        if grow_on or prof_on or sg_after:
            mx = float(g("pump_bm_ext_max_min", 20))
            out["max_hold_s"] = round(hold + mx * 60, 1)
            out["hold_why"] = f"BOOST {ex:.0f}% + {mx:g} min extras (tempo máximo)"
            out["bm_ext"] = {"end_t": round(end_t, 1), "ex": ex, "max_min": mx, "stop": float(g("pump_bm_ext_stop_pct", 25)),
                             "grow": float(g("pump_bm_ext_grow_pct", 10)) if grow_on else None,
                             "profit": float(g("pump_bm_hold_profit_pct", 10)) if prof_on else None}
        return out


    # ------------------------------------------------------------------ tela e banco
    def due_history(self, now: float) -> list[str]:
        """Tokens que já passaram de HIST_MIN min desde a migração e ainda não foram analisados."""
        return [m for m, b in self.items.items() if not b.get("hist_t") and now - b["t0"] >= HIST_MIN * 60]

    def view(self, b: dict) -> dict:
        keep = ("mint", "t0", "status", "symbol", "name", "progress", "creator", "dev_n", "dev_hist", "dev_scam", "dev_rec", "safety_ok",
                "safety_why", "trend_pct", "drawdown_pct", "buys_m5", "sells_m5", "mcap_sol", "track", "result", "top10_pct", "entry")
        out = {k: b.get(k) for k in keep}
        from .sybil import compact
        out["sybil"] = compact(b.get("sybil"))
        return out

    def dump(self, m: str) -> dict:
        b = self.items[m]
        d = {k: v for k, v in b.items() if k not in ("users",)}
        d["samples"] = (b.get("samples") or [])[-60:]
        return d

    def load(self, rows: list[dict], devs: list[dict]) -> None:
        now = self.clock()
        for r in rows or []:
            d = r.get("dados") or {}
            if d.get("mint") and now - float(d.get("t0") or 0) <= KEEP_S:
                d.setdefault("users", {})
                if not d.get("creator"):
                    d["creator_tries"] = 0          # 0.32.376: as tentativas gastas com o RPC sem resposta voltam a valer
                self.items.setdefault(d["mint"], d)
        for r in devs or []:
            d = r.get("dados") or {}
            if d.get("scam"):
                self.scam_devs[r["creator"]] = d["scam"]
            if d.get("book"):
                self.dev_book[r["creator"]] = d["book"]


class RealCfg:
    """0.32.394 (pedido do dono): as regras do BOOST vistas pela carteira REAL — cada pump_bm_<regra> de BM_REAL_RULES vem do
    pump_bmr_<regra>; o resto (chaves gerais, servidor) é o mesmo da conta."""

    def __init__(self, c):
        self._c = c

    def __getattr__(self, k):
        from .settings import BM_REAL_RULES
        if k.startswith("pump_bm_") and k[8:] in BM_REAL_RULES:
            return getattr(self._c, "pump_bmr_" + k[8:])
        return getattr(self._c, k)


def ext_decide(ext: dict, pnl: float | None, growth: float | None) -> tuple[bool, str]:
    """0.32.380: depois do fim do BOOST — (continua?, motivo). Perda passou do máximo: sai. Compras crescendo no último minuto
    acima do mínimo: fica. "Segurar até +X%" ligado e ainda abaixo de X%: fica. Senão sai."""
    stop, grow, prof = float(ext.get("stop") or 25), ext.get("grow"), ext.get("profit")
    if pnl is not None and pnl <= -stop:
        return False, f"BOOST acabou: perda de {pnl:.0f}% (máximo {stop:g}%)"
    if grow is not None and growth is not None and growth >= float(grow):
        return True, f"compras crescendo {growth:+.0f}% no último minuto (mínimo +{float(grow):g}%)"
    if prof is not None and (pnl is None or pnl < float(prof)):
        return True, f"segurando até +{float(prof):g}% (agora {'sem preço' if pnl is None else f'{pnl:+.0f}%'})"
    if prof is not None and pnl is not None and pnl >= float(prof):
        return False, f"BOOST acabou e chegou a {pnl:+.0f}% (alvo +{float(prof):g}%)"
    if grow is not None:
        g = "sem dados de compras" if growth is None else f"{growth:+.0f}% no último minuto, mínimo +{float(grow):g}%"
        return False, f"BOOST acabou e as compras não estão crescendo ({g})"
    return False, f"BOOST {float(ext.get('ex') or 0):.0f}%"
