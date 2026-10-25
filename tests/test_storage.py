"""Etapa 4: criptografia das chaves, gravação no banco por usuário e isolamento entre 2 usuários."""
import asyncio
import base64
import json
import os

import httpx
import pytest

from tests.fakes import FakeREST

UA = "11111111-1111-1111-1111-111111111111"
UB = "22222222-2222-2222-2222-222222222222"
MASTER = base64.b64encode(os.urandom(32)).decode()
W = "TraderGood1111111111111111111111111111111"
W2 = "TraderBeta1111111111111111111111111111111"


def _ev(kind, who, mint, sol, tok, vs, vt, **x):
    return {"txType": kind, "traderPublicKey": who, "mint": mint, "solAmount": sol, "tokenAmount": tok,
            "vSolInBondingCurve": vs, "vTokensInBondingCurve": vt, "marketCapSol": vs * 30, **x}


def _engine(db, uid, market=None):
    from app.db import SupabaseStore
    from app.pumpfun import PumpFun, PumpMarket
    from app.settings import PumpSettings
    cfg = PumpSettings()
    cfg.pump_min_mcap_usd = cfg.pump_min_vol_h1_usd = cfg.pump_max_top10_pct = cfg.pump_min_wallet_usd = 0
    cfg.pump_min_txns_h1 = 0
    st = SupabaseStore(db, uid)
    return PumpFun(cfg, st, market=market or PumpMarket()), st


# ---------------------------------------------------------------- criptografia
def test_aes_gcm_roundtrip_and_binding():
    from app.crypto import CryptoError, SecretBox, load_master_key
    box = SecretBox(MASTER)
    blob = box.encrypt(UA, "wallet_private_key", "segredo-super-secreto-123")
    assert blob.startswith("v1:") and "segredo" not in blob
    assert box.encrypt(UA, "wallet_private_key", "x" * 20) != box.encrypt(UA, "wallet_private_key", "x" * 20)
    assert box.decrypt(UA, "wallet_private_key", blob) == "segredo-super-secreto-123"
    with pytest.raises(CryptoError):
        box.decrypt(UB, "wallet_private_key", blob)          # cifra de A copiada para B não abre
    with pytest.raises(CryptoError):
        box.decrypt(UA, "rpc_url", blob)                     # nem trocando de campo
    with pytest.raises(CryptoError):
        SecretBox(base64.b64encode(os.urandom(32)).decode()).decrypt(UA, "wallet_private_key", blob)
    with pytest.raises(CryptoError):
        load_master_key("curta")
    assert len(load_master_key(os.urandom(32).hex())) == 32


def test_vault_saves_encrypted_and_isolated():
    from app.crypto import SecretBox
    from app.db import Vault
    db = FakeREST()
    v = Vault(db, SecretBox(MASTER))
    asyncio.run(v.save(UA, "solanatracker_api_key", "st-chave-do-A-1234567890"))
    asyncio.run(v.save(UB, "solanatracker_api_key", "st-chave-do-B-0987654321"))
    raw = json.dumps(db.tables["user_secrets"])
    assert "st-chave" not in raw                                      # no banco só a cifra
    assert asyncio.run(v.load(UA)) == {"solanatracker_api_key": "st-chave-do-A-1234567890"}
    assert asyncio.run(v.load(UB)) == {"solanatracker_api_key": "st-chave-do-B-0987654321"}
    asyncio.run(v.delete(UA, "solanatracker_api_key"))
    assert asyncio.run(v.load(UA)) == {} and asyncio.run(v.names(UB)) == {"solanatracker_api_key"}
    with pytest.raises(ValueError):
        asyncio.run(v.save(UA, "qualquer_coisa", "x" * 20))


# ---------------------------------------------------------------- configurações
def test_settings_real_always_off_and_validation():
    from app.settings import PumpSettings, USER_KEYS
    s = PumpSettings({"pump_real_enabled": True, "pump_copy_sol": 0.3, "pump_stop_pct": 999, "lixo": 1})
    assert s.pump_real_enabled is False and s.pump_copy_sol == 0.3 and s.pump_stop_pct == 40.0
    applied, errors = s.apply({"pump_real_enabled": True, "pump_copy_sol": "0.2", "pump_lb_days": 5,
                               "pump_max_open": "abc", "pump_rpc_ws": "wss://x"})
    assert applied == {"pump_copy_sol": 0.2} and s.pump_real_enabled is False
    assert set(errors) == {"pump_real_enabled", "pump_lb_days", "pump_max_open", "pump_rpc_ws"}
    assert "pump_real_enabled" not in s.user_dict() and set(s.user_dict()) == set(USER_KEYS)


def test_env_overrides_defaults(monkeypatch):
    from app.settings import PumpSettings
    monkeypatch.setenv("PUMP_COPY_SOL", "0.25")
    monkeypatch.setenv("PUMP_REAL_ENABLED", "true")             # ignorado: real nunca liga pelo .env
    s = PumpSettings()
    assert s.pump_copy_sol == 0.25 and s.pump_real_enabled is False


