-- 0.32.2 (pedido do dono em 2026-10-28: "siga o que a outra IA diz", caminho 1): usuário de banco SÓ LEITURA para a IA
-- consultar trades, sombras, calls e logs sem print. Sem senha aqui: nasce sem poder entrar (NOLOGIN); o dono define a senha
-- no SQL Editor do Supabase (alter role leitor_ia with login password '...'). Ninguém escreve: só SELECT, transação
-- somente leitura e tempo máximo de 30 s por consulta. Fora: user_secrets, app_secrets e audit_log; de profiles só
-- user_id, nome, role e bloqueado (sem e-mail). Para desfazer: alter role leitor_ia nologin.
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'leitor_ia') then
    create role leitor_ia nologin noinherit nocreatedb nocreaterole;
  end if;
end $$;

alter role leitor_ia set default_transaction_read_only = on;
alter role leitor_ia set statement_timeout = '30s';
alter role leitor_ia set idle_in_transaction_session_timeout = '60s';
grant usage on schema public to leitor_ia;

do $$
declare
  t text;
begin
  foreach t in array array[
    'pump_trades', 'pump_positions', 'pump_feed', 'pump_lists', 'auto_trades', 'base_shadows', 'base_snapshots',
    'base_log', 'base_evolutions', 'calls', 'robot_log', 'robot_daily', 'explore_cycles', 'daily_report',
    'learning_daily', 'ghost_stats', 'auto_tune_log', 'study_auto_log', 'study_wallets', 'study_positions',
    'wallet_trades', 'elite_signals', 'token_xray', 'token_life', 'lab_state', 'market_hourly', 'creator_stats',
    'blacklist', 'config_offers', 'config_compare_reports', 'user_settings', 'api_usage', 'app_migracoes'
  ] loop
    if to_regclass('public.' || t) is not null then
      execute format('grant select on public.%I to leitor_ia', t);
      if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = t and policyname = 'leitor_ia: ler') then
        execute format('create policy "leitor_ia: ler" on public.%I for select to leitor_ia using (true)', t);
      end if;
    end if;
  end loop;
end $$;

grant select (user_id, nome, role, bloqueado) on public.profiles to leitor_ia;
do $$
begin
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'profiles' and policyname = 'leitor_ia: ler') then
    create policy "leitor_ia: ler" on public.profiles for select to leitor_ia using (true);
  end if;
end $$;
