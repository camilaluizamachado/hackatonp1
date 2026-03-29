"""
Validador de Acervo Tecnico Inteligente - SITAC/MA
Versao 1.1 | CREA-MA | Desenvolvido para Streamlit Community Cloud

Changelog v1.1:
- Camada de validacao deterministica Python antes da auditoria por IA
  Garante que regras criticas de data (V03, V04) nunca sejam ignoradas
  por alucinacao do modelo, independente do output do Claude.
- Injecao dos resultados deterministicos no prompt de auditoria para
  consistencia entre a camada local e o relatorio da IA.
- Classe DeterministicValidator isolada e testavel (pytest-friendly).
"""

import streamlit as st
import anthropic
import json
import zipfile
import io
import base64
from datetime import datetime, date
from dataclasses import dataclass, field, asdict
from typing import Optional
from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────────
# SCHEMA PYDANTIC
# ─────────────────────────────────────────────────────────────────────────────

class Atividade(BaseModel):
    descricao: str
    quantidade: float
    unidade: str


class DadosART(BaseModel):
    numero: str
    contratante_cnpj: str
    contratante_razao_social: str
    contrato_numero: str
    data_inicio: str
    data_termino_previsto: str
    data_solicitacao_baixa: Optional[str] = None
    data_registro_art: Optional[str] = None
    valor_contrato: Optional[float] = None
    atividades: list[Atividade] = Field(default_factory=list)


class DadosAtestado(BaseModel):
    emitente_cnpj: str
    emitente_razao_social: str
    contrato_numero: str
    art_referenciada: str
    data_inicio_periodo: str
    data_termino_periodo: str
    data_emissao: str
    atividades: list[Atividade] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# DATACLASSES — Log de Auditoria
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class VerificacaoAuditoria:
    id: str
    regra: str
    status: str          # CONFORME | ERRO_CRITICO | ALERTA
    criticidade: str     # CRITICA | ALTA | MEDIA
    detalhe: str
    valor_encontrado: str = ""
    valor_esperado: str = ""
    origem: str = "IA"   # "DETERMINISTICO" | "IA"


@dataclass
class RelatorioAuditoria:
    resultado_global: str
    apto_para_cat: bool
    verificacoes: list[VerificacaoAuditoria] = field(default_factory=list)
    erros_criticos: list[str] = field(default_factory=list)
    recomendacao_final: str = ""
    gerado_em: str = field(default_factory=lambda: datetime.now().isoformat())


# ─────────────────────────────────────────────────────────────────────────────
# CAMADA DETERMINISTICA — Validacao Python pura, sem IA
# Garante que nenhuma regra critica de data seja ignorada por alucinacao.
# Classe isolada para facilitar testes unitarios (pytest).
# ─────────────────────────────────────────────────────────────────────────────

