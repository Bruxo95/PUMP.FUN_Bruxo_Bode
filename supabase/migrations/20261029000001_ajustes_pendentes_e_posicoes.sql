-- 0.32.33 (2026-10-29). Duas tabelas, só o backend lê e grava.
-- 1) settings_overrides: ajuste de configuração pedido pelo dono no chat, aplicado pelo servidor NOVO quando carrega a conta.
--    Motivo: as migrações 20261028000013/14 gravaram direto em user_settings, mas o servidor antigo (ainda no ar até o deploy
--    terminar) salvou a configuração da memória por cima e os valores novos se perderam (print do dono em 29/10: "limite de 4
--    entradas por hora", "volume abaixo de $20,000").
create table if not exists public.settings_overrides (
  id          bigserial primary key,
  user_id     uuid not null,
  settings    jsonb not null default '{}'::jsonb,
  motivo      text,
  criado_em   timestamptz not null default now(),
  aplicado_em timestamptz
);
create index if not exists settings_overrides_user on public.settings_overrides (user_id) where aplicado_em is null;
alter table public.settings_overrides enable row level security;
revoke all on public.settings_overrides from anon, authenticated;

-- 2) position_learn: cada posição fechada, com onde entrou (15 min antes), as fotos de 15 em 15 min e o que o preço fez
--    15/30/60 min depois da saída (pedido do dono em 29/10: aprender se entrou e saiu na hora certa e alimentar a Base).
create table if not exists public.position_learn (
  id        bigserial primary key,
  user_id   uuid not null,
  pos_id    text,
  mint      text,
  real      boolean not null default false,
  fechou_em timestamptz,
  em        timestamptz not null default now(),
  data      jsonb not null default '{}'::jsonb
);
create index if not exists position_learn_em on public.position_learn (em desc);
alter table public.position_learn enable row level security;
revoke all on public.position_learn from anon, authenticated;
do $$ begin
  if exists (select 1 from pg_roles where rolname = 'leitor_ia') then
    grant select on public.position_learn to leitor_ia;
    create policy "leitor_ia: ler" on public.position_learn for select to leitor_ia using (true);
  end if;
end $$;

-- Ajuste do dono (o mesmo das migrações 13/14, que se perderam): barrados em +20%, sem volume mínimo, 20/h, 30 abertas.
insert into public.settings_overrides (user_id, settings, motivo)
select p.user_id, '{"pump_bar_auto_on": true, "pump_bar_min_gain": 20, "pump_bar_min_vol_usd": 0, "pump_bar_max_h": 20, "pump_bar_max_open": 30}'::jsonb,
       'pedido do dono no chat em 28/10 (barrados que subiram)'
from public.profiles p where lower(p.email) = 'onlineguyat@gmail.com' limit 1;
