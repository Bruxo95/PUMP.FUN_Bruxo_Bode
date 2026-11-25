-- 0.32.449 (pedido do dono, Zeus 25/11): trades REAIS antigos em que o SOL gasto a mais na compra (a PumpPortal na PumpSwap
-- gastava mais que o configurado) foi gravado como "taxa de rede". A rede passa a ser 0,0001 SOL por transação (compra + vendas),
-- e "Taxas pagas" e "Ganho geral" são refeitos. O líquido (pnl_sol, diferença real de SOL) não muda.
-- Só trades com a conta do token devolvida (desde 05/11): antes disso o aluguel não voltava e fazia parte do custo.
-- O valor antigo fica em data->'taxa_antiga'. Relatórios já gravados (daily_report, result_studies) continuam com o número antigo.
with fix as (
  select id,
         0.0001 * (1 + coalesce(jsonb_array_length(case when jsonb_typeof(data->'sells') = 'array' then data->'sells' end), 1)) as net,
         coalesce((data->'fee_parts'->>'platform')::numeric, 0) + coalesce((data->'fee_parts'->>'portal')::numeric, 0)
           + coalesce((data->'fee_parts'->>'slippage')::numeric, 0) as resto
  from pump_trades
  where real
    and data ? 'fee_parts'
    and not (data ? 'taxa_antiga')
    and coalesce((data->>'conta_devolvida_sol')::numeric, 0) > 0   -- antes da 0.32.215 o aluguel ficava preso: era custo de verdade
    and coalesce((data->'fee_parts'->>'network')::numeric, 0) > 0.002
)
update pump_trades t
set data = t.data
  || jsonb_build_object('taxa_antiga', jsonb_build_object('fee_parts', t.data->'fee_parts', 'fees_sol', t.data->'fees_sol', 'gross_sol', t.data->'gross_sol'))
  || jsonb_build_object('fee_parts', (t.data->'fee_parts') || jsonb_build_object('network', round(f.net, 6)))
  || jsonb_build_object('fees_sol', round(f.resto + f.net, 6))
  || jsonb_build_object('gross_sol', round(coalesce((t.data->>'pnl_sol')::numeric, 0) + f.resto + f.net, 6))
from fix f
where t.id = f.id;
