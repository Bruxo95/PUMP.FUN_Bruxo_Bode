"""Página Novidades (app/novidades.json, só admin): toda entrega registra o que mudou, onde fica e o que faz.
Este teste impede publicar uma versão nova sem a entrada correspondente no topo da lista."""
import json
import os
import re

from app.version import VERSION
from tests.test_api import env  # noqa: F401  (fixture env)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_novidades_list_starts_with_current_version_and_is_complete():
    with open(os.path.join(ROOT, "app", "novidades.json"), encoding="utf-8") as f:
        itens = json.load(f)["itens"]
    assert itens and itens[0]["versao"] == VERSION.split(" ")[0], "acrescente a versão nova no topo de app/novidades.json"
    # 0.32.37 (pedido do dono): a versão nova diz o que foi mexido (front-end, back-end, banco, UI/UX, menu…)
    assert itens[0].get("area"), "rode: py scripts/changelog_area.py --current <versão> antes do commit"
    for x in itens:
        assert set(x) >= {"versao", "data", "tipo", "onde", "titulo", "oque"}
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", x["data"]) and x["tipo"] in {"novo", "melhoria", "segurança", "correção"}
        assert x["onde"].strip() and x["titulo"].strip() and len(x["oque"]) >= 20


def test_novidades_only_for_admin_and_not_public(env):
    from tests.test_api import UA, UB, tok
    c = env["c"]
    assert c.get("/api/admin/novidades", headers=tok(UB, "b@x.com")).status_code == 403     # usuário comum
    assert c.get("/api/admin/novidades").status_code == 401                                   # sem login
    r = c.get("/api/admin/novidades", headers=tok(UA))
    assert r.status_code == 200 and r.json()["itens"][0]["versao"] == VERSION.split(" ")[0]
    assert c.get("/static/novidades.json").status_code == 404                                 # fora da pasta pública



def test_changelog_has_time_of_each_version():
    """0.31.57: cada versão do Changelog traz a hora em que entrou (app/versoes.json)."""
    import json
    from app.versions_report import load
    when = {v["versao"]: v.get("inicio") for v in load()}
    first = json.load(open(os.path.join(ROOT, "app", "novidades.json"), encoding="utf-8"))["itens"][0]
    assert when.get(first["versao"]) and "T" in when[first["versao"]]
