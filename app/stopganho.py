"""Stop de ganho autônomo (0.32.332, pedido do dono em 13/11/2026: "fazer uma estratégia sua autônoma de stop de ganho, ganhou
10% saiu fora, com tudo que já temos de histórico ... a lógica da gente tá certa, mas a estratégia de entrada e saída tá horrível;
reveja tudo no Solana, Robinhood, BNB e nos outros").

O que a revisão achou: a cópia passa por um bom momento e devolve tudo. O stop móvel só liga em +25% e sai 20 pontos abaixo do
pico, então a operação que foi a +15% (preço de uns +27%, porque a ida e volta custa ~10% na fictícia da Solana) não tem proteção
nenhuma e termina no stop de −30% ou na venda do trader. O BNB nem tinha alvo nem stop móvel.

Como o robô decide sozinho, por aba, a cada 10 min:
- Lê as operações FICTÍCIAS fechadas nos últimos 14 dias de todas as contas: o resultado final e o melhor momento (best_pct, já
  depois das taxas). O mesmo token comprado por contas diferentes com até 10 min de diferença conta uma vez.
- Para cada nível L (de +5% a +100% líquido) refaz a conta: a operação que chegou a +L teria saído em +L menos 1 ponto de folga
  (atraso e slippage); a que não chegou termina igual, porque um alvo não muda nada numa operação que nunca passou por ele. Para
  as operações de antes do stop de ganho essa conta é exata, sem chute sobre o que veio primeiro.
- Escolhe o nível que mais rende por operação contra as regras de hoje. Sem base (menos de 20 operações ou 3 dias) começa no +10%
  pedido pelo dono. Se nenhum nível ganhar das regras de hoje por pelo menos meio ponto por operação, a aba fica sem alvo. Para não
  ficar trocando por ruído, só sai do nível atual se o novo render meio ponto a mais.
- Depois que ele vende, a operação deixa de mostrar o que teria acontecido. Por isso uma "sombra" continua seguindo o preço com as
  regras normais da posição (stop, stop móvel, venda do trader, segurar no prejuízo, alvo antigo, tempo máximo) e guarda no
  próprio trade o resultado sem o stop de ganho (`sg.sem`) e o melhor momento (`sg.best_sem`). Assim a conta continua honesta e o
  robô pode subir, descer ou desligar o alvo quando o mercado mudar.

Limites conhecidos (aparecem na tela): o melhor momento é o preço que o robô viu (leitura a cada ~1–3 s); a operação com venda em
partes antes do alvo é contada como se tudo saísse no alvo; a sombra não repete as saídas espertas (dev vendeu, graduou) e para
em 24 h. Só mede e decide a saída: não compra nada.
"""
from __future__ import annotations

import random
from datetime import datetime, timezone

NIVEIS = (5.0, 8.0, 10.0, 12.0, 15.0, 20.0, 25.0, 30.0, 40.0, 50.0, 75.0, 100.0)
INICIAL = 10.0                 # pedido do dono: "ganhou 10% saiu fora"
FOLGA = 1.0                    # pontos a menos na conta: a venda de verdade sai um pouco abaixo do nível
JANELA_S = 14 * 86400
MIN_N, MIN_DIAS = 20, 3
MIN_GANHO = 0.5                # pontos por operação para valer a pena usar alvo
TROCA = 0.5                    # histerese: o nível novo precisa render isso a mais que o atual
CONFIANTE = 0.8                # chance (sorteando dias) de o ganho ser positivo para chamar de "confiança alta"
SUSPEITO = 1900.0              # mesmo corte de auto_trades.SUSPECT_PCT: preço lido errado não entra
DEDUP_S = 600
SOMBRA_S = 24 * 3600
SOMBRA_MAX = 600
REPS, SEED = 400, 20261113
CACHE_S = 600
MOTIVO = "stop de ganho autônomo"


