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
