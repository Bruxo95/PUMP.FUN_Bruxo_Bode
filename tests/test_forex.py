"""0.32.368 (pedido do dono, 15/11/2026): Projeto Forex — nota dos mestres e cópia FICTÍCIA (docs/FOREX.md). Tudo sem internet."""
import os
import random

import pytest

from app import forexcopy as fc
from app import forexmetrics as fm

DIA = 86400
T0 = 1_760_000_000


def trade(i, lucro, vol=0.1, sim="EURUSD", lado="buy", sl=1.05, abriu=None, dur=3600):
    a = abriu if abriu is not None else T0 + i * DIA // 2
    return {"ticket": str(i), "simbolo": sim, "lado": lado, "volume": vol, "abriu": a, "fechou": a + dur, "lucro": lucro, "sl": sl}


# ------------------------------------------------------------------------------------------------------------------ métricas
def test_max_drawdown_do_pico_ao_vale():
    r = fm.max_drawdown([100, 120, 90, 130, 104, 140])
    assert r["pct"] == pytest.approx(25.0) and r["pico"] == 120 and r["vale"] == 90
    assert fm.max_drawdown([100, 110, 120])["pct"] == 0


def test_profit_factor_e_sem_perda():
    ts = [trade(1, 100), trade(2, -50), trade(3, 50)]
    assert fm.profit_factor(ts) == pytest.approx(3.0)
    assert fm.profit_factor([trade(1, 10)]) == float("inf") and fm.profit_factor([]) is None


def test_curva_tira_depositos():
    fotos = [{"t": 1, "patrimonio": 1000}, {"t": 2, "patrimonio": 2000, "depositos": 1000}, {"t": 3, "patrimonio": 1900}]
    assert fm.curva_sem_depositos(fotos) == [1000, 1000, 900]      # o depósito não vira lucro; a queda depois é de 10%


def test_trader_consistente_e_elegivel_com_nota_alta():
    random.seed(7)
    ts = [trade(i, random.choice([40, 35, 50, -25, 30, -20, 45])) for i in range(160)]   # ~80 dias, ganhos pequenos e stop
    r = fm.avaliar(ts, 10_000)
    assert r["elegivel"], r["motivos"]
    assert r["mdd_pct"] < 5 and r["profit_factor"] > 1.5 and r["score"] > 50


def test_martingale_e_reprovado_mesmo_ganhando():
    ts, vol, i = [], 0.01, 0
    for ciclo in range(30):
        for _ in range(2):                                          # perde e dobra o lote
            ts.append(trade(i, -10 * vol / 0.01, vol=vol)); vol *= 2; i += 1
        ts.append(trade(i, 35 * vol / 0.01, vol=vol)); vol = 0.01; i += 1   # ganha e volta ao lote base
    r = fm.avaliar(ts, 10_000)
    assert r["lucro"] > 0 and r["martingale"] >= 0.9
    assert not r["elegivel"] and any("martingale" in m for m in r["motivos"])


def test_grade_sem_stop_e_reprovada():
    ts = []
    for k in range(20):                                             # 5 posições juntas no mesmo lado, sem stop
        a = T0 + k * 4 * DIA
        ts += [trade(k * 10 + j, 8, sl=None, abriu=a + j * 600, dur=DIA) for j in range(5)]
    r = fm.avaliar(ts, 10_000)
    assert r["grade"] > 0.9 and not r["elegivel"]


def test_filtros_minimos_demo_e_historico_curto():
    ts = [trade(i, 10, abriu=T0 + i * 3600) for i in range(20)]
    r = fm.avaliar(ts, 1000, conta_real=False)
    assert not r["elegivel"]
    assert any("demo" in m for m in r["motivos"]) and any("histórico curto" in m for m in r["motivos"]) and any("poucos trades" in m for m in r["motivos"])


def test_ranking_poe_elegivel_na_frente():
    bom = [trade(i, 30 if i % 3 else -15) for i in range(140)]
    curto = [trade(i, 100, abriu=T0 + i * 3600) for i in range(10)]
    rk = fm.ranking([{"id": "c", "trades": curto, "saldo_inicial": 1000}, {"id": "b", "trades": bom, "saldo_inicial": 10000}])
    assert rk[0]["id"] == "b" and rk[0]["elegivel"] and not rk[1]["elegivel"]


# ------------------------------------------------------------------------------------------------------------------ lote
def test_lote_proporcional_ao_patrimonio_e_arredonda_para_baixo():
    sp = fc.spec("EURUSD")
    lote, m = fc.lote_seguidor(1.0, {"modo_lote": "equity", "multiplicador": 1, "lote_max": 5}, 1000, 10000, sp)
    assert lote == pytest.approx(0.10) and m is None                # mestre $10k, seguidor $1k → 10× menor
    lote, _ = fc.lote_seguidor(0.37, {"modo_lote": "equity", "multiplicador": 1, "lote_max": 5}, 1000, 10000, sp)
    assert lote == pytest.approx(0.03)                              # 0,037 → 0,03 (nunca para cima)
    lote, m = fc.lote_seguidor(0.05, {"modo_lote": "equity", "multiplicador": 1, "lote_max": 5}, 1000, 10000, sp)
    assert lote == 0 and "mínimo" in m                              # 0,005 é abaixo de 0,01: não copia
    assert fc.lote_seguidor(2, {"modo_lote": "multiplicador", "multiplicador": 0.5, "lote_max": 5}, 1, 1, sp)[0] == pytest.approx(1.0)
    assert fc.lote_seguidor(9, {"modo_lote": "fixo", "lote_fixo": 0.2, "lote_max": 5}, 1, 1, sp)[0] == pytest.approx(0.2)
    assert fc.lote_seguidor(9, {"modo_lote": "multiplicador", "multiplicador": 1, "lote_max": 0.5}, 1, 1, sp)[0] == pytest.approx(0.5)


