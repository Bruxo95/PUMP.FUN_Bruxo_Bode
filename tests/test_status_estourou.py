"""0.32.235 (pedido do dono: "o RPC estourou e o status ficou ok"): o Status do sistema fica vermelho quando o serviço
passou do limite grátis, quando o RPC recusa leituras ou quando nenhuma leitura vira trade."""
import time

from app.apiusage import Usage
from tests.test_api import UA, env, tok  # noqa: F401  (fixture env)

H = "Helius (RPC da Solana)"
T0 = 1_790_000_000.0


def test_pct_por_minuto_usa_o_tempo_que_a_janela_cobre():
    """Janela que voltou do banco depois do reinício: 300/min por 24 h é 50% de 600/min, não 170%."""
    u = Usage()
    u.started = T0 - 7 * 3600                            # reiniciou há 7 h
    m = int(T0 // 60)
    u.win[(H, "requisições")] = {m - i: 300 for i in range(1440)}
    r = [x for x in u.windows(T0) if x["api"] == H and x["tipo"] == "requisições"][0]
    assert 49 <= r["janelas"]["24"]["pct"] <= 51
    assert not u.estourou(T0)


def test_estourou_os_creditos_do_mes():
    u = Usage()
    mes = time.strftime("%Y-%m", time.gmtime(T0))
    u.month[(mes, H + " · créditos", None)] = 1_584_194
    u.win[(H, "créditos")] = {int(T0 // 60): 10}
    e = u.estourou(T0)
    assert e[H]["tipo"] == "créditos" and e[H]["pct"] > 150


def test_status_do_rpc_fica_vermelho(env):
    c, hub = env["c"], env["hub"]
    st = hub.market.rpc_status
    st.update(ws=True, prov=H)
    a = c.get("/api/pump", headers=tok(UA)).json()["apis"]
    assert a["rpc"]["ok"] is True and a["solana_tracker_cota"]["estourou"] is False
    hub.market.rpc_429_at = time.time() - 60             # recusou há 1 min e nada deu certo depois
    a = c.get("/api/pump", headers=tok(UA)).json()["apis"]
    assert a["rpc"]["ok"] is False and "429" in a["rpc"]["motivos"][0]
    hub.market.rpc_ok_at = time.time()                   # voltou a ler
    assert hub.health_alerts()["rpc"]["ok"] is True


def test_estourou_aparece_no_rpc_e_na_solana_tracker(env):
    c, hub = env["c"], env["hub"]
    hub.market.rpc_status.update(ws=True, prov=H)

    class U:
        def estourou(self, now=None):
            return {H: {"tipo": "créditos", "pct": 158.4, "mes": 1_584_194, "limite_mes": 1_000_000, "limite_min": 600},
                    "Solana Tracker": {"tipo": "requisições", "pct": 120.0, "mes": 12_000, "limite_mes": 10_000, "limite_min": 180}}
    hub.usage = U()
    a = c.get("/api/pump", headers=tok(UA)).json()["apis"]
    assert a["rpc"]["ok"] is False and a["rpc"]["estourou"] and "158%" in a["rpc"]["motivos"][0]
    assert a["solana_tracker"]["ok"] is False and "12.000 de 10.000" in a["solana_tracker_cota"]["motivo"]


def test_nenhuma_leitura_vira_trade(env):
    hub = env["hub"]
    hub.market.rpc_status.update(ws=True, queued=8039, parsed=0)
    hub.started_at = time.time() - 7 * 3600
    al = hub.health_alerts()["rpc"]
    assert al["ok"] is False and "nenhuma virou trade" in al["motivos"][0]
