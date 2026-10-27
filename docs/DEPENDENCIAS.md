# Inventário de dependências - PUMP FUN COPY

Emissão: **2026-10-27**; revisão documental **2.0**.
Aplicação: **0.31.77 · 2026-10-27 · Pools de cada token no Explorar**.
Referência Git na emissão: `fecc6fc59b3ee1e9adeb47bc97409c316af05809`; fontes locais identificadas por SHA-256 no JSON.
Emissão: OpenAI Codex, família GPT-6; identificador exato do modelo não exposto nesta sessão. Auditoria original: OpenAI Codex, família GPT-6.

## Quantidade e significado

- **9 dependências diretas de execução:** 8 Python e 1 JavaScript.
- **1 dependência direta de teste**, declarada separadamente no CI.
- **34 pacotes Python no snapshot histórico:** inclui os diretos, teste e 26 outros pacotes.
- **5 Actions únicas** e **2 fontes externas**, contabilizadas à parte.
- Não somar o snapshot aos diretos: os mesmos pacotes apareceriam duas vezes.
- Não há dependências deste projeto instaladas atualmente no Windows principal; o ambiente observado foi removido.

## Execução Python: declaração versus versão observada

| Pacote | Regra em requirements.txt | Versão histórica observada |
|---|---|---|
| fastapi | `>=0.115,<1` | 0.162.0 |
| uvicorn[standard] | `>=0.30,<1` | 0.54.0 |
| httpx | `>=0.27,<1` | 0.28.1 |
| websockets | `>=13,<16` | 15.0.1 |
| solders | `>=0.21,<1` | 0.29.0 |
| cryptography | `>=42` | 50.0.2 |
| PyJWT[crypto] | `>=2.8,<3` | 2.15.1 |
| tzdata | `>=2024.1` | Não registrada |

Extras como [standard] e [crypto] ativam dependências adicionais; não são pacotes separados.
As faixas declaradas não fixam versões exatas. A coluna observada é histórica, não um lockfile.

## Testes e JavaScript

| Tipo | Nome | Regra/versão declarada | Versão histórica |
|---|---|---|---|
| Teste Python | pytest | não fixada | 9.1.1 |
| JavaScript de execução | @supabase/supabase-js | 2.118.0 | Não se aplica ao snapshot Python |

A biblioteca JS aparece nos dois HTMLs, mas é contada uma vez. Seu SRI fica registrado no JSON.

## Snapshot completo de Python

Origem: `docs/auditoria/2026-10-25/pacotes-testados.json`, auditoria de 2026-10-25, aplicação 0.8.2,
commit `1cec6a04dfe076be8ddbad5258359d2afb225f38`, Python 3.12.14.

**Histórico: ambiente local removido; não representa produção nem instalação atual.**

| Nome | Versão | Classificação no inventário |
|---|---|---|
| annotated-doc | 0.0.5 | Outra do ambiente de testes |
| annotated-types | 0.8.0 | Outra do ambiente de testes |
| anyio | 4.15.1 | Outra do ambiente de testes |
| certifi | 2026.10.23 | Outra do ambiente de testes |
| cffi | 2.1.1 | Outra do ambiente de testes |
| click | 8.5.0 | Outra do ambiente de testes |
| colorama | 0.4.6 | Outra do ambiente de testes |
| cryptography | 50.0.2 | Direta de execução |
| fastapi | 0.162.0 | Direta de execução |
| h11 | 0.16.0 | Outra do ambiente de testes |
| httpcore | 1.0.9 | Outra do ambiente de testes |
| httptools | 0.9.0 | Outra do ambiente de testes |
| httpx | 0.28.1 | Direta de execução |
| idna | 3.20 | Outra do ambiente de testes |
| iniconfig | 2.3.1 | Outra do ambiente de testes |
| jsonalias | 0.1.1 | Outra do ambiente de testes |
| opentelemetry-api | 1.45.1 | Outra do ambiente de testes |
| packaging | 26.3 | Outra do ambiente de testes |
| pluggy | 1.7.0 | Outra do ambiente de testes |
| pycparser | 3.12 | Outra do ambiente de testes |
| pydantic | 2.14.1 | Outra do ambiente de testes |
| pydantic_core | 2.50.1 | Outra do ambiente de testes |
| Pygments | 2.21.0 | Outra do ambiente de testes |
| PyJWT | 2.15.1 | Direta de execução |
| pytest | 9.1.1 | Direta de teste |
| python-dotenv | 1.2.4 | Outra do ambiente de testes |
| PyYAML | 6.0.3 | Outra do ambiente de testes |
| solders | 0.29.0 | Direta de execução |
| starlette | 1.10.0 | Outra do ambiente de testes |
| typing-inspection | 0.4.4 | Outra do ambiente de testes |
| typing_extensions | 4.16.0 | Outra do ambiente de testes |
| uvicorn | 0.54.0 | Direta de execução |
| watchfiles | 1.3.0 | Outra do ambiente de testes |
| websockets | 15.0.1 | Direta de execução |

