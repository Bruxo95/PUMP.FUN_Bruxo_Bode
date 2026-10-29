"""Relatório de carteira em estudo + prompt para o ChatGPT (0.32.47, pedido do dono em 29/10: "me dá as carteiras e um
prompt pra eu mandar o ChatGPT fazer uma varredura de transações pra entender o que ela fez e como ganhou dinheiro; deixa o
ChatGPT fazer só o grosso, a análise tem que ser você").

O ChatGPT só junta os dados brutos (transações, tokens, horários, valores) em tabelas; a análise e o veredito ficam com o
Claude, que recebe a resposta de volta junto com este relatório. Só leitura: nada muda no robô."""
from __future__ import annotations

from datetime import datetime, timezone


def _f(v, d=4):
    try:
        return f"{float(v):.{d}f}"
    except (TypeError, ValueError):
        return "-"


def _hms(s):
    try:
        s = int(s)
    except (TypeError, ValueError):
        return "-"
    return f"{s}s" if s < 60 else f"{s // 60} min" if s < 3600 else f"{s / 3600:.1f} h" if s < 86400 else f"{s / 86400:.1f} dias"


def wallet_block(w: str, name: str | None, prof: dict, facts: dict | None, mine: dict | None) -> str:
    """O que o sistema já sabe da carteira (texto)."""
    m = prof.get("main") or prof.get("live") or {}
    dg = prof.get("digest") or {}
    fx = facts or {}
    u = dg.get("unit") or m.get("unit") or "SOL"
    L = [f"## Carteira {w}" + (f" ({name})" if name else ""),
         f"- Solscan: https://solscan.io/account/{w} · GMGN: https://gmgn.ai/sol/address/{w} · pump.fun: https://pump.fun/profile/{w}",
         f"- Idade: {fx.get('age_days', '-')} dias{' (pelo menos)' if fx.get('age_more') else ''} · transações: {fx.get('txs', '-')}"
         f" · saldo: US$ {_f(fx.get('usd'), 0)} · tokens criados: {fx.get('criados', '-')}",
         f"- Fonte dos números: {m.get('source') or '-'} · fechadas: {m.get('closed', '-')} · acerto: "
         f"{_f((m.get('win_rate') or 0) * 100, 0) if m.get('win_rate') is not None else '-'}% · segura (mediana): {_hms(m.get('hold_med_s'))}",
         f"- Lucro 24 h: {_f(m.get('pnl_24h'))} {u} · 7 dias: {_f(m.get('pnl_7d'))} {u} · por dia (7 d): {_f(m.get('per_day_7d'))} {u}",
         f"- Nota do estudo: {dg.get('score', '-')} · acertos {dg.get('n_acertos', 0)} × erros {dg.get('n_erros', 0)} · ganho {_f(dg.get('ganho'))}"
         f" × perda {_f(dg.get('perda'))} {u} · {dg.get('pump_pct', '-')}% das operações na pump.fun",
         f"- Trades vistos pelo robô: {prof.get('trades_seen', 0)}"]
    if dg.get("acertos"):
        L.append("- Maiores acertos: " + "; ".join(f"{a.get('symbol') or a['mint'][:6]} ({a['mint']}) {_f(a.get('realized'))} {u}"
                                                   for a in dg["acertos"]))
    if dg.get("erros"):
        L.append("- Maiores erros: " + "; ".join(f"{a.get('symbol') or a['mint'][:6]} ({a['mint']}) {_f(a.get('realized'))} {u}"
                                                 for a in dg["erros"]))
    cp = prof.get("copy") or {}
    if cp:
        L.append(f"- Se você tivesse copiado (com atraso e taxas): 7 d {_f(cp.get('pnl_7d'))} SOL · acerto "
                 f"{_f((cp.get('win_rate') or 0) * 100, 0)}% · veredito: {cp.get('verdict') or '-'}")
    if mine:
        L.append(f"- Copiando de verdade (fictícia): {mine.get('trades', 0)} trades · {_f(mine.get('pnl_sol'))} SOL")
    rec = prof.get("recent") or []
    if rec:
        L.append("- Últimas transações vistas pelo robô (data UTC · compra/venda · SOL · token · market cap SOL · assinatura):")
        for t in rec[:25]:
            L.append(f"  - {str(t.get('at') or '')[:19]} · {t.get('side')} · {_f(t.get('sol'), 3)} · {t.get('mint')} · "
                     f"{_f(t.get('mcap_sol'), 0)} · {t.get('signature')}")
    return "\n".join(L)


PROMPT = """Você vai fazer SÓ o levantamento bruto de dados (sem opinião) de carteiras Solana que negociam memecoins na pump.fun.
Outra IA vai fazer a análise depois, então seja completo, exato e não invente nada: se não conseguir abrir uma página ou um dado,
escreva "NÃO CONFIRMADO" e diga qual fonte falhou.

Para CADA carteira da lista no fim:
1. Abra o histórico de transações (Solscan → aba "DeFi Activities"/"Transfers"; GMGN.ai → "Activity"/"PnL"; pump.fun/profile) dos
   últimos 30 dias (ou o máximo que conseguir) e monte uma TABELA, uma linha por token negociado:
   token (nome + endereço do mint) | se é da pump.fun (mint termina em "pump") | 1ª compra (data/hora UTC) | idade do token na
   1ª compra (min desde a criação) | market cap na compra | SOL investido (soma) | nº de compras | vendas (data/hora, % vendido,
   SOL recebido) | tempo segurando | resultado em SOL e % | se o token graduou (PumpSwap/Raydium) antes ou depois da entrada |
   onde comprou (curva da pump.fun, PumpSwap, Raydium, Jupiter…).
2. Liste à parte: transferências grandes de SOL entrando/saindo (de onde/para onde), carteiras com que ela troca SOL com
   frequência (possíveis carteiras irmãs/bundle), e tokens que ELA criou (se houver).
3. Números gerais: total investido, total recebido, lucro realizado, acerto (% de tokens no lucro), mediana do tempo segurando,
   horários do dia em que mais opera (UTC), tamanho típico de compra, quantas compras por hora nos picos.
4. Para os 5 maiores ganhos e as 5 maiores perdas: a linha do tempo minuto a minuto (compra, vendas parciais, preço/market cap
   em cada momento) e se havia outras carteiras grandes comprando o mesmo token nos mesmos minutos (quantas, endereços).
5. Diga as fontes e a data/hora em que leu cada uma. Não estime o que não está na fonte.

Formato da resposta: Markdown, uma seção por carteira, tabelas completas (sem resumir linhas), e no fim um bloco
"Dados que faltaram" com o que não conseguiu levantar. NÃO dê conselho de investimento nem conclusões sobre a estratégia.

Abaixo está o que o nosso sistema já sabe de cada carteira (use para conferir e completar; se a fonte pública discordar, mostre
os dois números)."""


def ai_text(blocks: list[str], now: float | None = None) -> str:
    when = datetime.fromtimestamp(now, timezone.utc) if now else datetime.now(timezone.utc)
    head = (f"# Carteiras em estudo · relatório de {when.strftime('%d/%m/%Y %H:%M')} UTC (PUMP FUN COPY)\n\n"
            "Como usar: copie TUDO e cole no ChatGPT (com navegação ligada). Depois traga a resposta dele de volta para o Claude, junto "
            "com este texto, para a análise de como cada carteira ganha dinheiro e se dá para copiar.\n\n---\n\n")
    return head + PROMPT + "\n\n---\n\n" + "\n\n".join(blocks) + "\n"