class DeterministicValidator:
    """
    Executa verificacoes de regra de negocio CONFEA/CREA de forma
    deterministica, sem depender de modelos de linguagem.

    Deve ser chamada ANTES do pipeline de auditoria por IA.
    Os resultados sao injetados no prompt para garantir consistencia.

    Regras implementadas:
        V03 — data_termino_periodo (Atestado) <= data_solicitacao_baixa (ART)
        V04 — data_emissao (Atestado) <= data_solicitacao_baixa (ART)
              Diferenca de +1 dia ja e ERRO_CRITICO (regra SITAC/MA)

    Exemplo de uso em testes:
        validator = DeterministicValidator(art_dict, atestado_dict)
        resultados = validator.executar()
        assert all(r.status == "CONFORME" for r in resultados)
    """

    DATE_FMT = "%d/%m/%Y"

    def __init__(self, art: dict, atestado: dict) -> None:
        self._art = art
        self._atestado = atestado
        self._resultados: list[VerificacaoAuditoria] = []

    # ── helpers ──────────────────────────────────────────────────────────────

    def _parse(self, valor: Optional[str]) -> Optional[date]:
        """Converte string DD/MM/AAAA -> date. Retorna None se invalida."""
        if not valor:
            return None
        for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(valor.strip(), fmt).date()
            except ValueError:
                continue
        return None

    def _fmt(self, d: Optional[date]) -> str:
        return d.strftime(self.DATE_FMT) if d else "data invalida ou ausente"

    def _delta_dias(self, anterior: date, posterior: date) -> int:
        """Retorna quantos dias 'posterior' ultrapassa 'anterior'. Negativo = conforme."""
        return (posterior - anterior).days

    def _adicionar(self, v: VerificacaoAuditoria) -> None:
        self._resultados.append(v)

    # ── verificacoes ─────────────────────────────────────────────────────────

    def _verificar_v03(self) -> None:
        """
        V03 — Termino do periodo do Atestado deve ser anterior ou igual
        a data de solicitacao de baixa da ART.
        """
        termino_at = self._parse(self._atestado.get("data_termino_periodo"))
        baixa_art = self._parse(self._art.get("data_solicitacao_baixa"))

        if termino_at is None or baixa_art is None:
            self._adicionar(VerificacaoAuditoria(
                id="V03",
                regra="Termino do Atestado <= Data de Baixa da ART",
                status="ALERTA",
                criticidade="ALTA",
                valor_encontrado=self._atestado.get("data_termino_periodo", "ausente"),
                valor_esperado=f"<= {self._art.get('data_solicitacao_baixa', 'ausente')}",
                detalhe=(
                    "Nao foi possivel verificar a regra V03: uma ou ambas as datas estao "
                    "ausentes ou em formato nao reconhecido. Revise os documentos originais."
                ),
                origem="DETERMINISTICO",
            ))
            return

        delta = self._delta_dias(baixa_art, termino_at)

        if delta > 0:
            self._adicionar(VerificacaoAuditoria(
                id="V03",
                regra="Termino do Atestado <= Data de Baixa da ART",
                status="ERRO_CRITICO",
                criticidade="CRITICA",
                valor_encontrado=self._fmt(termino_at),
                valor_esperado=f"<= {self._fmt(baixa_art)}",
                detalhe=(
                    f"ERRO CRITICO DE CONFORMIDADE: O periodo do Atestado termina em "
                    f"{self._fmt(termino_at)}, que e {delta} dia(s) APOS a baixa da ART "
                    f"({self._fmt(baixa_art)}). O Atestado nao pode cobrir periodo posterior "
                    f"a vigencia da ART. Resolucao CONFEA 1.025/2009, Art. 8."
                ),
                origem="DETERMINISTICO",
            ))
        else:
            self._adicionar(VerificacaoAuditoria(
                id="V03",
                regra="Termino do Atestado <= Data de Baixa da ART",
                status="CONFORME",
                criticidade="CRITICA",
                valor_encontrado=self._fmt(termino_at),
                valor_esperado=f"<= {self._fmt(baixa_art)}",
                detalhe=(
                    f"Termino do periodo do Atestado ({self._fmt(termino_at)}) e anterior "
                    f"ou igual a data de baixa da ART ({self._fmt(baixa_art)}). Conforme."
                ),
                origem="DETERMINISTICO",
            ))

    def _verificar_v04(self) -> None:
        """
        V04 — Data de emissao do Atestado deve ser anterior ou igual
        a data de solicitacao de baixa da ART.
        Diferenca de +1 dia ja configura ERRO_CRITICO (regra SITAC/MA).
        """
        emissao_at = self._parse(self._atestado.get("data_emissao"))
        baixa_art = self._parse(self._art.get("data_solicitacao_baixa"))

        if emissao_at is None or baixa_art is None:
            self._adicionar(VerificacaoAuditoria(
                id="V04",
                regra="Emissao do Atestado <= Data de Baixa da ART (+1 dia = Erro Critico)",
                status="ALERTA",
                criticidade="CRITICA",
                valor_encontrado=self._atestado.get("data_emissao", "ausente"),
                valor_esperado=f"<= {self._art.get('data_solicitacao_baixa', 'ausente')}",
                detalhe=(
                    "Nao foi possivel verificar a regra V04 de forma deterministica: "
                    "data de emissao do Atestado ou data de baixa da ART ausente/invalida. "
                    "ATENCAO: Esta e uma regra critica — diferenca de 1 dia ja causa indeferimento."
                ),
                origem="DETERMINISTICO",
            ))
            return

        delta = self._delta_dias(baixa_art, emissao_at)  # positivo = emissao APOS baixa

        if delta > 0:
            # Erro critico — qualquer numero de dias, inclusive 1
            self._adicionar(VerificacaoAuditoria(
                id="V04",
                regra="Emissao do Atestado <= Data de Baixa da ART (+1 dia = Erro Critico)",
                status="ERRO_CRITICO",
                criticidade="CRITICA",
                valor_encontrado=self._fmt(emissao_at),
                valor_esperado=f"<= {self._fmt(baixa_art)}",
                detalhe=(
                    f"ERRO CRITICO DE CONFORMIDADE: O Atestado foi emitido em "
                    f"{self._fmt(emissao_at)}, que e {delta} dia(s) POSTERIOR a data de "
                    f"solicitacao de baixa da ART ({self._fmt(baixa_art)}). "
                    f"Pelo padrao SITAC/MA, diferenca de +1 dia ja e causa de indeferimento. "
                    f"Resolucao CONFEA 1.025/2009, Art. 8."
                ),
                origem="DETERMINISTICO",
            ))
        elif delta == 0:
            self._adicionar(VerificacaoAuditoria(
                id="V04",
                regra="Emissao do Atestado <= Data de Baixa da ART (+1 dia = Erro Critico)",
                status="CONFORME",
                criticidade="CRITICA",
                valor_encontrado=self._fmt(emissao_at),
                valor_esperado=f"<= {self._fmt(baixa_art)}",
                detalhe=(
                    f"Data de emissao do Atestado ({self._fmt(emissao_at)}) e igual a data "
                    f"de baixa da ART ({self._fmt(baixa_art)}). Conforme (mesmo dia = aceito)."
                ),
                origem="DETERMINISTICO",
            ))
        else:
            # delta negativo = emissao ANTES da baixa — conforme
            self._adicionar(VerificacaoAuditoria(
                id="V04",
                regra="Emissao do Atestado <= Data de Baixa da ART (+1 dia = Erro Critico)",
                status="CONFORME",
                criticidade="CRITICA",
                valor_encontrado=self._fmt(emissao_at),
                valor_esperado=f"<= {self._fmt(baixa_art)}",
                detalhe=(
                    f"Atestado emitido em {self._fmt(emissao_at)}, anterior a data de "
                    f"baixa da ART ({self._fmt(baixa_art)}). Conforme."
                ),
                origem="DETERMINISTICO",
            ))

    # ── entry point ──────────────────────────────────────────────────────────

    def executar(self) -> list[VerificacaoAuditoria]:
        """
        Executa todas as verificacoes deterministicas e retorna a lista
        de resultados. Ordem: V03, V04.
        """
        self._resultados = []
        self._verificar_v03()
        self._verificar_v04()
        return self._resultados

    def tem_erro_critico(self) -> bool:
        return any(v.status == "ERRO_CRITICO" for v in self._resultados)

    def serializar_para_prompt(self) -> str:
        """
        Serializa os resultados deterministicos em texto estruturado
        para injecao no prompt de auditoria da IA, garantindo que o
        modelo nao contradiga as verificacoes locais.
        """
        linhas = ["PRE-VALIDACAO DETERMINISTICA (Python — nao pode ser contradita):"]
        for v in self._resultados:
            linhas.append(
                f"  [{v.id}] status={v.status} | encontrado={v.valor_encontrado} "
                f"| esperado={v.valor_esperado} | {v.detalhe}"
            )
        return "\n".join(linhas)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS — Extracao de texto
