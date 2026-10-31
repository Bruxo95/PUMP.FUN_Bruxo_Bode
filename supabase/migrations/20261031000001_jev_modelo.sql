-- 0.32.106: versão do Jev que respondeu cada pergunta (a resposta traz `model`). Sem isto os estudos misturariam versões.
alter table public.jev_decisions add column if not exists modelo text;
