-- 0.32.52 (print do dono, 29/10: barrados ainda entraram às 11:05, 11:08 e 11:13 depois da 0.32.44): o ajuste que desligava a
-- entrada automática dos barrados foi aplicado, mas o servidor antigo, que ainda estava no ar na troca de versão, gravou a
-- configuração da memória (ligada) por cima. Mesmo pedido de novo, só na conta do dono; a 0.32.52 reafirma o ajuste por 20 min.
insert into public.settings_overrides (user_id, settings, motivo)
select p.user_id, '{"pump_bar_auto_on": false}'::jsonb,
       'pedido do dono (29/10): barrados automáticos desligados (de novo: o servidor antigo tinha gravado por cima)'
from public.profiles p where lower(p.email) = 'onlineguyat@gmail.com';
