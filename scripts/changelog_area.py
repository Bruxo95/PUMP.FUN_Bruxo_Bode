"""Área de cada entrega no Changelog (0.32.37, pedido do dono em 2026-10-29: "dizer se foi front-end, back-end, UI/UX,
banco, menu… e qual código melhorou").

A partir dos arquivos mudados em cada versão, monta:
- `area`: etiquetas curtas (Back-end (Python), Front-end (JavaScript), UI/UX (telas), Visual (CSS), Menu, Banco de dados,
  Motor de trades, Aprendizado, Monitor da Solana, Execução real, Testes, Automação, Documentação);
- `arquivos`: os principais arquivos de código mexidos (sem testes, docs e arquivos gerados).

Uso:
  py scripts/changelog_area.py --backfill        preenche as versões antigas do app/novidades.json pelo histórico do Git
  py scripts/changelog_area.py --current V       preenche a versão V (a do topo) pelos arquivos mudados agora (antes do commit)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOV = os.path.join(ROOT, "app", "novidades.json")
SKIP = ("app/novidades.json", "app/versoes.json", "app/version.py", "CLAUDE.md", "docs/DEPENDENCIAS.md",
        "docs/dependencias/inventario.json", "output/pdf/relatorio-dependencias.pdf")
MODULES = {  # arquivo do back-end → área específica
    "app/pumpfun.py": "Motor de trades", "app/monitor.py": "Monitor da Solana", "app/txguard.py": "Execução real",
    "app/jupiter.py": "Execução real", "app/autolearn.py": "Aprendizado", "app/basegeral.py": "Aprendizado",
    "app/evolucoes.py": "Aprendizado", "app/autotune.py": "Aprendizado", "app/ghosts.py": "Aprendizado",
    "app/poslearn.py": "Aprendizado", "app/raiox.py": "Aprendizado", "app/calls.py": "Calls quentes",
    "app/explore.py": "Explorar", "app/daily.py": "Relatórios", "app/reports.py": "Relatórios", "app/robotlog.py": "Logs",
    "app/api.py": "API", "app/auth.py": "Segurança", "app/crypto.py": "Segurança", "app/settings.py": "Configurações",
}
ORDER = ["Back-end (Python)", "Front-end (JavaScript)", "UI/UX (telas)", "Visual (CSS)", "Menu", "Banco de dados",
         "Motor de trades", "Execução real", "Explorar", "Aprendizado", "Calls quentes", "Monitor da Solana", "Relatórios",
         "Logs", "Configurações", "API", "Segurança", "Testes", "Automação", "Documentação"]


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout


def classify(files: list[str], menu: bool = False) -> tuple[list[str], list[str]]:
    area, code = set(), []
    for f in files:
        f = f.replace("\\", "/")
        if f in SKIP or f.startswith("app/relatorios_ia/"):
            continue
        if f.startswith("app/") and f.endswith(".py"):
            area.add("Back-end (Python)")
            if f in MODULES:
                area.add(MODULES[f])
            code.append(f.split("/")[-1])
        elif f.startswith("web/") and f.endswith(".js"):
            area.add("Front-end (JavaScript)")
            code.append(f.split("/")[-1])
        elif f.startswith("web/") and f.endswith(".html"):
            area.add("UI/UX (telas)")
            code.append(f.split("/")[-1])
        elif f.startswith("web/") and f.endswith(".css"):
            area.add("Visual (CSS)")
            code.append(f.split("/")[-1])
        elif f.startswith("supabase/migrations/"):
            area.add("Banco de dados")
        elif f.startswith("tests/"):
            area.add("Testes")
        elif f.startswith((".github/", "scripts/", "Dockerfile", "deploy/")):
            area.add("Automação")
        elif f.startswith("docs/") or f.endswith(".md"):
            area.add("Documentação")
    if menu:
        area.add("Menu")
    return [a for a in ORDER if a in area], list(dict.fromkeys(code))[:8]


def _menu_changed(diff: str) -> bool:
    """Mexeu no menu lateral: linha adicionada/removida com um link de menu (data-v=) no app.html."""
    return any(re.match(r"^[+-]\s*<a href=\"#[a-z]+\"[^>]*data-v=", ln) for ln in diff.splitlines())


def _load() -> dict:
    with open(NOV, encoding="utf-8") as f:
        return json.load(f)


def _save(d: dict) -> None:
    lines = ['{', '  "_regra": ' + json.dumps(d.get("_regra", ""), ensure_ascii=False) + ',', '  "itens": [']
    itens = d["itens"]
    for i, x in enumerate(itens):
        lines.append("    " + json.dumps(x, ensure_ascii=False) + ("," if i < len(itens) - 1 else ""))
    lines += ["  ]", "}", ""]
    with open(NOV, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))


def backfill() -> int:
    d = _load()
    log = _git("log", "--format=%H%x09%s")
    by_ver: dict[str, list[str]] = {}
    for line in log.splitlines():
        sha, _, subj = line.partition("\t")
        m = re.match(r"Vers[aã]o (\d+\.\d+\.\d+)", subj)
        if m:
            by_ver.setdefault(m.group(1), []).append(sha)
    n = 0
    for x in d["itens"]:
        if x.get("area"):
            continue
        shas = by_ver.get(x["versao"]) or []
        files, menu = [], False
        for sha in shas:
            files += _git("show", "--name-only", "--format=", sha).split()
            menu = menu or _menu_changed(_git("show", "--format=", sha, "--", "web/app.html"))
        if not files:
            continue
        x["area"], x["arquivos"] = classify(files, menu)
        n += 1
    _save(d)
    return n


def current(ver: str) -> list[str]:
    files = _git("diff", "--name-only", "HEAD").split() + _git("ls-files", "--others", "--exclude-standard").split()
    menu = _menu_changed(_git("diff", "HEAD", "--", "web/app.html"))
    d = _load()
    top = d["itens"][0]
    if top["versao"] != ver:
        raise SystemExit(f"a versão do topo é {top['versao']}, não {ver}")
    top["area"], top["arquivos"] = classify(files, menu)
    _save(d)
    return top["area"]


if __name__ == "__main__":
    if sys.argv[1:2] == ["--backfill"]:
        print("versões preenchidas:", backfill())
    elif sys.argv[1:2] == ["--current"] and len(sys.argv) > 2:
        print("área:", ", ".join(current(sys.argv[2])))
    else:
        print(__doc__)
