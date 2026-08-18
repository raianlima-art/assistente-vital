import base64
import csv
import datetime
import io
import json
import os
import smtplib
import unicodedata
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import streamlit as st
from dotenv import load_dotenv
from geopy.distance import geodesic
from geopy.geocoders import Photon
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from openai import OpenAI
from supabase import Client, create_client


from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

# -----------------------------------------------------------------------------
# 1. CARREGAMENTO DAS VARIÁVEIS DE AMBIENTE
# -----------------------------------------------------------------------------
load_dotenv(override=True)

def get_secret(key, default=None):
    try:
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return os.getenv(key, default)

API_KEY_OPENAI = get_secret("OPENAI_API_KEY")
SUPABASE_URL = get_secret("SUPABASE_URL")
SUPABASE_KEY = get_secret("SUPABASE_KEY")

EMAIL_REMETENTE = get_secret("EMAIL_REMETENTE")
EMAIL_SENHA_APP = get_secret("EMAIL_SENHA_APP")
EMAIL_DESTINATARIO = get_secret("EMAIL_DESTINATARIO")

ADM_PASSWORD = get_secret("ADM_PASSWORD", "admin123")
ESTOQUE_PASSWORD = get_secret("ESTOQUE_PASSWORD", "estoque123")
GOOGLE_DRIVE_FOLDER_ID = get_secret("GOOGLE_DRIVE_FOLDER_ID", "")

LOGO_PATH = "logo.png"

# -----------------------------------------------------------------------------
# 2. CONFIGURAÇÃO DA PÁGINA E CSS CUSTOMIZADO
# -----------------------------------------------------------------------------
pagina_icone = LOGO_PATH if os.path.exists(LOGO_PATH) else "🤖"

st.set_page_config(
    page_title="Assistente Integrado Vital C", 
    page_icon=pagina_icone, 
    layout="centered",
    initial_sidebar_state="expanded"
)

custom_css = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }

    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}

    .main-header {
        background: linear-gradient(135deg, #0f172a 0%, #1e3c72 100%);
        padding: 22px 25px;
        border-radius: 16px;
        color: white;
        text-align: center;
        margin-bottom: 20px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.08);
    }
    .main-header h1 {
        color: #ffffff !important;
        font-size: 1.8rem !important;
        font-weight: 700 !important;
        margin: 0 !important;
        letter-spacing: -0.5px;
    }
    .main-header p {
        color: #94a3b8;
        font-size: 0.9rem;
        margin: 4px 0 0 0;
    }

    div.stButton > button:first-child {
        background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
        color: white;
        border: none;
        border-radius: 8px;
        padding: 0.6rem 1.2rem;
        font-weight: 600;
        letter-spacing: 0.5px;
        transition: all 0.25s ease;
        box-shadow: 0 4px 6px rgba(0,0,0,0.08);
        width: 100%;
    }
    div.stButton > button:first-child:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 12px rgba(42, 82, 152, 0.25);
        color: white;
    }

    .stTextInput input, .stNumberInput input, .stSelectbox > div > div {
        border-radius: 8px !important;
        border: 1px solid #cbd5e1 !important;
        background-color: #ffffff !important;
        transition: all 0.2s ease-in-out;
    }
    .stTextInput input:focus, .stNumberInput input:focus, .stSelectbox > div > div:focus-within {
        border-color: #2a5298 !important;
        box-shadow: 0 0 0 3px rgba(42, 82, 152, 0.15) !important;
    }

    [data-testid="stSidebar"] {
        background-color: #f8fafc;
        border-right: 1px solid #e2e8f0;
    }

    [data-testid="stExpander"] {
        border: 1px solid #e2e8f0 !important;
        border-radius: 10px !important;
        background-color: #ffffff !important;
        margin-bottom: 12px !important;
        box-shadow: 0 2px 4px rgba(0,0,0,0.02) !important;
    }

    [data-baseweb="tab-list"] {
        gap: 8px;
        background-color: #f1f5f9;
        padding: 6px;
        border-radius: 12px;
        border: 1px solid #e2e8f0;
        margin-bottom: 20px;
    }
    [data-baseweb="tab"] {
        border-radius: 8px;
        padding: 8px 18px;
        font-weight: 600;
        color: #64748b;
        background: transparent;
        border: none !important;
    }
    [data-baseweb="tab"][aria-selected="true"] {
        background-color: #ffffff !important;
        color: #1e3c72 !important;
        box-shadow: 0 2px 6px rgba(0,0,0,0.06);
    }

    [data-testid="stChatMessage"] {
        padding: 14px 18px;
        border-radius: 14px;
        margin-bottom: 12px;
        border: 1px solid #e2e8f0;
        box-shadow: 0 2px 5px rgba(0,0,0,0.02);
    }
