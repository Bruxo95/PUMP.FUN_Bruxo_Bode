-- 0.32.59 (pedido do dono no chat, 29/10: "pegar lá do início quando abre, fazer lucro e sair antes de graduar" + "sim").
-- Só na conta do dono (settings_overrides): cópias só com a curva até 25% e nunca em token graduado; saída antes da graduação
-- (curva em 85%) só nas cópias; Aba do Bruxo só com token de até 2 min e curva até 25%, saindo com a curva em 85%; e o estudo do
-- lançamento sem trader (só mede, nunca compra). O Explorar não muda.
insert into public.settings_overrides (user_id, settings, motivo)
select p.user_id,
       '{"pump_entry_curve_on": true, "pump_entry_curve_min": 0, "pump_entry_curve_max": 25,
         "pump_curve_exit_on": true, "pump_curve_exit_pct": 85, "pump_cx_copies_only": true,
         "pump_bx_max_age_min": 2, "pump_bx_curve_max": 25, "pump_bx_grad_exit": 85, "pump_lanc_on": true}'::jsonb,
       'pedido do dono (29/10): entrar no começo da curva e sair antes de graduar'
from public.profiles p where lower(p.email) = 'onlineguyat@gmail.com';
