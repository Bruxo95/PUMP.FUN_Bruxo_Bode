"""Barreira de pre-instalacao Python, usando somente a biblioteca padrao.

Recebe o JSON de pip --dry-run --ignore-installed --only-binary=:all:. Nao
instala, importa nem executa os pacotes candidatos. Exige versoes ja triadas,
consulta OSV/PyPI ao vivo e emite uma lista exata com hashes, para pip instalar
com --require-hashes --no-deps --only-binary=:all:. Falha de consulta bloqueia.

Esta verificacao identifica alertas conhecidos; nao certifica ausencia de malware.
"""
from __future__ import annotations

import argparse
import base64
import binascii
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
from typing import Callable
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECORDS = ROOT / "docs/dependencias/triagem-seguranca.json"
# Sem prazo de validade para o registro (decisao de 2026-10-25): as versoes ficam
# fixadas em constraints.txt e cada build repete OSV/PyPI ao vivo. Um prazo de 7 dias
# reprovaria o deploy automatico toda semana sem nenhuma versao nova.
MAX_FUTURE_SKEW = timedelta(hours=24)
ALLOWED_DOWNLOAD_HOSTS = frozenset({"files.pythonhosted.org", "pypi.org"})
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9.!+_-]*\Z")
SHA256 = re.compile(r"[a-fA-F0-9]{64}\Z")
MAX_JSON_BYTES = 12_000_000


class GateError(ValueError):
    """Instalacao nao aprovada pelo registro ou pelas consultas atuais."""


def canonical(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def utc_date(value: str) -> datetime:
    if not isinstance(value, str):
        raise GateError("Data de triagem ausente ou invalida.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise GateError("Data de triagem invalida.") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def require_recent(value: str, now: datetime, label: str) -> None:
    if now - utc_date(value) < -MAX_FUTURE_SKEW:
        raise GateError(f"{label}: data de triagem no futuro; refazer a pesquisa e o PDF.")


def fetch_json(url: str, payload: dict | None = None) -> dict:
    """URLs chamadas aqui sao construidas a partir de hosts oficiais fixos."""
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={
        "User-Agent": "pump-fun-copy-dependency-gate/1.0",
        "Accept": "application/json", "Content-Type": "application/json",
    })
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=20) as response:
            raw = response.read(MAX_JSON_BYTES + 1)
        if len(raw) > MAX_JSON_BYTES:
            raise GateError("Resposta da consulta excedeu o limite permitido.")
        result = json.loads(raw)
    except urllib.error.HTTPError as exc:
        raise GateError(f"Consulta de seguranca indisponivel (HTTP {exc.code}); instalacao bloqueada.") from None
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        raise GateError("Consulta de seguranca indisponivel ou invalida; instalacao bloqueada.") from None
    if not isinstance(result, dict):
        raise GateError("Formato inesperado na consulta de seguranca.")
    return result


def official_url(value: str) -> str:
    if not isinstance(value, str):
        raise GateError("URL de artefato ausente.")
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError:
        raise GateError("URL de artefato invalida.") from None
    if (parsed.scheme != "https" or parsed.hostname not in ALLOWED_DOWNLOAD_HOSTS
            or parsed.username is not None or parsed.password is not None
            or port not in (None, 443) or parsed.query):
        raise GateError("Artefato fora dos hosts HTTPS oficiais permitidos do PyPI.")
    if not urllib.parse.unquote(parsed.path).endswith(".whl"):
        raise GateError("Somente wheels podem passar pela triagem; sdist/VCS/local sao bloqueados.")
    return urllib.parse.urlunsplit(parsed._replace(fragment=""))


