-- 0.32.31 (pedido do dono no chat em 2026-10-28: "tem alguns que não foram, eles sempre devem ir na fictícia"): na conta do dono
-- (onlineguyat@gmail.com), a entrada automática dos barrados sobe de 4 para 20 por hora e ganha 30 vagas próprias de posição.
-- Continua só na carteira fictícia. Nenhuma outra opção dele ou de outra pessoa muda.
update public.user_settings us
set settings = coalesce(us.settings, '{}'::jsonb) || '{"pump_bar_max_h": 20, "pump_bar_max_open": 30}'::jsonb,
    atualizado_em = now()
where us.user_id = (select p.user_id from public.profiles p where lower(p.email) = 'onlineguyat@gmail.com' limit 1);
