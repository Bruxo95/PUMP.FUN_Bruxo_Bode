"""Página Novidades (web/novidades.json): toda entrega registra o que mudou, onde fica e o que faz.
Este teste impede publicar uma versão nova sem a entrada correspondente no topo da lista."""
import json
import os
import re

from app.version import VERSION

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")


def test_novidades_list_starts_with_current_version_and_is_complete():
    with open(os.path.join(WEB, "novidades.json"), encoding="utf-8") as f:
        itens = json.load(f)["itens"]
    assert itens and itens[0]["versao"] == VERSION.split(" ")[0], "acrescente a versão nova no topo de web/novidades.json"
    for x in itens:
        assert set(x) >= {"versao", "data", "tipo", "onde", "titulo", "oque"}
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", x["data"]) and x["tipo"] in {"novo", "melhoria", "segurança", "correção"}
        assert x["onde"].strip() and x["titulo"].strip() and len(x["oque"]) >= 20
