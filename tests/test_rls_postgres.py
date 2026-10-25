"""Isolamento entre usuários NO BANCO: aplica as migrações num Postgres local (sem internet) com um "auth"
mínimo igual ao do Supabase e confere que o usuário A não vê nada do usuário B.

Precisa dos programas do Postgres (initdb/pg_ctl/psql). Se a máquina não tiver, o teste é pulado.
"""
import glob
import os
import shutil
import subprocess
import tempfile
import time

import pytest

UA = "11111111-1111-1111-1111-111111111111"
UB = "22222222-2222-2222-2222-222222222222"

SUPABASE_STUB = """
create role anon nologin; create role authenticated nologin; create role service_role nologin bypassrls;
create schema auth;
create table auth.users (id uuid primary key, email text, raw_user_meta_data jsonb default '{}'::jsonb);
create function auth.uid() returns uuid language sql stable as $$
  select nullif(current_setting('request.jwt.claims', true)::json ->> 'sub', '')::uuid $$;
grant usage on schema public, auth to anon, authenticated, service_role;
grant execute on function auth.uid() to anon, authenticated, service_role;
alter default privileges in schema public grant all on tables to anon, authenticated, service_role;
alter default privileges in schema public grant all on sequences to anon, authenticated, service_role;
"""


def _pg_bin():
    for d in [os.environ.get("PG_BIN", "")] + sorted(glob.glob("/usr/lib/postgresql/*/bin"), reverse=True):
        if d and os.path.exists(os.path.join(d, "initdb")):
            return d
    p = shutil.which("initdb")
    return os.path.dirname(p) if p else None


@pytest.fixture(scope="module")
def pg():
    bindir = _pg_bin()
    if not bindir:
        pytest.skip("Postgres local não instalado")
    tmp = tempfile.mkdtemp(prefix="pgrls")
    data, sock = os.path.join(tmp, "data"), tmp
    pre = []
    if os.name != "posix":
        pytest.skip("teste de RLS com Postgres local só roda em Linux/macOS")
    if os.geteuid() == 0:                       # o Postgres não roda como root
        import pwd
        user = "nobody"
        pw = pwd.getpwnam(user)
        os.chown(tmp, pw.pw_uid, pw.pw_gid)
        pre = ["runuser", "-u", user, "--"]
    run = lambda *a, **k: subprocess.run(pre + list(a), check=True, capture_output=True, text=True, **k)
    run(os.path.join(bindir, "initdb"), "-D", data, "-A", "trust", "-U", "postgres")
    run(os.path.join(bindir, "pg_ctl"), "-D", data, "-l", os.path.join(tmp, "pg.log"),
        "-o", f"-k {sock} -c listen_addresses=''", "-w", "start", timeout=60)

    def psql(sql, claims=None, role=None):
        pre_sql = ""
        if role:
            pre_sql += f"set role {role};"
        if claims:
            pre_sql += f"select set_config('request.jwt.claims', '{{\"sub\":\"{claims}\"}}', false);"
        r = subprocess.run(pre + [os.path.join(bindir, "psql"), "-h", sock, "-U", "postgres", "-d", "postgres",
                                  "-v", "ON_ERROR_STOP=1", "-At", "-q", "-c", pre_sql + sql],
                           capture_output=True, text=True)
        return r.returncode, (r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""), r.stderr

    rc, _, err = psql(SUPABASE_STUB)
    assert rc == 0, err
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for f in sorted(glob.glob(os.path.join(root, "supabase", "migrations", "*.sql"))):
        rc, _, err = psql(open(f).read())
        assert rc == 0, f"{os.path.basename(f)}: {err}"
    yield psql
    run(os.path.join(bindir, "pg_ctl"), "-D", data, "-m", "immediate", "stop")
    shutil.rmtree(tmp, ignore_errors=True)


def test_first_user_is_admin_and_profiles_are_created(pg):
    assert pg(f"insert into auth.users (id, email) values ('{UA}', 'a@x.com'), ('{UB}', 'b@x.com');")[0] == 0
    assert pg(f"select role from public.profiles where user_id='{UA}'")[1] == "admin"
    assert pg(f"select role from public.profiles where user_id='{UB}'")[1] == "user"
    assert pg("select count(*) from public.user_settings")[1] == "2"


def test_rls_user_sees_only_own_rows(pg):
    for u, tag in ((UA, "A"), (UB, "B")):
        sql = f"""
        insert into public.pump_positions (id, user_id, real, data) values ('p{tag}', '{u}', false, '{{"s":"{tag}"}}');
        insert into public.pump_trades (id, user_id, real, data) values ('t{tag}', '{u}', false, '{{"s":"{tag}"}}');
        insert into public.pump_lists (user_id, tipo, wallet) values ('{u}', 'manual', 'W{tag}');
        insert into public.pump_feed (user_id, data) values ('{u}', '{{"s":"{tag}"}}');
        insert into public.audit_log (user_id, acao) values ('{u}', 'teste {tag}');
        insert into public.user_secrets (user_id, nome, valor_criptografado) values ('{u}', 'rpc_url', 'cifra{tag}');
        """
        assert pg(sql)[0] == 0
    for t in ("pump_positions", "pump_trades", "pump_lists", "pump_feed", "audit_log", "profiles", "user_settings"):
        rc, out, err = pg(f"select count(*) from public.{t}", claims=UA, role="authenticated")
        assert rc == 0 and out == "1", (t, out, err)
        rc, out, _ = pg(f"select count(*) from public.{t} where user_id='{UB}'", claims=UA, role="authenticated")
        assert out == "0", t
        rc, out, _ = pg(f"select count(*) from public.{t}", role="anon")          # sem login: nada
        assert rc != 0 or out == "0", t


def test_browser_cannot_write_or_read_encrypted_secret(pg):
    rc, out, _ = pg("select nome from public.user_secrets", claims=UA, role="authenticated")
    assert rc == 0 and out == "rpc_url"
    rc, _, err = pg("select valor_criptografado from public.user_secrets", claims=UA, role="authenticated")
    assert rc != 0 and "permission denied" in err
    rc, _, err = pg(f"insert into public.pump_positions (id, user_id, data) values ('x', '{UA}', '{{}}')",
                    claims=UA, role="authenticated")
    assert rc != 0
    rc, _, err = pg(f"update public.profiles set role='admin' where user_id='{UB}'", claims=UB, role="authenticated")
    assert rc != 0
    assert pg(f"select role from public.profiles where user_id='{UB}'")[1] == "user"


def test_feed_trim_keeps_last_n(pg):
    pg(f"insert into public.pump_feed (user_id, data) select '{UA}', jsonb_build_object('i', g) from generate_series(1, 30) g")
    assert pg(f"select public.trim_pump_feed('{UA}', 10)")[0] == 0
    assert pg(f"select count(*) from public.pump_feed where user_id='{UA}'")[1] == "10"
    assert pg(f"select count(*) from public.pump_feed where user_id='{UB}'")[1] == "1"   # o do outro fica
    rc, _, _ = pg(f"select public.trim_pump_feed('{UB}', 0)", claims=UA, role="authenticated")
    assert rc != 0                                   # o navegador não chama esta função


def test_system_keys_table_is_closed_to_browsers(pg):
    assert pg("insert into public.app_secrets (nome, valor_criptografado) values ('jupiter_api_key', 'cifra')")[0] == 0
    for role in ("authenticated", "anon"):
        rc, out, err = pg("select count(*) from public.app_secrets", claims=UA, role=role)
        assert rc != 0 and "permission denied" in err, role
