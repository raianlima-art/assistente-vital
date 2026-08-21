import base64
import csv
import datetime
import io
import json
import os
import requests
import streamlit as st
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload
from supabase import create_client


def get_secret(key, default=None):
    try:
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return os.getenv(key, default)


def obter_supabase():
    url = get_secret("SUPABASE_URL")
    key = get_secret("SUPABASE_KEY")
    if url and key and "seu-projeto" not in url:
        try:
            return create_client(url, key)
        except Exception:
            return None
    return None


def obter_servico_drive():
    folder_id = get_secret("GOOGLE_DRIVE_FOLDER_ID", "")
    if not folder_id:
        return None, None

    SCOPES = ["https://www.googleapis.com/auth/drive"]
    creds = None
    if os.path.exists("credentials.json"):
        creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
    else:
        creds_raw = get_secret("GOOGLE_DRIVE_CREDENTIALS")
        if not creds_raw:
            return None, None
        creds_json = None
        if isinstance(creds_raw, str):
            try:
                creds_json = json.loads(base64.b64decode(creds_raw.strip()).decode("utf-8"))
            except Exception:
                try:
                    creds_json = json.loads(creds_raw)
                except Exception:
                    pass
        elif hasattr(creds_raw, "to_dict"):
            creds_json = creds_raw.to_dict()
        elif isinstance(creds_raw, dict):
            creds_json = dict(creds_raw)

        if creds_json and "private_key" in creds_json:
            creds_json["private_key"] = str(creds_json["private_key"]).strip('"\'').replace("\\n", "\n")
            creds = Credentials.from_service_account_info(creds_json, scopes=SCOPES)

    if not creds:
        return None, None

    service = build("drive", "v3", credentials=creds)
    return service, folder_id


def salvar_no_drive(file_bytes, nome_arquivo, mime_type="text/csv", nome_subpasta=None):
    service, root_folder_id = obter_servico_drive()
    if not service or not root_folder_id:
        return None

    def obter_ou_criar_subpasta(parent_id, nome):
        q = f"'{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and name='{nome}' and trashed=false"
        res = service.files().list(q=q, spaces="drive", supportsAllDrives=True, includeItemsFromAllDrives=True, fields="files(id, name)").execute().get("files", [])
        if res:
            return res[0]["id"]
        meta = {"name": nome, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]}
        return service.files().create(body=meta, fields="id", supportsAllDrives=True).execute().get("id")

    atual_id = root_folder_id
    if nome_subpasta:
        for folder in nome_subpasta:
            atual_id = obter_ou_criar_subpasta(atual_id, folder)

    file_metadata = {"name": nome_arquivo, "parents": [atual_id]}
    media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype=mime_type, resumable=True)
    file_obj = service.files().create(body=file_metadata, media_body=media, fields="id, webViewLink", supportsAllDrives=True).execute()
    return file_obj.get("webViewLink")


def obter_todas_tabelas_supabase(supabase_url, supabase_key):
    try:
        schema_url = f"{supabase_url}/rest/v1/"
        headers = {"apikey": supabase_key, "Authorization": f"Bearer {supabase_key}"}
        resp = requests.get(schema_url, headers=headers)
        if resp.status_code == 200:
            swagger_data = resp.json()
            definitions = swagger_data.get("definitions", {})
            return list(definitions.keys())
    except Exception:
        pass
    return [
        "bonificacao_fechamento", "bonificacao_os", "bonificacao_pesos", 
        "cotacoes", "desempenho_fornecedores", "fechamento_mensal", 
        "solicitacoes_compras", "tecnicos"
    ]


def buscar_arquivos_backup_no_drive(service, parent_id):
    arquivos_encontrados = []
    
    query_files = f"'{parent_id}' in parents and mimeType='application/json' and trashed=false"
    res_files = service.files().list(q=query_files, spaces="drive", supportsAllDrives=True, includeItemsFromAllDrives=True, fields="files(id, name, createdTime)").execute()
    arquivos_encontrados.extend(res_files.get("files", []))
    
    query_folders = f"'{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
    res_folders = service.files().list(q=query_folders, spaces="drive", supportsAllDrives=True, includeItemsFromAllDrives=True, fields="files(id, name)").execute()
    
    for pasta in res_folders.get("files", []):
        arquivos_encontrados.extend(buscar_arquivos_backup_no_drive(service, pasta["id"]))
        
    return arquivos_encontrados


