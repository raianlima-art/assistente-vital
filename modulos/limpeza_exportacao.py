import base64
import csv
import datetime
import io
import json
import os
import streamlit as st
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
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


def salvar_no_drive(file_bytes, nome_arquivo, mime_type="text/csv", nome_subpasta=None):
    folder_id = get_secret("GOOGLE_DRIVE_FOLDER_ID", "")
    if not folder_id:
        return None

    SCOPES = ["https://www.googleapis.com/auth/drive"]
    creds = None
    if os.path.exists("credentials.json"):
        creds = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
    else:
        creds_raw = get_secret("GOOGLE_DRIVE_CREDENTIALS")
        if not creds_raw:
            return None
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
        return None

    service = build("drive", "v3", credentials=creds)

    def obter_ou_criar_subpasta(parent_id, nome):
        q = f"'{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and name='{nome}' and trashed=false"
        res = service.files().list(q=q, spaces="drive", supportsAllDrives=True, includeItemsFromAllDrives=True, fields="files(id, name)").execute().get("files", [])
        if res:
            return res[0]["id"]
        meta = {"name": nome, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]}
        return service.files().create(body=meta, fields="id", supportsAllDrives=True).execute().get("id")

    atual_id = folder_id
    if nome_subpasta:
        for folder in nome_subpasta:
            atual_id = obter_ou_criar_subpasta(atual_id, folder)

    file_metadata = {"name": nome_arquivo, "parents": [atual_id]}
    media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype=mime_type, resumable=True)
    file_obj = service.files().create(body=file_metadata, media_body=media, fields="id, webViewLink", supportsAllDrives=True).execute()
    return file_obj.get("webViewLink")


def iniciar():
    with st.expander("🧹 Limpeza & Exportação", expanded=False):
        st.info("Exporta compras finalizadas, desempenho de fornecedores e cotações para o Google Drive e limpa do Supabase.")
        adm_pass = get_secret("ADM_PASSWORD", "admin123")
        senha_export = st.text_input("Confirme a Senha ADM:", type="password", key="senha_exp_mod")

        if st.button("🚀 Exportar e Limpar", key="btn_exp_mod"):
            if senha_export == adm_pass:
                supabase = obter_supabase()
                if not supabase:
                    st.error("❌ Erro ao conectar ao Supabase.")
                    return

                with st.spinner("Processando exportação de 3 tabelas..."):
                    try:
                        data_atual = datetime.datetime.now().strftime("%d-%m-%Y_%H-%M")
                        data_dia = datetime.datetime.now().strftime("%d-%m-%Y")
                        caminho_backup = ["Relatórios IA", "Backup", data_dia]
                        links_gerados = []

                        # 1. Compras Finalizadas
                        resp_compras = supabase.table("solicitacoes_compras").select("*").eq("status", "Finalizado").execute()
                        dados_compras = [d for d in resp_compras.data if d.get("link_nf")]
                        if dados_compras:
                            output_c = io.StringIO()
                            output_c.write("\ufeff")
                            chaves_c = set()
                            for d in dados_compras:
                                chaves_c.update(d.keys())
                            writer_c = csv.DictWriter(output_c, fieldnames=list(chaves_c), delimiter=";")
                            writer_c.writeheader()
                            writer_c.writerows(dados_compras)
                            link_c = salvar_no_drive(output_c.getvalue().encode("utf-8"), f"Relatorio_Compras_{data_atual}.csv", mime_type="text/csv", nome_subpasta=caminho_backup)
                            if link_c:
                                for item in dados_compras:
                                    supabase.table("solicitacoes_compras").delete().eq("id", item["id"]).execute()
                                links_gerados.append(("Compras", link_c, len(dados_compras)))

                        # 2. Desempenho Fornecedores
                        resp_desemp = supabase.table("desempenho_fornecedores").select("*").execute()
                        dados_desemp = resp_desemp.data
                        if dados_desemp:
                            output_d = io.StringIO()
                            output_d.write("\ufeff")
                            chaves_d = set()
                            for d in dados_desemp:
                                chaves_d.update(d.keys())
                            writer_d = csv.DictWriter(output_d, fieldnames=list(chaves_d), delimiter=";")
                            writer_d.writeheader()
                            writer_d.writerows(dados_desemp)
                            link_d = salvar_no_drive(output_d.getvalue().encode("utf-8"), f"Relatorio_Desempenho_Fornecedores_{data_atual}.csv", mime_type="text/csv", nome_subpasta=caminho_backup)
                            if link_d:
                                for item in dados_desemp:
                                    supabase.table("desempenho_fornecedores").delete().eq("id", item["id"]).execute()
                                links_gerados.append(("Fornecedores", link_d, len(dados_desemp)))

                        # 3. Cotações
                        resp_cot = supabase.table("cotacoes").select("*").execute()
                        dados_cot = resp_cot.data
                        if dados_cot:
                            output_cot = io.StringIO()
                            output_cot.write("\ufeff")
                            chaves_cot = set()
                            for d in dados_cot:
                                chaves_cot.update(d.keys())
                            writer_cot = csv.DictWriter(output_cot, fieldnames=list(chaves_cot), delimiter=";")
                            writer_cot.writeheader()
                            writer_cot.writerows(dados_cot)
                            link_cot = salvar_no_drive(output_cot.getvalue().encode("utf-8"), f"Relatorio_Cotacoes_{data_atual}.csv", mime_type="text/csv", nome_subpasta=caminho_backup)
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