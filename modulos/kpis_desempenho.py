import os
import streamlit as st
from openai import OpenAI
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


def obter_openai():
    api_key = get_secret("OPENAI_API_KEY")
    if api_key:
        return OpenAI(api_key=api_key)
    return None


def iniciar():
    with st.expander("📈 KPIs & Desempenho", expanded=False):
        supabase = obter_supabase()
        openai_client = obter_openai()

        if not supabase:
            st.error("❌ Conexão com Supabase indisponível.")
            return

        # 1. Busca dados de desempenho de fornecedores
        try:
            dados = supabase.table("desempenho_fornecedores").select("*").execute().data or []
        except Exception:
            dados = []

        total_pedidos = len(dados)
        lead_time_medio = sum(float(d.get("lead_time_dias", 0) or 0) for d in dados) / total_pedidos if total_pedidos > 0 else 0.0
        otif_ok_count = sum(1 for d in dados if d.get("otif_ok"))
        otif_pct = (otif_ok_count / total_pedidos * 100) if total_pedidos > 0 else 100.0
        prazo_medio_pagto = int(sum(float(d.get("prazo_pagamento_dias", 0) or 0) for d in dados) / total_pedidos) if total_pedidos > 0 else 16

        # Exibição dos cards idênticos à sua tela
        c1, c2, c3 = st.columns(3)
        c1.metric("⏱️ Lead Time Médio", f"{lead_time_medio:.1f} dias")
        c2.metric("🎯 OTIF / Qualidade", f"{otif_pct:.1f}%")
        c3.metric("💳 Prazo Médio Pagto", f"{prazo_medio_pagto} dias")

        st.divider()

        # Botão para gerar parecer
        if st.button("💡 Gerar Oportunidades de Melhoria com IA", use_container_width=True, key="btn_kpi_ia"):
            if not openai_client:
                st.error("❌ Chave da OpenAI não configurada.")
                return

            with st.spinner("Analisando gargalos operacionais e oportunidades de caixa..."):
                prompt_system = """
                Você é um especialista em logística e gestão de suprimentos corporativos.
                Com base nos KPIs operacionais de compras fornecidos, analise os gargalos e gere exatamente 3 recomendações curtas e objetivas do que pode ser melhorado.

                Regras de Negócio para Avaliação:
                - Lead Time próximo de 0.0 dias indica falta de registro da data real de entrega pelo estoque ou compras em balcão/pronta entrega.
                - OTIF alto (100%) é ótimo, mas se o Lead Time for 0, deve-se alertar sobre o risco de dados incompletos.
                - Prazo de Pagamento abaixo de 30 dias (ex: 16 dias) pressiona o caixa e deve ser renegociado para prazos faturados de 28, 30 ou 45 dias.

                Responda em formato markdown, direto ao ponto, com ícones e sem introduções genéricas.
                """

                dados_kpi = {
                    "lead_time_medio_dias": lead_time_medio,
                    "otif_qualidade_porcentagem": otif_pct,
                    "prazo_medio_pagamento_dias": prazo_medio_pagto,
                    "total_pedidos_avaliados": total_pedidos
                }

                try:
                    res = openai_client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {"role": "system", "content": prompt_system},
                            {"role": "user", "content": f"KPIs Atuais: {dados_kpi}"}
                        ],
                        temperature=0.3
                    )

                    st.markdown("#### 🚀 Diagnóstico & Oportunidades de Melhoria")
                    st.info(res.choices[0].message.content)

                except Exception as e:
                    st.error(f"Erro ao consultar IA: {e}")