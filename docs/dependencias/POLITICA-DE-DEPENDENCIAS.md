# Política de triagem antes de instalar dependências

Data: 2026-10-25. Aplicação de referência: 0.8.2. Responsável: OpenAI Codex,
família GPT-6; identificador exato do modelo/revisão não exposto na sessão.

## Regra solicitada pelo usuário

Antes de instalar, atualizar ou aprovar uma nova versão, verificar o pacote e a
versão exatos, o ecossistema, a origem e avisos públicos de malware, vulnerabilidade
ou comprometimento. Registrar a consulta, fontes e conclusão e atualizar
Markdown/JSON/PDF. Não instalar dependências no Windows principal, mesmo quando
os sinais forem favoráveis; execução isolada/remota continua exigindo combinação.

## Sinais e classificação

- **Favorável:** versão localizada no registro oficial, não retirada/yanked, origem
  identificada e consultas de segurança concluídas sem alerta para a versão no
  escopo consultado. Significa sinais favoráveis, não atestado de código livre de malware.
- **Atenção / não aprovado:** origem ou consulta incompleta, pacote/repositório
  indisponível/arquivado, versão não verificada ou outro ponto que exija análise.
  Não instalar automaticamente até resolver a pendência.
- **Perigo / bloquear:** aviso conhecido aplicável à versão, relato de malware
  aplicável, versão retirada por segurança ou indicação de comprometimento.
  CVE não é sinônimo de malware: o motivo e o identificador precisam ficar claros.

Downloads, estrelas ou assinantes **não aprovam** um pacote por si só. Métrica
indisponível deve ser N/D, nunca zero inventado. Não rotular um mantenedor como
malicioso sem evidência. Conferir ecossistema e nome: `pydantic` no npm não é o
mesmo pacote que `pydantic` no PyPI, por exemplo.

## O que os números do relatório significam

- PyPI Stats e npm informam eventos de download do projeto, geralmente todas as
  versões no período; não são instalações únicas, pessoas únicas nem uso da versão avaliada.
- Estrelas são `stargazers_count` do GitHub.
- Pessoas acompanhando são aproximadas por contas assinantes do repositório,
  `subscribers_count`. `watchers_count` não deve ser usado como se fosse essa medida.
- Esses números são contextuais, mudam com o tempo e podem incluir automações.

## Procedimento antes de uma instalação nova

1. Identificar nome canônico, ecossistema, versão exata, finalidade e origem oficial.
2. Consultar OSV e suas fontes, incluindo OpenSSF Malicious Packages quando aplicável,
   avisos do mantenedor/registro e relatos públicos relevantes. Separar vulnerabilidade,
   malware, pacote homônimo/typosquat e simples hipótese.
3. Conferir existência da versão, retirada/yank, URL e hash do artefato. Quando houver
   attestations, considerar sua verificação; atestação prova origem, não inocuidade do código.
4. Registrar data, fontes, indisponibilidades e classificação no arquivo
   `triagem-seguranca.json`; regenerar o inventário e o PDF antes da entrega.
5. Fixar a versão exata em `constraints.txt` (publicada há 14 dias ou mais; exceção só
   para correção de segurança, registrada no próprio arquivo). Cada build repete a consulta
   OSV/PyPI ao vivo. Versão sem triagem, alerta atual ou falha de consulta bloqueia a
   instalação até nova avaliação. Popularidade não contorna o bloqueio.
6. No CI/imagem, resolver somente wheels com `--dry-run --only-binary=:all:`; não
   executar fonte/sdist para preparar metadados. Conferir os candidatos antes de instalar.
7. Instalar somente a relação exata aprovada, com hashes, sem nova resolução de
   dependências. O lock temporário do gate vale para aquela execução e não é uma
   aprovação de versões futuras permitidas pelas faixas de `requirements.txt`.

## Manutenção e limites

O coletor usa somente APIs/metadados públicos. Não baixa/importa/executa o código
dos pacotes avaliados. O verificador não torna o restante do sistema invulnerável,
e fontes públicas podem demorar a registrar um ataque novo. Não há garantia absoluta
de detecção de malware ou de comprometimento de um mantenedor.

Versões novas de dependências transitivas ou diferenças entre Windows e Linux devem
ser triadas antes de liberar uma execução. Um build bloqueado por versão desconhecida
é uma pendência a resolver, não motivo para desativar a verificação.

As alterações desta política e dos gates só passam a valer no GitHub após publicação;
não afirmar que o CI remoto foi alterado enquanto os arquivos forem apenas locais.

## Fontes metodológicas

- [OSV e fontes de dados](https://google.github.io/osv.dev/).
- [OpenSSF Malicious Packages](https://github.com/ossf/malicious-packages).
- [Documentação do PyPI](https://docs.pypi.org/).
- [Métricas PyPI Stats](https://pypistats.org/api/).
- [API de downloads do npm](https://github.com/npm/registry/blob/main/docs/download-counts.md).
