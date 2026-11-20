-- 0.32.401 (dono, 21/11: "o resultado da REAL não está gravando" no BOOST): o trade REAL fechado junto com a fictícia do
-- BOOST não guardava a origem, então o BOOST não o contava. Marca origem "boostmig" nos trades REAL que fecharam
-- "junto com a fictícia" até 10 min depois de um trade fictício do BOOST no mesmo token, da mesma conta. Só acrescenta a chave.
update public.pump_trades r
   set data = r.data || jsonb_build_object('origem', 'boostmig')
 where r.real = true
   and not (r.data ? 'origem')
   and coalesce(r.data->>'reason', '') like 'junto com a fictícia:%'
   and exists (select 1 from public.pump_trades f
                where f.user_id = r.user_id and f.real = false
                  and f.data->>'origem' = 'boostmig'
                  and f.data->>'mint' = r.data->>'mint'
                  and abs(extract(epoch from (r.fechada_em - f.fechada_em))) <= 600);
