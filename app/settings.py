"""Configurações.

- `ServerConfig`: o que vem do `.env` da VPS (Supabase, chave mestra, RPC público e as opções PUMP_* que mexem
  no monitor COMPARTILHADO).
- `PumpSettings`: as opções PUMP_* de UM usuário (mesmos padrões do projeto original). Ficam no banco
  (`user_settings.settings`) e só o próprio usuário muda pelo painel.

A execução REAL (`pump_real_enabled`) nunca vem do `apply` (só pelo botão com confirmação) e começa DESLIGADA. Desde a
0.31.28 o "ligado" fica gravado à parte (`_real_on` em `user_settings.settings`) e o hub religa no reinício se a trava
geral, a carteira e a conta permitirem.
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
    # 0.30.0: Explorar automático e proteções próprias das operações automáticas.
    "pump_ex_auto_on": (bool, True, 0, 1),             # 0.31.11: LIGADO por padrão a pedido do dono (só fictício)
    "pump_ex_auto_need_smart": (bool, False, 0, 1),
    "pump_ar_learn": (bool, True, 0, 1),
    # 0.31.99 (pedido do dono, itens 2, 3 e 4): tudo DESLIGADO; cada um liga quando os números mostrarem que vale
    "pump_ex_possivel_on": (bool, False, 0, 1),        # Explorar entra também no veredito "possível"…
    "pump_ex_possivel_pct": (float, 50.0, 10.0, 100.0),  # …com esta % do valor normal
    "pump_ar_learn_wilson": (bool, False, 0, 1),       # bloqueio do aprender com os erros pela regra estatística (Wilson)
    "pump_calls_auto_on": (bool, False, 0, 1),         # compra automática das Calls quentes, só na fictícia
    "pump_calls_auto_min": (int, 65, 40, 100),         # veredito mínimo da call (%)
    "pump_calls_auto_max_h": (int, 3, 1, 20),          # no máximo N compras de calls por hora
    "pump_st_auto_on": (bool, True, 0, 1),
    # 0.32.11 (pedido do dono, 28/10): copiar sozinha as carteiras que o estudo automático aprovou — SÓ na fictícia
    "pump_st_auto_copy": (bool, False, 0, 1),
    # 0.32.18 (pedido do dono, 28/10): trades das carteiras COPIADAS pela PumpPortal (subscribeAccountTrade), cobrado da carteira
    # ligada à chave PumpPortal do sistema (0,01 SOL a cada 10 mil trades, pumpportal.fun/fees). Começa DESLIGADO.
    "pump_pp_copy": (bool, False, 0, 1),
    "pump_st_real": (bool, False, 0, 1),
    # 0.32.21 (pedido do dono): barrados do Explorar que subiram entram sozinhos SÓ na fictícia (regras do botão Comprar)
    "pump_bar_auto_on": (bool, False, 0, 1),
    "pump_bar_min_gain": (float, 50.0, 5.0, 10000.0),     # subiu pelo menos X% desde que foi visto
    "pump_bar_min_vol_usd": (float, 20000.0, 0.0, 1e10),  # volume 24 h mínimo (US$)
    "pump_bar_max_h": (int, 4, 1, 50),                    # no máximo N entradas por hora
    "pump_bar_sol": (float, 0.05, 0.001, 10.0),           # SOL fictícios por entrada                 # 0.32.20: carteira em estudo também copia na REAL (padrão: só fictícia)
    # 0.32.19 (pedido do dono: Configuração do Trader). Tudo desligado; só o botão "Restaurar Padrões Pump.fun" liga.
    "pump_tp2_pct": (float, 0.0, 0.0, 10000.0),          # 2º alvo: ao chegar em +X% (0 = desligado)…
    "pump_tp2_frac_pct": (float, 25.0, 1.0, 99.0),       # …vende Y% da posição ORIGINAL; o resto (moonbag) segue no stop móvel
    "pump_timestop_on": (bool, False, 0, 1),             # stop por tempo: depois de X s…
    "pump_timestop_s": (float, 180.0, 10.0, 86400.0),
    "pump_timestop_gain_pct": (float, 0.0, -100.0, 1000.0),  # …se o melhor momento não passou de +Y% líquido, vende tudo
    "pump_entry_curve_on": (bool, False, 0, 1),          # só copia com a curva da pump.fun entre min% e max%
    "pump_entry_curve_min": (float, 0.0, 0.0, 100.0),
    "pump_entry_curve_max": (float, 85.0, 0.0, 100.0),
    "pump_real_jito_tip_sol": (float, 0.001, 0.0, 0.1),  # gorjeta Jito (guardada; o envio por Jito ainda não existe)
    "pump_tune_on": (bool, True, 0, 1),                # 0.31.14: ajuste automático (saída pelos fantasmas + pausar trader ruim)             # 0.31.13: estudo automático de carteiras (só estudo, não copia)
    "pump_st_auto_max": (int, 15, 1, 30),                # 0.31.12: aprender com os erros (bloqueia faixas que perdem; só aperta)     # exigir trader bom também no Explorar (na Base continua exigido)
    "pump_ex_auto_min_pressure": (float, 60.0, 0.0, 100.0),
    "pump_ex_auto_min_holders": (int, 100, 0, 1000000),
    "pump_ex_auto_max_risk": (int, 6, 1, 10),
    "pump_ex_auto_curve_min": (float, 60.0, 0.0, 100.0),
    "pump_ex_auto_curve_max": (float, 95.0, 0.0, 100.0),
    "pump_ex_auto_max_chg5": (float, 150.0, 0.0, 10000.0),
    "pump_ar_sol": (float, 0.05, 0.001, 100.0),
    "pump_ar_max_open": (int, 3, 1, 50),
    "pump_ar_max_h": (int, 4, 1, 100),
    "pump_ar_daily_loss": (float, 0.25, 0.0, 1000.0),
    "pump_ar_streak_n": (int, 3, 0, 50),
    "pump_ar_streak_h": (float, 1.0, 0.1, 72.0),
    "pump_ar_stop_pct": (float, 25.0, 1.0, 100.0),
    "pump_ar_tp1_pct": (float, 40.0, 0.0, 10000.0),
    "pump_ar_tp1_frac": (float, 50.0, 1.0, 99.0),
    "pump_ar_trail_start": (float, 40.0, 1.0, 10000.0),
    "pump_ar_trail_dist": (float, 15.0, 1.0, 1000.0),
    "pump_ar_tp_pct": (float, 150.0, 0.0, 10000.0),
    "pump_ar_max_hold_min": (float, 30.0, 1.0, 1440.0),
    "pump_ar_smart": (bool, True, 0, 1),
    "pump_ar_press_min": (float, 1.0, 0.0, 60.0),      # 0.31.21: saída por pressão depois de X min (0 = não usa)
    "pump_ar_exit_grad": (bool, True, 0, 1),           # 0.31.21: sai quando o token gradua
    "pump_radar_enabled": (bool, False, 0, 1),
    "pump_radar_min_wallets": (int, 2, 2, 30),
    "pump_radar_window_min": (int, 5, 1, 30),
    # 0.19.0: saídas inteligentes, nota da entrada (0–100) e gestão de banca — todas começam DESLIGADAS
    "pump_exit_dev_sell": (bool, False, 0, 1),          # vende tudo quando o criador do token vende
    "pump_exit_migrate": (bool, False, 0, 1),           # vende quando o token gradua (comprado ainda na curva)
    "pump_exit_pressure_on": (bool, False, 0, 1),
    "pump_exit_pressure_pct": (float, 35.0, 0.0, 100.0),  # vende se as compras caírem abaixo de X% das negociações
    "pump_exit_kol_on": (bool, False, 0, 1),
    "pump_exit_kol_n": (int, 2, 1, 30),
    # 0.31.10: saída por estagnação (visto em 2026-10-26: as perdas do dia vieram de "tempo máximo (6 h)", posições
    # paradas de -4% a -17% por horas). Começa DESLIGADA; as Estratégias fantasma medem antes de ligar.
    "pump_exit_stale_on": (bool, False, 0, 1),
    "pump_exit_stale_min": (float, 45.0, 5.0, 1440.0),  # depois de X min na posição…
    "pump_exit_stale_band": (float, 5.0, 0.5, 50.0),    # …se o resultado estiver entre -Y% e +Y%, sai                 # vende quando N outras carteiras seguidas/estudadas vendem o token
    "pump_score_min_on": (bool, False, 0, 1),
    "pump_score_min": (float, 50.0, 0.0, 100.0),        # só copia com nota da entrada >= X
    "pump_size_by_score": (bool, False, 0, 1),          # valor da cópia fictícia de x0,5 (nota 0) a x1,5 (nota 100)
    "pump_streak_on": (bool, False, 0, 1),
    "pump_streak_n": (int, 4, 2, 50),                   # N perdas seguidas -> para de abrir cópias por X h
    "pump_streak_h": (float, 2.0, 0.1, 72.0),
    "pump_cold_on": (bool, False, 0, 1),
    "pump_cold_wr": (float, 30.0, 0.0, 100.0),          # acerto das últimas 10 cópias em 2 h abaixo de X% -> metade do valor
    # 0.20.0: lista negra compartilhada e avisos no Telegram (começam desligados)
    "pump_base_hide_trash": (bool, False, 0, 1),
    # 0.26.0: botão Comprar já configurado (pedido do dono: não ter que digitar valores na hora de comprar)
    "pump_manual_sol": (float, 0.1, 0.001, 100.0),      # quanto o botão compra na carteira fictícia
    "pump_manual_stop_pct": (float, 30.0, 1.0, 100.0),  # stop de perda das compras do botão
    "pump_manual_tp_pct": (float, 100.0, 0.0, 10000.0), # alvo de ganho (vende tudo); 0 = sem alvo
    "pump_manual_trail_on": (bool, True, 0, 1),
    "pump_manual_trail_start": (float, 30.0, 1.0, 10000.0),  # stop móvel liga em +X%
    "pump_manual_trail_dist": (float, 15.0, 1.0, 1000.0),    # e sai se cair Y pontos do pico
    # 0.27.0: compra automática da Base da pump.fun (roda no servidor, mesmo com o painel fechado) — começa DESLIGADA
    # 0.31.0: segurança das entradas automáticas (Base e Explorar), pedidos do dono em áudio (2026-10-26):
    # "esperar uns 20 minutos", "muita carteira nova = robô, não entrar", "só entrar quando um bom trader entrou"
    "pump_ar_min_age_min": (float, 20.0, 0.0, 1440.0),  # idade mínima do token para entrar sozinho
    "pump_ar_fresh_on": (bool, True, 0, 1),             # barra token com muita carteira nova entre os maiores detentores
    "pump_ar_fresh_max_pct": (float, 30.0, 1.0, 100.0), # % máx. de carteiras novas entre os 20 maiores detentores
    "pump_ar_smart_on": (bool, True, 0, 1),             # só entra se um trader bom (seguido/ranking/estudo) já está no token
    "pump_ar_smart_min": (int, 1, 1, 30),
    # 0.31.2: Maiores traders — compra automática pelos sinais (começa DESLIGADA; usa as proteções pump_ar_*)
    # 0.31.4: copiar sozinho, compra e venda, os maiores traders com 80%+ de acerto (pedido do dono: "fazer o que ele
    # faz"). Só no simulado; real continua dependendo da execução real liberada. Começa LIGADO a pedido do dono.
    "pump_el_copy80": (bool, True, 0, 1),
    "pump_el_auto_on": (bool, False, 0, 1),
    "pump_el_auto_min_wallets": (int, 2, 1, 15),        # só compra sinal com N+ maiores traders no token
    "pump_el_auto_big": (bool, False, 0, 1),            # também compra o sinal de "compra grande" de um só
    "pump_el_follow_sell": (bool, True, 0, 1),          # vende quando um dos traders do sinal vende
    "pump_auto_on": (bool, False, 0, 1),
    "pump_auto_boost": (bool, True, 0, 1),              # entra sozinho quando o token está com Boost ON
    "pump_auto_chance": (bool, False, 0, 1),            # entra sozinho quando a previsão diz "chance alta"
    "pump_auto_max_age": (float, 45.0, 1.0, 60.0),      # só tokens com até X min de vida (0.31.0: 15 → 45, por causa da idade mínima)
    "pump_auto_max_h": (int, 5, 1, 100),                # no máx. N compras automáticas por hora
    "pump_auto_real": (bool, False, 0, 1),              # também na real (se a Execução real estiver ligada)
    "pump_manual_boost_on": (bool, True, 0, 1),         # token com boost pago: vende em +X% (pedido do dono, 2026-10-26)
    "pump_manual_boost_tp": (float, 80.0, 1.0, 10000.0),        # 0.25.0: Base da pump.fun esconde o que a previsão marca como lixo
    "pump_blacklist_on": (bool, False, 0, 1),           # não copia token de criador (ou trader) da lista negra
    "pump_tg_on": (bool, False, 0, 1),                  # avisos no Telegram (token do bot e chat em Chaves pessoais)
    "pump_tg_all": (bool, False, 0, 1),                 # OFF = só os importantes; ON = toda notificação
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
    # 0.31.82 (opção A escolhida pelo dono): usar a tabela oficial da PumpSwap por valor de mercado no lugar do valor fixo
    # acima. Começa DESLIGADA para não mudar a configuração de ninguém; cada um liga se quiser.
    "pump_swap_fee_official": (bool, False, 0, 1),
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
    # 0.31.37 (sugestão do Bruxo, 2026-10-27): com a Execução real ligada, a carteira real copia 100% dos trades da
    # fictícia (cópias, Explorar, Base, Maiores traders, botão Comprar), mas o valor e os limites vêm só das regras reais
    "pump_real_mirror": (bool, True, 0, 1),
    # 0.32.4 (pedido do dono, 28/10): "Copiar igual" — carteiras do leaderboard da pump.fun coladas à mão; copia toda
    # compra e venda delas sem filtros e sem espera. Começa DESLIGADO; a real só entra com pump_eq_real (pelo espelho)
    "pump_eq_on": (bool, False, 0, 1),
    "pump_eq_sol": (float, 0.05, 0.001, 10.0),
    "pump_eq_max_open": (int, 20, 1, 100),
    "pump_eq_max_hold_h": (float, 24.0, 0.5, 168.0),
    "pump_eq_stop_pct": (float, 0.0, 0.0, 100.0),
    "pump_eq_real": (bool, False, 0, 1),
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
        if k == "pump_radar_enabled":
            if not isinstance(v, (bool, int, str)) or str(v).lower() not in (
                    "true", "false", "1", "0", "sim", "não", "nao", "on", "off", "yes", "no"):
                raise ValueError("use ON ou OFF")
        if k in ("pump_radar_min_wallets", "pump_radar_window_min"):
            try:
                if isinstance(v, bool) or float(v) != int(float(v)):
                    raise ValueError
            except (TypeError, ValueError, OverflowError):
                raise ValueError("use um número inteiro") from None
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
