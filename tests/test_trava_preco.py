"""0.32.207 (ZEC, 04/11): um salto de preço de 20× ou mais só vale depois de confirmado. Sem internet."""
from app.pumpfun import PumpFun

ZEC = "A7bdiYdS5GjqGFtxf17ppRHtDKPkkRqbKtR27dxvQXaS"


def _pf():
    pf = PumpFun.__new__(PumpFun)
    return pf


def test_single_absurd_jump_is_held_and_old_price_stays():
    pf, tk = _pf(), {"price": 13.04, "last_t": 1000.0}
    assert not pf._px_ok(ZEC, tk, 133500.0, 1001.0, "trade rpc")
    assert tk["px_hold"]["px"] == 133500.0 and tk["px_jumps"] == 1
    # a leitura seguinte volta ao normal: o salto é esquecido
    assert pf._px_ok(ZEC, tk, 13.1, 1003.0, "DexScreener") and "px_hold" not in tk


def test_normal_moves_pass():
    pf, tk = _pf(), {"price": 1e-7, "last_t": 1000.0}
    assert pf._px_ok("x", tk, 1.5e-6, 1001.0, "trade pumpportal")          # 15× ainda passa
    assert pf._px_ok("x", {"price": 0, "last_t": 0}, 5.0, 1.0, "Jupiter")    # sem preço anterior


def test_jump_confirmed_by_another_source():
    pf, tk = _pf(), {"price": 1e-7, "last_t": 1000.0}
    assert not pf._px_ok("x", tk, 5e-6, 1001.0, "trade rpc")                # 50×: espera
    assert pf._px_ok("x", tk, 4.8e-6, 1004.0, "DexScreener")                # outra fonte confirma
    assert "px_hold" not in tk


def test_crash_confirmed_by_repeated_readings_of_the_same_source():
    pf, tk = _pf(), {"price": 1e-5, "last_t": 1000.0}
    assert not pf._px_ok("x", tk, 1e-7, 1001.0, "Jupiter")                  # caiu 100× (rug): espera
    assert not pf._px_ok("x", tk, 1.1e-7, 1010.0, "Jupiter")
    assert pf._px_ok("x", tk, 1e-7, 1035.0, "Jupiter")                      # 3 leituras em 30 s+ confirmam


def test_copy_uses_the_last_trusted_price_when_the_trade_price_was_refused():
    pf, tk = _pf(), {"price": 13.04, "last_t": 1000.0}
    ev = {"txType": "sell", "solAmount": 1335.0, "tokenAmount": 0.01}       # 133.500 SOL por ZEC
    assert not pf._px_ok(ZEC, tk, PumpFun.price_of(ev), 1001.0, "trade rpc")
    assert pf._ev_px(ev, tk) is None and tk["price"] == 13.04                 # a cópia cai no preço confiável
    ok = {"txType": "sell", "solAmount": 13.5, "tokenAmount": 1.0}
    assert pf._ev_px(ok, tk) == 13.5
