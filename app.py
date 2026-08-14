import base64
import json
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import streamlit as st
from dotenv import load_dotenv
from geopy.distance import geodesic
from geopy.geocoders import Photon
from openai import OpenAI
from supabase import Client, create_client

# -----------------------------------------------------------------------------
# 1. CARREGAMENTO DAS VARIÁVEIS DE AMBIENTE (.env)
# -----------------------------------------------------------------------------
load_dotenv()

API_KEY_OPENAI = os.getenv("OPENAI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

EMAIL_REMETENTE = os.getenv("EMAIL_REMETENTE")
EMAIL_SENHA_APP = os.getenv("EMAIL_SENHA_APP")
EMAIL_DESTINATARIO = os.getenv("EMAIL_DESTINATARIO")

ADM_PASSWORD = os.getenv("ADM_PASSWORD", "admin123")

LOGO_PATH = "logo.png"

# -----------------------------------------------------------------------------
# 2. CONFIGURAÇÃO DA PÁGINA
# -----------------------------------------------------------------------------
pagina_icone = LOGO_PATH if os.path.exists(LOGO_PATH) else "🤖"

st.set_page_config(
    page_title="Assistente Integrado Vital", 
    page_icon=pagina_icone, 
    layout="centered"
)

if not API_KEY_OPENAI:
    st.error("❌ A chave 'OPENAI_API_KEY' não foi encontrada no arquivo .env!")
    st.stop()

client = OpenAI(api_key=API_KEY_OPENAI)

supabase: Client = None
if SUPABASE_URL and SUPABASE_KEY and "seu-projeto" not in SUPABASE_URL:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    except Exception as e:
        st.sidebar.warning(f"⚠️ Supabase offline: {e}")

# -----------------------------------------------------------------------------
# 3. CONTROLE DE SESSÃO DO USUÁRIO E MODO ADM
# -----------------------------------------------------------------------------
if "usuario_identificado" not in st.session_state:
    st.session_state.usuario_identificado = False

if "is_adm" not in st.session_state:
    st.session_state.is_adm = False

# Tela de Login do Operador
if not st.session_state.usuario_identificado:
    st.title("🤖 Assistente Integrado Vital")
    st.markdown("### 👤 Identificação do Solicitante")
    st.info("Por favor, informe seus dados antes de iniciar o atendimento.")

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
    st.stop()

# -----------------------------------------------------------------------------
# 4. BARRA LATERAL
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

    # --- VALIDAÇÃO ADMINISTRATIVA ---
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
# 5. FUNÇÃO DE ENVIO DE E-MAIL
# -----------------------------------------------------------------------------
def enviar_email_notificacao(descricao, link, referencia, quantidade, motivo, solicitante):
    if not EMAIL_REMETENTE or not EMAIL_SENHA_APP or not EMAIL_DESTINATARIO:
        print("⚠️ Dados de e-mail não preenchidos no .env")
        return False

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
    </ul>

    <hr>
    <p><small>Este e-mail foi gerado automaticamente pelo Assistente Integrado Vital.</small></p>
    """

    msg.attach(MIMEText(corpo, 'html'))

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(EMAIL_REMETENTE, EMAIL_SENHA_APP.replace(" ", ""))
            server.sendmail(EMAIL_REMETENTE, EMAIL_DESTINATARIO, msg.as_string())
        print("📧 E-mail de notificação enviado com sucesso!")
        return True
    except Exception as e:
        print(f"❌ Erro ao enviar e-mail: {e}")
        return False

# -----------------------------------------------------------------------------
# 6. FUNÇÕES DE SUPORTE E CÁLCULO
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

def registrar_solicitacao_compra(descricao, link, referencia, quantidade, motivo, solicitante):
    if supabase:
        try:
            supabase.table("solicitacoes_compras").insert({
                "item_descricao": descricao,
                "link_produto": link,
                "referencia": referencia,
                "quantidade": int(quantidade),
                "motivo": motivo,
                "solicitante": solicitante,
                "status": "Pendente"
            }).execute()
        except Exception:
            desc_completa = f"{descricao} | Ref: {referencia} | Qtd: {quantidade} | Motivo: {motivo} | Solicitante: {solicitante}"
            supabase.table("solicitacoes_compras").insert({
                "item_descricao": desc_completa,
                "link_produto": link,
                "status": "Pendente"
            }).execute()
            
    enviar_email_notificacao(descricao, link, referencia, quantidade, motivo, solicitante)
    return {"sucesso": True, "mensagem": f"Item registrado e e-mail enviado!"}

# -----------------------------------------------------------------------------
# 7. FERRAMENTAS DA IA (TOOLS)
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
            "description": "Registra um pedido de compra APÓS obter do usuário: descrição do item, link, referência, quantidade e motivo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "descricao": {"type": "string", "description": "Nome resumido e claro do produto"},
                    "link": {"type": "string", "description": "URL/Link de compra do produto"},
                    "referencia": {"type": "string", "description": "Modelo, código ou especificação do produto"},
                    "quantidade": {"type": "integer", "description": "Quantidade de itens"},
                    "motivo": {"type": "string", "description": "Motivo/justificativa da compra"}
                },
                "required": ["descricao", "link", "referencia", "quantidade", "motivo"]
            }
        }
    }
]

# -----------------------------------------------------------------------------
# 8. INTERFACE PRINCIPAL E ABAS
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

    system_prompt = f"""
Você é o Assistente Integrado Vital, o sistema inteligente oficial da Vital Logística.
O operador identificado nesta sessão é: '{solicitante_atual}'.

Suas atribuições principais são:

1. COTAR FRETES: Solicite origem, destino, tipo de trajeto ("Apenas Ida" ou "Ida e Volta"), dias por trecho e se é viagem curta. Com todos os 5 dados, chame 'calcular_frete_ia'.

2. SOLICITAR COMPRAS: Quando o usuário enviar uma foto, link ou pedir para comprar um item:
   - Você JÁ SABE quem é o solicitante ({solicitante_atual}), portanto NUNCA PERGUNTE O NOME DO USUÁRIO no chat!
   - Solicite apenas as informações do produto que faltarem:
     1. Link de compra/referência
     2. Código de Referência / Modelo
     3. Quantidade
     4. Motivo da compra
   - Assim que possuir as 4 informações do produto, invoque 'registrar_solicitacao_compra'.

Seja cortês, profissional e objetivo.
"""

    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "system", "content": system_prompt}]

    # RENDERIZA HISTÓRICO (APENAS MENSAGENS DE USUÁRIO E ASSISTENTE - OMITE FERRAMENTAS BRUTAS)
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

    # INPUT DE MENSAGEM
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
                            solicitante=solicitante_atual
                        )
                        if "sucesso" in resultado:
                            link_url = args.get('link', '#')
                            link_html = f' — <a href="{link_url}" target="_blank" style="color: #0284c7; font-weight: 600; text-decoration: underline;">Ver Produto 🔗</a>' if link_url and link_url != '#' else ''
                            card_html_gerado = f"""<div style="background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 12px; padding: 18px; margin-bottom: 20px;">
<h4 style="margin: 0 0 12px 0; color: #166534; font-size: 1.1rem;">🛒 Compra Registrada com Sucesso!</h4>
<div style="display: flex; flex-direction: column; gap: 6px; font-size: 0.95rem; color: #14532d;">
<div><b>👤 Solicitante:</b> {solicitante_atual}</div>
<div><b>📦 Nome do item:</b> {args.get('descricao')}</div>
<div><b>🔢 Quantidade:</b> {args.get('quantidade')} un.</div>
<div><b>📋 Detalhe:</b> {args.get('referencia')}{link_html}</div>
<div><b>🎯 Motivo:</b> {args.get('motivo')}</div>
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
                
                # Se um card HTML foi gerado, anexa ao topo da resposta
                conteudo_completo = f"{card_html_gerado}\n\n{texto_final}" if card_html_gerado else texto_final
                st.session_state.messages.append({"role": "assistant", "content": conteudo_completo})

            else:
                st.session_state.messages.append({"role": "assistant", "content": response_message.content})

        # Recarrega a página para desenhar tudo ordenado com o chat_input no final da tela
        st.rerun()

# =============================================================================
# ABA 2: PAINEL DE GESTÃO DE COMPRAS (RESTRITO AO MODO ADM)
# =============================================================================
if aba_gestao:
    with aba_gestao:
        st.subheader("📋 Gestão e Aprovação de Pedidos (Acesso ADM)")
        
        if not supabase:
            st.warning("⚠️ O Supabase não está conectado. Configure as variáveis no .env para utilizar esta aba.")
        else:
            filtro_status = st.selectbox(
                "Filtrar por Status:", 
                ["Ativos (Pendentes e Comprados)", "Pendente", "Comprado", "Aprovado", "Recusado", "Finalizado", "Todos (Com Histórico)"],
                index=0
            )

            query = supabase.table("solicitacoes_compras").select("*")
            
            if filtro_status == "Ativos (Pendentes e Comprados)":
                query = query.neq("status", "Finalizado")
            elif filtro_status != "Todos (Com Histórico)":
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

                    if status_atual == "Pendente":
                        cor_borda = "#f59e0b"
                    elif status_atual in ["Aprovado", "Comprado"]:
                        cor_borda = "#10b981"
                    elif status_atual == "Finalizado":
                        cor_borda = "#64748b"
                    else:
                        cor_borda = "#ef4444"

                    with st.container():
                        st.markdown(f"""
                        <div style="border-left: 5px solid {cor_borda}; background: #f8fafc; padding: 15px; border-radius: 8px; margin-bottom: 12px; border: 1px solid #e2e8f0; border-left-width: 5px;">
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <h4 style="margin: 0; color: #0f172a;">📦 {desc}</h4>
                                <span style="background: {cor_borda}; color: white; padding: 3px 10px; border-radius: 12px; font-size: 0.8rem; font-weight: bold;">{status_atual}</span>
                            </div>
                            <p style="margin: 8px 0 4px 0; font-size: 0.9rem;"><b>👤 Solicitante:</b> {solic}</p>
                            <p style="margin: 0 0 4px 0; font-size: 0.9rem;"><b>🔢 Quantidade:</b> {qtd} un. | <b>📋 Ref:</b> {ref}</p>
                            <p style="margin: 0 0 4px 0; font-size: 0.9rem;"><b>🎯 Motivo:</b> {motivo}</p>
                            <p style="margin: 0; font-size: 0.9rem;">🔗 <a href="{link}" target="_blank">Ver Link do Produto</a></p>
                        </div>
                        """, unsafe_allow_html=True)

                        col1, col2, col3, col4 = st.columns(4)
                        with col1:
                            if st.button("✅ Aprovar", key=f"aprov_{item_id}"):
                                supabase.table("solicitacoes_compras").update({"status": "Aprovado"}).eq("id", item_id).execute()
                                st.success(f"Item #{item_id} Aprovado!")
                                st.rerun()
                        with col2:
                            if st.button("🛒 Comprado", key=f"comp_{item_id}"):
                                supabase.table("solicitacoes_compras").update({"status": "Comprado"}).eq("id", item_id).execute()
                                st.success(f"Item #{item_id} marcado como Comprado!")
                                st.rerun()
                        with col3:
                            if st.button("🏁 Finalizar", key=f"fin_{item_id}"):
                                supabase.table("solicitacoes_compras").update({"status": "Finalizado"}).eq("id", item_id).execute()
                                st.info(f"Item #{item_id} Finalizado e arquivado!")
                                st.rerun()
                        with col4:
                            if st.button("❌ Recusar", key=f"rec_{item_id}"):
                                supabase.table("solicitacoes_compras").update({"status": "Recusado"}).eq("id", item_id).execute()
                                st.warning(f"Item #{item_id} Recusado!")
                                st.rerun()
                        
                        st.divider()
