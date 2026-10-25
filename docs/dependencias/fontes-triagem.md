# Fontes e limites da triagem de dependências

Coleta em 2026-10-25, aplicação 0.8.2, snapshot histórico
`1cec6a04dfe076be8ddbad5258359d2afb225f38`. IA: OpenAI Codex, família GPT-6;
identificador exato do modelo não exposto na sessão.

O arquivo `triagem-seguranca.json` contém 39 entradas: 34 pacotes Python do ambiente
histórico de testes já removido, JavaScript Supabase, ferramenta documental ReportLab
preexistente e três ferramentas de auditoria já removidas. Essas contagens não devem
ser somadas como dependências de execução da aplicação.

## Resultado observado

- 36 entradas com sinais favoráveis no escopo consultado; isso não autoriza instalação automaticamente.
- 3 entradas em atenção; nenhuma foi classificada como malware comprovado.
- 0 entradas em perigo e 0 IDs retornados nas 38 consultas OSV de versões PyPI/npm.
- Downloads disponíveis para as 39 entradas; GitHub disponível para 37.
- `jsonalias 0.1.1`: metadados PyPI não informam repositório de origem; procedência exige revisão adicional.
- `ReportLab 4.4.9`: aponta site próprio, sem GitHub canônico confirmado pelo coletor; estrelas/assinantes são N/D, sem acusação de malware.
- `Gitleaks 8.30.1`: release binária GitHub não foi consultada como módulo Go; cobertura de segurança incompleta nesta coleta.

## Fontes e definições

1. **Registro PyPI:** JSON versionado `https://pypi.org/pypi/NOME/VERSAO/json`.
   Confere nome/versão, arquivos retirados, hashes publicados e links de origem.
   Ler um link fornecido pelo registro não prova a identidade do mantenedor nem
   equivale a verificar atestação/proveniência de build. Arquivos de pacote não foram baixados.
2. **Registro npm:** metadados versionados em `https://registry.npmjs.org/`.
   Integridade e assinaturas presentes no JSON são registradas, não validadas criptograficamente.
3. **OSV:** POST `https://api.osv.dev/v1/querybatch` para nome, ecossistema e versão exatos.
   IDs `MAL-` são relatos de pacote malicioso; CVE/GHSA/PYSEC são avisos de vulnerabilidade,
   não sinônimos de vírus. A base agrega relatos OpenSSF; ausência de ID não detecta
   malware desconhecido, comprometimento ainda não publicado ou tudo que o pacote executa.
   [OpenSSF explica o uso da OSV API para pacotes maliciosos](https://openssf.org/tag/malicious-packages/).
   [Base OpenSSF Malicious Packages](https://github.com/ossf/malicious-packages).
4. **Downloads PyPI:** agregador [PyPI Stats](https://pypistats.org/api/), endpoint
   `/api/packages/NOME/recent`, campo `last_month`. São eventos agregados do projeto
   em todas as versões; incluem automação/CI e não contam instalações nem pessoas únicas.
   A API não fornece início/fim explícitos nesse endpoint; não se inventou uma janela
   de calendário. O provedor atualiza diariamente e recomenda cache por um dia.
5. **Downloads npm:** [API documentada pelo npm](https://github.com/npm/registry/blob/main/docs/download-counts.md),
   `/downloads/point/last-month/NOME`, com início/fim registrados. Também não são pessoas únicas.
6. **GitHub:** `/repos/OWNER/REPO`, campos `stargazers_count` (estrelas) e
   `subscribers_count` (assinantes/watchers). `watchers_count` não é usado, pois coincide
   com a contagem de estrelas em respostas da API. Repositórios compartilhados por
   múltiplos pacotes repetem a mesma métrica; não somar como pessoas distintas.
7. **Gitleaks:** downloads são soma dos arquivos da release v8.30.1 desde sua publicação,
   incluindo plataformas e checksums. Não comparar diretamente com downloads mensais PyPI/npm.

Falha ou ausência de métrica fica como `null` com status e fonte. Popularidade não
determina a classificação de segurança. Um projeto fora do GitHub pode ser legítimo;
N/D não significa zero seguidores nem prova que ele é inseguro.

## Atualização sem instalar pacotes

O coletor usa somente biblioteca padrão e consulta JSON/HTTPS. Não usa pip, não
importa os pacotes analisados, não baixa wheels/sdists e não executa código deles:

```text
python -B -S scripts/coletar_risco_dependencias.py --workers 4
```

`--use-git-credential` pode usar internamente a autenticação já configurada do GitHub
para leituras públicas; a credencial nunca é impressa nem salva. Dados sociais do
mesmo dia são reutilizados; consultas de registro e OSV são renovadas.

Para avaliar uma versão nova, usar um JSON de candidatos sem instalar nada:

```json
{"packages":[{"ecosystem":"PyPI","name":"nome-do-pacote","version":"1.2.3","role":"candidata, não instalada"}]}
```

```text
python -B -S scripts/coletar_risco_dependencias.py --candidates-json candidatos.json --output triagem-candidatos.json
```

Depois revisar fontes e resultado antes de qualquer instalação no ambiente isolado
aprovado, atualizar PDF/Markdown/JSON e preservar a triagem histórica. O coletor não
é um antivírus nem substitui análise de código ou validação de artefatos assinados.
