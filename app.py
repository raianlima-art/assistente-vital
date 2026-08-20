import base64
import csv
import datetime
import glob
import importlib.util
import io
import json
import os
import smtplib
import unicodedata
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import urlparse

from dotenv import load_dotenv
from geopy.distance import geodesic
from geopy.geocoders import Photon
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from openai import OpenAI
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
import streamlit as st
from supabase import Client, create_client

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
    initial_sidebar_state="expanded",
)


def carregar_css(caminho="style.css"):
    if os.path.exists(caminho):
        with open(caminho, "r", encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)


carregar_css()

# -----------------------------------------------------------------------------
# 3. INICIALIZAÇÃO DE CONEXÕES E WHATSAPP
# -----------------------------------------------------------------------------
if not API_KEY_OPENAI:
    st.error("❌ A chave 'OPENAI_API_KEY' não foi encontrada!")
    st.stop()

client = OpenAI(api_key=API_KEY_OPENAI)

supabase: Client = None
if SUPABASE_URL and SUPABASE_KEY and "seu-projeto" not in SUPABASE_URL:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        st.sidebar.warning(f"⚠️ Supabase offline: {e}")


def enviar_whatsapp(numero, mensagem):
    """Envia mensagem no WhatsApp via Evolution API"""
    url = get_secret("WHATSAPP_API_URL")
    token = get_secret("WHATSAPP_API_TOKEN")
    
    if not url or not numero:
        return False
        
    numero_limpo = "".join(c for c in str(numero) if c.isdigit())
    if not numero_limpo.startswith("55") and len(numero_limpo) <= 11:
        numero_limpo = "55" + numero_limpo
        
    payload = {
        "number": numero_limpo,
        "text": mensagem
    }
    
    try:
        req = urllib.request.Request(url, method="POST")
        req.add_header('Content-Type', 'application/json')
        if token:
            req.add_header('apikey', token)
            
        data = json.dumps(payload).encode('utf-8')
        urllib.request.urlopen(req, data=data, timeout=5)
        return True
    except Exception as e:
        print(f"Erro ao enviar WhatsApp: {e}")
        return False


def extrair_telefone(solicitante_str):
    """Extrai o número do WhatsApp de dentro da string do solicitante."""
    try:
        if "[WA:" in solicitante_str:
            return solicitante_str.split("[WA:")[1].split("]")[0].strip()
    except Exception:
        pass
    return ""


# -----------------------------------------------------------------------------
# 4. FUNÇÕES AUXILIARES
# -----------------------------------------------------------------------------
def normalizar_texto(texto):
    if not texto:
        return ""
    nfkd = unicodedata.normalize("NFD", str(texto))
    return "".join([c for c in nfkd if not unicodedata.combining(c)]).lower().strip()


def extrair_nome_fornecedor(url):
    if not url or not isinstance(url, str) or url == "#" or not url.strip():
        return ""
    
    u = url.lower().strip()
    if "mercadolivre" in u or "mercadolibre" in u: return "Mercado Livre"
    if "aliexpress" in u: return "AliExpress"
    if "amazon" in u: return "Amazon"
    if "shopee" in u: return "Shopee"
    if "kabum" in u: return "KaBuM!"
    if "magazineluiza" in u or "magalu" in u: return "Magalu"
    if "lojadomecanico" in u: return "Loja do Mecânico"
    if "alibaba" in u: return "Alibaba"
    
    try:
        if not u.startswith(("http://", "https://")):
            u = "https://" + u
        domain = urlparse(u).netloc
        partes = domain.replace("www.", "").split(".")
        if partes and partes[0]:
            return partes[0].capitalize()
    except Exception:
        pass
    return ""


def converter_valor_float(valor_input):
    if not valor_input:
        return 0.0
    try:
        v_str = str(valor_input).replace("R$", "").strip()
        if "," in v_str and "." in v_str:
            v_str = v_str.replace(".", "").replace(",", ".")
        elif "," in v_str:
            v_str = v_str.replace(",", ".")
        return float(v_str)
    except Exception:
        return 0.0


def formatar_tempo_decorrido(data_inicio_str, data_fim_str=None):
    if not data_inicio_str:
        return "N/D"
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
            return f"{horas}h {minutos}m"
        else:
            return f"{minutos}m"
    except Exception:
        return "N/D"


def formar_real(valor):
    if valor is None:
        return "0,00"
    try:
        if isinstance(valor, (float, int)):
            return "{:,.2f}".format(valor).replace(",", "X").replace(".", ",").replace("X", ".")
        v_str = str(valor).replace("R$", "").strip()
        if not v_str:
            return "0,00"
        if "," in v_str:
            v_str = v_str.replace(".", "").replace(",", ".")
        val = float(v_str)
        return "{:,.2f}".format(val).replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "0,00"


def obter_servico_drive():
    try:
        if not GOOGLE_DRIVE_FOLDER_ID:
            return None
        SCOPES = ["https://www.googleapis.com/auth/drive"]
        if os.path.exists("credentials.json"):
            creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
        else:
            creds_raw = get_secret("GOOGLE_DRIVE_CREDENTIALS")
            if not creds_raw:
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
                return None
            if "private_key" in creds_json:
                pk = str(creds_json["private_key"]).strip('"\'').replace("\\n", "\n")
                creds_json["private_key"] = pk
            creds = Credentials.from_service_account_info(creds_json, scopes=SCOPES)
        return build("drive", "v3", credentials=creds)
    except Exception as e:
        print(f"Erro ao autenticar Google Drive: {e}")
        return None


def deletar_arquivo_do_drive(link_ou_id):
    if not link_ou_id:
        return False
    try:
        file_id = str(link_ou_id)
        if "id=" in file_id:
            file_id = file_id.split("id=")[1].split("&")[0]
        elif "/d/" in file_id:
            file_id = file_id.split("/d/")[1].split("/")[0]

        service = obter_servico_drive()
        if service:
            service.files().delete(fileId=file_id, supportsAllDrives=True).execute()
            return True
    except Exception as e:
        print(f"Erro ao deletar arquivo no Drive: {e}")
    return False


def obter_ou_criar_subpasta(service, parent_folder_id, nome_pasta):
    query = f"'{parent_folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and name='{nome_pasta}' and trashed=false"
    resultados = service.files().list(q=query, spaces="drive", supportsAllDrives=True, includeItemsFromAllDrives=True, fields="files(id, name)").execute()
    pastas = resultados.get("files", [])
    if pastas:
        return pastas[0]["id"]
    else:
        file_metadata = {
            "name": nome_pasta,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_folder_id],
        }
        pasta_criada = service.files().create(body=file_metadata, fields="id", supportsAllDrives=True).execute()
        return pasta_criada.get("id")


def obter_ou_criar_caminho_pastas(service, root_id, caminho):
    if isinstance(caminho, str):
        partes = [p.strip() for p in caminho.replace("\\", "/").split("/") if p.strip()]
    elif isinstance(caminho, list):
        partes = caminho
    else:
        partes = [str(caminho)]

    atual_id = root_id
    for nome_pasta in partes:
        atual_id = obter_ou_criar_subpasta(service, atual_id, nome_pasta)
    return atual_id


def salvar_nf_no_drive(file_bytes, nome_arquivo, mime_type="application/pdf", as_google_doc=False, nome_subpasta=None):
    try:
        service = obter_servico_drive()
        if not service:
            st.error("❌ Não foi possível conectar ao Google Drive.")
            return None

        if not nome_subpasta:
            data_hoje = datetime.datetime.now().strftime("%d-%m-%Y")
            nome_subpasta = ["Relatórios IA", "Backup", data_hoje]

        pasta_destino_id = obter_ou_criar_caminho_pastas(service, GOOGLE_DRIVE_FOLDER_ID, nome_subpasta)
        file_metadata = {"name": nome_arquivo, "parents": [pasta_destino_id]}

        if as_google_doc:
            file_metadata["mimeType"] = "application/vnd.google-apps.document"

        media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype=mime_type, resumable=True)
        file = service.files().create(body=file_metadata, media_body=media, fields="id, webViewLink", supportsAllDrives=True).execute()
        return file.get("webViewLink")
    except Exception as e:
        st.error(f"❌ Erro ao salvar no Google Drive: {e}")
        return None


