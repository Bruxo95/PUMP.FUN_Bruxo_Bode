"""Revisão dos ganhos de "mil e tantos %" (0.32.1, pedido do dono em 2026-10-28).

Casos conhecidos: SEALLIS +133.475% (real ~−9%), R1R2L1R2 +182.916% (real ~−8%), MW +7.291% e Jewlon (a real vendeu
no alvo falso com −13%) — curvas da pump.fun cotadas em outra moeda (SPCX, TTWO, NTRNDM), lidas como SOL até a 0.31.52.

Aqui só se LÊ e se MARCA: procura em todas as contas os trades com ganho (ou melhor momento) de +1.900% ou mais,
confere na blockchain a moeda da curva e, quando há chave da Solana Tracker, o preço em dólar na entrada e na saída.
Nenhum trade, total, relatório ou configuração é alterado ou escondido (os totais seguem com eles, regra da 0.31.39)."""
from __future__ import annotations

from datetime import datetime, timezone

from .auto_trades import SUSPECT_PCT
from .versions_report import _ts, load as load_versions

FIX_VERSION = "0.31.52"          # correção da leitura da curva em outra moeda
MAX_ITEMS = 300


def fix_time(versions: list[dict] | None = None) -> float | None:
    for v in versions if versions is not None else load_versions():
        if v.get("versao") == FIX_VERSION:
            return _ts(v.get("inicio"))
    return None


def version_at(t: float | None, versions: list[dict]) -> str | None:
    best = None
    for v in sorted(versions, key=lambda v: _ts(v.get("inicio")) or 0):
        s = _ts(v.get("inicio"))
        if s is not None and t is not None and s <= t:
            best = v.get("versao")
    return best


def collect(accounts: list[tuple[str, str, list[dict]]], versions: list[dict] | None = None) -> list[dict]:
    """accounts = [(user_id, nome, trades)]. Devolve os trades fechados com ganho ou melhor momento ≥ +1.900%."""
    versions = load_versions() if versions is None else versions
    cut = fix_time(versions)
    out = []
    for uid, nome, trades in accounts:
        for t in trades:
            pct, best = t.get("pnl_pct") or 0, t.get("best_pct") or 0
            if pct < SUSPECT_PCT and best < SUSPECT_PCT:
                continue
            c = _ts(t.get("closed_at"))
            out.append({"user_id": uid, "conta": nome, "id": t.get("id"), "real": bool(t.get("real")), "mint": t.get("mint"),
                        "symbol": t.get("symbol"), "origem": t.get("origem") or ("manual" if t.get("wallet") == "manual" else "cópia"),
                        "opened_at": t.get("opened_at"), "closed_at": t.get("closed_at"), "sol_in": t.get("sol_in"),
                        "pnl_sol": t.get("pnl_sol"), "pnl_pct": t.get("pnl_pct"), "best_pct": t.get("best_pct"),
                        "price_in": t.get("price_in"), "price_out": t.get("price_out"), "reason": t.get("reason"),
                        "sim_id": t.get("sim_id"), "pos_id": t.get("pos_id") or t.get("id"),
                        "tipo": "ganho" if pct >= SUSPECT_PCT else "melhor momento",
                        "versao": version_at(c, versions), "depois_da_correcao": bool(cut and c and c >= cut)})
    out.sort(key=lambda x: _ts(x.get("closed_at")) or 0, reverse=True)
    return out[:MAX_ITEMS]


def pair_real(items: list[dict], trades_by_user: dict[str, list[dict]]) -> None:
    """Fictícia com par na carteira real (espelho, 0.31.37): o resultado da real é o que aconteceu de verdade."""
    for it in items:
        if it["real"]:
            continue
        for t in trades_by_user.get(it["user_id"]) or []:
            if t.get("real") and t.get("sim_id") and t.get("sim_id") == it.get("pos_id"):
                it["par_real"] = {"pnl_pct": t.get("pnl_pct"), "pnl_sol": t.get("pnl_sol"), "reason": t.get("reason")}
                break