def candidates(report: dict) -> list[dict]:
    if str(report.get("version")) != "1" or not isinstance(report.get("install"), list):
        raise GateError("Relatorio pip ausente ou com formato nao suportado.")
    if not report["install"]:
        raise GateError("Relatorio sem candidatos. Resolver com --ignore-installed antes da verificacao.")
    result, seen = [], set()
    for item in report["install"]:
        if not isinstance(item, dict) or item.get("is_direct") or item.get("is_yanked"):
            raise GateError("Referencia direta, versao retirada ou candidato invalido no relatorio pip.")
        meta, download = item.get("metadata", {}), item.get("download_info", {})
        name, version = meta.get("name"), meta.get("version")
        if not isinstance(name, str) or not NAME.fullmatch(name):
            raise GateError("Nome de pacote invalido no relatorio.")
        if not isinstance(version, str) or not VERSION.fullmatch(version):
            raise GateError(f"Versao invalida no relatorio: {name}.")
        normalized = canonical(name)
        if normalized in seen:
            raise GateError(f"Pacote duplicado no relatorio: {name}.")
        seen.add(normalized)
        archive = download.get("archive_info", {})
        value = (archive.get("hashes") or {}).get("sha256")
        if value is None and isinstance(archive.get("hash"), str):
            prefix, _, legacy = archive["hash"].partition("=")
            value = legacy if prefix == "sha256" else None
        if not isinstance(value, str) or not SHA256.fullmatch(value):
            raise GateError(f"Hash SHA-256 ausente ou invalido: {name}.")
        result.append({"ecosystem": "PyPI", "name": normalized, "version": version,
                       "url": official_url(download.get("url")), "sha256": value.lower()})
    return sorted(result, key=lambda row: row["name"])


