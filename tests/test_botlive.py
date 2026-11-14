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


def test_compra_do_bot_vira_comentario_no_chat_do_youtube_so_quando_ligado(monkeypatch):
    """0.32.349 (pedido do dono): só as COMPRAS vão para o chat, com o hash da transação do trader copiado."""
    from app import ytchat
    t = ytchat.buy_text("MOON", "0x" + "ab" * 20, "0x" + "cd" * 32, "https://robinhoodchain.blockscout.com/")
    assert t.startswith("🤖 BOT BUY $MOON · copying trader 0xabab…abab") and t.endswith("/tx/0x" + "cd" * 32) and len(t) <= 200
    w, b = bot(monkeypatch)
    p = {"token": "0x" + "11" * 20, "wallet": TRADER, "tx_in": "0x" + "ee" * 32}
    b._sim_opened("u1", p)
    assert not b.yt.q.get("u1")                                            # desligado: nada vai para o chat
    b.yt.on["u1"] = True
    b.meta[p["token"]] = {"nome": "Moon Cat", "simbolo": "MOON"}
    b._sim_opened("u1", p)
    assert b.yt.q["u1"] == [ytchat.buy_text("MOON", TRADER, p["tx_in"], b.yt.explorer)]
    assert b._book_extra("u1") == {"yt_on": True}                          # o liga/desliga sobrevive ao reinício
    b2 = botlive.BotLive(w, Http())
    b2._book_loaded({"user_id": "u1", "cfg": {"yt_on": True}})
    assert b2.yt.on.get("u1") is True
    src = inspect.getsource(botlive_copy308.Book.buy)
    assert "open_hook" in src and "não copiou" in src                      # o gancho fica só na compra que abriu posição


def test_youtube_conecta_guarda_no_cofre_e_envia_para_a_live(monkeypatch):
    from app import ytchat

    class R:
        def __init__(self, code, j):
            self.status_code, self._j = code, j

        def json(self):
            return self._j

    class H:
        def __init__(self):
            self.sent = []

        async def post(self, url, data=None, json=None, params=None, headers=None, timeout=None):
            if url == ytchat.TOKEN:
                if data["grant_type"] == "authorization_code":
                    return R(200, {"access_token": "AT-1", "refresh_token": "RT-1", "expires_in": 3600})
                return R(200, {"access_token": "AT-2", "expires_in": 3600})
            assert url == ytchat.API + "/liveChat/messages"                  # 0.32.350: endereço oficial (o outro dava 404)
            self.sent.append((json["snippet"]["liveChatId"], json["snippet"]["textMessageDetails"]["messageText"], headers))
            return R(200, {"id": "m1"})

        async def get(self, url, params=None, headers=None, timeout=None):
            return R(200, {"items": [{"snippet": {"liveChatId": "CHAT1", "title": "Lofi live"}}]})

    class V:
        def __init__(self):
            self.d = {"youtube_client_id": "cid-123456", "youtube_client_secret": "sec-123456"}

        async def load(self, uid):
            return dict(self.d)

        async def names(self, uid):
            return set(self.d)

        async def save(self, uid, n, v):
            self.d[n] = v

    async def go():
        h, v = H(), V()
        y = ytchat.YTChat(h, v, "https://x")
        url = y.auth_url("u1", "cid-123456", "https://site/botlive/youtube/retorno")
        state = url.split("state=")[1]
        assert "youtube.force-ssl" in urllib.parse.unquote(url) and "access_type=offline" in url
        assert y.take_state(state) == "u1" and y.take_state(state) is None      # uso único
        await y.exchange("u1", "CODE", "https://site/botlive/youtube/retorno")
        assert v.d["youtube_refresh_token"] == "RT-1"
        assert await y.send("u1", "oi") is True
        st = await y.status("u1")
        assert st["conectado"] and st["live"] == "Lofi live" and st["enviadas_hoje"] == 1
        assert "RT-1" not in str(st) and "sec-123456" not in str(st) and "AT-1" not in str(st)   # nada de chave na resposta
        return h
    import urllib.parse
    h = run(go())
    assert h.sent[0][0] == "CHAT1" and h.sent[0][1] == "oi"