def gerar_pdf_controle_compras(resp_cot_hist, mes_referencia="Todos", ano_referencia="2026"):
    if ano_referencia == "Todos":
        ano_referencia = str(datetime.datetime.now().year)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=15,
        leftMargin=15,
        topMargin=15,
        bottomMargin=15,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleStyle", fontSize=13, leading=15, alignment=1, textColor=colors.HexColor("#0f172a"), fontName="Helvetica-Bold"
    )
    subtitle_style = ParagraphStyle(
        "SubTitleStyle", fontSize=8, leading=10, alignment=1, textColor=colors.HexColor("#475569"), fontName="Helvetica-Bold"
    )

    elements = [
        Paragraph(f"<b>STATUS GASTOS OU ECONOMIA - MENSAL/ANUAL ({ano_referencia})</b>", title_style),
        Paragraph("VITAL C — PAINEL CONSOLIDADO DE COMPRAS E METAS", subtitle_style),
        Spacer(1, 8),
    ]

    MESES_NOME = [
        "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
        "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"
    ]

    resumo_mensal = {m: {"media": 0.0, "meta": 0.0, "gasto": 0.0, "economia": 0.0} for m in range(1, 13)}
    meses_fechados = set()

    if supabase:
        try:
            res_f = supabase.table("fechamento_mensal").select("*").eq("ano", str(ano_referencia)).execute().data
            if res_f:
                for f in res_f:
                    m_idx = int(str(f.get("mes")).strip())
                    resumo_mensal[m_idx]["media"] = float(f.get("total_medias") or 0)
                    resumo_mensal[m_idx]["meta"] = float(f.get("meta_gasto") or 0)
                    resumo_mensal[m_idx]["gasto"] = float(f.get("gasto_real") or 0)
                    resumo_mensal[m_idx]["economia"] = float(f.get("economia_total") or 0)
                    meses_fechados.add(m_idx)
        except Exception as e_fech:
            st.sidebar.error(f"Erro ao carregar fechamento_mensal: {e_fech}")

    for item in resp_cot_hist:
        dt_c = item.get("data_cotacao") or ""
        try:
            dt_obj = datetime.datetime.strptime(dt_c, "%Y-%m-%d")
            if str(dt_obj.year) == str(ano_referencia):
                m_idx = dt_obj.month
                if m_idx not in meses_fechados:
                    resumo_mensal[m_idx]["media"] += float(item.get("media_orcam", 0) or 0)
                    resumo_mensal[m_idx]["meta"] += float(item.get("preco_alvo", 0) or 0)
                    resumo_mensal[m_idx]["gasto"] += float(item.get("valor_comprado", 0) or 0)
                    resumo_mensal[m_idx]["economia"] += float(item.get("economia_real", 0) or 0)
        except Exception:
            pass

    th_res_white = ParagraphStyle("THRW", fontSize=7.5, leading=9, fontName="Helvetica-Bold", textColor=colors.white, alignment=1)
    th_res_dark = ParagraphStyle("THRD", fontSize=7.5, leading=9, fontName="Helvetica-Bold", textColor=colors.HexColor("#0f172a"), alignment=1)
    td_res_style = ParagraphStyle("TDRS", fontSize=7.5, leading=9, fontName="Helvetica", alignment=1)
    td_res_bold = ParagraphStyle("TDRB", fontSize=7.5, leading=9, fontName="Helvetica-Bold", alignment=1)

    resumo_data = [[
        Paragraph("<b>Mês</b>", th_res_white),
        Paragraph("<b>Total Médias (R$)</b>", th_res_dark),
        Paragraph("<b>Meta de Gasto (R$)</b>", th_res_dark),
        Paragraph("<b>Gasto Real (R$)</b>", th_res_dark),
        Paragraph("<b>Economia Total (R$)</b>", th_res_white),
        Paragraph("<b>% Economia</b>", th_res_white),
    ]]

    resumo_styles = [
        ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#065f46")),
        ("BACKGROUND", (1, 0), (3, 0), colors.HexColor("#eab308")),
        ("BACKGROUND", (4, 0), (5, 0), colors.HexColor("#065f46")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]

    tot_med_ano = sum(r["media"] for r in resumo_mensal.values())
    tot_meta_ano = sum(r["meta"] for r in resumo_mensal.values())
    tot_gasto_ano = sum(r["gasto"] for r in resumo_mensal.values())
    tot_econ_ano = sum(r["economia"] for r in resumo_mensal.values())
    tot_pct_ano = (tot_econ_ano / tot_med_ano * 100) if tot_med_ano > 0 else 0.0

    for m_idx in range(1, 13):
        nome_mes = MESES_NOME[m_idx - 1]
        med = resumo_mensal[m_idx]["media"]
        meta = resumo_mensal[m_idx]["meta"]
        gasto = resumo_mensal[m_idx]["gasto"]
        econ = resumo_mensal[m_idx]["economia"]
        pct = (econ / med * 100) if med > 0 else 0.0

        bg_color = colors.HexColor("#d1fae5") if med > 0 else colors.HexColor("#ffffff")

        resumo_data.append([
            Paragraph(nome_mes, td_res_bold),
            Paragraph(f"R$ {formar_real(med)}", td_res_style),
            Paragraph(f"R$ {formar_real(meta)}", td_res_style),
            Paragraph(f"R$ {formar_real(gasto)}", td_res_style),
            Paragraph(f"R$ {formar_real(econ)}", td_res_bold),
            Paragraph(f"{pct:.2f}%", td_res_bold),
        ])
        resumo_styles.append(("BACKGROUND", (0, m_idx), (-1, m_idx), bg_color))

    tot_row_idx = len(resumo_data)
    tot_txt_style = ParagraphStyle("TTXT", fontSize=8, leading=10, fontName="Helvetica-Bold", textColor=colors.HexColor("#0f172a"), alignment=1)
    tot_white_style = ParagraphStyle("TTXTW", fontSize=8, leading=10, fontName="Helvetica-Bold", textColor=colors.white, alignment=1)

    resumo_data.append([
        Paragraph("TOTAL", tot_txt_style),
        Paragraph(f"R$ {formar_real(tot_med_ano)}", tot_txt_style),
        Paragraph(f"R$ {formar_real(tot_meta_ano)}", tot_txt_style),
        Paragraph(f"R$ {formar_real(tot_gasto_ano)}", tot_txt_style),
        Paragraph(f"R$ {formar_real(tot_econ_ano)}", tot_txt_style),
        Paragraph(f"{tot_pct_ano:.2f}%", tot_white_style),
    ])

    resumo_styles.append(("BACKGROUND", (0, tot_row_idx), (4, tot_row_idx), colors.HexColor("#93c5fd")))
    resumo_styles.append(("BACKGROUND", (5, tot_row_idx), (5, tot_row_idx), colors.HexColor("#15803d")))

    t_resumo = Table(resumo_data, colWidths=[100, 140, 140, 140, 140, 100])
    t_resumo.setStyle(TableStyle(resumo_styles))
    elements.append(t_resumo)
    elements.append(Spacer(1, 12))

    cotacoes_filtradas_mes = []
    for item in resp_cot_hist:
        dt_c = item.get("data_cotacao") or ""
        try:
            dt_obj = datetime.datetime.strptime(dt_c, "%Y-%m-%d")
            m_str = f"{dt_obj.month:02d}"
            a_str = str(dt_obj.year)

            if (ano_referencia == "Todos" or a_str == str(ano_referencia)) and \
               (mes_referencia == "Todos" or m_str == str(mes_referencia)):
                cotacoes_filtradas_mes.append(item)
        except Exception:
            pass

    if cotacoes_filtradas_mes:
        elements.append(Paragraph("<b>📋 DETALHAMENTO DOS ITENS COTADOS NO PERÍODO ATIVO</b>", title_style))
        elements.append(Spacer(1, 6))

        th_det_white = ParagraphStyle("THDW", fontSize=7.5, leading=9, fontName="Helvetica-Bold", textColor=colors.white, alignment=1)
        th_det_dark = ParagraphStyle("THDD", fontSize=7.5, leading=9, fontName="Helvetica-Bold", textColor=colors.HexColor("#0f172a"), alignment=1)

        comp_cells = [
            Paragraph("<b>Mês / Data</b>", th_det_dark),
            Paragraph("<b>Produto</b>", th_det_dark),
            Paragraph("<b>Fornecedor A</b>", th_det_dark),
            Paragraph("<b>Fornecedor B</b>", th_det_dark),
            Paragraph("<b>Fornecedor C</b>", th_det_dark),
            Paragraph("<b>Média Orçamentos</b>", th_det_white),
            Paragraph("<b>Preço Alvo</b>", th_det_white),
            Paragraph("<b>Valor Comprado</b>", th_det_dark),
            Paragraph("<b>Economia Real</b>", th_det_white),
            Paragraph("<b>Status Meta</b>", th_det_white),
        ]

        det_data = [comp_cells]
        det_styles = [
            ("BACKGROUND", (0, 0), (4, 0), colors.HexColor("#eab308")),
            ("BACKGROUND", (5, 0), (5, 0), colors.HexColor("#065f46")),
            ("BACKGROUND", (6, 0), (6, 0), colors.HexColor("#1d4ed8")),
            ("BACKGROUND", (7, 0), (7, 0), colors.HexColor("#eab308")),
            ("BACKGROUND", (8, 0), (9, 0), colors.HexColor("#065f46")),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]

        cell_style = ParagraphStyle("TD", fontSize=7, leading=9, fontName="Helvetica", alignment=1)
        cell_left = ParagraphStyle("TDL", fontSize=7, leading=9, fontName="Helvetica-Bold", alignment=0)
        cell_bold = ParagraphStyle("TDB", fontSize=7, leading=9, fontName="Helvetica-Bold", alignment=1)

        for row_idx, item in enumerate(cotacoes_filtradas_mes, start=1):
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

            st_text = "<font color='#15803d'><b>Atingida</b></font>" if ("Atingida" in st_meta and "Não" not in st_meta) else "<font color='#dc2626'><b>Não Atingida</b></font>"

            det_data.append([
                Paragraph(dt_formatted, cell_style),
                Paragraph(prod, cell_left),
                Paragraph(forn_a, cell_style),
                Paragraph(forn_b, cell_style),
                Paragraph(forn_c, cell_style),
                Paragraph(f"R$ {formar_real(med)}", cell_bold),
                Paragraph(f"R$ {formar_real(alvo)}", cell_bold),
                Paragraph(f"R$ {formar_real(comp)}", cell_bold),
                Paragraph(f"R$ {formar_real(econ)}", cell_bold),
                Paragraph(st_text, cell_style),
            ])

            det_styles.append(("BACKGROUND", (2, row_idx), (4, row_idx), colors.HexColor("#fef08a")))
            det_styles.append(("BACKGROUND", (5, row_idx), (5, row_idx), colors.HexColor("#d1fae5")))
            det_styles.append(("BACKGROUND", (6, row_idx), (6, row_idx), colors.HexColor("#dbeafe")))
            det_styles.append(("BACKGROUND", (7, row_idx), (7, row_idx), colors.HexColor("#fef08a")))
            det_styles.append(("BACKGROUND", (8, row_idx), (8, row_idx), colors.HexColor("#d1fae5")))

        t_detalhe = Table(det_data, colWidths=[55, 130, 90, 90, 90, 75, 75, 75, 70, 60], repeatRows=1)
        t_detalhe.setStyle(TableStyle(det_styles))
        elements.append(t_detalhe)
    else:
        msg_style = ParagraphStyle("MSGV", fontSize=8, leading=10, fontName="Helvetica-Oblique", textColor=colors.HexColor("#64748b"), alignment=1)
        elements.append(Spacer(1, 8))
        elements.append(Paragraph(f"<i>Nenhum item ativo para detalhamento no período {mes_referencia}/{ano_referencia}. (Dados arquivados ou sem cotações no mês)</i>", msg_style))

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
        bottomMargin=25,
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "HeaderTitle",
        fontSize=15,
        leading=18,
        alignment=1,
        textColor=colors.white,
        fontName="Helvetica-Bold",
    )
    subtitle_style = ParagraphStyle(
        "HeaderSub",
        fontSize=9,
        leading=11,
        alignment=1,
        textColor=colors.HexColor("#cbd5e1"),
        fontName="Helvetica-Bold",
    )

    header_data = [
        [Paragraph("<b>RELATÓRIO DE COTAÇÃO DE PREÇOS</b>", title_style)],
        [Paragraph("VITAL C", subtitle_style)],
    ]
    header_table = Table(header_data, colWidths=[540])
    header_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#0f172a")),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ])
    )

    elements = [header_table, Spacer(1, 15)]

    sec_title_style = ParagraphStyle(
        "SecTitle",
        fontSize=10,
        leading=12,
        textColor=colors.HexColor("#1e3c72"),
        fontName="Helvetica-Bold",
    )

    elements.append(Paragraph("<b>📦 DADOS DA SOLICITAÇÃO</b>", sec_title_style))
    elements.append(Spacer(1, 6))

    lbl_style = ParagraphStyle("LBL", fontSize=9, leading=12, fontName="Helvetica-Bold", textColor=colors.HexColor("#475569"))
    val_style = ParagraphStyle("VAL", fontSize=9, leading=12, fontName="Helvetica", textColor=colors.HexColor("#0f172a"))

    info_data = [
        [Paragraph("Item / Produto:", lbl_style), Paragraph(str(desc), val_style)],
        [Paragraph("Quantidade:", lbl_style), Paragraph(f"{qtd} un.", val_style)],
        [Paragraph("Referência / Modelo:", lbl_style), Paragraph(str(ref), val_style)],
        [Paragraph("Solicitante:", lbl_style), Paragraph(str(solic), val_style)],
        [Paragraph("Motivo da Compra:", lbl_style), Paragraph(str(motivo), val_style)],
        [Paragraph("Data da Cotação:", lbl_style), Paragraph(datetime.date.today().strftime("%d/%m/%Y"), val_style)],
    ]
    info_table = Table(info_data, colWidths=[140, 400])
    info_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ])
    )

    elements.append(info_table)
    elements.append(Spacer(1, 15))

    elements.append(Paragraph("<b>📊 COMPARATIVO DE PREÇOS</b>", sec_title_style))
    elements.append(Spacer(1, 6))

    th_style = ParagraphStyle("THC", fontSize=8, leading=10, fontName="Helvetica-Bold", textColor=colors.white, alignment=0)

    comp_data = [[
        Paragraph("Fornecedor", th_style),
        Paragraph("Preço Unit.", th_style),
        Paragraph("Frete", th_style),
        Paragraph("Valor Total", th_style),
        Paragraph("Link Cotação", th_style),
        Paragraph("Status", th_style),
    ]]

    comp_styles = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]

    td_style = ParagraphStyle("TDC", fontSize=8, leading=10, fontName="Helvetica", alignment=0)
    td_bold = ParagraphStyle("TDCB", fontSize=8, leading=10, fontName="Helvetica-Bold", alignment=0)
    aprov_style = ParagraphStyle("APROV", fontSize=8, leading=10, fontName="Helvetica-Bold", textColor=colors.HexColor("#15803d"), alignment=1)
    opc_style = ParagraphStyle("OPC", fontSize=8, leading=10, fontName="Helvetica", textColor=colors.HexColor("#64748b"), alignment=1)

    for idx, op in enumerate(opcoes_ordenadas, 1):
        is_aprovado = idx == 1
        st_badge = Paragraph("APROVADO", aprov_style) if is_aprovado else Paragraph("Cotação", opc_style)

        url = op.get("link", "").strip() if op.get("link") else ""
        if url:
            if not (url.startswith("http://") or url.startswith("https://")):
                url = "https://" + url
            link_str = f'<a href="{url}"><font color="#0284c7"><u>Acessar Cotação</u></font></a>'
        else:
            link_str = "Sem link"

        row = [
            Paragraph(op["nome"], td_bold if is_aprovado else td_style),
            Paragraph(f"R$ {formar_real(op['pu'])}", td_style),
            Paragraph(f"R$ {formar_real(op['frete'])}", td_style),
            Paragraph(f"R$ {formar_real(op['total'])}", td_bold if is_aprovado else td_style),
            Paragraph(link_str, td_style),
            st_badge,
        ]
        comp_data.append(row)
        if is_aprovado:
            comp_styles.append(("BACKGROUND", (0, idx), (-1, idx), colors.HexColor("#f0fdf4")))

    comp_table = Table(comp_data, colWidths=[120, 75, 65, 80, 110, 90])
    comp_table.setStyle(TableStyle(comp_styles))

    elements.append(comp_table)
    elements.append(Spacer(1, 15))

    venc_box_data = [
        [Paragraph("<b>📌 ORÇAMENTO APROVADO:</b>", ParagraphStyle("VTB", fontSize=9, leading=12, fontName="Helvetica-Bold", textColor=colors.HexColor("#166534")))],
        [Paragraph(f"<b>{vencedor['nome']}</b> — Valor Total Aprovado: <b>R$ {formar_real(vencedor['total'])}</b>", ParagraphStyle("VD", fontSize=9, leading=12, fontName="Helvetica", textColor=colors.HexColor("#14532d")))],
    ]
    venc_table = Table(venc_box_data, colWidths=[540])
    venc_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f0fdf4")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#bbf7d0")),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ])
    )

    elements.append(venc_table)

    doc.build(elements)
    return buffer.getvalue()


