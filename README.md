
raw
Readme · MD
<div align="center">
# 🏛️ ARTVAL-MA
### Validador Inteligente de Acervo Técnico — CREA-MA
 
[![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Streamlit](https://img.shields.io/badge/Streamlit-FF4B4B?style=flat-square&logo=streamlit&logoColor=white)](https://streamlit.io)
[![Claude API](https://img.shields.io/badge/Claude%20Sonnet-D4A017?style=flat-square&logo=anthropic&logoColor=white)](https://anthropic.com)
[![Hackathon](https://img.shields.io/badge/Hackathon-CREA--MA%202026-1c3a55?style=flat-square)]()
[![Status](https://img.shields.io/badge/Status-Concluído-22c55e?style=flat-square)]()
 
> Sistema de auditoria automática de documentos técnicos para emissão de CAT no SITAC/MA,
> construído com pipeline de **5 agentes de IA especializados** + camada determinística em Python puro.
 
</div>
---
 
## 🎯 Problema
 
Engenheiros registrados no CREA-MA precisam validar manualmente pares de documentos
**(ART × Atestado de Capacidade Técnica)** antes de submeter ao SITAC/MA.
 
Erros simples de data ou CNPJ resultam em **indeferimento imediato** — sem feedback claro sobre o motivo.
O processo manual é lento, sujeito a falhas humanas e exige conhecimento aprofundado das resoluções CONFEA/CREA.
 
## 💡 Solução
 
O **ARTVAL-MA** automatiza essa auditoria em segundos:
 
- 📄 Lê os documentos (PDF ou ZIP exportado do SITAC)
- 🔍 Extrai e estrutura todos os dados relevantes
- ⚖️ Valida 7 regras de conformidade com precisão determinística e IA
- 📚 Cita a fundamentação normativa de cada irregularidade
- 📝 Gera um **Parecer Técnico formal** pronto para protocolo no CREA-MA
---
 
## 🏗️ Arquitetura — Pipeline de 5 Agentes
 
```
[PDF / ZIP]
     │
     ▼
┌─────────────┐     ┌─────────────┐     ┌──────────────────┐
│   Agente 1  │────►│   Agente 2  │────►│  Camada Det. ⚡   │
│ Classificar │     │   Extrair   │     │  V03 / V04       │
│ tipo & qual.│     │  JSON est.  │     │  Python puro     │
└─────────────┘     └─────────────┘     └──────────────────┘
                                                 │
                         ┌───────────────────────┘
                         ▼
                ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
                │   Agente 3  │────►│   Agente 4  │────►│   Agente 5  │
                │  Auditar    │     │   Normas    │     │   Parecer   │
                │ V01/02/05-07│     │ CONFEA/CREA │     │   Formal    │
                └─────────────┘     └─────────────┘     └─────────────┘
```
 
| Camada | Responsabilidade | Tecnologia |
|--------|-----------------|------------|
| Agente 1 | Classifica tipo e qualidade dos documentos | Claude Sonnet |
| Agente 2 | Extrai dados estruturados (ART e Atestado) | Claude Sonnet |
| **Validador Determinístico** | Valida datas V03/V04 — resultado definitivo e incontestável | **Python puro** |
| Agente 3 | Audita regras SITAC/MA (V01, V02, V05–V07) | Claude Sonnet |
| Agente 4 | Cita fundamentação normativa CONFEA/CREA | Claude Sonnet |
| Agente 5 | Redige Parecer Técnico formal pronto para protocolo | Claude Sonnet |
 
> ⚡ **Decisão de design crítica:** a camada determinística em Python valida as regras de data (V03/V04)
> de forma independente da IA. Seus resultados **nunca podem ser contraditos** pelos agentes,
> garantindo precisão absoluta nas verificações que causam indeferimento imediato no SITAC/MA.
 
---
 
## ✅ Regras de Validação
 
| ID | Regra | Criticidade | Camada |
|----|-------|-------------|--------|
| V01 | CNPJ da ART igual ao esperado (CREA-MA) | 🔴 CRÍTICA | IA |
| V02 | CNPJ do Atestado igual ao esperado | 🔴 CRÍTICA | IA |
| V03 | Término do Atestado ≤ Data de Baixa da ART | 🔴 CRÍTICA | **Determinística** |
| V04 | Emissão do Atestado ≤ Data de Baixa (+1 dia = indeferimento imediato) | 🔴 CRÍTICA | **Determinística** |
| V05 | Atividades coincidem em descrição e quantidade (tolerância zero) | 🟠 ALTA | IA |
| V06 | Número do contrato idêntico em ART e Atestado | 🟠 ALTA | IA |
| V07 | Número da ART referenciada no Atestado confere | 🟠 ALTA | IA |
 
---
 
## 📊 Saídas do Sistema
 
- **Banner de resultado** — APROVADO / APROVADO COM RESSALVAS / REPROVADO
- **Classificação dos documentos** — tipo e qualidade de cada arquivo
- **Dados extraídos** — tabela estruturada com todos os campos relevantes
- **Verificações detalhadas** — status, valores encontrados vs esperados, fundamentação
- **Referências normativas** — resolução, artigo, ementa e consequência para cada irregularidade
- **Parecer Técnico formal** — documento completo pronto para protocolo no CREA-MA
- **Exportação** — JSON completo da auditoria e Parecer em `.txt`
---
 
## 🚀 Como executar
 
**Pré-requisitos:** Python 3.11+, conta na [Anthropic](https://console.anthropic.com)
 
```bash
# 1. Clone o repositório
git clone https://github.com/camilaluizamachado/artval-ma.git
cd artval-ma
 
# 2. Instale as dependências
pip install -r requirements.txt
 
# 3. Configure a chave da API
mkdir -p .streamlit
echo 'ANTHROPIC_API_KEY = "sua-chave-aqui"' > .streamlit/secrets.toml
 
# 4. Execute
streamlit run app.py
```
 
Acesse `http://localhost:8501` no navegador, faça upload da ART e do Atestado e clique em **Executar Validação**.
 
---
 
## 🛠️ Tecnologias
 
| Tecnologia | Uso |
|------------|-----|
| Python 3.11 | Lógica determinística, orquestração do pipeline |
| Streamlit | Interface web interativa |
| Anthropic Claude Sonnet | Agentes de classificação, extração, auditoria e redação |
| Pydantic | Validação e tipagem dos schemas de dados |
| pypdf | Extração de texto de arquivos PDF |
| Dataclasses | Modelagem das estruturas internas do relatório |
 
---
 
## 📁 Estrutura do Projeto
 
```
artval-ma/
├── app.py              # Aplicação principal (pipeline + interface)
├── requirements.txt    # Dependências
├── .gitignore
└── docs/
    └── demo.png        # Screenshot da interface
```
 
---
 
## 🏆 Contexto
 
Projeto desenvolvido no **Hackathon CREA-MA 2026**, com o objetivo de modernizar e automatizar
o processo de validação de acervo técnico para engenheiros registrados no Conselho Regional
de Engenharia e Agronomia do Maranhão.
 
---
 
## 👩‍💻 Autora
 
**Camila Luiza Machado**
Estudante de Engenharia da Computação — UEMA, São Luís - MA
 
[![GitHub](https://img.shields.io/badge/GitHub-camilaluizamachado-181717?style=flat-square&logo=github)](https://github.com/camilaluizamachado)
