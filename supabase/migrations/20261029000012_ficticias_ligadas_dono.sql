-- 0.32.61 (pedido do dono no chat, 29/10: "se for fictício sempre tá ligado, para aprender, estudar ou tentar ganhar mais";
-- "eu não quero nada da real ligado"). Só na conta do dono (settings_overrides): liga as estratégias e estudos que operam só na
-- carteira FICTÍCIA e deixa DESLIGADO todo botão REAL das abas. Os barrados do Explorar continuam como o dono deixou (ele
-- desligou depois de 11 stops); o Explorar não muda de regra.
insert into public.settings_overrides (user_id, settings, motivo)
select p.user_id,
       '{"pump_lanc_on": true, "pump_st_auto_on": true, "pump_st_auto_copy": true, "pump_calls_auto_on": true,
         "pump_el_auto_on": true, "pump_auto_on": true, "pump_radar_enabled": true, "pump_bx_on": true, "pump_eq_on": true,
         "pump_stop_fast_on": true,
         "pump_calls_real": false, "pump_el_real": false, "pump_auto_real": false, "pump_bx_real": false,
         "pump_bar_real": false, "pump_st_real": false, "pump_eq_real": false, "pump_ex_real_on": false}'::jsonb,
       'pedido do dono (29/10): tudo que é fictício ligado, tudo que é real desligado'
from public.profiles p where lower(p.email) = 'onlineguyat@gmail.com';
