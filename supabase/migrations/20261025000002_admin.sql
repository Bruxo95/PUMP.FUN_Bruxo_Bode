-- Gestão de usuários pelo admin: bloquear conta e saber quando cada um usou o painel pela última vez.
-- (Quem muda isto é só o backend, com a service key; o navegador continua sem permissão de escrita.)
alter table public.profiles add column if not exists bloqueado boolean not null default false;
alter table public.profiles add column if not exists ultimo_acesso timestamptz;
