"""0.32.370 (pedido do dono, 15/11/2026): conector do cTrader do Projeto Forex (etapa 2). Tudo sem internet: o servidor do
cTrader é falso (mesmo formato JSON do WebSocket oficial) e a troca do token também."""
import asyncio
import json
import os
import random
import urllib.parse

from app import ctrader as ct
from app import forexcopy as fc
from tests.test_api import env  # noqa: F401  (fixture env)

DIA = 86400
NOW = 1_763_200_000.0


def run(c):
    return asyncio.new_event_loop().run_until_complete(c)


def deal(did, pid, side, vol, t, price, close=None, sid=1, status=2):
    d = {"dealId": did, "orderId": did, "positionId": pid, "volume": vol, "filledVolume": vol, "symbolId": sid,
         "createTimestamp": int(t * 1000), "executionTimestamp": int(t * 1000), "executionPrice": price, "tradeSide": side,
         "dealStatus": status, "commission": -35, "moneyDigits": 2}
    if close:
        d["closePositionDetail"] = close
    return d


def cpd(entry, gross, balance, closed, swap=0, comm=-35):
    return {"entryPrice": entry, "grossProfit": gross, "swap": swap, "commission": comm, "balance": balance, "closedVolume": closed,
            "moneyDigits": 2}


# ------------------------------------------------------------------------------------------------------------------ conversões
def test_historico_junta_parciais_e_ignora_posicao_ainda_aberta():
    t0 = NOW - 10 * DIA
    deals = [
        deal(1, 10, 1, 10_000_000, t0, 1.08),                                                   # compra 1 lote
        deal(2, 10, 2, 4_000_000, t0 + 600, 1.081, cpd(1.08, 4000, 1_003_930, 4_000_000)),        # fecha 0,4: +40,00 −0,35
        deal(3, 10, 2, 6_000_000, t0 + 900, 1.082, cpd(1.08, 12000, 1_015_860, 6_000_000)),       # fecha 0,6: +120,00 −0,35
        deal(4, 11, 2, 10_000, t0 + 1000, 2400.0, sid=41),                                         # vende 1 lote de ouro (lotSize 10000)
        deal(5, 11, 1, 5_000, t0 + 2000, 2390.0, cpd(2400.0, 50000, 1_065_825, 5_000), sid=41),    # fechou só metade: segue aberta
        deal(6, 12, 1, 10_000_000, t0, 1.0, status=4),                                             # rejeitado: não conta
    ]
    trades, ini = ct.historico(deals, {1: "EURUSD", 41: "XAUUSD"}, {1: 10_000_000, 41: 10_000})
    assert len(trades) == 1
    t = trades[0]
    assert t["ticket"] == "10" and t["simbolo"] == "EURUSD" and t["lado"] == "buy" and t["volume"] == 1.0
    assert t["lucro"] == round(40 - 0.35 + 120 - 0.35, 2) and "sl" not in t                    # stop desconhecido no histórico
    assert ini == round(10_039.30 - 39.65, 2)                                                    # saldo antes do 1º fechamento


def test_evento_ao_vivo_vira_abriu_parcial_fechou_e_modificou():
    conta = {"simbolos": {1: "EURUSD"}, "lot": {1: 10_000_000}, "posicoes": {}, "md": 2}
    pos = {"positionId": 77, "tradeData": {"symbolId": 1, "volume": 20_000_000, "tradeSide": 1}, "positionStatus": 1,
           "stopLoss": 1.07, "takeProfit": 1.1, "price": 1.08}
    ab = ct.evento({"executionType": 3, "position": pos, "deal": deal(1, 77, 1, 20_000_000, NOW, 1.08)}, conta)
    assert ab["evento"] == "abriu" and ab["lado"] == "buy" and ab["volume"] == 2.0 and ab["sl"] == 1.07 and ab["ticket"] == "77"
    conta["posicoes"]["77"] = {"lado": "buy", "volume": 2.0, "sl": 1.07, "tp": 1.1}
    mo = ct.evento({"executionType": "ORDER_REPLACED", "position": {**pos, "stopLoss": 1.075}}, conta)
    assert mo["evento"] == "modificou" and mo["sl"] == 1.075
    pa = ct.evento({"executionType": 3, "position": pos, "deal": deal(2, 77, 2, 5_000_000, NOW, 1.09, cpd(1.08, 5000, 1_004_965, 5_000_000))}, conta)
    assert pa["evento"] == "fechou_parcial" and pa["volume_fechado"] == 0.5 and pa["lucro"] == 49.65 and pa["saldo"] == 10_049.65
    fe = ct.evento({"executionType": 3, "position": {**pos, "positionStatus": 2},
                    "deal": deal(3, 77, 2, 15_000_000, NOW, 1.09, cpd(1.08, 15000, 1_019_930, 15_000_000))}, conta)
    assert fe["evento"] == "fechou" and fe["lado"] == "buy"
    au = ct.evento({"executionType": 3, "position": pos, "deal": deal(4, 77, 1, 10_000_000, NOW, 1.085)}, conta)
    assert au["evento"] == "aumentou"                                                            # não é copiado nesta etapa
    assert ct.evento({"executionType": 2, "position": pos}, conta) is None                       # ordem aceita: nada muda


