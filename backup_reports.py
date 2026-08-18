import io
import csv
import json
import base64
import os
import datetime
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

def obter_servico_drive(credentials_raw):
    """Autentica e retorna o serviço do Google Drive API."""
    SCOPES = ['https://www.googleapis.com/auth/drive']
    
    if os.path.exists("credentials.json"):
        creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
    else:
        creds_json = None
        if isinstance(credentials_raw, str):
            try:
                decoded = base64.b64decode(credentials_raw.strip())
                creds_json = json.loads(decoded.decode("utf-8"))
            except Exception:
                try:
                    creds_json = json.loads(credentials_raw)
                except Exception:
                    pass
        elif isinstance(credentials_raw, dict):
            creds_json = credentials_raw

        if creds_json and "private_key" in creds_json:
            pk = str(creds_json["private_key"]).strip('"\'').replace("\\n", "\n")
            creds_json["private_key"] = pk
            creds = Credentials.from_service_account_info(creds_json, scopes=SCOPES)
        else:
            raise ValueError("Credenciais do Google Drive inválidas.")

    return build('drive', 'v3', credentials=creds)

def listar_backups_csv(service, folder_id):
    """Lista todos os arquivos CSV salvos na pasta de relatórios/backups."""
    query = f"'{folder_id}' in parents and mimeType='text/csv' and trashed=false"
    resultados = service.files().list(
        q=query,
        spaces='drive',
        supportsAllDrives=True,
        includeItemsFromAllDrives=True,
        fields='files(id, name, createdTime)'
    ).execute()
    return resultados.get('files', [])

def ler_csv_drive(service, file_id):
    """Lê um CSV de backup do Drive e converte em lista de dicionários."""
    request = service.files().get_media(fileId=file_id)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    
    buffer.seek(0)
    conteudo = buffer.getvalue().decode('utf-8-sig')
    leitor = csv.DictReader(io.StringIO(conteudo), delimiter=';')
    return list(leitor)

def formar_real(valor):
    try:
        val = float(str(valor).replace("R$", "").replace(".", "").replace(",", ".").strip())
        return "{:,.2f}".format(val).replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "0,00"