# ─────────────────────────────────────────────────────────────────────────────

def extrair_texto_de_upload(uploaded_file) -> tuple[str, bytes]:
    try:
        uploaded_file.seek(0)
    except Exception:
        pass
    raw = uploaded_file.read()

    # Tentativa 1: ZIP real ou PDF-que-e-ZIP (padrao SITAC)
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            texto = ""
            imagem_bytes = b""
            for name in z.namelist():
                low = name.lower()
                if low.endswith(".txt"):
                    raw_txt = z.read(name)
                    try:
                        texto = raw_txt.decode("utf-8")
                    except UnicodeDecodeError:
                        texto = raw_txt.decode("latin-1", errors="replace")
                if low.endswith((".jpeg", ".jpg", ".png")):
                    imagem_bytes = z.read(name)
            if texto.strip():
                return texto.strip(), imagem_bytes
            if imagem_bytes:
                return "", imagem_bytes
    except Exception:
        pass

    # Tentativa 2: PDF com texto selecionavel
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw))
        texto = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
        if texto:
            return texto, b""
    except Exception:
        pass

    return "", raw


def bytes_para_base64(b: bytes) -> str:
    return base64.standard_b64encode(b).decode("utf-8")


def ocr_via_claude(imagem_bytes: bytes, tipo_doc: str, client: anthropic.Anthropic) -> str:
    try:
        b64 = bytes_para_base64(imagem_bytes)
        mime = "image/png" if imagem_bytes[:8] == b'\x89PNG\r\n\x1a\n' else "image/jpeg"
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2048,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}},
                    {"type": "text", "text": (
                        f"Este e um documento do tipo {tipo_doc} do sistema SITAC/CREA-MA. "
                        "Transcreva todo o texto visivel na imagem, preservando labels e valores. "
                        "Retorne apenas o texto, sem comentarios."
                    )},
                ],
            }],
        )
        return resp.content[0].text
    except Exception:
        return ""


# ─────────────────────────────────────────────────────────────────────────────
# PROMPTS E LOGICA DE IA
# ─────────────────────────────────────────────────────────────────────────────

CNPJ_ESPERADO = "36.408.654/0001-04"

PROMPT_EXTRACAO = """
Voce e um analisador tecnico especialista no sistema SITAC do CREA-MA.
Analise os textos dos documentos abaixo e retorne EXCLUSIVAMENTE um objeto JSON valido.
Nao inclua markdown, nao inclua explicacoes. Somente o JSON.

TEXTO DO DOCUMENTO 1 (ART):
{texto_art}

TEXTO DO DOCUMENTO 2 (ATESTADO):
{texto_atestado}

Retorne o JSON com exatamente esta estrutura:
{{
  "art": {{
    "numero": "",
    "contratante_cnpj": "",
    "contratante_razao_social": "",
    "contrato_numero": "",
    "data_inicio": "",
    "data_termino_previsto": "",
    "data_solicitacao_baixa": "",
    "data_registro_art": "",
    "valor_contrato": 0.0,
    "atividades": [
      {{"descricao": "", "quantidade": 0.0, "unidade": ""}}
    ]
  }},
  "atestado": {{
    "emitente_cnpj": "",
    "emitente_razao_social": "",
    "contrato_numero": "",
    "art_referenciada": "",
    "data_inicio_periodo": "",
    "data_termino_periodo": "",
    "data_emissao": "",
    "atividades": [
      {{"descricao": "", "quantidade": 0.0, "unidade": ""}}
    ]
  }}
}}

Regras de parsing:
- Datas sempre no formato DD/MM/AAAA
- Para a ART, "data_solicitacao_baixa" e o campo "Data da Solicitacao" na secao de Baixa
- Valores numericos sem simbolo de moeda
"""

