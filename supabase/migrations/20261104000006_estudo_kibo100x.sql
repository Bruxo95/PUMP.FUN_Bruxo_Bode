-- 0.32.210 (pedido do dono no chat, 04/11): as 12 carteiras que o perfil kibo100x (CUK1…WU2e) segue na pump.fun entram em
-- Carteiras em estudo, só na conta do dono. Estudo só observa (não copia). Apelido "kibo100x · nome" (o estudo automático
-- só julga e tira as de apelido "auto · "). Respeita o limite de 30 por conta (app/study.py MAX_WALLETS) e não duplica.
do $$
declare
  uid uuid;
  w   record;
  n   integer;
begin
  select p.user_id into uid from public.profiles p where lower(p.email) = 'onlineguyat@gmail.com';
  if uid is null then
    return;
  end if;
  for w in select * from (values
      (1, '5YRgrP3mjGzrzirYYN5HAQH19cTYREYwGxW6XRJQUzij', 'kibo100x · slingoor'),
      (2, '6vbrTLsWy76TxDQAUKLqZrPohQuq6EVaJgfGzR82paFa', 'kibo100x · marcell'),
      (3, '6DQAGJT7VZPVBsuG4kn3AvpyHCEi7B2RFFvMZdbqQqqP', 'kibo100x · cupsey'),
      (4, '8k1sAmVUjzaZkxqexeYkCPphjcQobYugQeGmCyvKtHNG', 'kibo100x · PoorGoat'),
      (5, 'GccvEcZqMrcNdp3CarCasGdN5dUfdQ4wZ6iQsk5myRzX', 'kibo100x · SoloFNF'),
      (6, 'DuARUpsEzdVbVpSnbGipLJvWxaXUCPLDJDjNov6Rc6s6', 'kibo100x · HarryPaulDavies'),
      (7, '2NsevsKWiaDtEiYF5gGLCVGNBwsLNibgppoiVPHHYrqq', 'kibo100x · y22'),
      (8, 'AvGiSdrkwtGYhrrFXZPtdhNhV4pASUR67TmRjfaKGdMP', 'kibo100x · wirelyss'),
      (9, 'DPiQs7yP5WnBxN7RwttMKkrndmeTzeVZ69sxeAswxm8r', 'kibo100x · suggss'),
      (10, 'EGB6v3y5oS7Whv4KHYp8ksL2wRfqdfAF5Dbqq8kHXsZH', 'kibo100x · CyrusAbrahim'),
      (11, 'DEdEW3SMPU2dCfXEcgj2YppmX9H3bnMDJaU4ctn2BQDQ', 'kibo100x · Edward_Cullen'),
      (12, 'C5FuhpiezHH6b1bR7eSF5fT4dNsEMzwNcEVvpKggXJq1', 'kibo100x · gake')
    ) as v(ordem, wallet, apelido) order by ordem
  loop
    select count(*) into n from public.study_wallets where user_id = uid;
    exit when n >= 30;
    insert into public.study_wallets (user_id, wallet, apelido)
    values (uid, w.wallet, w.apelido)
    on conflict (user_id, wallet) do nothing;
  end loop;
end $$;
