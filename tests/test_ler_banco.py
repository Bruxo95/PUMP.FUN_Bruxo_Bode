"""0.32.2: leitor só leitura do banco (scripts/ler_banco.py) — conta SCRAM do RFC 7677 e recusa de escrita, sem rede."""
import importlib.util
import os

import pytest

_p = os.path.join(os.path.dirname(__file__), "..", "scripts", "ler_banco.py")
_s = importlib.util.spec_from_file_location("ler_banco", _p)
lb = importlib.util.module_from_spec(_s)
_s.loader.exec_module(lb)


def test_scram_matches_rfc7677_vector():
    sf = "r=rOprNGfwEbeRWgbNEkqO%hvYDpWUa2RaTCAfuxFIlj)hNlF$k0,s=W22ZaJ0SNY7soEsUEjb6gQ==,i=4096"
    final, server = lb.scram_final("pencil", "n=user,r=rOprNGfwEbeRWgbNEkqO", sf)
    assert final.endswith("p=dHzbZapWIk4jUhN+Ute9ytag9zjfMHgsqmmiz7AndVQ=")
    assert server == "6rriTRBi23WpRR/wtup+mMhUZUn/dB5nLTJRsjl95G4="


def test_only_queries_are_accepted():
    c = object.__new__(lb.Conexao)
    for sql in ("delete from pump_trades", "update x set a=1", "select 1; drop table x", "insert into x values (1)"):
        with pytest.raises(lb.DBErro):
            c.consulta(sql)
    assert lb.SO_CONSULTA.match("  WITH a as (select 1) select * from a")


def test_env_file_missing_gives_clear_message(tmp_path):
    with pytest.raises(lb.DBErro, match="PUMP_DB_URL"):
        lb.ler_env(str(tmp_path / "nao-existe.env"))
