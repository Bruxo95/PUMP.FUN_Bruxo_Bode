-- 0.32.450 (caso DXM do dono, 25/11): trades REAIS antigos em que o aluguel da conta do token devolvido foi tirado das taxas
-- (a soma das partes era 0,0016 SOL e "Taxas pagas" mostrava 0,0003). Mesma conta da 0.32.449: rede = 0,0001 SOL por transação
-- (compra + vendas), "Taxas pagas" = soma das partes e "Ganho geral" = líquido + taxas. O líquido (pnl_sol) não muda.
-- Só trades fechados antes da 0.32.449 com a conta do token devolvida e ainda sem correção; o antigo fica em data->'taxa_antiga'.
with fix as (
  select id,
         0.0001 * (1 + coalesce(jsonb_array_length(case when jsonb_typeof(data->'sells') = 'array' then data->'sells' end), 1)) as net,
         coalesce((data->'fee_parts'->>'platform')::numeric, 0) + coalesce((data->'fee_parts'->>'portal')::numeric, 0)
           + coalesce((data->'fee_parts'->>'slippage')::numeric, 0) as resto
  from pump_trades
  where real
    and data ? 'fee_parts'
    and not (data ? 'taxa_antiga')
    and coalesce((data->>'conta_devolvida_sol')::numeric, 0) > 0
    and fechada_em < '2026-11-25 01:45:00+00'
)
update pump_trades t
set data = t.data
  || jsonb_build_object('taxa_antiga', jsonb_build_object('fee_parts', t.data->'fee_parts', 'fees_sol', t.data->'fees_sol', 'gross_sol', t.data->'gross_sol'))
  || jsonb_build_object('fee_parts', (t.data->'fee_parts') || jsonb_build_object('network', round(f.net, 6)))
  || jsonb_build_object('fees_sol', round(f.resto + f.net, 6))
  || jsonb_build_object('gross_sol', round(coalesce((t.data->>'pnl_sol')::numeric, 0) + f.resto + f.net, 6))
from fix f
where t.id = f.id;
