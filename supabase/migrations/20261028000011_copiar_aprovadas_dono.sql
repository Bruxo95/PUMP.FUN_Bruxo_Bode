-- 0.32.11 (pedido do dono no chat em 2026-10-28: "liga pra ir automático somente na fictícia"): liga a cópia automática
-- das carteiras aprovadas pelo estudo automático SÓ na conta do dono (onlineguyat@gmail.com). Essa cópia nunca vai para a
-- carteira real (regra do código). Nenhuma outra opção dele ou de outra pessoa muda. Se o e-mail não existir, não faz nada.
update public.user_settings us
set settings = coalesce(us.settings, '{}'::jsonb) || '{"pump_st_auto_copy": true}'::jsonb,
    atualizado_em = now()
where us.user_id = (select p.user_id from public.profiles p where lower(p.email) = 'onlineguyat@gmail.com' limit 1);
