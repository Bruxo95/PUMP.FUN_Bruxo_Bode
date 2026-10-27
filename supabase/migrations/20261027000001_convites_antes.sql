-- 0.31.31 (pedido do dono em 2026-10-27): guardar os valores que a pessoa tinha ANTES de aceitar um convite de
-- configuração, para o painel mostrar "o que mudou e o que continuou igual". Só acrescenta a coluna; não apaga nada.
alter table public.config_offers add column if not exists antes jsonb not null default '{}'::jsonb;
