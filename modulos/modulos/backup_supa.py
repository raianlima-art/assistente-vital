import streamlit as st
import pandas as pd
import json
import datetime
import io
import os
from supabase import create_client
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from googleapiclient.http import MediaIoBaseUpload

def obter_servico_drive():
    try:
        drive_folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
        if not drive_folder_id:
            return None, None
            
        SCOPES = ["https://www.googleapis.com/auth/drive"]
        if os.path.exists("credentials.json"):
            creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
            service = build("drive", "v3", credentials=creds)
            return service, drive_folder_id
        return None, None
    except Exception as e:
        st.error(f"Erro de autenticação no Drive: {e}")
        return None, None

def obter_ou_criar_subpasta(service, parent_id, nome_pasta):
    query = f"'{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and name='{nome_pasta}' and trashed=false"
    res = service.files().list(q=query, spaces="drive", supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
    pastas = res.get("files", [])
    if pastas:
        return pastas[0]["id"]
    else:
        meta = {"name": nome_pasta, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]}
        pasta = service.files().create(body=meta, fields="id", supportsAllDrives=True).execute()
        return pasta.get("id")

def render_backup_supa():
    with st.expander("💾 Backup do Banco Supabase para o Google Drive"):
        st.caption("Exporta todas as tabelas principais do Supabase em formato JSON e salva no Drive.")
        
        if st.button("🚀 Gerar e Enviar Backup Agora", use_container_width=True):
            try:
                # 1. Conexão Supabase
                supabase_url = os.getenv("SUPABASE_URL")
                supabase_key = os.getenv("SUPABASE_KEY")
                if not supabase_url or not supabase_key:
                    st.error("❌ Credenciais do Supabase não encontradas.")
                    return

                supabase = create_client(supabase_url, supabase_key)
                
                # 2. Conexão Google Drive
                service, root_folder_id = obter_servico_drive()
                if not service:
                    st.error("❌ Não foi possível conectar ao Google Drive (verifique credentials.json).")
                    return

                with st.spinner("Extraindo dados do Supabase..."):
                    # Tabelas que serão salvas no backup
                    tabelas = ["solicitacoes_compras", "fechamento_mensal"]
                    dados_backup = {}

                    for tab in tabelas:
                        try:
                            res = supabase.table(tab).select("*").execute()
                            dados_backup[tab] = res.data
                        except Exception:
                            dados_backup[tab] = []

                    # Prepara o arquivo JSON
                    json_str = json.dumps(dados_backup, indent=4, ensure_ascii=False, default=str)
                    bytes_data = json_str.encode("utf-8")

                    # Nome do arquivo com timestamp
                    data_hoje = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                    nome_arquivo = f"backup_supabase_{data_hoje}.json"

                with st.spinner("Enviando para o Google Drive..."):
                    # Cria subpasta 'Backups_Supabase' no Drive
                    pasta_backup_id = obter_ou_criar_subpasta(service, root_folder_id, "Backups_Supabase")

                    file_metadata = {
                        "name": nome_arquivo,
                        "parents": [pasta_backup_id]
                    }
                    media = MediaIoBaseUpload(io.BytesIO(bytes_data), mimetype="application/json", resumable=True)
                    file_uploaded = service.files().create(
                        body=file_metadata, media_body=media, fields="id, webViewLink", supportsAllDrives=True
                    ).execute()

                    link_drive = file_uploaded.get("webViewLink")

                st.success(f"✅ Backup concluído com sucesso!")
                st.markdown(f"🔗 [Acessar Arquivo no Google Drive]({link_drive})")

            except Exception as e:
                st.error(f"Erro ao realizar backup: {e}")