Outros pacotes podem servir à execução ou aos testes; esta classificação não afirma uso exclusivo em produção.
Dependências transitivas de JavaScript e pacotes de sistema da imagem não têm inventário completo nesta emissão.

## Ambiente, CI e recursos externos

- Base Docker: `python:3.12-slim` (tag mutável).
- Python no CI: `3.12`; patch não fixado.
- Fontes: Inter, JetBrains Mono; versões não declaradas no código.
- Geração opcional do PDF: ReportLab 5.0.0. Ferramenta opcional de documentação, preexistente no runtime do app; não instalada nesta tarefa. Fora da contagem de execução da aplicação.

| GitHub Action | Referência declarada |
|---|---|
| actions/checkout | v4 |
| actions/setup-python | v5 |
| docker/build-push-action | v6 |
| docker/login-action | v3 |
| docker/setup-buildx-action | v3 |

## Ferramentas da auditoria, já removidas

Fora da contagem de execução e do snapshot de 34 pacotes:

- Bandit 1.9.4.
- pip-audit 2.10.1.
- Gitleaks 8.30.1.

## Padrão de atualização

1. Ao adicionar, remover ou atualizar dependência, registrar nome, finalidade, versão/faixa e origem antes da entrega.
2. Atualizar este Markdown, o JSON e o PDF juntos. Preservar o snapshot de auditoria original.
3. Versão exata nova só pode vir de manifesto fixo ou inventário capturado em ambiente isolado/remoto aprovado; não adivinhar.
4. Não instalar dependências no Windows principal para atualizar o documento. O gerador lê os arquivos, sem instalar/resolver pacotes.
5. O CI executa o verificador sem dependências externas e reprova documentos desatualizados. Isso exige regeneração; não faz commit automático.
6. Antes de instalar, o gate confere versão triada, avisos atuais, origem e hash; a instalação usa uma relação exata temporária com hashes.

Verificar, com Python padrão já disponível:

```text
python scripts/inventario_dependencias.py --check
```

Regenerar com ReportLab já disponível em runtime confiável ou ambiente isolado aprovado, usando a data local:

```text
python scripts/inventario_dependencias.py --refresh --date AAAA-MM-DD
```

Se o gerador de PDF não estiver disponível, não instalar automaticamente no Windows; usar o ambiente aprovado.

## Arquivos e rastreabilidade

- Dados e hashes: `docs/dependencias/inventario.json`.
- PDF: `output/pdf/relatorio-dependencias.pdf`.
- Geradores: `scripts/inventario_dependencias.py` e `scripts/pdf_dependencias.py`.
- A emissão usa fontes locais e o snapshot histórico; não consultou o ambiente efetivo de produção.
- O JSON inclui o hash do PDF para detectar divergência entre os artefatos.

## Triagem de malware, vulnerabilidades e procedência

Coleta: **2026-10-25T20:44:04+00:00**. 46 versões/ferramentas avaliadas: **43 favoráveis, 2 em atenção, 1 em perigo**.

O conjunto inclui os 34 pacotes históricos Python, as versões fixadas em constraints.txt, a biblioteca JS, o gerador PDF preexistente e três ferramentas de auditoria removidas. Não são 46 dependências de execução.
Favorável significa consulta concluída sem alerta aplicável no escopo e sinais de origem; não garante ausência de malware nem autoriza instalação no Windows.
Atenção significa verificação incompleta ou origem não confirmada neste método; não é acusação de malware. Perigo exige alerta/motivo aplicável registrado.

### Popularidade e acompanhamento

Downloads são eventos do projeto, todas as versões, e não instalações ou pessoas únicas. Estrelas e assinantes são contas do repositório GitHub, não garantia de segurança.
PyPI/npm: período mensal informado pelo provedor; Gitleaks: acumulado dos arquivos da release, identificado com *. N/D é indisponível, não zero.