def converter_backup_csv_para_pdf(dados_csv, nome_periodo="HISTÓRICO"):
    """Gera um PDF formatado em paisagem (A4) a partir dos dados do CSV de backup."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=15, leftMargin=15, topMargin=20, bottomMargin=20
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'TitleStyle', parent=styles['Heading1'], fontSize=16, leading=18,
        alignment=1, textColor=colors.HexColor('#0f172a'), fontName='Helvetica-Bold'
    )
    subtitle_style = ParagraphStyle(
        'SubTitleStyle', parent=styles['Normal'], fontSize=10, leading=12,
        alignment=1, textColor=colors.HexColor('#475569'), fontName='Helvetica-Bold'
    )

    elements = [
        Paragraph(f"<b>CONTROLE DE COMPRAS - {nome_periodo.upper()}</b>", title_style),
        Paragraph("VITAL C", subtitle_style),
        Spacer(1, 12)
    ]

    header_style = ParagraphStyle('TH', fontSize=8, leading=10, fontName='Helvetica-Bold', textColor=colors.white, alignment=1)
    header_yellow_style = ParagraphStyle('THY', fontSize=8, leading=10, fontName='Helvetica-Bold', textColor=colors.HexColor('#0f172a'), alignment=1)

    def style_th(text, bg_color):
        p_style = header_yellow_style if bg_color == '#eab308' else header_style
        return Paragraph(f"<b>{text}</b>", p_style)

    th_cells = [
        style_th("Mês / Data", '#eab308'), style_th("Produto", '#eab308'),
        style_th("Fornecedor A", '#eab308'), style_th("Fornecedor B", '#eab308'),
        style_th("Fornecedor C", '#eab308'), style_th("Média Orçamentos", '#065f46'),
        style_th("Preço Alvo<br/>(Média -10%)", '#1d4ed8'), style_th("Valor Comprado", '#eab308'),
        style_th("Economia Real", '#065f46'), style_th("Status Meta", '#065f46')
    ]

    data = [th_cells]
    cell_style = ParagraphStyle('TD', fontSize=8, leading=10, fontName='Helvetica', alignment=1)
    cell_left = ParagraphStyle('TDL', fontSize=8, leading=10, fontName='Helvetica-Bold', alignment=0)
    cell_bold = ParagraphStyle('TDB', fontSize=8, leading=10, fontName='Helvetica-Bold', alignment=1)

    tot_orcam_geral = 0.0
    tot_alvo_geral = 0.0
    tot_comprado_geral = 0.0
    tot_economia_geral = 0.0

    table_styles = [
        ('BACKGROUND', (0,0), (4,0), colors.HexColor('#eab308')),
        ('BACKGROUND', (5,0), (5,0), colors.HexColor('#065f46')),
        ('BACKGROUND', (6,0), (6,0), colors.HexColor('#1d4ed8')),
        ('BACKGROUND', (7,0), (7,0), colors.HexColor('#eab308')),
        ('BACKGROUND', (8,0), (9,0), colors.HexColor('#065f46')),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
        ('TOPPADDING', (0,0), (-1,-1), 5), ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING', (0,0), (-1,-1), 3), ('RIGHTPADDING', (0,0), (-1,-1), 3),
    ]

    for row_idx, item in enumerate(dados_csv, start=1):
        dt_formatted = item.get("data_cotacao") or item.get("data") or "N/A"
        prod = item.get("produto") or item.get("item_descricao") or "N/A"
        forn_a = item.get("fornecedor_a", "N/A")
        forn_b = item.get("fornecedor_b", "N/A")
        forn_c = item.get("fornecedor_c", "N/A")
        
        med = float(item.get("media_orcam", 0) or 0)
        alvo = float(item.get("preco_alvo", 0) or 0)
        comp = float(item.get("valor_comprado", 0) or 0)
        econ = float(item.get("economia_real", 0) or 0)
        st_meta = item.get("status_meta", "N/A")

        tot_orcam_geral += med
        tot_alvo_geral += alvo
        tot_comprado_geral += comp
        tot_economia_geral += econ

        st_text = "<font color='#15803d'><b>Atingida</b></font>" if "Atingida" in st_meta and "Não" not in st_meta else "<font color='#dc2626'><b>Não Atingida</b></font>"

        row = [
            Paragraph(str(dt_formatted), cell_style),
            Paragraph(str(prod), cell_left),
            Paragraph(str(forn_a), cell_style),
            Paragraph(str(forn_b), cell_style),
            Paragraph(str(forn_c), cell_style),
            Paragraph(f"R$ {formar_real(med)}", cell_bold),
            Paragraph(f"R$ {formar_real(alvo)}", cell_bold),
            Paragraph(f"R$ {formar_real(comp)}", cell_bold),
            Paragraph(f"R$ {formar_real(econ)}", cell_bold),
            Paragraph(st_text, cell_style)
        ]
        data.append(row)

        table_styles.append(('BACKGROUND', (2, row_idx), (4, row_idx), colors.HexColor('#fef08a')))
        table_styles.append(('BACKGROUND', (5, row_idx), (5, row_idx), colors.HexColor('#d1fae5')))
        table_styles.append(('BACKGROUND', (6, row_idx), (6, row_idx), colors.HexColor('#dbeafe')))
        table_styles.append(('BACKGROUND', (7, row_idx), (7, row_idx), colors.HexColor('#fef08a')))
        table_styles.append(('BACKGROUND', (8, row_idx), (8, row_idx), colors.HexColor('#d1fae5')))

    tot_row_idx = len(data)
    data.append([
        Paragraph("<b>TOTAIS ACUMULADOS:</b>", ParagraphStyle('TOTL', fontSize=8, leading=10, fontName='Helvetica-Bold', alignment=2)),
        "", "", "", "",
        Paragraph(f"R$ {formar_real(tot_orcam_geral)}", ParagraphStyle('TOTM', fontSize=8, leading=10, fontName='Helvetica-Bold', textColor=colors.HexColor('#065f46'), alignment=1)),
        Paragraph(f"R$ {formar_real(tot_alvo_geral)}", ParagraphStyle('TOTA', fontSize=8, leading=10, fontName='Helvetica-Bold', textColor=colors.HexColor('#1d4ed8'), alignment=1)),
        Paragraph(f"R$ {formar_real(tot_comprado_geral)}", ParagraphStyle('TOTC', fontSize=8, leading=10, fontName='Helvetica-Bold', textColor=colors.HexColor('#854d0e'), alignment=1)),
        Paragraph(f"R$ {formar_real(tot_economia_geral)}", ParagraphStyle('TOTE', fontSize=8, leading=10, fontName='Helvetica-Bold', textColor=colors.HexColor('#065f46'), alignment=1)),
        Paragraph("-", cell_style)
    ])

    table_styles.append(('SPAN', (0, tot_row_idx), (4, tot_row_idx)))
    table_styles.append(('BACKGROUND', (0, tot_row_idx), (-1, tot_row_idx), colors.HexColor('#f1f5f9')))

    col_widths = [65, 145, 95, 95, 95, 75, 75, 75, 62, 30]
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle(table_styles))

    elements.append(t)
    doc.build(elements)
    return buffer.getvalue()