-- 0.32.5 (pedido do dono no chat em 2026-10-28: "Liga pra mim", só na fictícia): liga o Copiar igual SÓ na conta do dono
-- (onlineguyat@gmail.com). pump_eq_real fica desligado (a real não entra por este modo). Nenhuma outra opção dele ou de
-- outra pessoa muda. Se o e-mail não existir, não faz nada.
update public.user_settings us
set settings = coalesce(us.settings, '{}'::jsonb) || '{"pump_eq_on": true, "pump_eq_real": false}'::jsonb,
    atualizado_em = now()
where us.user_id = (select p.user_id from public.profiles p where lower(p.email) = 'onlineguyat@gmail.com' limit 1);
