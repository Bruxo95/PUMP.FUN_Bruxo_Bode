"""Consultas do servidor (0.32.379, pedido do dono: "focar a API no BOOST e desativar as consultas dos outros").

Uma chave liga/desliga para cada laço de consulta de fundo. Vale para o SERVIDOR TODO (os laços são compartilhados por
todos os usuários): o valor é o do admin que mudou por último na tela (`_ov_user`), igual aos filtros do Jev Trade e às
regras do BOOST. Ninguém mudou = ligada (comportamento de antes).

Desligar um laço para as CONSULTAS dele (APIs de fora). Não mexe em posições abertas: o preço e os stops delas seguem
no laço de preços, que não tem chave aqui.
"""
from __future__ import annotations

import time

# (opção, nome na tela, o que para quando desliga)
LOOPS = [
    ("pump_q_boost", "BOOST da migração", "migrações, leitura do DEV e da trava de venda e cotação de cada token que migrou (PumpPortal, Helius, Jupiter)"),
    ("pump_q_boost_novos", "BOOST · tokens novos (curva)", "busca dos tokens recém-criados com volume (DexScreener a cada 8 s) e as leituras deles (DEV, trava, cotação Jupiter, topo/dump): o BOOST não entra em token novo"),
    ("pump_q_boost_ativo", "BOOST · BOOST ativo (migrou, janela aberta)", "leituras dos tokens nos ~5 min depois da migração (DEV, trava de venda, cotação Jupiter, compras × vendas): o BOOST não entra nas migrações"),
    ("pump_q_boost_migrou", "BOOST · depois do BOOST (migraram)", "acompanhamento de topo e dump dos tokens que migraram, do fim do BOOST até 30 min (DexScreener a cada 15 s): o histórico desses tokens fica com menos pontos"),
    ("pump_q_top", "Top traders", "ranking da Solana Tracker a cada 10 min, leitura das carteiras do ranking e das carteiras manuais de Top traders e o laboratório das compras barradas: a cópia de Top traders para"),
    ("pump_q_explorar", "Explorar", "listas da Solana Tracker a cada 5 min, pools na DexScreener, checagem de carteiras novas e entradas sombra: a compra automática do Explorar para"),
    ("pump_q_base", "Base da pump.fun", "curva on-chain dos tokens novos (fotos de 1/5/15/60 min) e a compra automática da Base. O Jev Trade usa esta base"),
    ("pump_q_estudo", "Carteiras em estudo", "estudo automático (Solana Tracker a cada 30 min), leitura das carteiras em estudo, idade e saldo delas e a cópia das aprovadas"),
    ("pump_q_bruxo", "Aba do Bruxo", "sinais, lançamentos, contagem de detentores (Helius) e relatórios da Aba do Bruxo"),
    ("pump_q_jt", "Jev Trade", "candidatos, contagem de detentores (Helius) e perguntas ao Jev do Jev Trade"),
    ("pump_q_jev", "JEV (sombra)", "perguntas ao Jev nos sinais ao vivo e o estudo do passado"),
    ("pump_q_calls", "Calls quentes", "registro e acompanhamento das calls (marcas de 5/15/60 min)"),
    ("pump_q_raiox", "Raio-X do token", "Raio-X automático (Solana Tracker). O botão Fazer Raio-X na ficha do token continua funcionando"),
    ("pump_q_elite", "Maiores traders", "sinais, saldo e idade dos maiores traders, leitura das carteiras deles e a cópia dos sugeridos 80%+"),
]
KEYS = [k for k, _, _ in LOOPS]
NOMES = {k: n for k, n, _ in LOOPS}

_src = None                 # função do hub que devolve {opção: (ligada, quem, quando)}
_cache: tuple[float, frozenset] = (0.0, frozenset())


def bind(fn) -> None:
    """O hub liga aqui a função que lê as chaves dos admins."""
    global _src, _cache
    _src, _cache = fn, (0.0, frozenset())


def off() -> frozenset:
    """Opções desligadas agora (lidas no máximo a cada 3 s)."""
    global _cache
    now = time.monotonic()
    if _src is not None and now - _cache[0] > 3:
        try:
            _cache = (now, frozenset(k for k, v in _src().items() if not v[0]))
        except Exception:
            _cache = (now, _cache[1])
    return _cache[1]


def on(key: str) -> bool:
    return key not in off()


def refresh() -> None:
    """Relê na próxima consulta (depois que alguém muda uma chave)."""
    global _cache
    _cache = (0.0, _cache[1])


def reset() -> None:
    """Testes: volta tudo ligado e esquece o hub."""
    bind(None)
