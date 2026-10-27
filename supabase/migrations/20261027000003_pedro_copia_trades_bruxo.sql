-- 0.31.62 (pedido do dono em 2026-10-27, no chat): a conta do Pedro Rodrigues (marketingwebhelper@gmail.com) passa a
-- copiar os TRADES da conta Bruxo 9519 (bruxo9519@gmail.com). Só acrescenta a chave _follow_user nas configurações do
-- Pedro; nenhuma outra opção dele ou de outra pessoa muda. Se algum dos dois e-mails não existir, não faz nada.
update public.user_settings us
set settings = coalesce(us.settings, '{}'::jsonb)
               || jsonb_build_object('_follow_user', (select p.user_id::text from public.profiles p
                                                      where lower(p.email) = 'bruxo9519@gmail.com' limit 1)),
    atualizado_em = now()
where us.user_id = (select p.user_id from public.profiles p where lower(p.email) = 'marketingwebhelper@gmail.com' limit 1)
  and exists (select 1 from public.profiles p where lower(p.email) = 'bruxo9519@gmail.com');