# ------------------------------------------------------------------------------------------------------------------ servidor falso
class FakeWS:
    def __init__(self, srv, url):
        self.srv, self.url = srv, url
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.sent = []

    async def send(self, s):
        d = json.loads(s)
        self.sent.append(d)
        pt, pl, mid = d["payloadType"], d.get("payload") or {}, d.get("clientMsgId")
        if pt == 51:
            return
        r = self.srv.answer(pt, pl)
        await self.inbox.put(json.dumps({"clientMsgId": mid, "payloadType": r[0], "payload": r[1]}))

    async def recv(self):
        return await self.inbox.get()

    async def close(self):
        pass


class FakeServer:
    def __init__(self, deals, live=True):
        self.deals, self.live, self.wss = deals, live, []

    async def connect(self, url):
        ws = FakeWS(self, url)
        self.wss.append(ws)
        return ws

    def answer(self, pt, pl):
        if pt == 2100:
            return (2101, {}) if pl.get("clientSecret") == "segredo-123" else (2142, {"errorCode": "CH_CLIENT_AUTH_FAILURE"})
        if pt == 2149:
            return 2150, {"accessToken": pl["accessToken"], "ctidTraderAccount": [{"ctidTraderAccountId": 111, "isLive": self.live, "traderLogin": 5001}]}
        if pt == 2102:
            return 2103, {"ctidTraderAccountId": pl["ctidTraderAccountId"]}
        if pt == 2121:
            return 2122, {"trader": {"ctidTraderAccountId": 111, "balance": 1_500_000, "moneyDigits": 2, "brokerName": "Corretora X",
                                     "traderLogin": 5001, "depositAssetId": 1}}
        if pt == 2114:
            return 2115, {"symbol": [{"symbolId": 1, "symbolName": "EURUSD"}, {"symbolId": 41, "symbolName": "XAUUSD"}]}
        if pt == 2124:
            return 2125, {"position": []}
        if pt == 2133:
            ds = [d for d in self.deals if pl["fromTimestamp"] <= d["executionTimestamp"] < pl["toTimestamp"]]
            return 2134, {"deal": ds, "hasMore": False}
        if pt == 2116:
            return 2117, {"symbol": [{"symbolId": i, "lotSize": 10_000 if i == 41 else 10_000_000} for i in pl["symbolId"]]}
        return 2142, {"errorCode": "NAO_SEI", "description": str(pt)}

    async def push(self, payload, pt=2126):
        await self.wss[-1].inbox.put(json.dumps({"payloadType": pt, "payload": payload}))


class Vault:
    def __init__(self):
        self.d = {}

    async def load(self, uid):
        return dict(self.d.get(uid, {}))

    async def save(self, uid, n, v):
        self.d.setdefault(uid, {})[n] = v

    async def delete(self, uid, n):
        self.d.get(uid, {}).pop(n, None)


class Http:
    def __init__(self):
        self.calls = []

    async def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))

        class R:
            status_code = 200

            def json(self_):
                if params.get("code") == "RUIM":
                    return {"errorCode": "ACCESS_DENIED", "description": "código vencido"}
                return {"accessToken": "AT-segredo-1", "refreshToken": "RT-segredo-1", "expiresIn": 2628000, "tokenType": "bearer"}
        return R()


def historico_bom(n=140, dias=120):
    """Mestre consistente: ganhos pequenos e perdas menores, ~1 trade por dia em 120 dias."""
    random.seed(3)
    out, bal, did = [], 1_000_000, 1
    for i in range(n):
        t = NOW - dias * DIA + i * (dias * DIA / n)
        g = random.choice([3000, 2500, 4000, -1500, 2000, -1200, 3500])
        out.append(deal(did, 1000 + i, 1, 1_000_000, t, 1.08)); did += 1
        bal += g - 35
        out.append(deal(did, 1000 + i, 2, 1_000_000, t + 3600, 1.081, cpd(1.08, g, bal, 1_000_000))); did += 1
    return out


