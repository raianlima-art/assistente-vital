import streamlit as st
import os
import json
import base64
from datetime import datetime
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

def obter_servico_drive_leitura():
    """Função interna do módulo para autenticar no Google Drive."""
    SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
    creds = None
    
    # Tenta ler do arquivo local primeiro
    if os.path.exists("credentials.json"):
        creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
    else:
        # Se não tiver arquivo, busca nos secrets do Streamlit
        try:
            creds_raw = st.secrets.get("GOOGLE_DRIVE_CREDENTIALS")
            if creds_raw:
                creds_json = None
                if isinstance(creds_raw, str):
                    try:
                        creds_json = json.loads(base64.b64decode(creds_raw.strip()).decode("utf-8"))
                    except:
                        try:
                            creds_json = json.loads(creds_raw)
                        except: pass
                elif hasattr(creds_raw, "to_dict"):
                    creds_json = creds_raw.to_dict()
                elif isinstance(creds_raw, dict):
                    creds_json = dict(creds_raw)

                if creds_json and "private_key" in creds_json:
                    creds_json["private_key"] = str(creds_json["private_key"]).strip('"\'').replace("\\n", "\n")
                    creds = Credentials.from_service_account_info(creds_json, scopes=SCOPES)
        except:
            pass

    if creds:
        return build("drive", "v3", credentials=creds)
    return None

def iniciar():
    """
    Função principal que o app.py chama automaticamente.
    Cria a interface (sanfona) de busca no painel de módulos.
    """
    with st.expander("🔍 Buscador Rápido de Notas Fiscais e Cotações no Drive", expanded=False):
        st.markdown(
            "Pesquise documentos no Google Drive diretamente por aqui. "
            "Você pode buscar pelo **Número do Pedido**, **Fornecedor** ou **Descrição do item**."
        )
        
        col_input, col_btn = st.columns([3, 1])
        with col_input:
            termo_busca = st.text_input("Digite o termo (ex: 1045, Kalunga, Monitor):", key="input_busca_drive")
        with col_btn:
            st.write("") # Espaçamento para alinhar com o input
            st.write("") 
            btn_buscar = st.button("🔎 Pesquisar", use_container_width=True)
            
        if btn_buscar:
            if not termo_busca.strip():
                st.warning("⚠️ Digite algum termo para realizar a busca.")
            else:
                with st.spinner("Conectando ao Google Drive e pesquisando..."):
                    service = obter_servico_drive_leitura()
                    if not service:
                        st.error("❌ Erro de autenticação. Não foi possível conectar ao Google Drive.")
                        return
                    
                    try:
                        # Monta a query de busca do Google Drive (procura arquivos que contenham o termo no nome)
                        # Filtramos apenas PDFs e arquivos que não estão na lixeira
                        query = f"name contains '{termo_busca}' and mimeType='application/pdf' and trashed=false"
                        
                        resultados = service.files().list(
                            q=query,
                            spaces="drive",
                            supportsAllDrives=True,
                            includeItemsFromAllDrives=True,
                            fields="files(id, name, webViewLink, createdTime)",
                            pageSize=20, # Traz até os 20 resultados mais recentes
                            orderBy="createdTime desc"
                        ).execute()
                        
                        arquivos = resultados.get("files", [])
                        
                        if not arquivos:
                            st.info(f"Nenhum arquivo PDF encontrado no Drive contendo o termo: **{termo_busca}**")
                        else:
                            st.success(f"✅ Foram encontrados {len(arquivos)} arquivo(s):")
                            
                            for arq in arquivos:
                                data_formatada = "Data não disponível"
                                if "createdTime" in arq:
                                    try:
                                        # Converte o padrão do Google Drive (2026-08-19T14:30:00.000Z) para PT-BR
                                        dt_obj = datetime.strptime(arq["createdTime"], "%Y-%m-%dT%H:%M:%S.%fZ")
                                        data_formatada = dt_obj.strftime("%d/%m/%Y às %H:%M")
                                    except:
                                        pass
                                        
                                card_html = f"""
                                <div style='padding:12px 18px; border:1px solid #e2e8f0; border-radius:10px; margin-bottom:10px; display:flex; justify-content:space-between; align-items:center; background-color:#f8fafc; box-shadow: 0 1px 2px rgba(0,0,0,0.02);'>
                                    <div>
                                        <div style='font-weight:700; color:#0f172a; font-size:0.95rem; margin-bottom:2px;'>📄 {arq['name']}</div>
                                        <div style='font-size:0.8rem; color:#64748b;'>☁️ Salvo no Drive em: {data_formatada}</div>
                                    </div>
                                    <a href='{arq['webViewLink']}' target='_blank' style='background:#eff6ff; color:#1d4ed8; padding:8px 14px; border-radius:8px; text-decoration:none; font-size:0.85rem; font-weight:700; border: 1px solid #bfdbfe; transition: 0.2s;'>Abrir Arquivo ↗</a>
                                </div>
                                """
                                st.markdown(card_html, unsafe_allow_html=True)
                                
                    except Exception as e:
                        st.error(f"❌ Ocorreu um erro durante a pesquisa: {e}")