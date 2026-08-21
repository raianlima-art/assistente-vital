import streamlit as st
import pandas as pd
from supabase import create_client
import os

def render_sync_appsheet():
    st.subheader("🔄 Sincronização Google Sheets / AppSheet")
    st.markdown("Importe os pedidos com status **Aguardando pedido** diretamente para a base do Supabase.")
    
    sheet_url = st.text_input(
        "Link da Planilha do Google Sheets:",
        value="https://docs.google.com/spreadsheets/d/1Q5fBVFYNB4rB-zpUC7YUqMFwyGE56Vrm2-GEyTxWQNA/edit?usp=sharing"
    )
    
    if st.button("🚀 Sincronizar Agora com o AppSheet"):
        try:
            # Extrai ID da planilha e gera URL de exportação direta CSV
            file_id = sheet_url.split('/d/')[1].split('/')[0]
            csv_url = f'https://docs.google.com/spreadsheets/d/{file_id}/export?format=csv'
            
            df = pd.read_csv(csv_url)
            
            # Conexão Supabase
            supabase_url = os.getenv("SUPABASE_URL")
            supabase_key = os.getenv("SUPABASE_KEY")
            supabase = create_client(supabase_url, supabase_key)
            
            novos = 0
            for _, row in df.iterrows():
                status_str = str(row.get('Status', '')).strip().lower()
                
                # Mapeia apenas os itens aguardando pedido no AppSheet
                if status_str == 'aguardando pedido':
                    item_nome = str(row.get('Nome do item/produto', '')).strip()
                    os_num = str(row.get('Ordem de serviço', '')).strip()
                    
                    if not item_nome or item_nome == 'nan':
                        continue
                        
                    # Impede duplicidades checando item + OS
                    res = supabase.table('solicitacoes_compras')\
                        .select('id')\
                        .eq('item_descricao', item_nome)\
                        .ilike('referencia', f'%{os_num}%')\
                        .execute()
                        
                    if not res.data:
                        dados = {
                            'item_descricao': item_nome,
                            'quantidade': float(row.get('Qtd', 1)) if pd.notnull(row.get('Qtd')) else 1.0,
                            'referencia': f"OS: {os_num}" if os_num and os_num != 'nan' else 'AppSheet',
                            'motivo': f"Manutenção (OS {os_num})" if os_num and os_num != 'nan' else 'Migração AppSheet',
                            'solicitante': f"{row.get('Solicitante', 'Fabiano')} (Manutenção Técnica)",
                            'status': 'Pendente',
                            'link_ref': str(row.get('Link', '')) if pd.notnull(row.get('Link')) else '',
                            'created_at': '2026-08-21'
                        }
                        supabase.table('solicitacoes_compras').insert(dados).execute()
                        novos += 1
                        
            st.success(f"✅ Sincronização concluída! {novos} novos pedidos foram adicionados à fila de pendentes.")
            
        except Exception as e:
            st.error(f"Erro ao acessar a planilha: {e}")