</style>
"""
st.markdown(custom_css, unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 3. INICIALIZAÇÃO DE CONEXÕES
# -----------------------------------------------------------------------------
if not API_KEY_OPENAI:
    st.error("❌ A chave 'OPENAI_API_KEY' não foi encontrada! Verifique o .env ou o Secrets do Streamlit.")
    st.stop()

client = OpenAI(api_key=API_KEY_OPENAI)

supabase: Client = None
if SUPABASE_URL and SUPABASE_KEY and "seu-projeto" not in SUPABASE_URL:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        st.sidebar.warning(f"⚠️ Supabase offline: {e}")

# -----------------------------------------------------------------------------
# 4. VALORES DE CONFIGURAÇÕES FIXAS (ESCOPO GLOBAL)
# -----------------------------------------------------------------------------
ipva = 10000.0
seguro = 10000.0
manut_anual = 10000.0
dias_uteis = 365
valor_alimentacao_dia = 70.0
valor_pernoite = 250.0
consumo = 8.0
preco_diesel = 8.00
diaria_motorista = 200.0
fator_estrada = 0.25
margem = 20
custo_fixo_diaria = (ipva + seguro + manut_anual) / dias_uteis

# -----------------------------------------------------------------------------
# 5. GERADORES DE PDF EM REPORTLAB (LARGURA E FORMATAÇÃO PERFEITAS)
# -----------------------------------------------------------------------------
def normalizar_texto(texto):
    if not texto:
        return ""
    nfkd = unicodedata.normalize("NFD", str(texto))
    return "".join([c for c in nfkd if not unicodedata.combining(c)]).lower().strip()

def formatar_tempo_decorrido(data_inicio_str, data_fim_str=None):
    if not data_inicio_str:
        return "Data indisponível"
    try:
        data_inicio_clean = data_inicio_str.replace("Z", "+00:00")
        inicio = datetime.datetime.fromisoformat(data_inicio_clean)

        if data_fim_str:
            data_fim_clean = data_fim_str.replace("Z", "+00:00")
            fim = datetime.datetime.fromisoformat(data_fim_clean)
        else:
            fim = datetime.datetime.now(datetime.timezone.utc)

        diff = fim - inicio
        dias = diff.days
        horas = diff.seconds // 3600
        minutos = (diff.seconds % 3600) // 60

        if dias > 0:
            return f"{dias}d {horas}h"
        elif horas > 0:
            return f"{horas}h {minutos}min"
        else:
            return f"{minutos} min"
    except Exception:
        return "Tempo n/d"

def formar_real(valor):
    try:
        val = float(valor)
        return "{:,.2f}".format(val).replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "0,00"

def gerar_pdf_controle_compras(resp_cot_hist):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=15,
        leftMargin=15,
        topMargin=20,
        bottomMargin=20
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'TitleStyle',
        parent=styles['Heading1'],
        fontSize=16,
        leading=18,
        alignment=1,
        textColor=colors.HexColor('#0f172a'),
        fontName='Helvetica-Bold'
    )
    subtitle_style = ParagraphStyle(
        'SubTitleStyle',
        parent=styles['Normal'],
        fontSize=10,
        leading=12,
        alignment=1,
        textColor=colors.HexColor('#475569'),
        fontName='Helvetica-Bold'
    )

    elements = [
        Paragraph("<b>CONTROLE DE COMPRAS 2026</b>", title_style),
        Paragraph("VITAL C", subtitle_style),
        Spacer(1, 12)
    ]

    header_style = ParagraphStyle('TH', fontSize=8, leading=10, fontName='Helvetica-Bold', textColor=colors.white, alignment=1)
    header_yellow_style = ParagraphStyle('THY', fontSize=8, leading=10, fontName='Helvetica-Bold', textColor=colors.HexColor('#0f172a'), alignment=1)

    def style_th(text, bg_color):
        p_style = header_yellow_style if bg_color == '#eab308' else header_style
        return Paragraph(f"<b>{text}</b>", p_style)

    th_cells = [
        style_th("Mês / Data", '#eab308'),
        style_th("Produto", '#eab308'),
        style_th("Fornecedor A", '#eab308'),
        style_th("Fornecedor B", '#eab308'),
        style_th("Fornecedor C", '#eab308'),
        style_th("Média Orçamentos", '#065f46'),
        style_th("Preço Alvo<br/>(Média -10%)", '#1d4ed8'),
        style_th("Valor Comprado", '#eab308'),
        style_th("Economia Real", '#065f46'),
        style_th("Status Meta", '#065f46')
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
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING', (0,0), (-1,-1), 3),
        ('RIGHTPADDING', (0,0), (-1,-1), 3),
    ]

    for row_idx, item in enumerate(resp_cot_hist, start=1):
        dt_c = item.get("data_cotacao") or ""
        try:
            dt_formatted = datetime.datetime.strptime(dt_c, "%Y-%m-%d").strftime("%d/%m/%Y")
        except Exception:
            dt_formatted = dt_c

        prod = item.get("produto", "N/A")
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

        if "Atingida" in st_meta and "Não" not in st_meta:
            st_text = "<font color='#15803d'><b>Atingida</b></font>"
        else:
            st_text = "<font color='#dc2626'><b>Não Atingida</b></font>"

        row = [
            Paragraph(dt_formatted, cell_style),
            Paragraph(prod, cell_left),
            Paragraph(forn_a, cell_style),
            Paragraph(forn_b, cell_style),
            Paragraph(forn_c, cell_style),
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
    tot_style_label = ParagraphStyle('TOTL', fontSize=8, leading=10, fontName='Helvetica-Bold', alignment=2)
    tot_style_m = ParagraphStyle('TOTM', fontSize=8, leading=10, fontName='Helvetica-Bold', textColor=colors.HexColor('#065f46'), alignment=1)
    tot_style_a = ParagraphStyle('TOTA', fontSize=8, leading=10, fontName='Helvetica-Bold', textColor=colors.HexColor('#1d4ed8'), alignment=1)
    tot_style_c = ParagraphStyle('TOTC', fontSize=8, leading=10, fontName='Helvetica-Bold', textColor=colors.HexColor('#854d0e'), alignment=1)
    tot_style_e = ParagraphStyle('TOTE', fontSize=8, leading=10, fontName='Helvetica-Bold', textColor=colors.HexColor('#065f46'), alignment=1)

    data.append([
        Paragraph("<b>TOTAIS ACUMULADOS:</b>", tot_style_label),
        "", "", "", "",
        Paragraph(f"R$ {formar_real(tot_orcam_geral)}", tot_style_m),
        Paragraph(f"R$ {formar_real(tot_alvo_geral)}", tot_style_a),
        Paragraph(f"R$ {formar_real(tot_comprado_geral)}", tot_style_c),
        Paragraph(f"R$ {formar_real(tot_economia_geral)}", tot_style_e),
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

def gerar_pdf_cotacao_individual(desc, qtd, ref, solic, motivo, opcoes_ordenadas, vencedor):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=25,
        leftMargin=25,
        topMargin=25,
        bottomMargin=25
    )

    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'HeaderTitle',
        fontSize=15,
        leading=18,
        alignment=1,
        textColor=colors.white,
        fontName='Helvetica-Bold'
    )
    subtitle_style = ParagraphStyle(
        'HeaderSub',
        fontSize=9,
        leading=11,
        alignment=1,
        textColor=colors.HexColor('#cbd5e1'),
        fontName='Helvetica-Bold'
    )

    header_data = [[
        Paragraph("<b>RELATÓRIO DE COTAÇÃO DE PREÇOS</b>", title_style),
    ], [
        Paragraph("VITAL C", subtitle_style)
    ]]
    header_table = Table(header_data, colWidths=[540])
    header_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#0f172a')),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))

    elements = [
        header_table,
        Spacer(1, 15)
    ]

    sec_title_style = ParagraphStyle(
        'SecTitle',
        fontSize=10,
        leading=12,
        textColor=colors.HexColor('#1e3c72'),
        fontName='Helvetica-Bold'
    )

    elements.append(Paragraph("<b>📦 DADOS DA SOLICITAÇÃO</b>", sec_title_style))
    elements.append(Spacer(1, 6))

    lbl_style = ParagraphStyle('LBL', fontSize=9, leading=12, fontName='Helvetica-Bold', textColor=colors.HexColor('#475569'))
    val_style = ParagraphStyle('VAL', fontSize=9, leading=12, fontName='Helvetica', textColor=colors.HexColor('#0f172a'))

    info_data = [
        [Paragraph("Item / Produto:", lbl_style), Paragraph(str(desc), val_style)],
        [Paragraph("Quantidade:", lbl_style), Paragraph(f"{qtd} un.", val_style)],
        [Paragraph("Referência / Modelo:", lbl_style), Paragraph(str(ref), val_style)],
        [Paragraph("Solicitante:", lbl_style), Paragraph(str(solic), val_style)],
        [Paragraph("Motivo da Compra:", lbl_style), Paragraph(str(motivo), val_style)],
        [Paragraph("Data da Cotação:", lbl_style), Paragraph(datetime.date.today().strftime('%d/%m/%Y'), val_style)],
    ]
    info_table = Table(info_data, colWidths=[140, 400])
    info_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8fafc')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
    ]))

    elements.append(info_table)
    elements.append(Spacer(1, 15))

    elements.append(Paragraph("<b>📊 COMPARATIVO DE PREÇOS</b>", sec_title_style))
    elements.append(Spacer(1, 6))

    th_style = ParagraphStyle('THC', fontSize=8, leading=10, fontName='Helvetica-Bold', textColor=colors.white, alignment=0)
    
    comp_data = [[
        Paragraph("Fornecedor", th_style),
        Paragraph("Preço Unit.", th_style),
        Paragraph("Frete", th_style),
        Paragraph("Valor Total", th_style),
        Paragraph("Link Cotação", th_style),
        Paragraph("Status", th_style)
    ]]

    comp_styles = [
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0f172a')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
    ]

    td_style = ParagraphStyle('TDC', fontSize=8, leading=10, fontName='Helvetica', alignment=0)
    td_bold = ParagraphStyle('TDCB', fontSize=8, leading=10, fontName='Helvetica-Bold', alignment=0)
    venc_style = ParagraphStyle('VENC', fontSize=8, leading=10, fontName='Helvetica-Bold', textColor=colors.HexColor('#15803d'), alignment=1)
    opc_style = ParagraphStyle('OPC', fontSize=8, leading=10, fontName='Helvetica', textColor=colors.HexColor('#64748b'), alignment=1)

    for idx, op in enumerate(opcoes_ordenadas, 1):
        is_vencedor = (idx == 1)
        st_badge = Paragraph("🏆 VENCEDOR", venc_style) if is_vencedor else Paragraph("Opção", opc_style)
        link_str = f"<font color='#0284c7'><u>Acessar Cotação</u></font>" if op.get("link") else "Sem link"

        row = [
            Paragraph(op['nome'], td_bold if is_vencedor else td_style),
            Paragraph(f"R$ {formar_real(op['pu'])}", td_style),
            Paragraph(f"R$ {formar_real(op['frete'])}", td_style),
            Paragraph(f"R$ {formar_real(op['total'])}", td_bold if is_vencedor else td_style),
            Paragraph(link_str, td_style),
            st_badge
        ]
        comp_data.append(row)
        if is_vencedor:
            comp_styles.append(('BACKGROUND', (0, idx), (-1, idx), colors.HexColor('#f0fdf4')))

    comp_table = Table(comp_data, colWidths=[120, 75, 65, 80, 110, 90])
    comp_table.setStyle(TableStyle(comp_styles))

    elements.append(comp_table)
    elements.append(Spacer(1, 15))

    venc_box_data = [[
        Paragraph("<b>🏆 FORNECEDOR VENCEDOR SELECIONADO:</b>", ParagraphStyle('VTB', fontSize=9, leading=12, fontName='Helvetica-Bold', textColor=colors.HexColor('#166534'))),
    ], [
        Paragraph(f"<b>{vencedor['nome']}</b> — Valor Total Aprovado: <b>R$ {formar_real(vencedor['total'])}</b>", ParagraphStyle('VD', fontSize=9, leading=12, fontName='Helvetica', textColor=colors.HexColor('#14532d')))
    ]]
    venc_table = Table(venc_box_data, colWidths=[540])
    venc_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f0fdf4')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#bbf7d0')),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('LEFTPADDING', (0,0), (-1,-1), 10),
    ]))

    elements.append(venc_table)

    doc.build(elements)
    return buffer.getvalue()

def obter_ou_criar_subpasta(service, parent_folder_id, nome_pasta):
    query = f"'{parent_folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and name='{nome_pasta}' and trashed=false"
    resultados = service.files().list(q=query, spaces='drive', supportsAllDrives=True, includeItemsFromAllDrives=True, fields='files(id, name)').execute()
    pastas = resultados.get('files', [])
    if pastas:
        return pastas[0]['id']
    else:
        file_metadata = {'name': nome_pasta, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [parent_folder_id]}
        pasta_criada = service.files().create(body=file_metadata, fields='id', supportsAllDrives=True).execute()
        return pasta_criada.get('id')

def salvar_nf_no_drive(file_bytes, nome_arquivo, mime_type='application/pdf', as_google_doc=False, nome_subpasta=None):
    try:
        if not GOOGLE_DRIVE_FOLDER_ID:
            st.error("❌ A variável 'GOOGLE_DRIVE_FOLDER_ID' não foi configurada nos Secrets!")
            return None

        SCOPES = ['https://www.googleapis.com/auth/drive']

        if os.path.exists("credentials.json"):
            creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
        else:
            creds_raw = get_secret("GOOGLE_DRIVE_CREDENTIALS")
            if not creds_raw:
                st.error("❌ Segredo 'GOOGLE_DRIVE_CREDENTIALS' não encontrado!")
                return None

            creds_json = None
            if isinstance(creds_raw, str):
                try:
                    decoded_bytes = base64.b64decode(creds_raw.strip())
                    creds_json = json.loads(decoded_bytes.decode("utf-8"))
                except Exception:
                    try:
                        creds_json = json.loads(creds_raw)
                    except Exception:
                        pass

            if not creds_json:
                if hasattr(creds_raw, "to_dict"):
                    creds_json = creds_raw.to_dict()
                elif isinstance(creds_raw, dict):
                    creds_json = dict(creds_raw)

            if not creds_json:
                st.error("❌ Formato de credenciais do Google Drive inválido!")
                return None

            if "private_key" in creds_json:
                pk = str(creds_json["private_key"]).strip('"\'')
                pk = pk.replace("\\n", "\n")
                creds_json["private_key"] = pk

            creds = Credentials.from_service_account_info(creds_json, scopes=SCOPES)

        service = build('drive', 'v3', credentials=creds)
        
        if not nome_subpasta:
            nome_subpasta = datetime.datetime.now().strftime("%m-%Y")
            
        pasta_destino_id = obter_ou_criar_subpasta(service, GOOGLE_DRIVE_FOLDER_ID, nome_subpasta)
        file_metadata = {'name': nome_arquivo, 'parents': [pasta_destino_id]}
        
        if as_google_doc:
            file_metadata['mimeType'] = 'application/vnd.google-apps.document'
            
        media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype=mime_type, resumable=True)
        file = service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink', supportsAllDrives=True).execute()
        return file.get('webViewLink')
    except Exception as e:
        st.error(f"❌ Erro ao salvar no Google Drive: {e}")
        return None

def enviar_email_notificacao(descricao, link, referencia, quantidade, motivo, solicitante,
                             id_manutencao=None, compativel=None, encapsulamento=None, 
                             custo_estimado=None, link_adicional=None, datasheet=None):
    if not EMAIL_REMETENTE or not EMAIL_SENHA_APP or not EMAIL_DESTINATARIO:
        return False

    campos_fabiano_html = ""
    if any([id_manutencao, compativel, encapsulamento, custo_estimado, link_adicional, datasheet]):
        campos_fabiano_html = f"""
        <li><strong>ID Manutenção:</strong> {id_manutencao or 'N/A'}</li>
        <li><strong>Compatível:</strong> {compativel or 'N/A'}</li>
        <li><strong>Encapsulamento:</strong> {encapsulamento or 'N/A'}</li>
        <li><strong>Custo Estimado:</strong> {custo_estimado or 'N/A'}</li>
        <li><strong>Link Adicional:</strong> {f'<a href="{link_adicional}">Ver Link</a>' if link_adicional else 'N/A'}</li>
        <li><strong>Datasheet:</strong> {f'<a href="{datasheet}">Ver Datasheet</a>' if datasheet else 'N/A'}</li>
        """

    msg = MIMEMultipart()
    msg['From'] = EMAIL_REMETENTE
    msg['To'] = EMAIL_DESTINATARIO
    msg['Subject'] = f"🚨 Nova Solicitação de Compra - {solicitante}"

    corpo = f"""
    <h2>🛒 Nova Solicitação de Compra Recebida!</h2>
    <p>O assistente virtual recebeu um novo pedido de insumo/peça:</p>
    <ul>
        <li><strong>Solicitante:</strong> {solicitante}</li>
        <li><strong>Nome do item:</strong> {descricao}</li>
        <li><strong>Quantidade:</strong> {quantidade} un.</li>
        <li><strong>Detalhe:</strong> {referencia} (<a href="{link}">Ver Produto</a>)</li>
        <li><strong>Motivo:</strong> {motivo}</li>
        {campos_fabiano_html}
    </ul>
    <hr>
    <p><small>Este e-mail foi gerado automaticamente pelo Assistente Integrado Vital C.</small></p>
    """

    msg.attach(MIMEText(corpo, 'html'))

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(EMAIL_REMETENTE, EMAIL_SENHA_APP.replace(" ", ""))
            server.sendmail(EMAIL_REMETENTE, EMAIL_DESTINATARIO, msg.as_string())
        return True
    except Exception as e:
        print(f"❌ Erro ao enviar e-mail: {e}")
        return False

@st.cache_data(show_spinner="Consultando mapa...")
def obter_localizacao(cidade):
    geolocator = Photon(user_agent="vital_logistica_v18", timeout=10)
    try:
        return geolocator.geocode(cidade)
    except Exception:
        return None

def calcular_frete_ia(origem, destino, tipo_trajeto, dias_por_trecho, is_viagem_curta, solicitante):
    loc1 = obter_localizacao(origem)
    loc2 = obter_localizacao(destino)

    if not loc1 or not loc2:
        return {"erro": "Uma ou ambas as cidades não foram encontradas no mapa."}

    multiplicador = 2 if tipo_trajeto == "Apenas Ida" else 4
    dist_direta = geodesic((loc1.latitude, loc1.longitude), (loc2.latitude, loc2.longitude)).km
    dist_total_km = dist_direta * (1 + fator_estrada) * multiplicador
    dias_totais_operacao = dias_por_trecho * multiplicador

    custo_diesel = (dist_total_km / consumo) * preco_diesel
    custo_alimentacao_total = valor_alimentacao_dia * 1
    custo_hospedagem_total = 0.0 if is_viagem_curta else (valor_pernoite * dias_por_trecho)
    custo_pessoal = diaria_motorista * dias_totais_operacao
    custo_fixo_veiculo = custo_fixo_diaria * dias_totais_operacao

    custo_operacional_total = (
        custo_diesel + custo_alimentacao_total + custo_pessoal + 
        custo_fixo_veiculo + custo_hospedagem_total
    )
    preco_final = custo_operacional_total * (1 + margem / 100)

    if supabase:
        try:
            supabase.table("cotacoes").insert({
                "origem": origem,
                "destino": destino,
                "km_total": int(dist_total_km),
                "preco_final": preco_final,
                "solicitante": solicitante
            }).execute()
        except Exception:
            pass

    return {
        "sucesso": True,
        "km_total": int(dist_total_km),
        "custo_diesel": custo_diesel,
        "custo_hospedagem_alim": custo_hospedagem_total + custo_alimentacao_total,
        "gastos_fixos": custo_pessoal + custo_fixo_veiculo,
        "preco_final": preco_final
    }

def registrar_solicitacao_compra(descricao, link, referencia, quantidade, motivo, solicitante,
                                 id_manutencao=None, compativel=None, encapsulamento=None, 
                                 custo_estimado=None, link_adicional=None, datasheet=None):
    if supabase:
        payload = {
            "item_descricao": descricao,
            "link_produto": link,
            "referencia": referencia,
            "quantidade": int(quantidade),
            "motivo": motivo,
            "solicitante": solicitante,
            "status": "Pendente",
            "id_manutencao": id_manutencao,
            "compativel": compativel,
            "encapsulamento": encapsulamento,
            "custo_estimado": custo_estimado,
            "link_adicional": link_adicional,
            "datasheet": datasheet
        }
        try:
            supabase.table("solicitacoes_compras").insert(payload).execute()
        except Exception:
            extra_text = f" | ID Manut: {id_manutencao} | Compativel: {compativel} | Encapsulamento: {encapsulamento} | Custo Est: {custo_estimado}"
            payload_fallback = {
                "item_descricao": f"{descricao} {extra_text}",
                "link_produto": link,
                "referencia": referencia,
                "quantidade": int(quantidade),
                "motivo": motivo,
                "solicitante": solicitante,
                "status": "Pendente"
            }
            supabase.table("solicitacoes_compras").insert(payload_fallback).execute()
            
    enviar_email_notificacao(descricao, link, referencia, quantidade, motivo, solicitante,
                             id_manutencao, compativel, encapsulamento, custo_estimado, link_adicional, datasheet)
    return {"sucesso": True, "mensagem": "Item registrado e e-mail enviado!"}

tools = [
    {
        "type": "function",
        "function": {
            "name": "calcular_frete_ia",
            "description": "Calcula o valor do frete com base nos dados de transporte.",
            "parameters": {
                "type": "object",
                "properties": {
                    "origem": {"type": "string"},
                    "destino": {"type": "string"},
                    "tipo_trajeto": {"type": "string", "enum": ["Apenas Ida", "Ida e Volta"]},
                    "dias_por_trecho": {"type": "integer"},
                    "is_viagem_curta": {"type": "boolean"}
                },
                "required": ["origem", "destino", "tipo_trajeto", "dias_por_trecho", "is_viagem_curta"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "registrar_solicitacao_compra",
            "description": "Registra um pedido de compra no sistema.",
            "parameters": {
                "type": "object",
                "properties": {
                    "descricao": {"type": "string", "description": "Nome resumido do produto"},
                    "link": {"type": "string", "description": "URL/Link do produto"},
                    "referencia": {"type": "string", "description": "Modelo, código ou especificação"},
                    "quantidade": {"type": "integer", "description": "Quantidade de items"},
                    "motivo": {"type": "string", "description": "Motivo da compra"},
                    "id_manutencao": {"type": "string"},
                    "compativel": {"type": "string"},
                    "encapsulamento": {"type": "string"},
                    "custo_estimado": {"type": "string"},
                    "link_adicional": {"type": "string"},
                    "datasheet": {"type": "string"}
                },
                "required": ["descricao", "link", "referencia", "quantidade", "motivo"]
            }
        }
    }
]

# -----------------------------------------------------------------------------
# 6. TELA DE AUTENTICAÇÃO E LOGIN (BLOQUEANTE)
# -----------------------------------------------------------------------------
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False

if "is_adm" not in st.session_state:
    st.session_state.is_adm = False

if "is_estoque" not in st.session_state:
    st.session_state.is_estoque = False

if not st.session_state.autenticado:
    st.markdown("""
        <div class="main-header">
            <h1>🤖 Assistente Integrado Vital C</h1>
            <p>Plataforma Inteligente de Compras & Logística</p>
        </div>
    """, unsafe_allow_html=True)
    
    aba_login_user, aba_login_restrito = st.tabs(["👤 Identificação do Solicitante", "🔑 Acesso Restrito (ADM / Estoque)"])

    with aba_login_user:
        with st.form("form_identificacao"):
            nome_user = st.text_input("Seu Nome Completo:")
            setor_user = st.text_input("Seu Setor / Cargo:", placeholder="Ex: Manutenção, Frota, Compras...")
            filial_user = st.selectbox(
                "Unidade / Filial:", 
                ["Arco - São Paulo", "Ultrassom - São Paulo", "Outra"]
            )
            btn_entrar = st.form_submit_button("🚀 Iniciar Atendimento")

            if btn_entrar:
                if not nome_user.strip() or not setor_user.strip():
                    st.error("⚠️ Por favor, preencha seu nome e setor!")
                else:
                    st.session_state.solicitante_str = f"{nome_user} ({setor_user} - {filial_user})"
                    st.session_state.autenticado = True
                    st.session_state.is_adm = False
                    st.session_state.is_estoque = False
                    st.rerun()

    with aba_login_restrito:
        with st.form("form_adm_direto"):
            senha_direta = st.text_input("Senha de Acesso:", type="password")
            btn_direto = st.form_submit_button("🔓 Entrar")
            
            if btn_direto:
                if senha_direta == ADM_PASSWORD:
                    st.session_state.is_adm = True
                    st.session_state.is_estoque = False
                    st.session_state.solicitante_str = "Administrador (ADM)"
                    st.session_state.autenticado = True
                    st.rerun()
                elif senha_direta == ESTOQUE_PASSWORD:
                    st.session_state.is_estoque = True
                    st.session_state.is_adm = False
                    st.session_state.solicitante_str = "Estoque (Recebimento)"
                    st.session_state.autenticado = True
                    st.rerun()
                else:
                    st.error("Senha incorreta!")

    st.stop()

# -----------------------------------------------------------------------------
# 7. BARRA LATERAL (EXIBIDA SOMENTE APÓS LOGIN)
# -----------------------------------------------------------------------------
with st.sidebar:
    st.success(f"👤 **Logado como:**\n\n{st.session_state.solicitante_str}")
    if st.button("🚪 Trocar Usuário / Sair", key="btn_sb_logout"):
        st.session_state.clear()
        st.rerun()

    st.divider()
    st.header("🔑 Acesso Restrito")
    
    if st.session_state.is_estoque:
        st.info("🔓 **Modo Estoque Ativo**")
        if st.button("🔄 Sair do Modo Estoque", key="btn_sb_sair_est"):
            st.session_state.clear()
            st.rerun()
            
    elif st.session_state.is_adm:
        st.info("🔓 **Modo Administrador Ativo**")
        if st.button("🔄 Sair do Modo ADM", key="btn_sb_sair_adm"):
            st.session_state.clear()
            st.rerun()

        if supabase:
            st.divider()
            with st.expander("🧹 Limpeza e Exportação das 3 Tabelas"):
                st.info("Exporta compras finalizadas, desempenho de fornecedores e cotações para o Google Drive e limpa do Supabase.")
                senha_export = st.text_input("Confirme a Senha ADM:", type="password", key="senha_exp_sb")
                
                if st.button("🚀 Exportar e Limpar", key="btn_exp_sb"):
                    if senha_export == ADM_PASSWORD:
                        with st.spinner("Processando exportação de 3 tabelas..."):
                            try:
                                data_atual = datetime.datetime.now().strftime("%d-%m-%Y_%H-%M")
                                links_gerados = []

                                resp_compras = supabase.table("solicitacoes_compras").select("*").eq("status", "Finalizado").execute()
                                dados_compras = [d for d in resp_compras.data if d.get("link_nf")]
                                if dados_compras:
                                    output_c = io.StringIO()
                                    output_c.write('\ufeff')
                                    chaves_c = set()
                                    for d in dados_compras: chaves_c.update(d.keys())
                                    writer_c = csv.DictWriter(output_c, fieldnames=list(chaves_c), delimiter=';')
                                    writer_c.writeheader()
                                    writer_c.writerows(dados_compras)
                                    link_c = salvar_nf_no_drive(output_c.getvalue().encode('utf-8'), f"Relatorio_Compras_{data_atual}.csv", mime_type='text/csv')
                                    if link_c:
                                        for item in dados_compras:
                                            supabase.table("solicitacoes_compras").delete().eq("id", item["id"]).execute()
                                        links_gerados.append(("Compras", link_c, len(dados_compras)))

                                resp_desemp = supabase.table("desempenho_fornecedores").select("*").execute()
                                dados_desemp = resp_desemp.data
                                if dados_desemp:
                                    output_d = io.StringIO()
                                    output_d.write('\ufeff')
                                    chaves_d = set()
                                    for d in dados_desemp: chaves_d.update(d.keys())
                                    writer_d = csv.DictWriter(output_d, fieldnames=list(chaves_d), delimiter=';')
                                    writer_d.writeheader()
                                    writer_d.writerows(dados_desemp)
                                    link_d = salvar_nf_no_drive(output_d.getvalue().encode('utf-8'), f"Relatorio_Desempenho_Fornecedores_{data_atual}.csv", mime_type='text/csv')
                                    if link_d:
                                        for item in dados_desemp:
                                            supabase.table("desempenho_fornecedores").delete().eq("id", item["id"]).execute()
                                        links_gerados.append(("Fornecedores", link_d, len(dados_desemp)))

                                resp_cot = supabase.table("cotacoes").select("*").execute()
                                dados_cot = resp_cot.data
                                if dados_cot:
                                    output_cot = io.StringIO()
                                    output_cot.write('\ufeff')
                                    chaves_cot = set()
                                    for d in dados_cot: chaves_cot.update(d.keys())
                                    writer_cot = csv.DictWriter(output_cot, fieldnames=list(chaves_cot), delimiter=';')
                                    writer_cot.writeheader()
                                    writer_cot.writerows(dados_cot)
                                    link_cot = salvar_nf_no_drive(output_cot.getvalue().encode('utf-8'), f"Relatorio_Cotacoes_{data_atual}.csv", mime_type='text/csv')
                                    if link_cot:
                                        for item in dados_cot:
                                            supabase.table("cotacoes").delete().eq("id", item["id"]).execute()
                                        links_gerados.append(("Cotações", link_cot, len(dados_cot)))

                                if not links_gerados:
                                    st.warning("Nenhum dado pendente encontrado.")
                                else:
                                    st.success("✅ Concluído!")
                                    for titulo, link_d, qtd in links_gerados:
                                        st.markdown(f"📊 **{titulo}:** {qtd} item(ns) — [Abrir Drive]({link_d})")
                            except Exception as e:
                                st.error(f"❌ Erro: {e}")
                    else:
                        st.error("❌ Senha incorreta!")

        st.divider()
        st.header("⚙️ Configurações Fixas")

        with st.expander("💰 Custos Fixos Veículo", expanded=False):
            ipva = st.number_input("IPVA Anual (R$)", value=10000.0)
            seguro = st.number_input("Seguro Anual (R$)", value=10000.0)
            manut_anual = st.number_input("Manutenção Fixa Anual (R$)", value=10000.0)
            dias_uteis = st.number_input("Dias Úteis/Ano", value=365)

        with st.expander("🍴 Custos Unitários", expanded=False):
            valor_alimentacao_dia = st.number_input("Alimentação/Dia (R$)", value=70.0)
            valor_pernoite = st.number_input("Hospedagem/Noite (R$)", value=250.0)

        with st.expander("⛽ Operação e Lucro", expanded=False):
            consumo = st.number_input("Consumo (km/L)", value=8.0)
            preco_diesel = st.number_input("Preço Diesel (R$)", value=8.00)
            diaria_motorista = st.number_input("Salário Motorista (R$)", value=200.0)
            fator_estrada = st.slider("Ajuste de Curvas (%)", 10, 40, 25) / 100
            margem = st.slider("Margem de Lucro (%)", 0, 100, 20)

# -----------------------------------------------------------------------------
# 8. INTERFACE PRINCIPAL
# -----------------------------------------------------------------------------
st.markdown("""
    <div class="main-header">
        <h1>🤖 Assistente Integrado Vital C</h1>
        <p>Central de Operações, Cotações e Gestão de Compras</p>
    </div>
