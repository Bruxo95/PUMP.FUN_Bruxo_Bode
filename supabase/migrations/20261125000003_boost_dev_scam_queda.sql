-- 0.32.457 (pedido do dono, 25/11/2026): DEVs dos tokens do BOOST que caíram −70% ou mais de uma vez e não foram para a lista
-- de scam (a DexScreener parou de responder e o acompanhamento de preço não viu a queda). Marca, como a regra nova do código:
-- posição do BOOST que fechou com −70% ou pior até 10 min depois da migração, nos últimos 3 dias. Só muda quem ainda não está
-- marcado (scam vazio); não cria linha nova. A lista de scam vale 7 dias a partir de agora (SCAM_KEEP_S do código).
with q as (
  select distinct on (h.creator) h.creator, t.mint, t.sym, round(t.pnl::numeric) pnl,
         round(t.ct - extract(epoch from h.t0)) apos
  from (select data->>'mint' mint, data->>'symbol' sym, min((data->>'pnl_pct')::float) pnl,
               max(extract(epoch from (data->>'closed_at')::timestamptz)) ct
        from public.pump_trades
        where data->>'origem' = 'boostmig' and (data->>'closed_at')::timestamptz > now() - interval '3 days'
        group by 1, 2) t
  join public.boost_history h on h.mint = t.mint
  where t.pnl <= -70 and t.ct - extract(epoch from h.t0) <= 600 and h.creator is not null
  order by h.creator, t.pnl
), m as (
  select creator, mint, sym, format('queda de %s%% na posição do BOOST aos %s min %s s', pnl, apos::int / 60, apos::int % 60) why
  from q
)
update public.boost_devs d
set dados = jsonb_set(d.dados, '{scam}', jsonb_build_object(
      't', extract(epoch from now()), 'why', m.why, 'symbol', m.sym,
      'mints', jsonb_build_object(m.mint, jsonb_build_object('symbol', m.sym, 'why', m.why, 't', extract(epoch from now()))))),
    atualizado = now()
from m
where d.creator = m.creator and coalesce(d.dados -> 'scam', 'null'::jsonb) = 'null'::jsonb;
