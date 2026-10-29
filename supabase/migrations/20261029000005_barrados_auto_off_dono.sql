-- 0.32.44 (pedido do dono no chat, 29/10: "Sim, desliga"): a entrada automática dos barrados que subiram estava entrando no
-- topo (11 stops de −30% em 15 fechadas em 3 h, vários em segundos). Desligada só na conta do dono, pela tabela
-- settings_overrides (aplicada pelo servidor novo ao carregar a conta). As outras contas não mudam; a lista dos barrados e a
-- tabela "E se tivesse entrado cedo?" continuam medindo.
insert into public.settings_overrides (user_id, settings, motivo)
select p.user_id, '{"pump_bar_auto_on": false}'::jsonb,
       'pedido do dono (29/10): desligar a entrada automática dos barrados até os relatórios mostrarem um gatilho que dê lucro'
from public.profiles p where lower(p.email) = 'onlineguyat@gmail.com';