| Pacote / versão | Papel | Downloads no período | Estrelas | Assinantes | Triagem |
|---|---|---|---|---|---|
| annotated-doc 0.0.5 | snapshot indireto/suporte | 398.390.693 | 82 | 0 | Favorável |
| annotated-types 0.8.0 | snapshot indireto/suporte | 729.630.352 | 615 | 9 | Favorável |
| anyio 4.15.1 | snapshot indireto/suporte | 802.491.233 | 2.558 | 27 | Favorável |
| certifi 2026.10.23 | fixada em constraints.txt (excecao: correcao de seguranca) | 1.286.781.208 | 1.022 | 38 | Favorável |
| cffi 2.1.1 | snapshot indireto/suporte | 947.049.149 | 285 | 10 | Favorável |
| click 8.5.0 | snapshot indireto/suporte | 817.486.347 | 17.801 | 182 | Favorável |
| colorama 0.4.6 | snapshot indireto/suporte | 246.918.496 | 3.796 | 42 | Favorável |
| cryptography 50.0.2 | execução direta | 1.068.178.556 | 7.824 | 132 | Favorável |
| fastapi 0.162.0 | execução direta | 381.578.963 | 104.168 | 770 | Favorável |
| h11 0.16.0 | snapshot indireto/suporte | 713.263.467 | 571 | 15 | Favorável |
| httpcore 1.0.9 | snapshot indireto/suporte | 616.032.625 | 551 | 23 | Favorável |
| httptools 0.9.0 | snapshot indireto/suporte | 215.330.382 | 1.328 | 34 | Favorável |
| httpx 0.28.1 | execução direta | 618.500.392 | 15.800 | 150 | Favorável |
| idna 3.20 | snapshot indireto/suporte | 1.343.340.011 | 299 | 11 | Favorável |
| iniconfig 2.3.1 | snapshot indireto/suporte | 737.973.073 | 63 | 3 | Favorável |
| jsonalias 0.1.1 | snapshot indireto/suporte | 1.589.796 | N/D | N/D | Favorável |
| opentelemetry-api 1.45.1 | snapshot indireto/suporte | 443.719.489 | 2.690 | 41 | Favorável |
| packaging 26.3 | snapshot indireto/suporte | 1.511.871.245 | 752 | 26 | Favorável |
| pluggy 1.7.0 | snapshot indireto/suporte | 856.331.218 | 1.704 | 19 | Favorável |
| pycparser 3.12 | snapshot indireto/suporte | 839.516.278 | 3.580 | 85 | Favorável |
| pydantic 2.14.1 | snapshot indireto/suporte | 842.451.944 | 29.175 | 174 | Favorável |
| pydantic_core 2.50.1 | snapshot indireto/suporte | 807.865.749 | 29.175 | 174 | Favorável |
| Pygments 2.21.0 | snapshot indireto/suporte | 919.257.931 | 2.218 | 41 | Favorável |
| PyJWT 2.15.1 | execução direta | 574.600.226 | 5.721 | 58 | Favorável |
| pytest 9.1.1 | teste direto | 761.970.029 | 14.643 | 194 | Favorável |
| python-dotenv 1.2.4 | snapshot indireto/suporte | 582.189.812 | 8.904 | 35 | Favorável |
| PyYAML 6.0.3 | snapshot indireto/suporte | 910.520.274 | 2.959 | 51 | Favorável |
| solders 0.29.0 | execução direta | 1.669.387 | 449 | 5 | Favorável |
| starlette 1.10.0 | snapshot indireto/suporte | 500.961.483 | 12.684 | 98 | Favorável |
| typing-inspection 0.4.4 | snapshot indireto/suporte | 701.701.820 | 71 | 3 | Favorável |
| typing_extensions 4.16.0 | snapshot indireto/suporte | 1.396.475.070 | 591 | 17 | Favorável |
| uvicorn 0.54.0 | execução direta | 499.065.051 | 11.036 | 93 | Favorável |
| watchfiles 1.3.0 | snapshot indireto/suporte | 303.627.277 | 2.552 | 15 | Favorável |
| websockets 15.0.1 | execução direta | 401.505.282 | 5.739 | 107 | Favorável |
| @supabase/supabase-js 2.118.0 | JavaScript direto | 114.658.331 | 4.600 | 65 | Favorável |
| reportlab 4.4.9 | documentação opcional preexistente | 66.000.604 | N/D | N/D | Atenção |
| bandit 1.9.4 | ferramenta de auditoria removida | 24.417.585 | 8.347 | 70 | Favorável |
| pip-audit 2.10.1 | ferramenta de auditoria removida | 26.723.596 | 1.383 | 27 | Favorável |
| gitleaks 8.30.1 | ferramenta de auditoria removida | 18.098.461* | 30.321 | 179 | Atenção |
| certifi 2026.7.22 | rejeitada: aviso GHSA-6q48-6c7w-9gw2 (nao usar) | 1.286.781.208 | 1.022 | 38 | Perigo |
| fastapi 0.143.0 | fixada em constraints.txt (14+ dias) | 381.578.963 | 104.168 | 770 | Favorável |
| pluggy 1.6.0 | fixada em constraints.txt (14+ dias) | 856.331.218 | N/D | N/D | Favorável |
| pycparser 3.11 | fixada em constraints.txt (14+ dias) | 839.516.278 | 3.580 | 85 | Favorável |
| starlette 1.7.0 | fixada em constraints.txt (14+ dias) | 500.961.483 | 12.684 | 98 | Favorável |
| uvloop 0.23.0 | fixada em constraints.txt (14+ dias) | 216.734.647 | 11.913 | 216 | Favorável |
| tzdata 2026.5 | execução direta (fuso do /health), fixada em constraints.txt | 382.367.011 | 121 | 11 | Favorável |

