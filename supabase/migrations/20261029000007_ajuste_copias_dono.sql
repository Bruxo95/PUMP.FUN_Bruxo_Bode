-- 0.32.50 (pedido do dono no chat, 29/10: "faz tudo aí" sobre as sugestões a partir dos relatórios e erros do dia). Só na conta
-- do dono, pela tabela settings_overrides (aplicada pelo servidor novo ao carregar a conta). Vale para as CÓPIAS de traders
-- (Explorar, Aba do Bruxo, barrados e botão Comprar têm regras próprias e não mudam). A REAL dele está desligada.
--  - stop por tempo: 5 min sem passar de +10% líquido, vende;  - tempo máximo das cópias: 24 min (a moeda dura ~25 min);
--  - venda parcial: 50% em +35%;  - stop móvel no resto: 13 pontos do pico (devolvia 15–25);
--  - filtro contra despejo: 10 maiores ≤ 35%, criador ≤ 10%, carteiras novas ≤ 30%.
insert into public.settings_overrides (user_id, settings, motivo)
select p.user_id,
       '{"pump_timestop_on": true, "pump_timestop_s": 300, "pump_timestop_gain_pct": 10, "pump_max_hold_h": 0.4,
         "pump_tp1_on": true, "pump_tp1_pct": 35, "pump_tp1_frac_pct": 50, "pump_trail_enabled": true, "pump_trail_dist_pct": 13,
         "pump_dump_on": true, "pump_dump_top10_max": 35, "pump_dump_dev_max": 10, "pump_dump_fresh_max": 30}'::jsonb,
       'pedido do dono (29/10): cópias com saída por tempo, parcial em +35%, stop móvel de 13 pontos e filtro contra despejo'
from public.profiles p where lower(p.email) = 'onlineguyat@gmail.com';
