-- 0.32.29 (pedido do dono no chat em 2026-10-28, com a tabela "E se tivesse entrado cedo?": +20% deu 15 entradas, 60% de
-- acerto e média +13,5% já com taxas): a entrada automática dos barrados passa a entrar em +20% e sem volume mínimo (a
-- simulação não filtrou volume), SÓ na conta do dono (onlineguyat@gmail.com). Continua só na carteira fictícia.
update public.user_settings us
set settings = coalesce(us.settings, '{}'::jsonb) || '{"pump_bar_auto_on": true, "pump_bar_min_gain": 20, "pump_bar_min_vol_usd": 0}'::jsonb,
    atualizado_em = now()
where us.user_id = (select p.user_id from public.profiles p where lower(p.email) = 'onlineguyat@gmail.com' limit 1);
