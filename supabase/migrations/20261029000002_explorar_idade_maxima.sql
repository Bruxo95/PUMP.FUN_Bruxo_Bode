-- 0.32.36 (sugestão do Bruxo no WhatsApp em 28/10 22:11, "faz isso agora" do dono): no Explorar, só token com até 10 min de vida
-- (sem a espera mínima de 20 min das automáticas, que tornaria impossível entrar). Só nas contas do dono e do Bruxo, pela
-- tabela settings_overrides (aplicada pelo servidor novo ao carregar a conta). As outras contas não mudam.
insert into public.settings_overrides (user_id, settings, motivo)
select p.user_id, '{"pump_ex_max_age_min": 10, "pump_ex_min_age_min": 0}'::jsonb,
       'sugestão do Bruxo (28/10 22:11): Explorar só com token de até 10 min'
from public.profiles p where lower(p.email) in ('onlineguyat@gmail.com', 'bruxo9519@gmail.com');
