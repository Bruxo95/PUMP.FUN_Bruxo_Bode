-- 0.32.227 (pedido do dono, 05/11/2026): Dormant, painel próprio que vigia a watchlist da CoinMarketCap do dono pela
-- CoinGecko e diz o que está dormindo, acordando, num pump ou num dump. Só observa: não compra nada.
-- dormant_state: regras, ligação CoinMarketCap -> CoinGecko e os últimos alertas. dormant_snap: uma linha por hora com o
-- preço, o volume e o valor de mercado de todas as moedas (jsonb), guardada 90 dias. Só o backend lê e grava.
create table if not exists public.dormant_state (
  k   text primary key,
  v   jsonb not null default '{}'::jsonb,
  em  timestamptz not null default now()
);
create table if not exists public.dormant_snap (
  t      timestamptz primary key,
  dados  jsonb not null default '{}'::jsonb
);
alter table public.dormant_state enable row level security;
alter table public.dormant_snap enable row level security;
revoke all on public.dormant_state from anon, authenticated;
revoke all on public.dormant_snap from anon, authenticated;

-- chave Demo da CoinGecko como chave do sistema (toda chave do sistema nova entra nesta regra; tests/test_jev.py confere)
alter table public.app_secrets drop constraint if exists app_secrets_nome_check;
alter table public.app_secrets add constraint app_secrets_nome_check check (
  nome in ('solanatracker_api_key', 'pumpportal_api_key', 'jupiter_api_key', 'rpc_url', 'jev_api_key', 'nodereal_bnb_key',
           'coingecko_key')
);

do $$ begin
  if exists (select 1 from pg_roles where rolname = 'leitor_ia') then
    grant select on public.dormant_state, public.dormant_snap to leitor_ia;
    create policy "leitor_ia: ler" on public.dormant_state for select to leitor_ia using (true);
    create policy "leitor_ia: ler" on public.dormant_snap for select to leitor_ia using (true);
  end if;
end $$;
