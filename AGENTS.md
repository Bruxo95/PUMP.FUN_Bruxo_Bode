# Instruções para agentes — PUMP.FUN Bruxo Bode

Antes de trabalhar, leia `CLAUDE.md` inteiro. Ele é o contexto compartilhado deste
projeto para Claude Code, Codex e Cursor. Leia também `README.md` e
`docs/ORIGEM.md` quando a tarefa envolver instalação ou arquitetura.

Para segurança, leia `docs/AUDITORIA-SEGURANCA.md`: contém o escopo, as evidências,
os achados e o ponto de retomada. Atualize seu checklist ao concluir cada etapa
relevante e antes de encerrar a tarefa; mantenha no `CLAUDE.md` apenas o resumo e
o link, sem duplicar o relatório nem registrar segredos.

Em cada auditoria, registrar data, versão da aplicação, SHA completo do código
auditado, IA/família e identificador exato do modelo quando disponível, estado dos
achados e próxima ação. Se o identificador da IA não estiver exposto, declarar isso;
nunca adivinhar. Associar os arquivos brutos dos scanners a essa identificação por
um manifesto, preservando seus formatos e a base histórica auditada.

Preferência do usuário (2026-10-25): não instalar dependências ou ferramentas deste
projeto no Windows principal. Os ambientes locais foram removidos a pedido dele.
Não recriar `.venv`, instalar scanners nem reinstalar pacotes para rodar testes sem
combinar antes um ambiente de execução isolado/remoto com o usuário. Registrar a
limitação de testes quando esse ambiente ainda não estiver disponível.

**Antes de todo push/deploy: `git pull` (ou `git fetch` + rebase) no `main`, integrar o que chegou, rodar a checagem e os testes e, se aparecer erro, corrigir ANTES de enviar.** Outra IA (Codex) e o dono também enviam ao mesmo repositório; push sem pull rejeita ou atropela a versão deles. Se a versão já foi usada por outro, subir para a próxima. Pedido do dono em 2026-10-25.

Inventário permanente de dependências: `docs/DEPENDENCIAS.md`, dados em
`docs/dependencias/inventario.json` e PDF em `output/pdf/relatorio-dependencias.pdf`.
Sempre que adicionar, remover ou atualizar dependências, extras, runtime, Actions,
scripts externos ou o snapshot usado, atualizar os três artefatos juntos com
`scripts/inventario_dependencias.py --refresh --date AAAA-MM-DD` em runtime com PDF
preexistente ou ambiente isolado/remoto aprovado. Não instalar pacotes no Windows.
Antes de publicar, executar `scripts/inventario_dependencias.py --check` com Python
padrão já disponível; o CI também verifica. Preservar versões históricas, informar
versão/faixa não fixada e nunca inventar a resolução efetiva em produção.

Antes de instalar ou atualizar qualquer versão, seguir
`docs/dependencias/POLITICA-DE-DEPENDENCIAS.md`: consultar malware/vulnerabilidades
e origem para nome/ecossistema/versão exatos, registrar data/fontes/classificação
em `docs/dependencias/triagem-seguranca.json` e atualizar o PDF. Usar downloads,
estrelas e assinantes apenas como contexto, nunca como garantia de segurança.
Versões não triadas, consultas incompletas/antigas ou alertas aplicáveis devem
bloquear a instalação até avaliação. Não contornar o gate nem reinstalar no Windows.

- Mantenha decisões, pendências e resultados de validação no `CLAUDE.md`, sem
  duplicar a memória em arquivos específicos de cada ferramenta.
- Confira o código e o estado atual do Git; diferencie informações históricas de
  verificações feitas na tarefa atual. Nunca registre senhas, tokens ou chaves.
- Neste projeto, "deploy" significa somente commit e push para
  `https://github.com/Bruxo95/PUMP.FUN_Bruxo_Bode`, com o workflow existente do
  GitHub Actions. Não acesse nem altere VPS, SSH, Portainer, Supabase remoto,
  servidores ou outros projetos sem uma solicitação explícita para essa ação.
- Antes de enviar alterações, confirme que o remoto pertence a este repositório.
  Informe o commit, as verificações realizadas e o que não foi validado.

Ao corrigir algo a partir de um relatório do dia, crie também `app/relatorios_ia/AAAA-MM-DD-versao.md` (formato em `app/changes.py`) com a projeção de ganho. Detalhes no CLAUDE.md.
