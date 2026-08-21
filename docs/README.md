# 🤖 Assistente Integrado Vital C — Compras & Logística

Plataforma corporativa full-stack desenvolvida em **Python** e **Streamlit** para automação de requisições de compras, cotações comparativas, cálculo de fretes operacionais, gestão de estoque/OTIF e diagnósticos financeiros executivos com **OpenAI (GPT-4o-mini)**.

---

## 🚀 Funcionalidades Principais

* **💬 Assistente IA (Chatbot Inteligente):**
  * **Cotação de Frete:** Cálculo automático de distâncias (Geopy/Photon), custos fixos, combustível (diesel), hospedagem/alimentação e margem de lucro.
  * **Solicitações de Compra:** Leitura de imagens/fotos anexadas e extração de dados do produto.
  * **Tratamento Personalizado:** Regras de interação dinâmicas para parâmetros técnicos (ID Manutenção, Compatibilidade, Encapsulamento, Datasheet).

* **📋 Painel de Compras (Acesso ADM):**
  * **Filtros Responsivos:** Seleção direcionada por *Status* (`Falta Cotação`, `Pendente`, `Aguardando entrega`, `Aguardando NF`, `Finalizado`, `Recusado`) e por *Filial* (`Arco`, `Ultrassom`, etc.).
  * **Gerador de Cotação Comparativa em PDF:** Emissão de PDF com até 3 fornecedores, cálculo de média e preço-alvo (-10%), com links externos clicáveis e envio automático ao Google Drive.
  * **Relatório Executivo Consolidado:** Emissão de PDF com o panorama de metas/economia acumulada do ano inteiro (Janeiro a Dezembro) combinado com o detalhamento do mês ativo.

* **📦 Conferência & Recebimento (Estoque):**
  * Interface simplificada para o estoquista conferir notas fiscais e cotações anexadas.
  * Monitoramento de desempenho de fornecedores (Lead Time, cumprimento de prazos e indicador OTIF - *On-Time In-Full*).

* **🧩 Módulos e Ferramentas Extras (`modulos/`):**
  * **Análise Mensal com IA (`analise_ia_mensal.py`):** Caixa retrátil (*expander*) com KPIs rápidos do mês e parecer estratégico sobre desvios e oportunidades de negociação.
  * **Limpeza e Exportação (`limpeza_exportacao.py`):** Consolidação dos totais mensais no Supabase (`fechamento_mensal`), backup das tabelas detalhadas em CSV no Google Drive e limpeza do banco.
  * **Gerenciador de Fechamento (`gerenciar_fechamento.py`):** Interface visual para inserção e ajuste de valores acumulados de meses passados.

---

## 🗄️ Estrutura do Banco de Dados (Supabase)

O sistema utiliza 4 tabelas conectadas:

| Tabela | Função |
| :--- | :--- |
| **`solicitacoes_compras`** | Registra todos os pedidos de insumos/peças criados no Chat ou via ADM. |
| **`cotacoes`** | Armazena os comparativos de preços de fornecedores, médias e economia gerada. |
| **`desempenho_fornecedores`** | Histórico de entregas, lead time e índice de qualidade/OTIF. |
| **`fechamento_mensal`** | Tabela leve de fechamento que preserva o histórico do relatório anual mantendo o banco zerado. |

### Criação da Tabela de Fechamento (`fechamento_mensal`):
```sql
CREATE TABLE IF NOT EXISTS fechamento_mensal (
    id SERIAL PRIMARY KEY,
    ano VARCHAR(4) NOT NULL,
    mes VARCHAR(2) NOT NULL,
    total_medias NUMERIC DEFAULT 0,
    meta_gasto NUMERIC DEFAULT 0,
    gasto_real NUMERIC DEFAULT 0,
    economia_total NUMERIC DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT TIMEZONE('utc'::text, NOW()),
    UNIQUE(ano, mes)
);

-- Permissão de leitura e escrita pública para a API
ALTER TABLE fechamento_mensal DISABLE ROW LEVEL SECURITY;

📂 Estrutura do Projeto

├── app.py                     # Código principal da aplicação Streamlit
├── logo.png                   # Identidade visual / Ícone da aplicação
├── requirements.txt           # Lista de dependências Python
├── modulos/                   # Extensões e ferramentas extras dinâmicas
│   ├── analise_ia_mensal.py   # Diagnóstico executivo com GPT
│   ├── limpeza_exportacao.py  # Automação de limpeza + Backup CSV Drive
│   └── gerenciar_fechamento.py# Cadastro manual de totais passados
└── .env                       # Variáveis de ambiente locais

🔑 Configuração das Variáveis de Ambiente
Configure no arquivo .env local ou nos Secrets do Streamlit (.streamlit/secrets.toml):
# OpenAI
OPENAI_API_KEY="sk-proj-..."

# Supabase
SUPABASE_URL="[https://seu-projeto.supabase.co](https://seu-projeto.supabase.co)"
SUPABASE_KEY="sua-chave-anon-ou-service-role"

# Controle de Acesso
ADM_PASSWORD="admin123"
ESTOQUE_PASSWORD="estoque123"

# Notificações E-mail (SMTP Gmail)
EMAIL_REMETENTE="seu-email@gmail.com"
EMAIL_SENHA_APP="sua-senha-de-app"
EMAIL_DESTINATARIO="compras@empresa.com.br"

# Google Drive API
GOOGLE_DRIVE_FOLDER_ID="id-da-pasta-raiz-no-drive"
GOOGLE_DRIVE_CREDENTIALS='{"type": "service_account", ...}'

🛠️ Como Executar o Projeto

1° Clone o repositório:
git clone [https://github.com/seu-usuario/vital-c-assistente.git](https://github.com/seu-usuario/vital-c-assistente.git)
cd vital-c-assistente

2° Crie e ative o ambiente virtual:
python -m venv venv
source venv/bin/activate  # No Windows: venv\Scripts\activate

3º Instale os pacotes requeridos:
pip install -r requirements.txt

4° Inicie a aplicação:
streamlit run app.py

🧹 Arquivamento e Manutenção do Supabase

Para garantir consumo mínimo de armazenamento no plano gratuito do Supabase:

Trabalhe normalmente durante o mês coletando solicitações e cotações.

No final do mês, vá até a aba 🧩 Ferramentas Extras e acesse a opção Limpeza e Exportação.

O sistema consolida o resumo do período na tabela fechamento_mensal, faz upload de planilhas .csv completas na pasta do Google Drive e apaga os itens detalhados do Supabase.

Os relatórios executivos em PDF continuam contendo a linha do tempo e totais do ano inteiro sem sobrecarregar o banco de dados.