def judge(it: dict, chain: dict | None, px: dict | None) -> dict:
    """Veredito de um item. chain = {quote: None|mint|'sem curva'}; px = {in_usd, out_usd} da Solana Tracker."""
    chain, px = chain or {}, px or {}
    q = chain.get("quote", "não lida")
    if q not in (None, "SOL", "sem curva", "não lida"):
        moeda = f"curva cotada em outra moeda ({q[:6]}…)"
        falso = True
    elif q in (None, "SOL"):
        moeda, falso = "curva em SOL", None
    else:
        moeda, falso = ("sem conta de curva (não é da pump.fun ou já fechou)" if q == "sem curva" else "não deu para ler"), None
    est = None
    if px.get("in_usd") and px.get("out_usd"):
        est = round((px["out_usd"] / px["in_usd"] - 1) * 100, 2)
    pct = it.get("pnl_pct") or 0
    if falso is None and est is not None and pct >= SUSPECT_PCT:
        falso = est < SUSPECT_PCT / 4          # o preço de mercado subiu bem menos que o registrado
    if it.get("par_real") and pct >= SUSPECT_PCT:
        falso = True if falso is None and (it["par_real"].get("pnl_pct") or 0) < SUSPECT_PCT / 4 else falso
    if falso is True:
        txt = "FALSO provável — " + moeda
    elif falso is False:
        txt = "parece verdadeiro — o preço de mercado também subiu"
    else:
        txt = "não confirmado — " + moeda
    verdade = (it["par_real"]["pnl_pct"] if it.get("par_real") else None)
    return {**it, "moeda": moeda, "quote_mint": q if falso and q not in (None, "SOL") else None, "falso": falso,
            "veredito": txt, "estimado_pct": est, "px_in_usd": px.get("in_usd"), "px_out_usd": px.get("out_usd"),
            "resultado_verdadeiro_pct": verdade if verdade is not None else (est if falso else None),
            "fonte_verdadeiro": "carteira real (par do espelho)" if verdade is not None else
                                ("preço da Solana Tracker na entrada e na saída, sem taxas" if (falso and est is not None) else None)}


def impact(items: list[dict], accounts: list[tuple[str, str, list[dict]]]) -> list[dict]:
    """Quanto os ganhos falsos pesam no total de cada conta (fictícia). Só informa; os totais da tela não mudam."""
    out = []
    for uid, nome, trades in accounts:
        f = [i for i in items if i["user_id"] == uid and i.get("falso") and not i["real"] and (i.get("pnl_pct") or 0) >= SUSPECT_PCT]
        if not f:
            continue
        tot = sum(t.get("pnl_sol") or 0 for t in trades if not t.get("real"))
        fs = sum(i.get("pnl_sol") or 0 for i in f)
        out.append({"conta": nome, "trades": len(f), "total_sol": round(tot, 4), "falsos_sol": round(fs, 4),
                    "sem_falsos_sol": round(tot - fs, 4), "versoes": sorted({i.get("versao") or "?" for i in f})})
    return out


def report(items: list[dict], accounts, feito: float | None = None) -> dict:
    falsos = [i for i in items if i.get("falso")]
    novos = [i for i in falsos if i.get("depois_da_correcao")]
    return {"feito": datetime.fromtimestamp(feito or datetime.now(timezone.utc).timestamp(), timezone.utc).isoformat(),
            "limite_pct": SUSPECT_PCT, "correcao": FIX_VERSION, "total": len(items), "falsos": len(falsos),
            "nao_confirmados": sum(1 for i in items if i.get("falso") is None),
            "depois_da_correcao": len(novos), "items": items, "impacto": impact(items, accounts),
            "onde_pesa": [
                "Explorar → Minhas operações automáticas e 'A conta do bot': os totais incluem esses ganhos (regra da 0.31.39).",
                "Relatórios → Por versão: a média por trade da versão em que o falso fechou fica inflada.",
                "Comparar configuração: a soma da conta com o falso fica maior que a real.",
                "Base geral, aprender com os erros e Estratégias fantasma: já ignoram ganhos de +1.900% (0.31.63–0.31.65).",
            ]}


def ai_text(rep: dict) -> str:
    L = [f"# Revisão dos ganhos de +{rep['limite_pct']:.0f}% ou mais ({rep['feito'][:16]} UTC)",
         f"Trades achados: {rep['total']} · falsos prováveis: {rep['falsos']} · não confirmados: {rep['nao_confirmados']} · "
         f"falsos depois da {rep['correcao']}: {rep['depois_da_correcao']}", ""]
    for i in rep["items"]:
        L.append(f"- {i.get('closed_at', '')[:16]} {i['conta']} {'REAL' if i['real'] else 'FICTÍCIA'} {i.get('symbol') or i.get('mint')} "
                 f"({i.get('mint')}): registrado {i.get('pnl_pct')}% (melhor {i.get('best_pct')}%), {i['veredito']}; "
                 f"verdadeiro {i.get('resultado_verdadeiro_pct')}% [{i.get('fonte_verdadeiro') or 'sem base'}]; versão {i.get('versao')}")
    for m in rep["impacto"]:
        L.append(f"- Impacto {m['conta']}: total {m['total_sol']} SOL; falsos {m['falsos_sol']} SOL; sem eles {m['sem_falsos_sol']} SOL")
    return "\n".join(L)
