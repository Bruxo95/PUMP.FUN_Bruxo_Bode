"""0.32.331: o preço lido do trade é conferido com o de mercado; ganho falso de token de DEX não libera trader/tela para a REAL;
filtro de subida antes da compra."""
import time

from tests.test_espelho_real import _pf

M = "Dex".ljust(44, "1")           # token de fora da pump.fun
W = "W" * 44


def test_px_mismatch_so_fora_da_curva_e_com_mercado_recente(tmp_path):
    pf = _pf(tmp_path)
    now = time.time()
    pf.tokens[M] = {"price": 3e-5, "mkt_px": 3e-5, "mkt_t": now}
    assert pf.px_mismatch(M, 1e-5, now, {"source": "rpc"})                    # 1/3 do mercado: não bate
    assert pf.px_mismatch(M, 3.3e-5, now, {"source": "rpc"}) is None          # 10% acima: bate
    assert pf.px_mismatch(M, 1e-5, now, {"vSolInBondingCurve": 30}) is None   # trade da curva: preço das reservas
    pf.tokens[M]["mkt_t"] = now - 3600
    assert pf.px_mismatch(M, 1e-5, now, {"source": "rpc"}) is None            # mercado velho: não há como conferir


def test_ingest_nao_grava_preco_que_nao_bate(tmp_path):
    pf = _pf(tmp_path)
    now = time.time()
    pf.tokens[M] = {"price": 3e-5, "mkt_px": 3e-5, "mkt_t": now, "last_t": now, "created_t": now}
    pf.ingest({"txType": "buy", "mint": M, "traderPublicKey": W, "solAmount": 2.0, "tokenAmount": 200000.0, "source": "rpc"}, now)
    assert pf.tokens[M]["price"] == 3e-5


def test_filtro_da_copia(tmp_path):
    pf = _pf(tmp_path)
    now = time.time()
    ev = {"txType": "buy", "mint": M, "solAmount": 2.0, "tokenAmount": 200000.0, "source": "rpc"}
    pf.tokens[M] = {"price": 1e-5}
    assert "sem preço de mercado" in pf.px_check_block(M, ev, now)
    pf.tokens[M].update(mkt_px=3e-5, mkt_t=now)
    assert "não bate" in pf.px_check_block(M, ev, now)
    pf.tokens[M].update(mkt_px=1.05e-5)
    assert pf.px_check_block(M, ev, now) is None
    pf.cfg.pump_px_check_on = False
    pf.tokens[M].update(mkt_px=3e-5)
    assert pf.px_check_block(M, ev, now) is None


def test_ganho_falso_de_dex_nao_conta_para_a_real(tmp_path):
    pf = _pf(tmp_path)
    old = {"venue": "DEX orca", "opened_at": "2026-11-10T10:00:00+00:00"}
    new = {"venue": "DEX orca", "opened_at": "2026-11-14T10:00:00+00:00"}
    pump = {"venue": "PumpSwap", "opened_at": "2026-11-10T10:00:00+00:00"}
    assert pf.px_tainted(old, 0) and not pf.px_tainted(new, 0) and not pf.px_tainted(pump, 0)


def test_subida_antes_da_compra(tmp_path):
    pf = _pf(tmp_path)
    now = time.time()
    pf.market.px_hist[M] = [(now - 600, 1e-6), (now - 300, 1.5e-6), (now - 60, 2.4e-6)]
    assert pf.runup_block(M, 2.5e-6, now) is None                 # desligado por padrão
    pf.cfg.pump_runup_max_pct = 100
    assert "já subiu 150%" in pf.runup_block(M, 2.5e-6, now)
    assert pf.runup_block(M, 1.6e-6, now) is None
    assert pf.runup_block("Outro".ljust(44, "1"), 2.5e-6, now) is None   # sem histórico: não bloqueia
