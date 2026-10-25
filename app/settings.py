"""Configurações.

- `ServerConfig`: o que vem do `.env` da VPS (Supabase, chave mestra, RPC público e as opções PUMP_* que mexem
  no monitor COMPARTILHADO).
- `PumpSettings`: as opções PUMP_* de UM usuário (mesmos padrões do projeto original). Ficam no banco
  (`user_settings.settings`) e só o próprio usuário muda pelo painel.

A execução REAL (`pump_real_enabled`) nunca é gravada: começa DESLIGADA e volta a desligar quando o servidor
reinicia.
"""
from __future__ import annotations

import os


def _env(k: str, d: str = "") -> str:
    v = os.environ.get(k)
    return d if v is None or v.strip() == "" else v.strip()


def _cast(typ, raw: str):
    if typ is bool:
        return raw.lower() in ("1", "true", "sim", "on", "yes")
    return typ(raw)


# nome: (tipo, padrão, mínimo, máximo)  — mesmos padrões do app/config.py original
USER_KEYS: dict[str, tuple] = {
    "pump_copy_enabled": (bool, True, 0, 1),
    "pump_sim_balance_sol": (float, 5.0, 0.01, 100000.0),
    "pump_copy_sol": (float, 0.1, 0.001, 100.0),
    "pump_copy_delay_s": (float, 0.0, 0.0, 3600.0),
    "pump_copy_other": (bool, True, 0, 1),
    "pump_copy_other_real": (bool, False, 0, 1),
    "pump_other_min_liq_usd": (float, 20000.0, 0.0, 1e9),
    "pump_other_fee_pct": (float, 0.30, 0.0, 5.0),
    "pump_other_slip_pct": (float, 1.0, 0.0, 50.0),
    "pump_max_open": (int, 10, 1, 50),
    "pump_extra_slip_pct": (float, 3.0, 0.0, 50.0),
    "pump_fee_pct": (float, 1.25, 0.0, 10.0),
    "pump_swap_fee_pct": (float, 0.30, 0.0, 5.0),
    "pump_portal_fee_pct": (float, 0.5, 0.0, 5.0),
    "pump_priority_sol": (float, 0.0005, 0.0, 0.1),
    "pump_stop_pct": (float, 40.0, 1.0, 100.0),
    "pump_hold_until_profit": (bool, True, 0, 1),
    "pump_hold_min_profit_pct": (float, 0.0, 0.0, 1000.0),
    "pump_min_mcap_usd": (float, 10000.0, 0.0, 1e10),
    "pump_min_vol_h1_usd": (float, 5000.0, 0.0, 1e10),
    "pump_min_txns_h1": (int, 30, 0, 100000),
    "pump_max_top10_pct": (float, 35.0, 0.0, 100.0),
    "pump_max_chase_pct": (float, 30.0, 0.0, 1000.0),
    # 0.13.2: cada opção nova tem botão ON/OFF (pedido do dono) — o número fica guardado mesmo desligado
    "pump_chase_on": (bool, True, 0, 1),
    "pump_tp1_on": (bool, False, 0, 1),
    "pump_curve_exit_on": (bool, False, 0, 1),
    "pump_curve_speed_on": (bool, False, 0, 1),
    "pump_buy_pressure_on": (bool, False, 0, 1),
    # 0.12.0 — pesquisa de 2026-10-25 (92% dos tokens têm derrubada forte; vender antes de graduar rendeu mais)
    "pump_tp1_pct": (float, 30.0, 0.0, 10000.0),        # venda em partes: realiza parte ao chegar em +X% (0 desliga)
    "pump_tp1_frac_pct": (float, 50.0, 1.0, 99.0),     # quanto vender nessa primeira saída
    "pump_curve_exit_pct": (float, 85.0, 0.0, 100.0),   # vende tudo quando a curva passa de X% (antes de graduar)
    "pump_min_curve_speed": (float, 5.0, 0.0, 1000.0), # só copia se a curva enche ao menos X% por minuto
    "pump_skip_graduated": (bool, False, 0, 1),        # não copia compra de token que já graduou (PumpSwap)
    "pump_size_by_trader": (bool, False, 0, 1),
    "pump_min_buy_pressure_pct": (float, 55.0, 0.0, 100.0),  # 0.13.0: só copia se as compras forem ≥ X% das negociações        # valor da cópia conforme o seu resultado com o trader  # não copia se o preço subiu mais que isso desde a compra do trader
    "pump_risk_check": (bool, True, 0, 1),          # nota de risco do token (Solana Tracker) antes de copiar
    "pump_max_risk_score": (int, 7, 1, 10),         # 1 = só tokens de risco baixo; 10 = só bloqueia "perigo"
    "pump_min_wallet_usd": (float, 5000.0, 0.0, 1e10),
    "pump_trail_enabled": (bool, True, 0, 1),
    "pump_trail_start_pct": (float, 20.0, 1.0, 10000.0),
    "pump_trail_dist_pct": (float, 10.0, 1.0, 1000.0),
    "pump_trail_min_lock_pct": (float, 2.0, 0.0, 1000.0),
    "pump_trail_fast_s": (float, 1.0, 0.0, 30.0),
    "pump_autopause_stops": (int, 2, 0, 100),
    "pump_autopause_hours": (float, 24.0, 0.0, 720.0),
    "pump_tp_pct": (float, 0.0, 0.0, 10000.0),
    "pump_max_hold_h": (float, 6.0, 0.05, 168.0),
    "pump_min_trader_sol": (float, 0.2, 0.0, 100.0),
    "pump_min_mcap_sol": (float, 0.0, 0.0, 1000000.0),
    "pump_max_mcap_sol": (float, 0.0, 0.0, 1000000.0),
    "pump_top_n": (int, 10, 1, 50),
    "pump_only_online": (bool, True, 0, 1),
    "pump_online_min": (float, 10.0, 1.0, 1440.0),
    "pump_rank_hours": (float, 24.0, 1.0, 168.0),
    "pump_min_closed": (int, 3, 1, 100),
    "pump_min_winrate": (float, 50.0, 0.0, 100.0),
    "pump_min_hold_s": (float, 20.0, 0.0, 3600.0),
    "pump_max_trades_h": (float, 120.0, 1.0, 10000.0),
    "pump_lb_days": (int, 7, 1, 90),
    "pump_lb_min_trades": (int, 1000, 0, 1000000),
    "pump_real_max_sol": (float, 0.05, 0.001, 100.0),
    "pump_real_max_open": (int, 5, 1, 50),
    "pump_real_daily_loss_sol": (float, 0.5, 0.0, 1000.0),
    "pump_real_slippage_pct": (float, 15.0, 1.0, 50.0),
}
LB_DAYS = (1, 7, 30, 90)

