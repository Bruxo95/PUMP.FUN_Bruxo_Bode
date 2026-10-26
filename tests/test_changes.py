"""Relatórios em PDF, texto para IA e relatórios das mudanças feitas pela IA (0.31.7)."""
import time

import pytest

from tests.test_api import UA, UB, env, tok  # noqa: F401  (fixture env)


def test_every_change_report_in_the_repo_is_valid():
    """Toda IA que corrige algo deixa app/relatorios_ia/AAAA-MM-DD-versao.md no formato certo (regra do CLAUDE.md)."""
    from app.changes import load
    ch = load()
    assert ch and not [c for c in ch if c.get("erro")], [c.get("erro") for c in ch if c.get("erro")]
    assert all(c["nome"].startswith(c["data"]) and c["nome"].endswith(c["versao"]) for c in ch)


def test_parse_and_realized():
    from app.changes import parse, realized
    with pytest.raises(ValueError):
        parse("sem cabeçalho", "x")
    with pytest.raises(ValueError):
        parse("---\nversao: 1\n---\ntexto", "x")
    c = parse("---\nversao: 0.40.0\ndata: 2026-10-10\nautor: IA\nbaseado_em: relatório de 2026-10-09\nprojecao_sol_dia: +0,05\n"
              "projecao_texto: stop mais largo\n---\n# Feito\nmudou o stop", "2026-10-10-0.40.0")
    assert c["projecao_sol_dia"] == 0.05 and c["texto"].startswith("# Feito")
    days = [{"dia": "2026-10-08", "pnl_sol": -0.1}, {"dia": "2026-10-09", "pnl_sol": -0.3},
            {"dia": "2026-10-10", "pnl_sol": 9.0}, {"dia": "2026-10-11", "pnl_sol": 0.1}]
    r = realized(c, days)
    assert r["antes_sol_dia"] == -0.2 and r["depois_sol_dia"] == 0.1 and r["diferenca_sol_dia"] == 0.3 and r["dias_depois"] == 1


def test_pdf_and_ai_text_of_the_daily_report(env):
    from tests.test_daily import _trades
    c, hub = env["c"], env["hub"]
    c.get("/api/pump", headers=tok(UA))
    _trades(hub.engines[UA], time.time())
    r = c.get("/api/pump/daily/pdf", headers=tok(UA))
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content.startswith(b"%PDF-1.4")
    assert b"%%EOF" in r.content[-20:] and "attachment" in r.headers["content-disposition"]
    t = c.get("/api/pump/daily/ai", headers=tok(UA))
    assert t.status_code == 200 and "Instruções para a IA" in t.text and "app/relatorios_ia" in t.text and "Acerto do dia" in t.text
    assert c.get("/api/pump/daily/pdf", headers=tok(UB, "b@x.com")).status_code == 403


def test_changes_route_lists_reports_with_pdf(env):
    c = env["c"]
    r = c.get("/api/pump/changes", headers=tok(UA)).json()
    first = r["changes"][0]
    assert first["versao"] and "real" in first and "texto" not in first
    one = c.get("/api/pump/changes/" + first["nome"], headers=tok(UA)).json()
    assert one["texto"]
    p = c.get("/api/pump/changes/" + first["nome"] + "?pdf=1", headers=tok(UA))
    assert p.status_code == 200 and p.content.startswith(b"%PDF")
    assert c.get("/api/pump/changes/nao-existe", headers=tok(UA)).status_code == 404
    assert c.get("/api/pump/changes", headers=tok(UB, "b@x.com")).status_code == 403


def test_pdf_writer_handles_accents_and_pages():
    from app.pdf import make
    b = make([("title", "Relatório"), ("p", "ação → coração −0,27 ≥ 39% " * 50)] * 40, "teste")
    assert b.startswith(b"%PDF-1.4") and b.count(b"/Type /Page ") >= 2