""", unsafe_allow_html=True)

col_status1, col_status2 = st.columns([3, 1])
with col_status1:
    st.markdown(f"👤 **Perfil Ativo:** `{st.session_state.solicitante_str}`")
with col_status2:
    if st.button("🔄 Alternar Perfil", key="btn_top_switch"):
        st.session_state.clear()
        st.rerun()

st.divider()

if st.session_state.is_adm:
    aba_chat, aba_gestao = st.tabs(["💬 Assistente IA", "📋 Painel de Compras (ADM)"])
    aba_estoque = None
elif st.session_state.is_estoque:
    aba_estoque = st.container()
    aba_chat = None
    aba_gestao = None
else:
    aba_chat = st.container()
    aba_gestao = None
    aba_estoque = None

# =============================================================================
# ABA 0: PAINEL DE ESTOQUE (RESTRITO AO ESTOQUISTA)
# =============================================================================
if aba_estoque:
    with aba_estoque:
        st.subheader("📦 Conferência & Recebimento de Mercadorias (Estoque)")
        st.info("Aqui você confere os pedidos em trânsito e confirma o recebimento ao chegar a mercadoria.")
        
        if not supabase:
            st.warning("⚠️ O Supabase não está conectado.")
        else:
            query = supabase.table("solicitacoes_compras").select("*").order("id", desc=True).execute()
            dados_nf = [item for item in query.data if item.get("status") in ["Aguardando entrega", "Aguardando NF"]]
            
            if not dados_nf:
                st.info("Nenhuma entrega pendente de conferência no momento.")
            else:
                st.markdown(f"Exibindo **{len(dados_nf)}** pedido(s) aguardando recebimento:")
                for item in dados_nf:
                    item_id = item.get("id")
                    desc = item.get("item_descricao", "Sem descrição")
                    qtd = item.get("quantidade", 1)
                    ref = item.get("referencia", "N/A")
                    solic = item.get("solicitante", "N/A")
                    link_nf = item.get("link_nf")
                    link_cotacao = item.get("link_cotacao")
                    num_pedido = item.get("numero_pedido", "N/A")
                    status_atual = item.get("status", "Pendente")
                    dt_prometida = item.get("data_prometida", "Não informada")
                    fornecedor = item.get("fornecedor_vencedor", "N/A")
                    prazo_pg = item.get("prazo_pagamento_dias", 30)
                    created_at = item.get("created_at")
                    
                    botoes_docs = ""
                    if link_cotacao:
                        botoes_docs += f'<a href="{link_cotacao}" target="_blank" style="background: #f0fdf4; color: #15803d; padding: 8px 14px; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 0.85rem; display: inline-block; border: 1px solid #bbf7d0; margin-right: 8px;">📊 Abrir Cotação ↗</a>'
                    if link_nf:
                        botoes_docs += f'<a href="{link_nf}" target="_blank" style="background: #eff6ff; color: #1d4ed8; padding: 8px 14px; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 0.85rem; display: inline-block; border: 1px solid #bfdbfe;">📄 Abrir Nota Fiscal ↗</a>'
                    if not botoes_docs:
                        botoes_docs = '<span style="color: #64748b; font-size: 0.85rem; font-weight: 500;">⏳ Documentos pendentes pelo ADM</span>'

                    card_html = f"""<div style="background: #ffffff; padding: 18px; border-radius: 12px; margin-bottom: 12px; border: 1px solid #e2e8f0; border-left: 6px solid #3b82f6; box-shadow: 0 2px 4px rgba(0,0,0,0.02);">
                    <h4 style="margin: 0 0 8px 0; color: #0f172a; font-size: 1.1rem;">📦 {desc}</h4>
                    <p style="margin: 0 0 4px 0; font-size: 0.9rem; color: #475569;"><b>🏷️ Nº Pedido:</b> <span style="color:#0f172a; font-weight:600;">{num_pedido}</span> | <b>🏢 Fornecedor:</b> {fornecedor}</p>
                    <p style="margin: 0 0 4px 0; font-size: 0.9rem; color: #475569;"><b>🔢 Qtd:</b> {qtd} un. | <b>📋 Ref:</b> {ref} | <b>📅 Data Prometida:</b> <span style="color:#2563eb; font-weight:600;">{dt_prometida}</span></p>
                    <p style="margin: 0 0 12px 0; font-size: 0.9rem; color: #475569;"><b>👤 Solicitante:</b> {solic} | <b>📌 Status:</b> {status_atual}</p>
                    {botoes_docs}
                    </div>"""
                    
                    st.markdown(card_html, unsafe_allow_html=True)

                    with st.expander(f"🏁 Confirmar Recebimento / Finalizar Item #{item_id}"):
                        with st.form(f"form_fin_est_{item_id}"):
                            col_e1, col_e2 = st.columns(2)
                            with col_e1:
                                f_dt_entregue = st.date_input("Data Real de Entrega:", value=datetime.date.today(), key=f"dt_ent_{item_id}")
                            with col_e2:
                                f_qualidade = st.selectbox("Qualidade OK (Sem defeitos/avarias)?", ["SIM", "NÃO"], key=f"qual_{item_id}")
                            
                            btn_confirm_est = st.form_submit_button("✅ Finalizar e Confirmar Recebimento")

                            if btn_confirm_est:
                                try:
                                    dt_inicio = datetime.datetime.fromisoformat(created_at.replace("Z", "+00:00")).date()
                                except Exception:
                                    dt_inicio = datetime.date.today()

                                try:
                                    dt_prom_obj = datetime.datetime.strptime(str(dt_prometida), "%Y-%m-%d").date()
                                    dt_prom_salvar = dt_prom_obj.isoformat()
                                except Exception:
                                    dt_prom_obj = f_dt_entregue
                                    dt_prom_salvar = f_dt_entregue.isoformat()

                                lead_time = (f_dt_entregue - dt_inicio).days
                                no_prazo = f_dt_entregue <= dt_prom_obj
                                otif = no_prazo and (f_qualidade == "SIM")
                                now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

                                supabase.table("solicitacoes_compras").update({
                                    "status": "Finalizado",
                                    "data_finalizacao": now_iso
                                }).eq("id", item_id).execute()

                                supabase.table("desempenho_fornecedores").insert({
                                    "pedido_id": item_id,
                                    "fornecedor": fornecedor,
                                    "data_prometida": dt_prom_salvar,
                                    "data_entregue": f_dt_entregue.isoformat(),
                                    "qualidade_ok": f_qualidade,
                                    "prazo_pagamento_dias": prazo_pg,
                                    "lead_time_dias": lead_time,
                                    "otif_ok": otif
                                }).execute()

                                st.success("🏁 Recebimento registrado com sucesso e pedido finalizado!")
                                st.rerun()

                    st.divider()

# =============================================================================
# ABA 1: CHAT DO ASSISTENTE
# =============================================================================
if aba_chat:
    with aba_chat:
        solicitante_atual = st.session_state.solicitante_str
        is_fabiano = "fabiano" in normalizar_texto(solicitante_atual)

        regras_fabiano = ""
        if is_fabiano:
            regras_fabiano = """