PROMPT_AUDITORIA = """
Voce e um auditor tecnico especialista nas regras do SITAC/MA (CREA-MA).
Com base nos dados JSON extraidos abaixo, execute a auditoria de conformidade.

CNPJ ESPERADO (obrigatorio): {cnpj_esperado}

DADOS EXTRAIDOS:
{dados_json}

ATENCAO — PRE-VALIDACAO DETERMINISTICA:
As verificacoes V03 e V04 abaixo foram calculadas de forma deterministica
por codigo Python antes de chegar a voce. Seus resultados sao definitivos
e NAO PODEM ser alterados. Reproduza-os exatamente no seu output.

{validacao_deterministica}

Agora execute as verificacoes V01, V02, V05, V06, V07 (que nao foram
pre-calculadas) e retorne SOMENTE um JSON valido sem markdown.

REGRAS RESTANTES A AUDITAR:
1. V01 - CNPJ da ART deve ser {cnpj_esperado}
2. V02 - CNPJ do Atestado deve ser {cnpj_esperado}
3. V05 - Quantitativos: quantidade e tipo de atividade devem coincidir (tolerancia zero)
4. V06 - Numero de contrato deve ser identico em ART e Atestado
5. V07 - Numero da ART referenciada no Atestado deve coincidir com o numero da ART

Inclua no array "verificacoes" TODAS as 7 verificacoes (V01-V07),
sendo V03 e V04 reproduzidos exatamente como indicado na pre-validacao.

Estrutura de retorno:
{{
  "resultado_global": "APROVADO | APROVADO COM OBSERVACAO | REPROVADO",
  "apto_para_cat": true | false,
  "verificacoes": [
    {{
      "id": "V01",
      "regra": "descricao resumida da regra",
      "status": "CONFORME | ERRO_CRITICO | ALERTA",
      "criticidade": "CRITICA | ALTA | MEDIA",
      "valor_encontrado": "valor real extraido",
      "valor_esperado": "valor esperado pela regra",
      "detalhe": "explicacao tecnica detalhada do resultado"
    }}
  ],
  "erros_criticos": ["lista de IDs com status ERRO_CRITICO"],
  "recomendacao_final": "texto com orientacao de proximos passos"
}}
"""


def chamar_claude(prompt: str, client: anthropic.Anthropic) -> str:
    mensagem = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    return mensagem.content[0].text


def extrair_json_da_resposta(texto: str) -> dict:
    try:
        limpo = texto.strip()
        if limpo.startswith("```"):
            linhas = limpo.splitlines()
            limpo = "\n".join(linhas[1:-1])
        return json.loads(limpo)
    except Exception as e:
        raise ValueError(f"Erro ao converter JSON: {e}\nResposta original:\n{texto}")


def _sobrescrever_v03_v04(
    verificacoes_ia: list[dict],
    resultados_deterministicos: list[VerificacaoAuditoria],
) -> list[dict]:
    """
    Substitui as entradas V03 e V04 retornadas pela IA pelos resultados
    deterministicos. Garante que o modelo nao possa alterar decisoes criticas.
    """
    det_por_id = {v.id: v for v in resultados_deterministicos}
    saida = []
    ids_substituidos = set()

    for v in verificacoes_ia:
        vid = v.get("id", "")
        if vid in det_por_id:
            det = det_por_id[vid]
            saida.append({
                "id": det.id,
                "regra": det.regra,
                "status": det.status,
                "criticidade": det.criticidade,
                "valor_encontrado": det.valor_encontrado,
                "valor_esperado": det.valor_esperado,
                "detalhe": det.detalhe,
                "origem": "DETERMINISTICO",
            })
            ids_substituidos.add(vid)
        else:
            v.setdefault("origem", "IA")
            saida.append(v)

    # Insere deterministicos que a IA eventualmente omitiu
    for vid, det in det_por_id.items():
        if vid not in ids_substituidos:
            saida.insert(
                next((i for i, x in enumerate(saida) if x.get("id", "") > vid), len(saida)),
                {
                    "id": det.id,
                    "regra": det.regra,
                    "status": det.status,
                    "criticidade": det.criticidade,
                    "valor_encontrado": det.valor_encontrado,
                    "valor_esperado": det.valor_esperado,
                    "detalhe": det.detalhe,
                    "origem": "DETERMINISTICO",
                },
            )

    return saida