def test_simbolo_normalizado_e_spec():
    assert fc.base("EURUSD.r") == "EURUSD" and fc.base("eurusdm") == "EURUSD" and fc.base("XAUUSD") == "XAUUSD"
    assert fc.spec("USDJPY")["pip"] == 0.01 and fc.spec("XAUUSD")["contrato"] == 100


# ------------------------------------------------------------------------------------------------------------------ cópia fictícia
def _copier(t=[T0]):
    c = fc.ForexCopier(clock=lambda: t[0])
    b = c.livro("u1")
    b.cfg = fc.clean_cfg({"saldo_inicial": 1000, "seguindo": ["m1"], "slip_pips": 0, "comissao_lote": 0}, b.cfg)
    b.caixa = 1000
    c.mestres["m1"] = {"patrimonio": 10000, "elegivel": True}
    return c, b


def test_copia_abre_proporcional_e_fecha_com_o_resultado_do_mestre():
    c, b = _copier()
    out = c.on_event({"trader_id": "m1", "ticket": 1, "evento": "abriu", "lado": "buy", "simbolo": "EURUSD", "volume": 1.0,
                      "preco": 1.08, "sl": 1.07, "tp": 1.10, "t": T0})
    assert out and b.abertas["m1:1"]["lote"] == pytest.approx(0.1) and b.abertas["m1:1"]["sl"] == 1.07
    c.on_event({"trader_id": "m1", "ticket": 1, "evento": "fechou_parcial", "volume_fechado": 0.5, "lucro": 50, "preco": 1.081, "t": T0})
    assert b.abertas["m1:1"]["lote"] == pytest.approx(0.05) and b.fechadas[-1]["lucro"] == pytest.approx(5.0)
    c.on_event({"trader_id": "m1", "ticket": 1, "evento": "fechou", "lucro": 100, "preco": 1.082, "t": T0})
    assert "m1:1" not in b.abertas and b.fechadas[-1]["lucro"] == pytest.approx(10.0)
    assert c.painel("u1")["carteira"]["total"] == pytest.approx(1015.0)


def test_nao_copia_evento_atrasado_mestre_reprovado_nem_quem_nao_segue():
    c, b = _copier()
    c.clock = lambda: T0 + 60
    c.on_event({"trader_id": "m1", "ticket": 2, "evento": "abriu", "lado": "sell", "simbolo": "EURUSD", "volume": 1, "preco": 1.08, "t": T0})
    assert not b.abertas and "atraso" in b.eventos[-1]["motivo"]
    c.clock = lambda: T0
    c.mestres["m1"]["elegivel"] = False
    c.on_event({"trader_id": "m1", "ticket": 3, "evento": "abriu", "lado": "sell", "simbolo": "EURUSD", "volume": 1, "preco": 1.08, "t": T0})
    assert not b.abertas and "ranking" in b.eventos[-1]["motivo"]
    assert c.on_event({"trader_id": "m9", "ticket": 4, "evento": "abriu", "lado": "buy", "simbolo": "EURUSD", "volume": 1, "preco": 1, "t": T0}) == []


def test_custos_simulados_e_margem():
    c, b = _copier()
    b.cfg.update({"slip_pips": 1, "comissao_lote": 7})
    c.on_event({"trader_id": "m1", "ticket": 5, "evento": "abriu", "lado": "buy", "simbolo": "EURUSD", "volume": 1, "preco": 1.08, "t": T0})
    c.on_event({"trader_id": "m1", "ticket": 5, "evento": "fechou", "lucro": 0, "preco": 1.08, "t": T0})
    assert b.fechadas[-1]["lucro"] == pytest.approx(-(1 + 1 + 0.7))   # 1 pip na entrada e na saída (US$ 1 cada em 0,1 lote) + comissão
    b.cfg["alavancagem"] = 1                                           # sem alavancagem 1 lote de EURUSD precisa de ~US$ 108 mil
    b.cfg["modo_lote"], b.cfg["lote_fixo"] = "fixo", 1.0
    c.on_event({"trader_id": "m1", "ticket": 6, "evento": "abriu", "lado": "buy", "simbolo": "EURUSD", "volume": 1, "preco": 1.08, "t": T0})
    assert "margem" in b.eventos[-1]["motivo"]


def test_livro_salva_e_volta_igual():
    c, b = _copier()
    c.on_event({"trader_id": "m1", "ticket": 7, "evento": "abriu", "lado": "buy", "simbolo": "XAUUSD", "volume": 1, "preco": 2400, "t": T0})
    b2 = fc.Livro.load(b.dump())
    assert b2.abertas.keys() == b.abertas.keys() and b2.caixa == b.caixa and b2.cfg == b.cfg


def test_sql_do_banco_local_tem_as_tabelas_pedidas():
    sql = open(os.path.join(os.path.dirname(__file__), "..", "deploy", "forex.sql"), encoding="utf-8").read()
    for t in ("traders_monitored", "trades_history", "equity_snapshots", "copy_relations", "order_events", "copy_orders", "trader_scores"):
        assert f"create table forex.{t}" in sql
    assert "TROQUE_ESTA_SENHA" in sql and "cred_ref" in sql and "senha" not in sql.split("create schema")[1].split("cred_ref")[0].lower()
