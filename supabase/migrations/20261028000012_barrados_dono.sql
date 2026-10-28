-- 0.32.21 (pedido do dono no chat em 2026-10-28: "essas moedas já entrar automático no fictício, nunca no real"): liga a
-- entrada automática dos barrados que subiram SÓ na conta do dono (onlineguyat@gmail.com). Essa entrada é sempre só na
-- carteira fictícia (regra do código). Nenhuma outra opção dele ou de outra pessoa muda. Se o e-mail não existir, não faz nada.
update public.user_settings us
set settings = coalesce(us.settings, '{}'::jsonb) || '{"pump_bar_auto_on": true}'::jsonb,
    atualizado_em = now()
where us.user_id = (select p.user_id from public.profiles p where lower(p.email) = 'onlineguyat@gmail.com' limit 1);