# Opções do monitor COMPARTILHADO (um só para todos): só no .env do servidor
SERVER_KEYS: dict[str, tuple] = {
    "pump_enabled": (bool, True),
    "pump_ws_url": (str, "wss://pumpportal.fun/api/data"),
    "pump_rpc_ws": (str, "wss://api.mainnet-beta.solana.com"),
    "pump_rpc_http": (str, "https://api.mainnet-beta.solana.com"),
    "pump_price_every_s": (float, 3.0),
    "pump_ds_every_s": (float, 10.0),
    "pump_track_tokens": (int, 300),
    "pump_max_tx_min": (float, 10.0),
    "pump_lb_every_s": (float, 600.0),
    "pump_lb_platform": (str, "pumpfun-app"),
    "pump_wallet_check_s": (float, 1800.0),
    "pump_rank_every_s": (float, 600.0),
    "pump_paid_stream": (bool, False),
}


def server_defaults() -> dict:
    """Padrões com as substituições do .env (PUMP_COPY_SOL=0.2 muda o padrão de quem ainda não mexeu)."""
    out = {}
    for k, spec in list(USER_KEYS.items()) + list(SERVER_KEYS.items()):
        typ, dflt = spec[0], spec[1]
        raw = os.environ.get(k.upper())
        if raw is not None and raw.strip() != "":
            try:
                out[k] = _cast(typ, raw.strip())
                continue
            except ValueError:
                pass
        out[k] = dflt
    if os.environ.get("SOLANA_RPC_PUBLIC") and not os.environ.get("PUMP_RPC_HTTP"):
        out["pump_rpc_http"] = os.environ["SOLANA_RPC_PUBLIC"].strip()
    return out


class PumpSettings:
    """Configuração de UM usuário. Atributos com os mesmos nomes do projeto original (cfg.pump_*), então o
    motor de cópia funciona igual."""

    def __init__(self, saved: dict | None = None, defaults: dict | None = None):
        for k, v in (defaults or server_defaults()).items():
            setattr(self, k, v)
        for k, v in (saved or {}).items():
            if k in USER_KEYS:
                try:
                    setattr(self, k, self.validate(k, v))
                except ValueError:
                    pass
        self.pump_real_enabled = False          # segurança: nunca vem do banco

    @staticmethod
    def validate(k: str, v):
        spec = USER_KEYS.get(k)
        if not spec:
            raise ValueError("não pode ser alterado pelo painel")
        typ, _d, lo, hi = spec
        if typ is bool:
            return v if isinstance(v, bool) else str(v).lower() in ("1", "true", "sim", "on", "yes")
        try:
            val = typ(float(v)) if typ is int else typ(v)
        except (TypeError, ValueError, OverflowError):     # "1e1000" virava HTTP 500 (SEC-11, 2026-10-25)
            raise ValueError("valor inválido") from None
        if val != val or not lo <= val <= hi:          # NaN ou fora do limite
            raise ValueError(f"fora do limite {lo}–{hi}")
        if k == "pump_lb_days" and val not in LB_DAYS:
            raise ValueError("use 1, 7, 30 ou 90")
        return val

    def apply(self, changes: dict) -> tuple[dict, dict]:
        applied, errors = {}, {}
        for k, v in (changes or {}).items():
            if k == "pump_real_enabled":
                errors[k] = "use o botão de execução real (pede confirmação)"
                continue
            try:
                val = self.validate(k, v)
            except ValueError as e:
                errors[k] = str(e)
                continue
            setattr(self, k, val)
            applied[k] = val
        return applied, errors

    def user_dict(self) -> dict:
        return {k: getattr(self, k) for k in USER_KEYS}


class ServerConfig:
    def __init__(self):
        self.supabase_url = _env("SUPABASE_URL").rstrip("/")
        self.supabase_anon_key = _env("SUPABASE_ANON_KEY")
        self.supabase_service_key = _env("SUPABASE_SERVICE_ROLE_KEY")
        self.supabase_jwt_secret = _env("SUPABASE_JWT_SECRET")     # opcional (projetos com chave HS256 antiga)
        self.encryption_key = _env("APP_ENCRYPTION_KEY")
        self.public_base_url = _env("PUBLIC_BASE_URL", "http://localhost:8080").rstrip("/")
        self.solana_rpc_public = _env("SOLANA_RPC_PUBLIC", "https://api.mainnet-beta.solana.com")
        self.port = int(_env("PORT", "8080"))
        self.defaults = server_defaults()