def iniciar():
    with st.expander("🧹 Limpeza, Backups & Restauração", expanded=False):
        tab_bkp, tab_rest, tab_limpeza = st.tabs([
            "💾 Backup Completo (Drive)", 
            "📥 Restaurar do Drive", 
            "🧹 Expurgo Geral de Tabelas"
        ])

        # --- ABA 1: BACKUP JSON COMPLETO DAS TABELAS ---
        with tab_bkp:
            st.caption("Gera uma cópia de segurança em formato JSON de **TODAS** as tabelas do Supabase e salva no Drive por Ano/Mês.")
            if st.button("🚀 Gerar e Enviar Backup Completo Agora", use_container_width=True):
                try:
                    supabase_url = get_secret("SUPABASE_URL")
                    supabase_key = get_secret("SUPABASE_KEY")
                    supabase = obter_supabase()
                    
                    if not supabase:
                        st.error("❌ Erro ao conectar ao Supabase.")
                    else:
                        with st.spinner("Mapeando tabelas e extraindo dados..."):
                            tabelas = obter_todas_tabelas_supabase(supabase_url, supabase_key)
                            dados_backup = {}
                            tabelas_salvas = []

                            for tab in tabelas:
                                try:
                                    res = supabase.table(tab).select("*").execute()
                                    if res.data is not None:
                                        dados_backup[tab] = res.data
                                        tabelas_salvas.append(tab)
                                except Exception:
                                    continue

                            json_str = json.dumps(dados_backup, indent=4, ensure_ascii=False, default=str)
                            bytes_data = json_str.encode("utf-8")

                            agora = datetime.datetime.now()
                            data_hoje = agora.strftime("%Y-%m-%d_%H-%M-%S")
                            nome_arquivo = f"backup_supabase_COMPLETO_{data_hoje}.json"

                            meses_pt = {
                                "01": "01 - Janeiro", "02": "02 - Fevereiro", "03": "03 - Março",
                                "04": "04 - Abril", "05": "05 - Maio", "06": "06 - Junho",
                                "07": "07 - Julho", "08": "08 - Agosto", "09": "09 - Setembro",
                                "10": "10 - Outubro", "11": "11 - Novembro", "12": "12 - Dezembro"
                            }
                            caminho_pasta = ["Backups_Supabase", agora.strftime("%Y"), meses_pt[agora.strftime("%m")]]

                            link = salvar_no_drive(bytes_data, nome_arquivo, mime_type="application/json", nome_subpasta=caminho_pasta)

                            if link:
                                st.success(f"✅ Backup de {len(tabelas_salvas)} tabela(s) concluído com sucesso!")
                                st.info(f"📁 **Caminho:** `Backups_Supabase/{agora.strftime('%Y')}/{meses_pt[agora.strftime('%m')]}/`")
                                st.markdown(f"🔗 [Acessar Arquivo no Google Drive]({link})")
                            else:
                                st.error("❌ Falha ao enviar para o Google Drive.")
                except Exception as e:
                    st.error(f"Erro ao realizar backup: {e}")

        # --- ABA 2: RESTAURAR DO DRIVE PARA O SUPABASE ---
        with tab_rest:
            st.caption("Busque e selecione backups em JSON armazenados no Google Drive para restaurar dados no Supabase.")
            
            if st.button("🔎 Buscar Arquivos no Google Drive", use_container_width=True):
                try:
                    service, root_folder_id = obter_servico_drive()
                    if service:
                        with st.spinner("Varrendo diretórios do Drive..."):
                            def obter_id_subpasta(parent_id, nome):
                                q = f"'{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and name='{nome}' and trashed=false"
                                res = service.files().list(q=q, spaces="drive", supportsAllDrives=True, includeItemsFromAllDrives=True, fields="files(id, name)").execute().get("files", [])
                                return res[0]["id"] if res else None

                            pasta_bkp_id = obter_id_subpasta(root_folder_id, "Backups_Supabase") or root_folder_id
                            arquivos = buscar_arquivos_backup_no_drive(service, pasta_bkp_id)
                            
                            if arquivos:
                                st.session_state["lista_backups_restaurar"] = arquivos
                                st.toast(f"Encontrados {len(arquivos)} backups no Drive.", icon="📂")
                            else:
                                st.warning("Nenhum backup .json foi localizado.")
                except Exception as e:
                    st.error(f"Erro ao acessar o Drive: {e}")

            if "lista_backups_restaurar" in st.session_state and st.session_state["lista_backups_restaurar"]:
                lista = st.session_state["lista_backups_restaurar"]
                mapa = {arq["name"]: arq["id"] for arq in lista}
                escolha = st.selectbox("Selecione o arquivo de backup:", list(mapa.keys()))
                
                if st.button("📥 Restaurar Backup Selecionado no Supabase", type="primary", use_container_width=True):
                    try:
                        service, _ = obter_servico_drive()
                        supabase = obter_supabase()
                        file_id = mapa[escolha]

                        with st.spinner("Baixando do Google Drive..."):
                            request = service.files().get_media(fileId=file_id)
                            fh = io.BytesIO()
                            downloader = MediaIoBaseDownload(fh, request)
                            done = False
                            while not done:
                                _, done = downloader.next_chunk()
                            fh.seek(0)
                            conteudo = json.load(fh)

                        with st.spinner("Restaurando registros nas tabelas do Supabase..."):
                            restauradas = 0
                            for tab, reg in conteudo.items():
                                if reg and isinstance(reg, list):
                                    supabase.table(tab).upsert(reg).execute()
                                    restauradas += 1

                        st.success(f"🎉 Restauração concluída com sucesso! {restauradas} tabela(s) foram sincronizadas.")
                    except Exception as e:
                        st.error(f"Erro ao restaurar: {e}")

        # --- ABA 3: EXPURGO COMPLETO DE TODAS AS TABELAS ---
        with tab_limpeza:
            st.warning("⚠️ **Atenção:** Esta ação gera relatórios em CSV de **todas as tabelas do banco**, envia para o Drive e deleta os registros do Supabase.")
            
            adm_pass = get_secret("ADM_PASSWORD", "admin123")
            senha_export = st.text_input("Confirme a Senha ADM para autorizar:", type="password", key="senha_exp_mod")

            if st.button("🚀 Exportar Todos os Dados para CSV e Limpar Banco", key="btn_exp_mod"):
                if senha_export == adm_pass:
                    supabase_url = get_secret("SUPABASE_URL")
                    supabase_key = get_secret("SUPABASE_KEY")
                    supabase = obter_supabase()
                    
                    if not supabase:
                        st.error("❌ Erro ao conectar ao Supabase.")
                        return

                    with st.spinner("Varrendo todas as tabelas e processando expurgo..."):
                        try:
                            data_atual = datetime.datetime.now().strftime("%d-%m-%Y_%H-%M")
                            data_dia = datetime.datetime.now().strftime("%d-%m-%Y")
                            caminho_backup = ["Relatórios IA", "Expurgo_Geral", data_dia]
                            
                            tabelas_alvo = obter_todas_tabelas_supabase(supabase_url, supabase_key)
                            links_gerados = []

                            for tabela in tabelas_alvo:
                                try:
                                    resp = supabase.table(tabela).select("*").execute()
                                    dados = resp.data
                                    
                                    if dados:
                                        output = io.StringIO()
                                        output.write("\ufeff")
                                        chaves = set()
                                        for d in dados:
                                            chaves.update(d.keys())
                                            
                                        writer = csv.DictWriter(output, fieldnames=list(chaves), delimiter=";")
                                        writer.writeheader()
                                        writer.writerows(dados)
                                        
                                        nome_csv = f"Expurgo_{tabela}_{data_atual}.csv"
                                        link_csv = salvar_no_drive(output.getvalue().encode("utf-8"), nome_csv, mime_type="text/csv", nome_subpasta=caminho_backup)
                                        
                                        if link_csv:
                                            # Deleta os registros da tabela limpa
                                            for item in dados:
                                                if "id" in item:
                                                    supabase.table(tabela).delete().eq("id", item["id"]).execute()
                                            links_gerados.append((tabela, link_csv, len(dados)))
                                except Exception as e_tab:
                                    st.warning(f"Não foi possível processar a tabela '{tabela}': {e_tab}")

                            if not links_gerados:
                                st.info("Nenhum dado encontrado nas tabelas para expurgo.")
                            else:
                                st.success("✅ Expurgo geral concluído com sucesso!")
                                for tab_nome, link_d, qtd in links_gerados:
                                    st.markdown(f"📊 **Tabela `{tab_nome}`:** {qtd} registro(s) expurgados — [Abrir CSV no Drive]({link_d})")
                        except Exception as e:
                            st.error(f"❌ Erro ao expurgar dados: {e}")
                else:
                    st.error("❌ Senha incorreta!")