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
    # 0.32.61 (pedido do dono: "o que não tiver real tem que ter o botão"): cada compra automática só vai para a carteira REAL
    # com o botão REAL dela; antes Maiores traders e Base iam para a real pelo espelho sem botão próprio. Começam DESLIGADOS.
    "pump_calls_real": (bool, False, 0, 1),
    "pump_el_real": (bool, False, 0, 1),
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
    "pump_bar_sol": (float, 0.05, 0.001, 10.0),           # SOL fictícios por entrada
    "pump_bar_max_open": (int, 20, 1, 100),               # 0.32.31: posições abertas dos barrados (vagas próprias)
    "pump_bar_real": (bool, False, 0, 1),                 # 0.32.33: barrados também na REAL (pelo espelho); padrão só fictícia
    # 0.32.41 — Aba do Bruxo (áudios e prompt do Bruxo, 29/10): entrar junto com os top traders em moedas NOVAS. Começa
    # DESLIGADA; a REAL fica sempre desligada até a pessoa ligar ("trabalhamos ativo só fictícia" — dono).
    "pump_bx_on": (bool, False, 0, 1),
    "pump_bx_real": (bool, False, 0, 1),
    "pump_bx_sol": (float, 0.05, 0.001, 10.0),            # SOL fictícios por entrada
    "pump_bx_max_age_min": (float, 5.0, 0.5, 60.0),       # token com menos de X min de criação
    "pump_bx_flow_mult": (float, 1.0, 0.0, 20.0),         # ritmo de compra >= X vezes a média inicial dos tokens novos (0 = não usa)
    "pump_bx_top10_max": (float, 35.0, 5.0, 100.0),       # 10 maiores detentores (sem a curva) com no máximo X%
    "pump_bx_min_mcap": (float, 32.0, 0.0, 500.0),        # liquidez: market cap da curva de pelo menos X SOL
    "pump_bx_dev_max": (float, 10.0, 0.0, 100.0),         # criador com no máximo X% do token
    "pump_bx_min_trader_sol": (float, 0.2, 0.0, 100.0),   # compra do top trader de pelo menos X SOL (tira robô de centavos)
    "pump_bx_tp1_pct": (float, 100.0, 5.0, 10000.0),      # vende parte em +X%...
    "pump_bx_tp1_frac": (float, 50.0, 5.0, 100.0),        # ...esta % da posição
    "pump_bx_trail_dist": (float, 20.0, 2.0, 90.0),       # stop móvel no resto: sai se cair X pontos do pico
    "pump_bx_stop_pct": (float, 30.0, 0.0, 95.0),         # stop de perda (0 = sem stop)
    "pump_bx_max_hold_min": (float, 25.0, 1.0, 1440.0),   # tempo máximo (o Bruxo viu que dura uns 25 min)
    "pump_bx_curve_max": (float, 100.0, 1.0, 100.0),      # 0.32.59: só entra com a curva até X% (100 = não usa)
    "pump_bx_grad_exit": (float, 0.0, 0.0, 100.0),        # 0.32.59: vende tudo com a curva em X% (antes de graduar; 0 = não usa)
    "pump_jt_wallet": (bool, True, 0, 1),                 # 0.32.93: cada entrada do Jev Trade vai também para a carteira FICTÍCIA
    "pump_jt_wallet_max": (int, 10, 1, 50),
    "pump_jt_real": (bool, False, 0, 1),
    # 0.32.373 (pedido do dono): BOOST da migração (app/boostmig.py; guia do hermes-jev-trader 2026-11-18.15). Tudo por usuário.
    "pump_bm_on": (bool, False, 0, 1),                    # entra sozinho na FICTÍCIA
    "pump_bm_real": (bool, False, 0, 1),                  # também na REAL (precisa da Execução real ligada)
    "pump_bm_sol": (float, 0.05, 0.001, 5.0),
    "pump_bm_max_open": (int, 3, 1, 20),
    "pump_bm_enter_max_pct": (float, 40.0, 1.0, 60.0),
    "pump_bm_exit_pct": (float, 80.0, 10.0, 100.0),
    "pump_bm_watch_s": (float, 60.0, 0.0, 180.0),
    "pump_bm_min_trend_pct": (float, -3.0, -50.0, 50.0),
    "pump_bm_max_dd_pct": (float, 15.0, 0.0, 90.0),
    "pump_bm_min_buy_ratio": (float, 1.2, 0.0, 10.0),
    "pump_bm_min_buys": (int, 100, 0, 5000),
    "pump_bm_block_repeat": (bool, True, 0, 1),
    "pump_bm_block_scam": (bool, True, 0, 1),
    "pump_bm_vip_skip_repeat": (bool, True, 0, 1),
    "pump_bm_require_safety": (bool, True, 0, 1),
    "pump_bm_max_top10": (float, 35.0, 0.0, 100.0),
    "pump_bm_no_stop": (bool, False, 0, 1),               # sem stop de perda até a saída do BOOST
    "pump_bm_stop_pct": (float, 40.0, 1.0, 95.0),
    "pump_bm_trail_start": (float, 10.0, 1.0, 1000.0),
    "pump_bm_trail_dist": (float, 5.0, 1.0, 90.0),
    "pump_bm_partial_on": (bool, True, 0, 1),
    "pump_bm_partial_at": (float, 15.0, 1.0, 1000.0),
    "pump_bm_partial_frac": (float, 50.0, 5.0, 95.0),
    # 0.32.375: as opções que faltavam em relação ao original
    "pump_bm_scam_dump_pct": (float, 70.0, 10.0, 99.0),   # DEV scam: caiu X% do topo…
    "pump_bm_scam_dump_min": (float, 10.0, 1.0, 120.0),   # …até X min depois da migração
    "pump_bm_twin_min": (float, 10.0, 1.0, 120.0),        # cópias: 2+ tokens com o mesmo nome migrando em até X min
    "pump_bm_scam_keep_d": (float, 7.0, 1.0, 90.0),       # lembrar o DEV scam por X dias
    "pump_bm_vip_keep_d": (float, 30.0, 1.0, 365.0),      # lembrar o resultado do DEV (VIP) por X dias
    "pump_bm_fast": (bool, True, 0, 1),
    "pump_q_boost": (bool, True, 0, 1),                      # 0.32.379: consultas do servidor (Configurações → Consultas)
    "pump_q_top": (bool, True, 0, 1),                      # 0.32.379: consultas do servidor (Configurações → Consultas)
    "pump_q_explorar": (bool, True, 0, 1),                      # 0.32.379: consultas do servidor (Configurações → Consultas)
    "pump_q_base": (bool, True, 0, 1),                      # 0.32.379: consultas do servidor (Configurações → Consultas)
    "pump_q_estudo": (bool, True, 0, 1),                      # 0.32.379: consultas do servidor (Configurações → Consultas)
    "pump_q_bruxo": (bool, True, 0, 1),                      # 0.32.379: consultas do servidor (Configurações → Consultas)
    "pump_q_jt": (bool, True, 0, 1),                      # 0.32.379: consultas do servidor (Configurações → Consultas)
    "pump_q_jev": (bool, True, 0, 1),                      # 0.32.379: consultas do servidor (Configurações → Consultas)
    "pump_q_calls": (bool, True, 0, 1),                      # 0.32.379: consultas do servidor (Configurações → Consultas)
    "pump_q_raiox": (bool, True, 0, 1),                      # 0.32.379: consultas do servidor (Configurações → Consultas)
    "pump_q_elite": (bool, True, 0, 1),                      # 0.32.379: consultas do servidor (Configurações → Consultas)
    "pump_bm_ext_on": (bool, True, 0, 1),                 # 0.32.380: no fim do BOOST fica se as compras crescem
    "pump_bm_ext_grow_pct": (float, 10.0, 0.0, 500.0),    # …crescimento mínimo das compras no último minuto (%)
    "pump_bm_ext_stop_pct": (float, 25.0, 1.0, 95.0),     # …perda máxima enquanto fica depois do BOOST (%)
    "pump_bm_ext_max_min": (float, 20.0, 1.0, 240.0),     # …tempo extra máximo depois do BOOST (min)
    "pump_bm_hold_profit_on": (bool, False, 0, 1),        # 0.32.380: segura até ficar +X% depois do BOOST
    "pump_bm_hold_profit_pct": (float, 10.0, 1.0, 1000.0),
    "pump_bm_sybil_on": (bool, True, 0, 1),               # 0.32.382: carteiras ligadas ao DEV (Alchemy) — análise do servidor
    "pump_bm_sybil_alert": (bool, True, 0, 1),            # …avisar (sino/Telegram) quando o nível for alto ou médio
    "pump_bm_sybil_alert_pct": (float, 20.0, 5.0, 90.0),  # …alerta alto: DEV + carteiras ligadas com X% ou mais do total
    "pump_bm_sybil_bundle_pct": (float, 25.0, 5.0, 90.0), # …alerta alto: bundle (comprou no bloco do lançamento) com X%+
    "pump_bm_sybil_top": (float, 15.0, 5.0, 20.0),        # …quantos maiores detentores analisar
    "pump_bm_sybil_max_h": (float, 30.0, 1.0, 200.0),     # …no máximo N tokens por hora (gasto da Alchemy)
    "pump_bm_sybil_block": (bool, False, 0, 1),           # …TRAVA: barrar a compra com alerta alto (desativada nesta versão)
    "pump_bm_hist_min": (float, 20.0, 5.0, 30.0),         # 0.32.378: análise de cada token X min depois da migração (histórico)                   # posição do BOOST no laço rápido de preço (~1 s)
    # 0.32.102 (dono, 31/10): filtros do Jev Trade editáveis na tela; padrão = a regra que estava valendo
    "pump_jt_min_holders": (int, 40, 5, 5000),            # detentores mínimos na 1ª conferência
    "pump_jt_age_min": (float, 5.0, 1.0, 60.0),           # confere o token a partir de X min de vida…
    "pump_jt_age_max": (float, 8.0, 1.0, 120.0),          # …até Y min
    "pump_jt_janela_min": (float, 2.0, 1.0, 10.0),        # janela da regra (detentores subindo em cada leitura)
    "pump_jt_cresc_pct": (float, 0.0, 0.0, 500.0),        # alta mínima de detentores na janela (0 = qualquer alta)
    "pump_jt_prazo_min": (float, 7.0, 2.0, 30.0),         # prazo na lista (fechamento)
    "pump_jt_stop_pct": (float, 25.0, 1.0, 90.0),         # stop de perda (quando o Jev não escolhe outro)
    "pump_jt_empate_pct": (float, 50.0, 1.0, 1000.0),     # depois de +X% o stop vai para 0%
    "pump_jt_parcial_pct": (float, 100.0, 1.0, 5000.0),   # vende parte em +X%
    "pump_jt_parcial_frac": (float, 50.0, 5.0, 100.0),    # quanto vende (%)
    "pump_jt_trail_apos": (float, 30.0, 1.0, 1000.0),     # stop móvel liga em +X%
    "pump_jt_trail_pct": (float, 25.0, 1.0, 90.0),        # sai se cair X% do pico
    "pump_jt_saida_det_pct": (float, 15.0, 1.0, 90.0),
    "pump_jt_parado_min": (float, 3.0, 0.0, 30.0),        # 0.32.111: mercado parado X min com posição aberta = sai (0 = desligado)
    "pump_jt_parado_pct": (float, 5.0, 0.5, 50.0),        # "parado" = o preço variou menos de X% na janela    # sai se os detentores caírem X% do maior número desde a entrada                  # 0.32.97: entradas do Jev Trade também na REAL (começa desligado; o dono liga)
    "pump_jt_on": (bool, True, 0, 1),                     # 0.32.87: Jev Trade: o Jev decide entrada e saída em simulação
    "pump_jev_on": (bool, True, 0, 1),                    # 0.32.83: Jev (TypeSafe AI) opina em cada sinal da Aba do Bruxo (só sombra)
    "pump_lanc_on": (bool, False, 0, 1),                  # 0.32.59: estuda o lançamento sem trader (só mede, nunca compra)
    "pump_bx_follow_sell": (bool, True, 0, 1),            # sai quando o top trader do sinal vende
    "pump_bx_max_open": (int, 5, 1, 50),
    "pump_lanc_max_open": (int, 30, 1, 100),              # 0.32.78: vagas próprias das compras do Lançamento sem trader                  # posições abertas da aba (vagas próprias)
    "pump_bx_max_h": (int, 6, 1, 60),                     # entradas por hora
    # 0.32.32 (pedido do dono: "nas Proteções das automáticas tem que ter a opção do real"): entradas automáticas do Explorar
    # também na REAL (padrão ON = como já era pelo espelho) e o valor delas na real (0 = "SOL por compra" da Execução real)
    "pump_ex_real_on": (bool, True, 0, 1),
    "pump_ar_real_sol": (float, 0.0, 0.0, 100.0),                 # 0.32.20: carteira em estudo também copia na REAL (padrão: só fictícia)
    # 0.32.19 (pedido do dono: Configuração do Trader). Tudo desligado; só o botão "Restaurar Padrões Pump.fun" liga.
    "pump_tp2_pct": (float, 0.0, 0.0, 10000.0),          # 2º alvo: ao chegar em +X% (0 = desligado)…
    "pump_tp2_frac_pct": (float, 25.0, 1.0, 99.0),       # …vende Y% da posição ORIGINAL; o resto (moonbag) segue no stop móvel
    "pump_timestop_on": (bool, False, 0, 1),             # stop por tempo: depois de X s…
    "pump_timestop_s": (float, 180.0, 10.0, 86400.0),
    "pump_timestop_gain_pct": (float, 0.0, -100.0, 1000.0),  # …se o melhor momento não passou de +Y% líquido, vende tudo
    # 0.32.50 (pedido do dono, 29/10: perdas de −54% a −101% com stop de −30% = moeda despejada de uma vez): filtro contra despejo
    # nas cópias, igual ao da Aba do Bruxo. Começa DESLIGADO.
    "pump_dump_on": (bool, False, 0, 1),
    # 0.32.53 (pedido do dono, BabyNuts −92% com stop de −30%): trava de segurança nas entradas dos barrados, do botão Comprar
    # e da Aba do Bruxo — token graduado só com preço da PumpSwap/DEX lido há até 30 s e liquidez mínima, e o filtro contra
    # despejo sempre. Começa DESLIGADA (ligada só na conta do dono por settings_overrides). O Explorar não passa por ela.
    "pump_guard_on": (bool, False, 0, 1),
    # 0.32.57 (análise das 26 carteiras em estudo, "sim, aplica" do dono): nunca copiar lançador de token, robô de alta frequência
    # nem quem segura menos que o atraso da cópia. Começa DESLIGADO (ligado só na conta do dono por settings_overrides).
    # 0.32.324 (pedido do dono, 11/11/2026, pacote das pesquisas conferidas): ligado por padrão. Das 26 carteiras analisadas em
    # 29/10, 11 eram lançadoras e 7 de alta frequência: o lucro delas não passa para quem copia.
    "pump_nc_on": (bool, True, 0, 1),
    "pump_nc_launch_min": (int, 20, 1, 100000),          # criou N+ tokens (vistos pela Base da pump.fun em 14 dias)
    "pump_nc_hft_day": (int, 150, 10, 100000),           # N+ trades em 24 h
    "pump_nc_hold_min_s": (float, 30.0, 0.0, 86400.0),   # segura menos que X s na mediana (8+ tokens fechados em 7 dias)
    "pump_guard_min_liq_usd": (float, 15000.0, 0.0, 1e9),
    "pump_dump_top10_max": (float, 35.0, 5.0, 100.0),    # 10 maiores detentores (sem a curva) com no máximo X%
    "pump_dump_dev_max": (float, 10.0, 0.0, 100.0),      # criador com no máximo X% do token
    "pump_dump_fresh_max": (float, 30.0, 0.0, 100.0),    # carteiras novas entre os maiores detentores (quando já checado)
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
    "pump_ar_stop_pct": (float, 25.0, 0.0, 100.0),       # 0.32.35 (pedido do dono): 0 = sem stop de perda nas automáticas
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
    # 0.32.324: ligado por padrão. Aporius, 6.817 graduações (conferido em 28/10): mediana -12,1% em 5 min e -59,5% em 10 min.
    "pump_exit_migrate": (bool, True, 0, 1),            # vende quando o token gradua (comprado ainda na curva)
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
    # 0.32.36 (sugestão do Bruxo, 28/10 22:11): no Explorar, só token novo. 0 = sem limite (padrão: ninguém muda sozinho)
    "pump_ex_max_age_min": (float, 0.0, 0.0, 1440.0),
    # idade mínima SÓ do Explorar; -1 = usa a das automáticas (pump_ar_min_age_min, 20 min) como antes
    "pump_ex_min_age_min": (float, -1.0, -1.0, 1440.0),
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
    "pump_sim_on": (bool, True, 0, 1),                  # 0.32.198: chave geral da carteira FICTÍCIA (desligada = não abre compra nova)
    "pump_top_on": (bool, True, 0, 1),                  # 0.32.127: compras da aba Top traders (ligado = como sempre foi)
    "pump_st_copy_on": (bool, True, 0, 1),              # 0.32.127: compras das Carteiras em estudo copiadas (ligado = como sempre foi)
    "pump_st_lucro_on": (bool, False, 0, 1),            # 0.32.211: copia as carteiras do estudo que deram lucro
    "pump_st_lucro_real": (bool, False, 0, 1),          # 0.32.213: as que deram lucro também na REAL (começa desligada)
    "pump_sim_balance_sol": (float, 5.0, 0.01, 100000.0),
    "pump_copy_sol": (float, 0.1, 0.001, 100.0),
    "pump_copy_delay_s": (float, 0.0, 0.0, 3600.0),
    "pump_copy_other": (bool, True, 0, 1),
    "pump_copy_other_real": (bool, False, 0, 1),
    "pump_other_min_liq_usd": (float, 20000.0, 0.0, 1e9),
    "pump_other_fee_pct": (float, 0.30, 0.0, 5.0),
    "pump_other_slip_pct": (float, 1.0, 0.0, 50.0),
    "pump_max_open": (int, 10, 1, 50),
    # 0.32.335 (dono, 13/11: "você decide, só fictícia"): 3% → 1,5% por lado. Com 3% a ida e volta da fictícia custava ~9,5%; a REAL
    # mediu 4,5% (estudo de 13/11). Com 1,5% fica ~6,5%, ainda mais caro que a REAL. A REAL não muda: a conta dela usa no mínimo 3%.
    "pump_extra_slip_pct": (float, 1.5, 0.0, 50.0),
    "pump_fee_pct": (float, 1.25, 0.0, 10.0),
    "pump_swap_fee_pct": (float, 0.30, 0.0, 5.0),
    # 0.31.82 (opção A escolhida pelo dono): usar a tabela oficial da PumpSwap por valor de mercado no lugar do valor fixo
    # acima. Começa DESLIGADA para não mudar a configuração de ninguém; cada um liga se quiser.
    "pump_swap_fee_official": (bool, True, 0, 1),      # 0.32.324: ligado por padrão (só muda a conta da FICTÍCIA; 0,30% subestimava)
    "pump_portal_fee_pct": (float, 0.5, 0.0, 5.0),
    # 0.32.324: 0,0005 → 0,0001. Lido em 28/10: gorjeta Jito P95 0,00004 e P99 0,00023 SOL; o exemplo da PumpPortal usa 0,00005.
    # Com 0,05 SOL por compra, 0,0005 por transação custava 2% na ida e volta.
    "pump_priority_sol": (float, 0.0001, 0.0, 0.1),
    # 0.32.323 (pedido do dono, 11/11/2026: "por que estamos sempre no negativo" → "Sim, aplica"): a revisão achou a cópia
    # segurando a perda (trader saiu no prejuízo = segura até o stop de 40% ou as 6 h) e cortando o ganho (stop móvel a 10
    # pontos do pico). Padrões novos: stop 30%, vende junto com o trader mesmo no prejuízo, stop móvel liga em +25% e sai 20
    # pontos abaixo, e "só copia na REAL quem dá resultado" ligado. Conta antiga: ver saidas_upgrade (uma vez).
    "pump_stop_pct": (float, 30.0, 1.0, 100.0),
    "pump_hold_until_profit": (bool, False, 0, 1),
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
    # 0.32.59 (pedido do dono: "pegar do início e sair antes de graduar"): a saída antes da graduação vale só para as CÓPIAS de
    # traders (Explorar, barrados, botão Comprar e automáticas seguem as regras delas). Desligado = como antes (vale para todas).
    "pump_cx_copies_only": (bool, False, 0, 1),
    "pump_min_curve_speed": (float, 5.0, 0.0, 1000.0), # só copia se a curva enche ao menos X% por minuto
    "pump_skip_graduated": (bool, False, 0, 1),        # não copia compra de token que já graduou (PumpSwap)
    "pump_size_by_trader": (bool, False, 0, 1),
    "pump_min_buy_pressure_pct": (float, 55.0, 0.0, 100.0),  # 0.13.0: só copia se as compras forem ≥ X% das negociações        # valor da cópia conforme o seu resultado com o trader  # não copia se o preço subiu mais que isso desde a compra do trader
    "pump_risk_check": (bool, True, 0, 1),          # nota de risco do token (Solana Tracker) antes de copiar
    "pump_max_risk_score": (int, 7, 1, 10),         # 1 = só tokens de risco baixo; 10 = só bloqueia "perigo"
    "pump_min_wallet_usd": (float, 5000.0, 0.0, 1e10),
    "pump_trail_enabled": (bool, True, 0, 1),
    "pump_trail_start_pct": (float, 25.0, 1.0, 10000.0),
    "pump_trail_dist_pct": (float, 20.0, 1.0, 1000.0),
    "pump_trail_min_lock_pct": (float, 2.0, 0.0, 1000.0),
    "pump_trail_fast_s": (float, 1.0, 0.0, 30.0),
    # 0.32.61 (perdas de −65% e −100% com stop de −30%/−40%): o preço de TODA posição aberta com stop de perda é lido no
    # mesmo laço rápido do stop móvel (~1 s), não só a cada 3–10 s. Explorar fica fora (lógica intocável sem OK do dono).
    "pump_stop_fast_on": (bool, True, 0, 1),
    "pump_autopause_stops": (int, 2, 0, 100),
    "pump_autopause_hours": (float, 24.0, 0.0, 720.0),
    "pump_tp_pct": (float, 0.0, 0.0, 10000.0),
    # 0.32.332 (pedido do dono, 13/11/2026: "estratégia autônoma de stop de ganho, ganhou 10% saiu fora"): o robô escolhe o alvo de
    # cada aba pelo histórico (app/stopganho.py) e vende tudo quando o líquido chega lá. Vale na FICTÍCIA; a REAL que é par da
    # fictícia sai junto dela pelo espelho. A REAL sem par e o Explorar (lógica que não muda sem OK do dono) têm chave própria, desligada.
    "pump_sg_on": (bool, True, 0, 1),
    "pump_sg_fixo_pct": (float, 0.0, 0.0, 500.0),      # 0 = o robô escolhe; acima de 0 = nível fixo escolhido por você
    "pump_sg_explorar": (bool, False, 0, 1),
    "pump_sg_real": (bool, False, 0, 1),
    # 0.32.335: não copiar entrada que cai numa faixa que o cérebro do stop de ganho marcou como ruim (1 em cada 5 passa para medir)
    "pump_sg_entrada_on": (bool, True, 0, 1),
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
    "pump_real_min_age_min": (float, 10.0, 0.0, 10080.0),   # 0.32.254: REAL só compra token com pelo menos N min de vida
    # 0.32.330 (estudo do dono, 12/11: a REAL na curva da pump.fun deu −30% por trade em 12 dias): REAL não compra token ainda na curva
    "pump_real_no_curve": (bool, False, 0, 1),
    # 0.32.331 (estudo de 13/11): confere o preço lido do trade com o de mercado antes de copiar (ganhos falsos de token de DEX)
    "pump_px_check_on": (bool, True, 0, 1),
    "pump_px_need_mkt": (bool, True, 0, 1),            # token de fora da pump.fun só é copiado com preço de mercado para conferir
    # não copiar token que já subiu X% nos 15 min antes da compra do trader (0 = desliga). 0.32.332 (pedido do dono, 13/11: "a estratégia de
    # entrada tá horrível; segue o que você propõe"): padrão 100 para quem ainda não mexeu. Estudo de 13/11: essas cópias deram −24% (44),
    # contra −1,7% das que entraram antes da subida. Quem já salvou outro valor fica com o dele.
    "pump_runup_max_pct": (float, 100.0, 0.0, 100000.0),
    # 0.31.37 (sugestão do Bruxo, 2026-10-27): com a Execução real ligada, a carteira real copia 100% dos trades da
    # fictícia (cópias, Explorar, Base, Maiores traders, botão Comprar), mas o valor e os limites vêm só das regras reais
    "pump_real_mirror": (bool, True, 0, 1),
    "pump_real_need_win": (bool, True, 0, 1),
    # 0.32.325 (pedido do dono, 12/11/2026: "sim, faz a trava"): trava por TELA. Uma tela (Top traders, Explorar, Aba do Bruxo…) só
    # compra na REAL depois de provar resultado na FICTÍCIA: pelo menos N operações fechadas nos últimos D dias com a soma
    # positiva depois das taxas. Voltou ao prejuízo, sai da REAL sozinha. Compra pelo botão (clique seu) não passa pela trava.
    "pump_tab_gate_on": (bool, True, 0, 1),
    "pump_tab_gate_n": (int, 20, 1, 1000),
    "pump_tab_gate_days": (int, 7, 1, 90),
    "pump_real_full_mirror": (bool, False, 0, 1),      # 0.32.277: Espelho total, ignora o "só fictícia" do estudo (começa OFF)         # 0.32.251: trader novo só na fictícia até uma cópia fictícia com lucro
    # 0.32.275 (pedido do dono): copiar só traders com resultado médio por cópia positivo (o acerto sozinho engana: com stop de
    # 40%, 10 perdas não se pagam com 20 ganhos de 10%)
    "pump_edge_on": (bool, True, 0, 1),               # 0.32.323: ligado por padrão (só trava a REAL: pump_edge_real_only)
    "pump_edge_min_n": (int, 5, 1, 100),              # cópias fictícias fechadas para ter base
    "pump_edge_days": (int, 7, 1, 90),                # janela das cópias que contam
    "pump_edge_min_pct": (float, 0.0, -50.0, 500.0),  # média mínima por cópia (%), depois das taxas
    "pump_edge_real_only": (bool, True, 0, 1),
    # 0.32.328 (pedido do dono, 12/11: "faz tudo" — copiar os maiores traders não estava dando certo): liga de candidatos. As vagas do
    # Top traders vão primeiro para quem já deu resultado PARA QUEM COPIA (média por cópia fictícia, regra acima), depois para quem
    # ainda está em teste; quem tem base e dá prejuízo, ou vende rápido demais para ser copiado, perde a vaga para o próximo.
    "pump_liga_on": (bool, True, 0, 1),
    "pump_liga_min_hold_s": (int, 60, 0, 3600),       # cópias que duram menos que isso (mediana) = trader rápido demais para copiar        # True: só trava a REAL; a fictícia continua copiando para aprender
    # 0.32.158 (pedido do dono, 02/11): com real e fictícia ligadas, a REAL manda e a fictícia é a cópia exata dela (mesmo valor,
    # mesmo preço de entrada, sai junto; se a real não compra, a fictícia é desfeita). Começa desligada; ligada só por ajuste pedido.
    "pump_real_exact": (bool, False, 0, 1),
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


