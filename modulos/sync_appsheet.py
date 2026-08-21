import streamlit as st
import pandas as pd
from supabase import create_client
import os

def iniciar():
    sheet_url = "https://docs.google.com/spreadsheets/d/1Q5fBVFYNB4rB-zpUC7YUqMFwyGE56Vrm2-GEyTxWQNA/edit?usp=sharing"
    gid_aba = "978876710"
    
    with st.expander("🔄 Sincronização Google Sheets / AppSheet"):
        st.caption("Sincroniza automaticamente os pedidos com status **Aguardando pedido** diretamente da planilha.")
        
        if st.button("🚀 Sincronizar Agora com o AppSheet", use_container_width=True):
            try:
                file_id = sheet_url.split('/d/')[1].split('/')[0]
                csv_url = f'https://docs.google.com/spreadsheets/d/{file_id}/export?format=csv&gid={gid_aba}'
                
                df = pd.read_csv(csv_url)
                df.columns = [str(col).strip() for col in df.columns]
                
                col_status = next((c for c in df.columns if 'status' in c.lower()), None)
                col_item = next((c for c in df.columns if 'nome' in c.lower() or 'item' in c.lower() or 'produto' in c.lower()), None)
                col_os = next((c for c in df.columns if 'ordem' in c.lower() or 'serviço' in c.lower() or 'os' in c.lower()), None)
                col_motivo = next((c for c in df.columns if 'motivo' in c.lower()), None)
                col_qtd = next((c for c in df.columns if 'qtd' in c.lower() or 'quant' in c.lower()), None)
                col_solic = next((c for c in df.columns if 'solicit' in c.lower()), None)
                col_link = next((c for c in df.columns if 'link' in c.lower()), None)

                if not col_status or not col_item:
                    st.error("❌ Não foi possível mapear as colunas da planilha.")
                    return

                supabase_url = os.getenv("SUPABASE_URL")
                supabase_key = os.getenv("SUPABASE_KEY")
                supabase = create_client(supabase_url, supabase_key)
                
                novos = 0
                
                for idx, row in df.iterrows():
                    status_valor = str(row.get(col_status, '')).strip().lower()
                    
                    if status_valor == 'aguardando pedido':
                        item_nome = str(row.get(col_item, '')).strip()
                        os_num = str(row.get(col_os, '')).strip() if col_os else ''
                        motivo_planilha = str(row.get(col_motivo, '')).strip() if col_motivo else ''
                        link_val = str(row.get(col_link, '')).strip() if col_link else ''
                        
                        if not item_nome or item_nome.lower() == 'nan':
                            continue
                        
                        qtd_raw = str(row.get(col_qtd, '1')).replace(',', '.').split('.')[0].strip() if col_qtd else '1'
                        try:
                            qtd_val = int(qtd_raw)
                        except ValueError:
                            qtd_val = 1

                        if os_num and os_num.lower() != 'nan':
                            os_limpa = os_num.replace('OS:', '').strip()
                            res = supabase.table('solicitacoes_compras')\
                                .select('id')\
                                .eq('item_descricao', item_nome)\
                                .ilike('referencia', f'%{os_limpa}%')\
                                .execute()
                        else:
                            res = supabase.table('solicitacoes_compras')\
                                .select('id')\
                                .eq('item_descricao', item_nome)\
                                .eq('status', 'Pendente')\
                                .execute()
                            
                        if not res.data:
                            motivo_final = motivo_planilha if (motivo_planilha and motivo_planilha.lower() != 'nan') else "Manutenção Técnica"
                            solic_val = str(row.get(col_solic, 'Fabiano')).strip() if col_solic else 'Fabiano'
                            os_txt = f"OS: {os_num}" if (os_num and os_num.lower() != 'nan') else "AppSheet"
                            
                            if link_val and link_val.lower() != 'nan':
                                if not link_val.startswith('http'):
                                    link_val = 'https://' + link_val
                                ref_final = f'{os_txt} | <a href="{link_val}" target="_blank" style="color:#0284c7; font-weight:bold; text-decoration:underline;">🔗 Ver Produto</a>'
                            else:
                                ref_final = os_txt

                            dados = {
                                'item_descricao': item_nome,
                                'quantidade': qtd_val,
                                'referencia': ref_final,
                                'motivo': motivo_final,
                                'solicitante': solic_val,
                                'status': 'Pendente',
                                'created_at': '2026-08-21'
                            }
                            
                            supabase.table('solicitacoes_compras').insert(dados).execute()
                            novos += 1
                            
                st.toast(f"✅ Sincronizado! {novos} novos itens importados.", icon="🚀")
                
            except Exception as e:
                st.error(f"Erro ao acessar planilha: {e}")