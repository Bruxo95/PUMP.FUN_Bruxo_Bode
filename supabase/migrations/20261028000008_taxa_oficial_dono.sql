-- 0.32.0 (pedido do dono no chat em 2026-10-28: "faz isso agora … ligar só pro fictício pra testes"): liga a opção
-- pump_swap_fee_official SÓ na conta do dono (onlineguyat@gmail.com). Desde a 0.32.0 essa tabela só vale para a carteira
-- fictícia. Nenhuma outra opção dele ou de outra pessoa muda. Se o e-mail não existir, não faz nada.
update public.user_settings us
set settings = coalesce(us.settings, '{}'::jsonb) || '{"pump_swap_fee_official": true}'::jsonb,
    atualizado_em = now()
where us.user_id = (select p.user_id from public.profiles p where lower(p.email) = 'onlineguyat@gmail.com' limit 1);
