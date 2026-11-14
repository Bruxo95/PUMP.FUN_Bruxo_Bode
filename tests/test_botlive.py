"""0.32.338 (pedido do dono, 13/11/2026): BOT LIVE com carteira simulada própria, motor da Robinhood da versão 0.32.308, separado da /hood."""
import inspect

from app import botlive, botlive_copy308, hood, hoodcopy
from tests.test_api import env  # noqa: F401  (fixture env)
from tests.test_hood_copia import KEY, PID, TRADER, Http, Watch, run, settle, trade


def bot(monkeypatch):
    w = Watch()
    w.trades, w.balances, w.cfg = [], {}, {}
    w.danger = lambda now=None: {}
    monkeypatch.setattr(botlive, "rank", lambda trades, now, cfg, bal: {"rows": [{"wallet": TRADER, "realized_eth": 1.0, "eligible": False, "online": False}], "copiaria": []})
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


def test_carteira_do_bot_live_nasce_sozinha_para_quem_usa_a_robinhood(monkeypatch):
    """0.32.339: o BOT trabalha mesmo sem a página aberta — a carteira nasce para toda conta com carteira na /hood."""
    w, b = bot(monkeypatch)
    w.copier = hoodcopy.Copier(w, Http())
    w.copier.book("dono")
    assert "dono" not in b.books
    assert b.ensure_books() == 1 and "dono" in b.books and b.books["dono"].dirty_book
    run(b.tick())
    assert b.ensure_books() == 0


def test_bot_live_copia_os_top_traders_sem_bloqueio_e_com_stop(monkeypatch):
    """0.32.340: todos os top traders (mesmo não aptos/offline) e saídas com stop de perda e stop móvel."""
    w, b = bot(monkeypatch)
    assert b.w.ranking()["copiaria"] == [TRADER]                       # o trader não era "apto" nem online, e entra
    w.danger_reason = lambda wallet: "robô"
    assert b.w.danger_reason(TRADER) is None                           # PERIGO da /hood não vale no BOT LIVE
    c = b.book("novo").cfg
    assert c["stop_pct"] == botlive.SAIDAS["stop_pct"] and c["trail_on"] and c["max_hold_h"] == botlive.SAIDAS["max_hold_h"]
    b.books["novo"].cfg["stop_pct"] = 30.0                            # o dono mudou: fica como ele quis
    assert b.book("novo").cfg["stop_pct"] == 30.0


def test_log_do_bot_live_mostra_horario_token_rede_e_motivo():
    import os
    js = open(os.path.join(os.path.dirname(__file__), "..", "web", "sala.js"), encoding="utf-8").read()
    assert "function renderBotLog(" in js and "function radar(" in js and '"NC"' in js
    api = open(os.path.join(os.path.dirname(__file__), "..", "app", "botlive_api.py"), encoding="utf-8").read()
    assert "fill_names" in api


def test_link_do_obs_abre_sem_login_so_com_o_codigo_e_o_banco_guarda_so_o_hash(monkeypatch):
    """0.32.347 (pedido do dono): o link do OBS abre a SALA LIVE direto, sem login; gerar outro derruba o anterior."""
    import hashlib
    w, b = bot(monkeypatch)
    k1 = b.obs_new("u1")
    assert b.obs_user(k1) == "u1" and b.obs["u1"] == hashlib.sha256(k1.encode()).hexdigest()
    assert b._book_extra("u1") == {"obs_hash": b.obs["u1"]} and k1 not in str(b._book_extra("u1"))
    k2 = b.obs_new("u1")
    assert b.obs_user(k1) is None and b.obs_user(k2) == "u1"            # o link antigo parou
    assert b.obs_user("") is None and b.obs_user("x" * 30) is None
    b2 = botlive.BotLive(w, Http())                                        # depois de reiniciar, volta do banco
    b2._book_loaded({"user_id": "u1", "cfg": {"obs_hash": b.obs["u1"]}})
    assert b2.obs_user(k2) == "u1"


def test_rota_publica_do_obs_recusa_codigo_errado_e_gerar_exige_login(env):
    c = env["c"]
    assert c.post("/api/botlive/obs-link", json={}).status_code == 401
    r = c.get("/api/botlive/obs/painel?k=" + "A" * 32)
    assert r.status_code in (200, 403)
    assert "posicoes" not in r.json()                                      # código que não existe não lê nada
