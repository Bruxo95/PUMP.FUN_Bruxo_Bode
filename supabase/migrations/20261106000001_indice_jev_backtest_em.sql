-- 0.32.240: o arquivo (app/arquivo.py) e o estudo do passado do Jev (hub.jev_bt_cases) leem jev_backtest ordenado por `em`.
-- Só havia índice em (fonte, em): a consulta ordenava a tabela inteira (jsonb pesado) e caía no limite de tempo (erro 57014).
-- Regra (docs/ARQUITETURA.md): toda tabela que vai para o arquivo precisa de índice na coluna de hora.
create index if not exists jev_backtest_em on public.jev_backtest using btree (em);