def ts_de(x) -> float | None:
    """ISO ou número → segundos."""
    if x is None or x == "":
        return None
    if isinstance(x, (int, float)):
        return float(x)
    try:
        d = datetime.fromisoformat(str(x).replace("Z", "+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()
    except (TypeError, ValueError):
        return None


def dia_de(t: float | None) -> str | None:
    try:
        return datetime.fromtimestamp(float(t), timezone.utc).date().isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def hora_berlim(t: float | None) -> int | None:
    if t is None:
        return None
    try:
        from zoneinfo import ZoneInfo
        z = ZoneInfo("Europe/Berlin")
    except Exception:
        z = timezone.utc
    try:
        return datetime.fromtimestamp(float(t), timezone.utc).astimezone(z).hour
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def marcar(p: dict, chg: float, t: float) -> None:
    """Primeira vez que a posição passou de cada nível (segundos desde a compra) e a pior queda até ali, em `p["sg_hits"]`. O melhor
    e o pior momento sozinhos não dizem o que veio primeiro; com isto o cérebro poderá medir stop e alvo juntos sem chute."""
    if chg < NIVEIS[0]:
        return
    h = p.setdefault("sg_hits", {})
    for nv in NIVEIS:
        if chg < nv:
            break
        k = f"{nv:g}"
        if k not in h:
            h[k] = [round(t - float(p.get("open_t") or t)), round(float(p.get("worst_pct") or 0), 1)]


# ------------------------------------------------------------------ uma operação para a conta
def linha(pct, best, t_fim, sg: dict | None = None, x: dict | None = None) -> dict | None:
    """pct = resultado final em % (depois das taxas); best = melhor momento em %; sg = o que o stop de ganho deixou no trade.
    None = fica de fora (sem dado, preço suspeito ou a sombra ainda não terminou)."""
    try:
        pct, best = float(pct), float(best)
    except (TypeError, ValueError):
        return None
    dia = dia_de(t_fim)
    if dia is None or pct != pct or best != best or pct >= SUSPEITO or best >= SUSPEITO:
        return None
    best = max(best, pct)                       # o melhor momento nunca fica abaixo do resultado
    sg = sg if isinstance(sg, dict) else {}
    if sg.get("saiu"):
        if sg.get("sem") is None:
            return None                         # sombra aberta ou perdida: sem o "e se" não dá para comparar
        try:
            sem, bs = float(sg["sem"]), float(sg.get("best_sem", best))
        except (TypeError, ValueError):
            return None
        if sem >= SUSPEITO or bs >= SUSPEITO:
            return None
        return {"pct": pct, "best": best, "dia": dia, "saiu": True, "sem": sem, "bu": max(bs, best), "x": x or {}}
    return {"pct": pct, "best": best, "dia": dia, "saiu": False, "sem": pct, "bu": best, "x": x or {}}


def com_alvo(r: dict, nivel: float) -> float:
    """Resultado da operação com alvo em +nivel. bu = melhor momento sem o stop de ganho (na sombra, para as que já saíram)."""
    return nivel - FOLGA if r["bu"] >= nivel else r["sem"]


def dedup(itens: list[tuple]) -> list[dict]:
    """itens = [(conta, grupo, token, hora_abertura, linha)]. O mesmo token no mesmo grupo comprado por CONTAS diferentes com até
    10 min de diferença conta uma vez (contas com a mesma configuração compram juntas e pesavam em dobro)."""
    vistos: dict[tuple, list] = {}
    out = []
    for conta, grupo, token, t0, r in sorted(itens, key=lambda i: (i[3] or 0)):
        if r is None:
            continue
        k = (grupo, token)
        if token and t0 is not None and any(c != conta and abs(t0 - x) <= DEDUP_S for c, x in vistos.get(k, [])):
            continue
        vistos.setdefault(k, []).append((conta, t0 or 0))
        out.append(dict(r, grupo=grupo))
    return out


# ------------------------------------------------------------------ a decisão
def _chance(por_dia: dict[str, list[float]], reps: int = REPS, seed: int = SEED) -> float | None:
    """Fração dos sorteios (dias inteiros com reposição) em que o ganho médio fica acima de zero. None com menos de 5 dias."""
    if len(por_dia) < 5:
        return None
    S = [(sum(v), len(v)) for v in por_dia.values()]
    rng, pos = random.Random(seed), 0
    for _ in range(reps):
        tot = n = 0
        for _x in S:
            s, c = S[rng.randrange(len(S))]
            tot += s
            n += c
        pos += 1 if n and tot / n > 0 else 0
    return round(pos / reps, 3)


def _media(xs) -> float | None:
    xs = list(xs)
    return round(sum(xs) / len(xs), 2) if xs else None


def avaliar(rows: list[dict], niveis=NIVEIS) -> list[dict]:
    """Uma linha por nível: média por operação com esse alvo, ganho contra sem alvo, quantas chegaram lá e a chance do ganho."""
    out = []
    if not rows:
        return out
    n = len(rows)
    for L in niveis:
        dias: dict[str, list[float]] = {}
        soma_c = soma_g = 0.0
        chegou = 0
        for r in rows:
            c = com_alvo(r, L)
            g = c - r["sem"]
            soma_c += c
            soma_g += g
            chegou += 1 if r["bu"] >= L else 0
            dias.setdefault(r["dia"], []).append(g)
        bons = sum(1 for v in dias.values() if sum(v) > 0)
        out.append({"nivel": L, "media": round(soma_c / n, 2), "ganho": round(soma_g / n, 2), "chegou": chegou,
                    "chegou_pct": round(100 * chegou / n, 1), "dias_melhor": bons, "chance": _chance(dias)})
    return out


def decidir(rows: list[dict], atual: float | None = None, inicial: float = INICIAL) -> dict:
    """Nível de um grupo (aba). acao: 'inicio' (sem base, usa o inicial), 'aplicar' (nível que mais rende) ou 'manter' (sem alvo)."""
    n, dias = len(rows), len({r["dia"] for r in rows})
    tab = avaliar(rows)
    out = {"n": n, "dias": dias, "media_hoje": _media(r["pct"] for r in rows), "media_sem": _media(r["sem"] for r in rows),
           "saiu_pelo_alvo": sum(1 for r in rows if r.get("saiu")), "tabela": tab, "ganho": None, "chance": None, "confianca": None}
    if n < MIN_N or dias < MIN_DIAS:
        return {**out, "acao": "inicio", "nivel": float(inicial),
                "motivo": f"sem base ainda: {n} operações em {dias} dias (precisa de {MIN_N} em {MIN_DIAS} dias). "
                          f"Começa no +{inicial:g}% pedido pelo dono e ajusta sozinho quando tiver base."}
    best = max(tab, key=lambda x: (x["ganho"], -x["nivel"]))
    cur = next((x for x in tab if atual is not None and x["nivel"] == float(atual)), None)
    if cur is not None and cur is not best and cur["ganho"] >= MIN_GANHO and best["ganho"] - cur["ganho"] < TROCA:
        best = cur                                   # quase igual ao atual: não troca por ruído
    if best["ganho"] < MIN_GANHO:
        return {**out, "acao": "manter", "nivel": None, "ganho": best["ganho"], "chance": best["chance"],
                "motivo": f"nenhum alvo ganhou das regras de hoje nas últimas {n} operações: o melhor, +{best['nivel']:g}%, "
                          f"mudaria {best['ganho']:+.1f} ponto por operação. Esta aba fica sem stop de ganho."}
    ch = best["chance"]
    conf = "alta" if ch is not None and ch >= CONFIANTE else ("média" if ch is not None and ch >= 0.6 else
                                                               ("baixa" if ch is not None else "poucos dias"))
    return {**out, "acao": "aplicar", "nivel": best["nivel"], "ganho": best["ganho"], "chance": ch, "confianca": conf,
            "motivo": f"+{best['nivel']:g}% rendeu {best['ganho']:+.1f} pontos por operação a mais que sem alvo nas últimas {n} "
                      f"operações ({best['chegou_pct']:.0f}% chegaram lá; média {best['media']:+.1f}% contra "
                      f"{out['media_sem']:+.1f}%). Confiança {conf}" + (f" ({ch * 100:.0f}% dos sorteios de dias)." if ch is not None else ".")}


def decidir_grupos(rows: list[dict], antes: dict | None = None, inicial: float = INICIAL) -> dict:
    """rows já com 'grupo' (dedup). Devolve {grupo: decisão}; `antes` = decisões anteriores (histerese)."""
    antes = antes or {}
    g: dict[str, list[dict]] = {}
    for r in rows:
        g.setdefault(r.get("grupo") or "geral", []).append(r)
    out = {}
    for nome, rs in g.items():
        a = antes.get(nome) or {}
        out[nome] = decidir(rs, a.get("nivel") if a.get("acao") == "aplicar" else None, inicial)
    return out


def nivel_de(dec: dict | None, fixo: float = 0.0, inicial: float = INICIAL) -> tuple[float | None, str]:
    """(nível, fonte) para uma posição: 'fixo' (escolhido na tela), 'inicio', 'aplicar' ou 'manter' (sem alvo)."""
    try:
        fixo = float(fixo or 0)
    except (TypeError, ValueError):
        fixo = 0.0
    if fixo > 0:
        return fixo, "fixo"
    if not dec:
        return float(inicial), "inicio"
    if dec.get("acao") == "manter":
        return None, "manter"
    return float(dec.get("nivel") or inicial), str(dec.get("acao") or "inicio")


def tela(decs: dict, fixo: float = 0.0, ligado: bool = True, fora: tuple = ()) -> list[dict]:
    """Uma linha por grupo para a tela, sem a tabela inteira de níveis (essa vai só para quem abre o detalhe)."""
    out = []
    for nome, d in sorted(decs.items(), key=lambda kv: -(kv[1].get("n") or 0)):
        nv, fonte = nivel_de(d, fixo)
        out.append({"aba": nome, "acao": d.get("acao"), "nivel": nv, "fonte": fonte, "n": d.get("n"), "dias": d.get("dias"),
                    "ganho": d.get("ganho"), "chance": d.get("chance"), "confianca": d.get("confianca"),
                    "media_hoje": d.get("media_hoje"), "media_sem": d.get("media_sem"), "saiu_pelo_alvo": d.get("saiu_pelo_alvo"),
                    "motivo": d.get("motivo"), "aplica": bool(ligado) and nome not in fora and nv is not None,
                    "tabela": d.get("tabela") or []})
    return out


# ------------------------------------------------------------------ onde a entrada perde (só mede)
FAIXAS = {
    "hora": ("Hora da entrada (Berlim)", ((0, 6, "0–6 h"), (6, 12, "6–12 h"), (12, 18, "12–18 h"), (18, 24, "18–24 h"))),
    "atraso": ("Atraso da cópia", ((0, 3, "até 3 s"), (3, 10, "3–10 s"), (10, 30, "10–30 s"), (30, 1e9, "mais de 30 s"))),
    "mcap": ("Market cap na entrada (SOL)", ((0, 40, "até 40"), (40, 80, "40–80"), (80, 200, "80–200"), (200, 1e12, "mais de 200"))),
    "nota": ("Nota da entrada", ((0, 40, "até 40"), (40, 60, "40–60"), (60, 75, "60–75"), (75, 101, "75 ou mais"))),
    "acima": ("Preço acima do que o trader pagou", ((-1e9, 2, "até 2%"), (2, 5, "2–5%"), (5, 10, "5–10%"), (10, 1e9, "mais de 10%"))),
}
RUIM_N, RUIM_MEDIA, RUIM_CHEGOU = 15, -5.0, 30.0


def faixas(rows: list[dict], nivel: float | None, campos=None) -> list[dict]:
    """Resultado por faixa de cada informação da entrada, já com o alvo escolhido (ou sem alvo). 'ruim' = 15+ operações, média
    de −5% ou pior e no máximo 30% chegando ao alvo. Só mede e mostra: nenhuma compra é barrada por isto."""
    out = []
    for campo, (nome, cortes) in (campos or FAIXAS).items():
        for lo, hi, rotulo in cortes:
            sel = [r for r in rows if isinstance((r.get("x") or {}).get(campo), (int, float)) and lo <= r["x"][campo] < hi]
            if not sel:
                continue
            res = [com_alvo(r, nivel) if nivel else r["sem"] for r in sel]
            media = sum(res) / len(sel)
            ch = (100 * sum(1 for r in sel if nivel and r["bu"] >= nivel) / len(sel)) if nivel else None
            out.append({"campo": campo, "nome": nome, "faixa": rotulo, "n": len(sel), "media": round(media, 2),
                        "ganhou": round(100 * sum(1 for v in res if v > 0) / len(sel), 1),
                        "chegou_pct": None if ch is None else round(ch, 1),
                        "ruim": len(sel) >= RUIM_N and media <= RUIM_MEDIA and (ch is None or ch <= RUIM_CHEGOU)})
    return sorted(out, key=lambda f: f["media"])


# ------------------------------------------------------------------ a sombra: o que teria acontecido sem o stop de ganho
def _valor(st: dict, px: float) -> float:
    return max(0.0, float(st["tokens"]) * px * float(st["mult"]) - float(st.get("fixo") or 0.0))


def _pct(st: dict, px: float) -> float:
    """Ganho que as regras da posição olham: só a parte que sobrou (Solana) ou a posição inteira (Robinhood e BNB)."""
    v = _valor(st, px)
    if st.get("base") == "total":
        inv = float(st.get("inv") or 0)
        return (float(st.get("realizado") or 0) + v - inv) / inv * 100 if inv else 0.0
    custo = float(st.get("custo") or 0)
    return (v / custo - 1) * 100 if custo else 0.0


def _final(st: dict, px: float | None) -> float:
    inv = float(st.get("inv") or 0)
    v = _valor(st, px) if px else 0.0
    return (float(st.get("realizado") or 0) + v - inv) / inv * 100 if inv else 0.0


class Sombras:
    """Posições que o stop de ganho fechou e que continuam sendo seguidas com as regras normais. O estado fica DENTRO do trade
    (`trade["sg"]["sombra"]`), que é gravado de novo pelo `salvar` quando a sombra termina: sobrevive ao reinício sem tabela nova."""

    def __init__(self, salvar=None, maximo: int = SOMBRA_MAX):
        self.abertas: list[dict] = []
        self.salvar = salvar
        self.maximo = maximo
        self.feitas = 0

    @staticmethod
    def _st(tr: dict) -> dict | None:
        st = (tr.get("sg") or {}).get("sombra") if isinstance(tr.get("sg"), dict) else None
        return st if isinstance(st, dict) else None

    def mints(self) -> set:
        return {st["token"] for st in (self._st(t) for t in self.abertas) if st and st.get("token")}

    def _tirar(self, tr: dict) -> None:
        self.abertas = [x for x in self.abertas if x is not tr]

    def abrir(self, tr: dict, st: dict) -> None:
        """st: token, wallet, t (hora da venda), ate (quando as regras normais sairiam pelo tempo), tokens, mult, fixo, custo,
        inv, realizado, base ('resto' ou 'total'), stop, trail ([liga, distância, trava] ou None), alvo, segue (vende com o
        trader), segura (mínimo para vender quando o trader saiu no prejuízo, ou None), segurando, pico, best, px."""
        st = dict(st)
        st["best"] = float(st.get("best") or 0.0)
        sg = tr.setdefault("sg", {})
        sg["sombra"] = st
        if len(self.abertas) >= self.maximo:
            velha = self.abertas.pop(0)
            vs = velha.get("sg") or {}
            vs.pop("sombra", None)
            vs["sombra_fim"] = "sem lugar (muitas abertas)"
            if self.salvar:
                self.salvar(velha)
        self.abertas.append(tr)

    def restaurar(self, trades, now: float) -> int:
        """Depois de reiniciar: volta a seguir as sombras que estavam abertas nos trades (até 24 h)."""
        ja, n = {id(t) for t in self.abertas}, 0
        for tr in trades or []:
            st = self._st(tr) if isinstance(tr, dict) else None
            if not st or id(tr) in ja or not (tr.get("sg") or {}).get("saiu"):
                continue
            if now - float(st.get("t") or 0) >= SOMBRA_S:
                self._fim(tr, st.get("px"), "parou depois de 24 h", now)
                continue
            self.abertas.append(tr)
            n += 1
        return n

    @staticmethod
    def _regra(st: dict, pct: float, t: float) -> str | None:
        stop = float(st.get("stop") or 0)
        tr_ = st.get("trail")
        if tr_:
            ini, dist, trava = (float(v) for v in tr_)
            if st.get("pico") is not None or pct >= ini:
                st["pico"] = max(float(st["pico"]) if st.get("pico") is not None else pct, pct)
                if pct <= max(st["pico"] - dist, trava):
                    return "stop móvel"
        if st.get("segurando") and pct > float(st.get("segura") or 0):
            return "segurou até ficar positivo"
        if stop and pct <= -stop:
            return "stop de perda"
        alvo = float(st.get("alvo") or 0)
        if alvo and pct >= alvo:
            return "alvo"
        if t >= float(st.get("ate") or 0):
            return "tempo máximo"
        return None

    def preco(self, token: str, px, t: float) -> int:
        if not px or px <= 0 or not self.abertas:
            return 0
        n = 0
        for tr in [x for x in self.abertas if (self._st(x) or {}).get("token") == token]:
            st = self._st(tr)
            st["px"] = px
            pct = _pct(st, px)
            st["best"] = max(float(st.get("best") or 0), pct)
            why = self._regra(st, pct, t)
            if why:
                self._fim(tr, px, why, t)
                n += 1
        return n

    def trader(self, wallet: str, token: str, frac: float, px, t: float) -> int:
        """O trader copiado vendeu `frac` do que tinha: a sombra vende a mesma parte (ou segura, pela regra da conta)."""
        if not px or px <= 0 or frac < 0.01 or not self.abertas:
            return 0
        n = 0
        for tr in [x for x in self.abertas if (self._st(x) or {}).get("token") == token and (self._st(x) or {}).get("wallet") == wallet]:
            st = self._st(tr)
            if not st.get("segue") or st.get("segurando"):
                continue
            st["px"] = px
            pct = _pct(st, px)
            if st.get("segura") is not None and pct < float(st["segura"]):
                st["segurando"] = True                   # "trader saiu no prejuízo: segura até ficar positivo"
                continue
            if frac >= 0.97:
                self._fim(tr, px, "trader vendeu", t)
                n += 1
                continue
            parte = max(0.0, float(st["tokens"]) * frac * px * float(st["mult"]) - float(st.get("fixo") or 0.0))
            st["realizado"] = float(st.get("realizado") or 0) + parte
            st["tokens"] = float(st["tokens"]) * (1 - frac)
            st["custo"] = float(st.get("custo") or 0) * (1 - frac)
        return n

    def tempo(self, t: float, preco_de=None) -> int:
        n = 0
        for tr in list(self.abertas):
            st = self._st(tr)
            if st is None:
                self._tirar(tr)
                continue
            if t >= float(st.get("ate") or 0) or t - float(st.get("t") or t) >= SOMBRA_S:
                px = (preco_de(st["token"]) if preco_de else None) or st.get("px")
                self._fim(tr, px, "tempo máximo" if t >= float(st.get("ate") or 0) else "parou depois de 24 h", t)
                n += 1
        return n

    def _fim(self, tr: dict, px, why: str, t: float) -> None:
        self._tirar(tr)
        sg = tr.get("sg") if isinstance(tr.get("sg"), dict) else None
        st = sg.pop("sombra", None) if sg is not None else None
        if not st:
            return
        try:
            px = float(px) if px else None
        except (TypeError, ValueError):
            px = None
        sg.update(sem=round(_final(st, px), 2), best_sem=round(max(float(st.get("best") or 0), float(tr.get("best_pct") or 0)), 2),
                  sombra_fim=why, sombra_t=round(float(t)))
        self.feitas += 1
        if self.salvar:
            self.salvar(tr)
