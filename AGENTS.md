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
