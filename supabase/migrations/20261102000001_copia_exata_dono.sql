-- 0.32.158 (pedido do dono no chat, 02/11: "com a fictícia e a real ligadas, a fictícia tem que ser a cópia exata; a decisão é
-- sempre primeiro da real, de compra e venda"): liga o espelho e a cópia exata só na conta do dono, pela tabela
-- settings_overrides (aplicada pelo servidor novo ao carregar a conta). As outras contas não mudam.
insert into public.settings_overrides (user_id, settings, motivo)
select p.user_id, '{"pump_real_mirror": true, "pump_real_exact": true}'::jsonb,
       'pedido do dono (02/11): a real manda e a fictícia é a cópia exata dela'
from public.profiles p where lower(p.email) = 'onlineguyat@gmail.com';
