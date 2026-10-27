-- 0.31.63 (pedido do dono em 2026-10-27, no chat): a conta do Pedro Rodrigues (marketingwebhelper@gmail.com) PARA de copiar
-- os trades do Bruxo 9519 — o bot dele decide sozinho com a mesma configuração e o aprendizado geral. Só tira a chave
-- _follow_user das configurações do Pedro; nenhuma outra opção dele ou de outra pessoa muda.
update public.user_settings us
set settings = coalesce(us.settings, '{}'::jsonb) - '_follow_user',
    atualizado_em = now()
where us.user_id = (select p.user_id from public.profiles p where lower(p.email) = 'marketingwebhelper@gmail.com' limit 1);
