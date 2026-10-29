-- 0.32.38 (pedido do dono em 29/10: "isso tem que ser estudado e aprendido pela IA"): as decisões do estudo automático passam a
-- incluir o resultado DE VERDADE de copiar cada carteira: parou_de_copiar, sugere_parar e copiou_lucro. Só troca a regra de
-- valores aceitos da coluna acao (nenhum dado é apagado).
alter table public.study_auto_log drop constraint if exists study_auto_log_acao_check;
alter table public.study_auto_log add constraint study_auto_log_acao_check
  check (acao in ('adicionou', 'aprovou', 'descartou', 'parou_de_copiar', 'sugere_parar', 'copiou_lucro'));