def executar_pipeline(
    texto_art: str,
    texto_atestado: str,
    client: anthropic.Anthropic,
    status_widget,
) -> tuple[dict, dict, RelatorioAuditoria]:

    # ── Etapa 1: Extracao estruturada via IA ─────────────────────────────────
    with status_widget.status("Etapa 1 — Parsing estruturado via IA", expanded=True) as s:
        prompt_ext = PROMPT_EXTRACAO.format(
            texto_art=texto_art,
            texto_atestado=texto_atestado,
        )
        try:
            resposta_ext = chamar_claude(prompt_ext, client)
            dados = extrair_json_da_resposta(resposta_ext)
            art_dict = dados.get("art", {})
            atestado_dict = dados.get("atestado", {})
            s.update(label="Etapa 1 concluida — Dados extraidos com sucesso", state="complete")
        except Exception as e:
            s.update(label=f"Erro na extracao: {e}", state="error")
            raise

    # ── Etapa 2: Validacao deterministica (Python puro, sem IA) ─────────────
    with status_widget.status(
        "Etapa 2 — Validacao deterministica de datas (V03/V04)", expanded=True
    ) as s:
        validator = DeterministicValidator(art_dict, atestado_dict)
        resultados_deterministicos = validator.executar()
        tem_critico_local = validator.tem_erro_critico()

        ids_criticos_det = [
            v.id for v in resultados_deterministicos if v.status == "ERRO_CRITICO"
        ]

        label_det = (
            f"Etapa 2 concluida — {len(ids_criticos_det)} erro(s) critico(s) detectado(s)"
            if ids_criticos_det
            else "Etapa 2 concluida — Regras de data conformes"
        )
        s.update(label=label_det, state="complete" if not ids_criticos_det else "error")

    # ── Etapa 3: Auditoria das demais regras via IA ──────────────────────────
    with status_widget.status(
        "Etapa 3 — Auditoria de conformidade SITAC/MA (V01, V02, V05-V07)", expanded=True
    ) as s:
        prompt_aud = PROMPT_AUDITORIA.format(
            cnpj_esperado=CNPJ_ESPERADO,
            dados_json=json.dumps(dados, ensure_ascii=False, indent=2),
            validacao_deterministica=validator.serializar_para_prompt(),
        )
        try:
            resposta_aud = chamar_claude(prompt_aud, client)
            resultado_aud = extrair_json_da_resposta(resposta_aud)
            s.update(label="Etapa 3 concluida — Relatorio de auditoria gerado", state="complete")
        except Exception as e:
            s.update(label=f"Erro na auditoria: {e}", state="error")
            raise

    # ── Merge: sobrescreve V03/V04 da IA com os resultados deterministicos ──
    verificacoes_raw = _sobrescrever_v03_v04(
        resultado_aud.get("verificacoes", []),
        resultados_deterministicos,
    )

    verificacoes = [
        VerificacaoAuditoria(
            id=v.get("id", ""),
            regra=v.get("regra", ""),
            status=v.get("status", ""),
            criticidade=v.get("criticidade", ""),
            detalhe=v.get("detalhe", ""),
            valor_encontrado=v.get("valor_encontrado", ""),
            valor_esperado=v.get("valor_esperado", ""),
            origem=v.get("origem", "IA"),
        )
        for v in verificacoes_raw
    ]

    # Erros criticos = uniao de deterministicos + IA (sem duplicatas)
    erros_criticos_ia = resultado_aud.get("erros_criticos", [])
    erros_criticos_final = list(
        dict.fromkeys(ids_criticos_det + [e for e in erros_criticos_ia if e not in ids_criticos_det])
    )

    # Resultado global: se deterministico detectou critico, e sempre REPROVADO
    resultado_global = resultado_aud.get("resultado_global", "")
    if tem_critico_local and resultado_global != "REPROVADO":
        resultado_global = "REPROVADO"

    apto_cat = not bool(erros_criticos_final)

    relatorio = RelatorioAuditoria(
        resultado_global=resultado_global,
        apto_para_cat=apto_cat,
        verificacoes=verificacoes,
        erros_criticos=erros_criticos_final,
        recomendacao_final=resultado_aud.get("recomendacao_final", ""),
    )

    return art_dict, atestado_dict, relatorio


# ─────────────────────────────────────────────────────────────────────────────
# UI
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Validador SITAC/MA — CREA-MA",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@300;400;500;600;700&display=swap');

*, html, body, [class*="css"] { font-family: 'IBM Plex Sans', sans-serif; }
.block-container { padding-top: 2rem; padding-bottom: 3rem; }

