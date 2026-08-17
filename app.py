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

# -----------------------------------------------------------------------------
# 1. CARREGAMENTO DAS VARIÁVEIS DE AMBIENTE (.env LOCAL E st.secrets NUVEM)
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
GOOGLE_DRIVE_FOLDER_ID = get_secret("GOOGLE_DRIVE_FOLDER_ID", "")

LOGO_PATH = "logo.png"

# -----------------------------------------------------------------------------
# 2. CONFIGURAÇÃO DA PÁGINA E CLIENTES DE API
# -----------------------------------------------------------------------------
pagina_icone = LOGO_PATH if os.path.exists(LOGO_PATH) else "🤖"

st.set_page_config(
    page_title="Assistente Integrado Vital", 
    page_icon=pagina_icone, 
    layout="centered"
)

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
# 3. FUNÇÕES DE SUPORTE E CÁLCULO DE TEMPO
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

# -----------------------------------------------------------------------------
# 4. FUNÇÕES DE UPLOAD PARA O GOOGLE DRIVE
# -----------------------------------------------------------------------------
def obter_ou_criar_pasta_do_mes(service, parent_folder_id):
    hoje = datetime.datetime.now()
    nome_pasta_mes = hoje.strftime("%m-%Y") 

    query = f"'{parent_folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and name='{nome_pasta_mes}' and trashed=false"
    
    resultados = service.files().list(
        q=query, 
        spaces='drive',
        supportsAllDrives=True, 
        includeItemsFromAllDrives=True,
        fields='files(id, name)'
    ).execute()
    
    pastas = resultados.get('files', [])
    
    if pastas:
        return pastas[0]['id']
    else:
        file_metadata = {
            'name': nome_pasta_mes,
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [parent_folder_id]
        }
        pasta_criada = service.files().create(
            body=file_metadata,
            fields='id',
            supportsAllDrives=True
        ).execute()
        
        return pasta_criada.get('id')


def salvar_nf_no_drive(file_bytes, nome_arquivo, mime_type='application/pdf'):
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
        pasta_destino_id = obter_ou_criar_pasta_do_mes(service, GOOGLE_DRIVE_FOLDER_ID)

        file_metadata = {'name': nome_arquivo, 'parents': [pasta_destino_id]}
        media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype=mime_type, resumable=True)
        
        file = service.files().create(
            body=file_metadata, 
            media_body=media, 
            fields='id, webViewLink',
            supportsAllDrives=True
        ).execute()
        
        return file.get('webViewLink')
    except Exception as e:
        st.error(f"❌ Erro ao salvar no Google Drive: {e}")
        return None

# -----------------------------------------------------------------------------
# 5. CONTROLE DE SESSÃO DO USUÁRIO E MODO ADM
# -----------------------------------------------------------------------------
if "usuario_identificado" not in st.session_state:
    st.session_state.usuario_identificado = False

if "is_adm" not in st.session_state:
    st.session_state.is_adm = False

if not st.session_state.usuario_identificado:
    st.title("🤖 Assistente Integrado Vital")
    st.markdown("### 👤 Identificação do Solicitante")
    st.info("Por favor, informe seus dados para iniciar ou acesse diretamente como Administrador.")

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
                st.session_state.usuario_identificado = True
                st.rerun()

    st.divider()

    with st.expander("🔑 Acesso Direto para Administradores (Painel ADM)", expanded=True):
        with st.form("form_adm_direto"):
            senha_adm_direta = st.text_input("Senha do Administrador:", type="password")
            btn_adm_direto = st.form_submit_button("🔓 Entrar Direto no Painel ADM")
            
            if btn_adm_direto:
                if senha_adm_direta == ADM_PASSWORD:
                    st.session_state.is_adm = True
                    st.session_state.solicitante_str = "Administrador (ADM)"
                    st.session_state.usuario_identificado = True
                    st.success("Acesso ADM Liberado!")
                    st.rerun()
                else:
                    st.error("Senha incorreta!")

    st.stop()

# -----------------------------------------------------------------------------
# 6. BARRA LATERAL
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

