"""Renderizacao documental opcional. Usa ReportLab preexistente, sem instalacao."""
from __future__ import annotations

from html import escape
from pathlib import Path


def create_pdf(data: dict, output: Path, fingerprint: str) -> None:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    import reportlab
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
                                   PageBreak, KeepTogether, LongTable)

    fonts = Path(reportlab.__file__).resolve().parent / 'fonts'
    for name, filename in [('ReportSans','Vera.ttf'),('ReportSans-Bold','VeraBd.ttf'),
                           ('ReportSans-Italic','VeraIt.ttf'),('ReportSans-BoldItalic','VeraBI.ttf')]:
        pdfmetrics.registerFont(TTFont(name, str(fonts / filename)))
    pdfmetrics.registerFontFamily('ReportSans', normal='ReportSans', bold='ReportSans-Bold',
                                 italic='ReportSans-Italic', boldItalic='ReportSans-BoldItalic')
    navy, teal, ink = colors.HexColor('#142D40'), colors.HexColor('#087E83'), colors.HexColor('#243747')
    muted, pale, line = colors.HexColor('#647586'), colors.HexColor('#F1F6F8'), colors.HexColor('#D8E3E8')
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle('ReportTitle', fontName='Helvetica-Bold', fontSize=27, leading=30, textColor=navy, spaceAfter=12))
    styles.add(ParagraphStyle('SectionTitle', fontName='Helvetica-Bold', fontSize=16, leading=20, textColor=navy, spaceAfter=10))
    styles.add(ParagraphStyle('Lead', fontName='Helvetica', fontSize=10.2, leading=14, textColor=ink, spaceAfter=9))
    styles.add(ParagraphStyle('SmallNote', fontName='Helvetica', fontSize=8.2, leading=11, textColor=muted, spaceAfter=7))
    styles.add(ParagraphStyle('Cell', fontName='Helvetica', fontSize=9, leading=11.5, textColor=ink))
    styles.add(ParagraphStyle('CellSmall', parent=styles['Cell'], fontSize=8.5, leading=10.5))
    styles.add(ParagraphStyle('HeadCell', fontName='Helvetica-Bold', fontSize=8.5, leading=11, textColor=colors.white))
    styles.add(ParagraphStyle('Metric', fontName='Helvetica-Bold', fontSize=25, leading=29, textColor=teal))
    styles.add(ParagraphStyle('MetricLabel', parent=styles['SmallNote'], fontSize=8.7, leading=11, spaceAfter=0))
    for style in styles.byName.values():
        if getattr(style, 'fontName', None) == 'Helvetica':
            style.fontName = 'ReportSans'
        elif getattr(style, 'fontName', None) == 'Helvetica-Bold':
            style.fontName = 'ReportSans-Bold'

    def p(value, style='Lead'):
        return Paragraph(escape(str(value)), styles[style])

    def rich(value, style='Lead'):
        return Paragraph(value, styles[style])

    def table(headers, rows, widths, small=False):
        content = [[p(h,'HeadCell') for h in headers]]
        content += [[p(c, 'CellSmall' if small else 'Cell') for c in row] for row in rows]
        t = LongTable(content, colWidths=widths, repeatRows=1, hAlign='LEFT')
        t.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0),navy), ('VALIGN',(0,0),(-1,-1),'TOP'),
            ('LEFTPADDING',(0,0),(-1,-1),6 if small else 9), ('RIGHTPADDING',(0,0),(-1,-1),6 if small else 9),
            ('TOPPADDING',(0,0),(-1,0),9), ('BOTTOMPADDING',(0,0),(-1,0),9),
            ('TOPPADDING',(0,1),(-1,-1),2.2 if small else 7),
            ('BOTTOMPADDING',(0,1),(-1,-1),2.2 if small else 7),
            ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,pale]),
            ('LINEBELOW',(0,0),(-1,0),0.8,navy),
            ('LINEBELOW',(0,1),(-1,-1),0.3,line),
        ]))
        return t

    width = A4[0] - 88
    doc = SimpleDocTemplate(str(output), pagesize=A4, rightMargin=44, leftMargin=44,
        topMargin=67, bottomMargin=47, title='Inventário de dependências - PUMP FUN COPY',
        author=data['issuer'], subject='source-digest:'+fingerprint)
    story = []
    c, snap, tools = data['counts'], data['python_observed_snapshot'], data['toolchain']

    def on_page(canvas, current_doc):
        canvas.saveState()
        canvas.setFillColor(navy)
        canvas.rect(0,A4[1]-40,A4[0],40,fill=1,stroke=0)
        canvas.setFillColor(colors.white)
        canvas.setFont('ReportSans-Bold',9)
        canvas.drawString(44,A4[1]-25,'PUMP FUN COPY  /  CONTROLE DE DEPENDÊNCIAS')
        canvas.setFont('ReportSans',8)
        canvas.setFillColor(muted)
        canvas.drawString(44,28,f"Emissão {data['generated_date']}  |  Aplicação {data['application_version'].split(' · ')[0]}  |  Revisão {data['document_revision']}")
        canvas.drawRightString(A4[0]-44,28,f"Página {current_doc.page}")
        canvas.restoreState()

    story += [p('Inventário de\ndependências'.replace('\n',' '),'ReportTitle'),
        p('Nomes, versões e regras para manter o projeto documentado.'), Spacer(1,7)]
    metrics = Table([[p(c['runtime_direct_total'],'Metric'),p(c['python_observed_snapshot'],'Metric'),p(c['github_actions_unique'],'Metric')],
        [p('diretas de execução\nPython + JavaScript','MetricLabel'),p('pacotes Python\nsnapshot histórico','MetricLabel'),p('Actions únicas\nferramentas de CI','MetricLabel')]],colWidths=[width/3]*3)
    metrics.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),pale),('BOX',(0,0),(-1,-1),0.5,line),
        ('LEFTPADDING',(0,0),(-1,-1),13),('TOPPADDING',(0,0),(-1,0),11),('BOTTOMPADDING',(0,1),(-1,1),12),('VALIGN',(0,0),(-1,-1),'TOP')]))
    story += [metrics,Spacer(1,15),rich(f"<b>Versão do projeto:</b> {escape(data['application_version'])}<br/>"
        f"<b>Referência Git:</b> {data['repository_reference'][:12]} | <b>Emissão:</b> {data['generated_date']}", 'SmallNote'),
        p('01  Dependências declaradas','SectionTitle')]
    rows=[]
    for r in data['python_runtime_direct']:
        rows.append([r['name']+r['extras'],r['constraint'],r['observed_version'] or 'Não registrada'])
    story += [table(['Python / execução','Faixa declarada','Versão histórica'],rows,[width*.40,width*.27,width*.33]),Spacer(1,9)]
    js=data['javascript_runtime_direct']
    for r in js:
        story.append(rich(f"<b>JavaScript:</b> {escape(r['name'])} <b>{escape(r['version'])}</b> - CDN com integridade SRI registrada.",'Lead'))
    for r in data['python_test_direct']:
        story.append(rich(f"<b>Teste:</b> {escape(r['name'])} - versão declarada {escape(r['constraint'])}; observada {escape(r['observed_version'] or 'não registrada')}.",'Lead'))
    story += [p(f"As {c['python_runtime_direct']} dependências Python e {c['javascript_runtime_direct']} JavaScript formam as {c['runtime_direct_total']} diretas de execução. O pytest é contado separadamente. Extras [standard] e [crypto] não são pacotes adicionais por si só.",'SmallNote'),
        p('As faixas permitem versões diferentes em instalações futuras. As versões históricas foram registradas na auditoria e não representam um inventário da produção.','SmallNote'),PageBreak()]

    story += [p('02  Pacotes Python observados','SectionTitle'),
        p(f"Snapshot de {snap['date']} | aplicação {snap['application_version']} | Python {snap['python']} | commit {snap['commit'][:12]}",'SmallNote'),
        rich('<b>Ambiente já removido do Windows principal.</b> Esta lista preserva evidência histórica de testes, incluindo bibliotecas indiretas; não indica pacotes atualmente instalados.','Lead')]
    category={'Direta de execução':'Execução direta','Direta de teste':'Teste direto','Outra do ambiente de testes':'Indireta / suporte*'}
    story += [table(['Nome do pacote','Versão exata observada','Classificação'],
        [[r['name'],r['version'],category[r['category']]] for r in snap['packages']],
        [width*.41,width*.28,width*.31],small=True),Spacer(1,8),
        p(f"* {c['other_observed_python']} outros pacotes estavam no ambiente de testes; podem servir à execução ou aos testes. Não representam uso exclusivo em produção. Não somar os {c['python_observed_snapshot']} aos diretos: haveria dupla contagem.",'SmallNote'),PageBreak()]

    story += [p('03  Ambiente e manutenção','SectionTitle'),
        rich(f"<b>Docker:</b> {escape(tools['docker_base'])}<br/><b>Python no CI:</b> {escape(tools['ci_python'])} - patch não fixado.<br/><b>Fontes externas:</b> {escape(', '.join(tools['fonts']))} - sem versão declarada.",'Lead'),
        table(['GitHub Action','Referência'],[[r['name'],r['ref']] for r in tools['github_actions']],[width*.73,width*.27]),Spacer(1,11),
        rich('<b>Ferramentas da auditoria, removidas:</b> '+ '; '.join(escape(r['name']+' '+r['version']) for r in data['audit_tools_removed'])+'. Não fazem parte da contagem de execução.','SmallNote'),
        rich(f"<b>Gerador opcional deste PDF:</b> ReportLab {escape(tools['pdf_generator']['version'])}, já incluído no runtime do aplicativo. Nenhum pacote foi instalado nesta tarefa; ferramenta fora da execução do projeto.",'SmallNote'),
        p('Padrão para qualquer alteração','SectionTitle')]
    rules=[
        'Registrar inclusão, remoção ou atualização, com nome, finalidade, origem e versão/faixa.',
        'Atualizar juntos o Markdown, o JSON e este PDF. O CI reprova fontes ou artefatos divergentes; não publica correções automaticamente.',
        'Versão exata nova precisa de manifesto fixo ou inventário de ambiente isolado/remoto aprovado. Preservar o snapshot histórico, sem adivinhar versões.',
        'Não instalar dependências no Windows principal para manter este documento. O gerador lê os arquivos e usa recurso de PDF preexistente ou ambiente aprovado.',
    ]
    for i,rule in enumerate(rules,1):
        story.append(p(f'{i}. {rule}'))
    story += [Spacer(1,3),rich('<b>Verificação:</b> python scripts/inventario_dependencias.py --check<br/>'
        '<b>Atualização:</b> python scripts/inventario_dependencias.py --refresh --date AAAA-MM-DD','SmallNote'),
        p('Fontes e limites','SectionTitle'),
        p('Fontes: requirements.txt, HTMLs do projeto, Dockerfile, workflow de imagem e snapshot da auditoria de 25/10/2026. Hashes completos e origem das versões estão no JSON do inventário.','SmallNote'),
        p('As versões Python são fixadas em constraints.txt; cada build verifica os candidatos e gera uma lista temporária com hashes. O inventário de dependências transitivas JavaScript, da imagem efetiva e dos pacotes do sistema operacional permanece pendente. Este documento não substitui a auditoria de segurança.','SmallNote'),
        p('Memória: AGENTS.md e CLAUDE.md. Dados: docs/dependencias/inventario.json. Documento editável: docs/DEPENDENCIAS.md. Emissão: '+data['issuer']+'. Auditoria original: OpenAI Codex, família GPT-6.','SmallNote')]
    # 04 - triagem antes de instalar (pedido do dono em 2026-10-25): malware/avisos,
    # popularidade so como contexto e classificacao Favoravel/Atencao/Perigo com motivo.
    sec, sc = data['security_review'], data['security_counts']
    level_name = {'favorable': 'Favorável', 'attention': 'Atenção', 'danger': 'Perigo'}
    level_color = {'favorable': colors.HexColor('#CFEEDB'), 'attention': colors.HexColor('#FBE7B5'),
                   'danger': colors.HexColor('#F6C9C3')}

    def number(value):
        return 'N/D' if value is None else f"{value:,}".replace(',', '.')

    story += [PageBreak(), p('04  Triagem de segurança antes de instalar','SectionTitle'),
        p(f"Coleta {sec['collected_at'][:16].replace('T',' ')} UTC | {sc['reviewed']} versões avaliadas | IA: {sec['reviewer'].get('agent')} {sec['reviewer'].get('exact_model_id') or ''}",'SmallNote')]
    counts = Table([[p(sc['favorable'],'Metric'),p(sc['attention'],'Metric'),p(sc['danger'],'Metric')],
        [p('Favorável','MetricLabel'),p('Atenção','MetricLabel'),p('Perigo','MetricLabel')]],colWidths=[width/3]*3)
    counts.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),pale),('BOX',(0,0),(-1,-1),0.5,line),
        ('LEFTPADDING',(0,0),(-1,-1),13),
        ('TOPPADDING',(0,0),(-1,0),11),('BOTTOMPADDING',(0,1),(-1,1),12),('VALIGN',(0,0),(-1,-1),'TOP')]))
    story += [counts, Spacer(1,10),
        rich('<b>Favorável:</b> versão existe no registro oficial, origem confirmada e nenhum aviso de malware ou vulnerabilidade (OSV) nesta data. Não é garantia de código livre de malware.<br/>'
             '<b>Atenção:</b> faltou confirmar algo (origem, cobertura da consulta). Não é acusação de malware; não instalar até revisar.<br/>'
             '<b>Perigo:</b> aviso aplicável à versão (malware, vulnerabilidade ou release retirada). Bloqueado.','SmallNote'),
        rich('<b>Downloads</b> = eventos do último mês, todas as versões, inclui robôs de CI; não é número de instalações nem de pessoas. '
             '<b>Estrelas</b> e <b>assinantes</b> (pessoas acompanhando o repositório no GitHub) são só contexto: popularidade não aprova nenhum pacote. N/D = indisponível.','SmallNote')]
    rows, styles_rows = [], []
    for i, r in enumerate(sec['packages'], 1):
        dl, gh, lv = r['popularity']['downloads'], r['popularity']['github'], r['classification']['level']
        star = '*' if r['ecosystem'] == 'GitHubRelease' else ''
        rows.append([f"{r['name']} {r['version']}", r['role'], number(dl.get('count'))+star,
                     number(gh.get('stars')), number(gh.get('subscribers')), level_name[lv]])
        styles_rows.append(('BACKGROUND',(5,i),(5,i),level_color[lv]))
    t = table(['Pacote / versão','Papel','Downloads/mês','Estrelas','Assinantes','Triagem'], rows,
              [width*.24,width*.24,width*.18,width*.10,width*.13,width*.11], small=True)
    t.setStyle(TableStyle(styles_rows))
    story += [t, Spacer(1,6), p('Cor da coluna Triagem: verde = Favorável, amarelo = Atenção, vermelho = Perigo. * Gitleaks: soma de downloads da release desde a publicação.','SmallNote'),
              p('Motivos de Atenção, Perigo e revisões manuais','SectionTitle')]
    for r in sec['packages']:
        c = r['classification']
        if c['level'] != 'favorable' or c.get('manual_review'):
            story.append(rich(f"<b>{escape(r['name'])} {escape(r['version'])} — {level_name[c['level']]}:</b> "
                              + escape(' '.join(c['reasons'])) + (' <b>Avisos:</b> ' + escape(', '.join(r['advisories']['ids'])) if r['advisories'].get('ids') else ''),'Lead'))
    story += [p('Como a regra é aplicada','SectionTitle')]
    for i, rule in enumerate([
        'Versões exatas ficam em constraints.txt; só entra versão publicada há 14 dias ou mais (exceção apenas para correção de segurança, anotada no arquivo).',
        'Versão nova: rodar scripts/coletar_risco_dependencias.py, revisar Atenção/Perigo, regenerar este PDF e só então trocar constraints.txt.',
        'O CI e o Dockerfile resolvem só metadados, conferem a triagem e consultam OSV e PyPI ao vivo; qualquer versão não triada, aviso atual ou falha de consulta bloqueia a instalação.',
        'A instalação usa exatamente as versões e hashes SHA-256 aprovados, sem resolver nada novo.'], 1):
        story.append(p(f'{i}. {rule}'))
    doc.build(story,onFirstPage=on_page,onLaterPages=on_page)
