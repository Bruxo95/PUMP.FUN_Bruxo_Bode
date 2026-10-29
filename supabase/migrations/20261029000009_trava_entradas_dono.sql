-- 0.32.53 (pedido do dono no chat, 29/10: "põe a trava", depois do BabyNuts −92% com stop de −30%): trava de segurança nas
-- entradas dos barrados, do botão Comprar e da Aba do Bruxo, só na conta do dono (settings_overrides). O Explorar não passa por ela.
insert into public.settings_overrides (user_id, settings, motivo)
select p.user_id, '{"pump_guard_on": true, "pump_guard_min_liq_usd": 15000}'::jsonb,
       'pedido do dono (29/10): trava de segurança nas entradas (preço confirmado, liquidez e contra despejo)'
from public.profiles p where lower(p.email) = 'onlineguyat@gmail.com';
