"""Cérebro em sombra nas outras abas (0.32.117, pedido do dono: "melhorar o cérebro para perder menos").

Hoje só a entrada do Explorar usa o aprender com os erros. Aqui a MESMA regra é medida nas outras abas, sem decidir nada: cada trade
fechado é julgado só com o que já tinha fechado ANTES de ele abrir. Usar o histórico inteiro faria a regra acertar por já conhecer
o resultado. Assim o número responde "se a regra estivesse ligada na época, o que teria barrado e quanto teria poupado".

Só mede: nada aqui bloqueia compra, muda filtro ou mexe em configuração.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from . import autolearn, stats
from .auto_trades import SUSPECT_PCT
from .daily import TZ, TZ_NAME
from .resultstudy import ts as closed_ts

FORA = ("Explorar", "Botão Comprar", "Copiar trades de usuário")    # o Explorar já decide; os outros dois não são decisão do robô
MCAP = [(0, 30, "abaixo de 30 SOL"), (30, 60, "30 a 60 SOL"), (60, 100, "60 a 100 SOL"), (100, 300, "100 a 300 SOL"), (300, 1e12, "300 SOL ou mais")]
NOTA = [(0, 40, "abaixo de 40"), (40, 55, "40 a 55"), (55, 70, "55 a 70"), (70, 101, "70 ou mais")]
PARTE = [(0, 0.4, "fraca"), (0.4, 0.7, "média"), (0.7, 1.01, "forte")]
JANELA_S = 7 * 86400
LIMITES = (2, 4, 6, 10)
HORAS = [(0, 6, "00h às 06h"), (6, 12, "06h às 12h"), (12, 18, "12h às 18h"), (18, 24, "18h às 24h")]


def _faixa(v, faixas) -> str | None:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return next((n for lo, hi, n in faixas if lo <= v < hi), None)


def _opened(t: dict) -> float | None:
    try:
        return datetime.fromisoformat(str(t.get("opened_at")).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def aba(t: dict, aba_of) -> str | None:
    """A aba que decidiu a entrada, ou None se o trade não entra na medida."""
    if t.get("real") or t.get("follow_of") or t.get("origem") == "barrado_btn" or float(t.get("pnl_pct") or 0) >= SUSPECT_PCT:
        return None
    nome = aba_of(t)
    return None if nome in FORA else nome


def features(t: dict, opened: float) -> list[tuple[str, str]]:
    """Só o que se sabia ao abrir. Nada do que aconteceu depois (saída, pico, tempo de posição) pode entrar aqui."""
    hora = datetime.fromtimestamp(opened, timezone.utc).astimezone(TZ).hour
    F = [("Valor de mercado na entrada", _faixa(t.get("mcap_in"), MCAP)), ("Nota da entrada", _faixa(t.get("score"), NOTA)),
         (f"Horário ({TZ_NAME})", _faixa(hora, HORAS))]
    parts = t.get("score_parts") if isinstance(t.get("score_parts"), dict) else {}    # só nos trades a partir da 0.32.117
    F += [("Pressão de compra (parte da nota)", _faixa(parts.get("pressão"), PARTE)), ("Curva (parte da nota)", _faixa(parts.get("curva"), PARTE)),
          ("Criador (parte da nota)", _faixa(parts.get("criador"), PARTE))]
    info = t.get("auto_info") if isinstance(t.get("auto_info"), dict) else {}
    F += [(autolearn.label(f), autolearn.bucket(f, info.get(f))) for f in autolearn.FEATURES]
    return [(s, f) for s, f in F if f]


def regras(d: dict) -> tuple[bool, bool]:
    """(regra atual do Explorar, regra da faixa de confiança): mesmas contas de `autolearn.study`."""
    n, k = d["n"], d["k"]
    if n < autolearn.MIN_N or d["pct"] / n >= autolearn.MAX_AVG_PCT:
        return False, False
    return k / n < autolearn.MAX_WR, autolearn.wilson(k, n)[1] < autolearn.WILSON_MAX


def _unicos(rows: list[tuple]) -> list[tuple]:
    """O mesmo token na mesma aba comprado por contas diferentes com até 10 min conta uma vez, como em `learn_trades`."""
    vistos: dict[tuple, list] = {}
    out = []
    for conta, nome, t, ab, fe in sorted(rows, key=lambda r: r[3]):
        L = vistos.setdefault((nome, t.get("mint")), [])
        if any(c != conta and abs(ab - x) <= 600 for x, c in L):
            continue
        L.append((ab, conta))
        out.append((nome, t, ab, fe))
    return out


def _leitura(ci: dict) -> str:
    if ci["n"] == 0:
        return "não teria barrado nada até agora"
    if ci["lo"] is None:
        return f"poucos dados: {ci['n']} trades barrados em {ci['dias']} dias; a faixa de confiança precisa de pelo menos {stats.MIN_GRUPOS} dias"
    faixa = f"média de {ci['media']:+.1f}% nos barrados (faixa de {ci['lo']:+.1f}% a {ci['hi']:+.1f}%)"
    if ci["hi"] < 0:
        return "ajudaria: " + faixa
    if ci["lo"] > 0:
        return "atrapalharia: " + faixa
    return "ainda não dá para concluir: " + faixa


def _total(L: list[dict]) -> dict:
    pnl = [float(t.get("pnl_sol") or 0) for t in L]
    ci = stats.ci_days([(stats.day_of(t.get("closed_at")), t.get("pnl_pct")) for t in L])
    return {"n": len(L), "ganhos": sum(p > 0 for p in pnl), "poupado_sol": round(-sum(p for p in pnl if p <= 0), 6),
            "perderia_sol": round(sum(p for p in pnl if p > 0), 6), "efeito_sol": round(-sum(pnl), 6), "ci": ci, "leitura": _leitura(ci)}


def _bloco(L: list[dict]) -> dict:
    ci = stats.ci_days([(stats.day_of(t.get("closed_at")), t.get("pnl_pct")) for t in L])
    return {"n": ci["n"], "dias": ci["dias"], "media": ci["media"], "lo": ci["lo"], "hi": ci["hi"], "saldo_sol": round(sum(float(t.get("pnl_sol") or 0) for t in L), 6),
            "acerto": round(sum(float(t.get("pnl_sol") or 0) > 0 for t in L) / len(L) * 100) if L else None}


def evolucao(un: list[tuple], now: float) -> list[dict]:
    """Últimos 7 dias × 7 anteriores, por aba. Só diz que mudou quando as duas faixas de confiança nem se encostam."""
    g: dict[str, tuple] = {}
    for nome, t, _ab, fe in un:
        A, B = g.setdefault(nome, ([], []))
        if now - JANELA_S <= fe <= now:
            A.append(t)
        elif now - 2 * JANELA_S <= fe < now - JANELA_S:
            B.append(t)
    out = []
    for nome, (A, B) in g.items():
        if not A and not B:
            continue
        r, a = _bloco(A), _bloco(B)
        if r["lo"] is None or a["lo"] is None:
            vd, txt = "poucos dados", f"precisa de {stats.MIN_GRUPOS} dias com trades em cada semana: agora são {r['dias']} e {a['dias']}"
        elif r["lo"] > a["hi"]:
            vd, txt = "melhorou", f"de {a['media']:+.1f}% para {r['media']:+.1f}% por trade, com as faixas separadas"
        elif r["hi"] < a["lo"]:
            vd, txt = "piorou", f"de {a['media']:+.1f}% para {r['media']:+.1f}% por trade, com as faixas separadas"
        else:
            vd, txt = "sem conclusão", f"de {a['media']:+.1f}% para {r['media']:+.1f}% por trade, mas as faixas se encostam"
        out.append({"aba": nome, "recente": r, "antes": a, "veredito": vd, "leitura": txt})
    return sorted(out, key=lambda x: -x["recente"]["n"])


def limites(prep: list[tuple]) -> list[dict]:
    """Teste no histórico: com no máximo N entradas por hora em cada aba e conta, quais trades não teriam entrado. Conta por conta,
    porque o limite valeria por conta. Só mede."""
    g: dict[tuple, list] = {}
    for conta, nome, t, ab, _fe in prep:
        g.setdefault((nome, conta), []).append((ab, t))
    pico: dict[str, int] = {}
    cort: dict[tuple, list] = {}
    for (nome, _conta), L in g.items():
        L.sort(key=lambda x: x[0])
        for lim in LIMITES:
            aceitos: list[float] = []
            for ab, t in L:
                if sum(1 for x in aceitos[-lim:] if ab - x < 3600) >= lim:
                    cort.setdefault((nome, lim), []).append(t)
                else:
                    aceitos.append(ab)
        ini = 0
        for fim, (ab, _t) in enumerate(L):
            while ab - L[ini][0] >= 3600:
                ini += 1
            pico[nome] = max(pico.get(nome, 0), fim - ini + 1)
    out = [{"aba": nome, "limite": lim, "pico_hora": pico[nome], **_total(L)} for (nome, lim), L in cort.items()]
    return sorted(out, key=lambda x: (x["aba"], x["limite"]))


def run(rows: list[tuple], now: float | None = None) -> dict:
    """rows = [(conta, aba, trade)], já sem o que `aba` tirou. Devolve a medida por aba."""
    now = time.time() if now is None else now
    prep = []
    for conta, nome, t in rows:
        ab, fe = _opened(t), closed_ts(t)
        if ab is not None and fe is not None:
            prep.append((conta, nome, t, ab, fe))
    abas: dict[str, dict] = {}
    un = _unicos(prep)
    fechados = sorted(un, key=lambda r: r[3])                        # r[3] = fechou
    i = 0
    for nome, t, ab, _fe in un:                                      # em ordem de abertura
        while i < len(fechados) and fechados[i][3] < ab:             # o que já tinha fechado quando este abriu
            n2, t2, ab2, _ = fechados[i]
            i += 1
            G = abas.setdefault(n2, {"T": [], "A": [], "W": [], "F": {}})["F"]
            for k in features(t2, ab2):
                d = G.setdefault(k, {"n": 0, "k": 0, "pct": 0.0})
                d["n"] += 1
                d["k"] += float(t2.get("pnl_sol") or 0) > 0
                d["pct"] += float(t2.get("pnl_pct") or 0)
        A = abas.setdefault(nome, {"T": [], "A": [], "W": [], "F": {}})
        A["T"].append(t)
        julga = [regras(A["F"][k]) for k in features(t, ab) if k in A["F"]]
        if any(x[0] for x in julga):
            A["A"].append(t)
        if any(x[1] for x in julga):
            A["W"].append(t)
    for n2, t2, ab2, _ in fechados[i:]:                              # o resto entra só nas faixas de hoje
        G = abas.setdefault(n2, {"T": [], "A": [], "W": [], "F": {}})["F"]
        for k in features(t2, ab2):
            d = G.setdefault(k, {"n": 0, "k": 0, "pct": 0.0})
            d["n"] += 1
            d["k"] += float(t2.get("pnl_sol") or 0) > 0
            d["pct"] += float(t2.get("pnl_pct") or 0)
    out = []
    for nome, A in abas.items():
        faixas = []
        for (sinal, faixa), d in A["F"].items():
            at, wi = regras(d)
            if at or wi:
                faixas.append({"sinal": sinal, "faixa": faixa, "n": d["n"], "acerto": round(d["k"] / d["n"] * 100), "media_pct": round(d["pct"] / d["n"], 2), "atual": at, "wilson": wi})
        out.append({"aba": nome, "fechadas": len(A["T"]), "saldo_sol": round(sum(float(t.get("pnl_sol") or 0) for t in A["T"]), 6), "atual": _total(A["A"]),
                    "wilson": _total(A["W"]), "faixas": sorted(faixas, key=lambda x: x["media_pct"])[:12]})
    out.sort(key=lambda x: -x["fechadas"])
    return {"abas": out, "evolucao": evolucao(un, now), "limites": limites(prep), "fechadas": sum(x["fechadas"] for x in out), "min_n": autolearn.MIN_N, "max_acerto": round(autolearn.MAX_WR * 100), "max_media": autolearn.MAX_AVG_PCT}