.sitac-header {
    background: #0a1628;
    border: 1px solid #1c3350;
    border-radius: 12px;
    padding: 2.4rem 2.4rem 2rem;
    margin-bottom: 2rem;
    position: relative;
    overflow: hidden;
}
.sitac-header::after {
    content: "";
    position: absolute;
    right: 0; top: 0; bottom: 0;
    width: 280px;
    background: linear-gradient(90deg, transparent, rgba(14,60,110,0.4));
    pointer-events: none;
}
.sitac-badge {
    display: inline-block;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.65rem;
    font-weight: 500;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: #4a9bbe;
    border: 1px solid #1c3a55;
    background: rgba(74,155,190,0.08);
    padding: 3px 12px;
    border-radius: 3px;
    margin-bottom: 1rem;
}
.sitac-header h1 {
    color: #ddeef8;
    font-size: 1.65rem;
    font-weight: 600;
    margin: 0 0 0.4rem 0;
    letter-spacing: -0.02em;
}
.sitac-header p {
    color: #5a85a5;
    font-size: 0.82rem;
    font-family: 'IBM Plex Mono', monospace;
    margin: 0;
}
.upload-label {
    background: #0c1c30;
    border: 1px solid #1c3350;
    border-radius: 8px;
    padding: 1.2rem 1.4rem;
    margin-bottom: 0.6rem;
}
.upload-label .doc-type {
    font-size: 0.65rem;
    font-family: 'IBM Plex Mono', monospace;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: #4a7a9a;
    margin-bottom: 0.3rem;
}
.upload-label .doc-title {
    font-size: 0.95rem;
    font-weight: 600;
    color: #b8d4e8;
    margin-bottom: 0.15rem;
}
.upload-label .doc-hint {
    font-size: 0.75rem;
    color: #3a5a72;
    font-family: 'IBM Plex Mono', monospace;
}
div[data-testid="stFileUploadDropzone"] {
    background: #081422 !important;
    border: 1px dashed #1c3350 !important;
    border-radius: 6px !important;
}
.result-banner {
    border-radius: 8px;
    padding: 1.5rem 2rem;
    margin-bottom: 1.8rem;
    display: flex;
    align-items: center;
    gap: 1.4rem;
}
.result-banner.aprovado { background: #071a0f; border: 1px solid #1a4a28; }
.result-banner.reprovado { background: #180808; border: 1px solid #4a1a1a; }
.result-banner.aviso { background: #16110a; border: 1px solid #4a3a10; }
.status-indicator {
    width: 10px; height: 10px;
    border-radius: 50%;
    flex-shrink: 0;
}
.aprovado .status-indicator { background: #22c55e; box-shadow: 0 0 8px rgba(34,197,94,0.4); }
.reprovado .status-indicator { background: #ef4444; box-shadow: 0 0 8px rgba(239,68,68,0.4); }
.aviso .status-indicator { background: #f59e0b; box-shadow: 0 0 8px rgba(245,158,11,0.4); }
.status-title { font-size: 1rem; font-weight: 600; letter-spacing: 0.03em; margin-bottom: 0.2rem; }
.aprovado .status-title { color: #4ade80; }
.reprovado .status-title { color: #f87171; }
.aviso .status-title { color: #fbbf24; }
.status-sub { font-size: 0.78rem; font-family: 'IBM Plex Mono', monospace; color: #3a5a4a; }
.reprovado .status-sub { color: #5a2a2a; }
.aviso .status-sub { color: #5a4a1a; }
.secao {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.65rem;
    font-weight: 600;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: #3a5a72;
    padding-bottom: 0.6rem;
    border-bottom: 1px solid #0f2035;
    margin: 2rem 0 1rem 0;
}
.data-block {
    background: #081422;
    border: 1px solid #0f2035;
    border-radius: 8px;
    padding: 1rem 1.2rem;
}
.block-title {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.65rem;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: #3a6a8a;
    margin-bottom: 0.8rem;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid #0f2035;
}
.data-row {
    display: flex;
    gap: 0.8rem;
    padding: 0.38rem 0;
    border-bottom: 1px solid #0a1a28;
    align-items: baseline;
}
.data-row:last-child { border-bottom: none; }
.data-key {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.68rem;
    color: #3a5a72;
    min-width: 155px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    flex-shrink: 0;
}
.data-val { font-size: 0.85rem; color: #a8cce0; }
.verif-card {
    border-radius: 6px;
    padding: 0.9rem 1.1rem;
    margin-bottom: 0.6rem;
    border-left: 3px solid transparent;
}
.verif-card.conforme { background: #06120a; border-left-color: #16a34a; }
.verif-card.erro     { background: #120606; border-left-color: #dc2626; }
.verif-card.alerta   { background: #110d04; border-left-color: #d97706; }
.verif-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem; }
.verif-id { font-family: 'IBM Plex Mono', monospace; font-size: 0.65rem; color: #2a4a62; margin-right: 0.6rem; }
.verif-regra { font-size: 0.85rem; font-weight: 500; color: #a8c8e0; }
.verif-badges { display: flex; gap: 0.4rem; align-items: center; flex-shrink: 0; }
.verif-badge {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.62rem;
    font-weight: 600;
    letter-spacing: 0.08em;
    padding: 2px 9px;
    border-radius: 3px;
    white-space: nowrap;
}
.badge-conforme { background: rgba(22,163,74,0.12); color: #4ade80; border: 1px solid rgba(22,163,74,0.25); }
.badge-erro     { background: rgba(220,38,38,0.12); color: #f87171; border: 1px solid rgba(220,38,38,0.25); }
.badge-alerta   { background: rgba(217,119,6,0.12); color: #fbbf24; border: 1px solid rgba(217,119,6,0.25); }
.badge-origem-det { background: rgba(99,102,241,0.10); color: #818cf8; border: 1px solid rgba(99,102,241,0.2); font-size: 0.55rem; letter-spacing: 0.06em; }
.badge-origem-ia  { background: rgba(45,90,120,0.10); color: #4a7a9a; border: 1px solid rgba(45,90,120,0.2); font-size: 0.55rem; letter-spacing: 0.06em; }
.verif-valores { font-size: 0.76rem; font-family: 'IBM Plex Mono', monospace; color: #2a4a62; margin-bottom: 0.4rem; }
.verif-detalhe { font-size: 0.8rem; color: #6a90a8; line-height: 1.5; }
.verif-card.erro .verif-detalhe { color: #8a5050; }
</style>
""", unsafe_allow_html=True)

# HEADER
st.markdown("""
<div class="sitac-header">
  <div class="sitac-badge">CREA-MA &nbsp;&middot;&nbsp; Sistema SITAC &nbsp;&middot;&nbsp; v1.1</div>
  <h1>Validador de Acervo Tecnico</h1>
  <p>Auditoria automatica de conformidade ART x Atestado para emissao de CAT</p>
</div>
""", unsafe_allow_html=True)

# UPLOAD
col1, col2 = st.columns(2, gap="large")

with col1:
    st.markdown("""
    <div class="upload-label">
      <div class="doc-type">Documento 01</div>
      <div class="doc-title">ART — Anotacao de Responsabilidade Tecnica</div>
      <div class="doc-hint">Exportado do SITAC &nbsp;|&nbsp; .pdf ou .zip</div>
    </div>
    """, unsafe_allow_html=True)
    upload_art = st.file_uploader(
        "ART", type=["pdf", "zip"], key="art_upload", label_visibility="collapsed"
    )

with col2:
    st.markdown("""
    <div class="upload-label">
      <div class="doc-type">Documento 02</div>
      <div class="doc-title">Atestado de Capacidade Tecnica</div>
      <div class="doc-hint">Emitido pelo contratante &nbsp;|&nbsp; .pdf ou .zip</div>
    </div>
    """, unsafe_allow_html=True)
    upload_atestado = st.file_uploader(
        "Atestado", type=["pdf", "zip"], key="atestado_upload", label_visibility="collapsed"
    )

st.divider()

_, col_btn, _ = st.columns([2, 1, 2])
with col_btn:
    btn_validar = st.button(
        "Executar Validacao",
        use_container_width=True,
        type="primary",
        disabled=(upload_art is None or upload_atestado is None),
    )

if upload_art is None or upload_atestado is None:
    st.info("Carregue os dois documentos para iniciar a validacao.")
    st.stop()

# PIPELINE
if btn_validar:
    try:
        api_key = st.secrets["ANTHROPIC_API_KEY"]
    except KeyError:
        st.error("Chave ANTHROPIC_API_KEY nao configurada. Verifique o arquivo secrets.toml.")
        st.stop()

    client = anthropic.Anthropic(api_key=api_key)

    upload_art.seek(0)
    upload_atestado.seek(0)

    texto_art, img_art = extrair_texto_de_upload(upload_art)
    texto_atestado, img_atestado = extrair_texto_de_upload(upload_atestado)

    if not texto_art and img_art:
        texto_art = ocr_via_claude(img_art, "ART", client)
    if not texto_atestado and img_atestado:
        texto_atestado = ocr_via_claude(img_atestado, "Atestado", client)

    if not texto_art or not texto_atestado:
        st.error(
            "Nao foi possivel extrair texto dos arquivos. "
            "Use os arquivos baixados diretamente do SITAC/MA."
        )
        st.stop()

    status_container = st.container()

    try:
        art_dict, atestado_dict, relatorio = executar_pipeline(
            texto_art, texto_atestado, client, status_container
        )
    except Exception as ex:
        st.error(f"Falha no pipeline de analise: {ex}")
        st.stop()

    st.divider()

    # BANNER
    if relatorio.apto_para_cat and relatorio.resultado_global == "APROVADO":
        st.markdown("""
        <div class="result-banner aprovado">
          <div class="status-indicator"></div>
          <div>
            <div class="status-title">APROVADO — APTO PARA EMISSAO DE CAT</div>
            <div class="status-sub">Todos os criterios de conformidade SITAC/MA foram satisfeitos.</div>
          </div>
        </div>
        """, unsafe_allow_html=True)
    elif relatorio.erros_criticos:
        n = len(relatorio.erros_criticos)
        st.markdown(f"""
        <div class="result-banner reprovado">
          <div class="status-indicator"></div>
          <div>
            <div class="status-title">REPROVADO — NAO SUBMETER AO SITAC</div>
            <div class="status-sub">{n} erro(s) critico(s) identificado(s). Submissao resultara em indeferimento imediato.</div>
          </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div class="result-banner aviso">
          <div class="status-indicator"></div>
          <div>
            <div class="status-title">APROVADO COM RESSALVAS</div>
            <div class="status-sub">Revise os alertas antes de submeter ao SITAC/MA.</div>
          </div>
        </div>
        """, unsafe_allow_html=True)

    # DADOS EXTRAIDOS
    st.markdown('<div class="secao">Dados Extraidos dos Documentos</div>', unsafe_allow_html=True)

    def linha_dado(chave, valor):
        return (
            f'<div class="data-row">'
            f'<span class="data-key">{chave}</span>'
            f'<span class="data-val">{valor or "—"}</span>'
            f'</div>'
        )

    col_a, col_b = st.columns(2, gap="large")

    with col_a:
        rows = "".join([
            linha_dado("Numero ART", art_dict.get("numero")),
            linha_dado("CNPJ Contratante", art_dict.get("contratante_cnpj")),
            linha_dado("Razao Social", art_dict.get("contratante_razao_social")),
            linha_dado("Contrato", art_dict.get("contrato_numero")),
            linha_dado("Data Inicio", art_dict.get("data_inicio")),
            linha_dado("Termino Previsto", art_dict.get("data_termino_previsto")),
            linha_dado("Data Baixa", art_dict.get("data_solicitacao_baixa")),
        ])
        for a in art_dict.get("atividades", []):
            rows += linha_dado(
                "Atividade",
                f'{a.get("descricao","")}  {a.get("quantidade","")} {a.get("unidade","")}',
            )
        st.markdown(
            f'<div class="data-block">'
            f'<div class="block-title">ART — Anotacao de Responsabilidade Tecnica</div>'
            f'{rows}</div>',
            unsafe_allow_html=True,
        )

    with col_b:
        rows = "".join([
            linha_dado("CNPJ Emitente", atestado_dict.get("emitente_cnpj")),
            linha_dado("Razao Social", atestado_dict.get("emitente_razao_social")),
            linha_dado("Contrato", atestado_dict.get("contrato_numero")),
            linha_dado("ART Referenciada", atestado_dict.get("art_referenciada")),
            linha_dado("Periodo Inicio", atestado_dict.get("data_inicio_periodo")),
            linha_dado("Periodo Termino", atestado_dict.get("data_termino_periodo")),
            linha_dado("Data Emissao", atestado_dict.get("data_emissao")),
        ])
        for a in atestado_dict.get("atividades", []):
            rows += linha_dado(
                "Atividade",
                f'{a.get("descricao","")}  {a.get("quantidade","")} {a.get("unidade","")}',
            )
        st.markdown(
            f'<div class="data-block">'
            f'<div class="block-title">Atestado de Capacidade Tecnica</div>'
            f'{rows}</div>',
            unsafe_allow_html=True,
        )

    # VERIFICACOES
    st.markdown(
        '<div class="secao">Verificacoes de Conformidade SITAC/MA</div>',
        unsafe_allow_html=True,
    )

    for v in relatorio.verificacoes:
        if v.status == "CONFORME":
            cls, badge_cls, badge_txt = "conforme", "badge-conforme", "CONFORME"
        elif v.status == "ERRO_CRITICO":
            cls, badge_cls, badge_txt = "erro", "badge-erro", "ERRO CRITICO"
        else:
            cls, badge_cls, badge_txt = "alerta", "badge-alerta", "ALERTA"

        origem_badge_cls = (
            "badge-origem-det" if v.origem == "DETERMINISTICO" else "badge-origem-ia"
        )
        origem_label = "DETERMINISTICO" if v.origem == "DETERMINISTICO" else "IA"

        st.markdown(f"""
        <div class="verif-card {cls}">
          <div class="verif-header">
            <div>
              <span class="verif-id">{v.id}</span>
              <span class="verif-regra">{v.regra}</span>
            </div>
            <div class="verif-badges">
              <span class="verif-badge {origem_badge_cls}">{origem_label}</span>
              <span class="verif-badge {badge_cls}">{badge_txt}</span>
            </div>
          </div>
          <div class="verif-valores">
            Encontrado: {v.valor_encontrado or "—"} &nbsp;&nbsp;|&nbsp;&nbsp; Esperado: {v.valor_esperado or "—"}
          </div>
          <div class="verif-detalhe">{v.detalhe}</div>
        </div>
        """, unsafe_allow_html=True)

    # RECOMENDACAO
    if relatorio.recomendacao_final:
        st.markdown(
            '<div class="secao">Recomendacao Final</div>', unsafe_allow_html=True
        )
        st.info(relatorio.recomendacao_final)

    # EXPORT
    st.divider()
    relatorio_json = {
        "resultado_global": relatorio.resultado_global,
        "apto_para_cat": relatorio.apto_para_cat,
        "verificacoes": [asdict(v) for v in relatorio.verificacoes],
        "erros_criticos": relatorio.erros_criticos,
        "recomendacao_final": relatorio.recomendacao_final,
        "gerado_em": relatorio.gerado_em,
        "dados_extraidos": {"art": art_dict, "atestado": atestado_dict},
    }

    _, col_dl, _ = st.columns([2, 1, 2])
    with col_dl:
        st.download_button(
            "Exportar Relatorio JSON",
            data=json.dumps(relatorio_json, ensure_ascii=False, indent=2),
            file_name=f"auditoria_sitac_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            mime="application/json",
            use_container_width=True,
        )
