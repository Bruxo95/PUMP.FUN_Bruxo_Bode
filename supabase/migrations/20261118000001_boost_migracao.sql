-- 0.32.373 (pedido do dono, 18/11/2026): BOOST da migração (app/boostmig.py). Parte compartilhada, só o servidor lê e grava
-- (RLS ligado e sem política para o navegador). As posições e os trades de cada usuário continuam em pump_positions/pump_trades.
create table if not exists public.boost_tokens (
  mint text primary key,
  t0 timestamptz not null,                 -- hora da migração para a PumpSwap
  dados jsonb not null default '{}'::jsonb, -- DEV, trava, topo/dump, amostras, resultado
  atualizado timestamptz not null default now()
);
create index if not exists boost_tokens_t0 on public.boost_tokens (t0 desc);
alter table public.boost_tokens enable row level security;
revoke all on public.boost_tokens from anon, authenticated;

create table if not exists public.boost_devs (
  creator text primary key,                -- carteira do DEV (criador lido na conta da curva)
  dados jsonb not null default '{}'::jsonb, -- {"scam": {...} | null, "book": {...} | null}
  atualizado timestamptz not null default now()
);
alter table public.boost_devs enable row level security;
revoke all on public.boost_devs from anon, authenticated;

do $$
begin
  if exists (select 1 from pg_roles where rolname = 'leitor_ia') then
    grant select on public.boost_tokens, public.boost_devs to leitor_ia;
    create policy "leitor_ia: ler" on public.boost_tokens for select to leitor_ia using (true);
    create policy "leitor_ia: ler" on public.boost_devs for select to leitor_ia using (true);
  end if;
end $$;
