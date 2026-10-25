"""Consulta metadados e relatos publicos, sem instalar/importar pacotes analisados.

Somente biblioteca padrao. Downloads sao eventos agregados, nao instalacoes ou
pessoas unicas. Estrelas/assinantes nao aprovam seguranca. A consulta sem alertas
nao certifica ausencia de malware. Usar --use-git-credential apenas quando autorizado.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/dependencias/triagem-seguranca.json"
MANUAL = ROOT / "docs/dependencias/revisoes-manuais.json"
OSV_URL = "https://api.osv.dev/v1/querybatch"
UA = "PUMP-FUN-COPY-dependency-triage/1.0 (metadata-only)"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(request, fp, code, msg, headers, newurl)
        if redirected and urllib.parse.urlsplit(newurl).hostname != urllib.parse.urlsplit(request.full_url).hostname:
            redirected.remove_header("Authorization")
        return redirected


def request_json(url: str, token: str | None = None, payload=None) -> tuple[dict | None, dict]:
    headers = {"User-Agent": UA, "Accept": "application/json"}
    if token and urllib.parse.urlsplit(url).hostname == "api.github.com":
        headers["Authorization"] = "Bearer " + token
    raw = json.dumps(payload).encode() if payload is not None else None
    if raw:
        headers["Content-Type"] = "application/json"
    opener = urllib.request.build_opener(SafeRedirect)
    for attempt in range(2):
        try:
            with opener.open(urllib.request.Request(url, data=raw, headers=headers), timeout=20) as response:
                data = json.load(response)
            return data, {"status": "ok", "source_url": url, "checked_at": now()}
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt == 0:
                time.sleep(2)
                continue
            return None, {"status": "unavailable", "source_url": url, "checked_at": now(), "http_status": exc.code}
        except (OSError, ValueError) as exc:
            if attempt == 0:
                time.sleep(1)
                continue
            return None, {"status": "unavailable", "source_url": url, "checked_at": now(), "error_type": type(exc).__name__}
    raise AssertionError("unreachable")


def github_repository(url: str | None) -> str | None:
    if not isinstance(url, str):
        return None
    value = url.removeprefix("git+")
    if value.startswith("git@github.com:"):
        value = "https://github.com/" + value.split(":", 1)[1]
    parsed = urllib.parse.urlsplit(value)
    if parsed.hostname not in ("github.com", "www.github.com") or parsed.username or parsed.password:
        return None
    pieces = parsed.path.strip("/").split("/")
    if len(pieces) < 2:
        return None
    owner, repo = pieces[:2]
    repo = repo.removesuffix(".git")
    return owner + "/" + repo if re.fullmatch(r"[A-Za-z0-9_.-]+", owner) and re.fullmatch(r"[A-Za-z0-9_.-]+", repo) else None


def pypi_repository(info: dict) -> tuple[str | None, str | None]:
    links = list((info.get("project_urls") or {}).items())
    priority = {"source": 0, "source code": 0, "repository": 0, "code": 0, "homepage": 1}
    links.sort(key=lambda item: priority.get(item[0].lower(), 2))
    links.append(("home_page", info.get("home_page")))
    for _, url in links:
        if (repo := github_repository(url)):
            return repo, url
    # Nao atribuir metricas de espelhos GitHub quando o projeto aponta para outro forge.
    return None, next((url for label, url in links if isinstance(url, str) and label.lower() in priority), None)


def candidates(candidate_file: Path | None = None) -> list[dict]:
    if candidate_file:
        supplied = json.loads(candidate_file.read_text(encoding="utf-8"))
        rows = supplied if isinstance(supplied, list) else supplied.get("packages", [])
        if not rows or not all(isinstance(r, dict) for r in rows):
            raise ValueError("Arquivo de candidatos precisa conter lista nao vazia de pacotes.")
        checked, seen = [], set()
        for row in rows:
            ecosystem, name, version = (row.get(k) for k in ("ecosystem", "name", "version"))
            valid_name = isinstance(name, str) and bool(re.fullmatch(
                r"(?:@[A-Za-z0-9_.-]+/)?[A-Za-z0-9_.-]+", name))
            if ecosystem not in ("PyPI", "npm", "GitHubRelease") or not valid_name or not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+_!-]*", version):
                raise ValueError("Candidato com ecossistema, nome ou versao invalida.")
            if ecosystem == "GitHubRelease" and name != "gitleaks":
                raise ValueError("Release GitHub ainda nao catalogada; estender o coletor antes de consultar.")
            key = (ecosystem, canonical(name), version)
            if key not in seen:
                checked.append({"ecosystem": ecosystem, "name": name, "version": version,
                                "role": row.get("role", "versao candidata, nao instalada")})
                seen.add(key)
        return checked
    snapshot = json.loads((ROOT / "docs/auditoria/2026-10-25/pacotes-testados.json").read_text(encoding="utf-8"))
    inventory_file = ROOT / "docs/dependencias/inventario.json"
    inventory = json.loads(inventory_file.read_text(encoding="utf-8"))["inventory"] if inventory_file.exists() else {}
    triage = json.loads((ROOT / "docs/auditoria/2026-10-25/triagem-scanners.json").read_text(encoding="utf-8"))
    direct = {canonical(line.split("[", 1)[0].split(">", 1)[0].split("=", 1)[0].strip())
              for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines() if line.strip()}
    rows = [{"ecosystem": "PyPI", "name": p["name"], "version": p["version"],
             "role": "execução direta" if canonical(p["name"]) in direct else (
                 "teste direto" if canonical(p["name"]) == "pytest" else "snapshot indireto/suporte")}
            for p in snapshot["packages"]]
    javascript = {}
    for html_path in (ROOT / "web/index.html", ROOT / "web/app.html"):
        for name, version in re.findall(r"/npm/((?:@[^/]+/)?[^@/]+)@([^/\"]+)", html_path.read_text(encoding="utf-8")):
            javascript[name] = version
    rows += [{"ecosystem": "npm", "name": n, "version": v, "role": "JavaScript direto"} for n, v in javascript.items()]
    rows += [{"ecosystem": "PyPI", "name": "reportlab", "version": inventory.get("toolchain", {}).get("pdf_generator", {}).get("version", "4.4.9"), "role": "documentação opcional preexistente"},
             {"ecosystem": "PyPI", "name": "bandit", "version": triage["bandit"]["version"], "role": "ferramenta de auditoria removida"},
             {"ecosystem": "PyPI", "name": "pip-audit", "version": triage["pip_audit"]["version"], "role": "ferramenta de auditoria removida"},
             {"ecosystem": "GitHubRelease", "name": "gitleaks", "version": triage["gitleaks"]["version"], "role": "ferramenta de auditoria removida"}]
    return rows


def registry_entry(row: dict, token: str | None, metrics_cache: dict | None = None) -> dict:
    row = dict(row)
    name, version, ecosystem = row["name"], row["version"], row["ecosystem"]
    if ecosystem == "PyPI":
        url = f"https://pypi.org/pypi/{urllib.parse.quote(name, safe='')}/{urllib.parse.quote(version, safe='')}/json"
        data, status = request_json(url)
        info, files = (data or {}).get("info", {}), (data or {}).get("urls", [])
        repository, repository_url = pypi_repository(info)
        exists = bool(data and info.get("version") == version and canonical(info.get("name", "")) == canonical(name))
        registry = {**status, "url": url, "version_exists": exists, "canonical_name": info.get("name"),
                    "yanked": bool(files and all(f.get("yanked") for f in files)),
                    "yanked_reason": sorted({f.get("yanked_reason") for f in files if f.get("yanked_reason")}),
                    "repository": repository, "repository_url": repository_url,
                    "artifact_count": len(files), "hashes_present": bool(files and all((f.get("digests") or {}).get("sha256") for f in files)),
                    "published_at": min((f.get("upload_time_iso_8601") for f in files if f.get("upload_time_iso_8601")), default=None),
                    "requires_python": info.get("requires_python"),
                    "artifact_hashes": [{"filename": f.get("filename"), "sha256": (f.get("digests") or {}).get("sha256"),
                        "type": f.get("packagetype"), "yanked": bool(f.get("yanked"))} for f in files],
                    "repository_evidence": "Link publicado nos metadados PyPI; nao verifica identidade do mantenedor."}
        stats_url = "https://pypistats.org/api/packages/" + urllib.parse.quote(canonical(name), safe="") + "/recent"
        cached = (metrics_cache or {}).get((ecosystem, canonical(name)))
        if cached:
            downloads = {**cached, "cache_reused": True}
        else:
            stats, stats_status = request_json(stats_url)
            count = (stats or {}).get("data", {}).get("last_month")
            downloads = {**stats_status, "count": count if isinstance(count, int) and count >= 0 else None,
                         "period": "last_month (janela movel do provedor)", "start": None, "end": None,
                         "scope": "Downloads de todas as versoes do projeto, nao instalacoes nem pessoas unicas.",
                         "provider": "PyPI Stats, agregador de dados publicos de downloads PyPI"}
    elif ecosystem == "npm":
        url = "https://registry.npmjs.org/" + urllib.parse.quote(name, safe="@") + "/" + urllib.parse.quote(version, safe="")
        data, status = request_json(url)
        repo_data = (data or {}).get("repository") or {}
        repo_url = repo_data.get("url") if isinstance(repo_data, dict) else repo_data
        repository = github_repository(repo_url)
        dist = (data or {}).get("dist") or {}
        registry = {**status, "url": url, "version_exists": bool(data and data.get("version") == version and data.get("name") == name),
                    "canonical_name": (data or {}).get("name"), "yanked": bool((data or {}).get("deprecated")),
                    "deprecation_notice": (data or {}).get("deprecated"), "repository": repository, "repository_url": repo_url,
                    "integrity": dist.get("integrity"), "signatures_present": bool(dist.get("signatures")),
                    "repository_evidence": "Link publicado nos metadados npm; nao verifica identidade do mantenedor."}
        stats_url = "https://api.npmjs.org/downloads/point/last-month/" + urllib.parse.quote(name, safe="@")
        stats, stats_status = request_json(stats_url)
        count = (stats or {}).get("downloads")
        downloads = {**stats_status, "count": count if isinstance(count, int) and count >= 0 else None,
                     "period": "last-month", "start": (stats or {}).get("start"), "end": (stats or {}).get("end"),
                     "scope": "Downloads de todas as versoes do projeto, nao instalacoes nem pessoas unicas.", "provider": "npm Downloads API"}
    else:
        repository = "gitleaks/gitleaks"
        url = f"https://api.github.com/repos/{repository}/releases/tags/v{version}"
        data, status = request_json(url, token)
        registry = {**status, "url": url, "version_exists": bool(data and data.get("tag_name") == "v" + version),
                    "canonical_name": "gitleaks", "yanked": False, "repository": repository,
                    "repository_url": "https://github.com/" + repository, "published_at": (data or {}).get("published_at"),
                    "repository_evidence": "Release do repositorio oficial usado na auditoria anterior."}
        assets = (data or {}).get("assets", [])
        downloads = {**status, "count": sum(a.get("download_count", 0) for a in assets) if data else None,
                     "period": "Desde publicacao da release v" + version, "start": (data or {}).get("published_at"), "end": status["checked_at"],
                     "scope": "Soma de downloads dos arquivos da release em todas plataformas, incluindo checksums; nao instalacoes/pessoas unicas.",
                     "provider": "GitHub Release API"}
    row["registry"] = registry
    row["popularity"] = {"downloads": downloads}
    return row


def github_metrics(repository: str, token: str | None) -> dict:
    url = "https://api.github.com/repos/" + repository
    data, status = request_json(url, token)
    return {**status, "repository": (data or {}).get("full_name", repository), "url": (data or {}).get("html_url"),
            "stars": (data or {}).get("stargazers_count"), "subscribers": (data or {}).get("subscribers_count"),
            "archived": (data or {}).get("archived"), "disabled": (data or {}).get("disabled"),
            "pushed_at": (data or {}).get("pushed_at"), "created_at": (data or {}).get("created_at"),
            "scope": "Estrelas e assinantes/watchers do repositorio; nao usuarios, auditorias ou garantia de seguranca."}


def manual_reviews() -> dict:
    # Revisao humana/IA registrada para pendencias que o coletor nao resolve sozinho
    # (ex.: release sem link de repositorio). Nunca anula alerta OSV ou release retirada.
    if not MANUAL.exists():
        return {}
    data = json.loads(MANUAL.read_text(encoding="utf-8"))
    return {(r["ecosystem"], canonical(r["name"]), r["version"]): r for r in data.get("reviews", [])}


def app_version() -> str:
    text = (ROOT / "app/version.py").read_text(encoding="utf-8")
    return re.search(r'VERSION = "([^"\s]+)', text)[1]


def classify(row: dict, manual: dict | None = None) -> dict:
    registry, advisories, github = row["registry"], row["advisories"], row["popularity"]["github"]
    danger, attention = [], []
    if advisories.get("malware_ids"):
        danger.append("Relato publico MAL de pacote/versao na consulta OSV; bloquear e revisar fonte.")
    elif advisories.get("ids"):
        danger.append("Aviso de vulnerabilidade para a versao consultada; nao equivale a malware; bloquear ate triagem.")
    if registry.get("yanked"):
        danger.append("Release retirada/depreciada conforme registro; exigir revisao antes de instalar.")
    if registry.get("status") != "ok" or not registry.get("version_exists"):
        attention.append("Versao/procedencia nao confirmada no registro consultado.")
    if advisories.get("status") != "ok":
        attention.append("Consulta de seguranca incompleta ou ecossistema nao coberto nesta coleta.")
    if github.get("status") != "ok":
        attention.append("Repositorio de origem sem confirmacao pela API GitHub nesta coleta; metrica ausente nao prova risco.")
    if github.get("archived") or github.get("disabled"):
        attention.append("Repositorio arquivado/desativado; revisar manutencao e origem.")
    level = "danger" if danger else "attention" if attention else "favorable"
    review = (manual or {}).get((row["ecosystem"], canonical(row["name"]), row["version"]))
    if level == "attention" and review and review.get("decision") == "favorable":
        return {"level": "favorable", "reasons": ["Revisao manual: " + review["reason"]],
                "automatic_findings": attention, "manual_review": review,
                "automatic_install_approval": False,
                "limitation": "Sinais favoraveis nao certificam ausencia de malware; popularidade nao determina esta classificacao."}
    reasons = danger + attention or ["Versao existente, origem vinculada ao registro confirmada e consulta OSV sem avisos retornados nesta data."]
    return {"level": level, "reasons": reasons,
            "automatic_install_approval": False,
            "limitation": "Sinais favoraveis nao certificam ausencia de malware; popularidade nao determina esta classificacao."}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--use-git-credential", action="store_true")
    parser.add_argument("--workers", type=int, default=4, choices=range(1, 7))
    parser.add_argument("--candidates-json", type=Path, help="Lista JSON de novas versoes candidatas; nao instala nada.")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--reviewer-agent", default="Claude Code")
    parser.add_argument("--reviewer-model", default="claude-opus-5-5")
    args = parser.parse_args()
    token = None
    if args.use_git_credential:
        import os
        result = subprocess.run(["git", "-c", "credential.interactive=false", "credential", "fill"],
            input="protocol=https\nhost=github.com\n\n", text=True, capture_output=True,
            env=dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="Never"), cwd=ROOT)
        credential = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        token = credential.get("password")
    started = now()
    manual = manual_reviews()
    metrics_cache, github_cache = {}, {}
    if args.output.exists():
        previous = json.loads(args.output.read_text(encoding="utf-8"))
        for row in previous.get("packages", []):
            downloads = row.get("popularity", {}).get("downloads", {})
            if downloads.get("checked_at", "")[:10] == started[:10]:
                metrics_cache[(row["ecosystem"], canonical(row["name"]))] = downloads
            repo = row.get("popularity", {}).get("github", {})
            if repo.get("checked_at", "")[:10] == started[:10] and repo.get("repository"):
                github_cache[repo["repository"]] = repo
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(lambda row: registry_entry(row, token, metrics_cache), candidates(args.candidates_json)))
        repositories = sorted({r["registry"]["repository"] for r in rows if r["registry"].get("repository")})
        github = dict(zip(repositories, pool.map(lambda repo: {**github_cache[repo], "cache_reused": True}
            if repo in github_cache else github_metrics(repo, token), repositories)))
    queries = [{"package": {"ecosystem": r["ecosystem"], "name": r["name"]}, "version": r["version"]}
               for r in rows if r["ecosystem"] in ("PyPI", "npm")]
    response, osv_status = request_json(OSV_URL, payload={"queries": queries})
    results = (response or {}).get("results", [])
    if len(results) != len(queries):
        osv_status["status"] = "unavailable"
        osv_status["error_type"] = "unexpected_result_count"
    iterator = iter(results)
    for row in rows:
        repo = row["registry"].get("repository")
        row["popularity"]["github"] = github.get(repo, {"status": "not_available", "repository": repo,
            "url": row["registry"].get("repository_url"), "stars": None, "subscribers": None,
            "archived": None, "source_url": None, "checked_at": now(),
            "scope": "Sem repositorio GitHub confirmado; nao usar contagem de espelho como origem oficial."})
        if row["ecosystem"] in ("PyPI", "npm"):
            answer = next(iterator, {}) if osv_status["status"] == "ok" else {}
            ids = sorted({v["id"] for v in answer.get("vulns", []) if v.get("id")})
            row["advisories"] = {**osv_status, "ids": ids, "malware_ids": [v for v in ids if v.startswith("MAL-")],
                "query": {"package": {"ecosystem": row["ecosystem"], "name": row["name"]}, "version": row["version"]},
                "record_urls": ["https://osv.dev/vulnerability/" + v for v in ids],
                "scope": "Relatos de vulnerabilidades e malware que a base OSV associa a este nome/ecossistema/versao; ausencia nao garante seguranca."}
        else:
            row["advisories"] = {"status": "not_covered", "ids": [], "malware_ids": [], "source_url": OSV_URL,
                "checked_at": now(), "scope": "Release binaria GitHub nao consultada como modulo Go; nao presumir ausencia de alertas."}
        row["classification"] = classify(row, manual)
    data = {"schema_version": 1, "collection_started_at": started, "collected_at": now(),
        "application_version": app_version(), "audit_snapshot_commit": "1cec6a04dfe076be8ddbad5258359d2afb225f38",
        "reviewer": {"agent": args.reviewer_agent, "exact_model_id": args.reviewer_model},
        "scope": "Metadados e fontes publicas; nenhum pacote analisado foi instalado, importado ou executado.",
        "legend": {"favorable": "Sinais favoraveis no escopo consultado; nao garante seguranca nem autoriza instalacao.",
                   "attention": "Consulta/procedencia incompleta ou manutencao requer revisao; nao e acusacao de malware.",
                   "danger": "Relato para a versao ou release retirada/depreciada; bloquear e revisar motivo. CVE nao significa malware."},
        "metrics_limitations": ["Nao existe contagem de instalacoes/pessoas unicas demonstrada por estas APIs.",
            "Downloads PyPI/npm cobrem todas versoes do projeto e incluem automacao/CI.",
            "GitHub stars != subscribers: assinantes usam subscribers_count, nao watchers_count.",
            "Uma metrica indisponivel e null, nunca zero inventado; popularidade nao determina classificacao."],
        "security_sources": ["https://osv.dev/", "https://github.com/ossf/malicious-packages", "https://pypi.org/", "https://registry.npmjs.org/"],
        "packages": rows,
        "summary": {"total": len(rows), **{level: sum(r["classification"]["level"] == level for r in rows)
            for level in ("favorable", "attention", "danger")},
            "downloads_available": sum(r["popularity"]["downloads"]["count"] is not None for r in rows),
            "github_available": sum(r["popularity"]["github"]["status"] == "ok" for r in rows),
            "osv_queries_ok": sum(r["advisories"]["status"] == "ok" for r in rows)}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "summary": data["summary"]}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