⚠️ REGRA ESPECIAL PARA O USUÁRIO FABIANO:
Como o solicitante é o Fabiano, você DEVE solicitar obrigatoriamente os seguintes campos adicionais antes de registrar a compra:
1. ID Manutenção
2. Compatível (com qual equipamento/máquina)
3. Encapsulamento
4. Custo estimado (R$)
5. Link adicional
6. Datasheet (link ou arquivo/PDF)

Não finalize a solicitação com a ferramenta 'registrar_solicitacao_compra' sem antes perguntar e obter esses 6 dados adicionais do Fabiano.
"""

        system_prompt = f"""
Você é o Assistente Integrado Vital, o sistema inteligente oficial da Vital C.
O operador identified nesta sessão é: '{solicitante_atual}'.

Suas atribuições principais são:

1. COTAR FRETES: Solicite origem, destino, tipo de trajeto ("Apenas Ida" ou "Ida e Volta"), dias por trecho e se é viagem curta. Com todos os 5 dados, chame 'calcular_frete_ia'.

2. SOLICITAR COMPRAS: Quando o usuário enviar uma foto, link ou pedir para comprar um item:
   - Você JÁ SABE quem é o solicitante ({solicitante_atual}), portanto NUNCA PERGUNTE O NOME DO USUÁRIO no chat!
   - Solicite as informações básicas do produto que faltarem:
     1. Link de compra/referência
     2. Código de Referência / Modelo
     3. Quantidade
     4. Motivo da compra

