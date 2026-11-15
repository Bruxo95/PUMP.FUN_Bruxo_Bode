"""0.32.368 (pedido do dono, 15/11/2026): motor de cópia do Projeto Forex (docs/FOREX.md, seções 2 e 4).

Nesta etapa a cópia é SÓ FICTÍCIA (decisão do dono): cada evento de um mestre (abriu / modificou / fechou parte / fechou) vira uma
posição na carteira fictícia de quem o segue, com o lote proporcional, slippage e comissão simulados. Nenhuma ordem vai para
corretora. O resultado de cada posição copiada é o do mestre na mesma proporção do lote (lucro do mestre × lote seguidor ÷ lote
mestre), menos os custos simulados — assim pares cruzados (EURGBP, ouro…) saem certos sem precisar de cotação de conversão.

As regras de cada usuário e a carteira fictícia ficam no Supabase (tabela forex_contas, uma linha por conta, RLS).
"""
from __future__ import annotations

import math
import time
from collections import deque

# especificação padrão quando a corretora ainda não mandou a do ativo (deploy/forex.sql, tabela ativos)
SPEC_PADRAO = {"contrato": 100000.0, "lote_min": 0.01, "lote_passo": 0.01, "lote_max": 100.0, "pip": 0.0001}
SPEC_ESPECIAL = {
    "XAUUSD": {"contrato": 100.0, "pip": 0.1}, "XAGUSD": {"contrato": 5000.0, "pip": 0.01},
    "US30": {"contrato": 1.0, "pip": 1.0}, "NAS100": {"contrato": 1.0, "pip": 1.0}, "BTCUSD": {"contrato": 1.0, "pip": 1.0},
}

CFG_PADRAO = {
    "saldo_inicial": 10000.0,      # US$ da carteira fictícia
    "modo_lote": "equity",         # equity | multiplicador | fixo
    "multiplicador": 1.0,
    "lote_fixo": 0.01,
    "lote_max": 1.0,
    "slip_pips": 0.5,              # slippage simulado em cada entrada e saída
    "comissao_lote": 7.0,          # US$ por lote, ida e volta (média de conta ECN)
    "alavancagem": 100,
    "atraso_max_s": 10,            # evento mais velho que isso não é copiado
    "copiar_sl_tp": True,
    "perda_dia_max": 0.0,          # 0 = sem limite
    "seguindo": [],                # ids dos mestres copiados
}
LIMITES = {"saldo_inicial": (100, 10_000_000), "multiplicador": (0.01, 50), "lote_fixo": (0.01, 100), "lote_max": (0.01, 100),
           "slip_pips": (0, 50), "comissao_lote": (0, 100), "alavancagem": (1, 2000), "atraso_max_s": (1, 600), "perda_dia_max": (0, 10_000_000)}
MODOS = ("equity", "multiplicador", "fixo")


def base(simbolo: str) -> str:
    """EURUSD.r, EURUSDm, eurusd → EURUSD (para casar o ativo do mestre com o do seguidor)."""
    s = "".join(ch for ch in str(simbolo or "").upper() if ch.isalnum())
    for suf in ("PRO", "ECN", "RAW", "M", "R", "I", "C"):
        if len(s) > 6 and s.endswith(suf) and s[:-len(suf)].isalpha():
            return s[:-len(suf)]
    return s


def spec(simbolo: str, extra: dict | None = None) -> dict:
    b = base(simbolo)
    s = dict(SPEC_PADRAO)
    if "JPY" in b:
        s["pip"] = 0.01
    s.update(SPEC_ESPECIAL.get(b, {}))
    s.update(extra or {})
    return s


def lote_seguidor(lote_mestre: float, cfg: dict, eq_seguidor: float, eq_mestre: float | None, sp: dict) -> tuple[float, str | None]:
    """Lote do seguidor (docs/FOREX.md, seção 4). Devolve (lote, motivo); lote 0 = não copia, com o motivo."""
    modo = cfg.get("modo_lote", "equity")
    if modo == "fixo":
        bruto = float(cfg.get("lote_fixo") or 0)
    elif modo == "multiplicador":
        bruto = lote_mestre * float(cfg.get("multiplicador") or 1)
    else:
        if not eq_mestre or eq_mestre <= 0:
            return 0.0, "patrimônio do mestre desconhecido (modo equity)"
        bruto = lote_mestre * (eq_seguidor / eq_mestre) * float(cfg.get("multiplicador") or 1)
    bruto = min(bruto, float(cfg.get("lote_max") or sp["lote_max"]), sp["lote_max"])
    passo = sp["lote_passo"]
    lote = math.floor(bruto / passo + 1e-9) * passo                 # arredonda PARA BAIXO: nunca mais risco que o pedido
    lote = round(lote, 4)
    if lote < sp["lote_min"] - 1e-9:
        return 0.0, f"lote {bruto:.4f} abaixo do mínimo {sp['lote_min']}"
    return lote, None


