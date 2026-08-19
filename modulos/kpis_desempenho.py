import os
import streamlit as st
from supabase import create_client

def obter_supabase():
    def get_secret(key, default=None):
        try:
            if key in st.secrets:
                return st.secrets[key]
        except Exception:
            pass
        return os.getenv(key, default)

    url = get_secret("SUPABASE_URL")
    key = get_secret("SUPABASE_KEY")
    
    if url and key and "seu-projeto" not in url:
        try:
            return create_client(url, key)
        except Exception:
            return None
    return None

def iniciar():
    """Função invocada automaticamente pelo sistema de plugins do app.py"""
    with st.expander("📈 Indicadores de Desempenho (KPIs)", expanded=True):
        supabase = obter_supabase()
        
        if not supabase:
            st.warning("⚠️ Supabase desconectado. Não foi possível carregar os KPIs.")
            return

        try:
            res_kpi = supabase.table("desempenho_fornecedores").select("*").execute().data
            if res_kpi:
                lead_times = [k.get("lead_time_dias") for k in res_kpi if k.get("lead_time_dias") is not None]
                lt_medio = sum(lead_times) / len(lead_times) if lead_times else 0.0

                otifs = [k.get("otif_ok") for k in res_kpi if k.get("otif_ok") is not None]
                otif_pct = (sum(1 for o in otifs if o) / len(otifs) * 100) if otifs else 0.0

                prazos_pg = [k.get("prazo_pagamento_dias") for k in res_kpi if k.get("prazo_pagamento_dias") is not None]
                pmp_medio = sum(prazos_pg) / len(prazos_pg) if prazos_pg else 0.0

                col_kpi1, col_kpi2, col_kpi3 = st.columns(3)
                col_kpi1.metric("⏱️ Lead Time Médio", f"{lt_medio:.1f} dias")
                col_kpi2.metric("🎯 OTIF / Qualidade", f"{otif_pct:.1f}%")
                col_kpi3.metric("💳 Prazo Médio Pagto", f"{pmp_medio:.0f} dias")
            else:
                st.info("Nenhum registro de fornecedor para calcular indicadores no momento.")
        except Exception as e:
            st.error(f"Erro ao carregar KPIs: {e}")