with st.sidebar:
    st.success(f"👤 **Logado como:**\n\n{st.session_state.solicitante_str}")
    if st.button("🚪 Trocar Usuário / Sair"):
        st.session_state.clear()
        st.rerun()

    st.divider()

    st.header("🔑 Acesso ADM")
    if not st.session_state.is_adm:
        senha_input = st.text_input("Senha do Administrador:", type="password", key="input_adm_pass")
        if st.button("🔓 Acessar Painel ADM"):
            if senha_input == ADM_PASSWORD:
                st.session_state.is_adm = True
                st.success("Acesso ADM Liberado!")
                st.rerun()
            else:
                st.error("Senha incorreta!")
    else:
        st.info("🔓 **Modo Administrador Ativo**")
        if st.button("🔒 Sair do Modo ADM"):
            st.session_state.is_adm = False
            st.rerun()

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

custo_fixo_diaria = (ipva + seguro + manut_anual) / dias_uteis

# -----------------------------------------------------------------------------
# 7. FUNÇÃO DE ENVIO DE E-MAIL
# -----------------------------------------------------------------------------
def enviar_email_notificacao(descricao, link, referencia, quantidade, motivo, solicitante,
                             id_manutencao=None, compativel=None, encapsulamento=None, 
                             custo_estimado=None, link_adicional=None, datasheet=None):
    if not EMAIL_REMETENTE or not EMAIL_SENHA_APP or not EMAIL_DESTINATARIO:
        print("⚠️ Dados de e-mail não preenchidos.")
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
    <p><small>Este e-mail foi gerado automaticamente pelo Assistente Integrado Vital.</small></p>
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

# -----------------------------------------------------------------------------
# 8. FUNÇÕES DE SUPORTE E CÁLCULO
# -----------------------------------------------------------------------------
@st.cache_data(show_spinner="Consultando mapa...")
def obter_localizacao(cidade):
    geolocator = Photon(user_agent="vital_logistica_v18", timeout=10)
    try:
        return geolocator.geocode(cidade)
    except Exception:
        return None

def formar_real(valor):
    return "{:,.2f}".format(valor).replace(",", "X").replace(".", ",").replace("X", ".")

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

# -----------------------------------------------------------------------------
# 9. FERRAMENTAS DA IA (TOOLS)
# -----------------------------------------------------------------------------
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
                    "id_manutencao": {"type": "string", "description": "ID Manutenção (solicitado se o usuário for o Fabiano)"},
                    "compativel": {"type": "string", "description": "Compatibilidade com equipamento (solicitado se o usuário for o Fabiano)"},
                    "encapsulamento": {"type": "string", "description": "Encapsulamento do componente (solicitado se o usuário for o Fabiano)"},
                    "custo_estimado": {"type": "string", "description": "Custo estimado R$ (solicitado se o usuário for o Fabiano)"},
                    "link_adicional": {"type": "string", "description": "Link adicional (solicitado se o usuário for o Fabiano)"},
                    "datasheet": {"type": "string", "description": "Link ou PDF do Datasheet (solicitado se o usuário for o Fabiano)"}
                },
                "required": ["descricao", "link", "referencia", "quantidade", "motivo"]
            }
        }
    }
]

# -----------------------------------------------------------------------------
# 10. INTERFACE PRINCIPAL E ABAS
# -----------------------------------------------------------------------------
st.title("🤖 Assistente Integrado Vital")

if st.session_state.is_adm:
    aba_chat, aba_gestao = st.tabs(["💬 Assistente IA", "📋 Painel de Compras (ADM)"])
else:
    aba_chat = st.container()
    aba_gestao = None

