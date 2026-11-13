"""0.32.338 (pedido do dono, 13/11/2026): BOT LIVE com carteira simulada própria, motor da Robinhood da versão 0.32.308, separado da /hood."""
import inspect

from app import botlive, botlive_copy308, hood, hoodcopy
from tests.test_api import env  # noqa: F401  (fixture env)
from tests.test_hood_copia import KEY, PID, TRADER, Http, Watch, run, settle, trade


def bot(monkeypatch):
    w = Watch()
    w.trades, w.balances, w.cfg = [], {}, {}
    w.danger = lambda now=None: {}
    monkeypatch.setattr(botlive, "rank", lambda trades, now, cfg, bal: {"rows": [], "copiaria": [TRADER]})
    b = botlive.BotLive(w, Http())
    b.keys[PID] = KEY
    b.book("u1")
    return w, b


def test_bot_live_e_o_motor_da_0_32_308_sem_parte_real(monkeypatch):
    w, b = bot(monkeypatch)
    assert isinstance(b.w, botlive.Watch308) and b.vault is None and b.real_allowed is False
    src = inspect.getsource(botlive_copy308)
    assert '"botlive_books"' in src and '"hood_books"' not in src and '"hood_trades"' not in src     # tabelas próprias
    assert "SellBlocked" not in src and "sg_on" not in src                                         # nada das versões novas
    assert botlive.CFG_DEFAULT["min_closed"] == 3 and botlive.CFG_DEFAULT["bot_per_day"] == 400        # ranking da 0.32.308


def test_bot_live_compra_na_carteira_simulada_pelo_ranking_da_0_32_308(monkeypatch):
    async def go():
        w, b = bot(monkeypatch)
        w.copiaria = []                                   # o ranking da /hood não copiaria ninguém...
        b.on_trade(trade("buy", 1000.0, 1.0), 0.0, [])
        await settle(b)
        return b
    b = run(go())
    assert len(b.book("u1").pos) == 1                     # ...mas a regra da 0.32.308 copia: a carteira do BOT abriu posição
    assert not b.real                                     # nunca a REAL


def test_ranking_da_0_32_308_volta_os_padroes_antigos():
    w = Watch()
    w.trades, w.balances, w.cfg = [], {}, {"v": 2, "min_closed": 5, "bot_per_day": 150, "top_n": 7}
    c = botlive.Watch308(w).cfg308()
    assert c["min_closed"] == 3 and c["bot_per_day"] == 400 and c["top_n"] == 7


def test_leitura_da_robinhood_entrega_os_trades_ao_bot_live_sem_mexer_na_hood():
    src = inspect.getsource(hood.HoodWatch)
    assert "self.extra" in src and "c.on_trade(tr, before, cop)" in src
    assert "botlive" not in inspect.getsource(hoodcopy)          # a cópia da /hood não sabe do BOT LIVE


def test_rotas_do_bot_live_exigem_login(env):
    c = env["c"]
    assert c.get("/api/botlive/painel").status_code == 401
    assert c.post("/api/botlive/carteira", json={"saldo_inicial": 1}).status_code == 401
    assert c.post("/api/botlive/zerar", json={}).status_code == 401
