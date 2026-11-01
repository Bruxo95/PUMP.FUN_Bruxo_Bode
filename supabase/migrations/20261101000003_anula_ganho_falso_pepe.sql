-- 0.32.128 (pedido do dono em 01/11/2026): anula o ganho falso do PEPE na carteira FICTÍCIA.
-- O preço era lido com 6 casas decimais e o token tem 4 (100× maior, corrigido na 0.32.65). O saldo fictício ficou ~10 SOL inflado.
-- Só trades fictícios do PEPE, fechados em 29 ou 30/10, com +1.900% ou mais. Trade REAL não entra. Nenhuma linha é apagada:
-- o resultado original fica em data->'corrigido'. Rodar de novo não muda nada, porque o trade anulado sai do filtro.
update public.pump_trades
set data = data || jsonb_build_object(
      'pnl_sol', 0,
      'pnl_pct', 0,
      'sol_out', data->'sol_in',
      'gross_sol', 0,
      'best_pct', 0,
      'reason', 'anulado: preço errado (PEPE, casas decimais, corrigido na 0.32.65)',
      'corrigido', jsonb_build_object(
        'versao', '0.32.128',
        'pnl_sol', data->'pnl_sol',
        'pnl_pct', data->'pnl_pct',
        'sol_out', data->'sol_out',
        'gross_sol', data->'gross_sol',
        'best_pct', data->'best_pct',
        'reason', data->'reason'))
where real = false
  and data->>'symbol' = 'PEPE'
  and fechada_em >= timestamptz '2026-10-29 00:00:00+00'
  and fechada_em <  timestamptz '2026-10-31 00:00:00+00'
  and case when jsonb_typeof(data->'pnl_pct') = 'number' then (data->>'pnl_pct')::numeric >= 1900 else false end;