def test_rotas_do_youtube_exigem_login_e_migracao_libera_os_nomes(env):
    c = env["c"]
    for path in ("/api/botlive/youtube", "/api/botlive/youtube/conectar"):
        assert c.get(path).status_code == 401
    for path in ("/api/botlive/youtube/chave", "/api/botlive/youtube/ligar", "/api/botlive/youtube/teste", "/api/botlive/youtube/remover"):
        assert c.post(path, json={}).status_code == 401
    r = c.get("/botlive/youtube/retorno?code=x&state=nao-existe", follow_redirects=False)
    assert r.status_code in (302, 307) and "yt=erro" in r.headers["location"]
    sql = open("supabase/migrations/20261114000001_botlive_youtube.sql", encoding="utf-8").read()
    for n in ("'youtube_client_id'", "'youtube_client_secret'", "'youtube_refresh_token'", "'hood_private_key'", "'wallet_private_key'"):
        assert n in sql


def test_musicas_lofi_por_horario_guarda_toca_e_recusa_o_que_nao_e_audio():
    """0.32.351 (pedido do dono): 4 playlists (madrugada, manhã, trabalho, noite) com músicas enviadas em /botlive."""
    from app import botmusic

    async def go():
        m = botmusic.Music()
        mp3 = b"ID3" + b"\x00" * 200
        it = await m.add(mp3, "manha", "Morning Coffee", "Artista", "morning.mp3")
        await m.add(b"OggS" + b"\x00" * 100, "noite", "Night")
        for bad in ((b"<html>", "manha"), (mp3, "tarde"), (b"", "manha")):
            try:
                await m.add(bad[0], bad[1], "x")
                assert False
            except ValueError:
                pass
        pub = await m.public()
        assert set(pub["periodos"]) == {"madrugada", "manha", "trabalho", "noite"}
        assert [x["titulo"] for x in pub["faixas"]] == ["Morning Coffee", "Night"] and "bytes" not in pub["faixas"][0]
        assert (await m.file(it["id"]))[1] == "audio/mpeg"
        src = pub["faixas"][0]["src"]                                   # link assinado, vale 6 h
        e, s = src.split("e=")[1].split("&s=")
        assert m.check(it["id"], e, s) and not m.check(it["id"], e, "x" * 32) and not m.check(it["id"], "1", s)
        for bad in ("http://cdn.pixabay.com/a.mp3", "https://evil.com/a.mp3", "https://169.254.169.254/x"):
            try:
                await m.import_url(None, bad, "manha", "x")
                assert False
            except ValueError:
                pass
        assert await m.move(it["id"], "trabalho") and (await m.public())["faixas"][0]["periodo"] == "trabalho"
        m2 = botmusic.Music(m.st)                                      # a lista fica no próprio armazenamento (index.json)
        assert len(await m2.faixas()) == 2
        assert await m.remove(it["id"]) and await m.file(it["id"]) is None
    run(go())


def test_rotas_das_musicas_lista_publica_envio_so_admin(env):
    c = env["c"]
    assert c.get("/api/botlive/musicas").status_code == 401                 # lista: login ou código do OBS
    assert c.get("/api/botlive/obs/musicas?k=" + "A" * 32).status_code in (403, 200)
    assert c.post("/api/botlive/musicas/importar", json={}).status_code == 401
    assert c.post("/api/botlive/musicas", content=b"ID3xxx").status_code == 401
    assert c.post("/api/botlive/musicas/remover", json={}).status_code == 401
    assert c.get("/botlive/musica/naoexiste").status_code == 404
    assert c.get("/botlive/musica/abc123?e=9999999999&s=errada").status_code == 404   # sem assinatura certa não toca
    sql = open("supabase/migrations/20261114000002_botlive_musicas.sql", encoding="utf-8").read()
    assert "'botlive-music'" in sql and "false" in sql                    # bucket privado
    js = open("web/botlive2.js", encoding="utf-8").read()
    assert "madrugada" in js and "/api/botlive/obs/musicas" in js and "Lofi.start()" in js   # sem músicas, volta para a gerada