def margem(lote: float, preco: float, simbolo: str, alav: float, sp: dict) -> float:
    """Margem aproximada em US$ (par XXXUSD: valor × preço; USDXXX: valor em dólar; resto: valor × preço)."""
    b = base(simbolo)
    nocional = lote * sp["contrato"] * (1.0 if b.startswith("USD") else (preco or 1.0))
    return nocional / max(1.0, float(alav or 100))


def valor_pip(lote: float, simbolo: str, preco: float, sp: dict) -> float:
    """US$ por pip (exato para XXXUSD; USDXXX dividido pelo preço; cruzados ≈ US$ 10 por lote, aproximação)."""
    b = base(simbolo)
    v = lote * sp["contrato"] * sp["pip"]
    if b.endswith("USD"):
        return v
    if b.startswith("USD") and preco:
        return v / preco
    return lote * 10.0


def clean_cfg(raw: dict, atual: dict | None = None) -> dict:
    c = dict(CFG_PADRAO)
    c.update(atual or {})
    for k, (lo, hi) in LIMITES.items():
        if k in raw:
            try:
                c[k] = float(min(hi, max(lo, float(raw[k]))))
            except (TypeError, ValueError):
                pass
    if raw.get("modo_lote") in MODOS:
        c["modo_lote"] = raw["modo_lote"]
    if "copiar_sl_tp" in raw:
        c["copiar_sl_tp"] = bool(raw["copiar_sl_tp"])
    if isinstance(raw.get("seguindo"), list):
        c["seguindo"] = [str(x)[:40] for x in raw["seguindo"]][:50]
    c["alavancagem"] = int(c["alavancagem"])
    c["atraso_max_s"] = int(c["atraso_max_s"])
    return c


