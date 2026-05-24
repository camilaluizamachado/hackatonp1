# 🏛️ ARTVAL-MA — Validador de Acervo Técnico

> Projeto desenvolvido no **Hackathon CREA-MA 2026**

Sistema de auditoria automática de documentos técnicos (ART × Atestado) 
para emissão de CAT no SITAC/MA, utilizando pipeline de 5 agentes com IA.

## ✨ Funcionalidades

- **Agente 1** — Classificação automática do tipo e qualidade dos documentos
- **Agente 2** — Extração estruturada de dados (ART e Atestado)
- **Camada determinística** — Validação de datas V03/V04 em Python puro
- **Agente 3** — Auditoria das regras SITAC/MA (V01, V02, V05–V07)
- **Agente 4** — Fundamentação normativa (Resoluções CONFEA/CREA)
- **Agente 5** — Geração de Parecer Técnico formal para protocolo

## 🛠️ Tecnologias

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-FF4B4B?style=for-the-badge&logo=streamlit&logoColor=white)
![Claude API](https://img.shields.io/badge/Claude_API-D4A017?style=for-the-badge)

## 🚀 Como executar

```bash
pip install -r requirements.txt
streamlit run app.py
```

Configure sua chave em `.streamlit/secrets.toml`:
```toml
ANTHROPIC_API_KEY = "sua-chave-aqui"
```

## 👩‍💻 Autora

Camila Luiza Machado — Engenharia da Computação, UEMA
