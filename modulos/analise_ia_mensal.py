import datetime
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


def formar_real(valor):
    try:
        if valor is None:
            return "0,00"
        return f"{float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "0,00"


def render_card_kpi(titulo, valor, indicador=None):
    badge_html = ""
    if indicador:
        badge_html = f'<span style="font-size: 0.7rem; color: #15803d; font-weight: 600; background: #f0fdf4; padding: 2px 6px; border-radius: 4px; border: 1px solid #bbf7d0;">↑ {indicador}</span>'

    # String HTML em linha única para não gerar bloco de código por indentação no Markdown
    return f'<div style="background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px 12px; min-height: 68px; display: flex; flex-direction: column; justify-content: center; box-sizing: border-box;"><div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;"><span style="font-size: 0.7rem; color: #64748b; font-weight: 600; text-transform: uppercase;">{titulo}</span>{badge_html}</div><div style="font-size: 1.05rem; color: #0f172a; font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{valor}</div></div>'


def iniciar():
    with st.expander("🤖 Análise Mensal IA", expanded=False):
        supabase = obter_supabase()
        openai_client = obter_openai()

        if not supabase:
            st.error("❌ Conexão com Supabase indisponível.")
            return

        c_mes, c_ano, c_btn = st.columns([2, 1.2, 2])

        meses_nomes = [
            "01 - Janeiro", "02 - Fevereiro", "03 - Março", "04 - Abril",
            "05 - Maio", "06 - Junho", "07 - Julho", "08 - Agosto",
            "09 - Setembro", "10 - Outubro", "11 - Novembro", "12 - Dezembro"
        ]

        mes_atual_idx = datetime.datetime.now().month - 1

        with c_mes:
            mes_sel = st.selectbox("Mês:", meses_nomes, index=mes_atual_idx, key="sel_ia_mes_module")
        with c_ano:
            ano_sel = st.selectbox("Ano:", ["2025", "2026", "2027"], index=1, key="sel_ia_ano_module")
        with c_btn:
            st.write("")
            btn_analisar = st.button("🤖 Gerar Diagnóstico", use_container_width=True, key="btn_run_ia_analise")

        mes_num = mes_sel.split(" - ")[0]
        mes_nome = mes_sel.split(" - ")[1]

        try:
            res_cot = supabase.table("cotacoes").select("*").execute().data or []
            dados_mes = [
                c for c in res_cot
                if str(c.get("data_cotacao", "")).startswith(f"{ano_sel}-{mes_num}")
            ]
        except Exception:
            dados_mes = []

        tot_orcado = sum(float(c.get("media_orcam", 0) or 0) for c in dados_mes)
        tot_gasto = sum(float(c.get("valor_comprado", 0) or 0) for c in dados_mes)
        tot_econ = sum(float(c.get("economia_real", 0) or 0) for c in dados_mes)

        pct_econ = (tot_econ / tot_orcado * 100) if tot_orcado > 0 else 0.0
        metas_ok = sum(1 for c in dados_mes if "Atingida" in str(c.get("status_meta", "")) and "Não" not in str(c.get("status_meta", "")))
        pct_meta = (metas_ok / len(dados_mes) * 100) if dados_mes else 100.0

        st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)

        k1, k2, k3, k4 = st.columns(4)
        with k1:
            st.markdown(render_card_kpi("Total Orçado", f"R$ {formar_real(tot_orcado)}"), unsafe_allow_html=True)
        with k2:
            st.markdown(render_card_kpi("Gasto Real", f"R$ {formar_real(tot_gasto)}"), unsafe_allow_html=True)
        with k3:
            indicador_str = f"{pct_econ:.1f}%" if tot_econ > 0 else None
            st.markdown(render_card_kpi("Economia", f"R$ {formar_real(tot_econ)}", indicador=indicador_str), unsafe_allow_html=True)
        with k4:
            st.markdown(render_card_kpi("Aproveit. Meta", f"{pct_meta:.0f}%"), unsafe_allow_html=True)

        if btn_analisar:
            if not openai_client:
                st.error("❌ Chave da OpenAI não configurada.")
                return

            with st.spinner(f"Analisando compras de {mes_nome}/{ano_sel}..."):
                prompt_system = """
                Você é um consultor executivo de Compras e Suprimentos.
                Analise os números consolidados do mês e gere um parecer executivo objetivo em markdown, com:
                1. Resumo do Desempenho Financeiro
                2. Oportunidades & Pontos de Atenção
                3. Recomendação de Negociação
                Seja direto, profissional e use marcadores limpos.
                """

                dicionario_dados = {
                    "periodo": f"{mes_nome}/{ano_sel}",
                    "total_itens_cotados": len(dados_mes),
                    "total_orcado_medias": tot_orcado,
                    "total_gasto_real": tot_gasto,
                    "economia_total_gerada": tot_econ,
                    "percentual_economia": pct_econ,
                    "percentual_metas_atingidas": pct_meta
                }

                try:
                    res = openai_client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {"role": "system", "content": prompt_system},
                            {"role": "user", "content": f"Dados operacionais: {dicionario_dados}"}
                        ],
                        temperature=0.3
                    )
                    st.markdown("<div style='margin-top: 14px;'></div>", unsafe_allow_html=True)
                    st.info(res.choices[0].message.content)
                except Exception as e:
                    st.error(f"Erro ao consultar IA: {e}")