class Livro:
    """Carteira fictícia de uma conta."""

    def __init__(self, cfg: dict | None = None):
        self.cfg = clean_cfg(cfg or {})
        self.caixa = self.cfg["saldo_inicial"]
        self.abertas: dict[str, dict] = {}      # chave "mestre:ticket"
        self.fechadas: deque = deque(maxlen=500)
        self.eventos: deque = deque(maxlen=200)
        self.sujo = False

    def dump(self) -> dict:
        return {"cfg": self.cfg, "caixa": self.caixa, "abertas": list(self.abertas.values()), "fechadas": list(self.fechadas)[-500:]}

    @classmethod
    def load(cls, d: dict) -> "Livro":
        b = cls((d or {}).get("cfg") or {})
        b.caixa = float((d or {}).get("caixa", b.cfg["saldo_inicial"]))
        for p in (d or {}).get("abertas") or []:
            b.abertas[p["chave"]] = p
        b.fechadas.extend((d or {}).get("fechadas") or [])
        return b

    def margem_usada(self) -> float:
        return sum(p.get("margem", 0) for p in self.abertas.values())

    def perda_hoje(self, agora: float) -> float:
        dia = int(agora // 86400)
        return -sum(p["lucro"] for p in self.fechadas if int(p["fechou_t"] // 86400) == dia and p["lucro"] < 0)


class ForexCopier:
    """Recebe os eventos normalizados dos conectores e espelha na carteira fictícia de cada seguidor."""

    def __init__(self, db=None, clock=time.time):
        self.db, self.clock = db, clock
        self.livros: dict[str, Livro] = {}
        self.carregado: set[str] = set()
        self.mestres: dict[str, dict] = {}    # id → {"apelido", "plataforma", "patrimonio", "elegivel", "score", "status"}

    # ------------------------------------------------------------------ carteira de cada conta
    def livro(self, uid: str) -> Livro:
        if uid not in self.livros:
            self.livros[uid] = Livro()
        return self.livros[uid]

    async def carregar(self, uid: str) -> Livro:
        if uid not in self.carregado and self.db is not None:
            try:
                rows = await self.db.select("forex_contas", {"user_id": uid}, limit=1)
                if rows:
                    self.livros[uid] = Livro.load(rows[0].get("dados") or {})
            except Exception:
                pass
            self.carregado.add(uid)
        return self.livro(uid)

    async def salvar(self, uid: str) -> None:
        b = self.livro(uid)
        if self.db is not None:
            await self.db.insert("forex_contas", {"user_id": uid, "dados": b.dump()}, upsert=True, on_conflict="user_id")
        b.sujo = False

    async def flush(self) -> None:
        for uid, b in list(self.livros.items()):
            if b.sujo:
                try:
                    await self.salvar(uid)
                except Exception:
                    pass

    async def save_cfg(self, uid: str, raw: dict) -> dict:
        b = await self.carregar(uid)
        old = b.cfg["saldo_inicial"]
        b.cfg = clean_cfg(raw if isinstance(raw, dict) else {}, b.cfg)
        b.caixa += b.cfg["saldo_inicial"] - old
        await self.salvar(uid)
        return b.cfg

    async def zerar(self, uid: str) -> None:
        b = await self.carregar(uid)
        cfg = dict(b.cfg)
        self.livros[uid] = Livro(cfg)
        await self.salvar(uid)

    # ------------------------------------------------------------------ eventos dos mestres
    def _nota(self, b: Livro, ev: dict, acao: str, motivo: str, simbolo: str | None = None) -> None:
        b.eventos.append({"t": self.clock(), "acao": acao, "token": simbolo or base(ev.get("simbolo") or ""), "mestre": ev.get("trader_id"), "motivo": motivo})

    def on_event(self, ev: dict) -> list[dict]:
        """ev = {trader_id, ticket, evento: abriu|modificou|fechou_parcial|fechou, lado, simbolo, volume, preco, sl, tp, t,
        patrimonio_mestre, lucro (no fechamento: lucro do mestre na parte fechada), volume_fechado (no parcial)}."""
        tid, out = str(ev.get("trader_id")), []
        if ev.get("patrimonio_mestre"):
            self.mestres.setdefault(tid, {})["patrimonio"] = float(ev["patrimonio_mestre"])
        for uid, b in self.livros.items():
            if tid not in b.cfg.get("seguindo", []):
                continue
            r = self._aplicar(b, ev, tid)
            if r:
                b.sujo = True
                out.append({"user_id": uid, **r})
        return out

    def _aplicar(self, b: Livro, ev: dict, tid: str) -> dict | None:
        agora, chave = self.clock(), tid + ":" + str(ev.get("ticket"))
        sp = spec(ev.get("simbolo", ""), ev.get("spec"))
        tipo = ev.get("evento")
        if tipo == "abriu":
            atraso = agora - float(ev.get("t") or agora)
            if atraso > b.cfg["atraso_max_s"]:
                self._nota(b, ev, "não copiou", f"evento com {atraso:.0f} s de atraso (máximo {b.cfg['atraso_max_s']} s)")
                return None
            m = self.mestres.get(tid, {})
            if m.get("elegivel") is False:
                self._nota(b, ev, "não copiou", "mestre fora do ranking (não elegível)")
                return None
            if b.cfg["perda_dia_max"] and b.perda_hoje(agora) >= b.cfg["perda_dia_max"]:
                self._nota(b, ev, "não copiou", "perda do dia chegou no limite")
                return None
            eq = self.patrimonio(b)
            lote, motivo = lote_seguidor(float(ev.get("volume") or 0), b.cfg, eq, m.get("patrimonio"), sp)
            if not lote:
                self._nota(b, ev, "não copiou", motivo or "lote zero")
                return None
            preco = float(ev.get("preco") or 0)
            mg = margem(lote, preco, ev.get("simbolo", ""), b.cfg["alavancagem"], sp)
            if mg > eq - b.margem_usada():
                self._nota(b, ev, "não copiou", f"margem insuficiente (precisa US$ {mg:.2f})")
                return None
            custo = b.cfg["slip_pips"] * valor_pip(lote, ev.get("simbolo", ""), preco, sp) + b.cfg["comissao_lote"] * lote / 2
            p = {"chave": chave, "id": chave, "mestre": tid, "ticket": str(ev.get("ticket")), "simbolo": base(ev.get("simbolo")),
                 "lado": ev.get("lado"), "lote": lote, "lote_mestre": float(ev.get("volume") or 0), "preco": preco,
                 "sl": ev.get("sl") if b.cfg["copiar_sl_tp"] else None, "tp": ev.get("tp") if b.cfg["copiar_sl_tp"] else None,
                 "abriu_t": agora, "custo": round(custo, 4), "margem": round(mg, 2), "atraso_s": round(agora - float(ev.get("t") or agora), 2)}
            b.abertas[chave] = p
            b.caixa -= custo
            self._nota(b, ev, "comprou" if ev.get("lado") == "buy" else "vendeu", f"{lote} lote (mestre {p['lote_mestre']})")
            return {"acao": "abriu", "posicao": p}
        p = b.abertas.get(chave)
        if p is None:
            return None                                                   # o seguidor não copiou a abertura: nada a fazer
        if tipo == "modificou":
            if b.cfg["copiar_sl_tp"]:
                p["sl"], p["tp"] = ev.get("sl"), ev.get("tp")
                self._nota(b, ev, "ajustou", "SL/TP copiados do mestre", p["simbolo"])
            return {"acao": "modificou", "posicao": p}
        if tipo in ("fechou", "fechou_parcial"):
            vol_m = float(ev.get("volume_fechado") or p["lote_mestre"]) if tipo == "fechou_parcial" else p["lote_mestre"]
            frac = 1.0 if tipo == "fechou" else min(1.0, vol_m / p["lote_mestre"]) if p["lote_mestre"] else 1.0
            lote_f = round(p["lote"] * frac, 4) if frac < 1 else p["lote"]
            lucro_m = float(ev.get("lucro") or 0)
            prop = lote_f / vol_m if vol_m else 0
            sp_ = spec(p["simbolo"])
            custo = b.cfg["slip_pips"] * valor_pip(lote_f, p["simbolo"], float(ev.get("preco") or p["preco"]), sp_) + b.cfg["comissao_lote"] * lote_f / 2
            lucro = round(lucro_m * prop - custo - (p["custo"] * frac), 2)
            b.caixa += lucro + p["custo"] * frac                           # o custo da entrada já tinha saído do caixa
            fech = {"id": chave + ":" + str(len(b.fechadas)), "mestre": tid, "simbolo": p["simbolo"], "lado": p["lado"], "lote": lote_f,
                    "preco": p["preco"], "preco_saida": ev.get("preco"), "abriu_t": p["abriu_t"], "fechou_t": self.clock(),
                    "lucro": lucro, "lucro_pct": round(lucro / self.patrimonio(b) * 100, 3) if self.patrimonio(b) else 0,
                    "motivo": "mestre fechou" if tipo == "fechou" else f"mestre fechou {frac:.0%}"}
            b.fechadas.append(fech)
            if frac >= 1:
                b.abertas.pop(chave, None)
            else:
                p["lote"] = round(p["lote"] - lote_f, 4)
                p["lote_mestre"] = round(p["lote_mestre"] - vol_m, 4)
                p["custo"] = round(p["custo"] * (1 - frac), 4)
                p["margem"] = round(p["margem"] * (1 - frac), 2)
            self._nota(b, ev, "fechou", f"{lucro:+.2f} US$ ({fech['motivo']})", p["simbolo"])
            return {"acao": tipo, "fechada": fech}
        return None

    def conectores(self) -> list[dict]:
        """Situação de cada plataforma (docs/FOREX.md, seção 3). Etapa 1: nenhuma conectada ainda."""
        return [{"plataforma": "cTrader", "status": "próxima etapa", "como": "Open API oficial (OAuth2 + WebSocket), grátis"},
                {"plataforma": "MT5", "status": "depois do cTrader", "como": "terminal MT5 (Windows VPS ou Wine) com senha de investidor"},
                {"plataforma": "Twelve Data", "status": "depois", "como": "segunda opinião do preço (plano grátis)"}]

    # ------------------------------------------------------------------ telas
    def patrimonio(self, b: Livro) -> float:
        return b.caixa           # sem cotação ao vivo nesta etapa: o flutuante entra na etapa do conector

    def painel(self, uid: str, ranking: list[dict] | None = None) -> dict:
        b = self.livro(uid)
        fech = list(b.fechadas)
        res = sum(x["lucro"] for x in fech)
        ini = b.cfg["saldo_inicial"]
        return {
            "carteira": {"inicial": ini, "total": round(self.patrimonio(b), 2), "resultado": round(res, 2),
                         "resultado_pct": round(res / ini * 100, 3) if ini else 0, "fechadas": len(fech),
                         "acerto": round(sum(1 for x in fech if x["lucro"] > 0) / len(fech) * 100, 1) if fech else None,
                         "margem_usada": round(b.margem_usada(), 2)},
            "cfg": b.cfg,
            "posicoes": sorted(b.abertas.values(), key=lambda p: -p["abriu_t"]),
            "trades": list(reversed(fech))[:300],
            "eventos": list(reversed(b.eventos))[:100],
            "seguindo": len(b.cfg.get("seguindo", [])),
            "mestres": [{"id": k, **v} for k, v in self.mestres.items()],
            "ranking": ranking or [],
        }
