-- Ajuste automático das compras automáticas do Explorar (0.31.21): novo tipo 'saida_auto' no registro de mudanças.
alter table public.auto_tune_log drop constraint if exists auto_tune_log_tipo_check;
alter table public.auto_tune_log add constraint auto_tune_log_tipo_check check (tipo in ('saida', 'saida_auto', 'trader'));
