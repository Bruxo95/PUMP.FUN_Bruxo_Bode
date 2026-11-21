"""0.32.404 (pedido do dono, 21/11): venda automática do Dormant ao chegar a +X%. Sem internet: rede e banco falsos."""
import asyncio
import time

from app import dormant_buy as db_
from tests.test_dormant_compra import KEY, SENHA, UID, OUTRO
from tests.test_dormant_venda import SellNet, bought

db_.RECIBO_PASSO = 0


def run(c):
    return asyncio.run(c)


def ready(pct=100, preco=0.02):
    """Compra de 1000 tokens por US$ 10 (preço 0,01); o preço de agora decide o total: 0,02 = +100%."""
    b, net, db = bought()
    b.watch.rows["tok-cg"]["current_price"] = preco
    b.watch.stat["leitura_t"] = time.time()
    run(b.set_on(UID, True, SENHA, "LIGAR"))
    run(b.save_autosell(UID, True, pct, SENHA))
    return b, net, db


def test_turning_on_needs_the_right_password_and_only_listed_percentages():
    b, net, db = bought()
    for pct in (7, 101, "x", None):
        try:
            run(b.save_autosell(UID, True, pct, SENHA))
            raise AssertionError
        except db_.BuyError as e:
            assert "porcentagem" in str(e)
    try:
        run(b.save_autosell(UID, True, 50, ""))
        raise AssertionError
    except db_.BuyError as e:
        assert "senha" in str(e)
    try:
        run(b.save_autosell(UID, True, 50, "senha-errada-99"))
        raise AssertionError
    except db_.BuyError as e:
        assert "errada" in str(e)
    assert UID not in b._as_pw
    st = run(b.save_autosell(UID, True, 50, SENHA))
    assert st["on"] is True and st["pct"] == 50 and st["ativa"] is True and st["pcts"] == [10, 15, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    assert SENHA not in str(db.tables) and KEY not in str(db.tables)          # a senha nunca vai para o banco, só para a memória


def test_sells_everything_when_the_purchase_reaches_the_target_and_writes_the_audit():
    b, net, db = ready(pct=100, preco=0.02)
    out = run(b.autosell_tick(UID))
    assert len(out) == 1 and out[0]["status"] == "confirmada"
    assert any(t["to"].lower() == db_.CHAINS["ethereum"]["router"] for t in net.txs)       # a venda saiu pelo roteador fixo
    assert db.tables["dormant_sells"] and db.tables["dormant_sells"][0]["compra"] == "c1"
    assert any(x["acao"] == "Dormant: venda automática" for x in db.tables["audit_log"])
    assert "vendida" in run(b.autosell_state(UID))["log"][-1]["msg"]
    assert SENHA not in str(db.tables)


def test_does_nothing_below_the_target_when_off_without_password_or_with_stale_prices():
    b, net, db = ready(pct=100, preco=0.015)                                  # +50%: abaixo do alvo
    assert run(b.autosell_tick(UID)) == [] and not net.txs
    b.watch.rows["tok-cg"]["current_price"] = 0.02
    b.watch.stat["leitura_t"] = time.time() - 3 * 3600                        # preço velho da CoinGecko não dispara
    assert run(b.autosell_tick(UID)) == [] and not net.txs
    b.watch.stat["leitura_t"] = time.time()
    b._as_pw.clear()                                                          # o servidor reiniciou: sem senha na memória, ninguém vende
    assert run(b.autosell_tick(UID)) == [] and not net.txs
    run(b.save_autosell(UID, True, 100, SENHA))
    run(b.save_autosell(UID, False, 100, None))                               # desligar não pede senha e apaga a da memória
    assert UID not in b._as_pw and run(b.autosell_tick(UID)) == [] and not net.txs
    assert run(b.autosell_state(UID))["on"] is False


def test_blocked_sale_waits_before_trying_again_and_general_lock_blocks():
    b, net, db = ready(pct=100, preco=0.02)
    net.token_bal = 0                                                         # sem saldo do token na carteira: a cotação bloqueia
    assert run(b.autosell_tick(UID)) == [] and not net.txs
    n_log = len(run(b.autosell_state(UID))["log"])
    assert "não vendeu" in run(b.autosell_state(UID))["log"][-1]["msg"]
    run(b.autosell_tick(UID))                                                 # dentro dos 5 min de espera: não tenta de novo
    assert len(run(b.autosell_state(UID))["log"]) == n_log
    b._as_fail.clear()
    net.token_bal = db_.__dict__.get("SALDO", 10 ** 21)
    b.allowed = lambda: False                                                 # trava geral do servidor fechada: nada vende
    assert run(b.autosell_tick(UID)) == [] and not net.txs


def test_other_account_is_untouched_and_exchange_purchases_are_ignored():
    b, net, db = ready(pct=100, preco=0.02)
    assert run(b.autosell_tick(OUTRO)) == []                                  # outra conta: sem senha na memória
    db.tables["dormant_buys"][0]["rede"] = "cex:binance"
    assert run(b.autosell_tick(UID)) == [] and not net.txs                    # compra em exchange não tem venda por aqui


# ------------------------------------------------------------------ 0.32.407: alvo próprio de cada compra
def bought_ready(preco=0.02):
    b, net, db = bought()
    b.watch.rows["tok-cg"]["current_price"] = preco
    b.watch.stat["leitura_t"] = time.time()
    run(b.set_on(UID, True, SENHA, "LIGAR"))
    return b, net, db


def test_one_purchase_can_have_its_own_target_with_the_general_switch_off():
    b, net, db = bought_ready()
    try:
        run(b.save_autosell_coin(UID, "c1", 100, ""))                          # ligar uma compra pede a senha se ela não está na memória
        raise AssertionError
    except db_.BuyError as e:
        assert "senha" in str(e)
    st = run(b.save_autosell_coin(UID, "c1", 100, SENHA))
    assert st["moedas"] == {"c1": 100} and st["on"] is False and st["ativa"] is True and st["n_moedas"] == 1 and st["precisa_senha"] is False
    assert len(run(b.autosell_tick(UID))) == 1 and net.txs                     # vendeu só por causa do alvo da compra, com a geral desligada
    assert SENHA not in str(db.tables)


def test_own_target_beats_the_general_one_and_zero_means_off_for_this_purchase():
    b, net, db = bought_ready()
    run(b.save_autosell(UID, True, 10, SENHA))                                 # geral: +10% (a compra está em +100%)
    run(b.save_autosell_coin(UID, "c1", 0, None))                              # desligada só nesta compra
    assert run(b.autosell_tick(UID)) == [] and not net.txs
    run(b.save_autosell_coin(UID, "c1", None, None))                           # volta a seguir a geral
    assert run(b.autosell_state(UID))["moedas"] == {}
    assert len(run(b.autosell_tick(UID))) == 1


def test_own_target_below_the_price_does_not_sell_and_password_leaves_memory_when_nothing_is_on():
    b, net, db = bought_ready(preco=0.015)                                     # +50%
    run(b.save_autosell_coin(UID, "c1", 100, SENHA))
    assert run(b.autosell_tick(UID)) == [] and not net.txs
    run(b.save_autosell_coin(UID, "c1", None, None))
    assert UID not in b._as_pw                                                 # sem nenhum alvo ligado, a senha sai da memória
    run(b.save_autosell(UID, True, 100, SENHA))
    run(b.save_autosell_coin(UID, "c1", 50, None))
    run(b.save_autosell(UID, False, 100, None))
    assert UID in b._as_pw                                                     # a compra ainda tem alvo próprio: a senha fica


def test_after_restart_unlock_keeps_every_target_and_bad_inputs_are_refused():
    b, net, db = bought_ready()
    run(b.save_autosell_coin(UID, "c1", 100, SENHA))
    b._as_pw.clear()                                                           # servidor reiniciou
    st = run(b.autosell_state(UID))
    assert st["precisa_senha"] is True and st["moedas"] == {"c1": 100}
    assert run(b.autosell_tick(UID)) == []
    st = run(b.autosell_unlock(UID, SENHA))
    assert st["precisa_senha"] is False and st["moedas"] == {"c1": 100}
    for bad in (7, 101, "x"):
        try:
            run(b.save_autosell_coin(UID, "c1", bad, SENHA))
            raise AssertionError
        except db_.BuyError as e:
            assert "porcentagem" in str(e)
    try:
        run(b.save_autosell_coin(UID, "naoexiste", 50, SENHA))
        raise AssertionError
    except db_.BuyError as e:
        assert "não encontrada" in str(e)
    try:
        run(b.save_autosell_coin(OUTRO, "c1", 50, SENHA))                      # compra de outra conta
        raise AssertionError
    except db_.BuyError as e:
        assert "não encontrada" in str(e)
    assert db_.clean_cfg(None, {"as_coins": {"a": 50, "b": 7, "c": True, "d": 0, "e": "100"}})["as_coins"] == {"a": 50, "d": 0}


# ------------------------------------------------------------------ 0.32.409: senha de compra desligável
def test_turning_the_password_off_needs_the_current_one_once_and_reseals_everything():
    b, net, db = bought_ready()
    try:
        run(b.set_senha_mode(UID, True, "", None))
        raise AssertionError
    except db_.BuyError as e:
        assert "senha" in str(e)
    try:
        run(b.set_senha_mode(UID, True, "senha-errada-99", None))
        raise AssertionError
    except db_.BuyError as e:
        assert "errada" in str(e)
    assert run(b.cfg(UID))["sem_senha"] is False
    r = run(b.set_senha_mode(UID, True, SENHA, None))
    assert r == {"sem_senha": True, "recifradas": 1} and run(b.cfg(UID))["sem_senha"] is True
    assert SENHA not in str(db.tables) and KEY not in str(db.tables)
    p = run(b.preview_sell(UID, "c1", 100))                                    # vender sem digitar nada
    assert p.get("quote_id"), p["bloqueia"]
    assert run(b.sell(UID, p["quote_id"], "", "VENDER"))["status"] == "confirmada"


def test_turning_it_back_on_asks_for_a_new_password_and_the_old_empty_one_stops_working():
    b, net, db = bought_ready()
    run(b.set_senha_mode(UID, True, SENHA, None))
    for ruim in ("", "123"):
        try:
            run(b.set_senha_mode(UID, False, None, ruim))
            raise AssertionError
        except db_.BuyError:
            pass
    assert run(b.cfg(UID))["sem_senha"] is True                                 # nada mudou na tentativa ruim
    run(b.set_senha_mode(UID, False, None, "senha-nova-123"))
    p = run(b.preview_sell(UID, "c1", 100))
    try:
        run(b.sell(UID, p["quote_id"], "", "VENDER"))
        raise AssertionError
    except db_.BuyError as e:
        assert "senha" in str(e)
    p = run(b.preview_sell(UID, "c1", 100))
    assert run(b.sell(UID, p["quote_id"], "senha-nova-123", "VENDER"))["status"] == "confirmada"


def test_without_password_new_wallets_and_exchange_keys_are_saved_with_nothing_typed():
    from tests.test_dormant_cex import API, SEC, Net
    from tests.test_dormant_compra import setup
    import app.dormant_cex as cx
    b, net, db = setup(Net())
    run(b.set_senha_mode(UID, True, None, None))                                # sem nada cadastrado: só liga o modo
    run(b.save_wallet(UID, "ethereum", KEY, ""))
    assert db_.vault.unseal(b.box, UID, "ethereum", db.tables["dormant_wallets"][0]["endereco"], db.tables["dormant_wallets"][0]["cifra"], "") == KEY
    c = cx.CexBuyer(b)
    r = run(c.save_key(UID, "binance", API, SEC, "", "", False))
    assert r["info"]["sem_senha"] is True
    assert run(c._keys(UID, "binance", ""))["secret"] == SEC
    try:
        run(b.change_password(UID, "", "senha-nova-123"))
        raise AssertionError
    except db_.BuyError as e:
        assert "desligada" in str(e)


def test_auto_sell_works_without_password_even_after_a_restart():
    b, net, db = bought_ready(preco=0.02)
    run(b.set_senha_mode(UID, True, SENHA, None))
    st = run(b.save_autosell(UID, True, 100, ""))                               # ligar não pede senha
    assert st["on"] is True and st["ativa"] is True and st["precisa_senha"] is False and st["sem_senha"] is True
    assert UID not in b._as_pw                                                  # e nada de senha na memória
    assert len(run(b.autosell_tick(UID))) == 1 and net.txs
    st = run(b.save_autosell_coin(UID, "c1", 50, ""))
    assert st["moedas"] == {"c1": 50}
    assert run(b.autosell_unlock(UID, ""))["ativa"] is True