async def _conecta(srv, copier=None, live=True):
    v, http = Vault(), Http()
    copier = copier or fc.ForexCopier(clock=lambda: NOW)
    h = ct.CTraderHub(http, copier, None, v, connect=srv.connect, clock=lambda: NOW, sleep=lambda s: asyncio.sleep(0))
    copier.ct = h
    await v.save("u1", "ctrader_client_id", "cliente-123")
    await v.save("u1", "ctrader_client_secret", "segredo-123")
    url = h.auth_url("u1", "cliente-123", "https://site/forex/ctrader/retorno")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert q["scope"] == ["accounts"] and q["client_id"] == ["cliente-123"]          # só leitura
    assert h.take_state(q["state"][0]) == "u1" and h.take_state(q["state"][0]) is None
    await h.exchange("u1", "CODE", "https://site/forex/ctrader/retorno")
    await h.volta()
    return h, v, copier, http


def test_conecta_le_historico_e_o_mestre_entra_no_ranking():
    async def go():
        srv = FakeServer(historico_bom())
        h, v, copier, http = await _conecta(srv)
        c = h.users["u1"]["contas"]["111"]
        assert c["pronta"] and c["status"] == "conectado" and c["saldo"] == 15_000 and c["corretora"] == "Corretora X"
        assert len(c["trades"]) == 140 and c["apelido"] == "Corretora X #5001"
        assert h.ranking and h.ranking[0]["id"] == "ct:111" and h.ranking[0]["elegivel"], h.ranking[0]["motivos"]
        assert copier.mestres["ct:111"]["elegivel"] and copier.mestres["ct:111"]["patrimonio"] == 15_000
        assert srv.wss[0].url == ct.HOSTS["live"]
        tk = json.loads(v.d["u1"]["ctrader_tokens"])
        assert tk["a"] == "AT-segredo-1" and tk["r"] == "RT-segredo-1"
        st = await h.status("u1")
        txt = json.dumps(st) + json.dumps(h.mestres_da("u1")) + json.dumps(h.ranking)
        assert "segredo" not in txt and "AT-" not in txt and "cliente-123" not in txt          # nada de chave na resposta
        assert st["client_id"] is True and st["conectado"] is True
        assert http.calls[0][1]["grant_type"] == "authorization_code"
        await h.fechar()
    run(go())


def test_demo_vai_para_o_servidor_demo_e_fica_fora_do_ranking():
    async def go():
        srv = FakeServer(historico_bom(), live=False)
        h, *_ = await _conecta(srv)
        assert any(w.url == ct.HOSTS["demo"] for w in srv.wss)
        r = h.ranking[0]
        assert not r["elegivel"] and "conta demo" in r["motivos"]
        await h.fechar()
    run(go())


def test_evento_ao_vivo_copia_na_carteira_ficticia_de_quem_segue():
    async def go():
        srv = FakeServer(historico_bom())
        copier = fc.ForexCopier(clock=lambda: NOW)
        b = copier.livro("u2")
        b.cfg = fc.clean_cfg({"saldo_inicial": 1500, "seguindo": ["ct:111"], "slip_pips": 0, "comissao_lote": 0}, b.cfg)
        b.caixa = 1500
        h, *_ = await _conecta(srv, copier)
        pos = {"positionId": 9001, "tradeData": {"symbolId": 1, "volume": 10_000_000, "tradeSide": 1}, "positionStatus": 1, "stopLoss": 1.07}
        await srv.push({"ctidTraderAccountId": 111, "executionType": 3, "position": pos, "deal": deal(9, 9001, 1, 10_000_000, NOW, 1.08)})
        for _ in range(20):
            await asyncio.sleep(0)
        assert "ct:111:9001" in b.abertas and b.abertas["ct:111:9001"]["lote"] == 0.1          # 1 lote × (1.500 ÷ 15.000)
        assert "9001" in h.users["u1"]["contas"]["111"]["posicoes"]
        await srv.push({"ctidTraderAccountId": 111, "executionType": 3, "position": {**pos, "positionStatus": 2},
                        "deal": deal(10, 9001, 2, 10_000_000, NOW + 60, 1.082, cpd(1.08, 20000, 1_519_965, 10_000_000))})
        for _ in range(20):
            await asyncio.sleep(0)
        assert "ct:111:9001" not in b.abertas and b.fechadas[-1]["lucro"] == round(199.65 * 0.1, 2)
        c = h.users["u1"]["contas"]["111"]
        assert c["saldo"] == 15_199.65 and c["trades"][-1]["ticket"] == "9001" and c["trades"][-1]["sl"] == 1.07
        await h.fechar()
    run(go())