### Pendências e motivos

- **jsonalias 0.1.1 (Favorável):** Revisao manual: Os metadados da 0.1.1 nao trazem link de repositorio, por isso o coletor marca atencao. Revisao manual: o solders 0.29.0 exige exatamente jsonalias==0.1.1; mesmo autor do solders (Kevin Heavey); a versao 0.1.2 do mesmo projeto aponta github.com/kevinheavey/jsonalias (nao arquivado); release de 2022 sem alertas OSV. Nao e auditoria do codigo.
- **reportlab 4.4.9 (Atenção):** Repositorio de origem sem confirmacao pela API GitHub nesta coleta; metrica ausente nao prova risco.
- **gitleaks 8.30.1 (Atenção):** Consulta de seguranca incompleta ou ecossistema nao coberto nesta coleta.
- **certifi 2026.7.22 (Perigo):** Aviso de vulnerabilidade para a versao consultada; nao equivale a malware; bloquear ate triagem.
- **pluggy 1.6.0 (Favorável):** Revisao manual: Os metadados da 1.6.0 nao trazem link de repositorio. Revisao manual: dependencia so de teste (pytest), do projeto pytest-dev; a 1.7.0 do mesmo pacote aponta github.com/pytest-dev/pluggy (nao arquivado); release de 2025 sem alertas OSV. Nao entra na imagem de producao.

### Procedimento obrigatório antes de cada instalação

- Versões exatas ficam em constraints.txt. Nome/versão não triados, alerta atual (OSV/PyPI consultados a cada build) ou consulta indisponível bloqueiam a instalação.
- Resolver somente metadados de wheels em CI/imagem, sem instalar nem executar sdists; validar candidatos com OSV e registro ao vivo.
- Instalar apenas versões e hashes aprovados para aquela execução, sem resolver novas dependências durante a instalação.
- JavaScript externo exige versão fixa, registro npm triado e SRI; o gate não substitui auditoria do código do bundle.
- Pendências que o coletor não resolve sozinho (ex.: release sem link de repositório) recebem revisão manual registrada em docs/dependencias/revisoes-manuais.json; revisão manual nunca anula alerta.
- Pacotes do SO/base Docker e Actions por tags continuam exigindo análise própria; não estão certificados por esta triagem Python/npm.
- O coletor consulta JSON/APIs, sem baixar/importar/executar os pacotes. Popularidade nunca é motivo único de aprovação.

Política completa: `docs/dependencias/POLITICA-DE-DEPENDENCIAS.md`. Pesquisa de relatos: `docs/dependencias/pesquisa-malware.md`.
Fontes, períodos e datas por pacote: `docs/dependencias/triagem-seguranca.json`.

Atualizar a coleta antes de mudar versão, usando apenas Python padrão e acesso às APIs:

```text
python scripts/coletar_risco_dependencias.py --help
```

Após revisar os resultados, regenerar Markdown/JSON/PDF e executar --check. As regras só entram no CI remoto após commit/push.
