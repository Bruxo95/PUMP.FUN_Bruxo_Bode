-- Base da pump.fun (0.31.1): contador de tokens "bundle" por criador (robô que compra a curva inteira junto com a
-- criação). Antes esses tokens contavam como "graduou/2x" e o robô aparecia como criador bom. Só acrescenta coluna;
-- os números são recalculados pelo servidor a partir de token_life na próxima partida.
alter table public.creator_stats add column if not exists bundles integer not null default 0;
