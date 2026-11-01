FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app

COPY requirements.txt constraints.txt ./
COPY scripts/verificar_triagem_dependencias.py /tmp/dependency-check/verificar_triagem_dependencias.py
COPY docs/dependencias/triagem-seguranca.json /tmp/dependency-check/triagem-seguranca.json
COPY web/index.html web/app.html /tmp/dependency-check/web/
# Resolve metadados de wheels sem instalar; bloqueia versao sem triagem, alerta,
# consulta indisponivel ou hash divergente antes de executar codigo dos pacotes.
RUN python -m pip --isolated install --dry-run --ignore-installed --only-binary=:all: \
      --index-url https://pypi.org/simple --report /tmp/dependency-check/candidatos.json \
      -c constraints.txt -r requirements.txt \
    && python -B /tmp/dependency-check/verificar_triagem_dependencias.py \
      --records /tmp/dependency-check/triagem-seguranca.json \
      --pip-report /tmp/dependency-check/candidatos.json \
      --frontend-dir /tmp/dependency-check/web \
      --output-lock /tmp/dependency-check/requirements-triados.txt \
    && python -m pip --isolated install --no-cache-dir --only-binary=:all: --require-hashes --no-deps \
      --index-url https://pypi.org/simple -r /tmp/dependency-check/requirements-triados.txt \
    && rm -rf /tmp/dependency-check

COPY app ./app
COPY web ./web

# roda sem ser root; nada é gravado no container (tudo fica no Supabase)
RUN useradd --system --uid 10001 bode
USER bode

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=600s --retries=3 \
  CMD python -c "import urllib.request,os; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8080')+'/health', timeout=4)"

CMD ["python", "-m", "app.main"]