# =============================================================================
# ABA 1: CHAT DO ASSISTENTE
# =============================================================================
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
Você é o Assistente Integrado Vital, o sistema inteligente oficial da Vital Logística.
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

    if prompt := st.chat_input("Digite sua mensagem, peça um frete ou anexe uma foto...", accept_file=True):
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
                            card_html_gerado = f"""<div style="background: #ffffff; border: 1px solid #e2e8f0; border-radius: 16px; padding: 20px; box-shadow: 0 4px 15px rgba(0,0,0,0.06); margin-bottom: 25px;">
<div style="background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%); padding: 25px 20px; border-radius: 12px; text-align: center; color: white;">
<p style="margin:0; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 1.5px; opacity: 0.9; font-weight: 600;">Valor Total Sugerido</p>
<h1 style="margin: 8px 0 0 0; font-size: 2.8rem; font-weight: 800; letter-spacing: -0.5px;">R$ {formar_real(resultado['preco_final'])}</h1>
</div>
<div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-top: 15px; text-align: center;">
<div style="background: #f8fafc; padding: 12px 6px; border-radius: 8px; border: 1px solid #f1f5f9;">
<div style="font-size: 0.7rem; color: #64748b; font-weight: 700; margin-bottom: 4px;">DISTÂNCIA</div>
<div style="font-size: 0.95rem; font-weight: 700; color: #0f172a;">{resultado['km_total']} km</div>
</div>
<div style="background: #f8fafc; padding: 12px 6px; border-radius: 8px; border: 1px solid #f1f5f9;">
<div style="font-size: 0.7rem; color: #64748b; font-weight: 700; margin-bottom: 4px;">DIESEL</div>
<div style="font-size: 0.9rem; font-weight: 700; color: #0f172a; white-space: nowrap;">R$ {formar_real(resultado['custo_diesel'])}</div>
</div>
<div style="background: #f8fafc; padding: 12px 6px; border-radius: 8px; border: 1px solid #f1f5f9;">
<div style="font-size: 0.7rem; color: #64748b; font-weight: 700; margin-bottom: 4px;">HOTEL/ALIM.</div>
<div style="font-size: 0.9rem; font-weight: 700; color: #0f172a; white-space: nowrap;">R$ {formar_real(resultado['custo_hospedagem_alim'])}</div>
</div>
<div style="background: #f8fafc; padding: 12px 6px; border-radius: 8px; border: 1px solid #f1f5f9;">
<div style="font-size: 0.7rem; color: #64748b; font-weight: 700; margin-bottom: 4px;">FIXOS</div>
<div style="font-size: 0.9rem; font-weight: 700; color: #0f172a; white-space: nowrap;">R$ {formar_real(resultado['gastos_fixos'])}</div>
</div>
</div>
</div>"""

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
                                extra_info += f"<div><b>🛠️ ID Manutenção:</b> {args.get('id_manutencao')} | <b>🧩 Compatível:</b> {args.get('compativel', 'N/A')}</div>"
                                extra_info += f"<div><b>📦 Encapsulamento:</b> {args.get('encapsulamento', 'N/A')} | <b>💰 Custo Est.:</b> {args.get('custo_estimado', 'N/A')}</div>"

                            card_html_gerado = f"""<div style="background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 12px; padding: 18px; margin-bottom: 20px;">
<h4 style="margin: 0 0 12px 0; color: #166534; font-size: 1.1rem;">🛒 Compra Registrada com Sucesso!</h4>
<div style="display: flex; flex-direction: column; gap: 6px; font-size: 0.95rem; color: #14532d;">
<div><b>👤 Solicitante:</b> {solicitante_atual}</div>
<div><b>📦 Nome do item:</b> {args.get('descricao')}</div>
<div><b>🔢 Quantidade:</b> {args.get('quantidade')} un.</div>
<div><b>📋 Detalhe:</b> {args.get('referencia')}{link_html}</div>
<div><b>🎯 Motivo:</b> {args.get('motivo')}</div>
{extra_info}
</div>
</div>"""

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
        
        # --- EXPORTAR E LIMPAR SUPABASE (AMBAS AS TABELAS) ---
        if supabase:
            with st.expander("🧹 Limpeza e Exportação das Tabelas (Compras e Cotações)"):
                st.info("Esta ação irá exportar os registros das tabelas **solicitacoes_compras** (pedidos finalizados com NF) e **cotacoes** em planilhas CSV enviadas diretamente para a pasta do mês no Google Drive. Após o envio bem-sucedido, os itens correspondentes serão removidos do Supabase.")
                senha_export = st.text_input("Confirme a Senha ADM:", type="password", key="senha_exp")
                
                if st.button("🚀 Iniciar Exportação e Limpeza Completa", key="btn_exp"):
                    if senha_export == ADM_PASSWORD:
                        with st.spinner("Exportando planilhas e organizando no Google Drive..."):
                            try:
                                data_atual = datetime.datetime.now().strftime("%d-%m-%Y_%H-%M")
                                links_gerados = []

                                # 1. EXPORTAR E LIMPAR SOLICITAÇÕES DE COMPRAS
                                resp_compras = supabase.table("solicitacoes_compras").select("*").eq("status", "Finalizado").execute()
                                dados_compras = [d for d in resp_compras.data if d.get("link_nf")]

                                if dados_compras:
                                    output_compras = io.StringIO()
                                    output_compras.write('\ufeff')
                                    chaves_c = set()
                                    for d in dados_compras: chaves_c.update(d.keys())
                                    writer_c = csv.DictWriter(output_compras, fieldnames=list(chaves_c), delimiter=';')
                                    writer_c.writeheader()
                                    writer_c.writerows(dados_compras)

                                    link_compras = salvar_nf_no_drive(
                                        output_compras.getvalue().encode('utf-8'),
                                        f"Relatorio_Solicitacoes_Compras_{data_atual}.csv",
                                        mime_type='text/csv'
                                    )

                                    if link_compras:
                                        for item in dados_compras:
                                            supabase.table("solicitacoes_compras").delete().eq("id", item["id"]).execute()
                                        links_gerados.append(("Solicitações de Compras", link_compras, len(dados_compras)))

                                # 2. EXPORTAR E LIMPAR COTAÇÕES
                                resp_cotacoes = supabase.table("cotacoes").select("*").execute()
                                dados_cotacoes = resp_cotacoes.data

                                if dados_cotacoes:
                                    output_cot = io.StringIO()
                                    output_cot.write('\ufeff')
                                    chaves_cot = set()
                                    for d in dados_cotacoes: chaves_cot.update(d.keys())
                                    writer_cot = csv.DictWriter(output_cot, fieldnames=list(chaves_cot), delimiter=';')
                                    writer_cot.writeheader()
                                    writer_cot.writerows(dados_cotacoes)

                                    link_cotacoes = salvar_nf_no_drive(
                                        output_cot.getvalue().encode('utf-8'),
                                        f"Relatorio_Cotacoes_Frete_{data_atual}.csv",
                                        mime_type='text/csv'
                                    )

                                    if link_cotacoes:
                                        for item in dados_cotacoes:
                                            supabase.table("cotacoes").delete().eq("id", item["id"]).execute()
                                        links_gerados.append(("Cotações de Frete", link_cotacoes, len(dados_cotacoes)))

                                # RESULTADOS
                                if not links_gerados:
                                    st.warning("Nenhum dado pendente de exportação encontrado nas tabelas.")
                                else:
                                    st.success("✅ Exportação e limpeza concluídas com sucesso!")
                                    for titulo, link_d, qtd in links_gerados:
                                        st.markdown(f"📊 **{titulo}:** {qtd} registro(s) exportado(s) — [Abrir no Drive]({link_d})")

                            except Exception as e:
                                st.error(f"❌ Ocorreu um erro durante a exportação/limpeza: {e}")
                    else:
                        st.error("❌ Senha incorreta!")
        st.divider()
        # ----------------------------------
        
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
                    created_at = item.get("created_at")
                    data_finalizacao = item.get("data_finalizacao")

                    id_manut = item.get("id_manutencao")
                    compat = item.get("compativel")
                    encaps = item.get("encapsulamento")
                    custo_est = item.get("custo_estimado")
                    num_pedido = item.get("numero_pedido")

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
                    if num_pedido:
                        campos_extra_adm += f'<p style="margin: 4px 0 0 0; font-size: 0.85rem; color: #475569;"><b>🏷️ Nº Pedido de Compra:</b> {num_pedido}</p>'
                    if id_manut or compat or encaps or custo_est:
                        campos_extra_adm += f'<p style="margin: 4px 0 0 0; font-size: 0.85rem; color: #475569;"><b>🛠️ ID Manut:</b> {id_manut or "N/A"} | <b>🧩 Compatível:</b> {compat or "N/A"} | <b>📦 Encaps:</b> {encaps or "N/A"} | <b>💰 Custo Est:</b> {custo_est or "N/A"}</p>'

                    card_html = f"""<div style="border-left: 5px solid {cor_borda}; background: #f8fafc; padding: 15px; border-radius: 8px; margin-bottom: 12px; border: 1px solid #e2e8f0; border-left-width: 5px;">
<div style="display: flex; justify-content: space-between; align-items: center;">
<h4 style="margin: 0; color: #0f172a;">📦 {desc}</h4>
<span style="background: {cor_borda}; color: white; padding: 3px 10px; border-radius: 12px; font-size: 0.8rem; font-weight: bold;">{status_atual}</span>
</div>
<p style="margin: 8px 0 4px 0; font-size: 0.9rem;"><b>👤 Solicitante:</b> {solic}</p>
<p style="margin: 0 0 4px 0; font-size: 0.9rem;"><b>🔢 Quantidade:</b> {qtd} un. | <b>📋 Ref:</b> {ref}</p>
<p style="margin: 0 0 4px 0; font-size: 0.9rem;"><b>🎯 Motivo:</b> {motivo}</p>
{campos_extra_adm}
<p style="margin: 4px 0 4px 0; font-size: 0.9rem; color: #1e293b;"><b>{rotulo_tempo}</b> <span style="background: #e2e8f0; padding: 2px 8px; border-radius: 6px; font-weight: 600;">{tempo_str}</span></p>
<p style="margin: 0; font-size: 0.9rem;">🔗 <a href="{link}" target="_blank">Ver Link do Produto</a></p>
</div>"""

                    with st.container():
                        st.markdown(card_html, unsafe_allow_html=True)

                        if link_nf:
                            st.success("📄 **Nota Fiscal Anexada!**")
                            st.markdown(f"🔗 [Clique aqui para abrir a NF no Google Drive]({link_nf})")
                        elif status_atual == "Aguardando NF":
                            st.info("📥 **Este pedido está aguardando o envio da Nota Fiscal:**")
                            
                            num_pedido_input = st.text_input("Número do Pedido de Compra (Obrigatório):", key=f"input_ped_{item_id}")
                            uploaded_nf = st.file_uploader("Anexar PDF da NF:", type=["pdf"], key=f"file_nf_{item_id}")
                            
                            if st.button("💾 Salvar NF no Drive e Marcar como Aguardando entrega", key=f"btn_save_nf_{item_id}"):
                                if not num_pedido_input.strip():
                                    st.error("⚠️ Por favor, preencha o Número do Pedido de Compra antes de salvar!")
                                elif not uploaded_nf:
                                    st.error("⚠️ Por favor, anexe o PDF da Nota Fiscal!")
                                else:
                                    with st.spinner("Enviando arquivo e organizando pasta do mês no Google Drive..."):
                                        bytes_data = uploaded_nf.read()
                                        
                                        desc_limpa = "".join(c for c in desc[:15] if c.isalnum() or c in " -_").strip()
                                        nome_arquivo = f"NF_Pedido_{num_pedido_input.strip()}_{item_id}_{desc_limpa}.pdf"
                                        
                                        link_drive = salvar_nf_no_drive(bytes_data, nome_arquivo)
                                        if link_drive:
                                            supabase.table("solicitacoes_compras").update({
                                                "link_nf": link_drive,
                                                "status": "Aguardando entrega",
                                                "numero_pedido": num_pedido_input.strip()
                                            }).eq("id", item_id).execute()
                                            st.success("Nota Fiscal salva na pasta do mês no Drive com sucesso!")
                                            st.rerun()

                        col1, col2, col3, col4 = st.columns(4)
                        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

                        with col1:
                            if st.button("🚚 Aguardando entrega", key=f"entreg_{item_id}"):
                                supabase.table("solicitacoes_compras").update({"status": "Aguardando entrega"}).eq("id", item_id).execute()
                                st.rerun()
                        with col2:
                            if st.button("📄 Aguardando NF", key=f"ped_nf_{item_id}"):
                                supabase.table("solicitacoes_compras").update({"status": "Aguardando NF"}).eq("id", item_id).execute()
                                st.rerun()
                        with col3:
                            if st.button("🏁 Finalizar", key=f"fin_{item_id}"):
                                supabase.table("solicitacoes_compras").update({
                                    "status": "Finalizado",
                                    "data_finalizacao": now_iso
                                }).eq("id", item_id).execute()
                                st.rerun()
                        with col4:
                            if st.button("❌ Recusar", key=f"rec_{item_id}"):
                                supabase.table("solicitacoes_compras").update({
                                    "status": "Recusado",
                                    "data_finalizacao": now_iso
                                }).eq("id", item_id).execute()
                                st.rerun()
                        
                        st.divider()