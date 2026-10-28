-- Compra automática das Calls quentes (0.31.99, pedido do dono em 2026-10-28; só na carteira fictícia e desligada por
-- padrão): libera a origem 'calls' no registro das operações automáticas.
alter table public.auto_trades drop constraint if exists auto_trades_origem_check;
alter table public.auto_trades add constraint auto_trades_origem_check check (origem in ('base', 'explorar', 'elite', 'calls'));
