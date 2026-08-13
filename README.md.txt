# 🤖 Assistente Integrado Vital

Um sistema inteligente desenvolvido em **Python** e **Streamlit** para a **Vital Logística**. Este assistente virtual utiliza Inteligência Artificial (OpenAI) para otimizar o fluxo de trabalho operacional, realizando cotações complexas de frete e gerenciando solicitações de compras de insumos.

---

## ✨ Funcionalidades

- **💬 Chat Inteligente (IA):** Comunicação natural com os operadores, guiando a coleta de dados necessários para cotações e compras.
- **🚚 Cotação de Frete Automatizada:** Calcula custos operacionais de transporte considerando:
  - Distância real entre cidades (via API de geolocalização).
  - Gastos com diesel, alimentação e hospedagem.
  - Rateio de custos fixos do veículo (IPVA, seguro, manutenção).
  - Margem de lucro configurável.
- **🛒 Gestão de Compras:**
  - Operadores podem solicitar compras fornecendo link, referência, quantidade e motivo.
  - Envio automático de **E-mail de Notificação** para o setor de compras.
  - Integração com banco de dados **Supabase** para salvar o histórico.
- **🔐 Painel Administrativo (Modo ADM):**
  - Área restrita protegida por senha na barra lateral.
  - Visualização em tempo real (estilo Kanban simplificado) de todos os pedidos de compra.
  - Ações rápidas de status: `✅ Aprovar`, `🛒 Comprado`, `❌ Recusar` e `🏁 Finalizar`.

---

## 🛠️ Tecnologias Utilizadas

- **[Python 3](https://www.python.org/)**
- **[Streamlit](https://streamlit.io/)** - Interface web interativa.
- **[OpenAI API (GPT-4o-mini)](https://openai.com/)** - Cérebro do assistente virtual.
- **[Supabase](https://supabase.com/)** - Banco de dados (PostgreSQL as a Service).
- **[Geopy (Photon)](https://geopy.readthedocs.io/)** - Cálculo de distâncias baseadas em geolocalização real.

---

## ⚙️ Como executar localmente

1. **Clone o repositório:**
   ```bash
   git clone [https://github.com/SEU_USUARIO/assistente-vital.git](https://github.com/SEU_USUARIO/assistente-vital.git)
   cd assistente-vital