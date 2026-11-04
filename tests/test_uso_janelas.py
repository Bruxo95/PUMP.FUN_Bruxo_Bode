"""0.32.185 (pedido do dono): uso de cada serviço em 1, 6, 12 e 24 h, desde o início e no mês. Sem internet."""
import json

from app import apiusage
from app.apiusage import Usage

T0 = 1_800_000_000.0


def _u():
    u = Usage()
    u.started = T0 - 30 * 3600
    return u


def test_helius_counts_requests_and_credits_get_program_accounts_costs_10():
    u = _u()
    for _ in range(5):
        u.count("mainnet.helius-rpc.com", body=json.dumps({"method": "getTransaction"}).encode(), now=T0)
    u.count("mainnet.helius-rpc.com", body=json.dumps([{"method": "getProgramAccounts"}, {"method": "getSlot"}]).encode(), now=T0)
    rows = {r["tipo"]: r for r in u.windows(now=T0 + 10) if r["api"] == "Helius (RPC da Solana)"}
    assert rows["requisições"]["janelas"]["1"]["n"] == 6 and rows["créditos"]["janelas"]["1"]["n"] == 16
    assert rows["créditos"]["limite_mes"] == 1_000_000 and rows["créditos"]["pct_mes"] == 0.002
    assert rows["requisições"]["limite_mes"] is None and rows["requisições"]["limite_min"] == 600
    assert all(r["api"] != "Helius (RPC da Solana) · créditos" for r in u.view(now=T0 + 10))


def test_windows_split_by_hour_and_since_start():
    u = _u()
    for h in (0.5, 3, 10, 20, 26):
        u.count("data.solanatracker.io", now=T0 - h * 3600)
    r = next(x for x in u.windows(now=T0) if x["api"] == "Solana Tracker")
    assert [r["janelas"][k]["n"] for k in ("1", "6", "12", "24")] == [1, 2, 3, 4]
    assert r["desde_inicio"] == 5 and r["janelas"]["24"]["pct"] == 0.04


def test_websocket_messages_and_paid_pumpportal_trades():
    u = _u()
    for _ in range(20_000):
        u.ws("PumpPortal", apiusage.PP_PAID, now=T0)
    u.ws("Helius (RPC da Solana)", "WebSocket: mensagens recebidas", now=T0)
    rows = {(r["api"], r["tipo"]): r for r in u.windows(now=T0)}
    pp = rows[("PumpPortal", apiusage.PP_PAID)]
    assert pp["janelas"]["1"]["n"] == 20_000 and pp["custo_sol"]["24"] == 0.02 and pp["janelas"]["1"]["pct"] is None
    assert rows[("Helius (RPC da Solana)", "WebSocket: mensagens recebidas")]["limite_min"] is None


def test_old_month_rows_get_the_new_names():
    u = _u()
    u.load([{"mes": "2027-01", "api": "RPC próprio / outros (mainnet.helius-rpc.com)", "chave": "", "n": 50},
            {"mes": "2027-01", "api": "RPC próprio / outros (bsc-rpc.publicnode.com)", "chave": "", "n": 7}])
    assert ("2027-01", "Helius (RPC da Solana)", None) in u.month and ("2027-01", "RPC da BNB (publicnode)", None) in u.month


def test_month_credits_count_at_least_the_month_requests():
    u = _u()
    u.load([{"mes": "2027-01", "api": "RPC próprio / outros (mainnet.helius-rpc.com)", "chave": "", "n": 987_150}])
    t = T0                                                # 15/01/2027 (UTC)
    u.count("mainnet.helius-rpc.com", body=b'{"method":"getSlot"}', now=t)
    r = next(x for x in u.windows(now=t) if x["api"] == "Helius (RPC da Solana)" and x["tipo"] == "créditos")
    assert r["mes"] == 987_151 and r["mes_minimo"] is True and r["pct_mes"] == 98.715
