import pandas as pd
from supabase import create_client
import os

def sincronizar_appsheet_para_supabase(sheet_url, supabase_url, supabase_key):
    # Converte o link do Google Sheets para exportação CSV automatizada
    file_id = sheet_url.split('/d/')[1].split('/')[0]
    csv_url = f'https://docs.google.com/spreadsheets/d/1Q5fBVFYNB4rB-zpUC7YUqMFwyGE56Vrm2-GEyTxWQNA/edit?usp=sharing'
    
    # Lê os dados da planilha
    df = pd.read_csv(csv_url)
    
    # Conecta ao Supabase
    supabase = create_client(supabase_url, supabase_key)
    
    novos_registros = 0
    for _, row in df.iterrows():
        # Filtra apenas o que está "Aguardando pedido" no AppSheet
        if str(row.get('Status', '')).strip().lower() == 'aguardando pedido':
            item_nome = str(row.get('Nome do item/produto', '')).strip()
            os_num = str(row.get('Ordem de serviço', '')).strip()
            
            # Evita duplicidade consultando se o pedido da OS já existe
            res = supabase.table('solicitacoes_compras')\
                .select('id')\
                .eq('item_descricao', item_nome)\
                .ilike('referencia', f'%{os_num}%')\
                .execute()
                
            if not res.data:
                # Prepara o mapa de inserção
                dados = {
                    'item_descricao': item_nome,
                    'quantidade': float(row.get('Qtd', 1)),
                    'referencia': f"OS: {os_num}",
                    'motivo': f"Manutenção (Ordem de Serviço {os_num})",
                    'solicitante': f"{row.get('Solicitante', 'Fabiano')} (Manutenção Técnica)",
                    'status': 'Pendente',
                    'link_ref': str(row.get('Link', '')),
                    'created_at': '2026-08-21'
                }
                supabase.table('solicitacoes_compras').insert(dados).execute()
                novos_registros += 1
                
    return novos_registros