def frontend_candidates(directory: Path) -> list[dict]:
    """Confere versao/SRI declarados, sem baixar nem executar JavaScript."""
    package_url = re.compile(r"/npm/(@[A-Za-z0-9._-]+/[A-Za-z0-9._-]+|[A-Za-z0-9._-]+)@([0-9][A-Za-z0-9.!+_-]*)/")
    found = {}

    class Scripts(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if tag != "script":
                return
            keys = [name for name, _ in attrs]
            if len(keys) != len(set(keys)):
                raise GateError("Atributos duplicados em script; revisar antes de instalar/publicar.")
            attributes = dict(attrs)
            url = attributes.get("src")
            if not url:
                return
            parsed = urllib.parse.urlsplit(url)
            if not parsed.scheme and not parsed.netloc:
                return  # Script local do proprio repositorio.
            try:
                port = parsed.port
            except ValueError:
                raise GateError("URL externa JavaScript invalida.") from None
            match = package_url.match(parsed.path)
            if (parsed.scheme != "https" or parsed.hostname != "cdn.jsdelivr.net"
                    or parsed.username is not None or parsed.password is not None
                    or port not in (None, 443) or parsed.query or parsed.fragment or not match):
                raise GateError("Dependencia JavaScript fora do CDN/versionamento suportado; catalogar antes de publicar.")
            integrities = (attributes.get("integrity") or "").split()
            if not integrities:
                raise GateError("Dependencia JavaScript sem SRI.")
            for integrity in integrities:
                algorithm, _, encoded = integrity.partition("-")
                try:
                    decoded = base64.b64decode(encoded, validate=True)
                except (ValueError, binascii.Error):
                    raise GateError("SRI JavaScript invalido.") from None
                if algorithm not in {"sha256", "sha384", "sha512"} or len(decoded) != {"sha256": 32, "sha384": 48, "sha512": 64}.get(algorithm):
                    raise GateError("Algoritmo/tamanho SRI JavaScript invalido.")
            name, version = match.groups()
            previous = found.get(name)
            if previous and (previous["version"] != version or previous["integrity"] != sorted(integrities)):
                raise GateError(f"Versao/SRI divergente entre paginas: {name}.")
            found[name] = {"ecosystem": "npm", "name": name, "version": version,
                           "integrity": sorted(integrities)}

    htmls = sorted(directory.rglob("*.html")) if directory.is_dir() else []
    if not htmls:
        raise GateError("HTMLs do frontend ausentes; verificacao de dependencias incompleta.")
    for path in htmls:
        Scripts().feed(path.read_text(encoding="utf-8"))
    return sorted(found.values(), key=lambda row: row["name"])


def reviewed_entries(records: dict, now: datetime) -> dict[tuple[str, str, str], dict]:
    if records.get("schema_version") != 1 or not isinstance(records.get("packages"), list):
        raise GateError("Registro de triagem ausente ou com formato nao suportado.")
    require_recent(records.get("collected_at"), now, "Registro")
    indexed = {}
    for entry in records["packages"]:
        if not isinstance(entry, dict) or entry.get("ecosystem") not in {"PyPI", "npm"}:
            continue
        name, version = entry.get("name"), entry.get("version")
        if not isinstance(name, str) or not isinstance(version, str):
            raise GateError("Entrada PyPI sem nome/versao no registro.")
        key = entry["ecosystem"], canonical(name), version
        if key in indexed:
            raise GateError(f"Entrada de triagem duplicada: {name} {version}.")
        indexed[key] = entry
    return indexed


def check_review(candidate: dict, entry: dict | None, now: datetime) -> None:
    label = candidate.get("ecosystem", "PyPI") + " " + candidate["name"] + " " + candidate["version"]
    if entry is None:
        raise GateError(f"{label}: versao ainda nao triada. Pesquisar e atualizar o PDF antes de instalar.")
    registry, alerts = entry.get("registry", {}), entry.get("advisories", {})
    if (registry.get("status") != "ok" or registry.get("version_exists") is not True
            or registry.get("yanked") is not False):
        raise GateError(f"{label}: procedencia/release nao confirmada ou versao retirada.")
    if alerts.get("status") != "ok" or alerts.get("ids") != [] or alerts.get("malware_ids") != []:
        raise GateError(f"{label}: alerta conhecido ou consulta anterior incompleta.")
    require_recent(alerts.get("checked_at"), now, label)
    if entry.get("classification", {}).get("level") != "favorable":
        raise GateError(f"{label}: classificacao exige revisao; nao ha liberacao automatica.")
    github = entry.get("popularity", {}).get("github", {})
    if github.get("archived") is True:
        raise GateError(f"{label}: repositorio arquivado; revisar antes de instalar.")


def check_release(candidate: dict, query: Callable = fetch_json) -> None:
    label = candidate["name"] + " " + candidate["version"]
    url = "https://pypi.org/pypi/" + urllib.parse.quote(candidate["name"], safe="") + "/" + urllib.parse.quote(candidate["version"], safe="") + "/json"
    release = query(url)
    info = release.get("info", {})
    if (canonical(str(info.get("name", ""))) != candidate["name"]
            or info.get("version") != candidate["version"]):
        raise GateError(f"{label}: metadados PyPI divergentes.")
    if release.get("vulnerabilities"):
        raise GateError(f"{label}: PyPI informa vulnerabilidade; instalacao bloqueada.")
    files = release.get("urls")
    if not isinstance(files, list):
        raise GateError(f"{label}: lista de artefatos PyPI indisponivel.")
    matching = []
    for artifact in files:
        if not isinstance(artifact, dict) or artifact.get("packagetype") != "bdist_wheel":
            continue
        try:
            artifact_url = official_url(artifact.get("url"))
        except GateError:
            continue
        if (artifact_url == candidate["url"]
                and (artifact.get("digests") or {}).get("sha256", "").lower() == candidate["sha256"]):
            matching.append(artifact)
    if len(matching) != 1 or matching[0].get("yanked") is not False:
        raise GateError(f"{label}: wheel/hash nao corresponde a artefato ativo publicado no PyPI.")


def check_npm_release(candidate: dict, query: Callable = fetch_json) -> None:
    url = "https://registry.npmjs.org/" + urllib.parse.quote(candidate["name"], safe="") + "/" + urllib.parse.quote(candidate["version"], safe="")
    release = query(url)
    if release.get("name") != candidate["name"] or release.get("version") != candidate["version"]:
        raise GateError("Metadados npm divergentes da versao JavaScript declarada.")
    if release.get("deprecated"):
        raise GateError(f"{candidate['name']} {candidate['version']}: versao npm descontinuada; revisar aviso.")
    integrity = (release.get("dist") or {}).get("integrity")
    if not isinstance(integrity, str) or not integrity.startswith(("sha256-", "sha384-", "sha512-")):
        raise GateError("Integridade do artefato npm indisponivel; instalacao/publicacao bloqueada.")


def check_live_osv(selected: list[dict], query: Callable = fetch_json) -> None:
    for start in range(0, len(selected), 100):
        batch = selected[start:start + 100]
        response = query("https://api.osv.dev/v1/querybatch", {"queries": [
            {"package": {"ecosystem": row.get("ecosystem", "PyPI"), "name": row["name"]}, "version": row["version"]}
            for row in batch
        ]})
        results = response.get("results")
        if not isinstance(results, list) or len(results) != len(batch):
            raise GateError("Consulta OSV incompleta; instalacao bloqueada.")
        for candidate, result in zip(batch, results):
            if (not isinstance(result, dict) or "error" in result or result.get("next_page_token")
                    or not isinstance(result.get("vulns", []), list)):
                raise GateError("Resposta OSV incompleta ou paginada; revisar antes de instalar.")
            if result.get("vulns"):
                ids = [str(v.get("id", "alerta sem ID")) for v in result["vulns"] if isinstance(v, dict)]
                raise GateError(f"{candidate['name']} {candidate['version']}: OSV retornou alertas {', '.join(ids)}.")


def validate(records: dict, report: dict, now: datetime | None = None,
             query: Callable = fetch_json, frontend: list[dict] | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    selected = candidates(report)
    indexed = reviewed_entries(records, now)
    all_candidates = selected + (frontend or [])
    for row in all_candidates:
        key = row.get("ecosystem", "PyPI"), canonical(row["name"]), row["version"]
        check_review(row, indexed.get(key), now)
    # Nenhum arquivo de instalacao e produzido antes destas consultas ao vivo.
    check_live_osv(all_candidates, query)
    for row in selected:
        check_release(row, query)
    for row in frontend or []:
        check_npm_release(row, query)
    return selected


def lock_text(selected: list[dict], now: datetime) -> str:
    return ("# Gerado apos triagem e consultas PyPI/OSV em " + now.isoformat() + "\n"
            "# Instalar somente com --require-hashes --no-deps --only-binary=:all:.\n"
            + "\n".join(row["name"] + "==" + row["version"] + " --hash=sha256:" + row["sha256"]
                        for row in selected) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pip-report", type=Path, required=True)
    parser.add_argument("--output-lock", type=Path, required=True)
    parser.add_argument("--records", type=Path, default=DEFAULT_RECORDS)
    parser.add_argument("--frontend-dir", type=Path, default=ROOT / "web")
    args = parser.parse_args()
    try:
        protected = {args.records.resolve(), args.pip_report.resolve(), Path(__file__).resolve(),
                     (ROOT / "requirements.txt").resolve()}
        if args.output_lock.resolve() in protected:
            raise GateError("A lista temporaria nao pode sobrescrever fontes ou registros.")
        records = json.loads(args.records.read_text(encoding="utf-8"))
        report = json.loads(args.pip_report.read_text(encoding="utf-8"))
        now = datetime.now(timezone.utc)
        frontend = frontend_candidates(args.frontend_dir)
        selected = validate(records, report, now, frontend=frontend)
        args.output_lock.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output_lock.with_name(args.output_lock.name + ".tmp")
        temporary.write_text(lock_text(selected, now), encoding="utf-8")
        temporary.replace(args.output_lock)
        print(f"Triagem atual e artefatos conferidos: {len(selected)} versoes exatas com SHA-256.")
        print(f"Frontend: {len(frontend)} dependencias npm com versao/SRI declarados e consultas atuais.")
        print("Nenhum pacote foi instalado pelo verificador. Alertas conhecidos nao cobrem malware desconhecido.")
        return 0
    except (GateError, OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        print(f"INSTALACAO BLOQUEADA: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
