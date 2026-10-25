"""Inventario documental: --refresh gera JSON/Markdown/PDF; --check usa so a stdlib.

Nao instala, importa nem resolve dependencias da aplicacao. O PDF usa ReportLab
somente no refresh, em runtime preexistente ou ambiente isolado aprovado.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
JSON_PATH = ROOT / "docs/dependencias/inventario.json"
MD_PATH = ROOT / "docs/DEPENDENCIAS.md"
PDF_PATH = ROOT / "output/pdf/relatorio-dependencias.pdf"
SNAPSHOT = "docs/auditoria/2026-10-25/pacotes-testados.json"
AUDIT_META = "docs/auditoria/2026-10-25/identificacao-auditoria.json"
TRIAGE = "docs/auditoria/2026-10-25/triagem-scanners.json"
SECURITY = "docs/dependencias/triagem-seguranca.json"
ISSUER = "Claude Code, modelo Claude Opus 5.5 (claude-opus-5-5)"
FIXED_SOURCES = [
    "requirements.txt", "requirements-test.txt", "constraints.txt", "app/version.py", "Dockerfile", ".dockerignore", ".github/workflows/imagem.yml",
    "web/index.html", "web/app.html", SNAPSHOT, AUDIT_META, TRIAGE,
    "scripts/inventario_dependencias.py", "scripts/pdf_dependencias.py",
    "scripts/coletar_risco_dependencias.py", "scripts/verificar_triagem_dependencias.py",
    "docs/dependencias/POLITICA-DE-DEPENDENCIAS.md", "docs/dependencias/pesquisa-malware.md", SECURITY,
    "docs/dependencias/revisoes-manuais.json",
]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8").replace("\r\n", "\n")


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def dump(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def digest(data) -> str:
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def sources() -> dict[str, str]:
    # Um novo manifesto nao pode passar silenciosamente sem ser catalogado.
    known = {"requirements.txt", "requirements-test.txt"}
    manifest_names = {"pyproject.toml", "Pipfile", "Pipfile.lock", "poetry.lock", "uv.lock",
                      "package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock"}
    ignored = {".git", ".venv", "node_modules", "tmp", "output"}
    for path in ROOT.rglob("*"):
        if not path.is_file() or ignored.intersection(path.relative_to(ROOT).parts):
            continue
        rel = path.relative_to(ROOT).as_posix()
        is_manifest = path.name in manifest_names or re.fullmatch(r"requirements.*\.txt", path.name)
        if is_manifest and rel not in known:
            raise ValueError(f"Novo manifesto precisa ser catalogado pelo inventario: {rel}")
    return {p: hashlib.sha256(text(p).encode()).hexdigest() for p in sorted(FIXED_SOURCES)}


def requirement(line: str) -> dict:
    match = re.fullmatch(r"([A-Za-z0-9_.-]+)(\[[^\]]+\])?(.*)", line.strip())
    if not match:
        raise ValueError(f"Declaracao nao suportada; revisar parser: {line}")
    return {"name": match[1], "extras": match[2] or "", "constraint": match[3] or "não fixada"}


def inventory(date: str, reference: str, pdf_generator_version: str) -> dict:
    snapshot = json.loads(text(SNAPSHOT))
    audit = json.loads(text(AUDIT_META))
    triage = json.loads(text(TRIAGE))
    observed = {canonical(p["name"]): p["version"] for p in snapshot["packages"]}
    runtime = []
    for line in text("requirements.txt").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            row = requirement(line)
            row["observed_version"] = observed.get(canonical(row["name"]))
            runtime.append(row)
    workflow = text(".github/workflows/imagem.yml")
    test_packages = {}
    for line in text("requirements-test.txt").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            row = requirement(line)
            row["observed_version"] = observed.get(canonical(row["name"]))
            if canonical(row["name"]) not in {canonical(p["name"]) for p in runtime}:
                test_packages[canonical(row["name"])] = row
    javascript = {}
    fonts = set()
    for path in ("web/index.html", "web/app.html"):
        html = text(path)
        for url in re.findall(r'<script[^>]+src="(https://[^\"]+)"', html):
            package = re.search(r"/npm/((?:@[^/]+/)?[^@/]+)@([^/]+)", url)
            name, version = (package[1], package[2]) if package else (url, "não declarada")
            row = javascript.setdefault(name, {"name": name, "version": version, "locations": [],
                                               "integrity": []})
            if row["version"] != version:
                raise ValueError(f"Versoes JS divergentes entre paginas: {name}")
            row["locations"].append(path)
            for tag in re.findall(r"<script[^>]+>", html):
                if url in tag:
                    sri = re.search(r'integrity="([^\"]+)"', tag)
                    if sri and sri[1] not in row["integrity"]:
                        row["integrity"].append(sri[1])
        fonts.update(name.replace("+", " ") for name in re.findall(r"family=([^:&\"]+)", html))
    assignments = ast.parse(text("app/version.py")).body
    version = next(ast.literal_eval(n.value) for n in assignments if isinstance(n, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == "VERSION" for t in n.targets))
    direct_names = {canonical(p["name"]) for p in runtime}
    test_names = set(test_packages)
    packages = []
    for row in snapshot["packages"]:
        name = canonical(row["name"])
        category = "Direta de execução" if name in direct_names else (
            "Direta de teste" if name in test_names else "Outra do ambiente de testes")
        packages.append({**row, "category": category})
    actions = sorted({(m[1], m[2]) for m in re.finditer(r"uses:\s*([^@\s]+)@([^\s#]+)", workflow)})
    base_image = re.search(r"^FROM\s+(\S+)", text("Dockerfile"), re.M)[1]
    security = json.loads(text(SECURITY))
    identifiers = [(p["ecosystem"], canonical(p["name"]), p["version"]) for p in security["packages"]]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Triagem contem versoes duplicadas.")
    for row in snapshot["packages"]:
        if ("PyPI", canonical(row["name"]), row["version"]) not in identifiers:
            raise ValueError(f"Versao historica sem triagem no relatorio: {row['name']} {row['version']}")
    for row in javascript.values():
        if ("npm", canonical(row["name"]), row["version"]) not in identifiers:
            raise ValueError(f"JavaScript novo sem triagem registrada: {row['name']} {row['version']}")
    risk_counts = {level: sum(p["classification"]["level"] == level for p in security["packages"])
                   for level in ("favorable", "attention", "danger")}
    return {
        "schema_version": 2, "document_revision": "2.0", "generated_date": date,
        "timezone": "Europe/Dublin", "repository_reference": reference,
        "application_version": version, "reviewer": audit["reviewer"], "issuer": ISSUER,
        "source_sha256": sources(), "python_runtime_direct": runtime,
        "security_review": security,
        "python_test_direct": list(test_packages.values()),
        "javascript_runtime_direct": list(javascript.values()),
        "python_observed_snapshot": {"date": audit["audit_date"], "commit": audit["code_commit_audited"],
            "application_version": audit["application_version_audited"], "python": snapshot["python"],
            "status": "Histórico: ambiente local removido; não representa produção nem instalação atual.",
            "packages": packages},
        "toolchain": {"docker_base": base_image, "ci_python": re.search(r'python-version:\s*"([^\"]+)"', workflow)[1],
            "github_actions": [{"name": n, "ref": ref} for n, ref in actions],
            "fonts": sorted(fonts), "pdf_generator": {"name": "ReportLab", "version": pdf_generator_version,
                "role": "Ferramenta opcional de documentação, preexistente no runtime do app; não instalada nesta tarefa."}},
        "audit_tools_removed": [{"name": "Bandit", "version": triage["bandit"]["version"]},
            {"name": "pip-audit", "version": triage["pip_audit"]["version"]},
            {"name": "Gitleaks", "version": triage["gitleaks"]["version"]}],
        "counts": {"python_runtime_direct": len(runtime), "javascript_runtime_direct": len(javascript),
            "runtime_direct_total": len(runtime) + len(javascript), "python_test_direct": len(test_packages),
            "python_observed_snapshot": len(packages), "other_observed_python": sum(
                p["category"] == "Outra do ambiente de testes" for p in packages),
            "github_actions_unique": len(actions), "external_fonts": len(fonts)},
        "security_counts": {"reviewed": len(security["packages"]), **risk_counts},
    }


def markdown(data: dict) -> str:
    c, snap, tool = data["counts"], data["python_observed_snapshot"], data["toolchain"]
    lines = ["# Inventário de dependências - PUMP FUN COPY", "",
        f"Emissão: **{data['generated_date']}**; revisão documental **{data['document_revision']}**.",
        f"Aplicação: **{data['application_version']}**.",
        f"Referência Git na emissão: `{data['repository_reference']}`; fontes locais identificadas por SHA-256 no JSON.",
        f"Emissão: {data['issuer']}. Auditoria original: OpenAI Codex, família GPT-6.", "",
        "## Quantidade e significado", "",
        f"- **{c['runtime_direct_total']} dependências diretas de execução:** {c['python_runtime_direct']} Python e {c['javascript_runtime_direct']} JavaScript.",
        f"- **{c['python_test_direct']} dependência direta de teste**, declarada separadamente no CI.",
        f"- **{c['python_observed_snapshot']} pacotes Python no snapshot histórico:** inclui os diretos, teste e {c['other_observed_python']} outros pacotes.",
        f"- **{c['github_actions_unique']} Actions únicas** e **{c['external_fonts']} fontes externas**, contabilizadas à parte.",
        "- Não somar o snapshot aos diretos: os mesmos pacotes apareceriam duas vezes.",
        "- Não há dependências deste projeto instaladas atualmente no Windows principal; o ambiente observado foi removido.", "",
        "## Execução Python: declaração versus versão observada", "",
        "| Pacote | Regra em requirements.txt | Versão histórica observada |", "|---|---|---|"]
    for row in data["python_runtime_direct"]:
        lines.append(f"| {row['name']}{row['extras']} | `{row['constraint']}` | {row['observed_version'] or 'Não registrada'} |")
    lines += ["", "Extras como [standard] e [crypto] ativam dependências adicionais; não são pacotes separados.",
        "As faixas declaradas não fixam versões exatas. A coluna observada é histórica, não um lockfile.", "",
        "## Testes e JavaScript", "", "| Tipo | Nome | Regra/versão declarada | Versão histórica |", "|---|---|---|---|"]
    for row in data["python_test_direct"]:
        lines.append(f"| Teste Python | {row['name']}{row['extras']} | {row['constraint']} | {row['observed_version'] or 'Não registrada'} |")
    for row in data["javascript_runtime_direct"]:
        lines.append(f"| JavaScript de execução | {row['name']} | {row['version']} | Não se aplica ao snapshot Python |")
    lines += ["", "A biblioteca JS aparece nos dois HTMLs, mas é contada uma vez. Seu SRI fica registrado no JSON.", "",
        "## Snapshot completo de Python", "",
        f"Origem: `{SNAPSHOT}`, auditoria de {snap['date']}, aplicação {snap['application_version']},",
        f"commit `{snap['commit']}`, Python {snap['python']}.", "",
        f"**{snap['status']}**", "", "| Nome | Versão | Classificação no inventário |", "|---|---|---|"]
    lines += [f"| {p['name']} | {p['version']} | {p['category']} |" for p in snap["packages"]]
    lines += ["", "Outros pacotes podem servir à execução ou aos testes; esta classificação não afirma uso exclusivo em produção.",
        "Dependências transitivas de JavaScript e pacotes de sistema da imagem não têm inventário completo nesta emissão.", "",
        "## Ambiente, CI e recursos externos", "", f"- Base Docker: `{tool['docker_base']}` (tag mutável).",
        f"- Python no CI: `{tool['ci_python']}`; patch não fixado.",
        f"- Fontes: {', '.join(tool['fonts'])}; versões não declaradas no código.",
        f"- Geração opcional do PDF: {tool['pdf_generator']['name']} {tool['pdf_generator']['version']}. {tool['pdf_generator']['role']} Fora da contagem de execução da aplicação.", "",
        "| GitHub Action | Referência declarada |", "|---|---|"]
    lines += [f"| {p['name']} | {p['ref']} |" for p in tool["github_actions"]]
    lines += ["", "## Ferramentas da auditoria, já removidas", "", "Fora da contagem de execução e do snapshot de 34 pacotes:", ""]
    lines += [f"- {p['name']} {p['version']}." for p in data["audit_tools_removed"]]
    lines += ["", "## Padrão de atualização", "",
        "1. Ao adicionar, remover ou atualizar dependência, registrar nome, finalidade, versão/faixa e origem antes da entrega.",
        "2. Atualizar este Markdown, o JSON e o PDF juntos. Preservar o snapshot de auditoria original.",
        "3. Versão exata nova só pode vir de manifesto fixo ou inventário capturado em ambiente isolado/remoto aprovado; não adivinhar.",
        "4. Não instalar dependências no Windows principal para atualizar o documento. O gerador lê os arquivos, sem instalar/resolver pacotes.",
        "5. O CI executa o verificador sem dependências externas e reprova documentos desatualizados. Isso exige regeneração; não faz commit automático.",
        "6. Antes de instalar, o gate confere versão triada, avisos atuais, origem e hash; a instalação usa uma relação exata temporária com hashes.", "",
        "Verificar, com Python padrão já disponível:", "", "```text", "python scripts/inventario_dependencias.py --check", "```", "",
        "Regenerar com ReportLab já disponível em runtime confiável ou ambiente isolado aprovado, usando a data local:", "",
        "```text", "python scripts/inventario_dependencias.py --refresh --date AAAA-MM-DD", "```", "",
        "Se o gerador de PDF não estiver disponível, não instalar automaticamente no Windows; usar o ambiente aprovado.", "",
        "## Arquivos e rastreabilidade", "",
        "- Dados e hashes: `docs/dependencias/inventario.json`.",
        "- PDF: `output/pdf/relatorio-dependencias.pdf`.",
        "- Geradores: `scripts/inventario_dependencias.py` e `scripts/pdf_dependencias.py`.",
        "- A emissão usa fontes locais e o snapshot histórico; não consultou o ambiente efetivo de produção.",
        "- O JSON inclui o hash do PDF para detectar divergência entre os artefatos.", ""]
    security, counts = data["security_review"], data["security_counts"]
    labels = {"favorable": "Favorável", "attention": "Atenção", "danger": "Perigo"}
    def number(value):
        return "N/D" if value is None else f"{value:,}".replace(",", ".")
    lines += ["## Triagem de malware, vulnerabilidades e procedência", "",
        f"Coleta: **{security['collected_at']}**. {counts['reviewed']} versões/ferramentas avaliadas: "
        f"**{counts['favorable']} favoráveis, {counts['attention']} em atenção, {counts['danger']} em perigo**.", "",
        f"O conjunto inclui os 34 pacotes históricos Python, as versões fixadas em constraints.txt, a biblioteca JS, o gerador PDF preexistente e três ferramentas de auditoria removidas. Não são {counts['reviewed']} dependências de execução.",
        "Favorável significa consulta concluída sem alerta aplicável no escopo e sinais de origem; não garante ausência de malware nem autoriza instalação no Windows.",
        "Atenção significa verificação incompleta ou origem não confirmada neste método; não é acusação de malware. Perigo exige alerta/motivo aplicável registrado.", "",
        "### Popularidade e acompanhamento", "",
        "Downloads são eventos do projeto, todas as versões, e não instalações ou pessoas únicas. Estrelas e assinantes são contas do repositório GitHub, não garantia de segurança.",
        "PyPI/npm: período mensal informado pelo provedor; Gitleaks: acumulado dos arquivos da release, identificado com *. N/D é indisponível, não zero.", "",
        "| Pacote / versão | Papel | Downloads no período | Estrelas | Assinantes | Triagem |", "|---|---|---|---|---|---|"]
    for row in security["packages"]:
        dl = row["popularity"]["downloads"]
        gh = row["popularity"]["github"]
        marker = "*" if row["ecosystem"] == "GitHubRelease" else ""
        lines.append(f"| {row['name']} {row['version']} | {row['role']} | {number(dl.get('count'))}{marker} | {number(gh.get('stars'))} | {number(gh.get('subscribers'))} | {labels[row['classification']['level']]} |")
    lines += ["", "### Pendências e motivos", ""]
    for row in security["packages"]:
        if row["classification"]["level"] != "favorable" or row["classification"].get("manual_review"):
            lines.append(f"- **{row['name']} {row['version']} ({labels[row['classification']['level']]}):** " + " ".join(row["classification"]["reasons"]))
    lines += ["", "### Procedimento obrigatório antes de cada instalação", "",
        "- Versões exatas ficam em constraints.txt. Nome/versão não triados, alerta atual (OSV/PyPI consultados a cada build) ou consulta indisponível bloqueiam a instalação.",
        "- Resolver somente metadados de wheels em CI/imagem, sem instalar nem executar sdists; validar candidatos com OSV e registro ao vivo.",
        "- Instalar apenas versões e hashes aprovados para aquela execução, sem resolver novas dependências durante a instalação.",
        "- JavaScript externo exige versão fixa, registro npm triado e SRI; o gate não substitui auditoria do código do bundle.",
        "- Pendências que o coletor não resolve sozinho (ex.: release sem link de repositório) recebem revisão manual registrada em docs/dependencias/revisoes-manuais.json; revisão manual nunca anula alerta.",
        "- Pacotes do SO/base Docker e Actions por tags continuam exigindo análise própria; não estão certificados por esta triagem Python/npm.",
        "- O coletor consulta JSON/APIs, sem baixar/importar/executar os pacotes. Popularidade nunca é motivo único de aprovação.", "",
        "Política completa: `docs/dependencias/POLITICA-DE-DEPENDENCIAS.md`. Pesquisa de relatos: `docs/dependencias/pesquisa-malware.md`.",
        "Fontes, períodos e datas por pacote: `docs/dependencias/triagem-seguranca.json`.", "",
        "Atualizar a coleta antes de mudar versão, usando apenas Python padrão e acesso às APIs:", "",
        "```text", "python scripts/coletar_risco_dependencias.py --help", "```", "",
        "Após revisar os resultados, regenerar Markdown/JSON/PDF e executar --check. As regras só entram no CI remoto após commit/push.", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--refresh", action="store_true")
    parser.add_argument("--date", help="Data da emissao, YYYY-MM-DD, timezone Europe/Dublin")
    args = parser.parse_args()
    try:
        if args.check:
            saved = json.loads(JSON_PATH.read_text(encoding="utf-8"))
            old = saved["inventory"]
            current = inventory(old["generated_date"], old["repository_reference"], old["toolchain"]["pdf_generator"]["version"])
            if current != old or MD_PATH.read_text(encoding="utf-8") != markdown(current):
                raise ValueError("Inventario desatualizado: regenerar Markdown, JSON e PDF antes de publicar.")
            if hashlib.sha256(PDF_PATH.read_bytes()).hexdigest() != saved["pdf_sha256"]:
                raise ValueError("PDF ausente ou divergente do inventario.")
            print("Inventario, fontes e PDF consistentes; nenhuma dependencia foi instalada.")
        else:
            if not args.date or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.date):
                raise ValueError("Informar --date YYYY-MM-DD na data do usuario.")
            ref = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
            from importlib.metadata import version, PackageNotFoundError
            try:
                pdf_version = version("reportlab")
            except PackageNotFoundError:
                raise ValueError("Gerador PDF preexistente indisponivel. Usar ambiente isolado/remoto aprovado.") from None
            data = inventory(args.date, ref, pdf_version)
            from pdf_dependencias import create_pdf
            PDF_PATH.parent.mkdir(parents=True, exist_ok=True)
            create_pdf(data, PDF_PATH, digest(data))
            JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
            JSON_PATH.write_text(dump({"inventory": data, "pdf_sha256": hashlib.sha256(PDF_PATH.read_bytes()).hexdigest()}), encoding="utf-8")
            MD_PATH.write_text(markdown(data), encoding="utf-8")
            print(f"Gerados: {MD_PATH.relative_to(ROOT)}, {JSON_PATH.relative_to(ROOT)}, {PDF_PATH.relative_to(ROOT)}")
        return 0
    except (ValueError, OSError, KeyError, ImportError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        print("Nao instalar pacotes no Windows principal; usar ambiente isolado/remoto aprovado.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
