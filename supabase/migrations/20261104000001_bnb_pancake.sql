-- 0.32.178 (pedido do dono, 04/11/2026): compras e vendas na PancakeSwap dos tokens que graduaram da Four.Meme entram na
-- mesma tabela dos trades da curva, marcadas em venue ('fourmeme' = curva, 'pancake' = par V2 da PancakeSwap).
-- Os pares ficam em bnb_state (k = 'pairs'). Só o backend lê e grava (RLS sem política, como antes).
alter table public.bnb_fm_trades add column if not exists venue text not null default 'fourmeme';
alter table public.bnb_fm_trades drop constraint if exists bnb_fm_trades_venue_check;
alter table public.bnb_fm_trades add constraint bnb_fm_trades_venue_check check (venue in ('fourmeme', 'pancake'));