# 0.32.323: valores que eram o padrão das saídas até a 0.32.322. A conta que ainda está neles (e não mexeu na opção pela tela)
# passa para o padrão novo UMA vez; a marca `_saidas_v` fica guardada junto das opções da conta.
# 0.32.324: o ajuste virou uma lista por etapa (AJUSTES); a conta recebe as etapas acima da marca que já tem.
AJUSTES = {
    2: {"pump_stop_pct": 40.0, "pump_hold_until_profit": True, "pump_trail_start_pct": 20.0, "pump_trail_dist_pct": 10.0,
        "pump_edge_on": False},
    3: {"pump_priority_sol": 0.0005, "pump_exit_migrate": False, "pump_nc_on": False, "pump_swap_fee_official": False},
    4: {"pump_extra_slip_pct": 3.0},
}
SAIDAS_V = max(AJUSTES)
SAIDAS_OLD = {k: v for etapa in AJUSTES.values() for k, v in etapa.items()}      # todos os padrões antigos (os testes antigos usam)
SAIDAS_WHY = "ajuste das versões 0.32.323, 0.32.324 e 0.32.335 (saídas, custo por trade, traders que não dá para copiar e slippage simulado da fictícia)"


def saidas_upgrade(saved: dict | None, atual: dict, mexeu=()) -> dict:
    """O que muda nesta conta: {opção: valor novo}. Vazio se a conta é nova, se já recebeu todas as etapas, se a opção não está
    mais no padrão antigo ou se a pessoa mudou a opção pela tela (`mexeu`). Só mexe nas opções de AJUSTES."""
    if not saved:
        return {}
    try:
        feito = int(saved.get("_saidas_v") or 1)
    except (TypeError, ValueError):
        feito = 1
    out = {}
    for etapa, olds in AJUSTES.items():
        if etapa <= feito:
            continue
        for k, old in olds.items():
            novo = USER_KEYS[k][1]
            if k not in mexeu and atual.get(k) == old and novo != old:
                out[k] = novo
    return out


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