# ---------------------------------------------------------------- gravação + isolamento
def test_two_users_data_written_and_isolated():
    db = FakeREST()
    db.add_user(UA, "a@x.com")
    db.add_user(UB, "b@x.com")
    a, sa = _engine(db, UA)
    b, sb = _engine(db, UB, market=a.market)                  # mesmo mercado público, dados separados
    a.add_manual(W)
    b.add_manual(W2)
    b.ban(W)
    m = "MintA".ljust(40, "1") + "pump"
    a.on_message(_ev("buy", W, m, 1.0, 1e6, 30, 3e7))
    assert len(a.positions()) == 1 and not b.positions()
    asyncio.run(sa.flush())
    asyncio.run(sb.flush())
    pos = db.tables["pump_positions"]
    assert len(pos) == 1 and pos[0]["user_id"] == UA and pos[0]["real"] is False
    lists = {(r["user_id"], r["tipo"], r["wallet"]) for r in db.tables["pump_lists"]}
    assert lists == {(UA, "manual", W), (UB, "manual", W2), (UB, "banida", W)}
    assert all(r["user_id"] == UA for r in db.tables["pump_feed"]) and db.tables["pump_feed"]
    # trader vende → trade fechado só do A
    a.on_message(_ev("sell", W, m, 1.5, 1e6, 30, 3e7 / 1.5, newTokenBalance=0))
    asyncio.run(sa.flush())
    assert not db.tables["pump_positions"] and len(db.tables["pump_trades"]) == 1
    assert db.tables["pump_trades"][0]["user_id"] == UA
    # toda escrita/leitura do servidor filtra por user_id
    for op, table, f in db.calls:
        if op in ("select", "delete"):
            assert f.get("user_id") in (UA, UB), (op, table, f)


def test_reload_after_restart_keeps_state_and_real_off():
    db = FakeREST()
    db.add_user(UA, "a@x.com")
    a, sa = _engine(db, UA)
    a.add_manual(W)
    a.pause(W2, 24)
    m = "Keep".ljust(40, "1") + "pump"
    a.on_message(_ev("buy", W, m, 1.0, 1e6, 30, 3e7))
    pid = a.positions()[0]["id"]
    asyncio.run(sa.flush())
    # "reiniciou o servidor": novo motor, carrega do banco
    from app.db import SupabaseStore
    from app.pumpfun import PumpFun
    from app.settings import PumpSettings
    st2 = SupabaseStore(db, UA)
    asyncio.run(st2.load())
    a2 = PumpFun(PumpSettings({"pump_real_enabled": True}), st2)
    assert [p["id"] for p in a2.positions()] == [pid] and a2.manual == [W] and a2.is_paused(W2)
    assert a2.cfg.pump_real_enabled is False and a2.feed
    # zerar fictícia apaga só o fictício do próprio usuário
    db.tables["pump_trades"].append({"id": "outro", "user_id": UB, "real": False, "data": {}})
    a2.reset_sim()
    asyncio.run(st2.flush())
    assert not db.tables["pump_positions"] and [t["id"] for t in db.tables["pump_trades"]] == ["outro"]


def test_flush_retries_when_db_is_down():
    db = FakeREST()
    a, sa = _engine(db, UA)
    a.add_manual(W)
    db.fail = True
    asyncio.run(sa.flush())
    assert sa.last_error and sa._q
    db.fail = False
    asyncio.run(sa.flush())
    assert not sa._q and sa.last_error is None and db.tables["pump_lists"]


def test_supa_rest_sends_service_key_and_user_filter():
    from app.db import SupaREST
    seen = []

    def h(req):
        seen.append(req)
        return httpx.Response(200, json=[{"id": "x"}])
    rest = SupaREST("https://abc.supabase.co", "service-key-xyz-123456", httpx.AsyncClient(transport=httpx.MockTransport(h)))
    rows = asyncio.run(rest.select("pump_positions", {"user_id": UA, "real": False}, order="id.desc", limit=5))
    r = seen[0]
    assert rows == [{"id": "x"}] and r.url.path == "/rest/v1/pump_positions"
    assert r.url.params["user_id"] == f"eq.{UA}" and r.url.params["real"] == "eq.false"
    assert r.headers["apikey"] == "service-key-xyz-123456"
    with pytest.raises(Exception):
        asyncio.run(rest.delete("pump_positions", {}))           # delete sem filtro é bloqueado


def test_migration_runner_only_applies_pending_in_order():
    """scripts/aplicar_migracoes.py: aplica só o que falta, em ordem; nome fora do padrão para tudo."""
    import importlib.util
    import pathlib
    import pytest
    path = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "aplicar_migracoes.py"
    spec = importlib.util.spec_from_file_location("aplicar_migracoes", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    files = ["20261025000004_aprendizado_diario.sql", "20261025000001_inicial.sql", "20261026000001_outra.sql"]
    assert mod.pending(files, {"20261025000001_inicial.sql"}) == ["20261025000004_aprendizado_diario.sql",
                                                                   "20261026000001_outra.sql"]
    with pytest.raises(SystemExit):
        mod.pending(["x;drop table.sql"], set())
    real = sorted(p.name for p in (path.parents[1] / "supabase" / "migrations").glob("*.sql"))
    assert set(mod.BASELINE) <= set(real) and mod.pending(real, set(real)) == []