def enviar_email_notificacao(descricao, link, referencia, quantidade, motivo, solicitante, id_manutencao=None, compativel=None, encapsulamento=None, custo_estimado=None, link_adicional=None, datasheet=None):
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
    msg["From"] = EMAIL_REMETENTE
    msg["To"] = EMAIL_DESTINATARIO
    msg["Subject"] = f"🚨 Nova Solicitação de Compra - {solicitante}"

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

    msg.attach(MIMEText(corpo, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
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

    ipva = float(st.session_state.get("ipva", 10000.0))
    seguro = float(st.session_state.get("seguro", 10000.0))
    manut_anual = float(st.session_state.get("manut_anual", 10000.0))
    dias_uteis = int(st.session_state.get("dias_uteis", 365))
    valor_alimentacao_dia = float(st.session_state.get("valor_alimentacao_dia", 70.0))
    valor_pernoite = float(st.session_state.get("valor_pernoite", 250.0))
    consumo = float(st.session_state.get("consumo", 8.0))
    preco_diesel = float(st.session_state.get("preco_diesel", 8.00))
    diaria_motorista = float(st.session_state.get("diaria_motorista", 200.0))
    fator_estrada = float(st.session_state.get("fator_estrada", 0.25))
    margem = float(st.session_state.get("margem", 20.0))

    custo_fixo_diaria = (ipva + seguro + manut_anual) / dias_uteis

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
        custo_diesel + custo_alimentacao_total + custo_pessoal + custo_fixo_veiculo + custo_hospedagem_total
    )
    preco_final = custo_operacional_total * (1 + margem / 100)

    if supabase:
        try:
            supabase.table("cotacoes").insert({
                "origem": origem,
                "destino": destino,
                "km_total": int(dist_total_km),
                "preco_final": preco_final,
                "solicitante": solicitante,
            }).execute()
        except Exception:
            pass

    return {
        "sucesso": True,
        "km_total": int(dist_total_km),
        "custo_diesel": custo_diesel,
        "custo_hospedagem_alim": custo_hospedagem_total + custo_alimentacao_total,
        "gastos_fixos": custo_pessoal + custo_fixo_veiculo,
        "preco_final": preco_final,
    }


def registrar_solicitacao_compra(descricao, link, referencia, quantidade, motivo, solicitante, id_manutencao=None, compativel=None, encapsulamento=None, custo_estimado=None, link_adicional=None, datasheet=None):
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
            "datasheet": datasheet,
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
                "status": "Pendente",
            }
            supabase.table("solicitacoes_compras").insert(payload_fallback).execute()

    enviar_email_notificacao(descricao, link, referencia, quantidade, motivo, solicitante, id_manutencao, compativel, encapsulamento, custo_estimado, link_adicional, datasheet)
    
    num_adm = get_secret("WHATSAPP_ADM_NUMERO")
    if num_adm:
        msg_adm = f"🚨 *Novo Pedido de Compra*\n\n*Solicitante:* {solicitante}\n*Item:* {descricao}\n*Qtd:* {quantidade}\n*Motivo:* {motivo}"
        enviar_whatsapp(num_adm, msg_adm)
        
    return {"sucesso": True, "mensagem": "Item registrado e notificações enviadas!"}


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
                    "is_viagem_curta": {"type": "boolean"},
                },
                "required": ["origem", "destino", "tipo_trajeto", "dias_por_trecho", "is_viagem_curta"],
            },
        },
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
                    "datasheet": {"type": "string"},
                },
                "required": ["descricao", "link", "referencia", "quantidade", "motivo"],
            },
        },
    },
]