def test_pausar_conta_tira_do_ranking_e_lembra_na_proxima_volta():
    async def go():
        srv = FakeServer(historico_bom())
        h, v, copier, _ = await _conecta(srv)
        assert h.set_off("u1", "111", True)
        assert not h.ranking and "ct:111" not in copier.mestres
        assert copier.livro("u1").cfg["ct_off"] == ["111"]
        assert fc.Livro.load(copier.livro("u1").dump()).cfg["ct_off"] == ["111"]             # sobrevive ao reinício
        await h.volta()
        assert not h.users["u1"]["contas"]["111"]["pronta"]
        h.set_off("u1", "111", False)
        await h.volta()
        assert h.users["u1"]["contas"]["111"]["pronta"] and h.ranking
        await h.fechar()
    run(go())


def test_segredo_errado_e_codigo_vencido_viram_erro_claro():
    async def go():
        srv = FakeServer([])
        v, http = Vault(), Http()
        h = ct.CTraderHub(http, fc.ForexCopier(clock=lambda: NOW), None, v, connect=srv.connect, clock=lambda: NOW, sleep=lambda s: asyncio.sleep(0))
        await v.save("u1", "ctrader_client_id", "cliente-123")
        await v.save("u1", "ctrader_client_secret", "errado-123")
        try:
            await h.exchange("u1", "RUIM", "https://x")
            assert False
        except ValueError as e:
            assert "código vencido" in str(e)
        await v.save("u1", "ctrader_tokens", json.dumps({"a": "AT", "r": "RT", "exp": NOW + 30 * DIA}))
        h.users["u1"] = {"contas": {}, "erro": None}          # no servidor, a lista vem do user_secrets
        await h.volta()
        assert "CH_CLIENT_AUTH_FAILURE" in h.users["u1"]["erro"]
    run(go())


def test_token_perto_de_vencer_e_renovado_e_gravado():
    async def go():
        srv = FakeServer(historico_bom(20, 30))
        v, http = Vault(), Http()
        h = ct.CTraderHub(http, fc.ForexCopier(clock=lambda: NOW), None, v, connect=srv.connect, clock=lambda: NOW, sleep=lambda s: asyncio.sleep(0))
        await v.save("u1", "ctrader_client_id", "cliente-123")
        await v.save("u1", "ctrader_client_secret", "segredo-123")
        await v.save("u1", "ctrader_tokens", json.dumps({"a": "AT-velho", "r": "RT-velho", "exp": NOW + DIA}))
        h.users["u1"] = {"contas": {}, "erro": None}
        await h.volta()
        await h.fechar()
        assert http.calls[-1][1]["grant_type"] == "refresh_token" and http.calls[-1][1]["refresh_token"] == "RT-velho"
        assert json.loads(v.d["u1"]["ctrader_tokens"])["a"] == "AT-segredo-1"
    run(go())


def test_rotas_do_ctrader_exigem_admin_e_retorno_com_state_errado_volta_com_erro(env):
    c = env["c"]
    for path in ("/api/forex/ctrader", "/api/forex/ctrader/conectar"):
        assert c.get(path).status_code == 401
    for path in ("/api/forex/ctrader/chave", "/api/forex/ctrader/remover", "/api/forex/ctrader/conta", "/api/forex/seguir"):
        assert c.post(path, json={}).status_code == 401
    r = c.get("/forex/ctrader/retorno?code=x&state=nao-existe", follow_redirects=False)
    assert r.status_code in (302, 307) and "ct=erro" in r.headers["location"]


def test_migracao_libera_os_nomes_e_o_stack_tem_o_banco_local():
    sql = open(os.path.join("supabase", "migrations", "20261115000002_forex_ctrader_chaves.sql"), encoding="utf-8").read()
    for n in ("'ctrader_client_id'", "'ctrader_client_secret'", "'ctrader_tokens'", "'youtube_refresh_token'", "'wallet_private_key'"):
        assert n in sql
    from app.keystore import BNB_SECRET_NAMES
    assert {"ctrader_client_id", "ctrader_client_secret", "ctrader_tokens"} <= set(BNB_SECRET_NAMES)
    stack = open(os.path.join("deploy", "portainer-stack.yml"), encoding="utf-8").read()
    assert "pump_forex_api:" in stack and "FOREX_DB_URL=http://pump_forex_api:3000" in stack and "${FOREX_DB_PASSWORD:-sem_senha}" in stack