{regras_fabiano}

Assim que possuir TODAS as informações necessárias, invoque 'registrar_solicitacao_compra'.
Seja cortês, profissional e objetivo.
"""

        if "messages" not in st.session_state:
            st.session_state.messages = [{"role": "system", "content": system_prompt}]

        for msg in st.session_state.messages:
            role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", None)
            content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", None)
            has_tools = bool(msg.get("tool_calls")) if isinstance(msg, dict) else bool(getattr(msg, "tool_calls", None))

            if role in ["user", "assistant"] and not has_tools and content:
                with st.chat_message(role):
                    if isinstance(content, list):
                        text_part = next((item["text"] for item in content if item.get("type") == "text"), "")
                        st.markdown(text_part, unsafe_allow_html=True)
                    else:
                        st.markdown(content, unsafe_allow_html=True)

        prompt = st.chat_input("Digite sua mensagem, peça um frete ou anexe uma foto...", accept_file=True)
        if prompt:
            user_text = getattr(prompt, "text", "") if not isinstance(prompt, str) else prompt
            user_files = getattr(prompt, "files", []) if not isinstance(prompt, str) else []

            user_payload = []
            if user_files:
                for file in user_files:
                    bytes_data = file.read()
                    base64_image = base64.b64encode(bytes_data).decode('utf-8')
                    user_payload.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}
                    })

            user_payload.append({"type": "text", "text": user_text})
            st.session_state.messages.append({"role": "user", "content": user_payload})

            with st.spinner("Processando..."):
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=st.session_state.messages,
                    tools=tools,
                    tool_choice="auto"
                )

                response_message = response.choices[0].message

                if response_message.tool_calls:
                    st.session_state.messages.append(response_message.model_dump())
                    
                    card_html_gerado = ""
                    for tool_call in response_message.tool_calls:
                        fn_name = tool_call.function.name
                        args = json.loads(tool_call.function.arguments)

                        if fn_name == "calcular_frete_ia":
                            resultado = calcular_frete_ia(
                                origem=args["origem"],
                                destino=args["destino"],
                                tipo_trajeto=args["tipo_trajeto"],
                                dias_por_trecho=args["dias_por_trecho"],
                                is_viagem_curta=args["is_viagem_curta"],
                                solicitante=solicitante_atual
                            )

                            if "sucesso" in resultado:
                                card_html_gerado = f'<div style="background: #ffffff; border: 1px solid #e2e8f0; border-radius: 16px; padding: 20px; box-shadow: 0 4px 15px rgba(0,0,0,0.06); margin-bottom: 25px;"><div style="background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%); padding: 25px 20px; border-radius: 12px; text-align: center; color: white;"><p style="margin:0; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 1.5px; opacity: 0.9; font-weight: 600;">Valor Total Sugerido</p><h1 style="margin: 8px 0 0 0; font-size: 2.8rem; font-weight: 800; letter-spacing: -0.5px;">R$ {formar_real(resultado["preco_final"])}</h1></div><div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-top: 15px; text-align: center;"><div style="background: #f8fafc; padding: 12px 6px; border-radius: 8px; border: 1px solid #f1f5f9;"><div style="font-size: 0.7rem; color: #64748b; font-weight: 700; margin-bottom: 4px;">DISTÂNCIA</div><div style="font-size: 0.95rem; font-weight: 700; color: #0f172a;">{resultado["km_total"]} km</div></div><div style="background: #f8fafc; padding: 12px 6px; border-radius: 8px; border: 1px solid #f1f5f9;"><div style="font-size: 0.7rem; color: #64748b; font-weight: 700; margin-bottom: 4px;">DIESEL</div><div style="font-size: 0.9rem; font-weight: 700; color: #0f172a; white-space: nowrap;">R$ {formar_real(resultado["custo_diesel"])}</div></div><div style="background: #f8fafc; padding: 12px 6px; border-radius: 8px; border: 1px solid #f1f5f9;"><div style="font-size: 0.7rem; color: #64748b; font-weight: 700; margin-bottom: 4px;">HOTEL/ALIM.</div><div style="font-size: 0.9rem; font-weight: 700; color: #0f172a; white-space: nowrap;">R$ {formar_real(resultado["custo_hospedagem_alim"])}</div></div><div style="background: #f8fafc; padding: 12px 6px; border-radius: 8px; border: 1px solid #f1f5f9;"><div style="font-size: 0.7rem; color: #64748b; font-weight: 700; margin-bottom: 4px;">FIXOS</div><div style="font-size: 0.9rem; font-weight: 700; color: #0f172a; white-space: nowrap;">R$ {formar_real(resultado["gastos_fixos"])}</div></div></div></div>'

                        elif fn_name == "registrar_solicitacao_compra":
                            resultado = registrar_solicitacao_compra(
                                descricao=args.get("descricao"),
                                link=args.get("link"),
                                referencia=args.get("referencia"),
                                quantidade=args.get("quantidade"),
                                motivo=args.get("motivo"),
                                solicitante=solicitante_atual,
                                id_manutencao=args.get("id_manutencao"),
                                compativel=args.get("compativel"),
                                encapsulamento=args.get("encapsulamento"),
                                custo_estimado=args.get("custo_estimado"),
                                link_adicional=args.get("link_adicional"),
                                datasheet=args.get("datasheet")
                            )
                            if "sucesso" in resultado:
                                link_url = args.get('link', '#')
                                link_html = f' — <a href="{link_url}" target="_blank" style="color: #0284c7; font-weight: 600; text-decoration: underline;">Ver Produto 🔗</a>' if link_url and link_url != '#' else ''
                                
                                extra_info = ""
                                if args.get("id_manutencao"):
                                    extra_info = f'<div><b>🛠️ ID Manutenção:</b> {args.get("id_manutencao")} | <b>🧩 Compatível:</b> {args.get("compativel", "N/A")}</div><div><b>📦 Encapsulamento:</b> {args.get("encapsulamento", "N/A")} | <b>💰 Custo Est.:</b> {args.get("custo_estimado", "N/A")}</div>'

                                card_html_gerado = f'<div style="background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 12px; padding: 18px; margin-bottom: 20px;"><h4 style="margin: 0 0 12px 0; color: #166534; font-size: 1.1rem;">🛒 Compra Registrada com Sucesso!</h4><div style="display: flex; flex-direction: column; gap: 6px; font-size: 0.95rem; color: #14532d;"><div><b>👤 Solicitante:</b> {solicitante_atual}</div><div><b>📦 Nome do item:</b> {args.get("descricao")}</div><div><b>🔢 Quantidade:</b> {args.get("quantidade")} un.</div><div><b>📋 Detalhe:</b> {args.get("referencia")}{link_html}</div><div><b>🎯 Motivo:</b> {args.get("motivo")}</div>{extra_info}</div></div>'

                        st.session_state.messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": json.dumps(resultado)
                        })

                    final_response = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=st.session_state.messages
                    )

                    texto_final = final_response.choices[0].message.content
                    conteudo_completo = f"{card_html_gerado}\n\n{texto_final}" if card_html_gerado else texto_final
                    st.session_state.messages.append({"role": "assistant", "content": conteudo_completo})

                else:
                    st.session_state.messages.append({"role": "assistant", "content": response_message.content})

            st.rerun()

# =============================================================================
# ABA 2: PAINEL DE GESTÃO DE COMPRAS (RESTRITO AO MODO ADM)
# =============================================================================
if aba_gestao:
    with aba_gestao:
        st.subheader("📋 Gestão e Aprovação de Pedidos (Acesso ADM)")
        
        if supabase:
            try:
                res_kpi = supabase.table("desempenho_fornecedores").select("*").execute().data
                if res_kpi:
                    lead_times = [k.get("lead_time_dias") for k in res_kpi if k.get("lead_time_dias") is not None]
                    lt_medio = sum(lead_times) / len(lead_times) if lead_times else 0.0

                    otifs = [k.get("otif_ok") for k in res_kpi if k.get("otif_ok") is not None]
                    otif_pct = (sum(1 for o in otifs if o) / len(otifs) * 100) if otifs else 0.0

                    prazos_pg = [k.get("prazo_pagamento_dias") for k in res_kpi if k.get("prazo_pagamento_dias") is not None]
                    pmp_medio = sum(prazos_pg) / len(prazos_pg) if prazos_pg else 0.0

                    col_kpi1, col_kpi2, col_kpi3 = st.columns(3)
                    col_kpi1.metric("⏱️ Lead Time Médio", f"{lt_medio:.1f} dias")
                    col_kpi2.metric("🎯 OTIF / Qualidade", f"{otif_pct:.1f}%")
                    col_kpi3.metric("💳 Prazo Médio Pagto", f"{pmp_medio:.0f} dias")
                    st.divider()

                if st.button("📊 Gerar Planilha 'Controle de Compras 2026' (PDF / Google Drive)"):
                    with st.spinner("Gerando PDF em formato Paisagem (sem quebras de texto)..."):
                        resp_compras_compradas = supabase.table("solicitacoes_compras").select("id").in_("status", ["Aguardando entrega", "Aguardando NF", "Finalizado"]).execute().data
                        ids_comprados = set(str(item["id"]) for item in resp_compras_compradas) if resp_compras_compradas else set()

                        resp_cot_hist_raw = supabase.table("cotacoes").select("*").order("id", desc=True).execute().data
                        
                        resp_cot_hist = []
                        cotacoes_pendentes_cnt = 0

                        if resp_cot_hist_raw:
                            for c in resp_cot_hist_raw:
                                p_id = c.get("pedido_id")
                                if p_id is None or str(p_id) in ids_comprados:
                                    resp_cot_hist.append(c)
                                else:
                                    cotacoes_pendentes_cnt += 1

                        if not resp_cot_hist:
                            if cotacoes_pendentes_cnt > 0:
                                st.warning(f"⚠️ Existem {cotacoes_pendentes_cnt} cotação(ões) salvas, mas o pedido correspondente ainda está com status 'Pendente'. Mude o status do pedido para 'Aguardando entrega' ou 'Finalizado' para entrar na planilha de compras efetuadas.")
                            else:
                                st.warning("⚠️ Nenhuma cotação salva encontrada na tabela 'cotacoes'. Certifique-se de executar o SQL no Supabase.")
                        else:
                            pdf_bytes_controle = gerar_pdf_controle_compras(resp_cot_hist)
                            nome_planilha = f"Planilha_Controle_de_Compras_2026_{datetime.date.today().strftime('%d-%m-%Y')}.pdf"

                            link_planilha = salvar_nf_no_drive(
                                pdf_bytes_controle,
                                nome_planilha,
                                mime_type='application/pdf',
                                as_google_doc=False,
                                nome_subpasta="Relatórios IA"
                            )

                            if link_planilha:
                                st.success("✅ PDF 'Controle de compras 2026' gerado no Google Drive!")
                                st.markdown(f"🔗 **[Abrir PDF da Planilha no Google Drive]({link_planilha})**")
                                st.download_button(
                                    label="📥 Baixar Arquivo PDF no Computador",
                                    data=pdf_bytes_controle,
                                    file_name=nome_planilha,
                                    mime="application/pdf"
                                )

            except Exception as e_pdf_gen:
                st.error(f"Erro ao gerar PDF: {e_pdf_gen}")

            with st.expander("➕ Cadastrar Novo Pedido Manualmente (ADM)"):
                with st.form("form_novo_pedido_adm"):
                    st.markdown("#### 📦 Dados Principais")
                    f_solic = st.text_input("Solicitante:", value="Administrador (ADM)")
                    f_desc = st.text_input("Descrição / Nome do Item:")
                    c_f1, c_f2 = st.columns(2)
                    with c_f1:
                        f_qtd = st.number_input("Quantidade:", min_value=1, value=1)
                        f_ref = st.text_input("Referência / Modelo:")
                    with c_f2:
                        f_link = st.text_input("Link do Produto:")
                        f_motivo = st.text_input("Motivo da Compra:")

                    st.markdown("#### 🛠️ Informações Complementares (Manutenção/Técnica)")
                    c_t1, c_t2 = st.columns(2)
                    with c_t1:
                        f_id_manut = st.text_input("ID Manutenção:")
                        f_compat = st.text_input("Compatível:")
                        f_encaps = st.text_input("Encapsulamento:")
                    with c_t2:
                        f_custo_est = st.text_input("Custo Estimado (R$):")
                        f_link_add = st.text_input("Link Adicional:")
                        f_datasheet = st.text_input("Datasheet:")

                    btn_salvar_adm = st.form_submit_button("💾 Salvar Pedido no Sistema")

                    if btn_salvar_adm:
                        if not f_desc.strip():
                            st.error("⚠️ Preencha pelo menos a descrição do item!")
                        else:
                            res_cad = registrar_solicitacao_compra(
                                descricao=f_desc,
                                link=f_link or "#",
                                referencia=f_ref or "N/A",
                                quantidade=f_qtd,
                                motivo=f_motivo or "N/A",
                                solicitante=f_solic,
                                id_manutencao=f_id_manut,
                                compativel=f_compat,
                                encapsulamento=f_encaps,
                                custo_estimado=f_custo_est,
                                link_adicional=f_link_add,
                                datasheet=f_datasheet
                            )
                            if res_cad.get("sucesso"):
                                st.success("✅ Pedido cadastrado com sucesso!")
                                st.rerun()

            st.divider()

        if not supabase:
            st.warning("⚠️ O Supabase não está conectado.")
        else:
            filtro_status = st.selectbox(
                "Filtrar por Status:", 
                ["Pendente", "Aguardando entrega", "Aguardando NF", "Finalizado", "Recusado", "Todos (Com Histórico)"],
                index=0
            )

            query = supabase.table("solicitacoes_compras").select("*")
            
            if filtro_status != "Todos (Com Histórico)":
                query = query.eq("status", filtro_status)
                
            dados_compras = query.order("id", desc=True).execute().data

            if not dados_compras:
                st.info(f"Nenhuma solicitação encontrada para o filtro **'{filtro_status}'**.")
            else:
                st.markdown(f"Exibindo **{len(dados_compras)}** solicitação(ões):")
                
                for item in dados_compras:
                    item_id = item.get("id")
                    desc = item.get("item_descricao", "Sem descrição")
                    qtd = item.get("quantidade", 1)
                    ref = item.get("referencia", "N/A")
                    motivo = item.get("motivo", "N/A")
                    solic = item.get("solicitante", "N/A")
                    link = item.get("link_produto", "#")
                    status_atual = item.get("status", "Pendente")
                    link_nf = item.get("link_nf")
                    link_cotacao = item.get("link_cotacao")
                    created_at = item.get("created_at")
                    data_finalizacao = item.get("data_finalizacao")

                    id_manut = item.get("id_manutencao")
                    compat = item.get("compativel")
                    encaps = item.get("encapsulamento")
                    custo_est = item.get("custo_estimado")
                    num_pedido = item.get("numero_pedido")
                    fornecedor = item.get("fornecedor_vencedor")
                    data_prometida = item.get("data_prometida")

                    if status_atual == "Pendente":
                        cor_borda = "#f59e0b"
                    elif status_atual == "Aguardando entrega":
                        cor_borda = "#10b981"
                    elif status_atual == "Aguardando NF":
                        cor_borda = "#2563eb"
                    elif status_atual == "Finalizado":
                        cor_borda = "#64748b"
                    else:
                        cor_borda = "#ef4444"

                    tempo_str = formatar_tempo_decorrido(created_at, data_finalizacao)
                    rotulo_tempo = "🏁 Tempo Total:" if data_finalizacao else "⏳ Em aberto há:"

                    campos_extra_adm = ""
                    if num_pedido or fornecedor or data_prometida:
                        campos_extra_adm += f'<p style="margin: 4px 0 0 0; font-size: 0.85rem; color: #475569;"><b>🏷️ Nº Pedido:</b> {num_pedido or "N/A"} | <b>🏢 Fornecedor:</b> {fornecedor or "N/A"} | <b>📅 Prometido para:</b> {data_prometida or "N/A"}</p>'
                    if id_manut or compat or encaps or custo_est:
                        campos_extra_adm += f'<p style="margin: 4px 0 0 0; font-size: 0.85rem; color: #475569;"><b>🛠️ ID Manut:</b> {id_manut or "N/A"} | <b>🧩 Compatível:</b> {compat or "N/A"} | <b>📦 Encaps:</b> {encaps or "N/A"} | <b>💰 Custo Est:</b> {custo_est or "N/A"}</p>'

                    card_html = f'<div style="border-left: 5px solid {cor_borda}; background: #f8fafc; padding: 15px; border-radius: 8px; margin-bottom: 12px; border: 1px solid #e2e8f0; border-left-width: 5px;"><div style="display: flex; justify-content: space-between; align-items: center;"><h4 style="margin: 0; color: #0f172a;">📦 {desc}</h4><span style="background: {cor_borda}; color: white; padding: 3px 10px; border-radius: 12px; font-size: 0.8rem; font-weight: bold;">{status_atual}</span></div><p style="margin: 8px 0 4px 0; font-size: 0.9rem;"><b>👤 Solicitante:</b> {solic}</p><p style="margin: 0 0 4px 0; font-size: 0.9rem;"><b>🔢 Quantidade:</b> {qtd} un. | <b>📋 Ref:</b> {ref}</p><p style="margin: 0 0 4px 0; font-size: 0.9rem;"><b>🎯 Motivo:</b> {motivo}</p>{campos_extra_adm}<p style="margin: 4px 0 4px 0; font-size: 0.9rem; color: #1e293b;"><b>{rotulo_tempo}</b> <span style="background: #e2e8f0; padding: 2px 8px; border-radius: 6px; font-weight: 600;">{tempo_str}</span></p><p style="margin: 0; font-size: 0.9rem;">🔗 <a href="{link}" target="_blank">Ver Link do Produto</a></p></div>'

                    with st.container():
                        st.markdown(card_html, unsafe_allow_html=True)

                        if link_cotacao:
                            st.info("📊 **Cotação Anexada!**")
                            col_c_link1, col_c_link2 = st.columns([3, 1])
                            with col_c_link1:
                                st.markdown(f"🔗 [Clique aqui para abrir a Cotação no Google Drive]({link_cotacao})")
                            with col_c_link2:
                                if st.button("🗑️ Remover Cotação", key=f"btn_del_cot_{item_id}"):
                                    supabase.table("solicitacoes_compras").update({"link_cotacao": None}).eq("id", item_id).execute()
                                    st.success("Cotação removida deste pedido!")
                                    st.rerun()

                        if link_nf:
                            st.success("📄 **Nota Fiscal Anexada!**")
                            st.markdown(f"🔗 [Clique aqui para abrir a NF no Google Drive]({link_nf})")
                        
                        if status_atual in ["Pendente", "Aguardando NF", "Aguardando entrega"]:
                            # --- MÓDULO DE GERAR COTAÇÃO COMPARATIVA (MÍNIMO 3 FORNECEDORES) ---
                            with st.expander("📊 Gerar Cotação Comparativa (Mínimo 3 Fornecedores)"):
                                with st.form(f"form_gerar_cot_{item_id}"):
                                    st.markdown("##### 🏢 Opção 1 (Fornecedor 1)")
                                    col_c1, col_c2, col_c3 = st.columns(3)
                                    with col_c1: forn1_nome = st.text_input("Nome Fornecedor 1:", key=f"f1_n_{item_id}")
                                    with col_c2: forn1_preco = st.number_input("Preço Unit. (R$):", min_value=0.0, value=0.0, step=0.01, key=f"f1_p_{item_id}")
                                    with col_c3: forn1_frete = st.number_input("Frete (R$):", min_value=0.0, value=0.0, step=0.01, key=f"f1_f_{item_id}")
                                    forn1_link = st.text_input("🔗 Link da Cotação / Produto 1 (Opcional):", key=f"f1_l_{item_id}")

                                    st.markdown("##### 🏢 Opção 2 (Fornecedor 2)")
                                    col_c4, col_c5, col_c6 = st.columns(3)
                                    with col_c4: forn2_nome = st.text_input("Nome Fornecedor 2:", key=f"f2_n_{item_id}")
                                    with col_c5: forn2_preco = st.number_input("Preço Unit. (R$):", min_value=0.0, value=0.0, step=0.01, key=f"f2_p_{item_id}")
                                    with col_c6: forn2_frete = st.number_input("Frete (R$):", min_value=0.0, value=0.0, step=0.01, key=f"f2_f_{item_id}")
                                    forn2_link = st.text_input("🔗 Link da Cotação / Produto 2 (Opcional):", key=f"f2_l_{item_id}")

                                    st.markdown("##### 🏢 Opção 3 (Fornecedor 3)")
                                    col_c7, col_c8, col_c9 = st.columns(3)
                                    with col_c7: forn3_nome = st.text_input("Nome Fornecedor 3:", key=f"f3_n_{item_id}")
                                    with col_c8: forn3_preco = st.number_input("Preço Unit. (R$):", min_value=0.0, value=0.0, step=0.01, key=f"f3_p_{item_id}")
                                    with col_c9: forn3_frete = st.number_input("Frete (R$):", min_value=0.0, value=0.0, step=0.01, key=f"f3_f_{item_id}")
                                    forn3_link = st.text_input("🔗 Link da Cotação / Produto 3 (Opcional):", key=f"f3_l_{item_id}")

                                    btn_gerar_cot = st.form_submit_button("⚙️ Gerar Documento de Cotação em PDF & Salvar")

                                    if btn_gerar_cot:
                                        opcoes = []
                                        if forn1_nome.strip() and forn1_preco > 0:
                                            tot1 = (forn1_preco * qtd) + forn1_frete
                                            opcoes.append({"nome": forn1_nome.strip(), "pu": forn1_preco, "frete": forn1_frete, "total": tot1, "link": forn1_link.strip()})
                                        if forn2_nome.strip() and forn2_preco > 0:
                                            tot2 = (forn2_preco * qtd) + forn2_frete
                                            opcoes.append({"nome": forn2_nome.strip(), "pu": forn2_preco, "frete": forn2_frete, "total": tot2, "link": forn2_link.strip()})
                                        if forn3_nome.strip() and forn3_preco > 0:
                                            tot3 = (forn3_preco * qtd) + forn3_frete
                                            opcoes.append({"nome": forn3_nome.strip(), "pu": forn3_preco, "frete": forn3_frete, "total": tot3, "link": forn3_link.strip()})

                                        if len(opcoes) < 3:
                                            st.error("⚠️ É obrigatório cadastrar no mínimo 3 fornecedores com preços válidos para gerar a cotação comparativa!")
                                        else:
                                            opcoes_ordenadas = sorted(opcoes, key=lambda x: x["total"])
                                            vencedor = opcoes_ordenadas[0]

                                            tot1_val = opcoes_ordenadas[0]['total']
                                            tot2_val = opcoes_ordenadas[1]['total']
                                            tot3_val = opcoes_ordenadas[2]['total']

                                            media_orcam = (tot1_val + tot2_val + tot3_val) / 3.0
                                            preco_alvo = media_orcam * 0.90
                                            valor_comprado = vencedor['total']
                                            economia_real = media_orcam - valor_comprado
                                            status_meta_txt = "Atingida" if valor_comprado <= preco_alvo else "Não Atingida"

                                            if supabase:
                                                try:
                                                    supabase.table("cotacoes").insert({
                                                        "data_cotacao": datetime.date.today().isoformat(),
                                                        "produto": desc,
                                                        "fornecedor_a": f"{opcoes_ordenadas[0]['nome']} (R$ {formar_real(tot1_val)})",
                                                        "valor_a": float(tot1_val),
                                                        "fornecedor_b": f"{opcoes_ordenadas[1]['nome']} (R$ {formar_real(tot2_val)})",
                                                        "valor_b": float(tot2_val),
                                                        "fornecedor_c": f"{opcoes_ordenadas[2]['nome']} (R$ {formar_real(tot3_val)})",
                                                        "valor_c": float(tot3_val),
                                                        "media_orcam": float(media_orcam),
                                                        "preco_alvo": float(preco_alvo),
                                                        "valor_comprado": float(valor_comprado),
                                                        "economia_real": float(economia_real),
                                                        "status_meta": status_meta_txt,
                                                        "solicitante": solic,
                                                        "pedido_id": int(item_id)
                                                    }).execute()
                                                except Exception as e_cot:
                                                    st.error(f"⚠️ Erro ao gravar no Supabase: {e_cot}")

                                            pdf_ind_bytes = gerar_pdf_cotacao_individual(desc, qtd, ref, solic, motivo, opcoes_ordenadas, vencedor)
                                            desc_limpa = "".join(c for c in desc[:15] if c.isalnum() or c in " -_").strip()
                                            nome_arq_ind = f"Cotacao_Sistema_{item_id}_{desc_limpa}.pdf"

                                            link_cot_gerada = salvar_nf_no_drive(
                                                pdf_ind_bytes,
                                                nome_arq_ind,
                                                mime_type='application/pdf',
                                                as_google_doc=False,
                                                nome_subpasta="Cotações"
                                            )

                                            if link_cot_gerada:
                                                supabase.table("solicitacoes_compras").update({
                                                    "link_cotacao": link_cot_gerada,
                                                    "fornecedor_vencedor": vencedor['nome']
                                                }).eq("id", item_id).execute()
                                                st.success(f"✅ Cotação Vital C salva em PDF! Vencedor: {vencedor['nome']} (R$ {formar_real(vencedor['total'])})")
                                                st.rerun()

                            # --- MÓDULO DE CADASTRO / UPLOAD DE DADOS ---
                            with st.expander("📝 Cadastrar / Atualizar Dados da Compra e NF"):
                                with st.form(f"form_upload_nf_{item_id}"):
                                    col_a1, col_a2 = st.columns(2)
                                    with col_a1:
                                        num_pedido_input = st.text_input("Número do Pedido de Compra (Obrigatório):", value=num_pedido or "", key=f"input_ped_{item_id}")
                                        f_fornec_input = st.text_input("Fornecedor Vencedor (Obrigatório):", value=fornecedor or "", key=f"input_forn_{item_id}")
                                    with col_a2:
                                        val_dt_prom = datetime.date.today()
                                        if data_prometida:
                                            try:
                                                val_dt_prom = datetime.datetime.strptime(str(data_prometida), "%Y-%m-%d").date()
                                            except Exception:
                                                pass
                                        f_dt_prometida_input = st.date_input("Data Estimada / Prometida de Entrega:", value=val_dt_prom, key=f"input_dtp_{item_id}")
                                        f_paz_pg_input = st.number_input("Prazo de Pagamento (Dias):", min_value=0, value=30, key=f"input_ppg_{item_id}")
                                    
                                    uploaded_cot = st.file_uploader("Anexar PDF da Cotação Externa (Opcional):", type=["pdf"], key=f"file_cot_{item_id}")
                                    uploaded_nf = st.file_uploader("Anexar PDF da NF (Opcional - pode anexar depois):", type=["pdf"], key=f"file_nf_{item_id}")
                                    btn_save_nf_adm = st.form_submit_button("💾 Salvar Dados da Compra e Anexos")

                                    if btn_save_nf_adm:
                                        if not num_pedido_input.strip():
                                            st.error("⚠️ Por favor, preencha o Número do Pedido de Compra!")
                                        elif not f_fornec_input.strip():
                                            st.error("⚠️ Por favor, preencha o Fornecedor Vencedor!")
                                        else:
                                            update_payload = {
                                                "status": "Aguardando entrega",
                                                "numero_pedido": num_pedido_input.strip(),
                                                "fornecedor_vencedor": f_fornec_input.strip(),
                                                "data_prometida": f_dt_prometida_input.isoformat(),
                                                "prazo_pagamento_dias": f_paz_pg_input
                                            }
                                            
                                            desc_limpa = "".join(c for c in desc[:15] if c.isalnum() or c in " -_").strip()

                                            if uploaded_cot:
                                                with st.spinner("Enviando Cotação para o Google Drive..."):
                                                    bytes_cot = uploaded_cot.read()
                                                    nome_cot = f"Cotacao_Pedido_{num_pedido_input.strip()}_{item_id}_{desc_limpa}.pdf"
                                                    link_cot_drive = salvar_nf_no_drive(bytes_cot, nome_cot, nome_subpasta="Cotações")
                                                    if link_cot_drive:
                                                        update_payload["link_cotacao"] = link_cot_drive

                                            if uploaded_nf:
                                                with st.spinner("Enviando Nota Fiscal para o Google Drive..."):
                                                    bytes_data = uploaded_nf.read()
                                                    nome_arquivo = f"NF_Pedido_{num_pedido_input.strip()}_{item_id}_{desc_limpa}.pdf"
                                                    link_drive = salvar_nf_no_drive(bytes_data, nome_arquivo)
                                                    if link_drive:
                                                        update_payload["link_nf"] = link_drive

                                            supabase.table("solicitacoes_compras").update(update_payload).eq("id", item_id).execute()
                                            st.success("Dados da compra e documentos salvos com sucesso!")
                                            st.rerun()

                        col1, col2, col3 = st.columns(3)
                        with col1:
                            if st.button("🚚 Aguardando entrega", key=f"entreg_{item_id}"):
                                supabase.table("solicitacoes_compras").update({"status": "Aguardando entrega"}).eq("id", item_id).execute()
                                st.rerun()
                        with col2:
                            if st.button("📄 Aguardando NF", key=f"ped_nf_{item_id}"):
                                supabase.table("solicitacoes_compras").update({"status": "Aguardando NF"}).eq("id", item_id).execute()
                                st.rerun()
                        with col3:
                            if st.button("❌ Recusar", key=f"rec_{item_id}"):
                                now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
                                supabase.table("solicitacoes_compras").update({
                                    "status": "Recusado",
                                    "data_finalizacao": now_iso
                                }).eq("id", item_id).execute()
                                st.rerun()
                        
                        st.divider()