# -----------------------------------------------------------------------------
# 5. TELA DE AUTENTICAÇÃO E LOGIN (BLOQUEANTE)
# -----------------------------------------------------------------------------
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False

if "is_adm" not in st.session_state:
    st.session_state.is_adm = False

if "is_estoque" not in st.session_state:
    st.session_state.is_estoque = False

if not st.session_state.autenticado:
    st.markdown(
        """
        <div class="main-header">
            <h1>🤖 Assistente Integrado Vital C</h1>
            <p>Plataforma Inteligente de Compras & Logística</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    aba_login_user, aba_login_restrito = st.tabs([
        "👤 Identificação do Solicitante",
        "🔑 Acesso Restrito (ADM / Estoque)",
    ])

    with aba_login_user:
        with st.form("form_identificacao"):
            nome_user = st.text_input("Seu Nome Completo:")
            setor_user = st.text_input("Seu Setor / Cargo:", placeholder="Ex: Manutenção, Frota, Compras...")
            filial_user = st.selectbox("Unidade / Filial:", ["Arco - São Paulo", "Ultrassom - São Paulo", "Outra"])
            telefone_user = st.text_input("Seu WhatsApp (com DDD):", placeholder="Ex: 11988887777")
            btn_entrar = st.form_submit_button("🚀 Iniciar Atendimento")

            if btn_entrar:
                if not nome_user.strip() or not setor_user.strip() or not telefone_user.strip():
                    st.error("⚠️ Por favor, preencha todos os campos, incluindo seu WhatsApp para receber notificações!")
                else:
                    st.session_state.solicitante_str = f"{nome_user} ({setor_user} - {filial_user}) [WA: {telefone_user}]"
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
# 6. BARRA LATERAL MINIMALISTA
# -----------------------------------------------------------------------------
with st.sidebar:
    st.caption("👤 PERFIL ATIVO")
    st.markdown(f"**{st.session_state.solicitante_str}**")

    if st.button("🚪 Sair da Sessão", key="btn_sb_logout"):
        st.session_state.clear()
        st.rerun()

# -----------------------------------------------------------------------------
# 7. INTERFACE PRINCIPAL
# -----------------------------------------------------------------------------
st.markdown(
    """
    <div class="main-header">
        <h1>🤖 Assistente Integrado Vital C</h1>
        <p>Central de Operações, Cotações e Gestão de Compras</p>
    </div>
    """,
    unsafe_allow_html=True,
)

col_status1, col_status2 = st.columns([3, 1])
with col_status1:
    st.markdown(f"👤 **Perfil Ativo:** `{st.session_state.solicitante_str}`")
with col_status2:
    if st.button("🔄 Alternar Perfil", key="btn_top_switch"):
        st.session_state.clear()
        st.rerun()

st.divider()

if st.session_state.is_adm:
    aba_chat, aba_gestao, aba_ferramentas = st.tabs([
        "💬 Assistente IA",
        "📋 Painel de Compras (ADM)",
        "🧩 Ferramentas Extras",
    ])
    aba_estoque = None
elif st.session_state.is_estoque:
    aba_estoque = st.container()
    aba_chat = None
    aba_gestao = None
    aba_ferramentas = None
else:
    aba_chat = st.container()
    aba_gestao = None
    aba_estoque = None
    aba_ferramentas = None

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
            col_est1, col_est2 = st.columns(2)
            with col_est1:
                filtro_est_status = st.selectbox(
                    "Filtrar por Status (Estoque):",
                    [
                        "Selecione para filtrar...",
                        "Aguardando entrega",
                        "Aguardando NF",
                        "Todos Pendentes de Recebimento",
                    ],
                    index=0,
                    key="select_est_status",
                )
            with col_est2:
                filtro_est_filial = st.selectbox(
                    "Filtrar por Filial:",
                    ["Todas as Filiais", "Arco - São Paulo", "Ultrassom - São Paulo", "Outra"],
                    index=0,
                    key="select_est_filial",
                )

            if filtro_est_status == "Selecione para filtrar...":
                st.info("💡 Selecione um status acima para carregar as entregas pendentes de conferência.")
            else:
                query = supabase.table("solicitacoes_compras").select("*").order("id", desc=True).execute()

                if filtro_est_status == "Todos Pendentes de Recebimento":
                    dados_nf = [item for item in query.data if item.get("status") in ["Aguardando entrega", "Aguardando NF"]]
                else:
                    dados_nf = [item for item in query.data if item.get("status") == filtro_est_status]

                if filtro_est_filial != "Todas as Filiais" and dados_nf:
                    dados_nf = [
                        item for item in dados_nf
                        if normalizar_texto(filtro_est_filial) in normalizar_texto(item.get("solicitante", ""))
                    ]

                if not dados_nf:
                    st.info("Nenhuma entrega encontrada para os filtros selecionados.")
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
                            botoes_docs += f'<a href="{link_cotacao}" target="_blank" style="background: #f0fdf4; color: #15803d; padding: 6px 12px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 0.8rem; border: 1px solid #bbf7d0; margin-right: 6px;">📊 Cotação ↗</a>'
                        if link_nf:
                            botoes_docs += f'<a href="{link_nf}" target="_blank" style="background: #eff6ff; color: #1d4ed8; padding: 6px 12px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 0.8rem; border: 1px solid #bfdbfe;">📄 Nota Fiscal ↗</a>'

                        card_html = (
                            f'<div style="background: #ffffff; padding: 14px 16px; border-radius: 8px; margin-bottom: 8px; border: 1px solid #e2e8f0; border-left: 4px solid #3b82f6;">'
                            f'<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">'
                            f'<span style="font-weight: 600; font-size: 0.95rem; color: #0f172a;">📦 {desc} <span style="font-size: 0.85rem; color: #64748b; font-weight: 400;">({qtd} un.)</span></span>'
                            f'<span style="background: #2563eb; color: white; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 600;">{status_atual}</span>'
                            f'</div>'
                            f'<div style="font-size: 0.825rem; color: #475569; margin-bottom: 6px;">'
                            f'<b>Solicitante:</b> {solic} &nbsp;|&nbsp; <b>PC:</b> {num_pedido} &nbsp;|&nbsp; <b>Forn:</b> {fornecedor} &nbsp;|&nbsp; <b>Prometido:</b> {dt_prometida}'
                            f'</div>'
                            f'<div>{botoes_docs}</div>'
                            f'</div>'
                        )

                        st.markdown(card_html, unsafe_allow_html=True)

                        with st.expander(f"🏁 Confirmar Recebimento / Finalizar Item #{item_id}"):
                            with st.form(f"form_fin_est_{item_id}"):
                                col_e1, col_e2 = st.columns(2)
                                with col_e1:
                                    f_dt_entregue = st.date_input("Data Real de Entrega:", value=datetime.date.today(), format="DD/MM/YYYY", key=f"dt_ent_{item_id}")
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
                                        "data_finalizacao": now_iso,
                                    }).eq("id", item_id).execute()

                                    supabase.table("desempenho_fornecedores").insert({
                                        "pedido_id": item_id,
                                        "fornecedor": fornecedor,
                                        "data_prometida": dt_prom_salvar,
                                        "data_entregue": f_dt_entregue.isoformat(),
                                        "qualidade_ok": f_qualidade,
                                        "prazo_pagamento_dias": prazo_pg,
                                        "lead_time_dias": lead_time,
                                        "otif_ok": otif,
                                    }).execute()
                                    
                                    tel = extrair_telefone(solic)
                                    msg_wa = f"✅ *Pedido Entregue!*\n\nSeu pedido de *{desc}* acabou de ser recebido e conferido pelo nosso Estoque."
                                    enviar_whatsapp(tel, msg_wa)

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
            REGRA PARA O USUARIO FABIANO:
            Apos receber as informacoes basicas do produto, pergunte uma unica vez:
            "Deseja adicionar alguma informacao tecnica opcional (ID Manutencao, Compatibilidade, Encapsulamento, Custo Estimado, Link Adicional ou Datasheet)?"

            - Se ele fornecer os dados, inclua-os na chamada da ferramenta.
            - Se ele disser "nao", "nao precisa", "pode registrar" ou mandar outro item, chame 'registrar_solicitacao_compra' imediatamente.
            """

        system_prompt = f"""
Você é o Assistente Integrado Vital, o sistema inteligente oficial da Vital C.
O operador identificado nesta sessão é: '{solicitante_atual}'.

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

Assim que possuir as informações básicas necessárias, invoque 'registrar_solicitacao_compra'.
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
                    base64_image = base64.b64encode(bytes_data).decode("utf-8")
                    user_payload.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"},
                    })

            user_payload.append({"type": "text", "text": user_text})
            st.session_state.messages.append({"role": "user", "content": user_payload})

            with st.spinner("Processando..."):
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=st.session_state.messages,
                    tools=tools,
                    tool_choice="auto",
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
                                solicitante=solicitante_atual,
                            )

                            if "sucesso" in resultado:
                                card_html_gerado = (
                                    f'<div style="background: #ffffff; border: 1px solid #e2e8f0; border-radius: 16px; padding: 20px; box-shadow: 0 4px 15px rgba(0,0,0,0.06); margin-bottom: 25px;">'
                                    f'<div style="background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%); padding: 25px 20px; border-radius: 12px; text-align: center; color: white;">'
                                    f'<p style="margin:0; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 1.5px; opacity: 0.9; font-weight: 600;">Valor Total Sugerido</p>'
                                    f'<h1 style="margin: 8px 0 0 0; font-size: 2.8rem; font-weight: 800; letter-spacing: -0.5px;">R$ {formar_real(resultado["preco_final"])}</h1>'
                                    f'</div>'
                                    f'<div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-top: 15px; text-align: center;">'
                                    f'<div style="background: #f8fafc; padding: 12px 6px; border-radius: 8px; border: 1px solid #f1f5f9;"><div style="font-size: 0.7rem; color: #64748b; font-weight: 700; margin-bottom: 4px;">DISTÂNCIA</div><div style="font-size: 0.95rem; font-weight: 700; color: #0f172a;">{resultado["km_total"]} km</div></div>'
                                    f'<div style="background: #f8fafc; padding: 12px 6px; border-radius: 8px; border: 1px solid #f1f5f9;"><div style="font-size: 0.7rem; color: #64748b; font-weight: 700; margin-bottom: 4px;">DIESEL</div><div style="font-size: 0.9rem; font-weight: 700; color: #0f172a; white-space: nowrap;">R$ {formar_real(resultado["custo_diesel"])}</div></div>'
                                    f'<div style="background: #f8fafc; padding: 12px 6px; border-radius: 8px; border: 1px solid #f1f5f9;"><div style="font-size: 0.7rem; color: #64748b; font-weight: 700; margin-bottom: 4px;">HOTEL/ALIM.</div><div style="font-size: 0.9rem; font-weight: 700; color: #0f172a; white-space: nowrap;">R$ {formar_real(resultado["custo_hospedagem_alim"])}</div></div>'
                                    f'<div style="background: #f8fafc; padding: 12px 6px; border-radius: 8px; border: 1px solid #f1f5f9;"><div style="font-size: 0.7rem; color: #64748b; font-weight: 700; margin-bottom: 4px;">FIXOS</div><div style="font-size: 0.9rem; font-weight: 700; color: #0f172a; white-space: nowrap;">R$ {formar_real(resultado["gastos_fixos"])}</div></div>'
                                    f'</div></div>'
                                )

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
                                datasheet=args.get("datasheet"),
                            )
                            if "sucesso" in resultado:
                                link_url = args.get("link", "#")
                                link_html = (
                                    f' — <a href="{link_url}" target="_blank" style="color: #0284c7; font-weight: 600; text-decoration: underline;">Ver Produto 🔗</a>'
                                    if link_url and link_url != "#"
                                    else ""
                                )

                                extra_info = ""
                                if args.get("id_manutencao"):
                                    extra_info = (
                                        f'<div><b>🛠️ ID Manutenção:</b> {args.get("id_manutencao")} | <b>🧩 Compatível:</b> {args.get("compativel", "N/A")}</div>'
                                        f'<div><b>📦 Encapsulamento:</b> {args.get("encapsulamento", "N/A")} | <b>💰 Custo Est.:</b> {args.get("custo_estimado", "N/A")}</div>'
                                    )

                                card_html_gerado = (
                                    f'<div style="background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 12px; padding: 18px; margin-bottom: 20px;">'
                                    f'<h4 style="margin: 0 0 12px 0; color: #166534; font-size: 1.1rem;">🛒 Compra Registrada com Sucesso!</h4>'
                                    f'<div style="display: flex; flex-direction: column; gap: 6px; font-size: 0.95rem; color: #14532d;">'
                                    f'<div><b>👤 Solicitante:</b> {solicitante_atual}</div>'
                                    f'<div><b>📦 Nome do item:</b> {args.get("descricao")}</div>'
                                    f'<div><b>🔢 Quantidade:</b> {args.get("quantidade")} un.</div>'
                                    f'<div><b>📋 Detalhe:</b> {args.get("referencia")}{link_html}</div>'
                                    f'<div><b>🎯 Motivo:</b> {args.get("motivo")}</div>'
                                    f'{extra_info}'
                                    f'</div></div>'
                                )

                        st.session_state.messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": json.dumps(resultado),
                        })

                    final_response = client.chat.completions.create(
                        model="gpt-4o-mini", messages=st.session_state.messages
                    )

                    texto_final = final_response.choices[0].message.content
                    conteudo_completo = f"{card_html_gerado}\n\n{texto_final}" if card_html_gerado else texto_final
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": conteudo_completo,
                    })

                else:
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": response_message.content,
                    })

            st.rerun()

# =============================================================================
# ABA 2: PAINEL DE GESTÃO DE COMPRAS (RESTRITO AO MODO ADM)
# =============================================================================
if aba_gestao:
    with aba_gestao:
        if supabase:
            st.markdown("#### 📊 Relatórios de Controle de Compras")
            col_mes, col_ano, col_btn_rel = st.columns([1, 1, 2])
            with col_mes:
                mes_filtro = st.selectbox("Mês:", ["Todos", "01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12"], index=datetime.datetime.now().month)
            with col_ano:
                ano_filtro = st.selectbox("Ano:", ["Todos", "2025", "2026", "2027", "2028"], index=2)

            with col_btn_rel:
                st.write("")
                btn_relatorio = st.button("📄 Gerar Relatório (PDF)", use_container_width=True)

            if btn_relatorio:
                with st.spinner("Filtrando período e gerando PDF..."):
                    try:
                        resp_compras_compradas = (
                            supabase.table("solicitacoes_compras")
                            .select("id")
                            .in_("status", ["Aguardando entrega", "Aguardando NF", "Finalizado"])
                            .execute()
                            .data
                        )
                        ids_comprados = set(str(item["id"]) for item in resp_compras_compradas) if resp_compras_compradas else set()

                        resp_cot_hist_raw = supabase.table("cotacoes").select("*").order("id", desc=True).execute().data

                        resp_cot_hist_detalhes = []
                        resp_cot_hist_ano_todo = []

                        if resp_cot_hist_raw:
                            for c in resp_cot_hist_raw:
                                dt_cotacao = c.get("data_cotacao", "")
                                p_id = c.get("pedido_id")
                                is_comprado = (p_id is None or str(p_id) in ids_comprados)

                                if ano_filtro == "Todos" or dt_cotacao.startswith(ano_filtro):
                                    if is_comprado:
                                        resp_cot_hist_ano_todo.append(c)

                                if ano_filtro != "Todos" and not dt_cotacao.startswith(ano_filtro):
                                    continue
                                if mes_filtro != "Todos" and f"-{mes_filtro}-" not in dt_cotacao:
                                    continue

                                if is_comprado:
                                    resp_cot_hist_detalhes.append(c)

                        pdf_bytes_controle = gerar_pdf_controle_compras(
                            resp_cot_hist_ano_todo,
                            mes_referencia=mes_filtro,
                            ano_referencia=ano_filtro,
                        )

                        rotulo_periodo = f"{mes_filtro}-{ano_filtro}" if mes_filtro != "Todos" else f"Geral_{ano_filtro}"
                        nome_planilha = f"Controle_Compras_{rotulo_periodo}.pdf"

                        link_planilha = salvar_nf_no_drive(
                            pdf_bytes_controle,
                            nome_planilha,
                            mime_type="application/pdf",
                            as_google_doc=False,
                            nome_subpasta=["Relatórios IA", "Fechamentos Mensais", rotulo_periodo],
                        )

                        if link_planilha:
                            st.success(f"✅ Relatório de {rotulo_periodo} gerado com sucesso!")
                            st.markdown(f"🔗 **[Abrir PDF da Planilha no Google Drive]({link_planilha})**")
                            st.download_button(
                                label="📥 Baixar Arquivo PDF no Computador",
                                data=pdf_bytes_controle,
                                file_name=nome_planilha,
                                mime="application/pdf",
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
                                datasheet=f_datasheet,
                            )
                            if res_cad.get("sucesso"):
                                st.success("✅ Pedido cadastrado com sucesso!")
                                st.rerun()

            st.divider()

        if not supabase:
            st.warning("⚠️ O Supabase não está conectado.")
        else:
            col_f1, col_f2 = st.columns(2)
            with col_f1:
                filtro_status = st.selectbox(
                    "Filtrar por Status:",
                    [
                        "Selecione para filtrar...",
                        "Pendente",
                        "Falta Cotação (Sem Cotação Anexada)",
                        "Aguardando entrega",
                        "Aguardando NF",
                        "Finalizado",
                        "Recusado",
                        "Todos (Com Histórico)",
                    ],
                    index=0,
                )
            with col_f2:
                filtro_filial = st.selectbox(
                    "Filtrar por Filial:",
                    ["Todas as Filiais", "Arco - São Paulo", "Ultrassom - São Paulo", "Outra"],
                    index=0,
                )

            if filtro_status == "Selecione para filtrar...":
                st.info("💡 Selecione um status acima para carregar as solicitações.")
            else:
                query = supabase.table("solicitacoes_compras").select("*")

                if filtro_status == "Falta Cotação (Sem Cotação Anexada)":
                    dados_compras = query.order("id", desc=True).execute().data
                    dados_compras = [
                        item for item in dados_compras 
                        if not item.get("link_cotacao") and item.get("status") not in ["Finalizado", "Recusado"]
                    ]
                elif filtro_status != "Todos (Com Histórico)":
                    query = query.eq("status", filtro_status)
                    dados_compras = query.order("id", desc=True).execute().data
                else:
                    dados_compras = query.order("id", desc=True).execute().data

                if filtro_filial != "Todas as Filiais" and dados_compras:
                    dados_compras = [
                        item for item in dados_compras
                        if normalizar_texto(filtro_filial) in normalizar_texto(item.get("solicitante", ""))
                    ]

                if not dados_compras:
                    st.info(f"Nenhuma solicitação encontrada para os filtros selecionados.")
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

                        links_list = []
                        if link and link != "#":
                            links_list.append(f'<a href="{link}" target="_blank" style="color: #2563eb; text-decoration: none; font-weight: 500;">🔗 Produto</a>')
                        if link_cotacao:
                            links_list.append(f'<a href="{link_cotacao}" target="_blank" style="color: #16a34a; text-decoration: none; font-weight: 500;">📊 Cotação Drive</a>')
                        if link_nf:
                            links_list.append(f'<a href="{link_nf}" target="_blank" style="color: #2563eb; text-decoration: none; font-weight: 500;">📄 NF Drive</a>')

                        docs_inline = " &nbsp;•&nbsp; ".join(links_list) if links_list else "<span style='color:#94a3b8;'>Sem anexos</span>"

                        detalhes_ped = []
                        if num_pedido: detalhes_ped.append(f"<b>PC:</b> {num_pedido}")
                        if fornecedor: detalhes_ped.append(f"<b>Forn:</b> {fornecedor}")
                        if data_prometida: detalhes_ped.append(f"<b>Entrega:</b> {data_prometida}")
                        detalhes_ped.append(f"<b>Tempo:</b> {tempo_str}")
                        linha_ped = " &nbsp;|&nbsp; ".join(detalhes_ped)

                        card_html = f"""
                        <div style="background: #ffffff; border: 1px solid #e2e8f0; border-left: 4px solid {cor_borda}; padding: 10px 14px; border-radius: 8px; margin-bottom: 6px;">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 2px;">
                                <span style="font-weight: 600; font-size: 0.925rem; color: #0f172a;">📦 {desc} <span style="font-weight: 400; color: #64748b; font-size: 0.825rem;">({qtd} un.)</span></span>
                                <span style="background: {cor_borda}; color: #ffffff; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 600;">{status_atual}</span>
                            </div>
                            <div style="font-size: 0.8rem; color: #475569; margin-bottom: 4px;">
                                <b>Solicitante:</b> {solic} &nbsp;|&nbsp; <b>Ref:</b> {ref} &nbsp;|&nbsp; <b>Motivo:</b> {motivo}
                            </div>
                            <div style="font-size: 0.775rem; color: #64748b; display: flex; justify-content: space-between; align-items: center; background: #f8fafc; padding: 4px 8px; border-radius: 4px;">
                                <div>{linha_ped}</div>
                                <div>{docs_inline}</div>
                            </div>
                        </div>
                        """

                        with st.container():
                            st.markdown(card_html, unsafe_allow_html=True)

                            if status_atual in ["Pendente", "Aguardando NF", "Aguardando entrega"]:
                                col_exp1, col_exp2 = st.columns(2)
                                with col_exp1:
                                    with st.expander("📊 Gerar / Gerenciar Cotação"):
                                        with st.form(f"form_gerar_cot_{item_id}"):
                                            default_link_1 = link if (link and link != "#") else ""
                                            default_nome_1 = extrair_nome_fornecedor(default_link_1)

                                            st.caption("🏢 Fornecedor 1")
                                            c_f1_1, c_f1_2, c_f1_3 = st.columns([2, 1, 1])
                                            forn1_nome = c_f1_1.text_input("Nome 1", value=default_nome_1, key=f"f1_n_{item_id}", placeholder="Nome 1", label_visibility="collapsed")
                                            forn1_preco_str = c_f1_2.text_input("Preço 1", key=f"f1_p_{item_id}", placeholder="Preço (15,90)", label_visibility="collapsed")
                                            forn1_frete_str = c_f1_3.text_input("Frete 1", key=f"f1_f_{item_id}", placeholder="Frete (0,00)", label_visibility="collapsed")
                                            forn1_link = st.text_input("Link 1", value=default_link_1, key=f"f1_l_{item_id}", placeholder="🔗 Link Cotação 1", label_visibility="collapsed")

                                            st.caption("🏢 Fornecedor 2")
                                            c_f2_1, c_f2_2, c_f2_3 = st.columns([2, 1, 1])
                                            forn2_nome = c_f2_1.text_input("Nome 2", key=f"f2_n_{item_id}", placeholder="Nome 2", label_visibility="collapsed")
                                            forn2_preco_str = c_f2_2.text_input("Preço 2", key=f"f2_p_{item_id}", placeholder="Preço (15,90)", label_visibility="collapsed")
                                            forn2_frete_str = c_f2_3.text_input("Frete 2", key=f"f2_f_{item_id}", placeholder="Frete (0,00)", label_visibility="collapsed")
                                            forn2_link = st.text_input("Link 2", key=f"f2_l_{item_id}", placeholder="🔗 Link Cotação 2", label_visibility="collapsed")

                                            st.caption("🏢 Fornecedor 3")
                                            c_f3_1, c_f3_2, c_f3_3 = st.columns([2, 1, 1])
                                            forn3_nome = c_f3_1.text_input("Nome 3", key=f"f3_n_{item_id}", placeholder="Nome 3", label_visibility="collapsed")
                                            forn3_preco_str = c_f3_2.text_input("Preço 3", key=f"f3_p_{item_id}", placeholder="Preço (15,90)", label_visibility="collapsed")
                                            forn3_frete_str = c_f3_3.text_input("Frete 3", key=f"f3_f_{item_id}", placeholder="Frete (0,00)", label_visibility="collapsed")
                                            forn3_link = st.text_input("Link 3", key=f"f3_l_{item_id}", placeholder="🔗 Link Cotação 3", label_visibility="collapsed")

                                            btn_gerar_cot = st.form_submit_button("⚙️ Salvar Cotação PDF", use_container_width=True)

                                            if btn_gerar_cot:
                                                forn1_preco = converter_valor_float(forn1_preco_str)
                                                forn1_frete = converter_valor_float(forn1_frete_str)
                                                forn2_preco = converter_valor_float(forn2_preco_str)
                                                forn2_frete = converter_valor_float(forn2_frete_str)
                                                forn3_preco = converter_valor_float(forn3_preco_str)
                                                forn3_frete = converter_valor_float(forn3_frete_str)

                                                if forn1_link.strip():
                                                    ext1 = extrair_nome_fornecedor(forn1_link)
                                                    if not forn1_nome.strip() or forn1_nome.strip() == "Nome 1":
                                                        forn1_nome = ext1 or forn1_nome

                                                if forn2_link.strip():
                                                    ext2 = extrair_nome_fornecedor(forn2_link)
                                                    if not forn2_nome.strip() or forn2_nome.strip() == "Nome 2":
                                                        forn2_nome = ext2 or forn2_nome

                                                if forn3_link.strip():
                                                    ext3 = extrair_nome_fornecedor(forn3_link)
                                                    if not forn3_nome.strip() or forn3_nome.strip() == "Nome 3":
                                                        forn3_nome = ext3 or forn3_nome

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
                                                    st.error("⚠️ Cadastre 3 fornecedores válidos!")
                                                else:
                                                    if link_cotacao:
                                                        deletar_arquivo_do_drive(link_cotacao)

                                                    if supabase:
                                                        try:
                                                            supabase.table("cotacoes").delete().eq("pedido_id", int(item_id)).execute()
                                                        except Exception:
                                                            pass

                                                    opcoes_ordenadas = sorted(opcoes, key=lambda x: x["total"])
                                                    vencedor = opcoes_ordenadas[0]

                                                    tot1_val = opcoes_ordenadas[0]["total"]
                                                    tot2_val = opcoes_ordenadas[1]["total"]
                                                    tot3_val = opcoes_ordenadas[2]["total"]

                                                    media_orcam = (tot1_val + tot2_val + tot3_val) / 3.0
                                                    preco_alvo = media_orcam * 0.90
                                                    valor_comprado = vencedor["total"]
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
                                                                "fornecedor_c": f"{opcoes_ordenadas[2 if len(opcoes_ordenadas)>2 else 1]['nome']} (R$ {formar_real(tot3_val)})",
                                                                "valor_c": float(tot3_val),
                                                                "media_orcam": float(media_orcam),
                                                                "preco_alvo": float(preco_alvo),
                                                                "valor_comprado": float(valor_comprado),
                                                                "economia_real": float(economia_real),
                                                                "status_meta": status_meta_txt,
                                                                "solicitante": solic,
                                                                "pedido_id": int(item_id),
                                                            }).execute()
                                                        except Exception:
                                                            pass

                                                    pdf_ind_bytes = gerar_pdf_cotacao_individual(desc, qtd, ref, solic, motivo, opcoes_ordenadas, vencedor)
                                                    desc_limpa = "".join(c for c in desc[:15] if c.isalnum() or c in " -_").strip()
                                                    nome_arq_ind = f"Cotacao_Sistema_{item_id}_{desc_limpa}.pdf"
                                                    mes_ano = datetime.datetime.now().strftime("%m-%Y")
                                                    dia_cot = datetime.datetime.now().strftime("%d-%m-%Y")

                                                    link_cot_gerada = salvar_nf_no_drive(
                                                        pdf_ind_bytes,
                                                        nome_arq_ind,
                                                        mime_type="application/pdf",
                                                        as_google_doc=False,
                                                        nome_subpasta=["Relatórios IA", "Cotações", mes_ano, dia_cot],
                                                    )

                                                    if link_cot_gerada:
                                                        supabase.table("solicitacoes_compras").update({
                                                            "link_cotacao": link_cot_gerada,
                                                            "fornecedor_vencedor": vencedor["nome"],
                                                        }).eq("id", item_id).execute()
                                                        st.success(f"✅ Cotação salva! Vencedor: {vencedor['nome']}")
                                                        st.rerun()

                                        if link_cotacao:
                                            if st.button("🗑️ Excluir Cotação do Drive/Sistema", key=f"btn_excluir_cot_{item_id}", use_container_width=True):
                                                deletar_arquivo_do_drive(link_cotacao)
                                                if supabase:
                                                    try:
                                                        supabase.table("cotacoes").delete().eq("pedido_id", int(item_id)).execute()
                                                        supabase.table("solicitacoes_compras").update({
                                                            "link_cotacao": None,
                                                            "fornecedor_vencedor": None
                                                        }).eq("id", item_id).execute()
                                                    except Exception:
                                                        pass
                                                st.success("✅ Cotação excluída!")
                                                st.rerun()

                                with col_exp2:
                                    with st.expander("📝 Dados da Compra & Anexo NF"):
                                        with st.form(f"form_upload_nf_{item_id}"):
                                            num_pedido_input = st.text_input("Nº Pedido:", value=num_pedido or "", key=f"input_ped_{item_id}")
                                            
                                            default_fornec = fornecedor or extrair_nome_fornecedor(link)
                                            f_fornec_input = st.text_input("Fornecedor Vencedor:", value=default_fornec, key=f"input_forn_{item_id}")
                                            
                                            val_dt_prom = datetime.date.today()
                                            if data_prometida:
                                                try: val_dt_prom = datetime.datetime.strptime(str(data_prometida), "%Y-%m-%d").date()
                                                except Exception: pass
                                            
                                            f_dt_prometida_input = st.date_input("Prometido para:", value=val_dt_prom, format="DD/MM/YYYY", key=f"input_dtp_{item_id}")
                                            
                                            uploaded_cot_ext = st.file_uploader("PDF Cotação / Orçamento Externa:", type=["pdf"], key=f"file_cot_ext_{item_id}")
                                            uploaded_nf = st.file_uploader("PDF da NF:", type=["pdf"], key=f"file_nf_{item_id}")
                                            
                                            validar_nf_ia = st.checkbox("🤖 Validar valores da NF automaticamente com IA", value=True, key=f"chk_val_{item_id}")
                                            
                                            btn_save_nf_adm = st.form_submit_button("💾 Atualizar Pedido / Anexos", use_container_width=True)

                                            if btn_save_nf_adm:
                                                if not num_pedido_input.strip() or not f_fornec_input.strip():
                                                    st.error("⚠️ Preencha Nº do Pedido e Fornecedor!")
                                                else:
                                                    pode_salvar = True
                                                    bytes_nf = uploaded_nf.getvalue() if uploaded_nf else None

                                                    if uploaded_nf and validar_nf_ia:
                                                        with st.spinner("🤖 Analisando a Nota Fiscal com Inteligência Artificial..."):
                                                            try:
                                                                import PyPDF2
                                                                pdf_reader = PyPDF2.PdfReader(io.BytesIO(bytes_nf))
                                                                texto_nf = "".join([page.extract_text() for page in pdf_reader.pages if page.extract_text()])
                                                                
                                                                valor_aprovado = 0.0
                                                                if supabase:
                                                                    try:
                                                                        cot_data = supabase.table("cotacoes").select("valor_comprado").eq("pedido_id", int(item_id)).execute()
                                                                        if cot_data.data:
                                                                            valor_aprovado = float(cot_data.data[0].get("valor_comprado", 0))
                                                                    except Exception:
                                                                        pass

                                                                prompt = f"""
                                                                Extraia o Valor Total exato desta Nota Fiscal.
                                                                Retorne APENAS um JSON válido no formato exato:
                                                                {{"valor_total_nf": 1500.50, "numero_nf": "12345"}}
                                                                Se não encontrar, retorne 0.0 para o valor.
                                                                Texto da NF: {texto_nf[:6000]}
                                                                """
                                                                
                                                                res = client.chat.completions.create(
                                                                    model="gpt-4o-mini",
                                                                    response_format={"type": "json_object"},
                                                                    messages=[{"role": "user", "content": prompt}],
                                                                    temperature=0.0
                                                                )
                                                                
                                                                dados_extraidos = json.loads(res.choices[0].message.content)
                                                                valor_nf_lido = float(dados_extraidos.get("valor_total_nf", 0.0))
                                                                
                                                                if valor_aprovado > 0 and abs(valor_nf_lido - valor_aprovado) > 1.5:
                                                                    st.error(f"🚨 **Divergência Financeira Bloqueada!**\n\nO valor lido na Nota Fiscal (**R$ {formar_real(valor_nf_lido)}**) é diferente do valor aprovado na cotação (**R$ {formar_real(valor_aprovado)}**).\n\n*Se for uma exceção aprovada, desmarque a caixa 'Validar valores da NF' e salve novamente.*")
                                                                    pode_salvar = False
                                                                else:
                                                                    st.success(f"✅ NF validada pela IA com sucesso! Valor confere: R$ {formar_real(valor_nf_lido)}")
                                                                    
                                                            except ImportError:
                                                                st.warning("⚠️ Instale o pacote PyPDF2 rodando 'pip install PyPDF2' no terminal para habilitar a IA nas NFs.")
                                                            except Exception as e:
                                                                st.warning(f"⚠️ Erro ao analisar PDF: {e}")

                                                    if pode_salvar:
                                                        update_payload = {
                                                            "numero_pedido": num_pedido_input.strip(),
                                                            "fornecedor_vencedor": f_fornec_input.strip(),
                                                            "data_prometida": f_dt_prometida_input.isoformat(),
                                                        }
                                                        
                                                        # Lógica Inteligente de Status para não estragar pedidos que já avançaram
                                                        if status_atual == "Pendente":
                                                            update_payload["status"] = "Aguardando entrega"
                                                        elif status_atual == "Aguardando NF" and uploaded_nf:
                                                            update_payload["status"] = "Aguardando entrega"
                                                        
                                                        desc_limpa = "".join(c for c in desc[:15] if c.isalnum() or c in " -_").strip()
                                                        mes_ano = datetime.datetime.now().strftime("%m-%Y")
                                                        dia_cot = datetime.datetime.now().strftime("%d-%m-%Y")

                                                        if uploaded_cot_ext:
                                                            if link_cotacao:
                                                                deletar_arquivo_do_drive(link_cotacao)
                                                            bytes_cot = uploaded_cot_ext.read()
                                                            nome_cot = f"Cotacao_Externa_{num_pedido_input.strip()}_{item_id}_{desc_limpa}.pdf"
                                                            link_cot_drive = salvar_nf_no_drive(bytes_cot, nome_cot, nome_subpasta=["Relatórios IA", "Cotações", mes_ano, dia_cot])
                                                            if link_cot_drive:
                                                                update_payload["link_cotacao"] = link_cot_drive

                                                        if uploaded_nf:
                                                            nome_arquivo = f"NF_Pedido_{num_pedido_input.strip()}_{item_id}_{desc_limpa}.pdf"
                                                            link_drive = salvar_nf_no_drive(bytes_nf, nome_arquivo, nome_subpasta=["Relatórios IA", "Notas Fiscais", mes_ano])
                                                            if link_drive:
                                                                update_payload["link_nf"] = link_drive

                                                        supabase.table("solicitacoes_compras").update(update_payload).eq("id", item_id).execute()
                                                        st.success("✅ Compra e anexos salvos!")
                                                        st.rerun()

                            col1, col2, col3 = st.columns(3)
                            
                            if status_atual == "Pendente":
                                with col1:
                                    if st.button("🚚 Ag. Entrega", key=f"entreg_{item_id}", use_container_width=True):
                                        payload_up = {"status": "Aguardando entrega"}
                                        if not fornecedor:
                                            forn_auto = extrair_nome_fornecedor(link)
                                            if forn_auto:
                                                payload_up["fornecedor_vencedor"] = forn_auto
                                        supabase.table("solicitacoes_compras").update(payload_up).eq("id", item_id).execute()
                                        
                                        tel = extrair_telefone(solic)
                                        msg_wa = f"🚚 *Atualização de Pedido*\n\nSeu pedido de *{desc}* foi aprovado pelo setor de Compras e agora está *Aguardando Entrega*."
                                        enviar_whatsapp(tel, msg_wa)
                                        
                                        st.rerun()
                                with col2:
                                    if st.button("📄 Ag. NF", key=f"ped_nf_{item_id}", use_container_width=True):
                                        supabase.table("solicitacoes_compras").update({"status": "Aguardando NF"}).eq("id", item_id).execute()
                                        
                                        tel = extrair_telefone(solic)
                                        msg_wa = f"📄 *Atualização de Pedido*\n\nSeu pedido de *{desc}* está com status *Aguardando Nota Fiscal*."
                                        enviar_whatsapp(tel, msg_wa)
                                        
                                        st.rerun()
                                with col3:
                                    if st.button("❌ Recusar", key=f"rec_{item_id}", use_container_width=True):
                                        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
                                        supabase.table("solicitacoes_compras").update({"status": "Recusado", "data_finalizacao": now_iso}).eq("id", item_id).execute()
                                        
                                        tel = extrair_telefone(solic)
                                        msg_wa = f"❌ *Pedido Recusado*\n\nInfelizmente, seu pedido de *{desc}* foi recusado pela administração."
                                        enviar_whatsapp(tel, msg_wa)
                                        
                                        st.rerun()
                            else:
                                with col1:
                                    if st.button("⏳ Voltar p/ Pendente", key=f"pend_{item_id}", use_container_width=True):
                                        supabase.table("solicitacoes_compras").update({"status": "Pendente"}).eq("id", item_id).execute()
                                        st.rerun()
                                with col2:
                                    novo_status = "Aguardando NF" if status_atual == "Aguardando entrega" else "Aguardando entrega"
                                    rotulo = "📄 Ag. NF" if status_atual == "Aguardando entrega" else "🚚 Ag. Entrega"
                                    if st.button(rotulo, key=f"alt_st_{item_id}", use_container_width=True):
                                        supabase.table("solicitacoes_compras").update({"status": novo_status}).eq("id", item_id).execute()
                                        st.rerun()
                                with col3:
                                    if st.button("❌ Recusar", key=f"rec_{item_id}", use_container_width=True):
                                        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
                                        supabase.table("solicitacoes_compras").update({"status": "Recusado", "data_finalizacao": now_iso}).eq("id", item_id).execute()
                                        st.rerun()

                        st.markdown("<div style='margin-bottom: 10px;'></div>", unsafe_allow_html=True)

# =============================================================================
# ABA 3: FERRAMENTAS E MÓDULOS EXTRAS (RESTRITO AO MODO ADM)
# =============================================================================
if aba_ferramentas:
    with aba_ferramentas:
        st.subheader("🧩 Módulos e Ferramentas Extras")
        st.info("Central de extensões e ferramentas adicionais do sistema.")

        if not os.path.exists("modulos"):
            os.makedirs("modulos")

        arquivos_modulos = glob.glob("modulos/*.py")

        if not arquivos_modulos:
            st.warning("Nenhum módulo extra encontrado na pasta 'modulos'.")
        else:
            for arquivo_py in arquivos_modulos:
                try:
                    nome_modulo = os.path.basename(arquivo_py)[:-3]
                    spec = importlib.util.spec_from_file_location(nome_modulo, arquivo_py)
                    modulo = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(modulo)

                    if hasattr(modulo, "iniciar"):
                        modulo.iniciar()
                except Exception as e:
                    st.error(f"Erro ao carregar o módulo {arquivo_py}: {e}")