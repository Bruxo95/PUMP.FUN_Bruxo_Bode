-- 0.32.330 (pedido do Bruxo 9519 no chat, 12/11: "faça as melhores configurações de entrada e saída para a carteira real lucrar"):
-- ajuste só na conta dele, pela tabela settings_overrides (aplicada pelo servidor ao carregar a conta). Base: 187 trades REAL
-- (−1,418 SOL) e 626 trades dos últimos 12 dias. As outras contas não mudam.
insert into public.settings_overrides (user_id, settings, motivo)
values ('06d5f047-6ef2-4695-ae58-d83913abc3e9',
        '{"pump_real_no_curve": true, "pump_edge_min_pct": 5, "pump_edge_min_n": 8,
          "pump_real_daily_loss_sol": 0.25, "pump_real_max_open": 10}'::jsonb,
        'estudo da carteira real (12/11): REAL fora da curva, só traders com +5% por cópia em 8+, perda do dia 0,25 SOL, 10 abertas');
