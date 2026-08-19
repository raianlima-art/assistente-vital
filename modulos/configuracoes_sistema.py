import streamlit as st


def iniciar():
    with st.expander("⚙️ Parâmetros de Frete", expanded=False):
        st.caption("Ajuste os valores operacionais utilizados pelo assistente para o cálculo automático de fretes.")

        c1, c2, c3 = st.columns(3)

        with c1:
            st.markdown("##### 💰 Custos Fixos Veículo")
            ipva = st.number_input("IPVA Anual (R$)", value=float(st.session_state.get("ipva", 10000.0)), key="cfg_ipva")
            seguro = st.number_input("Seguro Anual (R$)", value=float(st.session_state.get("seguro", 10000.0)), key="cfg_seguro")
            manut_anual = st.number_input("Manutenção Anual (R$)", value=float(st.session_state.get("manut_anual", 10000.0)), key="cfg_manut")
            dias_uteis = st.number_input("Dias Úteis / Ano", value=int(st.session_state.get("dias_uteis", 365)), key="cfg_dias")

        with c2:
            st.markdown("##### 🍴 Custos Unitários")
            alim = st.number_input("Alimentação / Dia (R$)", value=float(st.session_state.get("valor_alimentacao_dia", 70.0)), key="cfg_alim")
            pernoite = st.number_input("Hospedagem / Noite (R$)", value=float(st.session_state.get("valor_pernoite", 250.0)), key="cfg_pernoite")
            motorista = st.number_input("Diária Motorista (R$)", value=float(st.session_state.get("diaria_motorista", 200.0)), key="cfg_mot")

        with c3:
            st.markdown("##### ⛽ Operação & Lucro")
            consumo = st.number_input("Consumo (km/L)", value=float(st.session_state.get("consumo", 8.0)), key="cfg_cons")
            diesel = st.number_input("Preço Diesel (R$)", value=float(st.session_state.get("preco_diesel", 8.00)), key="cfg_diesel")
            fator = st.slider("Ajuste Curvas (%)", 10, 40, int(st.session_state.get("fator_estrada", 0.25) * 100), key="cfg_fator") / 100.0
            margem = st.slider("Margem Lucro (%)", 0, 100, int(st.session_state.get("margem", 20)), key="cfg_margem")

        if st.button("💾 Salvar Parâmetros", use_container_width=True, key="btn_save_cfg"):
            st.session_state.ipva = ipva
            st.session_state.seguro = seguro
            st.session_state.manut_anual = manut_anual
            st.session_state.dias_uteis = dias_uteis
            st.session_state.valor_alimentacao_dia = alim
            st.session_state.valor_pernoite = pernoite
            st.session_state.diaria_motorista = motorista
            st.session_state.consumo = consumo
            st.session_state.preco_diesel = diesel
            st.session_state.fator_estrada = fator
            st.session_state.margem = margem
            st.success("✅ Parâmetros de frete atualizados com sucesso!")