def test_sala_le_o_chat_a_cada_10_min_e_guarda_os_nomes(monkeypatch):
    """0.32.354 (pedido do dono): o personagem fala no balão o nome de quem escreveu no chat (lê a cada 10 min)."""
    from app import ytchat

    class R:
        def __init__(self, code, j):
            self.status_code, self._j = code, j

        def json(self):
            return self._j

    class H:
        def __init__(self):
            self.calls = []

        async def post(self, url, data=None, **k):
            return R(200, {"access_token": "AT", "expires_in": 3600})

        async def get(self, url, params=None, headers=None, timeout=None):
            self.calls.append(url)
            if url.endswith("/liveBroadcasts"):
                return R(200, {"items": [{"id": "VID1", "snippet": {"liveChatId": "C1", "title": "Lofi"}}]})
            if url.endswith("/liveChat/messages"):
                return R(200, {"nextPageToken": "P2", "items": [
                    {"authorDetails": {"displayName": "Maria Silva 🚀", "isChatOwner": False}},
                    {"authorDetails": {"displayName": "Canal Dono", "isChatOwner": True}}]})
            return R(200, {"items": [{"liveStreamingDetails": {"concurrentViewers": "47"}}]})

    class V:
        async def load(self, uid):
            return {"youtube_client_id": "c" * 10, "youtube_client_secret": "s" * 10, "youtube_refresh_token": "r" * 10}

    async def go():
        y = ytchat.YTChat(H(), V(), "https://x")
        assert y.room_due("u1")
        await y.poll_room("u1")
        v = y.room_view("u1")
        assert v["live"] and v["viewers"] == 47 and v["names"] == ["MARIA_SILVA"]   # o dono do canal não entra
        assert not y.room_due("u1")                                       # só daqui a 10 min (cota do YouTube)
        assert y.room["u1"]["page"] == "P2"                               # a próxima leitura pega só as mensagens novas
        y.room_off.add("u1")
        assert not y.room_due("u1", 10 ** 12)
        return y
    run(go())
    assert ytchat.clean_name("<script>x</script>") == "SCRIPTXSCRIPT" and len(ytchat.clean_name("a" * 50)) == 14


def test_baloes_do_chat_em_ingles_e_sem_placeholder_sobrando():
    js = open("web/sala.js", encoding="utf-8").read()
    for frase in ("WHERE IS EVERYBODY?", "WORKING ALONE AGAIN...", "HEY {N}! THANKS FOR WATCHING", "setInterval(talkNow, 600000)"):
        assert frase in js
    assert "/api/botlive/youtube/sala" in open("web/botlivecfg.js", encoding="utf-8").read()


def test_arte_do_spritecook_so_de_la_e_nomes_fixos(env):
    """0.32.355: personagem da SALA LIVE feito no SpriteCook; o servidor só baixa de cdn.spritecook.ai."""
    from app import botmusic

    async def go():
        m = botmusic.Music()
        for url, nome in (("https://evil.com/a.webp", "trader_atento"), ("http://cdn.spritecook.ai/a.webp", "trader_atento"),
                          ("https://cdn.spritecook.ai/a.webp", "../index.json")):
            try:
                await m.art_import(None, url, nome)
                assert False
            except ValueError:
                pass
        assert await m.art_file("index.json") is None and await m.art_file("trader_atento") is None
    run(go())
    c = env["c"]
    assert c.post("/api/botlive/arte/importar", json={}).status_code == 401
    assert c.get("/botlive/arte/trader_atento").status_code == 404
    js = open("web/sala.js", encoding="utf-8").read()
    assert "ImageDecoder" in js and "/botlive/arte/trader_" in js and "if (sprTrader()) return;" in js and "trader_base.png" in js
