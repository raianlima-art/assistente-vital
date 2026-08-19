import calendar
import datetime
import json
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
        return "{:,.2f}".format(float(valor)).replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "0,00"


def iniciar():
    with st.expander("🤖 Diagnóstico e Análise Mensal com IA", expanded=False):
        st.caption("Gera um parecer executivo sobre o volume de compras, economia gerada, metas atingidas e oportunidades de negociação.")

        col1, col2 = st.columns(2)
        with col1:
            meses_dict = {
                "01": "Janeiro", "02": "Fevereiro", "03": "Março", "04": "Abril",
                "05": "Maio", "06": "Junho", "07": "Julho", "08": "Agosto",
                "09": "Setembro", "10": "Outubro", "11": "Novembro", "12": "Dezembro"
            }
            mes_sel = st.selectbox(
                "Selecione o Mês:",
                options=list(meses_dict.keys()),
                format_func=lambda x: f"{x} - {meses_dict[x]}",
                index=datetime.datetime.now().month - 1,
                key="ia_analise_mes"
            )
        with col2:
            ano_sel = st.selectbox(
                "Selecione o Ano:",
                options=["2025", "2026", "2027"],
                index=1,
                key="ia_analise_ano"
            )

        btn_analisar = st.button("📊 Gerar Diagnóstico com IA", use_container_width=True, key="btn_run_ia_analise")

        if btn_analisar:
            supabase = obter_supabase()
            client_openai = obter_openai()

            if not supabase or not client_openai:
                st.error("❌ Conexão com Supabase ou OpenAI indisponível. Verifique as configurações de secrets.")
                return

            with st.spinner(f"Coletando dados e consultando Inteligência Artificial para {meses_dict[mes_sel]}/{ano_sel}..."):
                ano_int = int(ano_sel)
                mes_int = int(mes_sel)
                ultimo_dia = calendar.monthrange(ano_int, mes_int)[1]

                data_inicio = f"{ano_sel}-{mes_sel}-01"
                data_fim = f"{ano_sel}-{mes_sel}-{ultimo_dia:02d}"

                # 1. Busca cotações detalhadas ativas por intervalo de datas
                try:
                    cotacoes_raw = (
                        supabase.table("cotacoes")
                        .select("*")
                        .gte("data_cotacao", data_inicio)
                        .lte("data_cotacao", data_fim)
                        .execute()
                        .data or []
                    )
                except Exception as e_q:
                    st.error(f"Erro ao buscar cotações: {e_q}")
                    cotacoes_raw = []

                # 2. Busca resumo no fechamento_mensal caso o mês já tenha sido limpo
                try:
                    fechamento_raw = (
                        supabase.table("fechamento_mensal")
                        .select("*")
                        .eq("ano", str(ano_sel))
                        .eq("mes", str(mes_sel))
                        .execute()
                        .data or []
                    )
                except Exception:
                    fechamento_raw = []

                if not cotacoes_raw and not fechamento_raw:
                    st.warning(f"⚠️ Não foram encontrados registros de cotações ou fechamentos para o período {meses_dict[mes_sel]}/{ano_sel}.")
                    return

                tot_medias = 0.0
                tot_meta = 0.0
                tot_gasto = 0.0
                tot_economia = 0.0
                total_itens = len(cotacoes_raw)
                metas_atingidas = 0
                itens_resumo = []

                if cotacoes_raw:
                    for item in cotacoes_raw:
                        med = float(item.get("media_orcam", 0) or 0)
                        alvo = float(item.get("preco_alvo", 0) or 0)
                        gasto = float(item.get("valor_comprado", 0) or 0)
                        econ = float(item.get("economia_real", 0) or 0)
                        st_m = item.get("status_meta", "")

                        tot_medias += med
                        tot_meta += alvo
                        tot_gasto += gasto
                        tot_economia += econ

                        if "Atingida" in st_m and "Não" not in st_m:
                            metas_atingidas += 1

                        itens_resumo.append({
                            "produto": item.get("produto"),
                            "media": med,
                            "comprado": gasto,
                            "economia": econ,
                            "status_meta": st_m
                        })
                elif fechamento_raw:
                    f_data = fechamento_raw[0]
                    tot_medias = float(f_data.get("total_medias", 0) or 0)
                    tot_meta = float(f_data.get("meta_gasto", 0) or 0)
                    tot_gasto = float(f_data.get("gasto_real", 0) or 0)
                    tot_economia = float(f_data.get("economia_total", 0) or 0)

                pct_economia = (tot_economia / tot_medias * 100) if tot_medias > 0 else 0.0
                pct_meta_atingida = (metas_atingidas / total_itens * 100) if total_itens > 0 else 0.0

                c_kpi1, c_kpi2, c_kpi3, c_kpi4 = st.columns(4)
                c_kpi1.metric("Total Orçado (Médias)", f"R$ {formar_real(tot_medias)}")
                c_kpi2.metric("Total Gasto Real", f"R$ {formar_real(tot_gasto)}")
                c_kpi3.metric("Economia Gerada", f"R$ {formar_real(tot_economia)}", delta=f"{pct_economia:.1f}%")
                c_kpi4.metric("Aproveitamento de Meta", f"{pct_meta_atingida:.0f}%" if total_itens > 0 else "N/A")

                st.divider()

                prompt_contexto = {
                    "periodo": f"{meses_dict[mes_sel]}/{ano_sel}",
                    "total_orcado_medias": tot_medias,
                    "meta_gastos_alvo": tot_meta,
                    "total_gasto_real": tot_gasto,
                    "economia_total_reais": tot_economia,
                    "percentual_economia": round(pct_economia, 2),
                    "total_itens_cotados": total_itens,
                    "itens_com_meta_atingida": metas_atingidas,
                    "amostra_produtos": itens_resumo[:15]
                }

                system_instructions = """
                Você é um consultor executivo de inteligência em suprimentos e compras corporativas da empresa Vital C.
                Análise os dados de compras fornecidos do mês e gere um relatório estruturado e direto contendo:

                1. 📈 RESUMO EXECUTIVO: Avaliação geral do desempenho do mês.
                2. 💡 EFICIÊNCIA DE CUSTOS & ECONOMIA: Como a equipe se comportou em relação às metas (meta = média - 10%).
                3. ⚠️ PONTOS DE ATENÇÃO / DESTAQUES: Itens com maiores desvios ou onde não se atingiu a meta.
                4. 🎯 RECOMENDAÇÕES PARA O PRÓXIMO MÊS: Dicas práticas de negociação e estratégia de compras.

                Escreva em português profissional, com tom direto, usando marcadores (bullets) e destaques em negrito.
                """

                try:
                    response = client_openai.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {"role": "system", "content": system_instructions},
                            {"role": "user", "content": f"Dados de Compras do Mês: {json.dumps(prompt_contexto, ensure_ascii=False)}"}
                        ],
                        temperature=0.4
                    )

                    parecer_ia = response.choices[0].message.content
                    st.markdown(parecer_ia)

                except Exception as e_ia:
                    st.error(f"❌ Erro ao processar análise via IA: {e_ia}")